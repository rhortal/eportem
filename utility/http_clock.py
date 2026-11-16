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

CLI (dry run by default - prints the request without sending it):
    python3 -m utility.http_clock lunch_break --location office
    python3 -m utility.http_clock lunch_break --location office --send
"""
import argparse
import json
import os
import sys
from html.parser import HTMLParser
from pathlib import Path

import requests

BASE_URL = "https://eportem.es"
DASHBOARD_URL = f"{BASE_URL}/aplicaciones/e-portem/registro/"
CLOCK_URL = f"{DASHBOARD_URL}reghorario.cshtml"
COOKIE_FILE = Path(__file__).parent.parent / "config" / ".session_cookies.json"
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")

SESSION_ID_HOME = "1293"
SESSION_ID_OFFICE_DEFAULT = "1"
LUNCH_PAUSE_ID = "2"  # "Comida", the first _stpause entry - what Selenium clicks

CLOCK_IDS = ("_ststart", "_stpause", "_stini", "_ststop")


class SessionExpired(Exception):
    """The saved cookies no longer give access to the dashboard."""


class ButtonNotFound(Exception):
    """The dashboard has no button for this action (usually: wrong state)."""


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
    home = location == "home"
    if action_type == "start_day":
        button = (_first(buttons, "_ststart", SESSION_ID_HOME) if home
                  else _first(buttons, "_ststart", SESSION_ID_OFFICE_DEFAULT)
                  or next((b for b in buttons if b.get("id") == "_ststart"
                           and b.get("name") != SESSION_ID_HOME), None))
    elif action_type == "lunch_break":
        button = _first(buttons, "_stpause", LUNCH_PAUSE_ID) or _first(buttons, "_stpause")
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


class HttpClock:
    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)

    # --- cookies -------------------------------------------------------
    def load_cookies(self, path=COOKIE_FILE):
        if not path.exists():
            return False
        for c in json.loads(path.read_text()):
            self.session.cookies.set(c["name"], c["value"],
                                     domain=c.get("domain"), path=c.get("path", "/"))
        return True

    def save_cookies(self, path=COOKIE_FILE):
        data = [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
                for c in self.session.cookies]
        path.touch(mode=0o600, exist_ok=True)
        os.chmod(path, 0o600)
        path.write_text(json.dumps(data))

    def import_selenium_cookies(self, driver):
        self.session.cookies.clear()
        for c in driver.get_cookies():
            self.session.cookies.set(c["name"], c["value"],
                                     domain=c.get("domain"), path=c.get("path", "/"))

    def browser_login(self):
        """Log in with Selenium (the only way past reCAPTCHA), keep the cookies."""
        from utility.login_and_navigate import login_and_navigate
        driver = login_and_navigate()
        try:
            if "no es un robot" in driver.page_source:
                raise RuntimeError("Login rejected by reCAPTCHA ('no es un robot')")
            if "/Usuario/Login" in driver.current_url:
                raise RuntimeError(f"Login failed, still on {driver.current_url}")
            self.import_selenium_cookies(driver)
        finally:
            driver.quit()
        self.save_cookies()

    # --- dashboard -----------------------------------------------------
    def fetch_buttons(self):
        resp = self.session.get(DASHBOARD_URL, timeout=30)
        if "/Usuario/Login" in resp.url or 'id="login-form"' in resp.text:
            raise SessionExpired("Session cookies are no longer valid")
        resp.raise_for_status()
        return parse_buttons(resp.text)

    def ensure_session(self):
        """Return the dashboard buttons, logging in with a browser if needed."""
        if self.load_cookies():
            try:
                return self.fetch_buttons()
            except SessionExpired:
                print("Saved session expired, logging in with the browser")
        self.browser_login()
        return self.fetch_buttons()

    # --- the clock action ---------------------------------------------
    def clock(self, action_type, location, send=False):
        """Resolve and (only if send=True) perform the clock request.
        Returns (params, response_json_or_None)."""
        button = select_button(self.ensure_session(), action_type, location)
        params = build_params(button)
        if not send:
            return params, None
        resp = self.session.get(CLOCK_URL, params=params, timeout=30, headers={
            "X-Requested-With": "XMLHttpRequest",
            "Referer": DASHBOARD_URL,
        })
        resp.raise_for_status()
        result = json.loads(resp.text)
        self.save_cookies()  # keep any refreshed auth ticket
        return params, result


def main():
    from utility.env_loader import load_environment
    load_environment()
    parser = argparse.ArgumentParser(description="Clock action over HTTP (dry run unless --send).")
    parser.add_argument("action", choices=["start_day", "lunch_break", "after_lunch", "stop_day"])
    parser.add_argument("--location", choices=["home", "office"], default="office")
    parser.add_argument("--send", action="store_true",
                        help="Actually send the request (registers a real clock event)")
    args = parser.parse_args()

    params, result = HttpClock().clock(args.action, args.location, send=args.send)
    print(("SENT " if args.send else "DRY RUN, would send ") + f"GET {CLOCK_URL}")
    print(json.dumps(params, ensure_ascii=False, indent=2))
    if result is not None:
        print("Response:", json.dumps(result, ensure_ascii=False)[:500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
