import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import datetime
import tempfile
import unittest
from unittest.mock import patch

import main


class _ChdirTempDirMixin:

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self._tmpdir.name)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        self._tmpdir.cleanup()

    def _write_override(self, start, end, holiday_type=None):
        with open("holiday_override.txt", "w") as f:
            if holiday_type is None:
                f.write(f"{start},{end}")
            else:
                f.write(f"{start},{end},{holiday_type}")


class TestIsHoliday(_ChdirTempDirMixin, unittest.TestCase):

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


class TestGetTodayHoliday(_ChdirTempDirMixin, unittest.TestCase):

    def test_no_override_returns_none(self):
        self.assertIsNone(main.get_today_holiday())

    def test_legacy_two_field_file_defaults_to_holiday_type(self):
        today = datetime.date.today()
        self._write_override(today, today)
        self.assertEqual(main.get_today_holiday(), {"type": "holiday", "start": today, "end": today})

    def test_three_field_file_respects_business_trip_type(self):
        today = datetime.date.today()
        self._write_override(today, today, "business_trip")
        self.assertEqual(main.get_today_holiday(), {"type": "business_trip", "start": today, "end": today})

    def test_out_of_range_returns_none(self):
        today = datetime.date.today()
        past = today - datetime.timedelta(days=10)
        self._write_override(past, past, "business_trip")
        self.assertIsNone(main.get_today_holiday())

    def test_wrong_field_count_treated_as_invalid(self):
        with open("holiday_override.txt", "w") as f:
            f.write("2026-08-12,2026-08-17,business_trip,extra")
        self.assertIsNone(main.get_today_holiday())


class TestUpdateHolidaySlackStatus(unittest.TestCase):

    def _holiday(self, holiday_type, end=None):
        return {
            "type": holiday_type,
            "start": datetime.date(2026, 8, 12),
            "end": end or datetime.date(2026, 8, 17),
        }

    def test_skipped_when_slack_status_not_enabled(self):
        with patch.dict(os.environ, {"SLACK_STATUS": "NO"}, clear=False), \
             patch('utility.slack_status.SlackStatusUpdater') as mock_updater_cls:
            main.update_holiday_slack_status(self._holiday("holiday"))
        mock_updater_cls.assert_not_called()

    def test_holiday_uses_first_lookup_entry(self):
        with patch.dict(os.environ, {"SLACK_STATUS": "YES"}, clear=False), \
             patch('utility.slack_status.SlackStatusUpdater') as mock_updater_cls:
            main.update_holiday_slack_status(self._holiday("holiday"))
        mock_updater_cls.return_value.set_status.assert_called_once()
        text, emoji, expiration = mock_updater_cls.return_value.set_status.call_args[0]
        self.assertEqual((text, emoji), ("On holiday", ":palm_tree:"))

    def test_business_trip_uses_second_lookup_entry(self):
        with patch.dict(os.environ, {"SLACK_STATUS": "YES"}, clear=False), \
             patch('utility.slack_status.SlackStatusUpdater') as mock_updater_cls:
            main.update_holiday_slack_status(self._holiday("business_trip"))
        mock_updater_cls.return_value.set_status.assert_called_once()
        text, emoji, expiration = mock_updater_cls.return_value.set_status.call_args[0]
        self.assertEqual((text, emoji), ("On a business trip", ":airplane:"))

    def test_expiration_is_end_of_day_on_end_date(self):
        end_date = datetime.date(2026, 8, 17)
        expected = int(datetime.datetime.combine(end_date, datetime.time(23, 59)).timestamp())
        with patch.dict(os.environ, {"SLACK_STATUS": "YES"}, clear=False), \
             patch('utility.slack_status.SlackStatusUpdater') as mock_updater_cls:
            main.update_holiday_slack_status(self._holiday("holiday", end=end_date))
        _, _, expiration = mock_updater_cls.return_value.set_status.call_args[0]
        self.assertEqual(expiration, expected)


if __name__ == '__main__':
    unittest.main()
