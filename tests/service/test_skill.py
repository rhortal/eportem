"""The skill's script (skill/checkin/scripts/checkin.py) end to end: installed
from the app's signed link, its HTTP going to the app's test client (D-028)."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from checkin import skill
from tests.service.test_device import DeviceCase

APP = "http://testserver"
ENV = ("CHECKIN_URL", "CHECKIN_TOKEN", "CHECKIN_NO_UPDATE_CHECK", "CHECKIN_CONFIG")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SkillCase(DeviceCase):

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp)
        patcher = patch.dict(os.environ, {k: "" for k in ENV})
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in ENV:
            os.environ.pop(key)
        os.environ["CHECKIN_CONFIG"] = str(self.tmp / "conf" / "agent.json")
        # Install the skill from the link on alice's tokens page, as install.sh would.
        self.base = self.skill_base(self.browser())
        anonymous = TestClient(self.app)
        self.zip = anonymous.get(f"{self.base}/checkin.zip").content
        self.skills = self.tmp / "skills"
        self.skills.mkdir()
        with zipfile.ZipFile(io.BytesIO(self.zip)) as z:
            z.extractall(self.skills)
        self.script = load(self.skills / "checkin" / "scripts" / "checkin.py", "checkin_skill")
        self.script.http = self.http
        self.script.time.sleep = lambda s: self.unthrottle()

    def skill_base(self, browser):
        html = browser.get("/tokens").text
        return re.search(r"curl -fsSL (\S+)/install\.sh \| sh", html).group(1)

    def http(self, method, url, body=None, token=None, timeout=30):
        self.assertTrue(url.startswith(APP), url)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        r = self.client.request(method, url[len(APP):], json=body, headers=headers)
        try:
            parsed = r.json() if r.content else None
        except ValueError:
            parsed = r.text
        return r.status_code, parsed, r.content

    def run_script(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.script.main(list(argv))
        self.last_err = err.getvalue()
        return code, (json.loads(out.getvalue()) if out.getvalue().strip() else None)

    def sign_in(self, *extra):
        code, out = self.run_script("login", *extra)
        self.assertEqual(code, 0, self.last_err)
        self.approve(self.browser(), out["code"])
        self.unthrottle()
        code, out = self.run_script("login", "--wait")
        self.assertEqual(code, 0, self.last_err)
        return out


class TestSkill(SkillCase):

    def test_sign_in_status_and_sign_out(self):
        code, out = self.run_script("status")
        self.assertEqual(code, 3)                                  # not signed in yet
        code, out = self.run_script("login")
        self.assertTrue(out["open_this_link"].endswith(f"/device?code={out['code']}"))
        code, waiting = self.run_script("login", "--wait", "--timeout", "0")
        self.assertEqual((code, waiting["waiting"]), (4, True))
        self.approve(self.browser(), out["code"])
        self.unthrottle()
        code, out = self.run_script("login", "--wait")
        self.assertEqual((code, out["signed_in_as"]), (0, "alice"))
        conf = Path(os.environ["CHECKIN_CONFIG"])
        self.assertEqual(stat.S_IMODE(conf.stat().st_mode), 0o600)
        saved = json.loads(conf.read_text())
        self.assertTrue(saved["token"].startswith("ept_"))
        self.assertNotIn(saved["token"], json.dumps(out))        # the token is never printed
        code, out = self.run_script("status")
        self.assertEqual((code, out["user"]["username"]), (0, "alice"))
        self.assertEqual(self.run_script("whoami")[1]["username"], "alice")
        self.assertEqual(self.run_script("logout")[0], 0)
        self.assertEqual(self.call("GET", "/me", saved["token"]).status_code, 401)
        self.assertNotIn("token", json.loads(conf.read_text()))

    def test_requests_with_a_body_and_query_values(self):
        self.sign_in()
        code, out = self.run_script("post", "/days", '{"kind": "time_off", "start_date": "2030-12-24"}')
        self.assertEqual((code, out["kind"]), (0, "time_off"))
        code, out = self.run_script("get", "/calendar", "from=2030-12-23", "days=2")
        self.assertEqual([d["works"] for d in out], [True, False])
        self.assertEqual(self.run_script("delete", f"/api/v1/days/{self.run_script('get', '/days')[1][0]['id']}")[0],
                         0)
        code, _ = self.run_script("post", "/days", '{"kind": "nap"}')
        self.assertEqual(code, 1)
        self.assertIn("422", self.last_err)
        self.assertEqual(self.run_script("post", "/days", "{not json")[0], 2)
        self.assertEqual(self.run_script("get", "/calendar", "nonsense")[0], 2)

    def test_a_read_only_sign_in_cannot_change_things(self):
        self.sign_in("--read-only")
        code, _ = self.run_script("patch", "/me", '{"paused": true}')
        self.assertEqual(code, 1)
        self.assertIn("403", self.last_err)

    def test_state_and_clock_need_a_yes(self):
        self.sign_in()
        self.call("PUT", "/eportem-account", self.alice_token, json={"username": "U0", "password": "pw0"})
        self.call("POST", "/eportem-account/verify", self.alice_token)
        self.assertEqual(self.run_script("state")[1]["state"], "not_working")
        code, _ = self.run_script("clock", "start_day", "--location", "home")
        self.assertEqual(code, 2)
        self.assertIn("--yes", self.last_err)
        self.assertEqual(self.fake.events, [])
        code, out = self.run_script("clock", "start_day", "--location", "home", "--yes")
        self.assertEqual((code, out["recorded"], out["location"]), (0, True, "home"), self.last_err)
        self.assertEqual([(e["action"], e["codactiv"]) for e in self.fake.events], [("_ststart", "1293")])
        self.assertEqual(self.run_script("state")[1]["state"], "working")
        code, _ = self.run_script("clock", "start_day", "--yes")
        self.assertEqual(code, 1)                                    # already recorded today: 409
        self.assertIn("409", self.last_err)

    def test_an_expired_or_revoked_token_asks_to_sign_in_again(self):
        self.sign_in()
        self.run_script("delete", "/tokens/current")
        self.assertEqual(self.run_script("status")[0], 3)


class TestSkillUpdates(SkillCase):

    def setUp(self):
        super().setUp()
        self.sign_in()
        self.script.VERSION = "0.9.0"

    def test_update_check_needs_and_uses_the_agent_token(self):
        self.assertTrue(self.run_script("update", "--check")[1]["update_available"])
        self.script.VERSION = skill.version()
        code, out = self.run_script("update", "--check")
        self.assertEqual(out["update_available"], False)
        self.run_script("logout")
        self.assertEqual(self.run_script("update", "--check")[0], 3)

    def test_update_replaces_the_folder_after_checking_the_checksum(self):
        (self.skills / "checkin" / "stale.txt").write_text("old")
        code, out = self.run_script("update")
        self.assertEqual((code, out["updated_to"]), (0, skill.version()), self.last_err)
        self.assertFalse((self.skills / "checkin" / "stale.txt").exists())
        self.assertTrue((self.skills / "checkin" / "SKILL.md").is_file())
        self.assertEqual(sorted(p.name for p in self.skills.iterdir()), ["checkin"])

    def test_a_download_that_does_not_match_changes_nothing(self):
        real = self.http

        def tampered(method, url, *args, **kw):
            return (200, None, b"not the zip") if url.endswith(".zip") else real(method, url, *args, **kw)
        self.script.http = tampered
        (self.skills / "checkin" / "stale.txt").write_text("old")
        self.assertEqual(self.run_script("update")[0], 1)
        self.assertIn("checksum", self.last_err)
        self.assertTrue((self.skills / "checkin" / "stale.txt").exists())

    def test_unsafe_zips_are_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("../evil.txt", "x")
        with self.assertRaises(self.script.Problem):
            self.script.install_zip(buf.getvalue(), self.skills / "checkin")
        self.assertFalse((self.skills / "evil.txt").exists())

    def test_a_daily_note_when_a_newer_version_is_out(self):
        self.run_script("whoami")
        self.assertIn("is available", self.last_err)
        self.script.http = lambda *a, **k: self.fail("checked twice in a day")
        self.run_script("whoami")
        self.assertIn("is available", self.last_err)


class TestSkillOnlyForAccounts(SkillCase):

    def test_the_link_serves_the_installer_the_zip_and_its_checksum(self):
        anonymous = TestClient(self.app)
        script = anonymous.get(f"{self.base}/install.sh")
        self.assertEqual(script.status_code, 200)
        self.assertIn(f'BASE="{self.base}"', script.text)
        self.assertNotIn("{{", script.text)
        info = anonymous.get(f"{self.base}/version.json").json()
        self.assertEqual(info["sha256"], hashlib.sha256(self.zip).hexdigest())

    def test_no_link_no_skill(self):
        anonymous = TestClient(self.app)
        user_id = self.base.split("/skill/")[1].split(".")[0]
        for bad in ("nonsense", f"{user_id}.9999999999.{'0' * 32}", f"{user_id}.1.{'0' * 32}"):
            self.assertEqual(anonymous.get(f"/skill/{bad}/checkin.zip").status_code, 404, bad)
        self.assertEqual(anonymous.get("/api/v1/skill/checkin.zip").status_code, 401)
        self.assertEqual(anonymous.get("/api/v1/skill").status_code, 401)

    def test_links_expire_and_die_with_the_account(self):
        secret = self.settings.secret_key.get_secret_value()
        link = self.base.split("/skill/")[1]
        self.assertIsNotNone(skill.check_link(secret, link))
        self.assertIsNone(skill.check_link(secret, link, now=10 ** 11))
        from checkin.db.models import User
        with self.Session.begin() as db:
            db.get(User, self.alice).status = "suspended"
        self.assertEqual(TestClient(self.app).get(f"{self.base}/checkin.zip").status_code, 404)

    def test_the_zip_is_the_same_every_time_and_knows_this_app(self):
        self.assertEqual(TestClient(self.app).get(f"{self.base}/checkin.zip").content, self.zip)
        with zipfile.ZipFile(io.BytesIO(self.zip)) as z:
            self.assertEqual(sorted(z.namelist()), ["checkin/SKILL.md", "checkin/defaults.json",
                                                    "checkin/scripts/checkin.py"])
            self.assertEqual(json.loads(z.read("checkin/defaults.json")), {"app_url": APP})

    def test_the_skill_md_has_its_front_matter(self):
        text = (skill.SKILL_DIR / "checkin" / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: checkin\ndescription: "))
