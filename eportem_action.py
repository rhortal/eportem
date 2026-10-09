#!/usr/bin/env python3
import time
import argparse
import datetime
import os
from selenium.webdriver.common.by import By
from utility.login_and_navigate import login_and_navigate
from utility.notification_send import NotificationManager, TelegramChannel, SlackChannel
from utility.env_check import check_env_variable

# ePortem session-type IDs used in the "start"/"resume" button selectors below.
# These are specific to this account's ePortem configuration, not a fixed
# platform constant - if ePortem ever renumbers session types, update here.
SESSION_ID_HOME = "1293"
SESSION_ID_OFFICE_DEFAULT = "1"

BUSINESS_TRIP_STATUS_TEXT = "On a business trip"
BUSINESS_TRIP_STATUS_EMOJI = ":airplane:"

def _active_business_trip_end_date():
    """If business_trip_override.txt (written by override_location.py
    business-trip) covers today, return its end date, else None."""
    override_file = "business_trip_override.txt"
    if not os.path.exists(override_file):
        return None

    with open(override_file, "r") as f:
        try:
            start_str, end_str = f.read().strip().split(",")
            start_date = datetime.date.fromisoformat(start_str)
            end_date = datetime.date.fromisoformat(end_str)
        except ValueError:
            print("Invalid business trip override file format.")
            return None

    today = datetime.date.today()
    if end_date < today:
        os.remove(override_file)  # every date in the range has passed
        return None
    if start_date <= today:
        return end_date
    return None

class EPortemAction:
    def __init__(self, action_type, location="office", driver=None):
        """
        Initialize the EPortem action

        Parameters:
        - action_type: start_day, lunch_break, after_lunch, stop_day
        - location: office, home
        - driver: optional selenium webdriver instance
        """
        self.action_type = action_type
        self.location = location
        self.driver = driver
        self.selectors = self._get_selectors()

    def _get_selectors(self):
        """Return appropriate selectors based on action type and location"""
        selectors = {
            "start_day": {
                "office": {
                    "button1": "//*[@id=\"buttonsRegBox\"]/div/div/button",
                    "button2": None
                },
                "home": {
                    "button1": "//*[@id=\"buttonsRegBox\"]/div/button[@data-toggle=\"dropdown\"]",
                    "button2": f"//*[@id=\"_ststart\" and @name=\"{SESSION_ID_HOME}\"]"
                }
            },
            "lunch_break": {
                "office": {
                    "button1": "//*[@id=\"buttonsRegBox\"]/div/div/button",
                    "button2": "//*[@id=\"_stpause\"]"
                },
                "home": {
                    "button1": "//*[@id=\"buttonsRegBox\"]/div/div/button",
                    "button2": "//*[@id=\"_stpause\"]"
                }
            },
            "after_lunch": {
                "office": {
                    "button1": "//*[@id=\"buttonsRegBox\"]/div/div/button/div/div[2]/h2",
                    "button2": f"//a[@id=\"_stini\" and @name=\"{SESSION_ID_OFFICE_DEFAULT}\"]"
                },
                "home": {
                    "button1": "//*[@id=\"buttonsRegBox\"]/div/div/button/div/div[2]/h2",
                    "button2": f"//a[@id=\"_stini\" and @name=\"{SESSION_ID_HOME}\"]"
                }
            },
            "stop_day": {
                "office": {
                    "button1": "//*[@id=\"buttonsRegBox\"]/div/div/button",
                    "button2": "//*[@id=\"_ststop\"]"
                },
                "home": {
                    "button1": "//*[@id=\"buttonsRegBox\"]/div/div/button",
                    "button2": "//*[@id=\"_ststop\"]"
                }
            }
        }
        return selectors.get(self.action_type, {}).get(self.location, {})

    def _get_message(self):
        """Return the appropriate notification message"""
        messages = {
            "start_day": f"RePortemed at {self.location}",
            "lunch_break": "RePortemed going to lunch break",
            "after_lunch": "RePortemed back from lunch break",
            "stop_day": "RePortemed done for the day"
        }
        return messages.get(self.action_type, "RePortem action completed")

    def perform(self):
        """Perform the action"""
        check_env_variable()

        # Log in to ePortem
        self.driver = login_and_navigate(self.driver)

        try:
            # Find and click the first button
            button1 = self.driver.find_element(By.XPATH, self.selectors["button1"])
            print("Clicking button 1")
            button1.click()

            # Click the second button if needed
            if self.selectors["button2"]:
                time.sleep(1)  # Small delay to ensure dropdown is visible
                button2 = self.driver.find_element(By.XPATH, self.selectors["button2"])
                print("Clicking button 2")
                button2.click()

            time.sleep(3)
        finally:
            # Close the browser window
            self.driver.quit()

        manager = NotificationManager()
        if os.getenv('TELEGRAM_NOTIFY') == "YES":
            manager.register_channel(TelegramChannel())
        if os.getenv('SLACK_NOTIFY') == "YES":
            manager.register_channel(SlackChannel())
        manager.notify(self._get_message())

        # Slack status update
        if os.getenv('SLACK_STATUS', 'NO') == 'YES':
            from utility.slack_status import SlackStatusUpdater
            status_updater = SlackStatusUpdater()

            trip_end_date = _active_business_trip_end_date()
            if trip_end_date:
                # On a business trip, every check-in (including stop_day)
                # keeps the same status instead of reverting to "Done for
                # the day" - it only changes once the trip range ends.
                status_text = BUSINESS_TRIP_STATUS_TEXT
                emoji = BUSINESS_TRIP_STATUS_EMOJI
                expiration = int(datetime.datetime.combine(trip_end_date, datetime.time(23, 59)).timestamp())
            elif self.action_type == "start_day":
                status_text = f"Working at {self.location}"
                emoji = ":house:" if self.location == "home" else ":office:"
                expiration = 0
            elif self.action_type == "lunch_break":
                status_text = "Away for lunch"
                emoji = ":fork_and_knife:"
                expiration = 0
            elif self.action_type == "after_lunch":
                status_text = f"Working at {self.location}"
                emoji = ":house:" if self.location == "home" else ":office:"
                expiration = 0
            elif self.action_type == "stop_day":
                status_text = "Done for the day"
                emoji = ":palm_tree:"
                expiration = 0
            else:
                status_text = "Working"
                emoji = ":computer:"
                expiration = 0
            status_updater.set_status(status_text, emoji, expiration)

        return True


