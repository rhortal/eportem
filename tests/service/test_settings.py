"""eportem.settings: sources and their order, secrets from files, checks, and
the generated docs staying in step with the code."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from eportem import cli
from eportem import settings as s
from eportem.core.schedule import jitter_problems

KEY = Fernet.generate_key().decode()
REPO = Path(__file__).resolve().parent.parent.parent


def env(**kw):
    return {"EPORTEM_SECRET_KEY": KEY, **{f"EPORTEM_{k.upper()}": v for k, v in kw.items()}}


class TestLoading(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_defaults_are_neutral(self):
        st = s.load_settings(env())
        self.assertEqual(st.target_url, "https://eportem.es")
        self.assertEqual(st.effective_public_url, "http://localhost:8080")
        self.assertEqual(st.effective_database_url, "sqlite:////data/eportem.db")
        self.assertFalse(st.effective_secure_cookies)
        self.assertEqual((st.default_jitter_before_minutes, st.default_jitter_after_minutes), (5, 4))
        self.assertEqual(st.registration, "closed")

    def test_only_the_given_environment_is_read(self):
        os.environ["EPORTEM_PORT"] = "1234"
        self.addCleanup(os.environ.pop, "EPORTEM_PORT")
        self.assertEqual(s.load_settings(env()).port, 8080)

    def test_the_legacy_scripts_variables_are_ignored(self):
        st = s.load_settings(env(enabled="YES", http="YES", username="u", password="p", state_dir="/x"))
        self.assertEqual(st.port, 8080)

    def test_environment_parsing(self):
        st = s.load_settings(env(port="9000", trusted_proxies="192.0.2.1, 203.0.113.0/24", headless="false",
                                 public_url="https://eportem.example.com/", smtp_host=""))
        self.assertEqual(st.port, 9000)
        self.assertEqual(st.trusted_proxies, ["192.0.2.1", "203.0.113.0/24"])
        self.assertFalse(st.headless)
        self.assertEqual(st.public_url, "https://eportem.example.com")
        self.assertTrue(st.effective_secure_cookies)
        self.assertIsNone(st.smtp_host)

    def test_config_file_below_environment(self):
        path = self.dir / "eportem.toml"
        path.write_text('port = 7000\nlog_format = "text"\n')
        st = s.load_settings(env(config_file=str(path), port="7001"))
        self.assertEqual((st.port, st.log_format), (7001, "text"))

    def test_config_file_problems(self):
        path = self.dir / "bad.toml"
        path.write_text("nap = 1\n")
        with self.assertRaises(s.SettingsError) as cm:
            s.load_settings(env(config_file=str(path)))
        self.assertIn("unknown setting 'nap'", cm.exception.problems[0])
        path.write_text("port = \n")
        with self.assertRaisesRegex(s.SettingsError, "not valid TOML"):
            s.load_settings(env(config_file=str(path)))
        with self.assertRaisesRegex(s.SettingsError, "cannot read"):
            s.load_settings(env(config_file=str(self.dir / "missing.toml")))

    def test_secrets_from_files(self):
        key_file = self.dir / "key"
        key_file.write_text(KEY + "\n")
        st = s.load_settings({"EPORTEM_SECRET_KEY_FILE": str(key_file)})
        self.assertEqual(st.secret_key.get_secret_value(), KEY)
        with self.assertRaisesRegex(s.SettingsError, "either it or EPORTEM_SECRET_KEY_FILE"):
            s.load_settings({"EPORTEM_SECRET_KEY": KEY, "EPORTEM_SECRET_KEY_FILE": str(key_file)})
        with self.assertRaisesRegex(s.SettingsError, "EPORTEM_SECRET_KEY_FILE: cannot read"):
            s.load_settings({"EPORTEM_SECRET_KEY_FILE": str(self.dir / "nope")})


class TestChecks(unittest.TestCase):

    def problems(self, environ):
        with self.assertRaises(s.SettingsError) as cm:
            s.load_settings(environ)
        return " | ".join(cm.exception.problems)

    def test_every_field_problem_is_named_by_its_variable(self):
        text = self.problems({"EPORTEM_SECRET_KEY": "not-a-key", "EPORTEM_DEFAULT_TIMEZONE": "Mars/Base",
                              "EPORTEM_REGISTRATION": "everyone", "EPORTEM_TARGET_URL": "eportem.es",
                              "EPORTEM_PORT": "0", "EPORTEM_DEFAULT_TEMPLATE": "nap"})
        for name in ("EPORTEM_SECRET_KEY: must be a Fernet key", "EPORTEM_DEFAULT_TIMEZONE: unknown time zone",
                     "EPORTEM_REGISTRATION:", "EPORTEM_TARGET_URL: must start with http",
                     "EPORTEM_PORT:", "EPORTEM_DEFAULT_TEMPLATE: must be one of"):
            self.assertIn(name, text)
        self.assertIn("EPORTEM_SECRET_KEY: required", self.problems({}))

    def test_default_offset_must_fit_the_window(self):
        text = self.problems(env(window_minutes="10", default_jitter_after_minutes="11"))
        self.assertIn("default the random offset after (11 min) must not be larger than the 10-minute window", text)

    def test_cross_field_rules(self):
        self.assertIn("smtp_from is required", self.problems(env(smtp_host="mail.example.com")))
        self.assertIn("needs smtp_host", self.problems(env(registration="open")))
        self.assertIn("go together", self.problems(env(admin_username="admin")))

    def test_jitter_problems(self):
        self.assertEqual(jitter_problems(5, 4, 15), [])
        self.assertEqual(jitter_problems(15, 15, 15), [])
        self.assertEqual(len(jitter_problems(16, -1, 15)), 2)


class TestShow(unittest.TestCase):

    def test_sources_and_hidden_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.toml"
            path.write_text("log_level = 'DEBUG'\n")
            environ = env(config_file=str(path), port="9000", metrics_token="tok-123")
            rows = {r[0]: r[1:] for r in s.describe(s.load_settings(environ), environ)}
        self.assertEqual(rows["EPORTEM_PORT"], ("9000", "environment"))
        self.assertEqual(rows["EPORTEM_LOG_LEVEL"], ("DEBUG", f"config file {path}"))
        self.assertEqual(rows["EPORTEM_HOST"], ("0.0.0.0", "default"))
        self.assertEqual(rows["EPORTEM_METRICS_TOKEN"], ("(set)", "environment"))
        self.assertEqual(rows["EPORTEM_SECRET_KEY"][0], "(set)")
        self.assertNotIn("tok-123", repr(rows))
        self.assertNotIn(KEY, repr(rows))

    def test_cli_check_exit_codes(self):
        old = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))
        os.environ.pop("EPORTEM_SECRET_KEY", None)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli.main(["config", "check"]), 2)
        self.assertIn("EPORTEM_SECRET_KEY: required", err.getvalue())
        os.environ["EPORTEM_SECRET_KEY"] = KEY
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["config", "check"]), 0)
            self.assertEqual(cli.main(["config", "show"]), 0)
        self.assertNotIn(KEY, out.getvalue())


class TestDocsInStep(unittest.TestCase):
    """.env.example and README's table are generated; regenerate them with
    `python -m eportem config docs` after changing eportem/settings.py."""

    def test_env_example(self):
        self.assertEqual((REPO / ".env.example").read_text(), s.env_example() + "\n")

    def test_readme_table(self):
        readme = (REPO / "README.md").read_text()
        block = f"{cli.TABLE_START}\n{s.markdown_table()}\n{cli.TABLE_END}"
        self.assertIn(block, readme)

    def test_every_setting_is_documented(self):
        for name, field in s.Settings.model_fields.items():
            self.assertTrue(field.description, name)
            self.assertIn((field.json_schema_extra or {}).get("group"), s.GROUPS, name)


if __name__ == "__main__":
    unittest.main()
