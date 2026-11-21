"""The JSON API with FastAPI's test client, against the fake ePortem."""
import datetime
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from checkin import auth, service
from checkin.db.models import ApiToken, AuditEvent, EportemAccount, PlannedRun, User
from checkin.scheduler.scheduler import Scheduler
from checkin.settings import load_settings
from checkin.web.app import create_app
from tests.service.test_db import KEY
from tests.service.test_scheduler import SchedulerCase


class ApiCase(SchedulerCase):

    def setUp(self):
        super().setUp()
        self.settings = load_settings({"CHECKIN_SECRET_KEY": KEY, "CHECKIN_TARGET_URL": self.fake.base_url,
                                       "CHECKIN_ADMIN_USERNAME": "boss", "CHECKIN_ADMIN_PASSWORD": "boss-password-1"})
        self.sched = Scheduler(self.settings, self.Session, self.box, self.engine)
        self.app = create_app(self.settings, self.Session, self.engine, self.sched)
        self.client = TestClient(self.app)
        self.alice, self.alice_token = self.make_user("alice", 0)
        self.bob, self.bob_token = self.make_user("bob", 1)
        with self.Session.begin() as db:
            boss = db.scalar(select(User).where(User.username == "boss"))
            _, self.admin_token = auth.create_token(db, boss, "t", ["admin"])

    def make_user(self, name, i, scopes=("read", "write")):
        with self.Session.begin() as db:
            user = service.create_user(db, self.settings, "test", name, f"{name}-password-1")
            _, token = auth.create_token(db, user, "t", list(scopes))
            return user.id, token

    def call(self, method, path, token=None, **kw):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.request(method, f"/api/v1{path}", headers=headers, **kw)


class TestAuth(ApiCase):

    def test_no_token_bad_token_and_good_token(self):
        self.assertEqual(self.call("GET", "/me").status_code, 401)
        self.assertEqual(self.call("GET", "/me", "ept_nope_x").status_code, 401)
        self.assertEqual(self.call("GET", "/me", self.alice_token[:-1] + "x").status_code, 401)
        r = self.call("GET", "/me", self.alice_token)
        self.assertEqual((r.status_code, r.json()["username"]), (200, "alice"))
        self.assertNotIn("password_hash", r.json())

    def test_too_many_bad_tokens_are_refused_for_a_while(self):
        for _ in range(30):
            self.call("GET", "/me", "ept_aaaa_bad")
        self.assertEqual(self.call("GET", "/me", "ept_aaaa_bad").status_code, 429)

    def test_read_scope_cannot_write_and_users_cannot_admin(self):
        _, read_only = self.make_user("carol", 2, scopes=("read",))
        self.assertEqual(self.call("GET", "/me", read_only).status_code, 200)
        self.assertEqual(self.call("PATCH", "/me", read_only, json={"paused": True}).status_code, 403)
        self.assertEqual(self.call("GET", "/admin/users", self.alice_token).status_code, 403)
        self.assertEqual(self.call("POST", "/tokens", self.alice_token,
                                   json={"name": "x", "scopes": ["admin"]}).status_code, 403)

    def test_tokens_create_list_revoke(self):
        r = self.call("POST", "/tokens", self.alice_token, json={"name": "script", "scopes": ["read"],
                                                                  "expires_in_days": 30})
        self.assertEqual(r.status_code, 201)
        new = r.json()["token"]
        self.assertEqual(self.call("GET", "/me", new).status_code, 200)
        listed = self.call("GET", "/tokens", self.alice_token).json()
        self.assertTrue(all("token" not in t for t in listed))
        self.assertEqual(self.call("DELETE", f"/tokens/{r.json()['id']}", self.alice_token).status_code, 204)
        self.assertEqual(self.call("GET", "/me", new).status_code, 401)
        with self.Session() as db:
            self.assertNotIn(new, [t.token_hash for t in db.scalars(select(ApiToken))])

    def test_expired_token_and_suspended_user(self):
        with self.Session.begin() as db:
            row = db.scalar(select(ApiToken).where(ApiToken.user_id == self.alice))
            row.expires_at = datetime.datetime(2020, 1, 1)
        self.assertEqual(self.call("GET", "/me", self.alice_token).status_code, 401)
        self.call("PATCH", f"/admin/users/{self.bob}", self.admin_token, json={"status": "suspended"})
        self.assertEqual(self.call("GET", "/me", self.bob_token).status_code, 401)

    def test_first_admin_comes_from_the_settings_once(self):
        with self.Session() as db:
            self.assertEqual(db.query(User).filter_by(role="admin").count(), 1)
        create_app(self.settings, self.Session, self.engine, self.sched)  # a restart
        with self.Session() as db:
            self.assertEqual(db.query(User).filter_by(role="admin").count(), 1)

    def test_passwords(self):
        self.assertEqual(self.call("PUT", "/me/password", self.alice_token,
                                   json={"current": "wrong", "new": "a-new-password"}).status_code, 403)
        self.assertEqual(self.call("PUT", "/me/password", self.alice_token,
                                   json={"current": "alice-password-1", "new": "short"}).status_code, 422)
        self.assertEqual(self.call("PUT", "/me/password", self.alice_token,
                                   json={"current": "alice-password-1", "new": "a-new-password"}).status_code, 204)
        with self.Session() as db:
            self.assertIsNotNone(auth.check_password(db, "alice", "a-new-password"))
            self.assertIsNone(auth.check_password(db, "alice", "alice-password-1"))
            self.assertIsNone(auth.check_password(db, "nobody", "a-new-password"))


