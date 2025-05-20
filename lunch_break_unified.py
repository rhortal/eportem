#!/usr/bin/env python3
import argparse
from eportem_action import execute_action
from utility.env_check import check_env_variable

# Check if we should run
check_env_variable()

def main():
    parser = argparse.ArgumentParser(description="Lunch break script.")
    parser.add_argument("--location", choices=["home", "office"], default="office", 
                      help="Location (home or office)")
    parser.add_argument("--mock", action="store_true", help="Run with a mock driver.")
    args = parser.parse_args()
    
    execute_action("lunch_break", args.location, args.mock)

if __name__ == "__main__":
    main()