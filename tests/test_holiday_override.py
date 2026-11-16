import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import contextlib
import datetime
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import holiday_override
import main


NOW = datetime.datetime(2026, 8, 10, 9, 0)


class _StateDirMixin:

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.state = Path(self._tmpdir.name)
        env = patch.dict(os.environ, {"EPORTEM_STATE_DIR": self._tmpdir.name})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self._tmpdir.cleanup)
        now = patch('main._now', return_value=NOW)
        now.start()
        self.addCleanup(now.stop)
        self.today = NOW.date()

    def _write_override(self, start, end):
        (self.state / "holiday_override.txt").write_text(f"{start},{end}")


class TestIsHoliday(_StateDirMixin, unittest.TestCase):

    def test_no_override_file(self):
        self.assertFalse(main.is_holiday())

    def test_today_within_range(self):
        self._write_override(self.today - datetime.timedelta(days=1), self.today + datetime.timedelta(days=1))
        self.assertTrue(main.is_holiday())

    def test_today_is_single_day_holiday(self):
        self._write_override(self.today, self.today)
        self.assertTrue(main.is_holiday())

    def test_range_in_the_past(self):
        past = self.today - datetime.timedelta(days=10)
        self._write_override(past, past)
        self.assertFalse(main.is_holiday())

    def test_range_in_the_future(self):
        future = self.today + datetime.timedelta(days=10)
        self._write_override(future, future)
        self.assertFalse(main.is_holiday())

    def test_malformed_file_is_an_error_not_a_working_day(self):
        (self.state / "holiday_override.txt").write_text("not-a-valid-line")
        with self.assertRaises(main.HolidayFileError):
            main.is_holiday()


class TestGetTodayHoliday(_StateDirMixin, unittest.TestCase):

    def test_no_override_returns_none(self):
        self.assertIsNone(main.get_today_holiday())

    def test_today_in_range_returns_start_and_end(self):
        self._write_override(self.today, self.today)
        self.assertEqual(main.get_today_holiday(), {"start": self.today, "end": self.today})

    def test_out_of_range_returns_none(self):
        past = self.today - datetime.timedelta(days=10)
        self._write_override(past, past)
        self.assertIsNone(main.get_today_holiday())


class TestHolidayOverrideCli(_StateDirMixin, unittest.TestCase):

    def run_cli(self, *args):
        out = io.StringIO()
        with patch('sys.argv', ['holiday_override.py', *args]), contextlib.redirect_stdout(out):
            holiday_override.main()
        return out.getvalue()

    def test_single_day_format_and_printed_path(self):
        out = self.run_cli("2026-12-24")
        self.assertEqual((self.state / "holiday_override.txt").read_text(), "2026-12-24,2026-12-24")
        self.assertIn(str(self.state / "holiday_override.txt"), out)

    def test_range_format(self):
        self.run_cli("2026-12-24", "2026-12-26")
        self.assertEqual((self.state / "holiday_override.txt").read_text(), "2026-12-24,2026-12-26")

    def test_writes_to_state_dir_even_when_cwd_is_elsewhere(self):
        with tempfile.TemporaryDirectory() as elsewhere:
            orig = os.getcwd()
            os.chdir(elsewhere)
            try:
                self.run_cli("2026-12-24")
                self.assertEqual(os.listdir(elsewhere), [])
            finally:
                os.chdir(orig)
        self.assertTrue((self.state / "holiday_override.txt").exists())

    def test_default_location_is_the_repo_not_the_cwd(self):
        with patch.dict(os.environ, {"EPORTEM_STATE_DIR": ""}):
            self.assertEqual(holiday_override.state_path("x").parent,
                             Path(holiday_override.__file__).resolve().parent)

    def test_the_file_main_reads_is_the_file_the_cli_wrote(self):
        self.run_cli(str(self.today))
        self.assertIsNotNone(main.get_today_holiday())

    def test_write_is_atomic_and_leaves_no_temp_files(self):
        with patch('holiday_override.os.replace', wraps=os.replace) as spy:
            self.run_cli("2026-12-24")
        spy.assert_called_once()
        self.assertEqual([p.name for p in self.state.iterdir()], ["holiday_override.txt"])

    def test_failed_write_keeps_the_old_file_and_cleans_up(self):
        (self.state / "holiday_override.txt").write_text("2026-01-01,2026-01-02")
        with patch('holiday_override.os.replace', side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                self.run_cli("2026-12-24")
        self.assertEqual((self.state / "holiday_override.txt").read_text(), "2026-01-01,2026-01-02")
        self.assertEqual([p.name for p in self.state.iterdir()], ["holiday_override.txt"])

    def test_end_before_start_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_cli("2026-12-26", "2026-12-24")
        self.assertFalse((self.state / "holiday_override.txt").exists())

    def test_bad_date_is_rejected_cleanly(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_cli("24/12/2026")
        self.assertFalse((self.state / "holiday_override.txt").exists())


class TestUpdateHolidaySlackStatus(unittest.TestCase):

    def _holiday(self, end=None):
        return {"start": datetime.date(2026, 8, 12), "end": end or datetime.date(2026, 8, 17)}

    def test_skipped_when_slack_status_not_enabled(self):
        with patch.dict(os.environ, {"SLACK_STATUS": "NO"}, clear=False), \
             patch('utility.slack_status.SlackStatusUpdater') as mock_updater_cls:
            main.update_holiday_slack_status(self._holiday())
        mock_updater_cls.assert_not_called()

    def test_sets_on_holiday_status(self):
        with patch.dict(os.environ, {"SLACK_STATUS": "YES"}, clear=False), \
             patch('utility.slack_status.SlackStatusUpdater') as mock_updater_cls:
            main.update_holiday_slack_status(self._holiday())
        mock_updater_cls.return_value.set_status.assert_called_once()
        text, emoji, expiration = mock_updater_cls.return_value.set_status.call_args[0]
        self.assertEqual((text, emoji), ("On holiday", ":palm_tree:"))

    def test_expiration_is_end_of_day_on_end_date(self):
        end_date = datetime.date(2026, 8, 17)
        expected = int(datetime.datetime.combine(end_date, datetime.time(23, 59)).timestamp())
        with patch.dict(os.environ, {"SLACK_STATUS": "YES"}, clear=False), \
             patch('utility.slack_status.SlackStatusUpdater') as mock_updater_cls:
            main.update_holiday_slack_status(self._holiday(end=end_date))
        _, _, expiration = mock_updater_cls.return_value.set_status.call_args[0]
        self.assertEqual(expiration, expected)


if __name__ == '__main__':
    unittest.main()
