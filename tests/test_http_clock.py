import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import unittest
from unittest.mock import MagicMock, patch

from utility import http_clock
from utility.http_clock import (HttpClock, ButtonNotFound, SessionExpired,
                                parse_buttons, select_button, build_params,
                                CLOCK_URL, DASHBOARD_URL)

# #buttonsRegBox as captured from the live dashboard while working (2026-11-16),
# trimmed to the clock buttons.
WORKING_HTML = """
<div id="buttonsRegBox"><ul class="dropdown-menu">
<li><a id="_stpause" name="2" name2="P" name3="Comida" onclick="_doPostJor(this)">Comida</a></li>
<li><a id="_stpause" name="3" name2="P" name3="Ausencia" onclick="_doPostJor(this)">Ausencia</a></li>
<li><a id="_stini" name="1293" name2="W" name3="Trabajo en Casa" onclick="_doPostJor(this)">Casa</a></li>
<li><a id="_ststop" name2="P" name3="Inicio Trabajo" onclick="_doPostJor(this)">Terminar</a></li>
</ul></div>
"""

# Not yet captured from the live site: modelled on the Selenium XPaths
# (a direct office start button plus a home entry in a dropdown).
NOT_STARTED_HTML = """
<div id="buttonsRegBox"><div class="btn-group">
<button id="_ststart" name="1" name2="W" name3="Inicio Trabajo" onclick="_doPostJor(this)">Inicio</button>
<button data-toggle="dropdown"></button>
<ul><li><a id="_ststart" name="1293" name2="W" name3="Trabajo en Casa" onclick="_doPostJor(this)">Casa</a></li></ul>
</div></div>
"""

PAUSED_HTML = """
<div id="buttonsRegBox">
<a id="_stini" name="1" name2="W" name3="Trabajo" onclick="_doPostJor(this)">Oficina</a>
<a id="_stini" name="1293" name2="W" name3="Trabajo en Casa" onclick="_doPostJor(this)">Casa</a>
<a id="_ststop" name2="P" name3="Inicio Trabajo" onclick="_doPostJor(this)">Terminar</a>
</div>
"""


class TestButtonSelection(unittest.TestCase):

    def test_parse_ignores_non_clock_elements(self):
        buttons = parse_buttons(NOT_STARTED_HTML)
        self.assertEqual([b["id"] for b in buttons], ["_ststart", "_ststart"])

    def test_lunch_break_picks_comida(self):
        b = select_button(parse_buttons(WORKING_HTML), "lunch_break", "office")
        self.assertEqual(build_params(b), {
            "action": "_stpause", "_codactiv": "2", "_tipoactiv": "P",
            "_descactiv": "Comida", "_geolocation": "", "_localip": ""})

    def test_stop_day_sends_empty_codactiv(self):
        b = select_button(parse_buttons(WORKING_HTML), "stop_day", "home")
        params = build_params(b)
        self.assertEqual(params["action"], "_ststop")
        self.assertEqual(params["_codactiv"], "")

    def test_start_day_office_and_home(self):
        buttons = parse_buttons(NOT_STARTED_HTML)
        self.assertEqual(select_button(buttons, "start_day", "office")["name"], "1")
        self.assertEqual(select_button(buttons, "start_day", "home")["name"], "1293")

    def test_start_day_office_without_name_falls_back_to_non_home(self):
        buttons = [{"id": "_ststart"}, {"id": "_ststart", "name": "1293"}]
        self.assertNotIn("name", select_button(buttons, "start_day", "office"))

    def test_after_lunch_by_location(self):
        buttons = parse_buttons(PAUSED_HTML)
        self.assertEqual(select_button(buttons, "after_lunch", "office")["name"], "1")
        self.assertEqual(select_button(buttons, "after_lunch", "home")["name"], "1293")

    def test_lunch_break_without_comida_does_not_pick_another_pause(self):
        html = '<div id="buttonsRegBox"><a id="_stpause" name="3" name3="Ausencia"></a></div>'
        with self.assertRaises(ButtonNotFound) as cm:
            select_button(parse_buttons(html), "lunch_break", "office")
        self.assertIn("Ausencia", str(cm.exception))

    def test_unknown_location_raises(self):
        for location in ("Home", "", None, "remote"):
            with self.assertRaises(ValueError):
                select_button(parse_buttons(WORKING_HTML), "stop_day", location)

    def test_wrong_state_raises_instead_of_guessing(self):
        with self.assertRaises(ButtonNotFound):
            select_button(parse_buttons(WORKING_HTML), "after_lunch", "office")
        with self.assertRaises(ButtonNotFound):
            select_button(parse_buttons(WORKING_HTML), "start_day", "office")


