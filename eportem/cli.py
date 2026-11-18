"""`python -m eportem ...` (or `eportem ...` when installed).

    config check      check the settings; exit 2 with every problem listed
    config show       the settings in effect and where each came from (secrets hidden)
    config docs       regenerate .env.example and the settings table in README.md
    config new-key    print a new secret key for EPORTEM_SECRET_KEY
    migrate           create or upgrade the database
    import-legacy     bring a person's cron set-up into the database (see eportem/legacy_import.py)
    scheduler         run the scheduler in the foreground (until Ctrl-C or SIGTERM)
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
    from eportem import contract
    return contract.main(rest)


if __name__ == "__main__":
    sys.exit(main())
