"""The scheduler against the fake ePortem, in simulated time."""
import datetime
import random
import zoneinfo
from unittest.mock import patch

from sqlalchemy import select

from eportem.db.models import DayChangeRow, DayCheck, EportemAccount, PlannedRun, RunLog, User, UserSchedule
from eportem.db.repo import new_user
from eportem.scheduler.runner import Engine
from eportem.scheduler.scheduler import Scheduler
from eportem.settings import load_settings
from fake_eportem import Account, FakeEportem, Fault
from fake_eportem.testing import RequestsLoginDriver, login_with
from tests.service.test_db import KEY, DbCase

MADRID = zoneinfo.ZoneInfo("Europe/Madrid")
DAY = datetime.date(2026, 11, 18)  # a Wednesday


def utc(day, hhmm):
    h, m = map(int, hhmm.split(":"))
    local = datetime.datetime.combine(day, datetime.time(h, m), tzinfo=MADRID)
    return local.astimezone(datetime.UTC).replace(tzinfo=None)


class SchedulerCase(DbCase):
    dry_run = False

    def setUp(self):
        super().setUp()
        self.fake = FakeEportem([Account(f"U{i}", f"pw{i}") for i in range(3)]).start()
        self.addCleanup(self.fake.stop)
        env = {"EPORTEM_SECRET_KEY": KEY, "EPORTEM_TARGET_URL": self.fake.base_url,
               "EPORTEM_DRY_RUN": "true" if self.dry_run else "false"}
        self.settings = load_settings(env)
        self.engine = Engine(self.settings, make_driver=RequestsLoginDriver, login_for=login_with)
        self.alerts = []
        p = patch("eportem.scheduler.scheduler.send_alert",
                  lambda db, box, user_id, text: self.alerts.append((user_id, text)))
        p.start()
        self.addCleanup(p.stop)
        p = patch("time.sleep")
        p.start()
        self.addCleanup(p.stop)

    def person(self, i, template="european-9-18", homes=(), **kw):
        with self.Session.begin() as db:
            user = new_user(self.settings, f"user{i}", **kw)
            db.add(user)
            db.flush()
            db.add(EportemAccount(user_id=user.id, username=f"U{i}", password_enc=self.box.encrypt(f"pw{i}"),
                                  office_activity_id="1", home_activity_id="1293", lunch_pause_id="2"))
            db.add(UserSchedule(user_id=user.id, template_key=template,
                                location_weeks=[{str(d): "home" for d in homes}]))
            return user.id

    def scheduler(self, **kw):
        return Scheduler(self.settings, self.Session, self.box, self.engine, rng=random.Random(7), **kw)

    def runs(self, user_id, day=DAY):
        with self.Session() as db:
            return {r.action: r for r in db.scalars(select(PlannedRun).where(
                PlannedRun.user_id == user_id, PlannedRun.date == day))}

    def events(self, i):
        return [(e["action"], e["codactiv"]) for e in self.fake.events_for(f"U{i}")]

    def run_day(self, sched, day=DAY, start="07:00", end="19:30", step=5):
        t, stop = utc(day, start), utc(day, end)
        while t <= stop:
            sched.tick(t)
            t += datetime.timedelta(minutes=step)


class TestADay(SchedulerCase):

    def test_two_people_full_day(self):
        alice = self.person(0, homes=(2,))                       # Wednesday at home
        bob = self.person(1, template="spanish-9-18")
        self.run_day(self.scheduler())
        self.assertEqual(self.events(0), [("_ststart", "1293"), ("_stpause", "2"), ("_stini", "1293"), ("_ststop", "")])
        self.assertEqual(self.events(1), [("_ststart", "1"), ("_stpause", "2"), ("_stini", "1"), ("_ststop", "")])
        for uid in (alice, bob):
            self.assertEqual({r.status for r in self.runs(uid).values()}, {"recorded"})
            self.assertEqual({r.via for r in self.runs(uid).values()}, {"http"})
        with self.Session() as db:
            self.assertEqual(db.query(DayCheck).filter_by(ok=True).count(), 2)
            log = db.get(RunLog, self.runs(alice)["start_day"].id)
            self.assertEqual(log.outcome, "recorded over HTTP")
            self.assertIn("HTTP clock action recorded", log.text)
        self.assertEqual(self.alerts, [])

    def test_each_run_starts_inside_its_own_offset(self):
        uid = self.person(0, jitter_before_minutes=2, jitter_after_minutes=1)
        sched = self.scheduler()
        sched.tick(utc(DAY, "06:00"))
        for run in self.runs(uid).values():
            target = utc(DAY, "00:00") + datetime.timedelta(minutes=run.target_minute)
            self.assertGreaterEqual(run.planned_at, target - datetime.timedelta(minutes=2))
            self.assertLessEqual(run.planned_at, target + datetime.timedelta(minutes=1))

    def test_weekend_and_paused_plan_nothing(self):
        uid = self.person(0)
        paused = self.person(1, paused=True)
        self.run_day(self.scheduler(), day=datetime.date(2026, 11, 21))
        self.assertEqual(self.runs(uid, datetime.date(2026, 11, 21)), {})
        self.run_day(self.scheduler())
        self.assertEqual(self.runs(paused), {})
        self.assertEqual(self.events(1), [])