def execute_action(action_type, location="office"):
    """Helper function to execute an action with proper setup"""
    action = EPortemAction(action_type, location)
    return action.perform()


def run_fixed_action(action_type, description):
    """CLI entrypoint shared by start_day.py, lunch_break_unified.py, after_lunch.py
    and stop_day.py, each of which pins action_type and only needs to parse
    --location."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--location", choices=["home", "office"], default="office",
                      help="Location (home or office)")
    args = parser.parse_args()

    check_env_variable()
    execute_action(action_type, args.location)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Execute ePortem actions.")
    parser.add_argument("action", choices=["start_day", "lunch_break", "after_lunch", "stop_day", "help"],
                      help="The action to perform")
    parser.add_argument("--location", choices=["home", "office"], default="office",
                      help="Location (home or office)")
    args = parser.parse_args()

    if args.action == "help":
        print(
            "\nUSAGE EXAMPLES:\n"
            "  python3 eportem_action.py start_day --location office\n"
            "  python3 eportem_action.py start_day --location home\n"
            "  python3 eportem_action.py lunch_break --location office\n"
            "  python3 eportem_action.py lunch_break --location home\n"
            "  python3 eportem_action.py after_lunch --location office\n"
            "  python3 eportem_action.py after_lunch --location home\n"
            "  python3 eportem_action.py stop_day --location office\n"
            "  python3 eportem_action.py stop_day --location home\n"
            "\n"
            "ACTIONS:\n"
            "  start_day, lunch_break, after_lunch, stop_day\n"
            "  (use --location to specify 'office' or 'home')\n"
        )
    else:
        execute_action(args.action, args.location)
