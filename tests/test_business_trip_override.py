import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import datetime
import tempfile
import unittest

import eportem_action


class TestActiveBusinessTripEndDate(unittest.TestCase):

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self._tmpdir.name)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        self._tmpdir.cleanup()

    def _write_override(self, start, end):
        with open("business_trip_override.txt", "w") as f:
            f.write(f"{start},{end}")

    def test_no_override_file(self):
        self.assertIsNone(eportem_action._active_business_trip_end_date())

    def test_today_within_range_returns_end_date(self):
        today = datetime.date.today()
        end = today + datetime.timedelta(days=2)
        self._write_override(today - datetime.timedelta(days=1), end)
        self.assertEqual(eportem_action._active_business_trip_end_date(), end)

    def test_today_is_single_day_trip(self):
        today = datetime.date.today()
        self._write_override(today, today)
        self.assertEqual(eportem_action._active_business_trip_end_date(), today)

    def test_range_in_the_past_returns_none(self):
        today = datetime.date.today()
        past = today - datetime.timedelta(days=10)
        self._write_override(past, past)
        self.assertIsNone(eportem_action._active_business_trip_end_date())

    def test_expired_file_is_deleted(self):
        past = datetime.date.today() - datetime.timedelta(days=1)
        self._write_override(past, past)
        eportem_action._active_business_trip_end_date()
        self.assertFalse(os.path.exists("business_trip_override.txt"))

    def test_future_file_is_kept(self):
        future = datetime.date.today() + datetime.timedelta(days=3)
        self._write_override(future, future)
        eportem_action._active_business_trip_end_date()
        self.assertTrue(os.path.exists("business_trip_override.txt"))

    def test_range_in_the_future_returns_none(self):
        today = datetime.date.today()
        future = today + datetime.timedelta(days=10)
        self._write_override(future, future)
        self.assertIsNone(eportem_action._active_business_trip_end_date())

    def test_malformed_file_returns_none(self):
        with open("business_trip_override.txt", "w") as f:
            f.write("not-a-valid-line")
        self.assertIsNone(eportem_action._active_business_trip_end_date())


if __name__ == '__main__':
    unittest.main()
