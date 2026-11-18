"""`python -m eportem ...` (or `eportem ...` when installed).

    config check      check the settings; exit 2 with every problem listed
    config show       the settings in effect and where each came from (secrets hidden)
    config docs       regenerate .env.example and the settings table in README.md
    config new-key    print a new secret key for EPORTEM_SECRET_KEY
    migrate           create or upgrade the database
    import-legacy     bring a person's cron set-up into the database (see eportem/legacy_import.py)
    scheduler         run the scheduler in the foreground (until Ctrl-C or SIGTERM)
    serve             run the web app, API and scheduler (what the container runs)
    create-admin      create an admin (password from EPORTEM_NEW_PASSWORD or a prompt)
    create-token      create a personal access token for a person and print it once
    check-contract    read-only check of the real site (see eportem/contract.py)
"""
import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TABLE_START, TABLE_END = "<!-- settings-table:start -->", "<!-- settings-table:end -->"


def _config(args):
    from eportem import settings as s
    if args.action == "new-key":
        from cryptography.fernet import Fernet
        print(Fernet.generate_key().decode())
        return 0
    if args.action == "docs":
        (REPO / ".env.example").write_text(s.env_example() + "\n")
        readme = REPO / "README.md"
        text = readme.read_text()
        block = f"{TABLE_START}\n{s.markdown_table()}\n{TABLE_END}"
        new, n = re.subn(re.escape(TABLE_START) + ".*?" + re.escape(TABLE_END), lambda m: block, text,
                         flags=re.DOTALL)
        if n != 1:
            print(f"README.md needs exactly one {TABLE_START} ... {TABLE_END} block", file=sys.stderr)
            return 1
        readme.write_text(new)
        print("Wrote .env.example and the settings table in README.md")
        return 0
    try:
        loaded = s.load_settings()
    except s.SettingsError as e:
        print("Invalid settings:", file=sys.stderr)
        for p in e.problems:
            print(f"  - {p}", file=sys.stderr)
        return 2
    if args.action == "show":
        rows = s.describe(loaded)
        width = max(len(r[0]) for r in rows)
        for name, value, source in rows:
            print(f"{name:<{width}}  {value}  [{source}]")
    else:
        print("Settings OK.")
    return 0


def _load_settings_or_exit():
    from eportem import settings as s
    try:
        return s.load_settings()
    except s.SettingsError as e:
        print("Invalid settings:", file=sys.stderr)
        for p in e.problems:
            print(f"  - {p}", file=sys.stderr)
        return None


def _migrate(args):
    from eportem.db.engine import migrate
    settings = _load_settings_or_exit()
    if settings is None:
        return 2
    migrate(settings.effective_database_url)
    print("Database is up to date.")
    return 0


def _import_legacy(args):
    from eportem.db.crypto import SecretBox
    from eportem.db.engine import make_engine, make_sessionmaker
    from eportem.legacy_import import ImportError_, import_legacy
    settings = _load_settings_or_exit()
    if settings is None:
        return 2
    engine = make_engine(settings.effective_database_url)
    with make_sessionmaker(engine)() as db:
        try:
            report = import_legacy(db, settings, SecretBox.from_settings(settings), args.source,
                                   args.user, args.email)
        except ImportError_ as e:
            db.rollback()
            print("Nothing imported:", file=sys.stderr)
            for p in e.problems:
                print(f"  - {p}", file=sys.stderr)
            return 2
        for line in report.lines:
            print(f"  {line}")
        if args.dry_run:
            db.rollback()
            print("Dry run: nothing was saved.")
        else:
            db.commit()
            print("Imported.")
    return 0


def _scheduler(args):
    import logging
    import signal

    from eportem.db.crypto import SecretBox
    from eportem.db.engine import make_engine, make_sessionmaker, migrate
    from eportem.scheduler.runner import Engine
    from eportem.scheduler.scheduler import Scheduler
    settings = _load_settings_or_exit()
    if settings is None:
        return 2
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    migrate(settings.effective_database_url)
    sessionmaker = make_sessionmaker(make_engine(settings.effective_database_url))
    sched = Scheduler(settings, sessionmaker, SecretBox.from_settings(settings), Engine(settings))
    signal.signal(signal.SIGTERM, lambda *_: sched.stop())
    print(f"Scheduler running against {settings.target_url}"
          + (" (DRY RUN: nothing is sent)" if settings.dry_run else "") + "; Ctrl-C to stop.")
    try:
        sched.run_forever()
    except KeyboardInterrupt:
        sched.stop()
    return 0


