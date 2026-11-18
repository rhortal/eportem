"""eportem.core used directly, the way the service will use it: no
environment, no files, another company's activity IDs and another site URL."""
import datetime
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from eportem.core.actions import ClockAction, message_for, selectors_for, status_for
from eportem.core.activities import ActivityIds
from eportem.core.clock_http import ButtonNotFound, HttpClock, NotRecorded, OutcomeUnknown, select_button
from eportem.core.cookies import FileCookieStore, MemoryCookieStore
from eportem.core.target import Target

TARGET = Target("https://eportem.example.test/")
IDS = ActivityIds(office="7", home="8", lunch_pause="9")

NOT_STARTED = """<div id="buttonsRegBox">
<a id="_ststart" name="7" name2="W" name3="Oficina">x</a>
<a id="_ststart" name="8" name2="W" name3="Casa">x</a>
<a id="_ststart" name="9" name2="P" name3="Comida">x</a>
<a id="_ststart" name="1" name2="W" name3="Trabajo">x</a>
</div>"""
WORKING = """<div id="buttonsRegBox">
<a id="_stpause" name="9" name2="P" name3="Comida">x</a>
<a id="_stpause" name="2" name2="P" name3="Ausencia">x</a>
<a id="_ststop" name2="P" name3="Fin">x</a>
</div>"""


def response(url, text, status=200):
    r = requests.Response()
    r.url, r.status_code, r.encoding = url, status, "utf-8"
    r._content = text.encode()
    return r


class Said(list):
    """A `say` that keeps lines instead of printing them."""

    def __call__(self, *args, **kwargs):
        self.append(" ".join(str(a) for a in args))

    def text(self):
        return "\n".join(self)


class TestTarget(unittest.TestCase):

    def test_urls_follow_the_base_url(self):
        self.assertEqual(TARGET.base_url, "https://eportem.example.test")
        self.assertEqual(TARGET.login_url, "https://eportem.example.test/Usuario/Login?ReturnUrl=%2faplicaciones")
        self.assertEqual(TARGET.dashboard_url, "https://eportem.example.test/aplicaciones/e-portem/registro/")
        self.assertEqual(TARGET.clock_url, TARGET.dashboard_url + "reghorario.cshtml")
        self.assertEqual(Target().base_url, "https://eportem.es")

    def test_is_login_page(self):
        self.assertTrue(Target.is_login_page(TARGET.login_url))
        self.assertFalse(Target.is_login_page(TARGET.dashboard_url))
        self.assertFalse(Target.is_login_page(None))


class TestButtonsWithOtherActivityIds(unittest.TestCase):

    def test_start_day_uses_this_accounts_ids(self):
        from eportem.core.clock_http import parse_buttons
        buttons = parse_buttons(NOT_STARTED)
        self.assertEqual(select_button(buttons, "start_day", "office", IDS)["name"], "7")
        self.assertEqual(select_button(buttons, "start_day", "home", IDS)["name"], "8")

    def test_the_owners_ids_are_not_assumed(self):
        from eportem.core.clock_http import parse_buttons
        buttons = parse_buttons('<div id="buttonsRegBox"><a id="_ststart" name="1" name3="T">x</a></div>')
        with self.assertRaises(ButtonNotFound):
            select_button(buttons, "start_day", "office", IDS)

    def test_lunch_uses_the_lunch_pause_id(self):
        from eportem.core.clock_http import parse_buttons
        self.assertEqual(select_button(parse_buttons(WORKING), "lunch_break", "home", IDS)["name3"], "Comida")

    def test_selenium_selectors_use_the_ids(self):
        self.assertIn('@name="8"', selectors_for("start_day", "home", IDS)["button2"])
        self.assertIn('@name="7"', selectors_for("after_lunch", "office", IDS)["button2"])


