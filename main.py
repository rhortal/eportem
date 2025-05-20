#!/usr/bin/env python3
import datetime
import os
import json
from utility.env_loader import load_environment
from eportem_action import execute_action

load_environment()

def determine_location():
    """Determine the current location (from override file or config)"""
    override_file = "location_override.txt"
    if os.path.exists(override_file):
        with open(override_file, "r") as f:
            try:
                override_location, override_date = f.read().strip().split(",")
                if override_date == str(datetime.date.today()):
                    return override_location
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
