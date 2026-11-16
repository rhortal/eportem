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
<a id="_stini" name="1" name2="W" name3="Inicio Trabajo" onclick="_doPostJor(this)">Oficina</a>
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

    def test_wrong_state_raises_instead_of_guessing(self):
        with self.assertRaises(ButtonNotFound):
            select_button(parse_buttons(WORKING_HTML), "after_lunch", "office")
        with self.assertRaises(ButtonNotFound):
            select_button(parse_buttons(WORKING_HTML), "start_day", "office")


def _response(url, text="", status=200):
    r = MagicMock()
    r.url, r.text, r.status_code = url, text, status
    r.raise_for_status = MagicMock()
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


class TestEportemActionRouting(unittest.TestCase):

    ENV = {"EPORTEM_ENABLED": "YES", "TELEGRAM_NOTIFY": "NO",
           "SLACK_NOTIFY": "NO", "SLACK_STATUS": "NO"}

    def test_http_flag_uses_http_clock(self):
        from eportem_action import EPortemAction
        with patch.dict(os.environ, {**self.ENV, "EPORTEM_HTTP": "YES"}), \
             patch.object(http_clock.HttpClock, "clock",
                          return_value=({"action": "_ststop", "_descactiv": "x"}, {})) as clock, \
             patch("eportem_action.login_and_navigate") as selenium_login:
            EPortemAction("stop_day", "office").perform()
        clock.assert_called_once_with("stop_day", "office", send=True)
        selenium_login.assert_not_called()

    def test_default_still_uses_selenium(self):
        from eportem_action import EPortemAction
        env = {k: v for k, v in self.ENV.items()}
        with patch.dict(os.environ, env), \
             patch.dict(os.environ, {"EPORTEM_HTTP": "NO"}), \
             patch.object(http_clock.HttpClock, "clock") as clock:
            EPortemAction("stop_day", "office", MagicMock()).perform()
        clock.assert_not_called()


class TestCliExitCodes(unittest.TestCase):
    """The exit code decides whether run_http.sh falls back to Selenium, so a
    request that may have been recorded must never come back as 3."""

    PARAMS = {"action": "_stpause", "_codactiv": "2", "_tipoactiv": "P",
              "_descactiv": "Comida", "_geolocation": "", "_localip": ""}

    def _run(self, *argv, resolve=None, send=None, recorded=None):
        clock = MagicMock()
        clock.resolve.side_effect = resolve or (lambda *a: self.PARAMS)
        clock.send.side_effect = send or (lambda p: {"isActive": "P"})
        if isinstance(recorded, Exception):
            clock.is_recorded.side_effect = recorded
        else:
            clock.is_recorded.return_value = recorded
        with patch.object(http_clock, "HttpClock", return_value=clock), \
             patch("utility.env_loader.load_environment"), \
             patch.object(sys, "argv", ["http_clock", "lunch_break", *argv]), \
             patch("builtins.print"):
            return http_clock.main(), clock

    def test_dry_run_does_not_send(self):
        rc, clock = self._run()
        self.assertEqual(rc, http_clock.EXIT_RECORDED)
        clock.send.assert_not_called()

    def test_success(self):
        rc, clock = self._run("--send")
        self.assertEqual(rc, http_clock.EXIT_RECORDED)
        clock.send.assert_called_once()

    def test_failure_before_sending_allows_fallback(self):
        rc, clock = self._run("--send", resolve=ButtonNotFound("x"))
        self.assertEqual(rc, http_clock.EXIT_NOT_RECORDED)
        clock.send.assert_not_called()

    def test_send_error_but_button_still_there_allows_fallback(self):
        rc, _ = self._run("--send", send=ValueError("bad json"), recorded=False)
        self.assertEqual(rc, http_clock.EXIT_NOT_RECORDED)

    def test_send_error_but_recorded_is_success(self):
        rc, _ = self._run("--send", send=ValueError("bad json"), recorded=True)
        self.assertEqual(rc, http_clock.EXIT_RECORDED)

    def test_send_error_and_dashboard_unreadable_blocks_fallback(self):
        rc, _ = self._run("--send", send=ValueError("x"), recorded=SessionExpired("x"))
        self.assertEqual(rc, http_clock.EXIT_UNKNOWN)

    def test_notify_failure_is_reported_without_fallback(self):
        with patch("eportem_action.EPortemAction.after_action", side_effect=RuntimeError("slack")):
            rc, _ = self._run("--send", "--notify")
        self.assertEqual(rc, http_clock.EXIT_NOTIFY_FAILED)

    def test_is_recorded_checks_button_presence(self):
        session = MagicMock()
        session.headers = {}
        session.get.return_value = _response(DASHBOARD_URL, WORKING_HTML)
        clock = HttpClock(session)
        self.assertFalse(clock.is_recorded(self.PARAMS))  # pause still offered
        self.assertTrue(clock.is_recorded({**self.PARAMS, "action": "_ststart", "_codactiv": "1"}))


if __name__ == "__main__":
    unittest.main()
