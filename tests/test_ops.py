import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import contextlib
import datetime
import io
import stat
import unittest
from unittest.mock import MagicMock, patch

import main
import eportem_action
from eportem_action import EPortemAction
from utility import action_log, alerts
from utility.timestamps import TimestampedStream
from tests.test_main import _StateDirMixin, MONDAY
from tests.test_eportem import IsolatedCase

DAY = {"day": "Monday", "location": "office", "start_the_day": "09:00",
       "lunch_break": "13:30", "after_lunch_break": "14:30", "stop_the_day": "18:00"}


class TestActionLog(IsolatedCase):

    def lines(self):
        with open(action_log.actions_log_path()) as f:
            return f.read().splitlines()

    def test_selenium_path_records_a_browser_line(self):
        EPortemAction("lunch_break", "home", MagicMock()).perform()
        (line,) = self.lines()
        ts, date, action, location, how = line.split()
        self.assertEqual((action, location, how), ("lunch_break", "home", "browser"))
        self.assertEqual(date, ts[:10])
        datetime.datetime.fromisoformat(ts)

    def test_http_path_records_an_http_line(self):
        with patch.dict(os.environ, {"EPORTEM_HTTP": "YES"}), \
                patch.object(EPortemAction, "_perform_http"):
            EPortemAction("stop_day", "office").perform()
        self.assertTrue(self.lines()[0].endswith(" stop_day office http"))

    def test_http_fallback_records_browser(self):
        from utility.http_clock import NotRecorded
        with patch.dict(os.environ, {"EPORTEM_HTTP": "YES"}), \
                patch.object(EPortemAction, "_perform_http", side_effect=NotRecorded("x")), \
                patch.object(EPortemAction, "_perform_selenium"):
            EPortemAction("stop_day", "office").perform()
        self.assertTrue(self.lines()[0].endswith(" stop_day office browser"))

    def test_nothing_recorded_when_the_action_fails(self):
        driver = MagicMock()
        driver.find_element.side_effect = Exception("boom")
        with patch("eportem_action.RETRY_PAUSE_SECONDS", 0), patch("eportem_action.BUTTON_WAIT_SECONDS", 0):
            with self.assertRaises(Exception), contextlib.redirect_stdout(io.StringIO()):
                EPortemAction("lunch_break", "office", driver).perform()
        self.assertFalse(os.path.exists(action_log.actions_log_path()))

    def test_permissions(self):
        action_log.record_action("start_day", "office", "http")
        path = action_log.actions_log_path()
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode), 0o700)

    def test_write_failure_never_raises_and_does_not_fail_the_run(self):
        out = io.StringIO()
        with patch("utility.logfiles.os.open", side_effect=OSError("disk full")), \
                contextlib.redirect_stdout(out):
            action_log.record_action("start_day", "office", "http")  # must not raise
            self.assertTrue(EPortemAction("start_day", "office", MagicMock()).perform())
        self.assertIn("Could not write actions.log", out.getvalue())

    def test_reader_ignores_junk_and_other_days(self):
        action_log.record_action("start_day", "office", "http", datetime.datetime(2026, 8, 9, 9, 0))
        action_log.record_action("start_day", "office", "http", datetime.datetime(2026, 8, 10, 9, 0))
        with open(action_log.actions_log_path(), "a") as f:
            f.write("garbage\n\n")
        self.assertEqual(action_log.actions_recorded_on(datetime.date(2026, 8, 10)), ["start_day"])
        self.assertEqual(action_log.actions_recorded_on(datetime.date(2026, 8, 11)), [])


