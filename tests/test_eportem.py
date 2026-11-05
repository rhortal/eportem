import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import contextlib
import io
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from eportem_action import EPortemAction
from utility.login_and_navigate import LOGIN_URL

# Force every notification/status path off regardless of what the host's
# real config/.env contains, so these tests never hit Telegram, Slack, or
# update the real Slack status - only EPORTEM_ENABLED is required, since
# EPortemAction.perform() checks it before doing anything else.
NO_NOTIFY_ENV = {
    "EPORTEM_ENABLED": "YES",
    "TELEGRAM_NOTIFY": "NO",
    "SLACK_NOTIFY": "NO",
    "SLACK_STATUS": "NO",
}

class TestEPortem(unittest.TestCase):

    def setUp(self):
        patcher = patch.dict(os.environ, NO_NOTIFY_ENV, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("eportem_action.RETRY_PAUSE_SECONDS", 0)
    @patch("eportem_action.BUTTON_WAIT_SECONDS", 0)
    def test_missing_button_reopens_page_until_it_appears_then_clicks(self):
        mock_driver = MagicMock()
        mock_driver.find_elements.side_effect = [[], [], [], [MagicMock()]]
        EPortemAction("start_day", "home", mock_driver).perform()
        self.assertEqual(mock_driver.get.call_count, 3)
        mock_driver.get.assert_called_with("https://eportem.es/aplicaciones/e-portem/registro/")
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="buttonsRegBox"]/div/button[@data-toggle="dropdown"]')
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
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="buttonsRegBox"]/div/div/button')

    def test_start_day_home(self):
        mock_driver = MagicMock()
        action = EPortemAction("start_day", "home", mock_driver)
        action.perform()
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="buttonsRegBox"]/div/button[@data-toggle="dropdown"]')
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="_ststart" and @name="1293"]')

    def test_lunch_break(self):
        mock_driver = MagicMock()
        action = EPortemAction("lunch_break", "office", mock_driver)
        action.perform()
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="buttonsRegBox"]/div/div/button')
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="_stpause"]')

    def test_after_lunch_office(self):
        mock_driver = MagicMock()
        action = EPortemAction("after_lunch", "office", mock_driver)
        action.perform()
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="buttonsRegBox"]/div/div/button/div/div[2]/h2')
        mock_driver.find_element.assert_any_call("xpath", '//a[@id="_stini" and @name="1"]')

    def test_after_lunch_home(self):
        mock_driver = MagicMock()
        action = EPortemAction("after_lunch", "home", mock_driver)
        action.perform()
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="buttonsRegBox"]/div/div/button/div/div[2]/h2')
        mock_driver.find_element.assert_any_call("xpath", '//a[@id="_stini" and @name="1293"]')

    def test_stop_day(self):
        mock_driver = MagicMock()
        action = EPortemAction("stop_day", "office", mock_driver)
        action.perform()
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="buttonsRegBox"]/div/div/button')
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="_ststop"]')

    def test_notifications_registered_when_enabled_but_not_sent(self):
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
        mock_telegram_send.assert_called_once()
        mock_slack_send.assert_called_once()
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