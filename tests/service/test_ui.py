"""The web UI with FastAPI's test client, against the fake ePortem."""
import datetime
import re
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from checkin.db.models import DayChangeRow, EportemAccount, ScheduleTemplate, User, UserSchedule, WebSession
from checkin.db.repo import local_today
from checkin.i18n import LANGUAGES, translator
from tests.service.test_api import ApiCase

PAGES = ("/", "/schedule", "/calendar", "/notifications", "/account", "/history", "/profile", "/tokens")


class UiCase(ApiCase):

    def browser(self, username="alice", password="alice-password-1", lang="es"):
        client = TestClient(self.app, follow_redirects=False, headers={"Accept-Language": lang})
        r = client.post("/login", data={"username": username, "password": password, "next": "/"})
        self.assertEqual(r.status_code, 303, r.text)
        return client

    def csrf(self, client, path="/"):
        return re.search(r'name="csrf" value="([0-9a-f]+)"', client.get(path).text).group(1)

    def post(self, client, path, data=None, **kw):
        return client.post(path, data={"csrf": self.csrf(client), **(data or {})}, **kw)


class TestSignIn(UiCase):

    def test_pages_need_a_session(self):
        client = TestClient(self.app, follow_redirects=False)
        r = client.get("/schedule")
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/login?next=/schedule"))
        self.assertEqual(client.get("/login").status_code, 200)

    def test_wrong_password_and_rate_limit(self):
        client = TestClient(self.app, follow_redirects=False)
        r = client.post("/login", data={"username": "alice", "password": "nope"})
        self.assertEqual(r.status_code, 401)
        for _ in range(10):
            client.post("/login", data={"username": "alice", "password": "nope"})
        r = client.post("/login", data={"username": "alice", "password": "alice-password-1"})
        self.assertEqual(r.status_code, 429)

    def test_cookie_is_http_only_and_session_is_hashed(self):
        client = TestClient(self.app, follow_redirects=False)
        r = client.post("/login", data={"username": "alice", "password": "alice-password-1", "next": "//evil"})
        self.assertEqual(r.headers["location"], "/")              # no open redirect
        cookie = r.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("samesite=lax", cookie.lower())
        value = client.cookies.get("checkin_session")
        with self.Session() as db:
            self.assertNotIn(value, [s.id_hash for s in db.scalars(select(WebSession))])

    def test_logout_ends_the_session(self):
        client = self.browser()
        self.post(client, "/logout")
        self.assertEqual(client.get("/").status_code, 303)

    def test_forms_need_the_csrf_token(self):
        client = self.browser()
        self.assertEqual(client.post("/schedule/template", data={"template_key": "spanish-9-18"}).status_code, 403)
        self.assertEqual(client.post("/schedule/template", data={"template_key": "spanish-9-18",
                                                                  "csrf": "0" * 64}).status_code, 403)

    def test_api_with_the_cookie_needs_the_csrf_header(self):
        client = self.browser()
        self.assertEqual(client.get("/api/v1/me").json()["username"], "alice")
        self.assertEqual(client.patch("/api/v1/me", json={"paused": True}).status_code, 403)
        r = client.patch("/api/v1/me", json={"paused": True}, headers={"X-CSRF-Token": self.csrf(client)})
        self.assertEqual(r.status_code, 200)


