#!/usr/bin/env python3
"""Legacy adapter: one clock action for the account in config/.env.

The action itself (HTTP first, browser fallback, follow-ups) lives in
checkin.core.actions.ClockAction. EPortemAction fills it in from the
environment and the repository's files: EPORTEM_HTTP, the notification and
Slack settings, business_trip_override.txt, logs/actions.log,
logs/http_clock.log and diagnostics/. Settings are looked up when used, so
tests can patch them here.
"""
import argparse
import contextlib
import datetime
import io
import os
import sys

from checkin.core import actions as _core
from checkin.core.actions import (  # noqa: F401  (re-exported for the legacy scripts and tests)
    _DIAGNOSTICS_NAME,
    _TOKEN_VALUE,
    BUSINESS_TRIP_STATUS_EMOJI,
    BUSINESS_TRIP_STATUS_TEXT,
    ActionNotApplicable,
    LoginBudgetExceeded,
)
from checkin.core.overrides import parse_strict_date_range, range_state
from checkin.core.schedule import ACTIONS, LOCATIONS  # noqa: F401  (re-exported)
from utility import logfiles
from utility.action_log import record_action
from utility.env_check import check_env_variable
from utility.http_clock import ACTIVITY_IDS, SESSION_ID_HOME, SESSION_ID_OFFICE_DEFAULT  # noqa: F401
from utility.login_and_navigate import LOGIN_URL, TARGET, create_driver, login_and_navigate  # noqa: F401
from utility.notification_send import NotificationManager, SlackChannel, TelegramChannel, _describe_error  # noqa: F401
from utility.paths import business_trip_file, state_dir

REGISTRO_URL = TARGET.dashboard_url
BUTTON_WAIT_SECONDS = _core.BUTTON_WAIT_SECONDS
RETRY_BUDGET_SECONDS = _core.RETRY_BUDGET_SECONDS
RETRY_PAUSE_SECONDS = _core.RETRY_PAUSE_SECONDS
LOGIN_ATTEMPTS = _core.LOGIN_ATTEMPTS
MAX_LOGINS_PER_RUN = _core.MAX_LOGINS_PER_RUN
MAX_DIAGNOSTICS_PER_RUN = _core.MAX_DIAGNOSTICS_PER_RUN
MAX_DIAGNOSTICS_FILES = _core.MAX_DIAGNOSTICS_FILES
DIAGNOSTICS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diagnostics")


def _active_business_trip_end_date():
    """If business_trip_override.txt (written by override_location.py
    business-trip) covers today, return its end date, else None."""
    override_file = business_trip_file()  # anchored to the repo, not the cwd
    if not os.path.exists(override_file):
        return None

    with open(override_file) as f:
        try:
            start_date, end_date = parse_strict_date_range(f.read())
        except ValueError:
            print("Invalid business trip override file format.")
            return None

    state = range_state(start_date, end_date, datetime.date.today())
    if state == "past":
        os.remove(override_file)  # every date in the range has passed
        return None
    if state == "active":
        return end_date
    return None


def http_log_path():
    """logs/http_clock.log under the state dir (the repo, or EPORTEM_STATE_DIR),
    resolved per write like logs/actions.log, so tests never touch the real one."""
    return str(state_dir() / "logs" / "http_clock.log")


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


class _StdoutCapture:
    """Everything printed during the run (including by the HTTP client and the
    notification channels) is copied into the run's log block."""

    def __init__(self):
        self.tee = _Tee(sys.stdout)
        self._redirect = None

    def __enter__(self):
        self._redirect = contextlib.redirect_stdout(self.tee)
        self._redirect.__enter__()
        return self

    def __exit__(self, *exc):
        return self._redirect.__exit__(*exc)

    def write(self, text):
        self.tee.copy.write(text)

    def getvalue(self):
        return self.tee.copy.getvalue()


def _log_http_attempt(action_type, location, outcome, output=""):
    """One block per clock run in logs/http_clock.log: the outcome, then
    everything perform() printed (the HTTP attempt incl. the session-age line,
    the browser fallback, the follow-ups). Cron only mails on failure, so this
    is the record of runs that ended well. The file holds server response
    excerpts, so it is private and rotated (utility/logfiles.py)."""
    path = http_log_path()
    try:
        logfiles.append(path, f"=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} "
                                  f"{action_type} {location}: {outcome}\n{output}")
    except OSError as e:  # never let logging hide the real result
        print(f"Could not write {path}: {e}")


class _ModuleSetting:
    """A class attribute that reads this module's global of the same meaning on
    every access, so `patch("eportem_action.RETRY_PAUSE_SECONDS", 0)` still works."""

    def __init__(self, name):
        self.name = name

    def __get__(self, obj, owner=None):
        return globals()[self.name]


class EPortemAction(_core.ClockAction):
    button_wait_seconds = _ModuleSetting("BUTTON_WAIT_SECONDS")
    retry_budget_seconds = _ModuleSetting("RETRY_BUDGET_SECONDS")
    retry_pause_seconds = _ModuleSetting("RETRY_PAUSE_SECONDS")
    login_attempts = _ModuleSetting("LOGIN_ATTEMPTS")
    max_logins_per_run = _ModuleSetting("MAX_LOGINS_PER_RUN")
    max_diagnostics_per_run = _ModuleSetting("MAX_DIAGNOSTICS_PER_RUN")
    max_diagnostics_files = _ModuleSetting("MAX_DIAGNOSTICS_FILES")
    diagnostics_dir = _ModuleSetting("DIAGNOSTICS_DIR")
    failure_report = "cron mail"

    def __init__(self, action_type, location="office", driver=None):
        """
        Initialize the EPortem action

        Parameters:
        - action_type: start_day, lunch_break, after_lunch, stop_day
        - location: office, home
        - driver: optional selenium webdriver instance
        """
        super().__init__(action_type, location, driver, activity_ids=ACTIVITY_IDS, target=TARGET)

    def _new_driver(self):
        return create_driver()

    def _login_driver(self, driver):
        return login_and_navigate(driver)

    def _http_enabled(self):
        return http_enabled_for(self.action_type)

    def _new_http_clock(self):
        from utility.http_clock import HttpClock
        return HttpClock()

    def _before_perform(self):
        check_env_variable()

    def _capture(self):
        return _StdoutCapture()

    def _record(self, how):
        # main.py --verify-day reads logs/actions.log to spot missed actions
        record_action(self.action_type, self.location, how)

    def _log_run(self, outcome, output):
        _log_http_attempt(self.action_type, self.location, outcome, output)

    def _secrets(self):
        return _env_secrets()

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
        text, emoji, expiration = _core.status_for(
            self.action_type, self.location, _active_business_trip_end_date())
        return status_updater.set_status(text, emoji, expiration)


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
