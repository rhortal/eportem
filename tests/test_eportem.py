import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import unittest
from unittest.mock import MagicMock, patch
from eportem.eportem_action import EPortemAction

class TestEPortem(unittest.TestCase):

    def test_start_day_office(self):
        mock_driver = MagicMock()
        action = EPortemAction("start_day", "office", mock_driver)
        with patch('utility.notification_send.NotificationManager.notify'):
            action.perform()
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="buttonsRegBox"]/div/div/button')

    def test_start_day_home(self):
        mock_driver = MagicMock()
        action = EPortemAction("start_day", "home", mock_driver)
        with patch('utility.notification_send.NotificationManager.notify'):
            action.perform()
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="buttonsRegBox"]/div/button[@data-toggle="dropdown"]')
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="_ststart" and @name="1293"]')

    def test_lunch_break(self):
        mock_driver = MagicMock()
        action = EPortemAction("lunch_break", "office", mock_driver)
        with patch('utility.notification_send.NotificationManager.notify'):
            action.perform()
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="buttonsRegBox"]/div/div/button')
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="_stpause"]')

    def test_after_lunch_office(self):
        mock_driver = MagicMock()
        action = EPortemAction("after_lunch", "office", mock_driver)
        with patch('utility.notification_send.NotificationManager.notify'):
            action.perform()
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="buttonsRegBox"]/div/div/button/div/div[2]/h2')
        mock_driver.find_element.assert_any_call("xpath", '//a[@id="_stini" and @name="1"]')

    def test_after_lunch_home(self):
        mock_driver = MagicMock()
        action = EPortemAction("after_lunch", "home", mock_driver)
        with patch('utility.notification_send.NotificationManager.notify'):
            action.perform()
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="buttonsRegBox"]/div/div/button/div/div[2]/h2')
        mock_driver.find_element.assert_any_call("xpath", '//a[@id="_stini" and @name="1293"]')

    def test_stop_day(self):
        mock_driver = MagicMock()
        action = EPortemAction("stop_day", "office", mock_driver)
        with patch('utility.notification_send.NotificationManager.notify'):
            action.perform()
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="buttonsRegBox"]/div/div/button')
        mock_driver.find_element.assert_any_call("xpath", '//*[@id="_ststop"]')

if __name__ == '__main__':
    unittest.main()