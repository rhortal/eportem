#!/usr/bin/env python3
"""Legacy adapter: the HTTP clock for the account in config/.env.

The client lives in eportem.core.clock_http. This module gives it the owner's
activity IDs, the cookie file config/.session_cookies.json (chmod 600,
gitignored) and the browser login from utility/login_and_navigate, all looked
up when used so tests can patch them here.

Normal runs don't call this module directly: main.py decides the action,
location and holidays, and EPortemAction.perform() calls
HttpClock.clock_and_verify(), falling back to Selenium only on NotRecorded.

CLI, for testing by hand (dry run by default - prints the request without sending it).
It skips main.py's holiday, location-override and schedule checks:
    python3 -m utility.http_clock lunch_break --location office
    python3 -m utility.http_clock lunch_break --location office --send --notify
"""
import argparse
import json
import os  # noqa: F401  (tests patch utility.http_clock.os.replace)
import sys
import time  # noqa: F401
from pathlib import Path

from eportem.core import clock_http as _core
from eportem.core.activities import ActivityIds
from eportem.core.clock_http import (  # noqa: F401  (re-exported for the legacy scripts and tests)
    CLOCK_IDS,
    DASHBOARD_MARKER,
    RESULT_KEYS,
    ButtonNotFound,
    DashboardUnreadable,
    NotRecorded,
    OutcomeUnknown,
    SessionExpired,
    UnexpectedResponse,
    build_params,
    parse_buttons,
)
from eportem.core.clock_http import send_never_reached_server as _send_never_reached_server  # noqa: F401
from eportem.core.cookies import FileCookieStore

# Same browser identity the Selenium login uses, so the session looks consistent.
from utility.login_and_navigate import (  # noqa: F401  (re-exported)
    LOGIN_URL,
    TARGET,
    USER_AGENT,
    create_driver,
    login_and_navigate,
)

BASE_URL = TARGET.base_url
DASHBOARD_URL = TARGET.dashboard_url
CLOCK_URL = TARGET.clock_url
COOKIE_FILE = Path(__file__).parent.parent / "config" / ".session_cookies.json"

# Looked up per use, so tests can set them to 0.
VERIFY_ATTEMPTS = _core.VERIFY_ATTEMPTS
VERIFY_PAUSE_SECONDS = _core.VERIFY_PAUSE_SECONDS

# This account's ePortem activity IDs (see eportem/core/activities.py).
SESSION_ID_HOME = "1293"
SESSION_ID_OFFICE_DEFAULT = "1"
LUNCH_PAUSE_ID = "2"  # "Comida", the first _stpause entry - what Selenium clicks
ACTIVITY_IDS = ActivityIds(office=SESSION_ID_OFFICE_DEFAULT, home=SESSION_ID_HOME,
                           lunch_pause=LUNCH_PAUSE_ID)


def select_button(buttons, action_type, location):
    """Pick the button Selenium's XPaths in eportem_action.py would click."""
    return _core.select_button(buttons, action_type, location, ACTIVITY_IDS)


class HttpClock(_core.HttpClock):
    def __init__(self, session=None):
        super().__init__(session, target=TARGET, activity_ids=ACTIVITY_IDS, user_agent=USER_AGENT)

    @property
    def verify_attempts(self):
        return VERIFY_ATTEMPTS

    @property
    def verify_pause_seconds(self):
        return VERIFY_PAUSE_SECONDS

    def load_cookies(self, path=None):
        """Load saved cookies from `path` (default COOKIE_FILE, resolved per call)."""
        return self._load_from(FileCookieStore(path or COOKIE_FILE))

    def save_cookies(self, path=None):
        self._save_to(FileCookieStore(path or COOKIE_FILE))

    def _make_driver(self):
        return create_driver()

    def _login_driver(self, driver):
        login_and_navigate(driver)


# Exit codes for the CLI.
EXIT_RECORDED = 0          # the clock event is recorded (or dry run succeeded)
EXIT_NOT_RECORDED = 3      # nothing was recorded
EXIT_UNKNOWN = 4           # a request went out and its outcome is unknown: check by hand
EXIT_NOTIFY_FAILED = 5     # recorded, but notifications/Slack status failed


def main():
    from utility.env_loader import load_environment
    load_environment()
    parser = argparse.ArgumentParser(
        description="Clock action over HTTP (dry run unless --send). For testing by hand: "
                    "skips main.py's holiday, location-override and schedule checks.")
    parser.add_argument("action", choices=["start_day", "lunch_break", "after_lunch", "stop_day"])
    parser.add_argument("--location", choices=["home", "office"], default="office")
    parser.add_argument("--send", action="store_true",
                        help="Actually send the request (registers a real clock event)")
    parser.add_argument("--notify", action="store_true",
                        help="After a recorded --send, send the usual notifications and Slack status")
    args = parser.parse_args()

    if args.send and os.getenv("EPORTEM_ENABLED") != "YES":
        print("HTTP clock: EPORTEM_ENABLED is not YES; refusing to --send. Nothing recorded.")
        return EXIT_NOT_RECORDED

    clock = HttpClock()
    if not args.send:
        try:
            params = clock.resolve(args.action, args.location)
        except Exception as e:
            print(f"HTTP clock: could not prepare the request: {type(e).__name__}: {e}")
            return EXIT_NOT_RECORDED
        print(f"DRY RUN, would send GET {CLOCK_URL}")
        print(json.dumps(params, ensure_ascii=False, indent=2))
        return EXIT_RECORDED

    try:
        clock.clock_and_verify(args.action, args.location)
    except NotRecorded as e:
        print(f"HTTP clock: nothing recorded: {e}")
        return EXIT_NOT_RECORDED
    except OutcomeUnknown as e:
        print(f"HTTP clock: {e}")
        return EXIT_UNKNOWN

    if args.notify:
        try:
            from eportem_action import EPortemAction
            EPortemAction(args.action, args.location).after_action()
        except Exception as e:
            print(f"HTTP clock: recorded, but notifications failed: {type(e).__name__}: {e}")
            return EXIT_NOTIFY_FAILED
    return EXIT_RECORDED


if __name__ == "__main__":
    sys.exit(main())
