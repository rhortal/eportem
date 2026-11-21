"""checkin.legacy_import on a made-up cron checkout."""
import contextlib
import datetime
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select

from checkin import cli
from checkin.core.calendar import resolve
from checkin.db.models import (
    DayChangeRow,
    EportemAccount,
    EportemSession,
    NotificationChannelRow,
    PlannedRun,
    ScheduleTemplate,
    User,
    UserSchedule,
)
from checkin.db.repo import load_calendar
from checkin.legacy_import import ImportError_, import_legacy
from tests.service.test_db import KEY, SETTINGS, DbCase

TODAY = datetime.date(2026, 11, 18)  # a Wednesday
WEEK = {str(d): {"day": n, "location": "home" if d == 2 else "office", "start_the_day": "9:00",
                 "lunch_break": "13:30", "after_lunch_break": "14:30", "stop_the_day": "18:00"}
        for d, n in enumerate(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"))}
ENV = """EPORTEM_USERNAME=SOMEONE
EPORTEM_PASSWORD=pw-secret
EPORTEM_ENABLED=YES
EPORTEM_HTTP=YES
TELEGRAM_NOTIFY=YES
TELEGRAM_BOT_TOKEN=tg-secret
TELEGRAM_CHAT_ID=42
SLACK_NOTIFY=YES
SLACK_STATUS=YES
SLACK_BOT_TOKEN=xoxb-bot-secret
SLACK_TOKEN=xoxp-user-secret
"""


class ImportCase(DbCase):

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.src = Path(tmp.name)
        (self.src / "config").mkdir()
        (self.src / "logs").mkdir()
        (self.src / "config" / ".env").write_text(ENV)
        (self.src / "config" / "config.json").write_text(json.dumps({"schedule": WEEK}))
        (self.src / "holiday_override.txt").write_text("2026-12-22,2027-01-02")
        (self.src / "business_trip_override.txt").write_text("2026-11-01,2026-11-05")  # past: ignored
        (self.src / "location_override.txt").write_text("office,2026-11-18")
        (self.src / "config" / ".session_cookies.json").write_text(json.dumps(
            {"logged_in_at": "2026-11-18T08:57:00", "last_used_at": None,
             "cookies": [{"name": ".ASPXAUTH", "value": "ticket", "domain": "eportem.es", "path": "/"}]}))
        (self.src / "logs" / "actions.log.1").write_text(
            "2026-11-17T08:57:17 2026-11-17 start_day office http\n")
        (self.src / "logs" / "actions.log").write_text(
            "2026-11-18T08:58:01 2026-11-18 start_day home http\n"
            "not a line\n"
            "2026-11-18T13:27:44 2026-11-18 lunch_break home http\n")

    def run_import(self, **kw):
        with self.Session() as db:
            report = import_legacy(db, SETTINGS, self.box, self.src, "roberto", email="r@example.com",
                                   today=TODAY, **kw)
            db.commit()
        return "\n".join(report.lines)


class TestImport(ImportCase):

    def test_everything_arrives(self):
        text = self.run_import()
        with self.Session() as db:
            user = db.scalar(select(User))
            self.assertEqual((user.username, user.role, user.paused), ("roberto", "admin", False))
            account = db.get(EportemAccount, user.id)
            self.assertEqual((account.username, account.use_http), ("SOMEONE", True))
            self.assertEqual(self.box.decrypt(account.password_enc), "pw-secret")
            self.assertEqual((account.office_activity_id, account.home_activity_id, account.lunch_pause_id),
                             ("1", "1293", "2"))
            sched = db.get(UserSchedule, user.id)
            self.assertEqual(sched.template_key, "european-9-18")  # matched the built-in exactly
            self.assertEqual(db.scalar(select(ScheduleTemplate)), None)
            changes = {(c.kind, c.start_date, c.location) for c in db.scalars(select(DayChangeRow))}
            self.assertEqual(changes, {("time_off", datetime.date(2026, 12, 22), None),
                                       ("location", TODAY, "office")})
            channels = {c.kind: c for c in db.scalars(select(NotificationChannelRow))}
            self.assertEqual(self.box.decrypt_json(channels["telegram"].config_enc)["chat_id"], "42")
            slack = self.box.decrypt_json(channels["slack"].config_enc)
            self.assertEqual((slack["bot_token"], slack["user_token"]), ("xoxb-bot-secret", "xoxp-user-secret"))
            self.assertTrue(channels["slack"].slack_status)
            self.assertEqual(self.box.decrypt_json(db.get(EportemSession, user.id).data_enc)["cookies"][0]["value"],
                             "ticket")
            runs = sorted((r.date, r.action, r.status, r.via, r.target_minute) for r in db.scalars(select(PlannedRun)))
            self.assertEqual(runs, [
                (datetime.date(2026, 11, 17), "start_day", "recorded", "legacy-http", 540),
                (TODAY, "lunch_break", "recorded", "legacy-http", 810),
                (TODAY, "start_day", "recorded", "legacy-http", 540)])
            cal = load_calendar(db, user)
        self.assertEqual(resolve(cal, TODAY).location, "office")              # the override
        self.assertEqual(resolve(cal, datetime.date(2026, 11, 25)).location, "home")  # the pattern
        self.assertFalse(resolve(cal, datetime.date(2026, 12, 23)).works)    # imported time off
        for secret in ("pw-secret", "tg-secret", "xoxb-bot-secret", "xoxp-user-secret", "ticket"):
            self.assertNotIn(secret, text)

    def test_running_it_again_adds_no_duplicates(self):
        self.run_import()
        text = self.run_import()
        self.assertIn("user roberto exists", text)
        self.assertIn("already imported", text)
        with self.Session() as db:
            self.assertEqual(db.query(User).count(), 1)
            self.assertEqual(db.query(DayChangeRow).count(), 2)
            self.assertEqual(db.query(NotificationChannelRow).count(), 2)
            self.assertEqual(db.query(PlannedRun).count(), 3)

    def test_cron_wins_over_runs_the_service_never_sent(self):
        self.run_import()
        with self.Session.begin() as db:
            for run in db.scalars(select(PlannedRun).where(PlannedRun.date == TODAY)):
                run.status, run.via = ("skipped", None) if run.action == "start_day" else ("recorded", "http")
        self.run_import()
        with self.Session() as db:
            runs = {r.action: r for r in db.scalars(select(PlannedRun).where(PlannedRun.date == TODAY))}
        self.assertEqual((runs["start_day"].status, runs["start_day"].via), ("recorded", "legacy-http"))
        self.assertEqual(runs["lunch_break"].via, "http")  # a run the service sent is left alone

    def test_disabled_host_imports_as_paused_and_http_flag_is_kept(self):
        (self.src / "config" / ".env").write_text(ENV.replace("EPORTEM_ENABLED=YES", "EPORTEM_ENABLED=NO")
                                                  .replace("EPORTEM_HTTP=YES", "EPORTEM_HTTP=NO"))
        self.run_import()
        with self.Session() as db:
            user = db.scalar(select(User))
            self.assertTrue(user.paused)
            self.assertFalse(db.get(EportemAccount, user.id).use_http)

    def test_own_times_become_a_custom_template(self):
        week = json.loads(json.dumps(WEEK))
        week["4"] = {"start_the_day": "8:00", "stop_the_day": "15:00"}
        (self.src / "config" / "config.json").write_text(json.dumps({"schedule": week}))
        self.run_import()
        with self.Session() as db:
            row = db.scalar(select(ScheduleTemplate))
            self.assertEqual(row.key, "imported")
            self.assertEqual(row.days["4"], {"start": "08:00", "stop": "15:00"})
            self.assertEqual(db.scalar(select(UserSchedule)).template_key, "imported")

    def test_bad_files_import_nothing(self):
        (self.src / "config" / "config.json").write_text(json.dumps({"schedule": {"0": {"lunch_break": "25:00"}}}))
        with self.assertRaises(ImportError_) as cm:
            self.run_import()
        self.assertIn("must be a time", " ".join(cm.exception.problems))
        (self.src / "config" / "config.json").write_text(json.dumps({"schedule": {"0": {"lunch_break": "13:00"}}}))
        with self.assertRaisesRegex(ImportError_, "needs start_the_day and stop_the_day"):
            self.run_import()
        with self.Session() as db:
            self.assertEqual(db.query(User).count(), 0)


class TestCommand(ImportCase):

    def cli(self, *args):
        env = {"CHECKIN_SECRET_KEY": KEY, "CHECKIN_DATABASE_URL": self.url}
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_dry_run_saves_nothing_then_real_run_does(self):
        code, out, _ = self.cli("import-legacy", "--user", "roberto", "--from", str(self.src), "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("Dry run: nothing was saved.", out)
        with self.Session() as db:
            self.assertEqual(db.query(User).count(), 0)
        code, out, _ = self.cli("import-legacy", "--user", "roberto", "--from", str(self.src))
        self.assertEqual(code, 0)
        self.assertIn("Imported.", out)
        self.assertNotIn("pw-secret", out)

    def test_problems_exit_2(self):
        (self.src / "config" / "config.json").write_text("{")
        code, _, err = self.cli("import-legacy", "--user", "roberto", "--from", str(self.src))
        self.assertEqual(code, 2)
        self.assertIn("Nothing imported", err)

    def test_migrate_command(self):
        self.assertEqual(self.cli("migrate")[0], 0)

    def test_scheduler_command_starts_the_loop(self):
        with patch("checkin.scheduler.scheduler.Scheduler.run_forever") as loop:
            code, out, _ = self.cli("scheduler")
        self.assertEqual(code, 0)
        loop.assert_called_once()
        self.assertIn("Scheduler running against https://eportem.es", out)


if __name__ == "__main__":
    unittest.main()