class TestVerifyDay(_StateDirMixin, unittest.TestCase):

    def setUp(self):
        super().setUp()
        self.write_config({"0": dict(DAY)})
        p = patch("main.alerts.send_alert")
        self.alert = p.start()
        self.addCleanup(p.stop)

    def record(self, *actions, day=MONDAY):
        for a in actions:
            action_log.record_action(a, "office", "http", day.replace(hour=9))

    def verify(self, hour, minute=0):
        self.at(MONDAY.replace(hour=hour, minute=minute))
        return self.run_main(["--verify-day"])

    def test_all_present(self):
        self.record("start_day", "lunch_break", "after_lunch", "stop_day")
        code, _, out, err = self.verify(19)
        self.assertEqual(code, 0)
        self.assertIn("Day check OK: start_day, lunch_break, after_lunch and stop_day", out)
        self.alert.assert_not_called()

    def test_missing_alerts_and_exits_4(self):
        self.record("start_day", "stop_day")
        code, _, out, err = self.verify(19)
        self.assertEqual(code, main.EXIT_UNVERIFIED)
        self.assertEqual(code, 4)
        text = "ePortem: today's lunch_break and after_lunch were not recorded. Check Registro Jornada."
        self.assertIn(text, err)
        self.alert.assert_called_once_with(text)

    def test_single_missing_uses_was(self):
        self.record("start_day", "lunch_break", "after_lunch")
        code, *_ = self.verify(19)
        self.assertEqual(code, 4)
        self.alert.assert_called_once_with(
            "ePortem: today's stop_day was not recorded. Check Registro Jornada.")

    def test_duplicate_is_flagged(self):
        self.record("start_day", "start_day", "lunch_break", "after_lunch", "stop_day")
        code, *_ = self.verify(19)
        self.assertEqual(code, 4)
        (text,), _ = self.alert.call_args
        self.assertIn("start_day was recorded twice", text)

    def test_yesterday_does_not_count(self):
        self.record("start_day", "lunch_break", "after_lunch", "stop_day",
                    day=MONDAY - datetime.timedelta(days=1))
        code, *_ = self.verify(19)
        self.assertEqual(code, 4)

    def test_window_not_yet_closed_is_not_judged(self):
        # start 09:00: judged from 09:30; lunch 13:30 from 14:00
        code, _, out, _ = self.verify(9, 29)
        self.assertEqual(code, 0)
        self.assertIn("nothing to verify", out)
        code, *_ = self.verify(9, 30)
        self.assertEqual(code, 4)
        (text,), _ = self.alert.call_args
        self.assertIn("today's start_day was not recorded", text)
        self.assertNotIn("lunch_break", text)

    def test_grace_constant_is_what_decides(self):
        with patch("main.VERIFY_GRACE_MINUTES", 0):
            code, *_ = self.verify(9, 15)
        self.assertEqual(code, 4)

    def test_holiday_is_silent(self):
        self.write_holiday(f"{MONDAY.date()},{MONDAY.date()}")
        code, _, out, err = self.verify(19)
        self.assertEqual(code, 0)
        self.assertIn("holiday", out)
        self.alert.assert_not_called()
        self.assertTrue((self.state / "holiday_override.txt").exists())

    def test_no_schedule_is_silent(self):
        self.write_config({"3": dict(DAY)})
        code, _, out, _ = self.verify(19)
        self.assertEqual(code, 0)
        self.assertIn("No schedule for today", out)
        self.alert.assert_not_called()

    def test_disabled_is_silent(self):
        with patch.dict(os.environ, {"EPORTEM_ENABLED": "NO"}):
            code, _, out, err = self.verify(19)
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "ePortem is disabled (EPORTEM_ENABLED is not YES); nothing done.")
        self.alert.assert_not_called()

    def test_invalid_config_exits_2_with_an_alert(self):
        self.write_raw_config("{")
        code, *_ = self.verify(19)
        self.assertEqual(code, 2)
        (text,), _ = self.alert.call_args
        self.assertIn("ePortem: verify-day FAILED at 19:00 - invalid configuration", text)

    def test_check_and_verify_day_are_exclusive(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main.main(["--check", "--verify-day"])


class TestFailureAlerts(_StateDirMixin, unittest.TestCase):

    def setUp(self):
        super().setUp()
        self.write_config({"0": dict(DAY)})
        p = patch("main.alerts.send_alert", return_value=True)
        self.alert = p.start()
        self.addCleanup(p.stop)

    def text(self):
        (text,), _ = self.alert.call_args
        return text

    def test_exception_alerts_and_still_raises(self):
        self.at(MONDAY)
        with patch("main.execute_action", side_effect=RuntimeError("login rejected")), \
                patch("main.update_holiday_slack_status"), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                main.main([])
        self.assertEqual(self.text(), "ePortem: start_day FAILED at 09:00 - RuntimeError: login rejected. "
                                      "Check ePortem by hand; details in the cron mail.")

    def test_exception_text_is_scrubbed_single_line_and_has_no_traceback(self):
        self.at(MONDAY)
        err = RuntimeError("bad https://api.telegram.org/bot123:ABC/sendMessage\n  File x line 3\n"
                           "pw hunter2 " + "x" * 500)
        with patch.dict(os.environ, {"EPORTEM_PASSWORD": "hunter2"}), \
                patch("main.execute_action", side_effect=err), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                main.main([])
        text = self.text()
        self.assertNotIn("123:ABC", text)
        self.assertNotIn("hunter2", text)
        self.assertNotIn("\n", text)
        self.assertNotIn("Traceback", text)
        self.assertLess(len(text), 400)

    def test_exit_2_alerts_with_run_label(self):
        self.write_raw_config("{")
        self.at(MONDAY)
        code, *_ = self.run_main([])
        self.assertEqual(code, 2)
        self.assertTrue(self.text().startswith("ePortem: run FAILED at 09:00 - invalid configuration"))

    def test_exit_3_alerts(self):
        self.at(MONDAY.replace(hour=11))
        code, *_ = self.run_main([])
        self.assertEqual(code, 3)
        self.assertIn("run FAILED at 11:00 - the time 11:00 is outside every", self.text())

    def test_no_alert_for_check(self):
        self.at(MONDAY.replace(hour=11))
        self.assertEqual(self.run_main(["--check"])[0], 0)
        self.write_raw_config("{")
        self.assertEqual(self.run_main(["--check"])[0], 2)
        self.alert.assert_not_called()

    def test_no_alert_for_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main.main(["--nope"])
        self.alert.assert_not_called()

    def test_no_alert_when_disabled(self):
        self.at(MONDAY.replace(hour=11))
        with patch.dict(os.environ, {"EPORTEM_ENABLED": "NO"}):
            code, _, out, _ = self.run_main([])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "ePortem is disabled (EPORTEM_ENABLED is not YES); nothing done.")
        self.alert.assert_not_called()

    def test_disabled_skips_config_validation_and_holiday_status(self):
        self.write_raw_config("{")
        self.write_holiday(f"{MONDAY.date()},{MONDAY.date()}")
        self.at(MONDAY)
        with patch.dict(os.environ, {"EPORTEM_ENABLED": "NO"}), \
                patch("main.update_holiday_slack_status") as status, \
                patch("main.execute_action") as execute, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main.main([]), 0)
        status.assert_not_called()
        execute.assert_not_called()

    def test_check_still_validates_when_disabled(self):
        self.write_raw_config("{")
        with patch.dict(os.environ, {"EPORTEM_ENABLED": "NO"}):
            code, *_ = self.run_main(["--check"])
        self.assertEqual(code, 2)

    def test_recorded_action_with_failed_followups_does_not_alert(self):
        # The real perform(): the action is recorded, notifications fail, exit stays 0
        self.at(MONDAY)
        with patch.dict(os.environ, {"EPORTEM_HTTP": "NO", "TELEGRAM_NOTIFY": "YES"}), \
                patch.object(EPortemAction, "_perform_selenium"), \
                patch.object(EPortemAction, "_send_notifications", return_value=["telegram"]), \
                patch("main.execute_action", side_effect=eportem_action.execute_action), \
                patch("main.update_holiday_slack_status"):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main.main([])
        self.assertEqual(code, 0)
        self.assertIn("WARNING: the clock action WAS recorded", out.getvalue())
        self.alert.assert_not_called()

    def test_alert_failure_does_not_change_the_exit_code(self):
        self.at(MONDAY.replace(hour=11))
        self.alert.side_effect = RuntimeError("slack down")
        with patch("main.execute_action"), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            code = main.main([])
        self.assertEqual(code, 3)

    def test_alert_failure_does_not_mask_the_original_exception(self):
        self.at(MONDAY)
        self.alert.side_effect = RuntimeError("slack down")
        with patch("main.execute_action", side_effect=ValueError("orig")), \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):
                main.main([])