class TestNeverTwiceNeverLate(SchedulerCase):

    def test_a_second_scheduler_waits_for_the_lock(self):
        self.person(0)
        a, b = self.scheduler(holder="a"), self.scheduler(holder="b")
        a.tick(utc(DAY, "08:00"))
        a.tick(utc(DAY, "09:09"))                               # a's lock is fresh
        self.assertEqual(b.tick(utc(DAY, "09:10")), [])
        a.tick(utc(DAY, "09:10"))
        self.assertEqual(len(self.events(0)), 1)
        # a stops; after the lock goes stale b takes over and nothing is redone
        b.tick(utc(DAY, "13:40"))
        self.assertEqual(self.events(0), [("_ststart", "1"), ("_stpause", "2")])

    def test_a_run_is_claimed_once(self):
        uid = self.person(0)
        sched = self.scheduler()
        sched.tick(utc(DAY, "06:00"))
        run = self.runs(uid)["start_day"]
        now = utc(DAY, "09:00")
        self.assertTrue(sched._claim(run.id, uid, now))
        self.assertFalse(sched._claim(run.id, uid, now))

    def test_a_person_created_after_the_window_gets_no_alert(self):
        uid = self.person(0)
        with self.Session.begin() as db:
            db.get(User, uid).created_at = utc(DAY, "09:45")
        self.scheduler().tick(utc(DAY, "10:00"))
        self.assertEqual(self.runs(uid)["start_day"].status, "skipped")
        self.assertEqual(self.alerts, [])

    def test_started_after_the_window_skips_and_alerts(self):
        uid = self.person(0)
        with self.Session.begin() as db:
            db.get(User, uid).created_at = utc(DAY, "06:00")
        self.scheduler().tick(utc(DAY, "10:00"))                  # was down at 09:00
        self.assertEqual(self.runs(uid)["start_day"].status, "skipped")
        self.assertEqual(self.events(0), [])
        self.assertIn("start_day", self.alerts[0][1])

    def test_a_run_the_import_recorded_is_not_redone(self):
        uid = self.person(0)
        with self.Session.begin() as db:
            db.add(PlannedRun(user_id=uid, date=DAY, action="start_day", target_minute=540, location="office",
                              planned_at=utc(DAY, "08:57"), status="recorded", via="legacy-http"))
        self.fake.accounts["U0"].state = "working"
        self.run_day(self.scheduler(), start="10:00")
        self.assertEqual([a for a, _ in self.events(0)], ["_stpause", "_stini", "_ststop"])
        self.assertEqual(self.alerts, [])

    def test_crash_while_running_becomes_unknown(self):
        uid = self.person(0)
        sched = self.scheduler()
        sched.tick(utc(DAY, "06:00"))
        with self.Session.begin() as db:
            run = db.get(PlannedRun, self.runs(uid)["start_day"].id)
            run.status = "running"
        self.scheduler().tick(utc(DAY, "09:20"))                  # a new process
        self.assertEqual(self.runs(uid)["start_day"].status, "unknown")
        self.assertIn("may or may not", self.alerts[0][1])
        self.assertEqual(self.events(0), [])

    def test_outcome_unknown_is_not_retried(self):
        uid = self.person(0)
        self.fake.add_fault(Fault("clock", "drop"))
        self.run_day(self.scheduler(), end="10:00")
        self.assertEqual(self.runs(uid)["start_day"].status, "unknown")
        self.assertEqual(self.events(0), [])
        self.assertTrue(any("may or may not" in a for _, a in self.alerts))


