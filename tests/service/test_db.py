"""The database layer: migrations, encryption, the session store and the
calendar built from rows."""
import datetime
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from checkin.core.calendar import resolve
from checkin.core.clock_http import HttpClock
from checkin.core.target import Target
from checkin.db.crypto import SecretBox
from checkin.db.engine import downgrade, make_engine, make_sessionmaker, migrate
from checkin.db.models import (
    DayChangeRow,
    EportemAccount,
    EportemSession,
    LocalHoliday,
    PlannedRun,
    SchedulePeriod,
    ScheduleTemplate,
    UserSchedule,
)
from checkin.db.repo import DbCookieStore, activity_ids, load_calendar, new_user
from checkin.settings import load_settings
from fake_eportem import Account, FakeEportem
from fake_eportem.testing import RequestsLoginDriver, login_with

KEY = Fernet.generate_key().decode()
SETTINGS = load_settings({"CHECKIN_SECRET_KEY": KEY, "CHECKIN_DEFAULT_JITTER_BEFORE_MINUTES": "3"})
D = datetime.date


class DbCase(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.url = f"sqlite:///{Path(tmp.name) / 'data' / 'checkin.db'}"
        migrate(self.url)
        self.engine = make_engine(self.url)
        self.addCleanup(self.engine.dispose)
        self.Session = make_sessionmaker(self.engine)
        self.box = SecretBox(KEY)

    def user(self, db, name="alice", **kw):
        u = new_user(SETTINGS, name, **kw)
        db.add(u)
        db.flush()
        return u


class TestMigrations(DbCase):

    def test_round_trip(self):
        tables = set(inspect(self.engine).get_table_names())
        self.assertIn("planned_runs", tables)
        downgrade(self.url, "base")
        for expected in ({"alembic_version"}, tables):
            engine = make_engine(self.url)
            self.assertEqual(set(inspect(engine).get_table_names()), expected)
            engine.dispose()
            if expected != tables:
                migrate(self.url)

    def test_sqlite_runs_in_wal_mode_with_foreign_keys(self):
        with self.engine.connect() as c:
            self.assertEqual(c.exec_driver_sql("PRAGMA journal_mode").scalar(), "wal")
            self.assertEqual(c.exec_driver_sql("PRAGMA foreign_keys").scalar(), 1)


class TestUsersAndRuns(DbCase):

    def test_new_users_get_the_instance_defaults(self):
        with self.Session() as db:
            u = self.user(db)
            self.assertEqual((u.timezone, u.locale, u.jitter_before_minutes, u.jitter_after_minutes),
                             ("Europe/Madrid", "es", 3, 4))
            u2 = self.user(db, "bob", jitter_after_minutes=10)
            self.assertEqual(u2.jitter_after_minutes, 10)

    def test_one_run_per_person_date_and_action(self):
        with self.Session() as db:
            u = self.user(db)
            row = dict(user_id=u.id, date=D(2026, 11, 18), action="start_day", target_minute=540,
                       planned_at=datetime.datetime(2026, 11, 18, 7, 57), location="office")
            db.add(PlannedRun(**row))
            db.flush()
            db.add(PlannedRun(**row))
            with self.assertRaises(IntegrityError):
                db.flush()

    def test_deleting_a_person_deletes_their_data(self):
        with self.Session.begin() as db:
            u = self.user(db)
            db.add(EportemAccount(user_id=u.id, username="X", password_enc=self.box.encrypt("pw")))
            db.add(DayChangeRow(user_id=u.id, kind="time_off", start_date=D(2026, 1, 1), end_date=D(2026, 1, 1)))
        with self.Session.begin() as db:
            db.delete(db.get(type(u), u.id))
        with self.Session() as db:
            self.assertIsNone(db.get(EportemAccount, u.id))
            self.assertEqual(db.query(DayChangeRow).count(), 0)

    def test_activity_ids_need_all_three(self):
        self.assertIsNone(activity_ids(EportemAccount(office_activity_id="1", home_activity_id="2")))
        ids = activity_ids(EportemAccount(office_activity_id="1", home_activity_id="2", lunch_pause_id="3"))
        self.assertEqual(ids.work("home"), "2")


class TestCrypto(unittest.TestCase):

    def test_round_trip_and_wrong_key(self):
        box = SecretBox(KEY)
        token = box.encrypt("s3cret")
        self.assertNotIn("s3cret", token)
        self.assertEqual(box.decrypt(token), "s3cret")
        self.assertEqual(box.decrypt_json(box.encrypt_json({"a": [1]})), {"a": [1]})
        with self.assertRaisesRegex(ValueError, "wrong CHECKIN_SECRET_KEY"):
            SecretBox(Fernet.generate_key().decode()).decrypt(token)

    def test_rotation(self):
        old = SecretBox(KEY).encrypt("pw")
        new_key = Fernet.generate_key().decode()
        rotating = SecretBox(new_key, [KEY])
        self.assertEqual(rotating.decrypt(old), "pw")
        self.assertEqual(SecretBox(new_key).decrypt(rotating.rotate(old)), "pw")


class TestDbCookieStore(DbCase):

    def test_the_http_clock_keeps_its_session_in_the_database_encrypted(self):
        with self.Session.begin() as db:
            uid = self.user(db).id
        store = DbCookieStore(self.Session, uid, self.box)
        self.assertIsNone(store.load())
        with FakeEportem([Account("ALICE", "pw")]) as fake:
            def clock():
                return HttpClock(target=Target(fake.base_url), activity_ids=activity_ids(EportemAccount(
                    office_activity_id="1", home_activity_id="1293", lunch_pause_id="2")), cookie_store=store,
                    make_driver=RequestsLoginDriver, login_driver=login_with("ALICE", "pw"), say=lambda *a: None)
            clock().clock_and_verify("start_day", "office")
            clock().clock_and_verify("lunch_break", "office")
            self.assertEqual(fake.accounts["ALICE"].logins, 1)  # the second run reused the stored session
        with self.Session() as db:
            raw = db.get(EportemSession, uid).data_enc
        self.assertNotIn(".ASPXAUTH", raw)
        self.assertEqual(store.load()["cookies"][0]["name"], ".ASPXAUTH")


class TestLoadCalendar(DbCase):

    def test_rows_become_a_calendar(self):
        mon = D(2026, 11, 16)
        with self.Session.begin() as db:
            u = self.user(db)
            db.add(ScheduleTemplate(user_id=u.id, key="mine", name="Mine",
                                    days={"0": {"start": "8:00", "stop": "16:00"},
                                          "2": {"start": "8:00", "stop": "16:00"}}))
            db.add(UserSchedule(user_id=u.id, template_key="mine", location_weeks=[{"2": "home"}],
                                holiday_country="ES", holiday_region="MD"))
            db.add(SchedulePeriod(user_id=u.id, template_key="summer-8-15", start_date=D(2000, 7, 1),
                                  end_date=D(2000, 8, 31), yearly=True))
            db.add(DayChangeRow(user_id=u.id, kind="location", start_date=mon, end_date=mon, location="home"))
            db.add(DayChangeRow(user_id=u.id, kind="times", start_date=D(2026, 11, 20), end_date=D(2026, 11, 20),
                                times={"start": "10:00", "stop": "12:00"}))
            db.add(LocalHoliday(user_id=u.id, date=D(2026, 11, 18), name="Fiesta local"))
            uid = u.id
        with self.Session() as db:
            cal = load_calendar(db, db.get(type(u), uid))
        self.assertEqual((resolve(cal, mon).times.start, resolve(cal, mon).location), (480, "home"))
        self.assertFalse(resolve(cal, D(2026, 11, 17)).works)                     # not in "mine"
        self.assertEqual(resolve(cal, D(2026, 11, 18)).reason, "public holiday: Fiesta local")
        self.assertEqual(resolve(cal, D(2026, 11, 20)).times.stop, 720)            # a Friday, by change
        self.assertEqual(resolve(cal, D(2027, 7, 7)).template_key, "summer-8-15")  # yearly period
        self.assertIn("Madrid", resolve(cal, D(2027, 5, 3)).reason)                # regional holiday

    def test_a_paused_or_suspended_person_never_works(self):
        with self.Session.begin() as db:
            paused = self.user(db, "p", paused=True)
            suspended = self.user(db, "s", status="suspended")
            ids = paused.id, suspended.id
        with self.Session() as db:
            for uid in ids:
                self.assertFalse(resolve(load_calendar(db, db.get(type(paused), uid)), D(2026, 11, 16)).works)


if __name__ == "__main__":
    unittest.main()
