#!/usr/bin/env python3
import contextlib
import io
import sys
import time
import argparse
import datetime
import os
import re
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from utility.login_and_navigate import LOGIN_URL, create_driver, login_and_navigate
from utility.notification_send import NotificationManager, TelegramChannel, SlackChannel, _describe_error
from utility.paths import business_trip_file
from utility.env_check import check_env_variable
from utility.action_log import record_action

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
# Login form submissions over the whole run, across every _login() call: without
# it a persistent rejection is retried LOGIN_ATTEMPTS times per page reopen.
MAX_LOGINS_PER_RUN = 4
MAX_DIAGNOSTICS_PER_RUN = 3
MAX_DIAGNOSTICS_FILES = 20  # newest files kept in diagnostics/ (a set is .html + .png)
HTTP_LOG_MAX_BYTES = 1_000_000  # rotated to http_clock.log.1 beyond this

ACTIONS = ("start_day", "lunch_break", "after_lunch", "stop_day")
LOCATIONS = ("home", "office")
DIAGNOSTICS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diagnostics")

BUSINESS_TRIP_STATUS_TEXT = "On a business trip"
BUSINESS_TRIP_STATUS_EMOJI = ":airplane:"

def _active_business_trip_end_date():
    """If business_trip_override.txt (written by override_location.py
    business-trip) covers today, return its end date, else None."""
    override_file = business_trip_file()  # anchored to the repo, not the cwd
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

HTTP_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "http_clock.log")


def http_enabled_for(action_type):
    """EPORTEM_HTTP in config/.env: YES/ALL/TRUE/1 (every action), NO/FALSE/0/unset
    (none), or a comma-separated list of actions, e.g. "lunch_break,after_lunch".
    Case-insensitive; an unknown name in the list is warned about, not fatal."""
    value = os.getenv("EPORTEM_HTTP", "NO").strip()
    if value.upper() in ("YES", "ALL", "TRUE", "1"):
        return True
    if value.upper() in ("", "NO", "FALSE", "0"):
        return False
    tokens = {a.strip().lower() for a in value.split(",") if a.strip()}
    for token in sorted(tokens - set(ACTIONS)):
        print(f"WARNING: EPORTEM_HTTP lists '{token}', which is not an action "
              f"({', '.join(ACTIONS)}); ignoring it.")
    return action_type.lower() in tokens


def _env_secrets():
    return [os.getenv(k) for k in ("TELEGRAM_BOT_TOKEN", "SLACK_TOKEN", "SLACK_WEBHOOK_URL")]


class _Tee(io.TextIOBase):
    """Write to the real stdout and keep a copy, for logs/http_clock.log."""

    def __init__(self, stream):
        self.stream = stream
        self.copy = io.StringIO()

    def write(self, text):
        self.copy.write(text)
        return self.stream.write(text)

    def flush(self):
        self.stream.flush()


