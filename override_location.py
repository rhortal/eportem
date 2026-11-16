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
        description="Override where you're working: pin today's location to "
                     "home/office, or mark a date range as a business trip."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("home", help="Override today's location to home.")
    subparsers.add_parser("office", help="Override today's location to office.")

    business_trip = subparsers.add_parser(
        "business-trip",
        help="Mark a date range as a business trip. ePortem check-ins run "
             "as normal (same schedule/location as any other day), but the "
             "Slack status stays 'On a business trip' for the whole range "
             "instead of the usual per-action status."
    )
    business_trip.add_argument("start", help="First business trip date, YYYY-MM-DD.")
    business_trip.add_argument("end", nargs="?", default=None,
                                help="Last business trip date, YYYY-MM-DD (inclusive). Defaults to a single day.")

    args = parser.parse_args()

    if args.command in ("home", "office"):
        override_file = state_path("location_override.txt")
        write_atomic(override_file, f"{args.command},{datetime.date.today()}")
        print(f"Location overridden to {args.command} for today ({override_file}).")
    else:
        try:
            start_date = datetime.date.fromisoformat(args.start)
            end_date = datetime.date.fromisoformat(args.end) if args.end else start_date
        except ValueError:
            parser.error("dates must be YYYY-MM-DD")
        if end_date < start_date:
            parser.error("end date must not be before start date")

        override_file = state_path("business_trip_override.txt")
        write_atomic(override_file, f"{start_date},{end_date}")

        if start_date == end_date:
            print(f"Marked {start_date} as a business trip ({override_file}).")
        else:
            print(f"Marked {start_date} to {end_date} as a business trip ({override_file}).")


if __name__ == "__main__":
    main()
