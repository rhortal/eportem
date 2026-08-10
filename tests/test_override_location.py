import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import datetime
import tempfile
import unittest
from unittest.mock import patch

import override_location


class TestOverrideLocation(unittest.TestCase):

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self._tmpdir.name)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        self._tmpdir.cleanup()

    def test_writes_home_override_for_today_in_expected_format(self):
        with patch('sys.argv', ['override_location.py', 'home']):
            override_location.main()
        with open("location_override.txt") as f:
            contents = f.read()
        self.assertEqual(contents, f"home,{datetime.date.today()}")

    def test_writes_office_override_for_today(self):
        with patch('sys.argv', ['override_location.py', 'office']):
            override_location.main()
        with open("location_override.txt") as f:
            contents = f.read()
        self.assertEqual(contents, f"office,{datetime.date.today()}")

    def test_invalid_location_is_rejected(self):
        with patch('sys.argv', ['override_location.py', 'mars']):
            with self.assertRaises(SystemExit):
                override_location.main()
        self.assertFalse(os.path.exists("location_override.txt"))


if __name__ == '__main__':
    unittest.main()
