import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import datetime
import tempfile
import unittest
from unittest.mock import patch

import eportem_action


class TestActiveBusinessTripEndDate(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.path = os.path.join(self._tmpdir.name, "business_trip_override.txt")
        env = patch.dict(os.environ, {"EPORTEM_STATE_DIR": self._tmpdir.name})
        env.start()
        self.addCleanup(env.stop)

    def _write_override(self, start, end):
        with open(self.path, "w") as f:
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
        self.assertFalse(os.path.exists(self.path))

    def test_future_file_is_kept(self):
        future = datetime.date.today() + datetime.timedelta(days=3)
        self._write_override(future, future)
        eportem_action._active_business_trip_end_date()
        self.assertTrue(os.path.exists(self.path))

    def test_range_in_the_future_returns_none(self):
        today = datetime.date.today()
        future = today + datetime.timedelta(days=10)
        self._write_override(future, future)
        self.assertIsNone(eportem_action._active_business_trip_end_date())

    def test_malformed_file_returns_none(self):
        with open(self.path, "w") as f:
            f.write("not-a-valid-line")
        self.assertIsNone(eportem_action._active_business_trip_end_date())

    def test_found_even_when_cwd_is_elsewhere(self):
        """The file is anchored to the state dir, not to wherever cron started us."""
        today = datetime.date.today()
        self._write_override(today, today)
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        orig = os.getcwd()
        os.chdir(other.name)
        self.addCleanup(os.chdir, orig)
        self.assertEqual(eportem_action._active_business_trip_end_date(), today)


if __name__ == '__main__':
    unittest.main()
