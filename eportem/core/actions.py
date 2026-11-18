"""Perform one clock action for one account.

HTTP first (when enabled), falling back to clicking through the browser only
when HTTP recorded nothing; then the follow-ups (notifications, Slack status),
which never fail a recorded action.

ClockAction gets everything from its constructor: the site, the activity IDs,
how to start and log in a browser, how to build an HTTP clock, the
notification channels, the Slack status updater and where to record the run.
Each of those is also a method, so an adapter can override it instead.
"""
import contextlib
import datetime
import io
import os
import re
import time

from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from eportem.core.clock_http import NotRecorded, OutcomeUnknown
from eportem.core.notify import NotificationManager, describe_error
from eportem.core.output import default_say
from eportem.core.schedule import ACTIONS, LOCATIONS
from eportem.core.target import Target

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
MAX_DIAGNOSTICS_FILES = 20  # newest files kept in the diagnostics dir (a set is .html + .png)

BUSINESS_TRIP_STATUS_TEXT = "On a business trip"
BUSINESS_TRIP_STATUS_EMOJI = ":airplane:"

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


def message_for(action_type, location):
    """The notification text for a recorded action."""
    messages = {
        "start_day": f"RePortemed at {location}",
        "lunch_break": "RePortemed going to lunch break",
        "after_lunch": "RePortemed back from lunch break",
        "stop_day": "RePortemed done for the day"
    }
    return messages.get(action_type, "RePortem action completed")


def status_for(action_type, location, trip_end=None):
    """(text, emoji, expiration) for the Slack status after this action. On a
    business trip every action (including stop_day) keeps the same status
    until the trip's last day ends."""
    if trip_end:
        expiration = int(datetime.datetime.combine(trip_end, datetime.time(23, 59)).timestamp())
        return BUSINESS_TRIP_STATUS_TEXT, BUSINESS_TRIP_STATUS_EMOJI, expiration
    working_emoji = ":house:" if location == "home" else ":office:"
    if action_type in ("start_day", "after_lunch"):
        return f"Working at {location}", working_emoji, 0
    if action_type == "lunch_break":
        return "Away for lunch", ":fork_and_knife:", 0
    if action_type == "stop_day":
        return "Done for the day", ":palm_tree:", 0
    return "Working", ":computer:", 0


