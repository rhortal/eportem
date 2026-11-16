import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import contextlib
import datetime
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main

MONDAY = datetime.datetime(2026, 8, 10, 9, 0)
TUESDAY = datetime.datetime(2026, 8, 11, 9, 0)


class _StateDirMixin:
    """Points EPORTEM_STATE_DIR at a temp dir so tests never touch the real
    config or override files, whatever the cwd is."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.state = Path(self._tmpdir.name)
        env = patch.dict(os.environ, {"EPORTEM_STATE_DIR": self._tmpdir.name})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self._tmpdir.cleanup)

    def write_config(self, schedule):
        (self.state / "config").mkdir(exist_ok=True)
        (self.state / "config" / "config.json").write_text(json.dumps({"schedule": schedule}))

    def write_raw_config(self, text):
        (self.state / "config").mkdir(exist_ok=True)
        (self.state / "config" / "config.json").write_text(text)

    def write_location_override(self, location, date):
        (self.state / "location_override.txt").write_text(f"{location},{date}")

    def write_holiday(self, text):
        (self.state / "holiday_override.txt").write_text(text)

    def at(self, now):
        p = patch('main._now', return_value=now)
        p.start()
        self.addCleanup(p.stop)

    def run_main(self, argv=None):
        """Run main.main() with execute_action patched. Returns (code, execute mock, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with patch('main.execute_action') as mock_execute, \
             patch('main.update_holiday_slack_status'), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main.main(argv)
        return code, mock_execute, out.getvalue(), err.getvalue()


class TestDetermineLocation(_StateDirMixin, unittest.TestCase):

    def config(self, location="home"):
        return {"schedule": {"0": {"day": "Monday", "location": location}}}

    def test_config_location_used_when_no_override(self):
        self.at(MONDAY)
        self.assertEqual(main.determine_location(self.config("home")), "home")

    def test_config_entry_missing_location_key_defaults_to_office(self):
        self.at(MONDAY)
        self.assertEqual(main.determine_location({"schedule": {"0": {"day": "Monday"}}}), "office")

    def test_weekday_missing_from_schedule_defaults_to_office(self):
        self.at(TUESDAY)
        self.assertEqual(main.determine_location(self.config("home")), "office")

    def test_valid_override_for_today_wins_over_config(self):
        self.at(MONDAY)
        self.write_location_override("home", MONDAY.date())
        self.assertEqual(main.determine_location(self.config("office")), "home")

    def test_override_location_is_case_and_whitespace_insensitive(self):
        self.at(MONDAY)
        (self.state / "location_override.txt").write_text(f"﻿ Home , {MONDAY.date()} \n")
        self.assertEqual(main.determine_location(self.config("office")), "home")

    def test_stale_override_falls_back_to_config(self):
        self.at(MONDAY)
        self.write_location_override("office", MONDAY.date() - datetime.timedelta(days=1))
        self.assertEqual(main.determine_location(self.config("home")), "home")

    def test_malformed_override_falls_back_to_config_and_names_the_file(self):
        self.at(MONDAY)
        (self.state / "location_override.txt").write_text("not-a-valid-line")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main.determine_location(self.config("home")), "home")
        self.assertIn(str(self.state / "location_override.txt"), err.getvalue())
        # a malformed file is never deleted automatically
        self.assertTrue((self.state / "location_override.txt").exists())

    def test_unknown_location_value_is_treated_as_malformed(self):
        self.at(MONDAY)
        self.write_location_override("mars", MONDAY.date())
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main.determine_location(self.config("home")), "home")
        self.assertIn("mars", err.getvalue())

    def test_bad_date_in_override_is_treated_as_malformed(self):
        self.at(MONDAY)
        self.write_location_override("home", "someday")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main.determine_location(self.config("office")), "office")

    def test_stale_location_override_file_is_deleted(self):
        self.at(MONDAY)
        self.write_location_override("office", MONDAY.date() - datetime.timedelta(days=1))
        main.determine_location(self.config())
        self.assertFalse((self.state / "location_override.txt").exists())

    def test_stale_file_already_removed_by_another_run_is_not_an_error(self):
        self.at(MONDAY)
        self.write_location_override("office", MONDAY.date() - datetime.timedelta(days=1))
        with patch('main.os.remove', side_effect=FileNotFoundError):
            self.assertEqual(main.determine_location(self.config("home")), "home")

    def test_todays_location_override_file_is_kept(self):
        self.at(MONDAY)
        self.write_location_override("office", MONDAY.date())
        main.determine_location(self.config())
        self.assertTrue((self.state / "location_override.txt").exists())


