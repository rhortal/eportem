"""Clock actions over plain HTTP instead of clicking through Chromium.

Login still needs a real browser (reCAPTCHA v3, see
docs/http-api-investigation.md), so the browser is only used when there are no
valid session cookies; the clock request itself is made with `requests`.

Every clock button on the dashboard calls `_doPostJorEnviar()` in
/Content/js/reghorjor1.3.js, which sends:

    GET /aplicaciones/e-portem/registro/reghorario.cshtml
        ?action=<button id>&_codactiv=<name>&_tipoactiv=<name2>
        &_descactiv=<name3>&_geolocation=&_localip=

and gets back JSON describing the new state. The buttons shown depend on the
current state (e.g. "Pausar" only while working), so the dashboard is fetched
first and the button for the action is looked up in it - nothing about the
button attributes is hard-coded except the activity IDs used to pick one.
"""
import datetime
import json
import time
from html.parser import HTMLParser

import requests
from urllib3.exceptions import NewConnectionError

from eportem.core.browser import USER_AGENT
from eportem.core.cookies import MemoryCookieStore
from eportem.core.output import default_say
from eportem.core.target import Target

# Present on every real dashboard; a maintenance or error page served with a 200
# lacks it, and must never be read as "no buttons, so the action was recorded".
DASHBOARD_MARKER = "buttonsRegBox"

# After a failed send the server may still be committing the event, so the dashboard
# is re-read a few times before the action is declared not recorded.
VERIFY_ATTEMPTS = 3
VERIFY_PAUSE_SECONDS = 5
REQUEST_TIMEOUT_SECONDS = 30

# Keys of the clock response JSON (docs/http-api-investigation.md). A body with none
# of them is not a clock result, whatever its HTTP status.
RESULT_KEYS = ("isActive", "LastDescAct", "listActiv")

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
    """Nothing was recorded over HTTP, so falling back to the browser is safe."""


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


def select_button(buttons, action_type, location, activity_ids):
    """Pick the button for this action, by exact activity ID."""
    if location not in ("home", "office"):
        raise ValueError(f"Unknown location {location!r}, expected 'home' or 'office'")
    if action_type == "start_day":
        # Exact ids only: the not-started dashboard (captured 2026-11-16 18:30) also
        # offers _ststart for every absence type (2 Comida, 3 Ausencia, Vacaciones...),
        # so "any other _ststart" could start the day on a pause.
        button = _first(buttons, "_ststart", activity_ids.work(location))
    elif action_type == "lunch_break":
        # No fallback to another _stpause: those are Ausencia, Vacaciones, Baja...
        button = _first(buttons, "_stpause", activity_ids.lunch_pause)
    elif action_type == "after_lunch":
        button = _first(buttons, "_stini", activity_ids.work(location))
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


