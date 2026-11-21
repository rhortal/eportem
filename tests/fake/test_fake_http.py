"""The core engine against the fake ePortem over real HTTP (no browser):
several accounts at once, sessions, and every injected fault."""
import threading
import unittest
from unittest.mock import patch

from checkin.core.actions import ClockAction
from checkin.core.activities import ActivityIds
from checkin.core.clock_http import HttpClock, NotRecorded, OutcomeUnknown
from checkin.core.cookies import MemoryCookieStore
from checkin.core.target import Target
from fake_eportem import Account, FakeEportem, Fault
from fake_eportem.testing import RequestsLoginDriver, login_with

ALICE_IDS = ActivityIds(office="7", home="8", lunch_pause="9")
BOB_IDS = ActivityIds(office="1", home="1293", lunch_pause="2")


class Said(list):
    def __call__(self, *args, **kwargs):
        self.append(" ".join(str(a) for a in args))


class FakeCase(unittest.TestCase):
    recaptcha = False
    session_ttl = None

    def setUp(self):
        self.fake = FakeEportem([Account("ALICE", "a-pw", ALICE_IDS), Account("BOB", "b-pw", BOB_IDS)],
                                recaptcha=self.recaptcha, session_ttl=self.session_ttl).start()
        self.addCleanup(self.fake.stop)
        self.target = Target(self.fake.base_url)
        self.stores = {"ALICE": MemoryCookieStore(), "BOB": MemoryCookieStore()}
        p = patch("time.sleep")  # the verify pauses
        p.start()
        self.addCleanup(p.stop)

    def clock(self, user, password=None, ids=None):
        password = password or {"ALICE": "a-pw", "BOB": "b-pw"}[user]
        ids = ids or {"ALICE": ALICE_IDS, "BOB": BOB_IDS}[user]
        return HttpClock(target=self.target, activity_ids=ids, cookie_store=self.stores[user],
                         make_driver=RequestsLoginDriver, login_driver=login_with(user, password), say=Said())

    def action(self, user, action, location):
        said = Said()
        records = []
        act = ClockAction(action, location, activity_ids={"ALICE": ALICE_IDS, "BOB": BOB_IDS}[user],
                          target=self.target, use_http=True, http_clock=lambda: self.clock(user),
                          record=lambda *a: records.append(a), say=said)
        act.perform()
        return records, said

    def events(self, user):
        return [(e["action"], e["codactiv"]) for e in self.fake.events_for(user)]


class TestFullDays(FakeCase):

    def test_a_full_office_day(self):
        for action in ("start_day", "lunch_break", "after_lunch", "stop_day"):
            records, _ = self.action("ALICE", action, "office")
            self.assertEqual(records, [(action, "office", "http")])
        self.assertEqual(self.events("ALICE"),
                         [("_ststart", "7"), ("_stpause", "9"), ("_stini", "7"), ("_ststop", "")])
        self.assertEqual(self.fake.accounts["ALICE"].logins, 1)  # the session was reused

    def test_two_accounts_at_once_each_clocked_exactly_once(self):
        def day(user, location):
            for action in ("start_day", "lunch_break", "after_lunch", "stop_day"):
                self.action(user, action, location)
        threads = [threading.Thread(target=day, args=a) for a in (("ALICE", "home"), ("BOB", "office"))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(self.events("ALICE"),
                         [("_ststart", "8"), ("_stpause", "9"), ("_stini", "8"), ("_ststop", "")])
        self.assertEqual(self.events("BOB"),
                         [("_ststart", "1"), ("_stpause", "2"), ("_stini", "1"), ("_ststop", "")])

    def test_wrong_state_records_nothing(self):
        with self.assertRaises(NotRecorded):
            self.clock("ALICE").clock_and_verify("lunch_break", "office")  # not started yet
        self.assertEqual(self.events("ALICE"), [])


class TestSessions(FakeCase):

    def test_expired_session_logs_in_again(self):
        self.clock("ALICE").clock_and_verify("start_day", "office")
        self.fake.expire_sessions("ALICE")
        said = Said()
        clock = self.clock("ALICE")
        clock.say = said
        clock.clock_and_verify("lunch_break", "office")
        self.assertIn("saved session expired", " ".join(said))
        self.assertEqual(self.fake.accounts["ALICE"].logins, 2)

    def test_wrong_password_is_not_recorded(self):
        with self.assertRaisesRegex(NotRecorded, "LoginRejected"):
            self.clock("ALICE", password="nope").clock_and_verify("start_day", "office")
        self.assertEqual(self.events("ALICE"), [])


class TestRecaptchaBlocksPlainHttpLogin(FakeCase):
    recaptcha = True

    def test_plain_http_login_is_rejected_like_the_real_site(self):
        with self.assertRaisesRegex(NotRecorded, "reCAPTCHA"):
            self.clock("ALICE").clock_and_verify("start_day", "office")


class TestFaults(FakeCase):

    def setUp(self):
        super().setUp()
        self.clock("ALICE").clock_and_verify("start_day", "office")  # now working

    def lunch(self):
        return self.clock("ALICE").clock_and_verify("lunch_break", "office")

    def test_server_error_without_recording_is_not_recorded(self):
        self.fake.add_fault(Fault("clock", "error_500"))
        with self.assertRaises(NotRecorded):
            self.lunch()
        self.assertEqual(len(self.events("ALICE")), 1)

    def test_server_error_after_recording_counts_as_recorded(self):
        self.fake.add_fault(Fault("clock", "error_500", record=True))
        params, response = self.lunch()
        self.assertIsNone(response)  # recorded, seen on the dashboard
        self.assertEqual(self.events("ALICE")[-1], ("_stpause", "9"))

    def test_dropped_connection_without_recording_is_unknown(self):
        """The request reached the server, so it may still be committed: never retry."""
        self.fake.add_fault(Fault("clock", "drop"))
        with self.assertRaises(OutcomeUnknown):
            self.lunch()
        self.assertEqual(len(self.events("ALICE")), 1)

    def test_dropped_connection_after_recording_counts_as_recorded(self):
        self.fake.add_fault(Fault("clock", "drop", record=True))
        params, response = self.lunch()
        self.assertIsNone(response)
        self.assertEqual(len(self.events("ALICE")), 2)

    def test_maintenance_page_is_not_recorded_and_sends_nothing(self):
        self.fake.add_fault(Fault("dashboard", "maintenance"))
        with self.assertRaisesRegex(NotRecorded, "DashboardUnreadable"):
            self.lunch()
        self.assertEqual(len(self.events("ALICE")), 1)

    def test_unreadable_dashboard_after_a_failed_send_is_unknown(self):
        """Can't tell whether it was recorded: never retry."""
        self.fake.add_fault(Fault("clock", "error_500"))
        self.fake.add_fault(Fault("dashboard", "maintenance", skip=1, times=3))  # not the pre-send read
        with self.assertRaises(OutcomeUnknown):
            self.lunch()
        self.assertEqual(len(self.events("ALICE")), 1)

    def test_faults_for_one_account_leave_the_other_alone(self):
        self.fake.add_fault(Fault("clock", "error_500", username="ALICE", times=5))
        self.clock("BOB").clock_and_verify("start_day", "office")
        self.assertEqual(self.events("BOB"), [("_ststart", "1")])


if __name__ == "__main__":
    unittest.main()