def _response(url, text="", status=200):
    """A real requests.Response, so raise_for_status() really raises for 4xx/5xx."""
    import requests
    r = requests.Response()
    r.url, r.status_code, r.encoding = url, status, "utf-8"
    r._content = text.encode("utf-8")
    return r


class TestHttpClock(unittest.TestCase):

    def setUp(self):
        # Never touch the real cookie file.
        for name in ("load_cookies", "save_cookies"):
            p = patch.object(HttpClock, name, return_value=True)
            p.start()
            self.addCleanup(p.stop)

    def _clock(self, *responses):
        session = MagicMock()
        session.headers = {}
        session.get.side_effect = list(responses)
        return HttpClock(session), session

    def test_dry_run_never_requests_clock_url(self):
        clock, session = self._clock(_response(DASHBOARD_URL, WORKING_HTML))
        params, result = clock.clock("lunch_break", "office", send=False)
        self.assertIsNone(result)
        self.assertEqual(params["action"], "_stpause")
        urls = [c.args[0] for c in session.get.call_args_list]
        self.assertNotIn(CLOCK_URL, urls)

    def test_send_requests_clock_url_with_params(self):
        clock, session = self._clock(
            _response(DASHBOARD_URL, WORKING_HTML),
            _response(CLOCK_URL, '{"isActive": "P", "LastDescAct": "Comida"}'))
        params, result = clock.clock("lunch_break", "office", send=True)
        self.assertEqual(result["LastDescAct"], "Comida")
        call = session.get.call_args_list[-1]
        self.assertEqual(call.args[0], CLOCK_URL)
        self.assertEqual(call.kwargs["params"], params)

    def test_expired_session_logs_in_with_browser(self):
        login_url = "https://eportem.es/Usuario/Login?ReturnUrl=%2faplicaciones"
        clock, session = self._clock(
            _response(login_url, '<form id="login-form">'),
            _response(DASHBOARD_URL, WORKING_HTML))
        with patch.object(HttpClock, "browser_login") as login:
            clock.clock("stop_day", "office", send=False)
        login.assert_called_once()

    def test_fetch_buttons_detects_login_page(self):
        clock, _ = self._clock(_response("https://eportem.es/Usuario/Login", ""))
        with self.assertRaises(SessionExpired):
            clock.fetch_buttons()


    def test_fetch_buttons_http_error_raises(self):
        import requests
        for status in (404, 500, 503):
            clock, _ = self._clock(_response(DASHBOARD_URL, WORKING_HTML, status))
            with self.assertRaises(requests.HTTPError):
                clock.fetch_buttons()

    def test_fetch_buttons_rejects_page_without_dashboard_marker(self):
        clock, _ = self._clock(_response(DASHBOARD_URL, "<html>Mantenimiento</html>"))
        with self.assertRaises(http_clock.DashboardUnreadable):
            clock.fetch_buttons()

    def test_fetch_buttons_genuine_empty_box_returns_no_buttons(self):
        clock, _ = self._clock(_response(DASHBOARD_URL, '<div id="buttonsRegBox"></div>'))
        self.assertEqual(clock.fetch_buttons(), [])

    def test_resolve_on_maintenance_page_raises_before_sending(self):
        clock, session = self._clock(_response(DASHBOARD_URL, "<html>Error</html>"))
        with self.assertRaises(http_clock.DashboardUnreadable):
            clock.resolve("lunch_break", "office")
        session.get.assert_called_once()

    def test_clock_and_verify_maintenance_page_before_send_is_not_recorded(self):
        clock, session = self._clock(_response(DASHBOARD_URL, "<html>Error</html>"))
        with patch("builtins.print"), self.assertRaises(http_clock.NotRecorded):
            clock.clock_and_verify("lunch_break", "office")
        self.assertNotIn(CLOCK_URL, [c.args[0] for c in session.get.call_args_list])

    def test_is_recorded_on_maintenance_page_raises_not_true(self):
        clock, _ = self._clock(_response(DASHBOARD_URL, "<html>Error</html>"))
        with self.assertRaises(http_clock.DashboardUnreadable):
            clock.is_recorded({"action": "_stpause", "_codactiv": "2"})

    def test_is_recorded_on_empty_dashboard_raises(self):
        clock, _ = self._clock(_response(DASHBOARD_URL, '<div id="buttonsRegBox"></div>'))
        with self.assertRaises(http_clock.DashboardUnreadable):
            clock.is_recorded({"action": "_stpause", "_codactiv": "2"})

    def test_send_sends_ajax_headers(self):
        clock, session = self._clock(_response(CLOCK_URL, '{"isActive": "P"}'))
        clock.send({"action": "_stpause"})
        headers = session.get.call_args.kwargs["headers"]
        self.assertEqual(headers["X-Requested-With"], "XMLHttpRequest")
        self.assertEqual(headers["Referer"], DASHBOARD_URL)

    def test_send_http_error_raises(self):
        import requests
        for status in (403, 500):
            clock, _ = self._clock(_response(CLOCK_URL, '{"isActive": "P"}', status))
            with self.assertRaises(requests.HTTPError):
                clock.send({"action": "_stpause"})

    def test_send_accepts_documented_keys_only_by_presence(self):
        for body in ('{"isActive": "P"}', '{"LastDescAct": "x"}', '{"listActiv": "<a/>"}'):
            clock, _ = self._clock(_response(CLOCK_URL, body))
            self.assertIsInstance(clock.send({"action": "a"}), dict)

    def test_send_rejects_bodies_that_are_not_clock_results(self):
        bodies = ['<html><form id="login-form"></form></html>', "null", "[]", "{}",
                  '{"error": "boom"}', '[{"isActive": 1}]', "", "42"]
        for body in bodies:
            clock, _ = self._clock(_response(CLOCK_URL, body))
            with patch("builtins.print"), patch.object(HttpClock, "save_cookies") as save:
                with self.assertRaises(http_clock.UnexpectedResponse, msg=body):
                    clock.send({"action": "a"})
            save.assert_not_called()

    def test_send_logs_truncated_unexpected_body(self):
        clock, _ = self._clock(_response(CLOCK_URL, "x" * 1000))
        with patch("builtins.print") as out, self.assertRaises(http_clock.UnexpectedResponse):
            clock.send({"action": "a"})
        printed = " ".join(str(a) for c in out.call_args_list for a in c.args)
        self.assertIn("x" * 300, printed)
        self.assertNotIn("x" * 301, printed)

    def test_cookie_save_failure_after_successful_send_is_only_a_warning(self):
        clock, _ = self._clock(_response(CLOCK_URL, '{"isActive": "P"}'))
        with patch.object(HttpClock, "save_cookies", side_effect=OSError("disk full")), \
             patch("builtins.print") as out:
            result = clock.send({"action": "a"})
        self.assertEqual(result, {"isActive": "P"})
        self.assertIn("warning", " ".join(str(a) for c in out.call_args_list for a in c.args))


