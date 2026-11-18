"""`python -m eportem ...` (or `eportem ...` when installed).

    config check      check the settings; exit 2 with every problem listed
    config show       the settings in effect and where each came from (secrets hidden)
    config docs       regenerate .env.example and the settings table in README.md
    config new-key    print a new secret key for EPORTEM_SECRET_KEY
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


def main(argv=None):
    parser = argparse.ArgumentParser(prog="eportem", description="ePortem service commands.")
    sub = parser.add_subparsers(dest="command", required=True)
    config = sub.add_parser("config", help="settings")
    config.add_argument("action", choices=["check", "show", "docs", "new-key"])
    sub.add_parser("check-contract", help="read-only check of the real site", add_help=False)
    args, rest = parser.parse_known_args(argv)
    if args.command == "config":
        if rest:
            parser.error(f"unrecognized arguments: {' '.join(rest)}")
        return _config(args)
    from eportem import contract
    return contract.main(rest)


if __name__ == "__main__":
    sys.exit(main())
