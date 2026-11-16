#!/usr/bin/env python3
"""Clock actions over plain HTTP instead of clicking through Chromium.

Login still needs a real browser (reCAPTCHA v3, see
docs/http-api-investigation.md), so this logs in with Selenium only when it
has no valid session cookies, saves them to config/.session_cookies.json
(chmod 600, gitignored) and makes the clock request itself with `requests`.

Every clock button on the dashboard calls `_doPostJorEnviar()` in
/Content/js/reghorjor1.3.js, which sends:

    GET /aplicaciones/e-portem/registro/reghorario.cshtml
        ?action=<button id>&_codactiv=<name>&_tipoactiv=<name2>
        &_descactiv=<name3>&_geolocation=&_localip=

and gets back JSON describing the new state. The buttons shown depend on the
current state (e.g. "Pausar" only while working), so the dashboard is fetched
first and the same button Selenium would click is looked up in it - nothing
about the button attributes is hard-coded except how to pick one.

Normal runs don't call this module directly: main.py decides the action,
location and holidays, and EPortemAction.perform() calls
HttpClock.clock_and_verify(), falling back to Selenium only on NotRecorded.

CLI, for testing by hand (dry run by default - prints the request without sending it).
It skips main.py's holiday, location-override and schedule checks:
    python3 -m utility.http_clock lunch_break --location office
    python3 -m utility.http_clock lunch_break --location office --send --notify
"""
import argparse
import datetime
import json
import os
import sys
import tempfile
import time
from html.parser import HTMLParser
from pathlib import Path

import requests
from urllib3.exceptions import NewConnectionError

# Same browser identity the Selenium login uses, so the session looks consistent.
from utility.login_and_navigate import (  # noqa: F401  (re-exported)
    LOGIN_URL, USER_AGENT, create_driver, login_and_navigate)

BASE_URL = "https://eportem.es"
DASHBOARD_URL = f"{BASE_URL}/aplicaciones/e-portem/registro/"
CLOCK_URL = f"{DASHBOARD_URL}reghorario.cshtml"
COOKIE_FILE = Path(__file__).parent.parent / "config" / ".session_cookies.json"
# Present on every real dashboard; a maintenance or error page served with a 200
# lacks it, and must never be read as "no buttons, so the action was recorded".
DASHBOARD_MARKER = "buttonsRegBox"

# After a failed send the server may still be committing the event, so the dashboard
# is re-read a few times before the action is declared not recorded.
VERIFY_ATTEMPTS = 3
VERIFY_PAUSE_SECONDS = 5

# Keys of the clock response JSON (docs/http-api-investigation.md). A body with none
# of them is not a clock result, whatever its HTTP status.
RESULT_KEYS = ("isActive", "LastDescAct", "listActiv")

SESSION_ID_HOME = "1293"
SESSION_ID_OFFICE_DEFAULT = "1"
LUNCH_PAUSE_ID = "2"  # "Comida", the first _stpause entry - what Selenium clicks

CLOCK_IDS = ("_ststart", "_stpause", "_stini", "_ststop")


def _parse_time(value):
    return datetime.datetime.fromisoformat(value) if value else None