class TestHttpEnabledFor(unittest.TestCase):

    def _enabled(self, value, action):
        from eportem_action import http_enabled_for
        env = {} if value is None else {"EPORTEM_HTTP": value}
        with patch.dict(os.environ, env):
            if value is None:
                os.environ.pop("EPORTEM_HTTP", None)
            return http_enabled_for(action)

    def test_values(self):
        self.assertTrue(self._enabled("YES", "start_day"))
        self.assertTrue(self._enabled("all", "stop_day"))
        self.assertFalse(self._enabled("NO", "lunch_break"))
        self.assertFalse(self._enabled(None, "lunch_break"))
        self.assertTrue(self._enabled("lunch_break, after_lunch", "after_lunch"))
        self.assertFalse(self._enabled("lunch_break,after_lunch", "start_day"))


class TestEportemActionRouting(unittest.TestCase):
    """EPortemAction.perform() is the one place that picks HTTP or the browser."""

    ENV = {"EPORTEM_ENABLED": "YES", "TELEGRAM_NOTIFY": "NO",
           "SLACK_NOTIFY": "NO", "SLACK_STATUS": "NO"}
    PARAMS = {"action": "_ststop", "_descactiv": "x"}

    def setUp(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.log = os.path.join(tmp.name, "http_clock.log")
        for p in (patch("eportem_action.HTTP_LOG", self.log), patch("builtins.print")):
            p.start()
            self.addCleanup(p.stop)

    def _perform(self, http, verify, raises=None):
        """With raises=<exception class>, perform() must raise it; returns the mocks either way."""
        from eportem_action import EPortemAction
        with patch.dict(os.environ, {**self.ENV, "EPORTEM_HTTP": http}), \
             patch.object(http_clock.HttpClock, "clock_and_verify", side_effect=verify) as cv, \
             patch.object(EPortemAction, "_perform_selenium") as selenium, \
             patch.object(EPortemAction, "after_action") as after:
            if raises:
                with self.assertRaises(raises):
                    EPortemAction("stop_day", "office").perform()
            else:
                EPortemAction("stop_day", "office").perform()
        return cv, selenium, after

    def _log(self):
        with open(self.log) as f:
            return f.read()

    def test_recorded_over_http_skips_browser(self):
        cv, selenium, after = self._perform("YES", lambda *a: (self.PARAMS, {}))
        cv.assert_called_once_with("stop_day", "office")
        selenium.assert_not_called()
        after.assert_called_once()
        self.assertIn("stop_day office: recorded over HTTP", self._log())

    def test_not_recorded_falls_back_to_browser(self):
        cv, selenium, after = self._perform("YES", http_clock.NotRecorded("ButtonNotFound"))
        selenium.assert_called_once()
        after.assert_called_once()
        self.assertIn("falling back to the browser: ButtonNotFound", self._log())

    def test_unknown_outcome_raises_without_fallback(self):
        cv, selenium, after = self._perform(
            "YES", http_clock.OutcomeUnknown("check by hand"), raises=http_clock.OutcomeUnknown)
        selenium.assert_not_called()  # a browser retry could clock twice
        after.assert_not_called()
        self.assertIn("OUTCOME UNKNOWN", self._log())

    def test_unexpected_error_raises_without_fallback(self):
        cv, selenium, after = self._perform("YES", RuntimeError("boom"), raises=RuntimeError)
        selenium.assert_not_called()
        after.assert_not_called()
        self.assertIn("ERROR", self._log())

    def test_action_not_listed_uses_browser_only(self):
        cv, selenium, after = self._perform("lunch_break", None)
        cv.assert_not_called()
        selenium.assert_called_once()
        after.assert_called_once()

    def test_given_driver_always_uses_browser(self):
        from eportem_action import EPortemAction
        with patch.dict(os.environ, {**self.ENV, "EPORTEM_HTTP": "YES"}), \
             patch.object(http_clock.HttpClock, "clock_and_verify") as cv, \
             patch.object(EPortemAction, "_perform_selenium") as selenium:
            EPortemAction("stop_day", "office", MagicMock()).perform()
        cv.assert_not_called()
        selenium.assert_called_once()


class TestClockAndVerify(unittest.TestCase):
    """Which exception comes out decides whether a Selenium fallback runs, so a
    request that may have been recorded must never raise NotRecorded."""

    PARAMS = {"action": "_stpause", "_codactiv": "2", "_tipoactiv": "P",
              "_descactiv": "Comida", "_geolocation": "", "_localip": ""}

    def setUp(self):
        for name in ("VERIFY_PAUSE_SECONDS",):
            p = patch.object(http_clock, name, 0)
            p.start()
            self.addCleanup(p.stop)

    def _verify(self, resolve=None, send=None, recorded=None):
        clock = HttpClock(MagicMock(headers={}))
        r = patch.object(clock, "resolve", side_effect=resolve or (lambda *a: self.PARAMS))
        s = patch.object(clock, "send", side_effect=send or (lambda p: {"isActive": "P"}))
        i = (patch.object(clock, "is_recorded", side_effect=recorded)
             if isinstance(recorded, Exception)
             else patch.object(clock, "is_recorded", return_value=recorded))
        with r, s as send_mock, i, patch("builtins.print"):
            return clock.clock_and_verify("lunch_break", "office"), send_mock

    def test_success(self):
        (params, result), send = self._verify()
        self.assertEqual(result, {"isActive": "P"})
        send.assert_called_once()

    def test_failure_before_sending_is_not_recorded(self):
        with self.assertRaises(http_clock.NotRecorded):
            self._verify(resolve=ButtonNotFound("x"))

    def test_send_error_but_button_still_there_is_not_recorded(self):
        with self.assertRaises(http_clock.NotRecorded):
            self._verify(send=ValueError("bad json"), recorded=False)

    def test_send_error_but_recorded_is_success(self):
        (params, result), _ = self._verify(send=ValueError("bad json"), recorded=True)
        self.assertIsNone(result)

    def test_send_error_and_dashboard_unreadable_is_unknown(self):
        with self.assertRaises(http_clock.OutcomeUnknown):
            self._verify(send=ValueError("x"), recorded=SessionExpired("x"))

    def _settle(self, send_error, states):
        """clock_and_verify with a failing send and is_recorded answering `states` in turn."""
        clock = HttpClock(MagicMock(headers={}))
        with patch.object(clock, "resolve", return_value=self.PARAMS), \
             patch.object(clock, "send", side_effect=send_error), \
             patch.object(clock, "is_recorded", side_effect=states) as rec, \
             patch.object(http_clock.time, "sleep") as sleep, patch("builtins.print"):
            try:
                out = clock.clock_and_verify("lunch_break", "office")
            except Exception as e:
                out = e
        return out, rec, sleep

    def test_settling_recorded_on_a_later_check_is_recorded(self):
        out, rec, sleep = self._settle(ValueError("x"), [False, False, True])
        self.assertEqual(out, (self.PARAMS, None))
        self.assertEqual(rec.call_count, 3)

    def test_settling_stops_at_first_recorded(self):
        out, rec, sleep = self._settle(ValueError("x"), [True])
        self.assertEqual(rec.call_count, 1)
        sleep.assert_not_called()

    def test_settling_pauses_between_checks_and_exhausts_attempts(self):
        with patch.object(http_clock, "VERIFY_PAUSE_SECONDS", 5):
            out, rec, sleep = self._settle(ValueError("x"), [False] * 3)
        self.assertIsInstance(out, http_clock.NotRecorded)
        self.assertEqual(rec.call_count, http_clock.VERIFY_ATTEMPTS)
        self.assertEqual(sleep.call_count, http_clock.VERIFY_ATTEMPTS - 1)
        sleep.assert_called_with(5)

    def test_http_5xx_with_button_still_offered_is_not_recorded(self):
        import requests
        out, _, _ = self._settle(requests.HTTPError("503"), [False] * 3)
        self.assertIsInstance(out, http_clock.NotRecorded)

    def test_unexpected_body_goes_through_verification(self):
        U = http_clock.UnexpectedResponse
        self.assertIsInstance(self._settle(U("x"), [False] * 3)[0], http_clock.NotRecorded)
        self.assertEqual(self._settle(U("x"), [True])[0], (self.PARAMS, None))
        self.assertIsInstance(self._settle(U("x"), [SessionExpired("x")])[0],
                              http_clock.OutcomeUnknown)

    def test_read_timeout_with_button_still_offered_is_unknown(self):
        import requests
        out, rec, _ = self._settle(requests.exceptions.ReadTimeout("slow"), [False] * 3)
        self.assertIsInstance(out, http_clock.OutcomeUnknown)
        self.assertEqual(rec.call_count, 3)

    def test_read_timeout_recorded_after_settling_is_success(self):
        import requests
        out, _, _ = self._settle(requests.exceptions.ReadTimeout("slow"), [False, True])
        self.assertEqual(out, (self.PARAMS, None))

    def test_connect_errors_before_sending_stay_not_recorded(self):
        import requests
        from urllib3.exceptions import NewConnectionError
        refused = requests.exceptions.ConnectionError(
            MagicMock(reason=NewConnectionError(None, "refused")))
        for err in (requests.exceptions.ConnectTimeout("t"), refused):
            out, _, _ = self._settle(err, [False] * 3)
            self.assertIsInstance(out, http_clock.NotRecorded, type(err))

    def test_dropped_connection_after_sending_is_unknown(self):
        import requests
        out, _, _ = self._settle(
            requests.exceptions.ConnectionError("Connection aborted: RemoteDisconnected"),
            [False] * 3)
        self.assertIsInstance(out, http_clock.OutcomeUnknown)

    def test_dashboard_unreadable_while_settling_is_unknown(self):
        out, _, _ = self._settle(ValueError("x"), [False, http_clock.DashboardUnreadable("x")])
        self.assertIsInstance(out, http_clock.OutcomeUnknown)

    def test_unknown_location_is_not_recorded_and_sends_nothing(self):
        session = MagicMock(headers={})
        session.get.return_value = _response(DASHBOARD_URL, WORKING_HTML)
        clock = HttpClock(session)
        with patch.object(HttpClock, "load_cookies", return_value=True), \
             patch.object(HttpClock, "save_cookies"), patch("builtins.print"):
            with self.assertRaises(http_clock.NotRecorded):
                clock.clock_and_verify("stop_day", "mars")
        self.assertNotIn(CLOCK_URL, [c.args[0] for c in session.get.call_args_list])

    def test_real_send_with_login_page_body_then_dashboard_still_offering_is_not_recorded(self):
        session = MagicMock(headers={})
        session.get.side_effect = [
            _response(DASHBOARD_URL, WORKING_HTML),                     # resolve
            _response(CLOCK_URL, '<form id="login-form"></form>'),     # send: 200 HTML
            *[_response(DASHBOARD_URL, WORKING_HTML)] * 3]              # settle checks
        clock = HttpClock(session)
        with patch.object(HttpClock, "load_cookies", return_value=True), \
             patch.object(HttpClock, "save_cookies"), patch("builtins.print"), \
             self.assertRaises(http_clock.NotRecorded):
            clock.clock_and_verify("lunch_break", "office")

    def test_is_recorded_checks_button_presence(self):
        session = MagicMock()
        session.headers = {}
        session.get.return_value = _response(DASHBOARD_URL, WORKING_HTML)
        clock = HttpClock(session)
        self.assertFalse(clock.is_recorded(self.PARAMS))  # pause still offered
        self.assertTrue(clock.is_recorded({**self.PARAMS, "action": "_ststart", "_codactiv": "1"}))


class TestCliExitCodes(unittest.TestCase):

    def _run(self, *argv, verify=None, enabled="YES"):
        clock = MagicMock()
        clock.resolve.return_value = TestClockAndVerify.PARAMS
        clock.clock_and_verify.side_effect = verify or (lambda *a: (TestClockAndVerify.PARAMS, {}))
        with patch.object(http_clock, "HttpClock", return_value=clock), \
             patch("utility.env_loader.load_environment"), \
             patch.dict(os.environ, {"EPORTEM_ENABLED": enabled}), \
             patch.object(sys, "argv", ["http_clock", "lunch_break", *argv]), \
             patch("builtins.print"):
            return http_clock.main(), clock

    def test_dry_run_does_not_send(self):
        rc, clock = self._run()
        self.assertEqual(rc, http_clock.EXIT_RECORDED)
        clock.clock_and_verify.assert_not_called()

    def test_send_outcomes(self):
        self.assertEqual(self._run("--send")[0], http_clock.EXIT_RECORDED)
        self.assertEqual(self._run("--send", verify=http_clock.NotRecorded("x"))[0],
                         http_clock.EXIT_NOT_RECORDED)
        self.assertEqual(self._run("--send", verify=http_clock.OutcomeUnknown("x"))[0],
                         http_clock.EXIT_UNKNOWN)

    def test_send_refused_unless_enabled(self):
        for value in ("NO", "", "yes"):
            rc, clock = self._run("--send", enabled=value)
            self.assertEqual(rc, http_clock.EXIT_NOT_RECORDED)
            clock.clock_and_verify.assert_not_called()

    def test_dry_run_allowed_when_disabled(self):
        rc, clock = self._run(enabled="NO")
        self.assertEqual(rc, http_clock.EXIT_RECORDED)
        clock.resolve.assert_called_once()

    def test_notify_failure_is_reported(self):
        with patch("eportem_action.EPortemAction.after_action", side_effect=RuntimeError("slack")):
            rc, _ = self._run("--send", "--notify")
        self.assertEqual(rc, http_clock.EXIT_NOTIFY_FAILED)


class TestCookieFile(unittest.TestCase):

    def setUp(self):
        import tempfile, pathlib
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = pathlib.Path(self.dir.name) / "cookies.json"

    def test_round_trip_keeps_login_time_and_sets_last_used(self):
        import datetime, json
        clock = HttpClock(requests_session())
        clock.session.cookies.set(".ASPXAUTH", "abc", domain="eportem.es", path="/")
        clock.logged_in_at = datetime.datetime(2026, 11, 16, 10, 27)
        clock.save_cookies(self.path)
        self.assertEqual(oct(self.path.stat().st_mode & 0o777), "0o600")
        data = json.loads(self.path.read_text())
        self.assertEqual(data["logged_in_at"], "2026-11-16T10:27:00")
        self.assertIsNotNone(data["last_used_at"])

        again = HttpClock(requests_session())
        self.assertTrue(again.load_cookies(self.path))
        self.assertEqual(again.logged_in_at, datetime.datetime(2026, 11, 16, 10, 27))
        self.assertEqual(again.session.cookies.get(".ASPXAUTH"), "abc")

    def test_old_list_format_uses_file_time_as_login(self):
        import json
        self.path.write_text(json.dumps([{"name": "a", "value": "b", "domain": "eportem.es", "path": "/"}]))
        clock = HttpClock(requests_session())
        self.assertTrue(clock.load_cookies(self.path))
        self.assertIsNotNone(clock.logged_in_at)
        self.assertIsNone(clock.last_used_at)
        self.assertIn("last used unknown", clock._session_age())

    def test_corrupt_files_are_ignored_and_clear_partial_state(self):
        import json
        cookie = {"name": "a", "value": "b", "domain": "eportem.es", "path": "/"}
        bad = {
            "truncated": '{"logged_in_at": "2026-11-16T10:27:00", "cooki',
            "empty": "",
            "missing cookies": json.dumps({"logged_in_at": None}),
            "bad timestamp": json.dumps({"logged_in_at": "yesterday", "cookies": [cookie]}),
            "timestamp type": json.dumps({"logged_in_at": 5, "cookies": [cookie]}),
            "cookies not a list": json.dumps({"cookies": 3}),
            "cookie missing value": json.dumps({"cookies": [cookie, {"name": "x"}]}),
            "cookie wrong types": json.dumps({"cookies": [cookie, {"name": 1, "value": 2}]}),
            "json scalar": "42",
        }
        for label, text in bad.items():
            self.path.write_text(text)
            clock = HttpClock(requests_session())
            with patch("builtins.print") as out:
                self.assertFalse(clock.load_cookies(self.path), label)
            self.assertEqual(len(clock.session.cookies), 0, label)  # nothing half-loaded
            self.assertIsNone(clock.logged_in_at, label)
            self.assertEqual(out.call_count, 1, label)
            self.assertIn("unreadable", out.call_args.args[0])

    def test_corrupt_file_triggers_browser_login_and_is_rewritten(self):
        self.path.write_text('{"cookies": [')
        clock = HttpClock(requests_session())
        def fake_login(self_):
            self_.session.cookies.set("a", "b", domain="eportem.es", path="/")
            self_.logged_in_at = __import__("datetime").datetime(2026, 11, 16, 9, 0)
            self_.save_cookies()
        with patch.object(http_clock, "COOKIE_FILE", self.path), \
             patch.object(HttpClock, "browser_login", fake_login), \
             patch.object(HttpClock, "fetch_buttons", return_value=[]), patch("builtins.print"):
            clock.ensure_session()
        again = HttpClock(requests_session())
        self.assertTrue(again.load_cookies(self.path))

    def test_save_is_atomic_and_mode_600(self):
        import json, os
        self.path.write_text("old")
        os.chmod(self.path, 0o644)
        clock = HttpClock(requests_session())
        clock.save_cookies(self.path)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        json.loads(self.path.read_text())
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["cookies.json"])  # no temp left

    def test_failed_write_keeps_old_file_and_removes_temp(self):
        self.path.write_text('{"cookies": []}')
        clock = HttpClock(requests_session())
        with patch.object(http_clock.os, "replace", side_effect=OSError("nope")):
            with self.assertRaises(OSError):
                clock.save_cookies(self.path)
        self.assertEqual(self.path.read_text(), '{"cookies": []}')
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["cookies.json"])

    def test_default_path_is_resolved_at_call_time(self):
        clock = HttpClock(requests_session())
        with patch.object(http_clock, "COOKIE_FILE", self.path):
            clock.save_cookies()
            self.assertTrue(self.path.exists())
            self.assertTrue(HttpClock(requests_session()).load_cookies())

    def test_user_agent_round_trip_and_old_files(self):
        import json
        clock = HttpClock(requests_session())
        clock.user_agent = "UA-from-login-browser"
        clock.save_cookies(self.path)
        again = HttpClock(requests_session())
        again.load_cookies(self.path)
        self.assertEqual(again.session.headers["User-Agent"], "UA-from-login-browser")
        old = HttpClock(requests_session())
        self.path.write_text(json.dumps({"cookies": []}))
        old.load_cookies(self.path)
        self.assertEqual(old.session.headers["User-Agent"], http_clock.USER_AGENT)

    def test_real_session_gets_browser_user_agent(self):
        self.assertEqual(HttpClock().session.headers["User-Agent"], http_clock.USER_AGENT)
        self.assertEqual(HttpClock(requests_session()).session.headers["User-Agent"],
                         http_clock.USER_AGENT)

    def test_explicit_user_agent_on_a_passed_session_is_kept(self):
        s = requests_session()
        s.headers["User-Agent"] = "mine"
        self.assertEqual(HttpClock(s).session.headers["User-Agent"], "mine")

    def test_valid_session_is_logged_and_resaved(self):
        session = MagicMock()
        session.headers = {}
        session.get.return_value = _response(DASHBOARD_URL, WORKING_HTML)
        clock = HttpClock(session)
        with patch.object(HttpClock, "load_cookies", return_value=True), \
             patch.object(HttpClock, "save_cookies") as save, \
             patch("builtins.print") as out:
            clock.ensure_session()
        save.assert_called_once()
        self.assertIn("still valid", out.call_args_list[0].args[0])