class TestGetTodayHoliday(_StateDirMixin, unittest.TestCase):

    def setUp(self):
        super().setUp()
        self.at(MONDAY)
        self.today = MONDAY.date()

    def test_expired_file_is_deleted(self):
        past = self.today - datetime.timedelta(days=1)
        self.write_holiday(f"{past},{past}")
        self.assertIsNone(main.get_today_holiday())
        self.assertFalse((self.state / "holiday_override.txt").exists())

    def test_expired_file_already_gone_is_not_an_error(self):
        past = self.today - datetime.timedelta(days=1)
        self.write_holiday(f"{past},{past}")
        with patch('main.os.remove', side_effect=FileNotFoundError):
            self.assertIsNone(main.get_today_holiday())

    def test_future_file_is_kept(self):
        future = self.today + datetime.timedelta(days=3)
        self.write_holiday(f"{future},{future}")
        self.assertIsNone(main.get_today_holiday())
        self.assertTrue((self.state / "holiday_override.txt").exists())

    def test_range_ending_today_is_kept(self):
        self.write_holiday(f"{self.today - datetime.timedelta(days=1)},{self.today}")
        self.assertIsNotNone(main.get_today_holiday())
        self.assertTrue((self.state / "holiday_override.txt").exists())

    def test_tolerated_variations(self):
        t = self.today
        cases = {
            "whitespace around fields": f" {t} , {t} ",
            "trailing newline": f"{t},{t}\n",
            "BOM": f"﻿{t},{t}",
            "single date": f"{t}",
            "single date with newline": f"{t}\n",
            "CRLF": f"{t},{t}\r\n",
        }
        for name, text in cases.items():
            with self.subTest(name):
                (self.state / "holiday_override.txt").write_bytes(text.encode("utf-8"))
                self.assertEqual(main.get_today_holiday(), {"start": t, "end": t})

    def test_empty_file_means_no_holiday(self):
        for text in ("", "  \n"):
            with self.subTest(repr(text)):
                self.write_holiday(text)
                self.assertIsNone(main.get_today_holiday())
                self.assertTrue((self.state / "holiday_override.txt").exists())

    def test_rejected_variations_raise_and_keep_the_file(self):
        t = self.today
        for text in ("not-a-valid-line", f"{t},{t},{t}", f"{t},", ",", "2026-13-40",
                     f"{t},tomorrow", f"{t + datetime.timedelta(days=2)},{t}"):
            with self.subTest(text):
                self.write_holiday(text)
                with self.assertRaises(main.HolidayFileError):
                    main.get_today_holiday()
                self.assertTrue((self.state / "holiday_override.txt").exists())

    def test_undecodable_file_raises(self):
        (self.state / "holiday_override.txt").write_bytes(b"\xff\xfe\x00bad")
        with self.assertRaises(main.HolidayFileError):
            main.get_today_holiday()