def _fmt_delta(delta):
    minutes = int(delta.total_seconds() // 60)
    return f"{minutes // 60}h{minutes % 60:02d}m"


class SessionExpired(Exception):
    """The saved cookies no longer give access to the dashboard."""


class ButtonNotFound(Exception):
    """The dashboard has no button for this action (usually: wrong state)."""


class NotRecorded(Exception):
    """Nothing was recorded over HTTP, so falling back to Selenium is safe."""


class OutcomeUnknown(Exception):
    """A clock request went out and it can't be told whether it was recorded.
    Falling back could clock twice, so don't."""


class DashboardUnreadable(Exception):
    """The page that came back is not the clock dashboard (maintenance or error
    page, or a dashboard with no clock buttons), so it says nothing about the state."""


class UnexpectedResponse(Exception):
    """The clock request got a 200 whose body isn't a clock result."""


class _ButtonParser(HTMLParser):
    """Collect the attributes of every clock button on the page."""

    def __init__(self):
        super().__init__()
        self.buttons = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id") in CLOCK_IDS:
            self.buttons.append(attrs)


def parse_buttons(html):
    parser = _ButtonParser()
    parser.feed(html)
    return parser.buttons


def _first(buttons, id_, name=None):
    for b in buttons:
        if b.get("id") == id_ and (name is None or b.get("name") == name):
            return b
    return None


def select_button(buttons, action_type, location):
    """Pick the button Selenium's XPaths in eportem_action.py would click."""
    if location not in ("home", "office"):
        raise ValueError(f"Unknown location {location!r}, expected 'home' or 'office'")
    home = location == "home"
    if action_type == "start_day":
        # Exact ids only: the not-started dashboard (captured 2026-11-16 18:30) also
        # offers _ststart for every absence type (2 Comida, 3 Ausencia, Vacaciones...),
        # so "any other _ststart" could start the day on a pause.
        button = _first(buttons, "_ststart", SESSION_ID_HOME if home else SESSION_ID_OFFICE_DEFAULT)
    elif action_type == "lunch_break":
        # No fallback to another _stpause: those are Ausencia, Vacaciones, Baja...
        button = _first(buttons, "_stpause", LUNCH_PAUSE_ID)
    elif action_type == "after_lunch":
        button = _first(buttons, "_stini", SESSION_ID_HOME if home else SESSION_ID_OFFICE_DEFAULT)
    elif action_type == "stop_day":
        button = _first(buttons, "_ststop")
    else:
        raise ValueError(f"Unknown action {action_type!r}")

    if button is None:
        available = ", ".join(
            f"{b.get('id')}[{b.get('name')}] {b.get('name3')}" for b in buttons) or "none"
        raise ButtonNotFound(
            f"No button for {action_type} ({location}) on the dashboard. "
            f"Buttons present: {available}")
    return button


def build_params(button):
    """Mirror the query string jQuery builds in _doPostJorEnviar(). Missing
    attributes are sent empty, as jQuery does for undefined values;
    geolocation and local IP are empty, as in a browser without them."""
    return {
        "action": button.get("id"),
        "_codactiv": button.get("name") or "",
        "_tipoactiv": button.get("name2") or "",
        "_descactiv": button.get("name3") or "",
        "_geolocation": "",
        "_localip": "",
    }


def _send_never_reached_server(error):
    """True when a failed request can't have reached the server (it never
    connected), so nothing can have been recorded."""
    if isinstance(error, requests.exceptions.ConnectTimeout):
        return True
    if isinstance(error, requests.exceptions.ConnectionError) \
            and not isinstance(error, requests.exceptions.ReadTimeout):
        reason = getattr(error.args[0] if error.args else None, "reason", None)
        return isinstance(reason, NewConnectionError)  # includes DNS failures
    return False


class HttpClock:
    def __init__(self, session=None):
        self.logged_in_at = None
        self.last_used_at = None
        self.user_agent = None  # the one the login browser used, from the cookie file
        self.session = session or requests.Session()
        # A fresh requests.Session already carries "python-requests/x", so setdefault
        # would never apply; replace that, but keep a UA a caller chose on purpose.
        current = self.session.headers.get("User-Agent")
        if not isinstance(current, str) or current.startswith("python-requests"):
            self.session.headers["User-Agent"] = USER_AGENT

    # --- cookies -------------------------------------------------------
    def load_cookies(self, path=None):
        """Load saved cookies. The file is {"logged_in_at", "last_used_at",
        "user_agent", "cookies"}; an older plain list is accepted, its mtime taken
        as the login time. A corrupt file returns False (nothing loaded) so the
        caller logs in again and rewrites it."""
        path = path or COOKIE_FILE
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text())
            if isinstance(data, list):
                data = {"cookies": data, "last_used_at": None,
                        "logged_in_at": datetime.datetime.fromtimestamp(path.stat().st_mtime).isoformat()}
            logged_in_at = _parse_time(data.get("logged_in_at"))
            last_used_at = _parse_time(data.get("last_used_at"))
            user_agent = data.get("user_agent")
            cookies = [(c["name"], c["value"], c.get("domain"), c.get("path", "/"))
                       for c in data["cookies"]]
            if not all(isinstance(x[0], str) and isinstance(x[1], str) for x in cookies):
                raise TypeError("cookie name/value is not a string")
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            print(f"Session: the saved session file {path.name} is unreadable "
                  f"({type(e).__name__}); it will be replaced after a browser login")
            self.session.cookies.clear()
            self.logged_in_at = self.last_used_at = None
            return False
        self.logged_in_at, self.last_used_at = logged_in_at, last_used_at
        for name, value, domain, cpath in cookies:
            self.session.cookies.set(name, value, domain=domain, path=cpath)
        if isinstance(user_agent, str) and user_agent:
            self.user_agent = user_agent
            self.session.headers["User-Agent"] = user_agent
        return True

    def save_cookies(self, path=None):
        """Save the cookies (including any auth ticket the server renewed)
        and record when the session was last used. Written to a temp file with
        mode 600 and renamed over the old one, so a crash can't leave it truncated."""
        path = path or COOKIE_FILE
        self.last_used_at = datetime.datetime.now()
        data = {
            "logged_in_at": self.logged_in_at.isoformat() if self.logged_in_at else None,
            "last_used_at": self.last_used_at.isoformat(),
            "cookies": [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
                        for c in self.session.cookies],
        }
        if self.user_agent:
            data["user_agent"] = self.user_agent
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")  # mode 600
        try:
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps(data))
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _session_age(self):
        """'login 10:27, 3h05m ago; last used 10:56, 2h34m ago' - for the log, so
        each run is a data point on how long an ePortem session lasts."""
        now = datetime.datetime.now()
        def part(label, t):
            return f"{label} {t:%H:%M}, {_fmt_delta(now - t)} ago" if t else f"{label} unknown"
        return f"{part('login', self.logged_in_at)}; {part('last used', self.last_used_at)}"

    def import_selenium_cookies(self, driver):
        self.session.cookies.clear()
        for c in driver.get_cookies():
            self.session.cookies.set(c["name"], c["value"],
                                     domain=c.get("domain"), path=c.get("path", "/"))

    def browser_login(self):
        """Log in with Selenium (the only way past reCAPTCHA), keep the cookies and
        the browser's User-Agent. login_and_navigate raises LoginRejected if the
        login didn't go through."""
        driver = create_driver()
        try:
            driver.get(LOGIN_URL)
            login_and_navigate(driver)
            user_agent = driver.execute_script("return navigator.userAgent")
            self.import_selenium_cookies(driver)
            self.logged_in_at = datetime.datetime.now()
            if isinstance(user_agent, str) and user_agent:
                self.user_agent = user_agent
                self.session.headers["User-Agent"] = user_agent
        finally:
            driver.quit()
        self.save_cookies()

    # --- dashboard -----------------------------------------------------
    def fetch_buttons(self):
        resp = self.session.get(DASHBOARD_URL, timeout=30)
        if "/Usuario/Login" in resp.url or 'id="login-form"' in resp.text:
            raise SessionExpired("Session cookies are no longer valid")
        resp.raise_for_status()
        if DASHBOARD_MARKER not in resp.text:
            raise DashboardUnreadable(
                f"the page at {DASHBOARD_URL} has no {DASHBOARD_MARKER} (maintenance or error page?)")
        return parse_buttons(resp.text)

    def ensure_session(self):
        """Return the dashboard buttons, logging in with a browser if needed."""
        if self.load_cookies():
            try:
                buttons = self.fetch_buttons()
                print(f"Session: saved session still valid ({self._session_age()})")
                self.save_cookies()  # keep a renewed auth ticket, if the server sent one
                return buttons
            except SessionExpired:
                print(f"Session: saved session expired ({self._session_age()}); "
                      "logging in with the browser")
        else:
            print("Session: no saved session; logging in with the browser")
        self.browser_login()
        return self.fetch_buttons()

    # --- the clock action ---------------------------------------------
    def resolve(self, action_type, location):
        """The query parameters for this action, from the live dashboard.
        Sends nothing that records a clock event."""
        return build_params(select_button(self.ensure_session(), action_type, location))

    def send(self, params):
        """Send the clock request. This records a real clock event. Raises
        UnexpectedResponse if the 200 body doesn't look like a clock result."""
        resp = self.session.get(CLOCK_URL, params=params, timeout=30, headers={
            "X-Requested-With": "XMLHttpRequest",
            "Referer": DASHBOARD_URL,
        })
        resp.raise_for_status()
        try:
            result = json.loads(resp.text)
        except ValueError:
            result = None
        if not isinstance(result, dict) or not any(k in result for k in RESULT_KEYS):
            print("HTTP clock: unexpected response body:", resp.text[:300].replace("\n", " "))
            raise UnexpectedResponse("the response is not a clock result")
        try:
            self.save_cookies()  # keep any refreshed auth ticket
        except OSError as e:
            # The event is recorded; failing to save cookies must not look like a failed send.
            print(f"HTTP clock: warning: could not save the session cookies: {e}")
        return result

    def is_recorded(self, params):
        """After a send that may have failed: True if the dashboard no longer
        offers the button that was sent (so the server recorded it), False if
        it still does. Raises if the dashboard can't be read, including when it
        has no clock buttons at all (can't tell "recorded" from "no buttons")."""
        buttons = self.fetch_buttons()
        if not buttons:
            raise DashboardUnreadable("the dashboard shows no clock buttons")
        return not any(b.get("id") == params["action"]
                       and (b.get("name") or "") == params["_codactiv"]
                       for b in buttons)

    def _recorded_after_settling(self, params):
        """True as soon as the dashboard stops offering the button; False if every
        check still does. Re-checks with a pause since the server may still be
        committing a request that timed out or failed with a 5xx."""
        for attempt in range(VERIFY_ATTEMPTS):
            if attempt:
                time.sleep(VERIFY_PAUSE_SECONDS)
            if self.is_recorded(params):
                return True
        return False

    def clock_and_verify(self, action_type, location):
        """Send the clock request. Returns (params, response_json_or_None) when the
        action is recorded; the response is None if the request errored but the
        dashboard shows it was recorded anyway. Raises NotRecorded when it is safe
        to retry another way, OutcomeUnknown when it isn't."""
        try:
            params = self.resolve(action_type, location)
        except Exception as e:
            raise NotRecorded(f"could not prepare the request, nothing sent: "
                              f"{type(e).__name__}: {e}") from e
        print(f"Sending GET {CLOCK_URL}")
        print(json.dumps(params, ensure_ascii=False, indent=2))
        try:
            result = self.send(params)
            print("Response:", json.dumps(result, ensure_ascii=False)[:500])
            return params, result
        except Exception as e:
            print(f"HTTP clock: request failed: {type(e).__name__}: {e}. Checking the dashboard.")
            send_error = e
        try:
            recorded = self._recorded_after_settling(params)
        except Exception as e:
            raise OutcomeUnknown(
                f"request failed ({type(send_error).__name__}) and the dashboard can't be "
                f"read ({type(e).__name__}); the action may or may not be recorded. "
                "Check ePortem by hand.") from e
        if not recorded:
            # The button is still offered. That is only safe to retry if the request
            # can't have reached the server: a read timeout (or a dropped connection)
            # means it did, and the event may still be committed.
            if (isinstance(send_error, (requests.exceptions.ReadTimeout,
                                        requests.exceptions.ConnectionError))
                    and not _send_never_reached_server(send_error)):
                raise OutcomeUnknown(
                    f"request failed ({type(send_error).__name__}) after reaching the server "
                    "and the dashboard still offers the button; it may still be recorded. "
                    "Check ePortem by hand.") from send_error
            raise NotRecorded(f"request failed ({type(send_error).__name__}: {send_error}) "
                              "and the dashboard still offers the button")
        print("HTTP clock: the dashboard shows the action as recorded despite the error.")
        return params, None

    def clock(self, action_type, location, send=False):
        """Resolve and (only if send=True) perform the clock request.
        Returns (params, response_json_or_None)."""
        params = self.resolve(action_type, location)
        return params, (self.send(params) if send else None)


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
