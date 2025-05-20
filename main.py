#!/usr/bin/env python3
import datetime
import os
import subprocess
import json
from utility.env_loader import load_environment

load_environment()

def run_script(script_name):
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), script_name)
    try:
        subprocess.run(["python3", script_path], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running {script_name}: {e}")

def main():
    now = datetime.datetime.now()
   
    hour = now.hour
    minute = now.minute

    override_file = "location_override.txt"
    location = None
    if os.path.exists(override_file):
        with open(override_file, "r") as f:
            try:
                override_location, override_date = f.read().strip().split(",")
                if override_date == str(datetime.date.today()):
                    location = override_location
            except ValueError:
                print("Invalid override file format.")

    with open("config/config.json", "r") as f:
        config = json.load(f)

    weekday_num = str(now.weekday())
    schedule = None
    if not location:
        schedule = config["schedule"].get(weekday_num)
    if schedule:
            location = schedule.get("location", "office")


    if location:
        schedule = config["schedule"].get(weekday_num)
        if schedule:
            # Set action variable to false
            action = False 
            for task, time in schedule.items():
                if task in ["location", "day"]: # Skip non-time entries
                    continue
                task_hour, task_minute = map(int, time.split(":"))
                # Allow a 15-minute window
                if abs((hour * 60 + minute) - (task_hour * 60 + task_minute)) <= 15:
                    if location == "home" and (task == "start_the_day" or task == "after_lunch_break"):
                        run_script(task + "_home.py")
                        action = True
                    else:
                        run_script(task + ".py")
                        action = True
                        return
            # If action is false
            if not action:
                print("No action scheduled for the current time.")
    else:
        print("No schedule for today.")

if __name__ == "__main__":
    main()
