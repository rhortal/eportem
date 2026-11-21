"""Real headless Chromium against the fake ePortem: the login form (with the
stub reCAPTCHA), the Selenium click flow for every action, the HTTP clock after
a browser login, and the browser fallback. Skipped when no browser can start."""
import time
import unittest
from unittest.mock import patch

from checkin.core import browser
from checkin.core.actions import ClockAction
from checkin.core.activities import ActivityIds
from checkin.core.clock_http import HttpClock
from checkin.core.cookies import MemoryCookieStore
from checkin.core.target import Target
from fake_eportem import Account, FakeEportem, Fault

IDS = ActivityIds(office="7", home="8", lunch_pause="9")
_real_sleep = time.sleep
_browser_error = None


def _quiet(*args, **kwargs):
    pass


def _make_driver():
    return browser.create_driver(headless=True, say=_quiet)


def setUpModule():
    global _browser_error
    try:
        _make_driver().quit()
    except Exception as e:  # no Chrome, no driver, no display...
        _browser_error = f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}"


class BrowserCase(unittest.TestCase):

    def setUp(self):
        if _browser_error:
            self.skipTest(f"no browser: {_browser_error}")
        self.fake = FakeEportem([Account("ALICE", "a-pw", IDS)], recaptcha=True).start()
        self.addCleanup(self.fake.stop)
        self.target = Target(self.fake.base_url)
        # The engine's fixed pauses (login, dropdown, after clicking) are for the real
        # site; the fake needs none. Keep a tiny real sleep so waits still yield.
        # Waits that only matter on the real site, kept short so a broken flow
        # fails in seconds instead of retrying for ten minutes.
        for p in (patch("time.sleep", lambda s: _real_sleep(min(s, 0.05))),
                  patch.object(browser, "LOGIN_WAIT_SECONDS", 3),
                  patch.object(ClockAction, "retry_budget_seconds", 5),
                  patch.object(ClockAction, "button_wait_seconds", 3)):
            p.start()
            self.addCleanup(p.stop)

    def login(self, driver):
        browser.login(driver, "alice", "a-pw")  # lower case: the form upper-cases it
        return driver

    def events(self):
        return [(e["action"], e["codactiv"]) for e in self.fake.events_for("ALICE")]

    def click_action(self, action, location):
        ClockAction(action, location, activity_ids=IDS, target=self.target,
                    make_driver=_make_driver, login_driver=self.login, say=_quiet).perform()


class TestBrowserLogin(BrowserCase):

    def test_login_passes_the_stub_recaptcha_and_lands_on_the_app(self):
        driver = browser.open_and_login(self.target, "alice", "a-pw", _make_driver)
        try:
            self.assertFalse(Target.is_login_page(driver.current_url))
            self.assertIn(".ASPXAUTH", {c["name"] for c in driver.get_cookies()})
        finally:
            driver.quit()

    def test_wrong_password_is_rejected(self):
        with self.assertRaises(browser.LoginRejected):
            browser.open_and_login(self.target, "alice", "nope", _make_driver).quit()


class TestClickFlow(BrowserCase):

    def test_office_day_by_clicking(self):
        for action in ("start_day", "lunch_break", "after_lunch", "stop_day"):
            self.click_action(action, "office")
        self.assertEqual(self.events(), [("_ststart", "7"), ("_stpause", "9"), ("_stini", "7"), ("_ststop", "")])

    def test_home_day_by_clicking(self):
        for action in ("start_day", "lunch_break", "after_lunch", "stop_day"):
            self.click_action(action, "home")
        self.assertEqual(self.events(), [("_ststart", "8"), ("_stpause", "9"), ("_stini", "8"), ("_ststop", "")])

    def test_already_started_office_day_is_not_clicked_again(self):
        from checkin.core.actions import ActionNotApplicable
        self.click_action("start_day", "office")
        with self.assertRaises(ActionNotApplicable):
            self.click_action("start_day", "office")
        self.assertEqual(len(self.events()), 1)


class TestHttpWithBrowserLogin(BrowserCase):

    def clock(self):
        return HttpClock(target=self.target, activity_ids=IDS, cookie_store=self.store,
                         make_driver=_make_driver, login_driver=self.login, say=_quiet)

    def setUp(self):
        super().setUp()
        self.store = MemoryCookieStore()

    def test_browser_login_then_http_clock(self):
        self.clock().clock_and_verify("start_day", "home")
        self.clock().clock_and_verify("lunch_break", "home")
        self.assertEqual(self.events(), [("_ststart", "8"), ("_stpause", "9")])
        self.assertEqual(self.fake.accounts["ALICE"].logins, 1)
        self.assertIn("Chrome/", self.store.data["user_agent"])
        self.assertNotIn("HeadlessChrome", self.store.data["user_agent"])

    def test_not_recorded_over_http_falls_back_to_clicking(self):
        self.fake.add_fault(Fault("clock", "error_500"))  # HTTP send fails, nothing recorded
        records = []
        ClockAction("start_day", "office", activity_ids=IDS, target=self.target, use_http=True,
                    http_clock=self.clock, make_driver=_make_driver, login_driver=self.login,
                    record=lambda *a: records.append(a), say=_quiet).perform()
        self.assertEqual(records, [("start_day", "office", "browser")])
        self.assertEqual(self.events(), [("_ststart", "7")])


if __name__ == "__main__":
    unittest.main()