class TestIsolation(ApiCase):
    """Nobody can see or change another person's data."""

    def test_rows_of_another_person_are_not_found(self):
        ch = self.call("POST", "/channels", self.alice_token, json={
            "kind": "telegram", "config": {"token": "tg-alice", "chat_id": "1"}}).json()
        day = self.call("POST", "/days", self.alice_token, json={"kind": "time_off", "start_date": "2026-12-24"}).json()
        self.call("PUT", "/templates/mine", self.alice_token, json={"name": "Mine", "days": {
            "0": {"start": "8:00", "stop": "15:00"}}})
        with self.Session.begin() as db:
            run = PlannedRun(user_id=self.alice, date=datetime.date(2026, 10, 1), action="start_day",
                             target_minute=540, planned_at=datetime.datetime(2026, 10, 1, 8), location="office")
            db.add(run)
            db.flush()
            run_id = run.id
        for method, path in (("PATCH", f"/channels/{ch['id']}"), ("DELETE", f"/channels/{ch['id']}"),
                             ("POST", f"/channels/{ch['id']}/test"), ("DELETE", f"/days/{day['id']}"),
                             ("GET", f"/runs/{run_id}/log"), ("DELETE", "/templates/mine")):
            with self.subTest(path=path):
                r = self.call(method, path, self.bob_token, json={})
                self.assertEqual(r.status_code, 404, r.text)
        self.assertEqual(self.call("GET", "/channels", self.bob_token).json(), [])
        self.assertEqual(self.call("GET", "/days", self.bob_token).json(), [])
        self.assertEqual(self.call("GET", "/runs?from=2026-09-01&to=2026-11-30", self.bob_token).json(), [])
        self.assertNotIn("mine", [t["key"] for t in self.call("GET", "/templates", self.bob_token).json()])


class TestProfileAndSchedule(ApiCase):

    def test_offset_is_checked_against_the_window(self):
        r = self.call("PATCH", "/me", self.alice_token, json={"jitter_after_minutes": 20})
        self.assertEqual(r.status_code, 422)
        self.assertIn("15-minute window", r.json()["detail"][0])
        r = self.call("PATCH", "/me", self.alice_token, json={"jitter_before_minutes": 10, "jitter_after_minutes": 2,
                                                              "timezone": "Europe/Lisbon"})
        self.assertEqual((r.json()["jitter_before_minutes"], r.json()["timezone"]), (10, "Europe/Lisbon"))

    def test_schedule_templates_and_calendar(self):
        r = self.call("PUT", "/schedule", self.alice_token, json={
            "template_key": "spanish-9-18", "location_weeks": [{"2": "home"}], "holiday_region": "MD"})
        self.assertEqual(r.status_code, 200, r.text)
        days = self.call("GET", "/calendar?from=2026-11-16&days=7", self.alice_token).json()
        self.assertEqual([d["works"] for d in days], [True] * 5 + [False] * 2)
        self.assertEqual(days[2]["location"], "home")
        self.assertEqual(days[0]["actions"][1], {"action": "lunch_break", "time": "14:30"})
        bad = self.call("PUT", "/schedule", self.alice_token, json={"template_key": "nope",
                                                                     "location_weeks": [{"9": "moon"}]})
        self.assertEqual(len(bad.json()["detail"]), 2)
        self.assertEqual(self.call("PUT", "/templates/european-9-18", self.alice_token,
                                   json={"name": "x", "days": {}}).status_code, 422)

    def test_day_changes_periods_and_local_holidays(self):
        self.assertEqual(self.call("POST", "/days", self.alice_token, json={
            "kind": "times", "start_date": "2026-11-20", "times": {"start": "10:00", "stop": "9:00"}}).status_code, 422)
        self.call("POST", "/days", self.alice_token, json={"kind": "location", "start_date": "2026-11-16",
                                                           "location": "home"})
        self.call("POST", "/periods", self.alice_token, json={"template_key": "summer-8-15", "start_date": "2000-07-01",
                                                              "end_date": "2000-08-31", "yearly": True})
        self.call("POST", "/local-holidays", self.alice_token, json={"date": "2026-11-17", "name": "Fiesta"})
        self.assertEqual(self.call("POST", "/local-holidays", self.alice_token,
                                   json={"date": "2026-11-17"}).status_code, 409)
        days = self.call("GET", "/calendar?from=2026-11-16&days=2", self.alice_token).json()
        self.assertEqual((days[0]["location"], days[1]["reason"]), ("home", "public holiday: Fiesta"))
        july = self.call("GET", "/calendar?from=2027-07-05&days=1", self.alice_token).json()[0]
        self.assertEqual(july["actions"][-1], {"action": "stop_day", "time": "15:00"})

    def test_changes_are_audited(self):
        self.call("PATCH", "/me", self.alice_token, json={"paused": True})
        with self.Session() as db:
            event = db.scalar(select(AuditEvent).where(AuditEvent.kind == "profile.update"))
        self.assertEqual(event.detail, {"fields": ["paused"]})
        self.assertTrue(event.actor.startswith("alice (token "))


