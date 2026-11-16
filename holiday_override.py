#!/usr/bin/env python3
import argparse
import datetime
import os
import tempfile
from pathlib import Path


def state_path(name):
    # Same location as utility.paths (main.py reads it from there), duplicated
    # here so this script keeps working with the system python3, without the
    # venv's packages.
    return Path(os.environ.get("EPORTEM_STATE_DIR") or Path(__file__).resolve().parent) / name


def write_atomic(path, text):
    """Write via a temp file + rename so main.py never reads a half-written file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Mark a day or date range as a holiday, so main.py skips "
                     "check-ins and Slack/Telegram notifications entirely, and "
                     "(if SLACK_STATUS=YES) sets an 'On holiday' Slack status "
                     "for the duration."
    )
    parser.add_argument("start", help="First holiday date, YYYY-MM-DD (or the only date, if --end is omitted).")
    parser.add_argument("end", nargs="?", default=None,
                         help="Last holiday date, YYYY-MM-DD (inclusive). Defaults to a single-day holiday.")
    args = parser.parse_args()

    try:
        start_date = datetime.date.fromisoformat(args.start)
        end_date = datetime.date.fromisoformat(args.end) if args.end else start_date
    except ValueError:
        parser.error("dates must be YYYY-MM-DD")

    if end_date < start_date:
        parser.error("end date must not be before start date")

    override_file = state_path("holiday_override.txt")
    write_atomic(override_file, f"{start_date},{end_date}")

    if start_date == end_date:
        print(f"Marked {start_date} as a holiday ({override_file}).")
    else:
        print(f"Marked {start_date} to {end_date} as a holiday ({override_file}).")


if __name__ == "__main__":
    main()
