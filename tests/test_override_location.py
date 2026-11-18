import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import contextlib
import datetime
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import override_location


class TestOverrideLocation(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.state = Path(self._tmpdir.name)
        env = patch.dict(os.environ, {"EPORTEM_STATE_DIR": self._tmpdir.name})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self._tmpdir.cleanup)

    def run_cli(self, *args):
        out = io.StringIO()
        with patch('sys.argv', ['override_location.py', *args]), contextlib.redirect_stdout(out):
            override_location.main()
        return out.getvalue()

    def read(self, name):
        return (self.state / name).read_text()

    def test_writes_home_override_for_today_in_expected_format(self):
        out = self.run_cli('home')
        self.assertEqual(self.read("location_override.txt"), f"home,{datetime.date.today()}")
        self.assertIn(str(self.state / "location_override.txt"), out)

    def test_writes_office_override_for_today(self):
        self.run_cli('office')
        self.assertEqual(self.read("location_override.txt"), f"office,{datetime.date.today()}")

    def test_invalid_location_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_cli('mars')
        self.assertFalse((self.state / "location_override.txt").exists())

    def test_business_trip_single_day_writes_expected_format(self):
        out = self.run_cli('business-trip', '2026-08-20')
        self.assertEqual(self.read("business_trip_override.txt"), "2026-08-20,2026-08-20")
        self.assertIn(str(self.state / "business_trip_override.txt"), out)

    def test_business_trip_range_writes_expected_format(self):
        self.run_cli('business-trip', '2026-08-20', '2026-08-22')
        self.assertEqual(self.read("business_trip_override.txt"), "2026-08-20,2026-08-22")

    def test_business_trip_end_before_start_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_cli('business-trip', '2026-08-22', '2026-08-20')
        self.assertFalse((self.state / "business_trip_override.txt").exists())

    def test_business_trip_bad_date_is_rejected_cleanly(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_cli('business-trip', 'next-week')
        self.assertFalse((self.state / "business_trip_override.txt").exists())

    def test_business_trip_does_not_touch_location_override(self):
        self.run_cli('business-trip', '2026-08-20')
        self.assertFalse((self.state / "location_override.txt").exists())

    def test_writes_to_state_dir_even_when_cwd_is_elsewhere(self):
        with tempfile.TemporaryDirectory() as elsewhere:
            orig = os.getcwd()
            os.chdir(elsewhere)
            try:
                self.run_cli('home')
                self.run_cli('business-trip', '2026-08-20')
                self.assertEqual(os.listdir(elsewhere), [])
            finally:
                os.chdir(orig)
        self.assertTrue((self.state / "location_override.txt").exists())
        self.assertTrue((self.state / "business_trip_override.txt").exists())

    def test_default_location_is_the_repo_not_the_cwd(self):
        with patch.dict(os.environ, {"EPORTEM_STATE_DIR": ""}):
            self.assertEqual(override_location.state_path("x").parent,
                             Path(override_location.__file__).resolve().parent)

    def test_write_is_atomic_and_leaves_no_temp_files(self):
        with patch('override_location.os.replace', wraps=os.replace) as spy:
            self.run_cli('home')
        spy.assert_called_once()
        self.assertEqual([p.name for p in self.state.iterdir()], ["location_override.txt"])

    def test_failed_write_keeps_the_old_file_and_cleans_up(self):
        (self.state / "location_override.txt").write_text("office,2026-01-01")
        with patch('override_location.os.replace', side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                self.run_cli('home')
        self.assertEqual(self.read("location_override.txt"), "office,2026-01-01")
        self.assertEqual([p.name for p in self.state.iterdir()], ["location_override.txt"])


if __name__ == '__main__':
    unittest.main()
