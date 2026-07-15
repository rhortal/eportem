import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
import shutil
import tempfile
import datetime
import unittest
from unittest.mock import patch, MagicMock

import main


class TestGetTodayHoliday(unittest.TestCase):
    def setUp(self):
        self.orig_cwd = os.getcwd()
        self.tmp_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp_dir, "config"))
        os.chdir(self.tmp_dir)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmp_dir)

    def write_holidays(self, holidays):
        with open("config/holidays.json", "w") as f:
            json.dump({"holidays": holidays}, f)

    def test_no_holidays_file(self):
        self.assertIsNone(main.get_today_holiday())

    def test_today_within_range(self):
        today = datetime.date.today()
        self.write_holidays([{
            "start": str(today - datetime.timedelta(days=1)),
            "end": str(today + datetime.timedelta(days=1)),
            "type": "holiday",
        }])
        result = main.get_today_holiday()
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "holiday")

    def test_today_is_boundary_end_date(self):
        today = datetime.date.today()
        self.write_holidays([{
            "start": str(today - datetime.timedelta(days=4)),
            "end": str(today),
            "type": "business_trip",
        }])
        result = main.get_today_holiday()
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "business_trip")

    def test_today_outside_range(self):
        today = datetime.date.today()
        self.write_holidays([{
            "start": str(today + datetime.timedelta(days=5)),
            "end": str(today + datetime.timedelta(days=10)),
            "type": "holiday",
        }])
        self.assertIsNone(main.get_today_holiday())

    def test_no_matching_entry_among_several(self):
        today = datetime.date.today()
        self.write_holidays([
            {"start": str(today - datetime.timedelta(days=30)), "end": str(today - datetime.timedelta(days=25)), "type": "holiday"},
            {"start": str(today + datetime.timedelta(days=25)), "end": str(today + datetime.timedelta(days=30)), "type": "business_trip"},
        ])
        self.assertIsNone(main.get_today_holiday())


class TestDetermineLocation(unittest.TestCase):
    def setUp(self):
        self.orig_cwd = os.getcwd()
        self.tmp_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp_dir, "config"))
        os.chdir(self.tmp_dir)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmp_dir)

    def write_config(self, weekday_num, location):
        with open("config/config.json", "w") as f:
            json.dump({"schedule": {weekday_num: {
                "day": "X",
                "location": location,
                "start_the_day": "9:00",
                "lunch_break": "13:30",
                "after_lunch_break": "14:30",
                "stop_the_day": "18:00",
            }}}, f)

    def test_uses_config_location_when_no_override(self):
        today_weekday = str(datetime.date.today().weekday())
        self.write_config(today_weekday, "home")
        self.assertEqual(main.determine_location(), "home")

    def test_defaults_to_office_when_no_schedule_for_today(self):
        other_weekday = str((datetime.date.today().weekday() + 1) % 7)
        self.write_config(other_weekday, "home")
        self.assertEqual(main.determine_location(), "office")

    def test_override_file_wins_when_dated_today(self):
        today_weekday = str(datetime.date.today().weekday())
        self.write_config(today_weekday, "office")
        with open("location_override.txt", "w") as f:
            f.write(f"home,{datetime.date.today()}")
        self.assertEqual(main.determine_location(), "home")

    def test_override_file_ignored_when_dated_yesterday(self):
        today_weekday = str(datetime.date.today().weekday())
        self.write_config(today_weekday, "office")
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        with open("location_override.txt", "w") as f:
            f.write(f"home,{yesterday}")
        self.assertEqual(main.determine_location(), "office")

    def test_malformed_override_file_falls_back_to_config(self):
        today_weekday = str(datetime.date.today().weekday())
        self.write_config(today_weekday, "home")
        with open("location_override.txt", "w") as f:
            f.write("not,a,valid,override,line")
        self.assertEqual(main.determine_location(), "home")


class TestMainRunsScheduledAction(unittest.TestCase):
    def setUp(self):
        self.orig_cwd = os.getcwd()
        self.tmp_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp_dir, "config"))
        os.chdir(self.tmp_dir)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmp_dir)

    def write_config(self, weekday_num, start_time):
        with open("config/config.json", "w") as f:
            json.dump({"schedule": {weekday_num: {
                "day": "X",
                "location": "office",
                "start_the_day": start_time,
                "lunch_break": "13:30",
                "after_lunch_break": "14:30",
                "stop_the_day": "18:00",
            }}}, f)

    def test_executes_action_within_time_window(self):
        now = datetime.datetime.now()
        self.write_config(str(now.weekday()), now.strftime("%H:%M"))
        with patch("main.execute_action") as mock_execute:
            main.main()
            mock_execute.assert_called_once_with("start_day", "office")

    def test_no_action_when_outside_time_window(self):
        now = datetime.datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
        self.write_config(str(now.weekday()), "9:00")
        with patch("main.datetime") as mock_datetime:
            mock_datetime.datetime.now.return_value = now.replace(hour=15, minute=0)
            mock_datetime.date.today.return_value = now.date()
            mock_datetime.timedelta = datetime.timedelta
            with patch("main.execute_action") as mock_execute:
                main.main()
                mock_execute.assert_not_called()

    def test_no_schedule_for_today(self):
        other_weekday = str((datetime.datetime.now().weekday() + 1) % 7)
        self.write_config(other_weekday, "9:00")
        with patch("main.execute_action") as mock_execute:
            main.main()
            mock_execute.assert_not_called()