class TestValidateConfig(unittest.TestCase):

    def ok_day(self, **extra):
        day = {"day": "Monday", "location": "office", "start_the_day": "9:00"}
        day.update(extra)
        return day

    def test_valid_config_has_no_problems(self):
        cfg = {"schedule": {"0": self.ok_day(lunch_break="13:30", after_lunch_break="14:30",
                                              stop_the_day="18:00"), "6": {}}}
        self.assertEqual(main.validate_config(cfg), [])

    def test_each_problem_is_reported_with_its_location(self):
        cases = [
            ({"schedule": {"7": self.ok_day()}}, 'schedule["7"]'),
            ({"schedule": {"mon": self.ok_day()}}, 'schedule["mon"]'),
            ({"schedule": {"0": "x"}}, 'schedule["0"]: must be an object'),
            ({"schedule": {"0": self.ok_day(location="Home")}}, 'schedule["0"]["location"]'),
            ({"schedule": {"0": self.ok_day(day=3)}}, 'schedule["0"]["day"]'),
            ({"schedule": {"0": self.ok_day(start_the_day="25:00")}}, 'schedule["0"]["start_the_day"]'),
            ({"schedule": {"0": self.ok_day(start_the_day="9:60")}}, 'schedule["0"]["start_the_day"]'),
            ({"schedule": {"0": self.ok_day(start_the_day="9")}}, 'schedule["0"]["start_the_day"]'),
            ({"schedule": {"0": self.ok_day(start_the_day=900)}}, 'schedule["0"]["start_the_day"]'),
            ({"schedule": {"0": self.ok_day(lunch_brake="13:00")}}, 'unknown key "lunch_brake"'),
            ({"schedule": []}, '"schedule" must be an object'),
            ({"sched": {}}, '"schedule" key'),
            ([], '"schedule" key'),
        ]
        for cfg, expected in cases:
            with self.subTest(expected):
                problems = main.validate_config(cfg)
                self.assertTrue(any(expected in p for p in problems), problems)

    def test_all_problems_are_listed_not_just_the_first(self):
        cfg = {"schedule": {"0": self.ok_day(start_the_day="99:00", lunch_brake="1:00"),
                            "9": {}}}
        self.assertEqual(len(main.validate_config(cfg)), 3)


class TestLoadConfig(_StateDirMixin, unittest.TestCase):

    def test_missing_file(self):
        with self.assertRaises(main.ConfigError) as cm:
            main.load_config()
        self.assertIn("not found", cm.exception.problems[0])

    def test_invalid_json(self):
        self.write_raw_config("{not json")
        with self.assertRaises(main.ConfigError) as cm:
            main.load_config()
        self.assertIn("not valid JSON", cm.exception.problems[0])

    def test_missing_schedule_key(self):
        self.write_raw_config("{}")
        with self.assertRaises(main.ConfigError):
            main.load_config()


