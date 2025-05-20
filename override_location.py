#!/usr/bin/env python3
import argparse
import os
import datetime

def main():
    parser = argparse.ArgumentParser(description="Override the location for today.")
    parser.add_argument("location", choices=["home", "office"], help="The location to override to.")
    args = parser.parse_args()

    override_file = "location_override.txt"
    with open(override_file, "w") as f:
        f.write(f"{args.location},{datetime.date.today()}")

if __name__ == "__main__":
    main()