class TestAccountAndClocking(ApiCase):

    def test_password_is_write_only_and_verify_finds_the_ids(self):
        r = self.call("PUT", "/eportem-account", self.alice_token, json={"username": "U0", "password": "pw0"})
        self.assertNotIn("password", r.json())
        self.assertIsNone(r.json()["office_activity_id"])
        r = self.call("POST", "/eportem-account/verify", self.alice_token)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["found"], {"office_activity_id": "1", "home_activity_id": "1293",
                                             "lunch_pause_id": "2"})
        self.assertEqual(self.fake.events, [])                    # verifying never clocks
        self.assertNotIn("pw0", r.text)

    def test_verify_with_a_wrong_password(self):
        self.call("PUT", "/eportem-account", self.alice_token, json={"username": "U0", "password": "wrong-pw"})
        r = self.call("POST", "/eportem-account/verify", self.alice_token)
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("wrong-pw", r.text)

    def test_clock_now_needs_confirm_and_records_once(self):
        self.call("PUT", "/eportem-account", self.alice_token, json={"username": "U0", "password": "pw0"})
        self.call("POST", "/eportem-account/verify", self.alice_token)
        self.assertEqual(self.call("POST", "/actions/start_day", self.alice_token, json={}).status_code, 400)
        r = self.call("POST", "/actions/start_day", self.alice_token, json={"confirm": True, "location": "home"})
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual([(e["action"], e["codactiv"]) for e in self.fake.events], [("_ststart", "1293")])
        log = self.call("GET", f"/runs/{r.json()['run_id']}/log", self.alice_token).json()
        self.assertEqual(log["run"]["status"], "recorded")
        again = self.call("POST", "/actions/start_day", self.alice_token, json={"confirm": True})
        self.assertEqual(again.status_code, 409)
        self.assertEqual(len(self.fake.events), 1)

    def test_channels_hide_secrets_and_can_be_tested(self):
        r = self.call("POST", "/channels", self.alice_token, json={
            "kind": "slack", "notify": True, "slack_status": True,
            "config": {"bot_token": "xoxb-secret-bot", "user_token": "xoxp-secret-user"}})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["config"]["bot_token"], "(set)")
        self.assertNotIn("xoxb-secret-bot", self.call("GET", "/channels", self.alice_token).text)
        ok = MagicMock(ok=True, status_code=200)
        ok.json.return_value = {"ok": True, "user_id": "U1"}
        with patch("requests.post", return_value=ok):
            t = self.call("POST", f"/channels/{r.json()['id']}/test", self.alice_token).json()
        self.assertTrue(t["delivered"])
        bad = self.call("POST", "/channels", self.alice_token, json={"kind": "slack", "slack_status": True,
                                                                      "config": {"bot_token": "x"}})
        self.assertEqual(bad.status_code, 422)


class TestAdminAndHealth(ApiCase):

    def test_admin_users_runs_stats(self):
        r = self.call("POST", "/admin/users", self.admin_token, json={"username": "dave", "password": "dave-password"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.call("POST", "/admin/users", self.admin_token,
                                   json={"username": "dave"}).status_code, 422)
        names = [u["username"] for u in self.call("GET", "/admin/users", self.admin_token).json()]
        self.assertEqual(names, ["boss", "alice", "bob", "dave"])
        stats = self.call("GET", "/admin/stats", self.admin_token).json()
        self.assertEqual(stats["users"], {"active": 4})
        self.assertEqual(self.call("GET", "/admin/runs?status=failed", self.admin_token).json(), [])

    def test_health(self):
        self.assertEqual(self.client.get("/healthz").json(), {"status": "ok"})
        self.assertEqual(self.client.head("/healthz").status_code, 200)
        self.assertEqual(self.client.head("/readyz").status_code, 200)
        self.assertEqual(self.client.get("/readyz").json(), {"status": "ready"})
        self.assertEqual(self.client.get("/api/openapi.json").status_code, 200)

    def test_readyz_reports_a_silent_scheduler(self):
        with patch.object(self.sched, "run_forever"):
            client = TestClient(create_app(self.settings, self.Session, self.engine, self.sched,
                                           start_scheduler=True))
            with client:
                r = client.get("/readyz")
        self.assertEqual(r.status_code, 503)
        self.assertIn("scheduler", r.json()["problems"][0])

    def test_account_rows_are_encrypted(self):
        self.call("PUT", "/eportem-account", self.alice_token, json={"username": "U0", "password": "pw-plain-x"})
        with self.Session() as db:
            self.assertNotIn("pw-plain-x", db.get(EportemAccount, self.alice).password_enc)