class TestBrowserLogin(unittest.TestCase):
    """browser_login must quit the browser it creates on every path."""

    def _login(self, login_side_effect=None, ua="Chrome-UA"):
        driver = MagicMock()
        driver.get_cookies.return_value = [{"name": "a", "value": "b", "domain": "eportem.es", "path": "/"}]
        driver.execute_script.return_value = ua
        clock = HttpClock(requests_session())
        with patch.object(http_clock, "create_driver", return_value=driver) as create, \
             patch.object(http_clock, "login_and_navigate",
                          side_effect=login_side_effect) as login, \
             patch.object(HttpClock, "save_cookies") as save:
            try:
                clock.browser_login()
                error = None
            except Exception as e:
                error = e
        return clock, driver, create, login, save, error

    def test_success_quits_uses_given_driver_and_keeps_user_agent(self):
        clock, driver, create, login, save, error = self._login()
        self.assertIsNone(error)
        create.assert_called_once()
        driver.get.assert_called_once_with(http_clock.LOGIN_URL)
        login.assert_called_once_with(driver)
        driver.quit.assert_called_once()
        save.assert_called_once()
        self.assertEqual(clock.user_agent, "Chrome-UA")
        self.assertEqual(clock.session.headers["User-Agent"], "Chrome-UA")
        self.assertEqual(clock.session.cookies.get("a"), "b")
        self.assertIsNotNone(clock.logged_in_at)

    def test_login_failure_quits_and_saves_nothing(self):
        from utility.login_and_navigate import LoginRejected
        for exc in (LoginRejected("captcha"), RuntimeError("boom")):
            clock, driver, _, _, save, error = self._login(login_side_effect=exc)
            self.assertIs(error, exc)
            driver.quit.assert_called_once()
            save.assert_not_called()

    def test_page_load_failure_quits(self):
        driver = MagicMock()
        driver.get.side_effect = RuntimeError("timeout")
        with patch.object(http_clock, "create_driver", return_value=driver), \
             patch.object(http_clock, "login_and_navigate") as login:
            with self.assertRaises(RuntimeError):
                HttpClock(requests_session()).browser_login()
        login.assert_not_called()
        driver.quit.assert_called_once()

    def test_failure_reading_cookies_quits(self):
        driver = MagicMock()
        driver.get_cookies.side_effect = RuntimeError("gone")
        with patch.object(http_clock, "create_driver", return_value=driver), \
             patch.object(http_clock, "login_and_navigate"):
            with self.assertRaises(RuntimeError):
                HttpClock(requests_session()).browser_login()
        driver.quit.assert_called_once()


def requests_session():
    import requests
    return requests.Session()


if __name__ == "__main__":
    unittest.main()
