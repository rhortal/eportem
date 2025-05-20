import unittest
from unittest.mock import MagicMock
import start_the_day
import lunch_break
import after_lunch_break
import stop_the_day
import start_the_day_home
import after_lunch_break_home

class TestEPortem(unittest.TestCase):

    def test_start_the_day(self):
        mock_driver = MagicMock()
        start_the_day.main(driver=mock_driver)
        mock_driver.find_element.assert_called()

    def test_lunch_break(self):
        mock_driver = MagicMock()
        lunch_break.main(driver=mock_driver)
        mock_driver.find_element.assert_called()

    def test_after_lunch_break(self):
        mock_driver = MagicMock()
        after_lunch_break.main(driver=mock_driver)
        mock_driver.find_element.assert_called()

    def test_stop_the_day(self):
        mock_driver = MagicMock()
        stop_the_day.main(driver=mock_driver)
        mock_driver.find_element.assert_called()

    def test_start_the_day_home(self):
        mock_driver = MagicMock()
        start_the_day_home.main(driver=mock_driver)
        mock_driver.find_element.assert_called()

    def test_after_lunch_break_home(self):
        mock_driver = MagicMock()
        after_lunch_break_home.main(driver=mock_driver)
        mock_driver.find_element.assert_called()

if __name__ == '__main__':
    unittest.main()