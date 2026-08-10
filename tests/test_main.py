import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import datetime
import json
import tempfile
import unittest
from unittest.mock import patch

import main


def _config(schedule):
    return {"schedule": schedule}


def _write_config(schedule):
    os.mkdir("config")
    with open("config/config.json", "w") as f:
        json.dump(_config(schedule), f)


def _write_location_override(location, date):
    with open("location_override.txt", "w") as f:
        f.write(f"{location},{date}")


class _ChdirTempDirMixin:
    """Runs each test inside an isolated temp cwd so tests never touch real
    config/override files, and never leave artifacts behind."""

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self._tmpdir.name)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        self._tmpdir.cleanup()


class TestDetermineLocation(_ChdirTempDirMixin, unittest.TestCase):

    def test_config_location_used_when_no_override(self):
        _write_config({"0": {"day": "Monday", "location": "home"}})
        with patch('main.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = datetime.datetime(2026, 8, 10, 9, 0)  # Monday
            mock_dt.date.today.return_value = datetime.date(2026, 8, 10)
            self.assertEqual(main.determine_location(), "home")

    def test_config_entry_missing_location_key_defaults_to_office(self):
        _write_config({"0": {"day": "Monday"}})
        with patch('main.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = datetime.datetime(2026, 8, 10, 9, 0)  # Monday
            mock_dt.date.today.return_value = datetime.date(2026, 8, 10)
            self.assertEqual(main.determine_location(), "office")

    def test_weekday_missing_from_schedule_defaults_to_office(self):
        _write_config({"0": {"day": "Monday", "location": "home"}})
        with patch('main.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = datetime.datetime(2026, 8, 11, 9, 0)  # Tuesday, no entry
            mock_dt.date.today.return_value = datetime.date(2026, 8, 11)
            self.assertEqual(main.determine_location(), "office")

    def test_valid_override_for_today_wins_over_config(self):
        _write_config({"0": {"day": "Monday", "location": "office"}})
        today = datetime.date.today()
        _write_location_override("home", today)
        self.assertEqual(main.determine_location(), "home")

    def test_stale_override_falls_back_to_config(self):
        _write_config({"0": {"day": "Monday", "location": "home"}})
        yesterday = datetime.date(2026, 8, 9)
        _write_location_override("office", yesterday)
        with patch('main.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = datetime.datetime(2026, 8, 10, 9, 0)  # Monday
            mock_dt.date.today.return_value = datetime.date(2026, 8, 10)
            self.assertEqual(main.determine_location(), "home")

    def test_malformed_override_falls_back_to_config(self):
        _write_config({"0": {"day": "Monday", "location": "home"}})
        with open("location_override.txt", "w") as f:
            f.write("not-a-valid-line")
        with patch('main.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = datetime.datetime(2026, 8, 10, 9, 0)  # Monday
            mock_dt.date.today.return_value = datetime.date(2026, 8, 10)
            self.assertEqual(main.determine_location(), "home")


class TestMain(_ChdirTempDirMixin, unittest.TestCase):

    def test_holiday_short_circuits_before_any_action(self):
        today = datetime.date.today()
        with open("holiday_override.txt", "w") as f:
            f.write(f"{today},{today},business_trip")
        # update_holiday_slack_status is unit-tested separately (test_holiday_override.py);
        # patch it here too so this test can never make a real Slack API call
        # regardless of what SLACK_STATUS the host's real config/.env has set.
        with patch('main.execute_action') as mock_execute, \
             patch('main.update_holiday_slack_status') as mock_update_status:
            main.main()
        mock_execute.assert_not_called()
        mock_update_status.assert_called_once_with({
            "type": "business_trip", "start": today, "end": today
        })

    def test_no_schedule_for_today_does_not_call_execute_action(self):
        _write_config({"0": {"day": "Monday", "location": "office", "start_the_day": "09:00"}})
        with patch('main.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = datetime.datetime(2026, 8, 11, 9, 0)  # Tuesday, no entry
            mock_dt.date.today.return_value = datetime.date(2026, 8, 11)
            with patch('main.execute_action') as mock_execute:
                main.main()
        mock_execute.assert_not_called()

    def test_action_fires_within_15_minute_window(self):
        _write_config({"0": {"day": "Monday", "location": "office", "start_the_day": "09:00"}})
        with patch('main.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = datetime.datetime(2026, 8, 10, 9, 10)  # 10 min late
            mock_dt.date.today.return_value = datetime.date(2026, 8, 10)
            with patch('main.execute_action') as mock_execute:
                main.main()
        mock_execute.assert_called_once_with("start_day", "office")

    def test_action_does_not_fire_outside_15_minute_window(self):
        _write_config({"0": {"day": "Monday", "location": "office", "start_the_day": "09:00"}})
        with patch('main.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = datetime.datetime(2026, 8, 10, 9, 20)  # 20 min late
            mock_dt.date.today.return_value = datetime.date(2026, 8, 10)
            with patch('main.execute_action') as mock_execute:
                main.main()
        mock_execute.assert_not_called()

    def test_only_first_matching_task_fires(self):
        # Both entries fall within 15 minutes of 13:32; only the first (in
        # iteration order) should trigger an action, then the loop breaks.
        _write_config({
            "0": {
                "day": "Monday",
                "location": "office",
                "lunch_break": "13:30",
                "after_lunch_break": "13:35",
            }
        })
        with patch('main.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = datetime.datetime(2026, 8, 10, 13, 32)
            mock_dt.date.today.return_value = datetime.date(2026, 8, 10)
            with patch('main.execute_action') as mock_execute:
                main.main()
        mock_execute.assert_called_once_with("lunch_break", "office")

    def test_task_name_to_action_type_mapping(self):
        cases = [
            ("start_the_day", "start_day", "09:00", datetime.datetime(2026, 8, 10, 9, 0)),
            ("lunch_break", "lunch_break", "13:30", datetime.datetime(2026, 8, 10, 13, 30)),
            ("after_lunch_break", "after_lunch", "14:30", datetime.datetime(2026, 8, 10, 14, 30)),
            ("stop_the_day", "stop_day", "18:00", datetime.datetime(2026, 8, 10, 18, 0)),
        ]
        for task_key, expected_action_type, time_str, now in cases:
            with self.subTest(task=task_key):
                _write_config({"0": {"day": "Monday", "location": "office", task_key: time_str}})
                with patch('main.datetime') as mock_dt:
                    mock_dt.datetime.now.return_value = now
                    mock_dt.date.today.return_value = now.date()
                    with patch('main.execute_action') as mock_execute:
                        main.main()
                mock_execute.assert_called_once_with(expected_action_type, "office")
                os.remove("config/config.json")
                os.rmdir("config")

    def test_location_and_day_keys_are_skipped_not_treated_as_times(self):
        _write_config({
            "0": {
                "day": "Monday",
                "location": "home",
                "start_the_day": "09:00",
            }
        })
        with patch('main.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = datetime.datetime(2026, 8, 10, 9, 0)
            mock_dt.date.today.return_value = datetime.date(2026, 8, 10)
            with patch('main.execute_action') as mock_execute:
                main.main()  # would raise ValueError on "Monday".split(":") if not skipped
        mock_execute.assert_called_once_with("start_day", "home")


if __name__ == '__main__':
    unittest.main()