class TestHandleHoliday(unittest.TestCase):
    def setUp(self):
        self.orig_cwd = os.getcwd()
        self.tmp_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp_dir, "config"))
        os.chdir(self.tmp_dir)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmp_dir)

    def write_config(self, weekday_num, start_time="9:00"):
        with open("config/config.json", "w") as f:
            json.dump({"schedule": {weekday_num: {
                "day": "X",
                "location": "office",
                "start_the_day": start_time,
                "lunch_break": "13:30",
                "after_lunch_break": "14:30",
                "stop_the_day": "18:00",
            }}}, f)

    def test_skips_slack_when_disabled(self):
        now = datetime.datetime.now()
        self.write_config(str(now.weekday()), start_time=now.strftime("%H:%M"))
        with patch.dict(os.environ, {"SLACK_STATUS": "NO"}):
            with patch("utility.slack_status.SlackStatusUpdater") as mock_updater_cls:
                main.handle_holiday({"start": "2020-01-01", "end": "2099-01-05", "type": "holiday"}, now)
                mock_updater_cls.assert_not_called()

    def test_sets_slack_status_within_time_window(self):
        now = datetime.datetime.now()
        self.write_config(str(now.weekday()), start_time=now.strftime("%H:%M"))
        with patch.dict(os.environ, {"SLACK_STATUS": "YES"}):
            with patch("utility.slack_status.SlackStatusUpdater") as mock_updater_cls:
                mock_instance = MagicMock()
                mock_updater_cls.return_value = mock_instance
                main.handle_holiday({"start": "2020-01-01", "end": "2099-01-05", "type": "holiday"}, now)
                mock_instance.set_status.assert_called_once()
                text, emoji, expiration = mock_instance.set_status.call_args[0]
                self.assertEqual(text, "On holiday")
                self.assertEqual(emoji, ":palm_tree:")
                self.assertGreater(expiration, 0)

    def test_business_trip_uses_airplane_status(self):
        now = datetime.datetime.now()
        self.write_config(str(now.weekday()), start_time=now.strftime("%H:%M"))
        with patch.dict(os.environ, {"SLACK_STATUS": "YES"}):
            with patch("utility.slack_status.SlackStatusUpdater") as mock_updater_cls:
                mock_instance = MagicMock()
                mock_updater_cls.return_value = mock_instance
                main.handle_holiday({"start": "2020-01-01", "end": "2099-01-05", "type": "business_trip"}, now)
                text, emoji, _ = mock_instance.set_status.call_args[0]
                self.assertEqual(text, "On a business trip")
                self.assertEqual(emoji, ":airplane:")

    def test_no_slack_call_outside_time_window(self):
        now = datetime.datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
        self.write_config(str(now.weekday()), start_time="9:00")
        far_from_start = now.replace(hour=15, minute=0)
        with patch.dict(os.environ, {"SLACK_STATUS": "YES"}):
            with patch("utility.slack_status.SlackStatusUpdater") as mock_updater_cls:
                main.handle_holiday({"start": "2020-01-01", "end": "2099-01-05", "type": "holiday"}, far_from_start)
                mock_updater_cls.assert_not_called()

    def test_no_schedule_for_today_skips_slack(self):
        now = datetime.datetime.now()
        other_weekday = str((now.weekday() + 1) % 7)
        self.write_config(other_weekday, start_time="9:00")
        with patch.dict(os.environ, {"SLACK_STATUS": "YES"}):
            with patch("utility.slack_status.SlackStatusUpdater") as mock_updater_cls:
                main.handle_holiday({"start": "2020-01-01", "end": "2099-01-05", "type": "holiday"}, now)
                mock_updater_cls.assert_not_called()


class TestMainSkipsOnHoliday(unittest.TestCase):
    def setUp(self):
        self.orig_cwd = os.getcwd()
        self.tmp_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp_dir, "config"))
        os.chdir(self.tmp_dir)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmp_dir)

    def test_execute_action_not_called_on_holiday(self):
        today = datetime.date.today()
        with open("config/holidays.json", "w") as f:
            json.dump({"holidays": [{"start": str(today), "end": str(today), "type": "holiday"}]}, f)
        now = datetime.datetime.now()
        with open("config/config.json", "w") as f:
            json.dump({"schedule": {str(now.weekday()): {
                "day": "X", "location": "office",
                "start_the_day": now.strftime("%H:%M"),
                "lunch_break": "13:30", "after_lunch_break": "14:30", "stop_the_day": "18:00",
            }}}, f)
        with patch.dict(os.environ, {"SLACK_STATUS": "NO"}):
            with patch("main.execute_action") as mock_execute:
                main.main()
                mock_execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