def _db(settings):
    from eportem.db.engine import make_engine, make_sessionmaker, migrate
    migrate(settings.effective_database_url)
    return make_sessionmaker(make_engine(settings.effective_database_url))


def _serve(args):
    import uvicorn

    from eportem.web.app import create_app
    settings = _load_settings_or_exit()
    if settings is None:
        return 2
    app = create_app(settings, _db(settings), start_scheduler=True)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower(),
                proxy_headers=bool(settings.trusted_proxies),
                forwarded_allow_ips=",".join(settings.trusted_proxies) or None)
    return 0


def _create_admin(args):
    import getpass
    import os

    from eportem import service
    settings = _load_settings_or_exit()
    if settings is None:
        return 2
    password = os.environ.get("EPORTEM_NEW_PASSWORD") or getpass.getpass("Password for the new admin: ")
    with _db(settings).begin() as db:
        try:
            service.create_user(db, settings, "command line", args.username, password, args.email, role="admin")
        except service.ServiceError as e:
            print("Not created: " + "; ".join(e.problems), file=sys.stderr)
            return 2
    print(f"Admin {args.username} created.")
    return 0


def _create_token(args):
    from sqlalchemy import select

    from eportem import auth
    from eportem.db.models import User
    settings = _load_settings_or_exit()
    if settings is None:
        return 2
    with _db(settings).begin() as db:
        user = db.scalar(select(User).where(User.username == args.user))
        if user is None:
            print(f"No user {args.user}", file=sys.stderr)
            return 2
        try:
            row, token = auth.create_token(db, user, args.name, args.scopes.split(","),
                                           auth.expires_in(args.expires_in_days))
        except ValueError as e:
            print(f"Not created: {e}", file=sys.stderr)
            return 2
        auth.audit(db, user.id, "command line", "token.create", prefix=row.prefix, scopes=row.scopes)
    print(token)
    print("Store it now: it is not shown again.", file=sys.stderr)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="eportem", description="ePortem service commands.")
    sub = parser.add_subparsers(dest="command", required=True)
    config = sub.add_parser("config", help="settings")
    config.add_argument("action", choices=["check", "show", "docs", "new-key"])
    sub.add_parser("migrate", help="create or upgrade the database")
    imp = sub.add_parser("import-legacy", help="import a person's cron set-up")
    imp.add_argument("--user", required=True, help="the person's username in the service")
    imp.add_argument("--email")
    imp.add_argument("--from", dest="source", default=str(REPO), help="the cron checkout (default: this one)")
    imp.add_argument("--dry-run", action="store_true")
    sub.add_parser("scheduler", help="run the scheduler in the foreground")
    sub.add_parser("serve", help="run the web app, API and scheduler")
    adm = sub.add_parser("create-admin", help="create an admin")
    adm.add_argument("username")
    adm.add_argument("--email")
    tok = sub.add_parser("create-token", help="create a personal access token")
    tok.add_argument("user")
    tok.add_argument("--name", default="command line")
    tok.add_argument("--scopes", default="read,write")
    tok.add_argument("--expires-in-days", type=int)
    sub.add_parser("check-contract", help="read-only check of the real site", add_help=False)
    args, rest = parser.parse_known_args(argv)
    if args.command != "check-contract" and rest:
        parser.error(f"unrecognized arguments: {' '.join(rest)}")
    if args.command == "config":
        return _config(args)
    if args.command == "migrate":
        return _migrate(args)
    if args.command == "import-legacy":
        return _import_legacy(args)
    if args.command == "scheduler":
        return _scheduler(args)
    if args.command == "serve":
        return _serve(args)
    if args.command == "create-admin":
        return _create_admin(args)
    if args.command == "create-token":
        return _create_token(args)
    from eportem import contract
    return contract.main(rest)


if __name__ == "__main__":
    sys.exit(main())
