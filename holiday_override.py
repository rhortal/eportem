#!/usr/bin/env python3
import argparse
import datetime


def main():
    parser = argparse.ArgumentParser(
        description="Mark a day or date range as a holiday, so main.py skips "
                     "check-ins and Slack/Telegram notifications entirely."
    )
    parser.add_argument("start", help="First holiday date, YYYY-MM-DD (or the only date, if --end is omitted).")
    parser.add_argument("end", nargs="?", default=None,
                         help="Last holiday date, YYYY-MM-DD (inclusive). Defaults to a single-day holiday.")
    args = parser.parse_args()

    start_date = datetime.date.fromisoformat(args.start)
    end_date = datetime.date.fromisoformat(args.end) if args.end else start_date

    if end_date < start_date:
        parser.error("end date must not be before start date")

    override_file = "holiday_override.txt"
    with open(override_file, "w") as f:
        f.write(f"{start_date},{end_date}")

    if start_date == end_date:
        print(f"Marked {start_date} as a holiday.")
    else:
        print(f"Marked {start_date} to {end_date} as a holiday.")


if __name__ == "__main__":
    main()
