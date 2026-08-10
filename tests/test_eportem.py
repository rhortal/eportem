import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import unittest
from unittest.mock import MagicMock, patch
from eportem_action import EPortemAction

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
        mock_set_status.assert_called_once_with("Working at office", ":office:")

if __name__ == '__main__':
    unittest.main()