class TestHttpClockCore(unittest.TestCase):

    def _clock(self, responses, store=None, login_cookies=(("auth", "t"),)):
        session = MagicMock()
        session.headers = {}
        session.cookies = requests.cookies.RequestsCookieJar()
        session.get.side_effect = list(responses)
        driver = MagicMock()
        driver.get_cookies.return_value = [{"name": n, "value": v, "domain": "eportem.example.test", "path": "/"}
                                           for n, v in login_cookies]
        driver.execute_script.return_value = "Browser-UA"
        logins = []
        said = Said()
        clock = HttpClock(session, target=TARGET, activity_ids=IDS, cookie_store=store or MemoryCookieStore(),
                          make_driver=lambda: driver, login_driver=logins.append, say=said)
        return clock, session, driver, logins, said

    def test_no_saved_session_logs_in_then_clocks_on_the_target(self):
        store = MemoryCookieStore()
        clock, session, driver, logins, said = self._clock(
            [response(TARGET.dashboard_url, NOT_STARTED),
             response(TARGET.clock_url, '{"isActive": "W", "LastDescAct": "Oficina"}')], store)
        params, result = clock.clock_and_verify("start_day", "office")
        self.assertEqual(params["_codactiv"], "7")
        self.assertEqual(result["LastDescAct"], "Oficina")
        driver.get.assert_called_once_with(TARGET.login_url)
        self.assertEqual(logins, [driver])
        driver.quit.assert_called_once()
        self.assertEqual([c.args[0] for c in session.get.call_args_list], [TARGET.dashboard_url, TARGET.clock_url])
        self.assertEqual(store.data["user_agent"], "Browser-UA")
        self.assertEqual(store.data["cookies"][0]["name"], "auth")
        self.assertIn("no saved session", said.text())

    def test_saved_session_is_reused_without_a_browser(self):
        store = MemoryCookieStore({"logged_in_at": "2026-11-18T08:00:00", "last_used_at": None,
                                   "cookies": [{"name": "auth", "value": "t"}]})
        clock, session, driver, logins, said = self._clock(
            [response(TARGET.dashboard_url, WORKING), response(TARGET.clock_url, '{"isActive": "P"}')], store)
        clock.clock_and_verify("lunch_break", "office")
        self.assertEqual(logins, [])
        self.assertIn("still valid", said.text())

    def test_wrong_state_is_not_recorded_and_sends_nothing(self):
        clock, session, *_ = self._clock([response(TARGET.dashboard_url, WORKING)])
        with self.assertRaises(NotRecorded):
            clock.clock_and_verify("start_day", "office")
        self.assertEqual(session.get.call_count, 1)

    def test_read_timeout_with_button_still_offered_is_unknown(self):
        clock, *_ = self._clock([response(TARGET.dashboard_url, WORKING),
                                 requests.exceptions.ReadTimeout("slow"),
                                 *[response(TARGET.dashboard_url, WORKING)] * 3])
        clock.verify_pause_seconds = 0
        with self.assertRaises(OutcomeUnknown):
            clock.clock_and_verify("lunch_break", "office")

    def test_without_a_browser_configured_login_fails_clearly(self):
        session = MagicMock()
        session.headers = {}
        clock = HttpClock(session, target=TARGET, activity_ids=IDS, say=Said())
        with self.assertRaisesRegex(RuntimeError, "no browser configured"):
            clock.browser_login()

    def test_nothing_is_printed(self):
        clock, *_ = self._clock([response(TARGET.dashboard_url, WORKING),
                                 response(TARGET.clock_url, '{"isActive": "P"}')])
        with patch("builtins.print") as printed:
            clock.clock_and_verify("lunch_break", "office")
        printed.assert_not_called()


