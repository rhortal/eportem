#!/usr/bin/env python3
import time
import argparse
import datetime
import os
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from utility.login_and_navigate import LOGIN_URL, create_driver, login_and_navigate
from utility.notification_send import NotificationManager, TelegramChannel, SlackChannel
from utility.env_check import check_env_variable

# ePortem session-type IDs used in the "start"/"resume" button selectors below.
# These are specific to this account's ePortem configuration, not a fixed
# platform constant - if ePortem ever renumbers session types, update here.
SESSION_ID_HOME = "1293"
SESSION_ID_OFFICE_DEFAULT = "1"

REGISTRO_URL = "https://eportem.es/aplicaciones/e-portem/registro/"
BUTTON_WAIT_SECONDS = 30
# ePortem has short server outages (500 pages from database timeouts, 2026-11-05).
# Keep reopening the page for this long before giving up; nothing has been clicked yet.
RETRY_BUDGET_SECONDS = 600
RETRY_PAUSE_SECONDS = 60
LOGIN_ATTEMPTS = 3  # kept low so a rejected login can't hammer the account
DIAGNOSTICS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diagnostics")

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

    def _button_appears(self, xpath):
        """Wait for a button without clicking it; True if it showed up in time."""
        try:
            WebDriverWait(self.driver, BUTTON_WAIT_SECONDS).until(
                lambda d: d.find_elements(By.XPATH, xpath))
            return True
        except WebDriverException:  # includes the wait's TimeoutException
            return False

    def _save_diagnostics(self):
        """Record what the browser was showing, for the cron failure mail and later study."""
        try:
            print(f"URL: {self.driver.current_url} Title: {self.driver.title}")
            os.makedirs(DIAGNOSTICS_DIR, mode=0o700, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            base = os.path.join(DIAGNOSTICS_DIR, f"{stamp}-{self.action_type}")
            with open(f"{base}.html", "w") as f:
                f.write(self.driver.page_source)
            self.driver.save_screenshot(f"{base}.png")
            print(f"Diagnostics saved to {base}.html and .png")
        except Exception as e:  # must never hide the real failure
            print(f"Could not save diagnostics: {e}")

    def _login(self):
        """Log in, retrying a few times if the site is failing. Nothing is clicked on
        the registro page here, so a retry can't record anything."""
        new_browser = self.driver is None
        if new_browser:
            self.driver = create_driver()
        for attempt in range(1, LOGIN_ATTEMPTS + 1):
            try:
                if new_browser or attempt > 1:
                    self.driver.get(LOGIN_URL)
                self.driver = login_and_navigate(self.driver)
                return
            except WebDriverException as e:
                print(f"Login attempt {attempt} of {LOGIN_ATTEMPTS} failed: {type(e).__name__}")
                if attempt == LOGIN_ATTEMPTS:
                    self._save_diagnostics()
                    raise
                time.sleep(RETRY_PAUSE_SECONDS)

    def _ensure_button(self, xpath):
        """Give the first button time to appear, reopening the page until
        RETRY_BUDGET_SECONDS have passed and logging in again if the session was lost.
        Clicks nothing, so a retry can't record anything twice. If it is still missing,
        save diagnostics and let the caller's find_element raise as usual."""
        deadline = time.monotonic() + RETRY_BUDGET_SECONDS
        while not self._button_appears(xpath):
            if time.monotonic() >= deadline:
                print(f"Button not found after {RETRY_BUDGET_SECONDS}s of retries")
                self._save_diagnostics()
                return
            print(f"{datetime.datetime.now():%H:%M:%S} Button not found, "
                  f"reopening the page in {RETRY_PAUSE_SECONDS}s")
            time.sleep(RETRY_PAUSE_SECONDS)
            try:
                self.driver.get(REGISTRO_URL)
                if "/Usuario/Login" in self.driver.current_url:
                    print("Session lost, logging in again")
                    self._login()
            except WebDriverException as e:
                print(f"Reopening failed: {type(e).__name__}")

    def _page_state(self):
        """The label on ePortem's main button (Iniciar, Pausar, Reanudar), for messages."""
        try:
            button = self.driver.find_element(By.XPATH, "//*[@id=\"buttonsRegBox\"]//button")
            return " ".join(button.get_attribute("textContent").split())
        except WebDriverException:
            return "unknown"

    def _report_missing_option(self):
        """The dropdown doesn't offer this action. Opening it records nothing, so say so."""
        print(f"{self.action_type} ({self.location}) is not available: ePortem shows "
              f"'{self._page_state()}' and doesn't offer this option. Nothing was recorded.")
        if self.action_type == "after_lunch":
            print("There is no lunch break to resume, so the lunch_break run probably failed "
                  "(look for its cron mail). Correct the day in Registro Jornada > Detalle registro.")
        self._save_diagnostics()

    def perform(self):
        """Perform the action"""
        check_env_variable()

        if os.getenv('EPORTEM_HTTP', 'NO') == 'YES' and self.driver is None:
            self._perform_http()
        else:
            self._perform_selenium()

        self.after_action()
        return True

    def _perform_http(self):
        """Clock via a direct HTTP request; the browser is only used to log in
        when the saved session has expired (see utility/http_clock.py)."""
        from utility.http_clock import HttpClock
        params, result = HttpClock().clock(self.action_type, self.location, send=True)
        print(f"HTTP clock action sent: {params['action']} {params['_descactiv']}")

    def _perform_selenium(self):
        try:
            # Log in to ePortem
            self._login()

            # Find and click the first button
            self._ensure_button(self.selectors["button1"])
            button1 = self.driver.find_element(By.XPATH, self.selectors["button1"])
            print("Clicking button 1")
            button1.click()

            # Click the second button if needed
            if self.selectors["button2"]:
                time.sleep(1)  # Small delay to ensure dropdown is visible
                try:
                    button2 = self.driver.find_element(By.XPATH, self.selectors["button2"])
                except NoSuchElementException:
                    self._report_missing_option()
                    raise
                print("Clicking button 2")
                button2.click()

            time.sleep(3)
        finally:
            # Close the browser window
            if self.driver:
                self.driver.quit()

    def after_action(self):
        """Notifications and Slack status, once the action has been recorded."""
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