class TestSendAlert(unittest.TestCase):
    """The helper itself, with requests.post stubbed so nothing leaves the machine."""

    ENV = {"TELEGRAM_NOTIFY": "NO", "SLACK_NOTIFY": "NO", "TELEGRAM_BOT_TOKEN": "tok123",
           "TELEGRAM_CHAT_ID": "42", "SLACK_BOT_TOKEN": "", "SLACK_TOKEN": "",
           "SLACK_WEBHOOK_URL": "", "SLACK_NOTIFY_CHANNEL": ""}

    def send(self, text="hi", **env):
        post = MagicMock(return_value=MagicMock(status_code=200, ok=True))
        out = io.StringIO()
        with patch.dict(os.environ, dict(self.ENV, **env)), \
                patch("utility.notification_send.requests.post", post), \
                contextlib.redirect_stdout(out):
            result = alerts.send_alert(text)
        return result, post, out.getvalue()

    def test_no_channel_enabled_sends_nothing(self):
        result, post, out = self.send()
        self.assertTrue(result)
        post.assert_not_called()
        self.assertIn("Alert not sent", out)

    def test_telegram_enabled_sends(self):
        result, post, _ = self.send("hello", TELEGRAM_NOTIFY="YES")
        self.assertTrue(result)
        self.assertEqual(post.call_args[0][1]["text"], "hello")

    def test_slack_webhook_honours_slack_notify(self):
        result, post, _ = self.send("hello", SLACK_NOTIFY="YES",
                                    SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T/B/x")
        self.assertTrue(result)
        self.assertEqual(post.call_args[1]["json"], {"text": "hello"})

    def test_channel_exception_is_contained(self):
        with patch.dict(os.environ, dict(self.ENV, TELEGRAM_NOTIFY="YES")), \
                patch("utility.notification_send.requests.post", side_effect=RuntimeError("x")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(alerts.send_alert("hi"))

    def test_setup_exception_is_contained(self):
        with patch("utility.alerts.NotificationManager", side_effect=RuntimeError("x")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(alerts.send_alert("hi"))

    def test_failure_text_format(self):
        now = datetime.datetime(2026, 8, 10, 9, 5)
        self.assertEqual(alerts.failure_text(None, now, "boom"),
                         "ePortem: run FAILED at 09:05 - boom. Check ePortem by hand; details in the cron mail.")

    def test_secrets_from_env_are_scrubbed(self):
        with patch.dict(os.environ, {"SLACK_TOKEN": "xoxp-secret", "EPORTEM_PASSWORD": "pw-secret"}):
            text = alerts.failure_text("start_day", datetime.datetime(2026, 8, 10, 9, 5),
                                       "failed with xoxp-secret and pw-secret")
        self.assertNotIn("secret", text)


class FakeClock:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return datetime.datetime(2026, 8, 10, 9, 0, self.n)


class TestTimestampedStream(unittest.TestCase):

    def make(self):
        buf = io.StringIO()
        return TimestampedStream(buf, FakeClock()), buf

    def test_single_line(self):
        s, buf = self.make()
        s.write("hello\n")
        self.assertEqual(buf.getvalue(), "09:00:01 hello\n")

    def test_partial_writes_get_one_prefix(self):
        s, buf = self.make()
        s.write("Clicking ")
        s.write("button 1")
        s.write("\n")
        s.write("next\n")
        self.assertEqual(buf.getvalue(), "09:00:01 Clicking button 1\n09:00:02 next\n")

    def test_multi_line_write_prefixes_each_line(self):
        s, buf = self.make()
        s.write("a\nb\n\nc")
        s.write("d\n")
        self.assertEqual(buf.getvalue(), "09:00:01 a\n09:00:02 b\n09:00:03 \n09:00:04 cd\n")

    def test_empty_write_and_print(self):
        s, buf = self.make()
        s.write("")
        print("x", file=s)  # print writes "x" then "\n"
        self.assertEqual(buf.getvalue(), "09:00:01 x\n")

    def test_returns_length_and_delegates(self):
        s, buf = self.make()
        self.assertEqual(s.write("abc\n"), 4)
        s.flush()
        self.assertFalse(s.isatty())

    def test_flush_passes_through(self):
        inner = MagicMock()
        TimestampedStream(inner).flush()
        inner.flush.assert_called_once()

    def test_works_under_redirect_stdout_and_tee(self):
        s, buf = self.make()
        with patch("sys.stdout", s):
            tee = eportem_action._Tee(sys.stdout)
            with contextlib.redirect_stdout(tee):
                print("inside")
            print("after")
        self.assertEqual(tee.copy.getvalue(), "inside\n")  # the http_clock.log copy
        self.assertEqual(buf.getvalue(), "09:00:01 inside\n09:00:02 after\n")

    def test_not_installed_on_import(self):
        self.assertNotIsInstance(sys.stdout, TimestampedStream)
        self.assertNotIsInstance(sys.stderr, TimestampedStream)

    def test_install_wraps_once(self):
        from utility import timestamps
        with patch("sys.stdout", io.StringIO()), patch("sys.stderr", io.StringIO()):
            timestamps.install()
            first = sys.stdout
            timestamps.install()
            self.assertIs(sys.stdout, first)
            self.assertIsInstance(sys.stderr, TimestampedStream)


class TestKillSwitchDirectScripts(IsolatedCase):

    def test_perform_stops_with_zero_when_disabled(self):
        driver = MagicMock()
        out = io.StringIO()
        with patch.dict(os.environ, {"EPORTEM_ENABLED": "NO"}), contextlib.redirect_stdout(out), \
                self.assertRaises(SystemExit) as cm:
            EPortemAction("start_day", "office", driver).perform()
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("ePortem is disabled", out.getvalue())
        driver.get.assert_not_called()

    def test_run_fixed_action_stops_with_zero_when_disabled(self):
        with patch.dict(os.environ, {"EPORTEM_ENABLED": ""}), patch("sys.argv", ["start_day.py"]), \
                patch("eportem_action.execute_action") as execute, \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as cm:
            eportem_action.run_fixed_action("start_day", "d")
        self.assertEqual(cm.exception.code, 0)
        execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
