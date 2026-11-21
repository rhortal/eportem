import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import contextlib
import io
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException

import eportem_action
from eportem_action import EPortemAction, http_enabled_for
from utility.login_and_navigate import LOGIN_URL

# Everything that could reach the outside world is forced off, whatever the
# host's real config/.env says (importing the project loads it, and on the
# production host EPORTEM_HTTP=YES would make a driver-less EPortemAction send a
# real clock request). Credentials are emptied too, so a test that turns a
# notifier on without supplying its own credentials is skipped, not sent.
NO_NOTIFY_ENV = {
    "EPORTEM_ENABLED": "YES",
    "EPORTEM_HTTP": "NO",
    "TELEGRAM_NOTIFY": "NO",
    "SLACK_NOTIFY": "NO",
    "SLACK_STATUS": "NO",
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_CHAT_ID": "",
    "SLACK_BOT_TOKEN": "",
    "SLACK_TOKEN": "",
    "SLACK_WEBHOOK_URL": "",
}


class IsolatedCase(unittest.TestCase):
    """No real sleeps, no real env, no files outside a temp dir."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.diag_dir = os.path.join(self.tmp, "diagnostics")
        self.http_log = os.path.join(self.tmp, "logs", "http_clock.log")  # via EPORTEM_STATE_DIR
        env = dict(NO_NOTIFY_ENV, EPORTEM_STATE_DIR=self.tmp)
        for p in (patch.dict(os.environ, env, clear=False),
                  patch("eportem_action.login_and_navigate", side_effect=lambda d: d),
                  patch("time.sleep"),  # one patch covers eportem_action and login_and_navigate
                  patch("eportem_action.DIAGNOSTICS_DIR", self.diag_dir)):
            p.start()
            self.addCleanup(p.stop)


class TestEPortem(IsolatedCase):

    @patch("eportem_action.RETRY_PAUSE_SECONDS", 0)
    @patch("eportem_action.BUTTON_WAIT_SECONDS", 0)
    def test_missing_button_reopens_page_until_it_appears_then_clicks(self):
        mock_driver = MagicMock()
        mock_driver.find_elements.side_effect = [[], [], [], [MagicMock()]]
        EPortemAction("start_day", "home", mock_driver).perform()
        self.assertEqual(mock_driver.get.call_count, 3)
        mock_driver.get.assert_called_with("https://eportem.es/aplicaciones/e-portem/registro/")
        mock_driver.find_element.assert_any_call(
            "xpath", '//*[@id="buttonsRegBox"]/div/button[@data-toggle="dropdown"]')
        mock_driver.save_screenshot.assert_not_called()

    @patch("eportem_action.RETRY_PAUSE_SECONDS", 0)
    @patch("eportem_action.BUTTON_WAIT_SECONDS", 0)
    def test_reopen_error_is_retried(self):
        mock_driver = MagicMock()
        mock_driver.find_elements.side_effect = [[], [], [MagicMock()]]
        mock_driver.get.side_effect = [WebDriverException("net"), None]
        EPortemAction("start_day", "office", mock_driver).perform()
        self.assertEqual(mock_driver.get.call_count, 2)
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="buttonsRegBox"]/div/div/button')

    @patch("eportem_action.RETRY_PAUSE_SECONDS", 0)
    @patch("eportem_action.BUTTON_WAIT_SECONDS", 0)
    def test_lost_session_logs_in_again(self):
        mock_driver = MagicMock()
        mock_driver.find_elements.side_effect = [[], [MagicMock()]]
        with patch("eportem_action.login_and_navigate", side_effect=lambda d: d) as login:
            mock_driver.current_url = "https://eportem.es/Usuario/Login?ReturnUrl=x"
            EPortemAction("start_day", "office", mock_driver).perform()
        self.assertEqual(login.call_count, 2)

    @patch("eportem_action.RETRY_PAUSE_SECONDS", 0)
    def test_login_failure_is_retried_then_raises_and_closes_browser(self):
        mock_driver = MagicMock()
        with patch("eportem_action.login_and_navigate", side_effect=TimeoutException("no")) as login, \
                tempfile.TemporaryDirectory() as tmp, patch("eportem_action.DIAGNOSTICS_DIR", tmp):
            with self.assertRaises(TimeoutException):
                EPortemAction("start_day", "office", mock_driver).perform()
        self.assertEqual(login.call_count, 3)
        mock_driver.quit.assert_called_once()

    def test_login_recovers_on_second_attempt(self):
        mock_driver = MagicMock()
        with patch("eportem_action.RETRY_PAUSE_SECONDS", 0), \
                patch("eportem_action.login_and_navigate", side_effect=[TimeoutException("no"), mock_driver]):
            EPortemAction("start_day", "office", mock_driver).perform()
        mock_driver.get.assert_called_once_with(LOGIN_URL)
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="buttonsRegBox"]/div/div/button')

    def test_after_lunch_without_pause_explains_and_raises(self):
        mock_driver = MagicMock()
        mock_driver.page_source = "<html>page</html>"
        def find_element(by, value):
            if by == "xpath" and "_stini" in value:
                raise NoSuchElementException("missing")
            button = MagicMock()
            button.get_attribute.return_value = " Pausar "
            return button
        mock_driver.find_element.side_effect = find_element
        out = io.StringIO()
        with patch("eportem_action.login_and_navigate", side_effect=lambda d: d), \
                tempfile.TemporaryDirectory() as tmp, patch("eportem_action.DIAGNOSTICS_DIR", tmp), \
                contextlib.redirect_stdout(out):
            with self.assertRaises(NoSuchElementException):
                EPortemAction("after_lunch", "office", mock_driver).perform()
            self.assertEqual(len([f for f in os.listdir(tmp) if f.endswith(".html")]), 1)
        self.assertIn("'Pausar'", out.getvalue())
        self.assertIn("no lunch break to resume", out.getvalue())
        mock_driver.quit.assert_called_once()

    @patch("eportem_action.RETRY_BUDGET_SECONDS", 0.05)
    @patch("eportem_action.RETRY_PAUSE_SECONDS", 0.02)
    @patch("eportem_action.BUTTON_WAIT_SECONDS", 0)
    def test_button_never_appears_saves_diagnostics_and_raises(self):
        mock_driver = MagicMock()
        mock_driver.find_elements.return_value = []
        mock_driver.page_source = "<html>page</html>"
        def find_element(by, value):
            # the login form's fields, found by name, must still work
            if by == "xpath":
                raise NoSuchElementException("missing")
            return MagicMock()
        mock_driver.find_element.side_effect = find_element
        with tempfile.TemporaryDirectory() as tmp, patch("eportem_action.DIAGNOSTICS_DIR", tmp):
            with self.assertRaises(NoSuchElementException):
                EPortemAction("start_day", "home", mock_driver).perform()
            self.assertEqual(len([f for f in os.listdir(tmp) if f.endswith(".html")]), 1)
        self.assertGreaterEqual(mock_driver.get.call_count, 1)
        mock_driver.save_screenshot.assert_called_once()
        mock_driver.quit.assert_called_once()

    def test_start_day_office(self):
        mock_driver = MagicMock()
        action = EPortemAction("start_day", "office", mock_driver)
        action.perform()
        self.assertEqual(mock_driver.find_element.return_value.click.call_count, 1)
        mock_driver.quit.assert_called_once()
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="buttonsRegBox"]/div/div/button')

    def test_start_day_home(self):
        mock_driver = MagicMock()
        action = EPortemAction("start_day", "home", mock_driver)
        action.perform()
        self.assertEqual(mock_driver.find_element.return_value.click.call_count, 2)
        mock_driver.quit.assert_called_once()
        mock_driver.find_element.assert_any_call(
            "xpath", '//*[@id="buttonsRegBox"]/div/button[@data-toggle="dropdown"]')
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="_ststart" and @name="1293"]')

    def test_lunch_break(self):
        mock_driver = MagicMock()
        action = EPortemAction("lunch_break", "office", mock_driver)
        action.perform()
        self.assertEqual(mock_driver.find_element.return_value.click.call_count, 2)
        mock_driver.quit.assert_called_once()
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="buttonsRegBox"]/div/div/button')
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="_stpause"]')

    def test_after_lunch_office(self):
        mock_driver = MagicMock()
        action = EPortemAction("after_lunch", "office", mock_driver)
        action.perform()
        self.assertEqual(mock_driver.find_element.return_value.click.call_count, 2)
        mock_driver.quit.assert_called_once()
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="buttonsRegBox"]/div/div/button/div/div[2]/h2')
        mock_driver.find_element.assert_any_call("xpath", '//a[@id="_stini" and @name="1"]')

    def test_after_lunch_home(self):
        mock_driver = MagicMock()
        action = EPortemAction("after_lunch", "home", mock_driver)
        action.perform()
        self.assertEqual(mock_driver.find_element.return_value.click.call_count, 2)
        mock_driver.quit.assert_called_once()
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="buttonsRegBox"]/div/div/button/div/div[2]/h2')
        mock_driver.find_element.assert_any_call("xpath", '//a[@id="_stini" and @name="1293"]')

    def test_stop_day(self):
        mock_driver = MagicMock()
        action = EPortemAction("stop_day", "office", mock_driver)
        action.perform()
        self.assertEqual(mock_driver.find_element.return_value.click.call_count, 2)
        mock_driver.quit.assert_called_once()
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="buttonsRegBox"]/div/div/button')
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="_ststop"]')

    def test_enabled_channels_each_get_the_message_and_status_is_set(self):
        """With notify/status enabled, the real HTTP calls must still be mocked out."""
        mock_driver = MagicMock()
        action = EPortemAction("start_day", "office", mock_driver)
        env = dict(
            NO_NOTIFY_ENV,
            TELEGRAM_NOTIFY="YES", TELEGRAM_BOT_TOKEN="test-bot-token", TELEGRAM_CHAT_ID="12345",
            SLACK_NOTIFY="YES", SLACK_WEBHOOK_URL="https://hooks.slack.com/services/test",
            SLACK_STATUS="YES", SLACK_TOKEN="REDACTED-SLACK-TOKEN",
        )
        with patch.dict(os.environ, env, clear=False), \
             patch('utility.notification_send.TelegramChannel.send') as mock_telegram_send, \
             patch('utility.notification_send.SlackChannel.send') as mock_slack_send, \
             patch('utility.slack_status.SlackStatusUpdater.set_status') as mock_set_status:
            action.perform()
        mock_telegram_send.assert_called_once_with("Checked in at office")
        mock_slack_send.assert_called_once_with("Checked in at office")
        mock_set_status.assert_called_once_with("Working at office", ":office:", 0)

    def test_business_trip_overrides_status_for_every_action_type(self):
        """A business trip keeps the same Slack status across all actions,
        including stop_day - no reverting to 'Done for the day'."""
        import datetime
        trip_end = datetime.date(2026, 8, 22)
        expected_expiration = int(datetime.datetime.combine(trip_end, datetime.time(23, 59)).timestamp())

        for action_type in ["start_day", "lunch_break", "after_lunch", "stop_day"]:
            with self.subTest(action_type=action_type):
                mock_driver = MagicMock()
                action = EPortemAction(action_type, "office", mock_driver)
                env = dict(NO_NOTIFY_ENV, SLACK_STATUS="YES", SLACK_TOKEN="REDACTED-SLACK-TOKEN")
                with patch.dict(os.environ, env, clear=False), \
                     patch('eportem_action._active_business_trip_end_date', return_value=trip_end), \
                     patch('utility.slack_status.SlackStatusUpdater.set_status') as mock_set_status:
                    action.perform()
                mock_set_status.assert_called_once_with(
                    "On a business trip", ":airplane:", expected_expiration
                )

if __name__ == '__main__':
    unittest.main()

class TestAfterAction(IsolatedCase):
    """The action is already recorded: a follow-up failure must never raise."""

    ENV = dict(TELEGRAM_NOTIFY="YES", TELEGRAM_BOT_TOKEN="tok", TELEGRAM_CHAT_ID="1",
               SLACK_NOTIFY="YES", SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T/B/x",
               SLACK_STATUS="YES", SLACK_TOKEN="xoxp-test")

    def _after(self, telegram=True, slack=True, status=True, env=None):
        out = io.StringIO()
        with patch.dict(os.environ, env or self.ENV), \
                patch("utility.notification_send.TelegramChannel.send", side_effect=telegram) as tg, \
                patch("utility.notification_send.SlackChannel.send", side_effect=slack) as sl, \
                patch("utility.slack_status.SlackStatusUpdater.set_status", side_effect=status) as st, \
                contextlib.redirect_stdout(out):
            EPortemAction("start_day", "office", MagicMock()).after_action()
        return tg, sl, st, out.getvalue()

    def test_all_good_prints_no_warning(self):
        tg, sl, st, out = self._after(telegram=[True], slack=[True], status=[True])
        self.assertNotIn("WARNING", out)

    def test_telegram_exception_does_not_stop_slack_or_status(self):
        tg, sl, st, out = self._after(telegram=RuntimeError("boom"), slack=[True], status=[True])
        sl.assert_called_once()
        st.assert_called_once()
        self.assertIn("WAS recorded", out)
        self.assertIn("telegram", out)

    def test_channel_returning_false_is_reported(self):
        tg, sl, st, out = self._after(telegram=[True], slack=[False], status=[True])
        self.assertIn("follow-ups failed: slack", out)
        self.assertNotIn("telegram,", out)

    def test_status_failure_is_reported_and_does_not_raise(self):
        for status in ([False], RuntimeError("x")):
            with self.subTest(status=status):
                tg, sl, st, out = self._after(telegram=[True], slack=[True], status=status)
                self.assertIn("follow-ups failed: slack status", out)

    def test_status_without_token_is_skipped_not_a_failure(self):
        tg, sl, st, out = self._after(telegram=[True], slack=[True], env=dict(self.ENV, SLACK_TOKEN=""))
        st.assert_not_called()
        self.assertIn("SLACK_TOKEN is not configured", out)
        self.assertNotIn("WARNING", out)

    def test_unconfigured_channel_is_skipped_not_a_failure(self):
        tg, sl, st, out = self._after(telegram=[True], slack=[None], status=[True])
        self.assertNotIn("WARNING", out)

    def test_everything_failing_still_does_not_raise(self):
        tg, sl, st, out = self._after(telegram=OSError("a"), slack=OSError("b"), status=OSError("c"))
        self.assertIn("telegram, slack, slack status", out)

    def test_business_trip_file_error_does_not_raise(self):
        with patch("eportem_action._active_business_trip_end_date", side_effect=OSError("denied")):
            tg, sl, st, out = self._after(telegram=[True], slack=[True], status=[True])
        self.assertIn("slack status", out)

    def test_exception_text_does_not_leak_secrets(self):
        err = RuntimeError("failed for /bottok/sendMessage with xoxp-test")
        tg, sl, st, out = self._after(telegram=[True], slack=[True], status=err)
        self.assertNotIn("xoxp-test", out)

    def test_perform_returns_normally_when_notification_fails_selenium_path(self):
        with patch.dict(os.environ, self.ENV), \
                patch("utility.notification_send.TelegramChannel.send", side_effect=OSError("down")), \
                patch("utility.notification_send.SlackChannel.send", return_value=True), \
                patch("utility.slack_status.SlackStatusUpdater.set_status", return_value=True) as st, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(EPortemAction("start_day", "office", MagicMock()).perform())
        st.assert_called_once()

    def test_perform_returns_normally_when_notification_fails_http_path(self):
        with patch.dict(os.environ, dict(self.ENV, EPORTEM_HTTP="YES")), \
                patch.object(EPortemAction, "_perform_http"), \
                patch.object(EPortemAction, "_perform_selenium") as selenium, \
                patch("utility.notification_send.TelegramChannel.send", side_effect=OSError("down")), \
                patch("utility.notification_send.SlackChannel.send", return_value=True), \
                patch("utility.slack_status.SlackStatusUpdater.set_status", return_value=True), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(EPortemAction("start_day", "office").perform())
        selenium.assert_not_called()


class TestLoginBudget(IsolatedCase):

    @patch("eportem_action.BUTTON_WAIT_SECONDS", 0)
    def test_persistent_rejection_stops_at_the_run_budget(self):
        driver = MagicMock()
        driver.find_elements.return_value = []
        driver.current_url = "https://eportem.es/Usuario/Login"
        driver.page_source = "<html></html>"
        results = [driver] + [WebDriverException("rejected")] * 50
        with patch("eportem_action.login_and_navigate", side_effect=results) as login, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(eportem_action.LoginBudgetExceeded):
                EPortemAction("start_day", "office", driver).perform()
        self.assertEqual(login.call_count, eportem_action.MAX_LOGINS_PER_RUN)
        self.assertIn("Login budget spent", out.getvalue())
        driver.quit.assert_called_once()
        self.assertLessEqual(driver.save_screenshot.call_count, eportem_action.MAX_DIAGNOSTICS_PER_RUN)

    def test_diagnostics_capped_per_run(self):
        driver = MagicMock()
        driver.page_source = "<html></html>"
        action = EPortemAction("start_day", "office", driver)
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(10):
                action._save_diagnostics()
        self.assertEqual(driver.save_screenshot.call_count, eportem_action.MAX_DIAGNOSTICS_PER_RUN)


class TestAlreadyStartedGuard(IsolatedCase):

    def _run(self, label):
        driver = MagicMock()
        driver.page_source = "<html></html>"
        driver.find_element.return_value.get_attribute.return_value = label
        action = EPortemAction("start_day", "office", driver)
        with patch.object(EPortemAction, "after_action") as after, contextlib.redirect_stdout(io.StringIO()) as out:
            try:
                action.perform()
                raised = None
            except eportem_action.ActionNotApplicable as e:
                raised = e
        return driver, after, raised, out.getvalue()

    def test_started_day_is_not_clicked_and_not_notified(self):
        for label in (" Pausar ", "pausar jornada", "Reanudar", "  REANUDAR\n"):
            with self.subTest(label=label):
                driver, after, raised, out = self._run(label)
                self.assertIsNotNone(raised)
                driver.find_element.return_value.click.assert_not_called()
                after.assert_not_called()
                self.assertIn("already started", out)
                self.assertIn("nothing was recorded", out)
                driver.quit.assert_called_once()

    def test_not_started_or_unreadable_is_clicked(self):
        for label in ("Iniciar", "  iNICIAR  jornada", "", "Something new", MagicMock()):
            with self.subTest(label=label):
                driver, after, raised, _ = self._run(label)
                self.assertIsNone(raised)
                driver.find_element.return_value.click.assert_called_once()
                after.assert_called_once()

    def test_unreadable_label_reads_as_unknown(self):
        driver = MagicMock()
        self.assertEqual(EPortemAction("start_day", "office", driver)._page_state(), "unknown")

    def test_actions_with_a_second_button_are_not_checked(self):
        driver = MagicMock()
        driver.find_element.return_value.get_attribute.return_value = "Pausar"
        with contextlib.redirect_stdout(io.StringIO()):
            EPortemAction("lunch_break", "office", driver).perform()
        self.assertEqual(driver.find_element.return_value.click.call_count, 2)


class TestValidation(IsolatedCase):

    def test_unknown_action(self):
        with self.assertRaisesRegex(ValueError, "Unknown action_type 'nap'"):
            EPortemAction("nap", "office")

    def test_unknown_location(self):
        with self.assertRaisesRegex(ValueError, "Unknown location 'mars'"):
            EPortemAction("start_day", "mars")

    def test_valid_combinations(self):
        for action in eportem_action.ACTIONS:
            for location in eportem_action.LOCATIONS:
                self.assertTrue(EPortemAction(action, location).selectors)


class TestHttpEnabledFor(IsolatedCase):

    def _check(self, value, action="lunch_break"):
        out = io.StringIO()
        with patch.dict(os.environ, {"EPORTEM_HTTP": value}), contextlib.redirect_stdout(out):
            return http_enabled_for(action), out.getvalue()

    def test_all_spellings(self):
        for value in ("YES", "yes", "ALL", "all", "TRUE", "true", "1", " Yes "):
            with self.subTest(value=value):
                self.assertEqual(self._check(value), (True, ""))

    def test_none_spellings(self):
        for value in ("NO", "no", "FALSE", "false", "0", "", "  "):
            with self.subTest(value=value):
                self.assertEqual(self._check(value), (False, ""))

    def test_unset_means_none(self):
        with patch.dict(os.environ):
            os.environ.pop("EPORTEM_HTTP")
            self.assertFalse(http_enabled_for("start_day"))

    def test_list_is_case_insensitive_and_trimmed(self):
        self.assertEqual(self._check("Lunch_break , AFTER_LUNCH"), (True, ""))
        self.assertEqual(self._check("Lunch_break , AFTER_LUNCH", "stop_day"), (False, ""))

    def test_unknown_token_warns_but_known_ones_still_work(self):
        enabled, out = self._check("lunch_brek,after_lunch", "after_lunch")
        self.assertTrue(enabled)
        self.assertIn("lunch_brek", out)
        self.assertIn("WARNING", out)
        enabled, out = self._check("lunch_brek")
        self.assertFalse(enabled)


class TestLogAndDiagnosticsHygiene(IsolatedCase):

    def _mode(self, path):
        return os.stat(path).st_mode & 0o777

    def test_http_log_is_private(self):
        eportem_action._log_http_attempt("start_day", "office", "recorded over HTTP", "out\n")
        self.assertEqual(self._mode(os.path.dirname(self.http_log)), 0o700)
        self.assertEqual(self._mode(self.http_log), 0o600)
        with open(self.http_log) as f:
            self.assertIn("start_day office: recorded over HTTP", f.read())

    def test_existing_loose_permissions_are_tightened(self):
        os.makedirs(os.path.dirname(self.http_log), mode=0o755)
        with open(self.http_log, "w") as f:
            f.write("old\n")
        os.chmod(self.http_log, 0o644)
        os.chmod(os.path.dirname(self.http_log), 0o755)
        eportem_action._log_http_attempt("stop_day", "home", "x")
        self.assertEqual(self._mode(self.http_log), 0o600)
        self.assertEqual(self._mode(os.path.dirname(self.http_log)), 0o700)

    def test_log_rotates_when_too_big(self):
        with patch("utility.logfiles.MAX_BYTES", 30), patch("utility.logfiles.GENERATIONS", 1):
            eportem_action._log_http_attempt("start_day", "office", "first", "x" * 100)
            eportem_action._log_http_attempt("stop_day", "office", "second")
            eportem_action._log_http_attempt("stop_day", "office", "third")
        with open(self.http_log + ".1") as f:
            rotated = f.read()
        with open(self.http_log) as f:
            current = f.read()
        self.assertIn("second", rotated)
        self.assertNotIn("first", rotated)  # previous .1 was replaced
        self.assertIn("third", current)
        self.assertNotIn("second", current)

    def test_unwritable_log_is_reported_not_raised(self):
        with patch("eportem_action.os.open", side_effect=OSError("denied")), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            eportem_action._log_http_attempt("start_day", "office", "x")
        self.assertIn("Could not write", out.getvalue())

    def test_diagnostics_redacts_token_and_is_private(self):
        driver = MagicMock()
        driver.page_source = ('<form><input name="__RequestVerificationToken" type="hidden" '
                              'value="SECRETVALUE" /><p>hello</p></form>')
        with contextlib.redirect_stdout(io.StringIO()):
            EPortemAction("start_day", "office", driver)._save_diagnostics()
        self.assertEqual(self._mode(self.diag_dir), 0o700)
        (name,) = [n for n in os.listdir(self.diag_dir) if n.endswith(".html")]
        path = os.path.join(self.diag_dir, name)
        self.assertEqual(self._mode(path), 0o600)
        with open(path) as f:
            html = f.read()
        self.assertNotIn("SECRETVALUE", html)
        self.assertIn('value="<redacted>"', html)
        self.assertIn("hello", html)

    def test_diagnostics_are_pruned_to_the_newest(self):
        os.makedirs(self.diag_dir)
        for i, mtime in enumerate((1000, 2000, 3000)):
            path = os.path.join(self.diag_dir, f"2020010{i}-000000-start_day.html")
            open(path, "w").close()
            os.utime(path, (mtime, mtime))
        other = os.path.join(self.diag_dir, "notes.txt")  # not ours: never deleted
        open(other, "w").close()
        driver = MagicMock()
        driver.page_source = "<html></html>"
        with patch("eportem_action.MAX_DIAGNOSTICS_FILES", 2), contextlib.redirect_stdout(io.StringIO()):
            EPortemAction("start_day", "office", driver)._save_diagnostics()
        left = sorted(os.listdir(self.diag_dir))
        self.assertEqual(len(left), 3)
        self.assertIn("notes.txt", left)
        self.assertIn("20200102-000000-start_day.html", left)  # newest old one survives
        self.assertNotIn("20200100-000000-start_day.html", left)
        self.assertNotIn("20200101-000000-start_day.html", left)


if __name__ == '__main__':
    unittest.main()