def send_never_reached_server(error):
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
    """One ePortem account's HTTP clock.

    - target: the site (Target), so tests and the fake can stand in for eportem.es.
    - activity_ids: this account's ActivityIds.
    - cookie_store: where the session is kept (FileCookieStore, a DB store, ...).
    - make_driver / login_driver: start a browser, and log it in (given the
      driver). Only used when the saved session is missing or expired.
    """
    verify_attempts = VERIFY_ATTEMPTS
    verify_pause_seconds = VERIFY_PAUSE_SECONDS

    def __init__(self, session=None, *, target=None, activity_ids=None, cookie_store=None,
                 make_driver=None, login_driver=None, user_agent=USER_AGENT, say=default_say):
        self.target = target or Target()
        self.activity_ids = activity_ids
        self.cookie_store = cookie_store if cookie_store is not None else MemoryCookieStore()
        self._make_driver_fn = make_driver
        self._login_driver_fn = login_driver
        self.say = say
        self.logged_in_at = None
        self.last_used_at = None
        self.user_agent = None  # the one the login browser used, from the saved session
        self.session = session or requests.Session()
        # A fresh requests.Session already carries "python-requests/x", so setdefault
        # would never apply; replace that, but keep a UA a caller chose on purpose.
        current = self.session.headers.get("User-Agent")
        if not isinstance(current, str) or current.startswith("python-requests"):
            self.session.headers["User-Agent"] = user_agent

    # --- cookies -------------------------------------------------------
    def load_cookies(self):
        return self._load_from(self.cookie_store)

    def save_cookies(self):
        self._save_to(self.cookie_store)

    def _load_from(self, store):
        """Load the saved session. A corrupt record returns False (nothing
        loaded) so the caller logs in again and rewrites it."""
        try:
            data = store.load()
            if data is None:
                return False
            logged_in_at = _parse_time(data.get("logged_in_at"))
            last_used_at = _parse_time(data.get("last_used_at"))
            user_agent = data.get("user_agent")
            cookies = [(c["name"], c["value"], c.get("domain"), c.get("path", "/"))
                       for c in data["cookies"]]
            if not all(isinstance(x[0], str) and isinstance(x[1], str) for x in cookies):
                raise TypeError("cookie name/value is not a string")
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            self.say(f"Session: {store.describe()} is unreadable "
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

    def _save_to(self, store):
        """Save the cookies (including any auth ticket the server renewed)
        and record when the session was last used."""
        self.last_used_at = datetime.datetime.now()
        data = {
            "logged_in_at": self.logged_in_at.isoformat() if self.logged_in_at else None,
            "last_used_at": self.last_used_at.isoformat(),
            "cookies": [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
                        for c in self.session.cookies],
        }
        if self.user_agent:
            data["user_agent"] = self.user_agent
        store.save(data)

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

    # --- browser login -------------------------------------------------
    def _make_driver(self):
        if self._make_driver_fn is None:
            raise RuntimeError("no browser configured for logging in")
        return self._make_driver_fn()

    def _login_driver(self, driver):
        if self._login_driver_fn is None:
            raise RuntimeError("no login configured")
        self._login_driver_fn(driver)

    def browser_login(self):
        """Log in with the browser (the only way past reCAPTCHA), keep the cookies and
        the browser's User-Agent. The login function raises if the login didn't go
        through; the browser is always closed."""
        driver = self._make_driver()
        try:
            driver.get(self.target.login_url)
            self._login_driver(driver)
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
        resp = self.session.get(self.target.dashboard_url, timeout=REQUEST_TIMEOUT_SECONDS)
        if Target.is_login_page(resp.url) or 'id="login-form"' in resp.text:
            raise SessionExpired("Session cookies are no longer valid")
        resp.raise_for_status()
        if DASHBOARD_MARKER not in resp.text:
            raise DashboardUnreadable(
                f"the page at {self.target.dashboard_url} has no {DASHBOARD_MARKER} "
                "(maintenance or error page?)")
        return parse_buttons(resp.text)

    def ensure_session(self):
        """Return the dashboard buttons, logging in with a browser if needed."""
        if self.load_cookies():
            try:
                buttons = self.fetch_buttons()
                self.say(f"Session: saved session still valid ({self._session_age()})")
                self.save_cookies()  # keep a renewed auth ticket, if the server sent one
                return buttons
            except SessionExpired:
                self.say(f"Session: saved session expired ({self._session_age()}); "
                         "logging in with the browser")
        else:
            self.say("Session: no saved session; logging in with the browser")
        self.browser_login()
        return self.fetch_buttons()

    # --- the clock action ---------------------------------------------
    def select(self, buttons, action_type, location):
        return select_button(buttons, action_type, location, self.activity_ids)

    def resolve(self, action_type, location):
        """The query parameters for this action, from the live dashboard.
        Sends nothing that records a clock event."""
        return build_params(self.select(self.ensure_session(), action_type, location))

    def send(self, params):
        """Send the clock request. This records a real clock event. Raises
        UnexpectedResponse if the 200 body doesn't look like a clock result."""
        resp = self.session.get(self.target.clock_url, params=params, timeout=REQUEST_TIMEOUT_SECONDS,
                                headers={"X-Requested-With": "XMLHttpRequest",
                                         "Referer": self.target.dashboard_url})
        resp.raise_for_status()
        try:
            result = json.loads(resp.text)
        except ValueError:
            result = None
        if not isinstance(result, dict) or not any(k in result for k in RESULT_KEYS):
            self.say("HTTP clock: unexpected response body:", resp.text[:300].replace("\n", " "))
            raise UnexpectedResponse("the response is not a clock result")
        try:
            self.save_cookies()  # keep any refreshed auth ticket
        except OSError as e:
            # The event is recorded; failing to save cookies must not look like a failed send.
            self.say(f"HTTP clock: warning: could not save the session cookies: {e}")
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
        for attempt in range(self.verify_attempts):
            if attempt:
                time.sleep(self.verify_pause_seconds)
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
        self.say(f"Sending GET {self.target.clock_url}")
        self.say(json.dumps(params, ensure_ascii=False, indent=2))
        try:
            result = self.send(params)
            self.say("Response:", json.dumps(result, ensure_ascii=False)[:500])
            return params, result
        except Exception as e:
            self.say(f"HTTP clock: request failed: {type(e).__name__}: {e}. Checking the dashboard.")
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
                    and not send_never_reached_server(send_error)):
                raise OutcomeUnknown(
                    f"request failed ({type(send_error).__name__}) after reaching the server "
                    "and the dashboard still offers the button; it may still be recorded. "
                    "Check ePortem by hand.") from send_error
            raise NotRecorded(f"request failed ({type(send_error).__name__}: {send_error}) "
                              "and the dashboard still offers the button")
        self.say("HTTP clock: the dashboard shows the action as recorded despite the error.")
        return params, None

    def clock(self, action_type, location, send=False):
        """Resolve and (only if send=True) perform the clock request.
        Returns (params, response_json_or_None)."""
        params = self.resolve(action_type, location)
        return params, (self.send(params) if send else None)