class TestMain(_StateDirMixin, unittest.TestCase):

    def test_holiday_short_circuits_before_any_action(self):
        self.at(MONDAY)
        today = MONDAY.date()
        self.write_config({"0": {"day": "Monday", "location": "office", "start_the_day": "09:00"}})
        self.write_holiday(f"{today},{today}")
        out, err = io.StringIO(), io.StringIO()
        with patch('main.execute_action') as mock_execute, \
             patch('main.update_holiday_slack_status') as mock_update_status, \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main.main([])
        self.assertEqual(code, main.EXIT_OK)
        mock_execute.assert_not_called()
        mock_update_status.assert_called_once_with({"start": today, "end": today})

    def test_garbage_holiday_file_fails_closed(self):
        self.at(MONDAY)
        self.write_config({"0": {"day": "Monday", "location": "office", "start_the_day": "09:00"}})
        self.write_holiday("2026-12-24;2026-12-26")
        code, mock_execute, out, err = self.run_main([])
        self.assertEqual(code, main.EXIT_INVALID)
        self.assertNotEqual(code, 0)
        mock_execute.assert_not_called()
        self.assertIn(str(self.state / "holiday_override.txt"), err)
        self.assertIn("holiday_override.py", err)
        self.assertTrue((self.state / "holiday_override.txt").exists())

    def test_holiday_file_with_end_before_start_fails_closed(self):
        self.at(MONDAY)
        self.write_config({"0": {"day": "Monday", "location": "office", "start_the_day": "09:00"}})
        self.write_holiday("2026-08-12,2026-08-10")
        code, mock_execute, _, _ = self.run_main([])
        self.assertEqual(code, main.EXIT_INVALID)
        mock_execute.assert_not_called()

    def test_empty_holiday_file_clocks_normally(self):
        self.at(MONDAY)
        self.write_config({"0": {"day": "Monday", "location": "office", "start_the_day": "09:00"}})
        self.write_holiday("")
        code, mock_execute, _, _ = self.run_main([])
        self.assertEqual(code, 0)
        mock_execute.assert_called_once_with("start_day", "office")

    def test_invalid_config_exits_nonzero_and_lists_every_problem(self):
        self.at(MONDAY)
        self.write_config({"0": {"day": "Monday", "location": "Home", "start_the_day": "9:00",
                                  "lunch_brake": "13:00"},
                           "1": {"stop_the_day": "18:75"}})
        code, mock_execute, _, err = self.run_main([])
        self.assertEqual(code, main.EXIT_INVALID)
        mock_execute.assert_not_called()
        self.assertIn('schedule["0"]["location"]', err)
        self.assertIn('lunch_brake', err)
        self.assertIn('schedule["1"]["stop_the_day"]', err)
        self.assertIn(str(self.state / "config" / "config.json"), err)

    def test_invalid_entry_for_another_weekday_still_blocks_today(self):
        self.at(MONDAY)
        self.write_config({"0": {"day": "Monday", "start_the_day": "09:00"},
                           "3": {"start_the_day": "nine"}})
        code, mock_execute, _, _ = self.run_main([])
        self.assertEqual(code, main.EXIT_INVALID)
        mock_execute.assert_not_called()

    def test_missing_config_exits_nonzero(self):
        self.at(MONDAY)
        code, mock_execute, _, err = self.run_main([])
        self.assertEqual(code, main.EXIT_INVALID)
        mock_execute.assert_not_called()
        self.assertIn("not found", err)

    def test_config_without_schedule_key_exits_nonzero(self):
        self.at(MONDAY)
        self.write_raw_config('{"other": 1}')
        code, mock_execute, _, _ = self.run_main([])
        self.assertEqual(code, main.EXIT_INVALID)
        mock_execute.assert_not_called()

    def test_config_is_loaded_once_per_run(self):
        self.at(MONDAY)
        self.write_config({"0": {"day": "Monday", "location": "office", "start_the_day": "09:00"}})
        with patch('main.load_config', wraps=main.load_config) as spy:
            code, mock_execute, _, _ = self.run_main([])
        self.assertEqual(spy.call_count, 1)
        mock_execute.assert_called_once()

    def test_no_schedule_for_today_exits_zero_quietly(self):
        self.at(TUESDAY)
        self.write_config({"0": {"day": "Monday", "location": "office", "start_the_day": "09:00"}})
        code, mock_execute, out, _ = self.run_main([])
        self.assertEqual(code, 0)
        mock_execute.assert_not_called()
        self.assertIn("No schedule for today.", out)

    def test_action_fires_within_window(self):
        self.write_config({"0": {"day": "Monday", "location": "office", "start_the_day": "09:00"}})
        self.at(datetime.datetime(2026, 8, 10, 9, 10))
        code, mock_execute, _, _ = self.run_main([])
        self.assertEqual(code, 0)
        mock_execute.assert_called_once_with("start_day", "office")

    def test_window_edges(self):
        self.write_config({"0": {"day": "Monday", "location": "office", "start_the_day": "09:00"}})
        self.assertEqual(main.WINDOW_MINUTES, 15)
        for now, fires in ((datetime.datetime(2026, 8, 10, 8, 45), True),
                           (datetime.datetime(2026, 8, 10, 9, 15), True),
                           (datetime.datetime(2026, 8, 10, 8, 44), False),
                           (datetime.datetime(2026, 8, 10, 9, 16), False)):
            with self.subTest(now=now):
                with patch('main._now', return_value=now):
                    code, mock_execute, _, _ = self.run_main([])
                self.assertEqual(mock_execute.called, fires)
                self.assertEqual(code, 0 if fires else main.EXIT_NO_ACTION)

    def test_outside_every_window_exits_3_with_explanation(self):
        self.write_config({"0": {"day": "Monday", "location": "office",
                                  "start_the_day": "9:00", "stop_the_day": "18:00"}})
        self.at(datetime.datetime(2026, 8, 10, 18, 20))  # 20 min late
        code, mock_execute, out, err = self.run_main([])
        self.assertEqual(code, 3)
        mock_execute.assert_not_called()
        self.assertIn("18:20", err)
        self.assertIn("stop_the_day: 18:00 (window 17:45-18:15)", err)
        self.assertIn("start_the_day: 09:00 (window 08:45-09:15)", err)
        self.assertIn("crontab", err)

    def test_check_flag_never_clocks_and_exits_zero_when_it_would_run(self):
        self.write_config({"0": {"day": "Monday", "location": "home", "start_the_day": "09:00"}})
        self.at(MONDAY)
        code, mock_execute, out, _ = self.run_main(["--check"])
        self.assertEqual(code, 0)
        mock_execute.assert_not_called()
        self.assertIn("start_day", out)
        self.assertIn("home", out)

    def test_check_flag_exits_zero_when_no_action_matches(self):
        self.write_config({"0": {"day": "Monday", "location": "office", "start_the_day": "09:00"}})
        self.at(datetime.datetime(2026, 8, 10, 12, 0))
        code, mock_execute, out, err = self.run_main(["--check"])
        self.assertEqual(code, 0)
        mock_execute.assert_not_called()
        self.assertIn("No action would run", out)

    def test_check_flag_still_fails_on_invalid_config_or_holiday_file(self):
        self.at(MONDAY)
        self.write_config({"0": {"start_the_day": "nope"}})
        code, mock_execute, _, _ = self.run_main(["--check"])
        self.assertEqual(code, main.EXIT_INVALID)
        self.write_config({"0": {"start_the_day": "09:00"}})
        self.write_holiday("garbage")
        code, mock_execute, _, _ = self.run_main(["--check"])
        self.assertEqual(code, main.EXIT_INVALID)
        mock_execute.assert_not_called()

    def test_check_flag_does_not_set_slack_status_or_delete_stale_files(self):
        self.at(MONDAY)
        self.write_config({"0": {"day": "Monday", "start_the_day": "09:00"}})
        self.write_holiday(f"{MONDAY.date()},{MONDAY.date()}")
        self.write_location_override("home", MONDAY.date() - datetime.timedelta(days=1))
        with patch('main.update_holiday_slack_status') as mock_status, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main.main(["--check"]), 0)
        mock_status.assert_not_called()
        (self.state / "holiday_override.txt").unlink()
        with contextlib.redirect_stdout(io.StringIO()):
            main.main(["--check"])
        self.assertTrue((self.state / "location_override.txt").exists())

    def test_override_location_is_used_for_the_action(self):
        self.write_config({"0": {"day": "Monday", "location": "office", "start_the_day": "09:00"}})
        self.write_location_override("home", MONDAY.date())
        self.at(MONDAY)
        _, mock_execute, _, _ = self.run_main([])
        mock_execute.assert_called_once_with("start_day", "home")

    def test_only_first_matching_task_fires(self):
        self.write_config({"0": {"day": "Monday", "location": "office",
                                  "lunch_break": "13:30", "after_lunch_break": "13:35"}})
        self.at(datetime.datetime(2026, 8, 10, 13, 32))
        _, mock_execute, _, _ = self.run_main([])
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
                self.write_config({"0": {"day": "Monday", "location": "office", task_key: time_str}})
                with patch('main._now', return_value=now):
                    code, mock_execute, _, _ = self.run_main([])
                self.assertEqual(code, 0)
                mock_execute.assert_called_once_with(expected_action_type, "office")

    def test_location_and_day_keys_are_skipped_not_treated_as_times(self):
        self.write_config({"0": {"day": "Monday", "location": "home", "start_the_day": "09:00"}})
        self.at(MONDAY)
        _, mock_execute, _, _ = self.run_main([])
        mock_execute.assert_called_once_with("start_day", "home")

    def test_state_files_come_from_the_state_dir_not_the_cwd(self):
        self.write_config({"0": {"day": "Monday", "location": "office", "start_the_day": "09:00"}})
        self.at(MONDAY)
        with tempfile.TemporaryDirectory() as elsewhere:
            orig = os.getcwd()
            os.chdir(elsewhere)
            try:
                _, mock_execute, _, _ = self.run_main([])
            finally:
                os.chdir(orig)
        mock_execute.assert_called_once_with("start_day", "office")


if __name__ == '__main__':
    unittest.main()
