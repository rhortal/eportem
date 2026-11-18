import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import contextlib
import datetime
import io
import stat
import unittest
from unittest.mock import patch

import eportem_action
from eportem_action import EPortemAction
from tests.test_eportem import IsolatedCase
from utility import action_log, logfiles
from utility.http_clock import NotRecorded, OutcomeUnknown


def _http(self):
    print("Session: saved session still valid")
    print("HTTP clock action recorded: _ststop x")


def _notify(self):
    print("Telegram notification sent successfully.")
    return []


def _status(self):
    print("Slack status updated successfully.")
    return True


class TestRunLog(IsolatedCase):
    """Each run's block in logs/http_clock.log holds everything perform() printed."""

    def setUp(self):
        super().setUp()
        for p in (patch.dict(os.environ, {"EPORTEM_HTTP": "YES"}),
                  patch.object(EPortemAction, "_send_notifications", _notify),
                  patch.object(EPortemAction, "_update_slack_status", _status)):
            p.start()
            self.addCleanup(p.stop)

    def run_action(self, action="stop_day", raises=None, driver=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            if raises:
                with self.assertRaises(raises):
                    EPortemAction(action, "office", driver).perform()
            else:
                self.assertTrue(EPortemAction(action, "office", driver).perform())
        return out.getvalue()

    def log(self):
        with open(self.http_log) as f:
            return f.read()

    def test_http_block_has_attempt_and_follow_ups_in_order_and_console_is_unchanged(self):
        with patch.object(EPortemAction, "_perform_http", _http):
            console = self.run_action()
        expected = ("Session: saved session still valid\nHTTP clock action recorded: _ststop x\n"
                    "Telegram notification sent successfully.\nSlack status updated successfully.\n")
        self.assertEqual(console, expected)
        header, body = self.log().split("\n", 1)
        self.assertRegex(header, r"^=== \d{4}-\d\d-\d\d \d\d:\d\d:\d\d stop_day office: recorded over HTTP$")
        self.assertEqual(body, expected)

    def test_warning_line_is_in_the_block(self):
        with patch.object(EPortemAction, "_perform_http", _http), \
                patch.object(EPortemAction, "_send_notifications", lambda self: ["telegram"]):
            self.run_action()
        self.assertIn("WARNING: the clock action WAS recorded", self.log())

    def test_fallback_block_has_http_reason_browser_output_and_follow_ups(self):
        def browser(self):
            print("Clicking button 1")
        with patch.object(EPortemAction, "_perform_http", side_effect=NotRecorded("ButtonNotFound")), \
                patch.object(EPortemAction, "_perform_selenium", browser):
            console = self.run_action()
        self.assertEqual(self.log().count("==="), 1)  # one block per run
        lines = self.log().splitlines()
        self.assertTrue(lines[0].endswith(
            "stop_day office: not recorded, falling back to the browser: ButtonNotFound"))
        self.assertEqual(lines[1:], [
            "HTTP clock recorded nothing (ButtonNotFound); falling back to the browser",
            "Clicking button 1", "Telegram notification sent successfully.",
            "Slack status updated successfully."])
        self.assertEqual(console.splitlines(), lines[1:])

    def test_outcome_unknown_is_logged_and_reraised(self):
        def http(self):
            print("sent, no answer")
            raise OutcomeUnknown("check by hand")
        with patch.object(EPortemAction, "_perform_http", http):
            console = self.run_action(raises=OutcomeUnknown)
        self.assertEqual(console, "sent, no answer\n")
        header, body = self.log().split("\n", 1)
        self.assertTrue(header.endswith("stop_day office: OUTCOME UNKNOWN: check by hand"))
        self.assertEqual(body, "sent, no answer\n")

    def test_unexpected_error_is_logged_and_reraised(self):
        with patch.object(EPortemAction, "_perform_http", side_effect=RuntimeError("boom")):
            self.run_action(raises=RuntimeError)
        self.assertIn("stop_day office: ERROR, no fallback: RuntimeError: boom", self.log())

    def test_fallback_that_raises_is_logged_with_output_so_far_and_reraised(self):
        def browser(self):
            print("Clicking button 1")
            raise ValueError("no button")
        with patch.object(EPortemAction, "_perform_http", side_effect=NotRecorded("x")), \
                patch.object(EPortemAction, "_perform_selenium", browser):
            self.run_action(raises=ValueError)
        log = self.log()
        self.assertIn("stop_day office: not recorded, falling back to the browser: x", log)
        self.assertIn("Clicking button 1", log)
        self.assertIn("Browser fallback failed: ValueError: no button", log)
        self.assertNotIn("Telegram", log)  # follow-ups never ran
        self.assertFalse(os.path.exists(action_log.actions_log_path()))

    def test_browser_only_run_is_logged(self):
        with patch.dict(os.environ, {"EPORTEM_HTTP": "NO"}), \
                patch.object(EPortemAction, "_perform_selenium", lambda self: print("Clicking button 1")):
            self.run_action()
        header, body = self.log().split("\n", 1)
        self.assertTrue(header.endswith(
            "stop_day office: recorded with the browser (HTTP not enabled for this action)"))
        self.assertEqual(body, "Clicking button 1\nTelegram notification sent successfully.\n"
                               "Slack status updated successfully.\n")

    def test_browser_only_failure_is_logged_and_reraised(self):
        with patch.dict(os.environ, {"EPORTEM_HTTP": "NO"}), \
                patch.object(EPortemAction, "_perform_selenium", side_effect=ValueError("no button")):
            self.run_action(raises=ValueError)
        self.assertIn("ERROR, browser run failed: ValueError: no button", self.log())

    def test_log_follows_the_state_dir(self):
        # Tests that set only EPORTEM_STATE_DIR (not IsolatedCase) once wrote
        # fake runs into the real logs/http_clock.log
        self.assertEqual(eportem_action.http_log_path(), self.http_log)
        with patch.dict(os.environ, {"EPORTEM_STATE_DIR": ""}):
            self.assertEqual(eportem_action.http_log_path(), os.path.join(
                os.path.dirname(os.path.abspath(eportem_action.__file__)), "logs", "http_clock.log"))

    def test_log_write_failure_does_not_change_the_outcome(self):
        with patch.object(EPortemAction, "_perform_http", _http), \
                patch("utility.logfiles.os.open", side_effect=OSError("denied")):
            console = self.run_action()
        self.assertIn("Could not write", console)
        self.assertFalse(os.path.exists(self.http_log))

    def test_log_write_failure_does_not_hide_the_real_exception(self):
        with patch.object(EPortemAction, "_perform_http", side_effect=OutcomeUnknown("x")), \
                patch("utility.logfiles.os.open", side_effect=OSError("denied")):
            self.run_action(raises=OutcomeUnknown)


class TestLogFiles(unittest.TestCase):

    def setUp(self):
        import tempfile
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.dir = os.path.join(t.name, "logs")
        self.path = os.path.join(self.dir, "x.log")

    def read(self, suffix=""):
        with open(self.path + suffix) as f:
            return f.read()

    def fill(self, n, **kw):
        """Append "1", "2", ... "n" with a 3-byte limit so every append rotates."""
        for i in range(1, n + 1):
            logfiles.append(self.path, f"gen{i}\n", max_bytes=3, **kw)

    def test_under_the_limit_no_rotation(self):
        logfiles.append(self.path, "a\n", max_bytes=100)
        logfiles.append(self.path, "b\n", max_bytes=100)
        self.assertEqual(self.read(), "a\nb\n")
        self.assertFalse(os.path.exists(self.path + ".1"))

    def test_over_the_limit_creates_dot_one(self):
        logfiles.append(self.path, "a" * 50 + "\n", max_bytes=10)
        logfiles.append(self.path, "b\n", max_bytes=10)
        self.assertEqual(self.read(".1"), "a" * 50 + "\n")
        self.assertEqual(self.read(), "b\n")

    def test_generations_shift_and_the_oldest_is_dropped(self):
        self.fill(5, generations=3)
        self.assertEqual(self.read(), "gen5\n")
        self.assertEqual(self.read(".1"), "gen4\n")
        self.assertEqual(self.read(".2"), "gen3\n")
        self.assertEqual(self.read(".3"), "gen2\n")
        self.assertFalse(os.path.exists(self.path + ".4"))  # gen1 is gone

    def test_default_keeps_five_generations_of_one_megabyte(self):
        self.assertEqual((logfiles.MAX_BYTES, logfiles.GENERATIONS), (1_000_000, 5))

    def test_missing_middle_generation(self):
        self.fill(4, generations=4)  # file, .1, .2, .3
        os.remove(self.path + ".2")  # gen2 is lost; .3 (gen1) is older
        logfiles.append(self.path, "new\n", max_bytes=3, generations=4)
        self.assertEqual(self.read(".1"), "gen4\n")
        self.assertEqual(self.read(".2"), "gen3\n")  # the gap closes, nothing raises
        self.assertFalse(os.path.exists(self.path + ".3"))
        self.assertEqual(self.read(".4"), "gen1\n")
        self.assertEqual(self.read(), "new\n")

    def test_permissions(self):
        logfiles.append(self.path, "a\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.dir).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_loose_permissions_are_tightened(self):
        os.makedirs(self.dir, mode=0o755)
        with open(self.path, "w") as f:
            f.write("old\n")
        os.chmod(self.path, 0o644)
        os.chmod(self.dir, 0o755)
        logfiles.append(self.path, "a\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.dir).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_error_during_rotation_still_appends(self):
        logfiles.append(self.path, "a" * 50 + "\n", max_bytes=10)
        out = io.StringIO()
        with patch("utility.logfiles.os.replace", side_effect=OSError("denied")), \
                contextlib.redirect_stdout(out):
            logfiles.append(self.path, "b\n", max_bytes=10)
        self.assertEqual(out.getvalue().count("\n"), 1)
        self.assertIn("Could not rotate", out.getvalue())
        self.assertEqual(self.read(), "a" * 50 + "\n" + "b\n")

    def test_generation_paths_lists_existing_newest_first(self):
        self.fill(3, generations=5)
        self.assertEqual(logfiles.generation_paths(self.path),
                         [self.path + ".1", self.path + ".2"])


class TestVerifyDayReadsRotatedLogs(IsolatedCase):

    def test_action_only_in_a_rotated_generation_is_found(self):
        day = datetime.datetime(2026, 8, 10, 9, 0)
        action_log.record_action("start_day", "office", "http", day)
        path = action_log.actions_log_path()
        os.replace(path, path + ".1")  # a rotation in the middle of the day
        action_log.record_action("lunch_break", "office", "http", day.replace(hour=13))
        self.assertEqual(action_log.actions_recorded_on(day.date()), ["start_day", "lunch_break"])

    def test_oldest_generation_is_read_too(self):
        day = datetime.datetime(2026, 8, 10, 9, 0)
        action_log.record_action("start_day", "office", "http", day)
        path = action_log.actions_log_path()
        os.replace(path, path + ".5")
        self.assertEqual(action_log.actions_recorded_on(day.date()), ["start_day"])

    def test_verify_day_uses_it(self):
        import main
        day = datetime.datetime(2026, 8, 10, 9, 0)  # a Monday
        action_log.record_action("start_day", "office", "http", day)
        path = action_log.actions_log_path()
        os.replace(path, path + ".1")
        config = {"schedule": {"0": {"day": "Monday", "location": "office", "start_the_day": "09:00",
                                     "lunch_break": "13:30", "after_lunch_break": "14:30",
                                     "stop_the_day": "18:00"}}}
        now = datetime.datetime(2026, 8, 10, 10, 0)
        with patch("main.alerts.send_alert") as alert, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main._verify_day(config, now, "office"), main.EXIT_OK)
        alert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