class TestChanges(SchedulerCase):

    def test_a_day_change_replans_only_what_has_not_run(self):
        uid = self.person(0)
        sched = self.scheduler()
        self.run_day(sched, end="10:00")
        with self.Session.begin() as db:
            db.add(DayChangeRow(user_id=uid, kind="location", start_date=DAY, end_date=DAY, location="home"))
        sched.replan(uid, utc(DAY, "10:05"))
        runs = self.runs(uid)
        self.assertEqual((runs["start_day"].location, runs["start_day"].status), ("office", "recorded"))
        self.assertEqual(runs["after_lunch"].location, "home")
        self.run_day(sched, start="10:10")
        self.assertEqual(self.events(0)[2], ("_stini", "1293"))

    def test_time_off_added_today_cancels_what_is_left(self):
        uid = self.person(0)
        sched = self.scheduler()
        self.run_day(sched, end="10:00")
        with self.Session.begin() as db:
            db.add(DayChangeRow(user_id=uid, kind="time_off", start_date=DAY, end_date=DAY))
        sched.replan(uid, utc(DAY, "10:05"))
        statuses = {a: r.status for a, r in self.runs(uid).items()}
        self.assertEqual(statuses, {"start_day": "recorded", "lunch_break": "cancelled",
                                    "after_lunch": "cancelled", "stop_day": "cancelled"})
        self.run_day(sched, start="10:10")
        self.assertEqual(len(self.events(0)), 1)

    def test_account_without_activity_ids_is_not_recorded_and_alerts(self):
        uid = self.person(0)
        with self.Session.begin() as db:
            db.get(EportemAccount, uid).lunch_pause_id = None
        self.run_day(self.scheduler(), end="09:30")
        self.assertEqual(self.runs(uid)["start_day"].status, "not_recorded")
        self.assertIn("activity IDs", self.alerts[0][1])


class TestDryRun(SchedulerCase):
    dry_run = True

    def test_plans_and_logs_but_never_sends(self):
        uid = self.person(0)
        self.run_day(self.scheduler())
        self.assertEqual({r.status for r in self.runs(uid).values()}, {"dry_run"})
        self.assertEqual(self.fake.events, [])
        self.assertNotIn("/aplicaciones/e-portem/registro/reghorario.cshtml", self.fake.paths)
        with self.Session() as db:
            self.assertTrue(db.scalar(select(DayCheck.ok)))


class TestAWeekForManyPeople(SchedulerCase):

    def setUp(self):
        super().setUp()
        self.fake.stop()
        self.fake = FakeEportem([Account(f"U{i}", f"pw{i}") for i in range(30)]).start()
        self.settings = load_settings({"EPORTEM_SECRET_KEY": KEY, "EPORTEM_TARGET_URL": self.fake.base_url})
        self.engine = Engine(self.settings, make_driver=RequestsLoginDriver, login_for=login_with)

    def test_thirty_people_mixed_templates_one_week(self):
        templates = ("european-9-18", "spanish-9-18", "spanish-friday-short", "summer-8-15", "part-time-morning")
        ids = [self.person(i, template=templates[i % 5], homes=(i % 5,)) for i in range(30)]
        sched = self.scheduler()
        monday = datetime.date(2026, 11, 16)
        for d in range(7):
            self.run_day(sched, day=monday + datetime.timedelta(days=d), start="06:30", end="20:00", step=10)
        with self.Session() as db:
            runs = db.scalars(select(PlannedRun)).all()
            self.assertEqual({r.status for r in runs}, {"recorded"})
            per_day = {}
            for r in runs:
                per_day.setdefault((r.user_id, r.date), []).append(r.action)
            self.assertTrue(all(len(v) == len(set(v)) for v in per_day.values()))
            self.assertEqual(db.query(DayCheck).filter_by(ok=False).count(), 0)
            self.assertEqual(db.scalar(select(User).where(User.id == ids[0])).username, "user0")
        total = sum(len(self.fake.events_for(f"U{i}")) for i in range(30))
        self.assertEqual(total, len(runs))
        self.assertEqual(self.alerts, [])
