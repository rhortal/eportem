#!/usr/bin/env python3
import datetime
import os
import json
from utility.env_loader import load_environment
from eportem_action import execute_action

load_environment()

HOLIDAY_STATUS_TEXT = "On holiday"
HOLIDAY_STATUS_EMOJI = ":palm_tree:"

def get_today_holiday():
    """Return {"start", "end"} if today falls within the range set via
    holiday_override.py, else None."""
    override_file = "holiday_override.txt"
    if not os.path.exists(override_file):
        return None

    with open(override_file, "r") as f:
        try:
            start_str, end_str = f.read().strip().split(",")
            start_date = datetime.date.fromisoformat(start_str)
            end_date = datetime.date.fromisoformat(end_str)
        except ValueError:
            print("Invalid holiday override file format.")
            return None

    today = datetime.date.today()
    if end_date < today:
        os.remove(override_file)  # every date in the range has passed
        return None
    if start_date <= today:
        return {"start": start_date, "end": end_date}
    return None

def is_holiday():
    """Check whether today falls within a holiday range set via holiday_override.py"""
    return get_today_holiday() is not None

def update_holiday_slack_status(holiday):
    """Set the Slack status for today's holiday, if SLACK_STATUS is enabled.
    Safe to call on every run - it's just an idempotent status update, not a
    one-time notification."""
    if os.getenv('SLACK_STATUS', 'NO') != 'YES':
        return

    expiration = int(datetime.datetime.combine(holiday["end"], datetime.time(23, 59)).timestamp())

    from utility.slack_status import SlackStatusUpdater
    SlackStatusUpdater().set_status(HOLIDAY_STATUS_TEXT, HOLIDAY_STATUS_EMOJI, expiration)

def determine_location():
    """Determine the current location (from override file or config)"""
    override_file = "location_override.txt"
    if os.path.exists(override_file):
        with open(override_file, "r") as f:
            try:
                override_location, override_date = f.read().strip().split(",")
                today = str(datetime.date.today())
                if override_date == today:
                    return override_location
                if override_date < today:
                    os.remove(override_file)  # the day has passed
            except ValueError:
                print("Invalid override file format.")
    
    # Get from config
    with open("config/config.json", "r") as f:
        config = json.load(f)
        weekday_num = str(datetime.datetime.now().weekday())
        schedule = config["schedule"].get(weekday_num)
        if schedule:
            return schedule.get("location", "office")
            
    return "office"  # Default to office if not specified

def main():
    holiday = get_today_holiday()
    if holiday:
        print("On holiday today - skipping check-in.")
        update_holiday_slack_status(holiday)
        return

    now = datetime.datetime.now()
    hour = now.hour
    minute = now.minute

    # Get location (from override or config)
    location = determine_location()
    
    # Get today's schedule
    weekday_num = str(now.weekday())
    with open("config/config.json", "r") as f:
        config = json.load(f)
        
    schedule = config["schedule"].get(weekday_num)
    if not schedule:
        print("No schedule for today.")
        return
        
    # Check if any action should be performed based on current time
    action_performed = False
    for task, time_str in schedule.items():
        if task in ["location", "day"]:  # Skip non-time entries
            continue
            
        task_hour, task_minute = map(int, time_str.split(":"))
        
        # Allow a 15-minute window
        if abs((hour * 60 + minute) - (task_hour * 60 + task_minute)) <= 15:
            # Map task names to action types
            action_types = {
                "start_the_day": "start_day",
                "lunch_break": "lunch_break",
                "after_lunch_break": "after_lunch",
                "stop_the_day": "stop_day"
            }
            
            # Create and perform the action
            execute_action(action_types[task], location)
            action_performed = True
            break
            
    if not action_performed:
        print("No action scheduled for the current time.")

if __name__ == "__main__":
    main()