def selectors_for(action_type, location, activity_ids):
    """XPaths of the button(s) to click: the main button, then (if any) the
    dropdown entry."""
    home_id, office_id = activity_ids.home, activity_ids.office
    selectors = {
        "start_day": {
            "office": {
                "button1": "//*[@id=\"buttonsRegBox\"]/div/div/button",
                "button2": None
            },
            "home": {
                "button1": "//*[@id=\"buttonsRegBox\"]/div/button[@data-toggle=\"dropdown\"]",
                "button2": f"//*[@id=\"_ststart\" and @name=\"{home_id}\"]"
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
                "button2": f"//a[@id=\"_stini\" and @name=\"{office_id}\"]"
            },
            "home": {
                "button1": "//*[@id=\"buttonsRegBox\"]/div/div/button/div/div[2]/h2",
                "button2": f"//a[@id=\"_stini\" and @name=\"{home_id}\"]"
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
    return selectors.get(action_type, {}).get(location, {})


class SayCapture:
    """Copies everything the action says into a buffer for the run log, by
    wrapping its `say` for the duration of the run."""

    def __init__(self, action):
        self.action = action
        self.buffer = io.StringIO()
        self._outer = None

    def __enter__(self):
        self._outer = outer = self.action.say

        def say(*args, **kwargs):
            print(*args, **{**kwargs, "file": self.buffer})
            outer(*args, **kwargs)
        self.action.say = say
        return self

    def __exit__(self, *exc):
        self.action.say = self._outer
        return False

    def write(self, text):
        self.buffer.write(text)

    def getvalue(self):
        return self.buffer.getvalue()


class ClockAction:
    button_wait_seconds = BUTTON_WAIT_SECONDS
    retry_budget_seconds = RETRY_BUDGET_SECONDS
    retry_pause_seconds = RETRY_PAUSE_SECONDS
    login_attempts = LOGIN_ATTEMPTS
    max_logins_per_run = MAX_LOGINS_PER_RUN
    max_diagnostics_per_run = MAX_DIAGNOSTICS_PER_RUN
    max_diagnostics_files = MAX_DIAGNOSTICS_FILES

    # For actions with no second button, the main button's label (lowercase prefix)
    # that shows the action is still possible, and the labels that clearly show it
    # isn't. Anything else (unreadable, new wording) is not blocked.
    _STATE_OK = {"start_day": "iniciar"}
    _STATE_WRONG = ("pausar", "reanudar")
    # What a failed run leaves behind for the user to look at.
    failure_report = "failure report"

    def __init__(self, action_type, location="office", driver=None, *, activity_ids=None,
                 target=None, diagnostics_dir=None, make_driver=None, login_driver=None,
                 http_clock=None, use_http=False, channels=None, status_updater=None,
                 business_trip_end=None, record=None, log_run=None, secrets=(),
                 say=default_say):
        """
        - action_type: start_day, lunch_break, after_lunch, stop_day
        - location: office, home
        - driver: a webdriver to use instead of starting one (then HTTP is not tried)
        - make_driver(): start a browser; login_driver(driver) -> driver: log it in
        - http_clock(): a ready HttpClock for this account; use_http: try it first
        - channels(): notification channels; status_updater(): a SlackStatusUpdater or None
        - business_trip_end(): the last day of a business trip covering today, or None
        - record(action, location, how): store a recorded action
        - log_run(action, location, outcome, output): store this run's log block
        - secrets: values to scrub from follow-up error messages
        """
        if action_type not in ACTIONS:
            raise ValueError(f"Unknown action_type {action_type!r}; expected one of {', '.join(ACTIONS)}")
        if location not in LOCATIONS:
            raise ValueError(f"Unknown location {location!r}; expected one of {', '.join(LOCATIONS)}")
        self.action_type = action_type
        self.location = location
        self.driver = driver
        self.activity_ids = activity_ids
        self.target = target or Target()
        self._diagnostics_dir = diagnostics_dir
        self._make_driver_fn = make_driver
        self._login_driver_fn = login_driver
        self._http_clock_fn = http_clock
        self._use_http = use_http
        self._channels_fn = channels
        self._status_updater_fn = status_updater
        self._business_trip_end_fn = business_trip_end
        self._record_fn = record
        self._log_run_fn = log_run
        self._secret_values = tuple(secrets)
        self.say = say
        self.logins_used = 0
        self.diagnostics_saved = 0
        self.selectors = self._get_selectors()

    # --- collaborators (override in an adapter, or pass to __init__) -----
    @property
    def diagnostics_dir(self):
        return self._diagnostics_dir

    def _get_selectors(self):
        return selectors_for(self.action_type, self.location, self.activity_ids)

    def _get_message(self):
        return message_for(self.action_type, self.location)

    def _new_driver(self):
        if self._make_driver_fn is None:
            raise RuntimeError("no browser configured")
        return self._make_driver_fn()

    def _login_driver(self, driver):
        if self._login_driver_fn is None:
            raise RuntimeError("no login configured")
        return self._login_driver_fn(driver)

    def _http_enabled(self):
        return self._use_http

    def _new_http_clock(self):
        if self._http_clock_fn is None:
            raise RuntimeError("no HTTP clock configured")
        return self._http_clock_fn()

    def _before_perform(self):
        """Last check before anything is sent (the legacy kill switch)."""

    def _capture(self):
        return SayCapture(self)

    def _record(self, how):
        if self._record_fn:
            self._record_fn(self.action_type, self.location, how)

    def _log_run(self, outcome, output):
        if self._log_run_fn:
            self._log_run_fn(self.action_type, self.location, outcome, output)

    def _secrets(self):
        return self._secret_values

    def _channels(self):
        return list(self._channels_fn()) if self._channels_fn else []

    def _status_updater(self):
        return self._status_updater_fn() if self._status_updater_fn else None

    def _business_trip_end(self):
        return self._business_trip_end_fn() if self._business_trip_end_fn else None

    # --- the browser flow ----------------------------------------------
    def _button_appears(self, xpath):
        """Wait for a button without clicking it; True if it showed up in time."""
        try:
            WebDriverWait(self.driver, self.button_wait_seconds).until(
                lambda d: d.find_elements(By.XPATH, xpath))
            return True
        except WebDriverException:  # includes the wait's TimeoutException
            return False

    def _save_diagnostics(self):
        """Record what the browser was showing, for the failure output and later study.
        At most max_diagnostics_per_run times per run, newest max_diagnostics_files kept.
        Nothing is saved when there is no diagnostics dir."""
        if self.diagnostics_saved >= self.max_diagnostics_per_run:
            return
        self.diagnostics_saved += 1
        directory = self.diagnostics_dir
        try:
            self.say(f"URL: {self.driver.current_url} Title: {self.driver.title}")
            if not directory:
                return
            os.makedirs(directory, mode=0o700, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            base = os.path.join(directory, f"{stamp}-{self.action_type}")
            html = _TOKEN_VALUE.sub(r"\1<redacted>\2", str(self.driver.page_source))
            fd = os.open(f"{base}.html", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(html)
            self.driver.save_screenshot(f"{base}.png")
            with contextlib.suppress(OSError):
                os.chmod(f"{base}.png", 0o600)
            self.say(f"Diagnostics saved to {base}.html and .png")
        except Exception as e:  # must never hide the real failure
            self.say(f"Could not save diagnostics: {e}")
        if directory:
            self._prune_diagnostics()

    def _prune_diagnostics(self):
        """Delete all but the newest max_diagnostics_files saved files."""
        directory = self.diagnostics_dir
        try:
            files = [os.path.join(directory, n) for n in os.listdir(directory)
                     if _DIAGNOSTICS_NAME.match(n)]
            files.sort(key=lambda p: (os.path.getmtime(p), p), reverse=True)
            for old in files[self.max_diagnostics_files:]:
                with contextlib.suppress(OSError):
                    os.remove(old)
        except OSError:
            pass

    def _login(self):
        """Log in, retrying a few times if the site is failing. Nothing is clicked on
        the registro page here, so a retry can't record anything. Every form
        submission counts against max_logins_per_run."""
        new_browser = self.driver is None
        if new_browser:
            self.driver = self._new_driver()
        for attempt in range(1, self.login_attempts + 1):
            if self.logins_used >= self.max_logins_per_run:
                self.say(f"Login budget spent ({self.max_logins_per_run} submissions this run); "
                         "not trying again so the account isn't hammered.")
                self._save_diagnostics()
                raise LoginBudgetExceeded(
                    f"gave up after {self.max_logins_per_run} login submissions in one run")
            self.logins_used += 1
            try:
                if new_browser or attempt > 1:
                    self.driver.get(self.target.login_url)
                self.driver = self._login_driver(self.driver)
                return
            except WebDriverException as e:
                self.say(f"Login attempt {attempt} of {self.login_attempts} failed: {type(e).__name__}")
                if attempt == self.login_attempts:
                    self._save_diagnostics()
                    raise
                time.sleep(self.retry_pause_seconds)

    def _ensure_button(self, xpath):
        """Give the first button time to appear, reopening the page until
        retry_budget_seconds have passed and logging in again if the session was lost.
        Clicks nothing, so a retry can't record anything twice. If it is still missing,
        save diagnostics and let the caller's find_element raise as usual."""
        deadline = time.monotonic() + self.retry_budget_seconds
        while not self._button_appears(xpath):
            if time.monotonic() >= deadline:
                self.say(f"Button not found after {self.retry_budget_seconds}s of retries")
                self._save_diagnostics()
                return
            self.say(f"{datetime.datetime.now():%H:%M:%S} Button not found, "
                     f"reopening the page in {self.retry_pause_seconds}s")
            time.sleep(self.retry_pause_seconds)
            try:
                self.driver.get(self.target.dashboard_url)
                if Target.is_login_page(self.driver.current_url):
                    self.say("Session lost, logging in again")
                    self._login()
            except WebDriverException as e:
                self.say(f"Reopening failed: {type(e).__name__}")

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
        self.say(f"{self.action_type} ({self.location}) is not available: ePortem shows "
                 f"'{self._page_state()}' and doesn't offer this option. Nothing was recorded.")
        if self.action_type == "after_lunch":
            self.say("There is no lunch break to resume, so the lunch_break run probably failed "
                     f"(look for its {self.failure_report}). Correct the day in Registro Jornada > Detalle registro.")
        self._save_diagnostics()

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
            self.say(f"{self.action_type} ({self.location}) is not needed: ePortem shows "
                     f"'{label}', so the day is already started - nothing was recorded.")
            self._save_diagnostics()
            raise ActionNotApplicable(f"already started (button shows '{label}')")

    # --- the action ------------------------------------------------------
    def perform(self):
        """Perform the action: over HTTP if enabled, falling back to the browser
        only when HTTP recorded nothing. Holidays, location overrides and the
        schedule are decided before this, so they apply whichever way it is sent.
        Everything said during the run is passed to log_run with its outcome."""
        self._before_perform()
        run = {"outcome": None, "fallback": False}
        capture = self._capture()
        try:
            with capture:
                how = self._clock(run)
                # Before the follow-ups: the end-of-day check reads this to spot missed actions
                self._record(how)
                self.after_action()
        except BaseException as e:
            if run["outcome"] is None:
                run["outcome"] = f"ERROR, browser run failed: {type(e).__name__}: {e}"
            elif run["fallback"]:
                capture.write(f"Browser fallback failed: {type(e).__name__}: {e}\n")
            raise
        finally:
            self._log_run(run["outcome"] or "ERROR: run did not finish", capture.getvalue())
        return True

    def _clock(self, run):
        """Record the action over HTTP or the browser; returns how. Fills
        run["outcome"] (the header for the log block) as soon as it is known."""
        if self.driver is None and self._http_enabled():
            try:
                self._perform_http()
                run["outcome"] = "recorded over HTTP"
                return "http"
            except NotRecorded as e:
                run["outcome"] = f"not recorded, falling back to the browser: {e}"
                self.say(f"HTTP clock recorded nothing ({e}); falling back to the browser")
            except OutcomeUnknown as e:
                # Retrying could clock twice. Fail, so the failure is reported.
                run["outcome"] = f"OUTCOME UNKNOWN: {e}"
                raise
            except Exception as e:
                # A bug, not a known "nothing sent" case: don't guess, fail loudly.
                run["outcome"] = f"ERROR, no fallback: {type(e).__name__}: {e}"
                raise
            run["fallback"] = True
        else:
            why = ("HTTP not enabled for this action" if self.driver is None
                   else "browser supplied by the caller")
            self._perform_selenium()
            run["outcome"] = f"recorded with the browser ({why})"
            return "browser"
        self._perform_selenium()
        return "browser"

    def _perform_http(self):
        """Clock via a direct HTTP request; the browser is only used to log in
        when the saved session has expired. Raises NotRecorded or OutcomeUnknown
        if it isn't recorded."""
        params, _ = self._new_http_clock().clock_and_verify(self.action_type, self.location)
        self.say(f"HTTP clock action recorded: {params['action']} {params['_descactiv']}")

    def _perform_selenium(self):
        try:
            self._login()

            # Find and click the first button
            self._ensure_button(self.selectors["button1"])
            button1 = self.driver.find_element(By.XPATH, self.selectors["button1"])
            if not self.selectors["button2"]:
                self._check_state_for_single_button()
            self.say("Clicking button 1")
            button1.click()

            # Click the second button if needed
            if self.selectors["button2"]:
                time.sleep(1)  # Small delay to ensure dropdown is visible
                try:
                    button2 = self.driver.find_element(By.XPATH, self.selectors["button2"])
                except NoSuchElementException:
                    self._report_missing_option()
                    raise
                self.say("Clicking button 2")
                button2.click()

            time.sleep(3)
        finally:
            if self.driver:
                self.driver.quit()

    # --- follow-ups ------------------------------------------------------
    def after_action(self):
        """Notifications and Slack status, once the action has been recorded.

        Never raises: the action is already recorded, and a failing follow-up must
        not turn this into a failure (a report, a tempting manual re-run = a double
        clock). Each part is isolated from the other."""
        failed = []
        try:
            failed += self._send_notifications()
        except Exception as e:
            self.say(f"Notifications failed: {describe_error(e, *self._secrets())}")
            failed.append("notifications")
        try:
            if self._update_slack_status() is False:
                failed.append("slack status")
        except Exception as e:
            self.say(f"Slack status failed: {describe_error(e, *self._secrets())}")
            failed.append("slack status")
        if failed:
            self.say("WARNING: the clock action WAS recorded, but these follow-ups failed: "
                     + ", ".join(failed))

    def _send_notifications(self):
        """Returns the names of the channels that did not deliver."""
        manager = NotificationManager(say=self.say)
        for channel in self._channels():
            manager.register_channel(channel)
        return manager.notify(self._get_message())

    def _update_slack_status(self):
        """False if setting the status failed; None when not configured."""
        updater = self._status_updater()
        if updater is None:
            return None
        text, emoji, expiration = status_for(self.action_type, self.location, self._business_trip_end())
        return updater.set_status(text, emoji, expiration)