class TestPages(UiCase):

    def test_every_page_renders_in_every_language(self):
        for lang in LANGUAGES:
            word = translator(lang)("Schedule")
            with self.Session.begin() as db:
                db.get(User, self.alice).locale = lang
            client = self.browser(lang=lang)
            for path in PAGES:
                with self.subTest(lang=lang, path=path):
                    r = client.get(path)
                    self.assertEqual(r.status_code, 200, r.text[:500])
                    self.assertIn(word, r.text)
        admin = self.browser("boss", "boss-password-1")
        self.assertEqual(admin.get("/admin").status_code, 200)
        self.assertEqual(self.browser().get("/admin").status_code, 403)

    def test_home_shows_the_setup_steps_and_two_weeks(self):
        r = self.browser().get("/")
        self.assertIn("Primeros pasos", r.text)
        self.assertEqual(r.text.count('class="day '), 14)

    def test_one_tap_switches_a_day_and_a_second_tap_undoes_it(self):
        client = self.browser()
        day = local_today(type("U", (), {"timezone": "Europe/Madrid"})())
        while day.weekday() > 4:
            day += datetime.timedelta(days=1)
        r = self.post(client, f"/days/{day.isoformat()}/location", headers={"HX-Request": "true"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("casa", r.text)
        with self.Session() as db:
            self.assertEqual(db.query(DayChangeRow).count(), 1)
        r = self.post(client, f"/days/{day.isoformat()}/location", headers={"HX-Request": "true"})
        self.assertIn("oficina", r.text)
        with self.Session() as db:
            self.assertEqual(db.query(DayChangeRow).count(), 0)


class TestSecurityHeaders(UiCase):

    def test_pages_forbid_framing_and_inline_scripts(self):
        r = self.browser().get("/")
        csp = r.headers["content-security-policy"]
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("script-src 'self';", csp)
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertNotIn("onsubmit", r.text)
        self.assertNotIn("onclick", r.text)
        self.assertNotIn("strict-transport-security", r.headers)  # plain http here

    def test_clock_now_buttons_post_to_each_action(self):
        r = self.browser().get("/")
        for action in ("start_day", "lunch_break", "after_lunch", "stop_day"):
            self.assertIn(f'formaction="/actions/{action}"', r.text)


class TestForms(UiCase):

    def test_schedule_template_home_days_custom_week_and_periods(self):
        client = self.browser()
        self.assertEqual(self.post(client, "/schedule/template", {"template_key": "spanish-9-18"}).status_code, 303)
        self.post(client, "/schedule/home-days", {"home_2": "on", "home_4": "on"})
        self.post(client, "/schedule/holidays", {"holiday_country": "ES", "holiday_region": "CT"})
        with self.Session() as db:
            sched = db.get(UserSchedule, self.alice)
            self.assertEqual(sched.template_key, "spanish-9-18")
            self.assertEqual((sched.location_weeks[0]["2"], sched.location_weeks[0]["0"]), ("home", "office"))
            self.assertEqual(sched.holiday_region, "CT")
        bad = self.post(client, "/schedule/custom", {"works_0": "on", "start_0": "10:00", "stop_0": "09:00"})
        self.assertEqual(bad.status_code, 422)
        self.assertIn("times must be in order", bad.text)
        ok = self.post(client, "/schedule/custom", {"name": "Mine", "works_0": "on", "start_0": "08:00",
                                                   "stop_0": "15:00"})
        self.assertEqual(ok.status_code, 303)
        with self.Session() as db:
            self.assertEqual(db.scalar(select(ScheduleTemplate)).days, {"0": {"start": "08:00", "stop": "15:00"}})
            self.assertEqual(db.get(UserSchedule, self.alice).template_key, "custom")
        self.post(client, "/schedule/periods", {"template_key": "summer-8-15", "start_date": "2027-07-01",
                                                "end_date": "2027-08-31", "yearly": "1"})
        self.assertIn("summer-8-15", client.get("/schedule").text)

    def test_calendar_changes_and_local_holidays(self):
        client = self.browser()
        r = self.post(client, "/calendar/changes", {"kind": "time_off", "start_date": "2026-12-22",
                                                    "end_date": "2027-01-02", "note": "Navidad"})
        self.assertEqual(r.status_code, 303)
        r = self.post(client, "/calendar/changes", {"kind": "times", "start_date": "2026-12-01", "start": "10:00"})
        self.assertEqual(r.status_code, 422)
        self.post(client, "/calendar/holidays", {"date": "2026-12-09", "name": "Fiesta local"})
        page = client.get("/calendar?month=2026-12").text
        self.assertIn("Navidad", page)
        self.assertIn("Fiesta local", page)

    def test_account_save_and_verify_against_the_fake(self):
        client = self.browser()
        self.post(client, "/account", {"username": "U0", "password": "pw0", "use_http": "1"})
        r = self.post(client, "/account/verify")
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertIn("Trabajo en Casa", r.text)
        with self.Session() as db:
            self.assertEqual(db.get(EportemAccount, self.alice).home_activity_id, "1293")
        self.assertNotIn("pw0", client.get("/account").text)
        self.assertEqual(self.fake.events, [])

    def test_notifications_add_test_and_keep_secrets_hidden(self):
        client = self.browser()
        self.post(client, "/notifications", {"kind": "telegram", "token": "tg-secret-9", "chat_id": "7",
                                             "notify": "1", "alerts": "1"})
        page = client.get("/notifications").text
        self.assertNotIn("tg-secret-9", page)
        row_id = re.search(r'name="id" value="(\d+)"', page).group(1)
        with patch("requests.post", return_value=MagicMock(status_code=200)):
            r = self.post(client, f"/notifications/{row_id}/test")
        self.assertIn("Telegram notification sent successfully.", r.text)
        self.post(client, "/notifications", {"id": row_id, "chat_id": "8", "notify": "1"})  # token kept
        with self.Session() as db:
            from checkin.db.models import NotificationChannelRow
            cfg = self.box.decrypt_json(db.get(NotificationChannelRow, int(row_id)).config_enc)
        self.assertEqual((cfg["token"], cfg["chat_id"]), ("tg-secret-9", "8"))

    def test_tokens_profile_and_password(self):
        client = self.browser()
        r = self.post(client, "/tokens", {"name": "phone", "scope_read": "1"})
        token = re.search(r'<code class="token">(ept_[^<]+)</code>', r.text).group(1)
        self.assertEqual(self.call("GET", "/me", token).status_code, 200)
        self.assertNotIn(token, client.get("/tokens").text)
        bad = self.post(client, "/profile", {"timezone": "Europe/Madrid", "locale": "en",
                                             "jitter_before_minutes": "3", "jitter_after_minutes": "30"})
        self.assertEqual(bad.status_code, 422)
        self.post(client, "/profile", {"timezone": "Europe/Madrid", "locale": "en", "jitter_before_minutes": "3",
                                       "jitter_after_minutes": "2"})
        with self.Session() as db:
            self.assertEqual(db.get(User, self.alice).jitter_after_minutes, 2)
        r = self.post(client, "/profile/password", {"current": "alice-password-1", "new": "another-password"})
        self.assertEqual(r.status_code, 303)

    def test_admin_creates_and_suspends_and_sessions_end(self):
        admin = self.browser("boss", "boss-password-1")
        self.post(admin, "/admin/users", {"username": "erin", "password": "erin-password", "role": "user"})
        erin = self.browser("erin", "erin-password")
        with self.Session() as db:
            erin_id = db.scalar(select(User.id).where(User.username == "erin"))
        self.post(admin, f"/admin/users/{erin_id}/status", {"status": "suspended"})
        self.assertEqual(erin.get("/").status_code, 303)


class TestNoUntranslatedText(UiCase):
    """Every page in a made-up language whose texts are all ⟦marked⟧: whatever
    text is left unmarked was never sent through t() and would show in English
    whatever the person's language."""

    # Words that are the same in every language: names, codes, the person's own data.
    KEEP = {"CheckIn", "ePortem", "Telegram", "Slack", "token", "chat_id", "bot_token", "user_token", "channel",
            "webhook_url", "read", "write", "admin", "user", "ID", "UTC", "HTTP", "API", "api", "docs", "alice", "bob",
            "boss", "ept_", "BCDF", "GHJK"}

    class Texts(__import__("html.parser").parser.HTMLParser):
        def __init__(self):
            super().__init__()
            self.found, self.skip = [], 0

        VOID = ("input", "br", "meta", "link", "img", "hr")

        def handle_starttag(self, tag, attrs):
            if self.skip or tag in ("script", "style", "pre", "code") or ("translate", "no") in attrs:
                self.skip += tag not in self.VOID
                return
            self.found += [v for k, v in attrs if k in ("placeholder", "aria-label", "title") and v]

        def handle_endtag(self, tag):
            if self.skip and tag not in self.VOID:
                self.skip -= 1

        def handle_data(self, data):
            if not self.skip:
                self.found.append(data)

    def leftovers(self, html):
        parser = self.Texts()
        parser.feed(html)
        out = []
        for text in parser.found:
            rest = re.sub(r"⟦.*?⟧", " ", text, flags=re.S)
            out += [w for w in re.findall(r"[A-Za-z][A-Za-z_]{2,}", rest) if w not in self.KEEP]
        return out

    def test_every_page_is_fully_translated(self):
        from checkin import i18n
        marked = {"_language": "XX", **{k: f"⟦{v}⟧" for k, v in i18n.messages("en").items()}}
        with patch.dict(i18n.CATALOGUES, {"xx": marked}), patch.dict(i18n.LANGUAGES, {"xx": "XX"}):
            with self.Session.begin() as db:
                for u in db.scalars(select(User)):
                    u.locale = "xx"
            pages = [(self.browser(), p) for p in (*PAGES, "/device")]
            pages.append((self.browser("boss", "boss-password-1"), "/admin"))
            for client, path in pages:
                with self.subTest(path=path):
                    r = client.get(path)
                    self.assertEqual(r.status_code, 200)
                    self.assertEqual(self.leftovers(r.text), [])
