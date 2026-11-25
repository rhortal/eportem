"""Agents: signing in with the device flow, /status, revoking the current token
and reading ePortem's live state (D-028), against the fake ePortem."""
import datetime
import re

from fastapi.testclient import TestClient
from sqlalchemy import select

from checkin import device
from checkin.db.models import ApiToken, AuditEvent, DeviceGrant
from tests.service.test_ui import UiCase


class DeviceCase(UiCase):

    def start(self, **body):
        r = self.client.post("/api/v1/device/code", json=body or {"client_name": "Claude Code on laptop"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def poll(self, code):
        return self.client.post("/api/v1/device/token", json={"device_code": code})

    def approve(self, browser, user_code, scopes=("read", "write"), decision="approve"):
        page = browser.get(f"/device?code={user_code}")
        self.assertEqual(page.status_code, 200, page.text)
        csrf = re.search(r'name="csrf" value="([0-9a-f]+)"', page.text).group(1)
        data = {"csrf": csrf, "code": user_code, "decision": decision, **{f"scope_{s}": "1" for s in scopes}}
        return browser.post("/device", data=data)

    def unthrottle(self):
        """Pretend the agent waited its interval since its last poll."""
        with self.Session.begin() as db:
            for row in db.scalars(select(DeviceGrant)):
                if row.last_polled_at:
                    row.last_polled_at -= datetime.timedelta(seconds=device.INTERVAL)


class TestDeviceFlow(DeviceCase):

    def test_approve_then_the_agent_gets_a_working_token_once(self):
        out = self.start()
        self.assertRegex(out["user_code"], r"^[A-Z]{4}-[A-Z]{4}$")
        self.assertTrue(out["verification_uri_complete"].endswith(f"/device?code={out['user_code']}"))
        self.assertEqual((out["interval"], out["expires_in"]), (5, 600))
        self.assertEqual(self.poll(out["device_code"]).json()["error"], "authorization_pending")

        browser = self.browser(lang="en")
        page = browser.get(f"/device?code={out['user_code'].lower()}")
        self.assertIn("Claude Code on laptop", page.text)
        self.assertIn(out["user_code"], page.text)
        self.assertIn("ya está conectado", self.approve(browser, out["user_code"]).text)

        self.unthrottle()
        r = self.poll(out["device_code"])
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["username"], body["scopes"], body["token_type"]), ("alice", ["read", "write"], "Bearer"))
        me = self.call("GET", "/me", body["access_token"])
        self.assertEqual(me.json()["username"], "alice")
        self.assertEqual(self.poll(out["device_code"]).json()["error"], "invalid_grant")  # only once
        with self.Session() as db:
            token = db.scalar(select(ApiToken).where(ApiToken.prefix == body["token_prefix"]))
            self.assertEqual(token.name, "Agent: Claude Code on laptop")
            self.assertAlmostEqual((token.expires_at - token.created_at).days, device.TOKEN_DAYS, delta=1)
            grant = db.scalar(select(DeviceGrant))
            self.assertNotIn(out["device_code"], grant.device_code_hash)
            kinds = [e.kind for e in db.scalars(select(AuditEvent))]
            self.assertIn("device.approve", kinds)

    def test_the_person_can_give_less_than_asked(self):
        out = self.start()
        self.approve(self.browser(), out["user_code"], scopes=("read",))
        self.unthrottle()
        token = self.poll(out["device_code"]).json()["access_token"]
        self.assertEqual(self.call("PATCH", "/me", token, json={"paused": True}).status_code, 403)

    def test_choosing_nothing_is_a_problem_not_an_approval(self):
        out = self.start()
        r = self.approve(self.browser(), out["user_code"], scopes=())
        self.assertEqual(r.status_code, 422)
        self.unthrottle()
        self.assertEqual(self.poll(out["device_code"]).json()["error"], "authorization_pending")

    def test_a_non_admin_cannot_hand_out_admin(self):
        out = self.start(client_name="x", scopes=["read", "admin"])
        browser = self.browser()
        self.assertNotIn("scope_admin", browser.get(f"/device?code={out['user_code']}").text)
        self.approve(browser, out["user_code"], scopes=("read", "admin"))
        self.unthrottle()
        self.assertEqual(self.poll(out["device_code"]).json()["scopes"], ["read"])

    def test_deny(self):
        out = self.start()
        self.assertIn("no se ha conectado", self.approve(self.browser(), out["user_code"], decision="deny").text)
        self.unthrottle()
        r = self.poll(out["device_code"])
        self.assertEqual((r.status_code, r.json()["error"]), (400, "access_denied"))

    def test_polling_too_fast_is_slowed_down(self):
        out = self.start()
        self.poll(out["device_code"])
        r = self.poll(out["device_code"])
        self.assertEqual((r.status_code, r.json()["error"]), (429, "slow_down"))

    def test_expired_codes(self):
        out = self.start()
        with self.Session.begin() as db:
            db.scalar(select(DeviceGrant)).expires_at = datetime.datetime(2000, 1, 1)
        self.assertEqual(self.poll(out["device_code"]).json()["error"], "expired_token")
        r = self.browser().get(f"/device?code={out['user_code']}")
        self.assertEqual(r.status_code, 404)

    def test_unknown_device_code_and_bad_scopes(self):
        self.assertEqual(self.poll("nope").json()["error"], "invalid_grant")
        r = self.client.post("/api/v1/device/code", json={"scopes": ["everything"]})
        self.assertEqual(r.status_code, 422)

    def test_starting_is_rate_limited_per_address(self):
        for _ in range(10):
            self.start()
        self.assertEqual(self.client.post("/api/v1/device/code", json={}).status_code, 429)

    def test_the_page_needs_a_session_and_keeps_the_code_through_sign_in(self):
        client = TestClient(self.app, follow_redirects=False)
        r = client.get("/device?code=BCDF-GHJK")
        self.assertEqual(r.status_code, 303)
        self.assertEqual(r.headers["location"], "/login?next=/device%3Fcode%3DBCDF-GHJK")
        r = client.post("/login", data={"username": "alice", "password": "alice-password-1",
                                        "next": "/device?code=BCDF-GHJK"})
        self.assertEqual(r.headers["location"], "/device?code=BCDF-GHJK")

    def test_the_page_asks_for_a_code_and_guessing_is_limited(self):
        browser = self.browser(lang="en")
        self.assertIn('name="code"', browser.get("/device").text)
        for _ in range(10):
            self.assertEqual(browser.get("/device?code=BCDF-GHJK").status_code, 404)
        self.assertEqual(browser.get("/device?code=BCDF-GHJK").status_code, 429)

    def test_a_used_or_denied_code_cannot_be_approved_again(self):
        out = self.start()
        browser = self.browser()
        self.approve(browser, out["user_code"], decision="deny")
        csrf = self.csrf(browser, "/device")
        r = browser.post("/device", data={"csrf": csrf, "code": out["user_code"], "decision": "approve",
                                          "scope_read": "1"})
        self.assertEqual(r.status_code, 404)

    def test_the_spanish_page(self):
        out = self.start()
        self.assertIn("Conectar un agente", self.browser(lang="es").get(f"/device?code={out['user_code']}").text)

    def test_user_codes(self):
        self.assertEqual(device.normalise_user_code("bcdf ghjk"), "BCDFGHJK")
        self.assertEqual(device.normalise_user_code("ABCD-EFGH"), "")  # vowels are never in a code
        self.assertEqual(device.normalise_user_code(None), "")


