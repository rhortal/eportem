import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import datetime
import tempfile
import unittest

import main


class TestIsHoliday(unittest.TestCase):

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self._tmpdir.name)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        self._tmpdir.cleanup()

    def _write_override(self, start, end):
        with open("holiday_override.txt", "w") as f:
            f.write(f"{start},{end}")

    def test_no_override_file(self):
        self.assertFalse(main.is_holiday())

    def test_today_within_range(self):
        today = datetime.date.today()
        self._write_override(today - datetime.timedelta(days=1), today + datetime.timedelta(days=1))
        self.assertTrue(main.is_holiday())

    def test_today_is_single_day_holiday(self):
        today = datetime.date.today()
        self._write_override(today, today)
        self.assertTrue(main.is_holiday())

    def test_range_in_the_past(self):
        today = datetime.date.today()
        past = today - datetime.timedelta(days=10)
        self._write_override(past, past)
        self.assertFalse(main.is_holiday())

    def test_range_in_the_future(self):
        today = datetime.date.today()
        future = today + datetime.timedelta(days=10)
        self._write_override(future, future)
        self.assertFalse(main.is_holiday())

    def test_malformed_file_treated_as_not_holiday(self):
        with open("holiday_override.txt", "w") as f:
            f.write("not-a-valid-line")
        self.assertFalse(main.is_holiday())


if __name__ == '__main__':
    unittest.main()