def _log_http_attempt(action_type, location, outcome, output=""):
    """One block per HTTP attempt in logs/http_clock.log: the outcome, then what
    the HTTP client printed (including the session-age line). Cron only mails on
    failure, so this is the record of attempts and fallbacks that ended well.
    The file holds server response excerpts, so it is private (0600, dir 0700)."""
    try:
        log_dir = os.path.dirname(HTTP_LOG)
        os.makedirs(log_dir, mode=0o700, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(log_dir, 0o700)
        with contextlib.suppress(OSError):
            if os.path.getsize(HTTP_LOG) > HTTP_LOG_MAX_BYTES:
                os.replace(HTTP_LOG, HTTP_LOG + ".1")
        fd = os.open(HTTP_LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write(f"=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} "
                    f"{action_type} {location}: {outcome}\n{output}")
        with contextlib.suppress(OSError):
            os.chmod(HTTP_LOG, 0o600)
    except OSError as e:  # never let logging hide the real result
        print(f"Could not write {HTTP_LOG}: {e}")


# Anti-forgery token values in saved pages (same pattern as utility/capture_dashboard.py).
_TOKEN_VALUE = re.compile(
    r'(name="__RequestVerificationToken"[^>]*value=")[^"]*(")', re.IGNORECASE)
_DIAGNOSTICS_NAME = re.compile(r"^\d{8}-\d{6}-.+\.(html|png)$")


class LoginBudgetExceeded(RuntimeError):
    """The run has used all its login form submissions. Deliberately not a
    WebDriverException, so the retry loops don't swallow it."""


class ActionNotApplicable(RuntimeError):
    """The dashboard shows a state in which this action would record nothing
    (or the wrong thing); nothing was clicked."""


class EPortemAction:
    def __init__(self, action_type, location="office", driver=None):
        """
        Initialize the EPortem action

        Parameters:
        - action_type: start_day, lunch_break, after_lunch, stop_day
        - location: office, home
        - driver: optional selenium webdriver instance
        """
        if action_type not in ACTIONS:
            raise ValueError(f"Unknown action_type {action_type!r}; expected one of {', '.join(ACTIONS)}")
        if location not in LOCATIONS:
            raise ValueError(f"Unknown location {location!r}; expected one of {', '.join(LOCATIONS)}")
        self.action_type = action_type
        self.location = location
        self.driver = driver
        self.logins_used = 0
        self.diagnostics_saved = 0
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
        """Record what the browser was showing, for the cron failure mail and later study.
        At most MAX_DIAGNOSTICS_PER_RUN times per run, newest MAX_DIAGNOSTICS_FILES kept."""
        if self.diagnostics_saved >= MAX_DIAGNOSTICS_PER_RUN:
            return
        self.diagnostics_saved += 1
        try:
            print(f"URL: {self.driver.current_url} Title: {self.driver.title}")
            os.makedirs(DIAGNOSTICS_DIR, mode=0o700, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            base = os.path.join(DIAGNOSTICS_DIR, f"{stamp}-{self.action_type}")
            html = _TOKEN_VALUE.sub(r"\1<redacted>\2", str(self.driver.page_source))
            fd = os.open(f"{base}.html", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(html)
            self.driver.save_screenshot(f"{base}.png")
            with contextlib.suppress(OSError):
                os.chmod(f"{base}.png", 0o600)
            print(f"Diagnostics saved to {base}.html and .png")
        except Exception as e:  # must never hide the real failure
            print(f"Could not save diagnostics: {e}")
        self._prune_diagnostics()

    @staticmethod
    def _prune_diagnostics():
        """Delete all but the newest MAX_DIAGNOSTICS_FILES saved files."""
        try:
            files = [os.path.join(DIAGNOSTICS_DIR, n) for n in os.listdir(DIAGNOSTICS_DIR)
                     if _DIAGNOSTICS_NAME.match(n)]
            files.sort(key=lambda p: (os.path.getmtime(p), p), reverse=True)
            for old in files[MAX_DIAGNOSTICS_FILES:]:
                with contextlib.suppress(OSError):
                    os.remove(old)
        except OSError:
            pass

    def _login(self):
        """Log in, retrying a few times if the site is failing. Nothing is clicked on
        the registro page here, so a retry can't record anything. Every form
        submission counts against MAX_LOGINS_PER_RUN."""
        new_browser = self.driver is None
        if new_browser:
            self.driver = create_driver()
        for attempt in range(1, LOGIN_ATTEMPTS + 1):
            if self.logins_used >= MAX_LOGINS_PER_RUN:
                print(f"Login budget spent ({MAX_LOGINS_PER_RUN} submissions this run); "
                      "not trying again so the account isn't hammered.")
                self._save_diagnostics()
                raise LoginBudgetExceeded(
                    f"gave up after {MAX_LOGINS_PER_RUN} login submissions in one run")
            self.logins_used += 1
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
            label = button.get_attribute("textContent")
            if not isinstance(label, str):
                return "unknown"
            return " ".join(label.split()) or "unknown"
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

    # For actions with no second button, the main button's label (lowercase prefix)
    # that shows the action is still possible, and the labels that clearly show it
    # isn't. Anything else (unreadable, new wording) is not blocked.
    _STATE_OK = {"start_day": "iniciar"}
    _STATE_WRONG = ("pausar", "reanudar")

    def _check_state_for_single_button(self):
        """start_day at the office has no second button: clicking the main button
        on an already-started day just opens the "Pausar" dropdown, records
        nothing, and would still notify. So refuse when the label shows that."""
        expected = self._STATE_OK.get(self.action_type)
        if not expected:
            return
        label = self._page_state()
        lowered = label.strip().lower()
        if lowered.startswith(self._STATE_WRONG):
            print(f"{self.action_type} ({self.location}) is not needed: ePortem shows "
                  f"'{label}', so the day is already started - nothing was recorded.")
            self._save_diagnostics()
            raise ActionNotApplicable(f"already started (button shows '{label}')")

    def perform(self):
        """Perform the action: over HTTP if EPORTEM_HTTP enables it for this action,
        falling back to the browser only when HTTP recorded nothing.

        Holidays, location overrides and the schedule are decided before this (in
        main.py), so they apply whichever way the action is sent."""
        check_env_variable()

        how = "http"
        if self.driver is None and http_enabled_for(self.action_type):
            from utility.http_clock import NotRecorded, OutcomeUnknown
            tee = _Tee(sys.stdout)
            try:
                with contextlib.redirect_stdout(tee):
                    self._perform_http()
                _log_http_attempt(self.action_type, self.location, "recorded over HTTP",
                                  tee.copy.getvalue())
            except NotRecorded as e:
                _log_http_attempt(self.action_type, self.location,
                                  f"not recorded, falling back to the browser: {e}",
                                  tee.copy.getvalue())
                print(f"HTTP clock recorded nothing ({e}); falling back to the browser")
                how = "browser"
                self._perform_selenium()
            except OutcomeUnknown as e:
                # Retrying could clock twice. Fail, so cron mails the output.
                _log_http_attempt(self.action_type, self.location, f"OUTCOME UNKNOWN: {e}",
                                  tee.copy.getvalue())
                raise
            except Exception as e:
                # A bug, not a known "nothing sent" case: don't guess, fail loudly.
                _log_http_attempt(self.action_type, self.location,
                                  f"ERROR, no fallback: {type(e).__name__}: {e}",
                                  tee.copy.getvalue())
                raise
        else:
            how = "browser"
            self._perform_selenium()

        # Before the follow-ups: main.py --verify-day reads this to spot missed actions
        record_action(self.action_type, self.location, how)
        self.after_action()
        return True

    def _perform_http(self):
        """Clock via a direct HTTP request; the browser is only used to log in
        when the saved session has expired (see utility/http_clock.py).
        Raises NotRecorded or OutcomeUnknown if it isn't recorded."""
        from utility.http_clock import HttpClock
        params, _ = HttpClock().clock_and_verify(self.action_type, self.location)
        print(f"HTTP clock action recorded: {params['action']} {params['_descactiv']}")

    def _perform_selenium(self):
        try:
            # Log in to ePortem
            self._login()

            # Find and click the first button
            self._ensure_button(self.selectors["button1"])
            button1 = self.driver.find_element(By.XPATH, self.selectors["button1"])
            if not self.selectors["button2"]:
                self._check_state_for_single_button()
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
        """Notifications and Slack status, once the action has been recorded.

        Never raises: the action is already recorded, and a failing follow-up must
        not turn this into a non-zero exit (cron mail, a tempting manual re-run =
        a double clock). Each part is isolated from the other."""
        failed = []
        try:
            failed += self._send_notifications()
        except Exception as e:
            print(f"Notifications failed: {_describe_error(e, *_env_secrets())}")
            failed.append("notifications")
        try:
            if self._update_slack_status() is False:
                failed.append("slack status")
        except Exception as e:
            print(f"Slack status failed: {_describe_error(e, *_env_secrets())}")
            failed.append("slack status")
        if failed:
            print("WARNING: the clock action WAS recorded, but these follow-ups failed: "
                  + ", ".join(failed))

    def _send_notifications(self):
        """Returns the names of the channels that did not deliver."""
        manager = NotificationManager()
        if os.getenv('TELEGRAM_NOTIFY') == "YES":
            manager.register_channel(TelegramChannel())
        if os.getenv('SLACK_NOTIFY') == "YES":
            manager.register_channel(SlackChannel())
        return manager.notify(self._get_message())

    def _update_slack_status(self):
        """False if setting the status failed; None when disabled or not configured."""
        if os.getenv('SLACK_STATUS', 'NO') != 'YES':
            return None
        from utility.slack_status import SlackStatusUpdater
        try:
            status_updater = SlackStatusUpdater()
        except ValueError:
            print("Slack status skipped: SLACK_TOKEN is not configured.")
            return None  # not set up is not a failure

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
        return status_updater.set_status(status_text, emoji, expiration)


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
