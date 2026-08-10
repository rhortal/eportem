#!/usr/bin/env python3
import argparse
import datetime


def main():
    parser = argparse.ArgumentParser(
        description="Mark a day or date range as a holiday or business trip, so "
                     "main.py skips check-ins/notifications and (if SLACK_STATUS=YES) "
                     "sets a matching Slack status for the duration."
    )
    parser.add_argument("start", help="First date, YYYY-MM-DD (or the only date, if --end is omitted).")
    parser.add_argument("end", nargs="?", default=None,
                         help="Last date, YYYY-MM-DD (inclusive). Defaults to a single day.")
    parser.add_argument("--type", choices=["holiday", "business_trip"], default="holiday",
                         help="Type of absence (default: holiday). Controls the Slack status text/emoji.")
    args = parser.parse_args()

    start_date = datetime.date.fromisoformat(args.start)
    end_date = datetime.date.fromisoformat(args.end) if args.end else start_date

    if end_date < start_date:
        parser.error("end date must not be before start date")

    override_file = "holiday_override.txt"
    with open(override_file, "w") as f:
        f.write(f"{start_date},{end_date},{args.type}")

    label = "business trip" if args.type == "business_trip" else "holiday"
    if start_date == end_date:
        print(f"Marked {start_date} as a {label}.")
    else:
        print(f"Marked {start_date} to {end_date} as a {label}.")


if __name__ == "__main__":
    main()