class TestFileCookieStore(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "s.json"

    def test_missing_file_is_none_and_round_trip_works(self):
        store = FileCookieStore(self.path)
        self.assertIsNone(store.load())
        store.save({"cookies": [], "logged_in_at": None})
        self.assertEqual(store.load(), {"cookies": [], "logged_in_at": None})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_old_list_format_takes_mtime_as_login(self):
        self.path.write_text(json.dumps([{"name": "a", "value": "b"}]))
        data = FileCookieStore(self.path).load()
        self.assertEqual(data["cookies"][0]["name"], "a")
        self.assertIsNotNone(datetime.datetime.fromisoformat(data["logged_in_at"]))

    def test_corrupt_file_raises_for_the_caller(self):
        self.path.write_text("{")
        with self.assertRaises(ValueError):
            FileCookieStore(self.path).load()


class FakeHttpClock:
    def __init__(self, outcome):
        self.outcome = outcome

    def clock_and_verify(self, action, location):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return {"action": "_stpause", "_descactiv": "Comida"}, {"isActive": "P"}


class TestClockActionCore(unittest.TestCase):

    def setUp(self):
        p = patch("time.sleep")
        p.start()
        self.addCleanup(p.stop)

    def _action(self, outcome=None, action="lunch_break", location="home", driver_factory=None, **kw):
        self.said, self.records, self.logs = Said(), [], []
        self.channel = MagicMock(name="channel")
        self.channel.name = "test"
        self.channel.send.return_value = True
        self.updater = MagicMock()
        self.updater.set_status.return_value = True
        return ClockAction(
            action, location, activity_ids=IDS, target=TARGET, use_http=True,
            http_clock=lambda: FakeHttpClock(outcome),
            make_driver=driver_factory or (lambda: MagicMock()), login_driver=lambda d: d,
            channels=lambda: [self.channel], status_updater=lambda: self.updater,
            record=lambda *a: self.records.append(a), log_run=lambda *a: self.logs.append(a),
            say=self.said, **kw)

    def test_http_success_records_notifies_and_logs(self):
        self.assertTrue(self._action().perform())
        self.assertEqual(self.records, [("lunch_break", "home", "http")])
        self.channel.send.assert_called_once_with("RePortemed going to lunch break")
        self.updater.set_status.assert_called_once_with("Away for lunch", ":fork_and_knife:", 0)
        (action, location, outcome, output), = self.logs
        self.assertEqual(outcome, "recorded over HTTP")
        self.assertIn("HTTP clock action recorded: _stpause Comida", output)
        self.assertIn("HTTP clock action recorded", self.said.text())

    def test_not_recorded_falls_back_to_the_browser_on_the_target(self):
        driver = MagicMock()
        self._action(NotRecorded("x"), driver_factory=lambda: driver).perform()
        self.assertEqual(self.records, [("lunch_break", "home", "browser")])
        driver.get.assert_any_call(TARGET.login_url)
        driver.find_element.assert_any_call("xpath", '//*[@id="_stpause"]')
        driver.quit.assert_called_once()

    def test_unknown_outcome_never_falls_back(self):
        driver_factory = MagicMock()
        with self.assertRaises(OutcomeUnknown):
            self._action(OutcomeUnknown("?"), driver_factory=driver_factory).perform()
        driver_factory.assert_not_called()
        self.assertEqual(self.records, [])
        self.assertTrue(self.logs[0][2].startswith("OUTCOME UNKNOWN"))

    def test_follow_up_failures_never_fail_the_action(self):
        action = self._action()
        self.channel.send.side_effect = RuntimeError("down xoxb-secret-1")
        self.updater.set_status.return_value = False
        self.assertTrue(action.perform())
        self.assertIn("follow-ups failed: test, slack status", self.said.text())
        self.assertNotIn("xoxb-secret-1", self.said.text())

    def test_no_diagnostics_dir_writes_no_files(self):
        driver = MagicMock()
        driver.page_source = "<html></html>"
        action = self._action(driver_factory=lambda: driver)
        action.driver = driver
        with tempfile.TemporaryDirectory() as cwd, patch("os.getcwd", return_value=cwd):
            action._save_diagnostics()
            self.assertEqual(list(Path(cwd).iterdir()), [])
        driver.save_screenshot.assert_not_called()

    def test_say_is_restored_after_the_run(self):
        action = self._action()
        action.perform()
        self.assertIs(action.say, self.said)

    def test_two_runs_at_once_keep_separate_logs(self):
        """The reason core uses `say` instead of redirecting stdout."""
        barrier = threading.Barrier(2)

        class SlowClock(FakeHttpClock):
            def __init__(self, label, say):
                self.label, self.say = label, say

            def clock_and_verify(self, action, location):
                barrier.wait(timeout=5)
                self.say(f"working for {self.label}")
                barrier.wait(timeout=5)
                return {"action": "_stpause", "_descactiv": self.label}, {}

        logs = {}

        def run(label):
            said = Said()
            action = ClockAction("lunch_break", "office", activity_ids=IDS, target=TARGET, use_http=True,
                                 say=said, log_run=lambda *a: logs.__setitem__(label, a[3]))
            action._new_http_clock = lambda: SlowClock(label, action.say)
            action.perform()

        threads = [threading.Thread(target=run, args=(name,)) for name in ("alice", "bob")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertIn("working for alice", logs["alice"])
        self.assertNotIn("bob", logs["alice"])
        self.assertIn("working for bob", logs["bob"])
        self.assertNotIn("alice", logs["bob"])


class TestMessagesAndStatus(unittest.TestCase):

    def test_status_table(self):
        self.assertEqual(status_for("start_day", "home"), ("Working at home", ":house:", 0))
        self.assertEqual(status_for("after_lunch", "office"), ("Working at office", ":office:", 0))
        self.assertEqual(status_for("stop_day", "office"), ("Done for the day", ":palm_tree:", 0))
        text, emoji, expiration = status_for("stop_day", "office", datetime.date(2026, 12, 1))
        self.assertEqual((text, emoji), ("On a business trip", ":airplane:"))
        self.assertEqual(expiration, int(datetime.datetime(2026, 12, 1, 23, 59).timestamp()))

    def test_messages(self):
        self.assertEqual(message_for("start_day", "home"), "RePortemed at home")
        self.assertEqual(message_for("stop_day", "home"), "RePortemed done for the day")


if __name__ == "__main__":
    unittest.main()