class TestTokensPageForAgents(DeviceCase):

    def test_the_text_to_paste_has_a_personal_install_link(self):
        html = self.browser(lang="en").get("/tokens").text
        self.assertIn('id="for-agents"', html)
        self.assertRegex(html, r"curl -fsSL http://testserver/skill/\d+\.\d+\.[0-9a-f]{32}/install\.sh \| sh")
        self.assertIn("checkin.py login", html)
        self.assertIn("Configura CheckIn", html)             # alice reads Spanish

    def test_the_page_needs_a_session(self):
        r = TestClient(self.app, follow_redirects=False).get("/tokens")
        self.assertEqual(r.status_code, 303)


class TestAgentEndpoints(DeviceCase):

    def test_status(self):
        r = self.call("GET", "/status", self.alice_token)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["user"]["username"], "alice")
        self.assertIn("works", body["today"])
        self.assertEqual([s["step"] for s in body["setup"]],
                         ["ePortem account", "Working-day template", "Home days", "Notifications"])
        self.assertIn("next_run", body)

    def test_runs_say_when_they_really_go_in_local_time(self):
        import datetime as dt

        from checkin.db.models import PlannedRun
        with self.Session.begin() as db:
            db.add(PlannedRun(user_id=self.alice, date=dt.date(2026, 12, 1), action="stop_day", target_minute=18 * 60,
                              planned_at=dt.datetime(2026, 12, 1, 17, 8, 54), location="home", status="planned"))
        runs = self.call("GET", "/runs?from=2026-12-01&to=2026-12-01", self.alice_token).json()
        self.assertEqual((runs[0]["time"], runs[0]["at"]), ("18:00", "18:08:54"))   # Madrid, UTC+1

    def test_revoke_the_current_token(self):
        self.assertEqual(self.call("DELETE", "/tokens/current", self.alice_token).status_code, 204)
        self.assertEqual(self.call("GET", "/me", self.alice_token).status_code, 401)
        browser = self.browser()
        r = browser.delete("/api/v1/tokens/current", headers={"X-CSRF-Token": self.csrf(browser)})
        self.assertEqual(r.status_code, 400)

    def test_eportem_state_follows_the_dashboard_and_never_clocks(self):
        self.call("PUT", "/eportem-account", self.alice_token, json={"username": "U0", "password": "pw0"})
        self.call("POST", "/eportem-account/verify", self.alice_token)
        r = self.call("GET", "/eportem/state", self.alice_token)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["state"], "not_working")
        self.assertTrue(body["activity_ids_known"])
        self.assertIn({"action": "start_day", "location": "home"}, body["available_actions"])
        self.assertNotIn("stop_day", [a["action"] for a in body["available_actions"]])
        self.fake.accounts["U0"].state = "working"
        self.fake.accounts["U0"].working_activity = "1"
        body = self.call("GET", "/eportem/state", self.alice_token).json()
        self.assertEqual(body["state"], "working")
        self.assertEqual({a["action"] for a in body["available_actions"]}, {"lunch_break", "stop_day"})
        self.fake.accounts["U0"].state = "paused"
        body = self.call("GET", "/eportem/state", self.alice_token).json()
        self.assertEqual(body["state"], "on_break")
        self.assertEqual({(a["action"], a["location"]) for a in body["available_actions"]},
                         {("after_lunch", "home"), ("after_lunch", "office"), ("stop_day", None)})
        self.assertEqual(self.fake.events, [])

    def test_eportem_state_without_an_account_or_with_a_wrong_password(self):
        self.assertEqual(self.call("GET", "/eportem/state", self.alice_token).status_code, 422)
        self.call("PUT", "/eportem-account", self.alice_token, json={"username": "U0", "password": "wrong-pw"})
        r = self.call("GET", "/eportem/state", self.alice_token)
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("wrong-pw", r.text)
