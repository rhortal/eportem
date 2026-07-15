import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import shutil
import tempfile
import datetime
import unittest
from unittest.mock import patch

import override_location


class TestOverrideLocation(unittest.TestCase):
    def setUp(self):
        self.orig_cwd = os.getcwd()
        self.tmp_dir = tempfile.mkdtemp()
        os.chdir(self.tmp_dir)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmp_dir)

    def test_writes_location_and_today_date(self):
        with patch.object(sys, "argv", ["override_location.py", "home"]):
            override_location.main()
        with open("location_override.txt") as f:
            content = f.read().strip()
        location, date_str = content.split(",")
        self.assertEqual(location, "home")
        self.assertEqual(date_str, str(datetime.date.today()))

    def test_writes_office(self):
        with patch.object(sys, "argv", ["override_location.py", "office"]):
            override_location.main()
        with open("location_override.txt") as f:
            content = f.read().strip()
        location, _ = content.split(",")
        self.assertEqual(location, "office")

    def test_rejects_invalid_location(self):
        with patch.object(sys, "argv", ["override_location.py", "beach"]):
            with self.assertRaises(SystemExit):
                override_location.main()


if __name__ == '__main__':
    unittest.main()
