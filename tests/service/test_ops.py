"""eportem.ops: metrics, heartbeat, backups, logs and error-report scrubbing."""
import datetime
import json
import logging
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from eportem import ops
from eportem.db.models import PlannedRun
from eportem.settings import load_settings
from tests.service.test_api import ApiCase
from tests.service.test_db import KEY


class TestMetrics(ApiCase):

    def setUp(self):
        super().setUp()
        self.settings = load_settings({"EPORTEM_SECRET_KEY": KEY, "EPORTEM_TARGET_URL": self.fake.base_url,
                                       "EPORTEM_METRICS_TOKEN": "metrics-token-1"})
        from fastapi.testclient import TestClient

        from eportem.web.app import create_app
        self.client = TestClient(create_app(self.settings, self.Session, self.engine, self.sched))

    def test_metrics_need_the_token(self):
        self.assertEqual(self.client.get("/metrics").status_code, 401)
        self.assertEqual(self.client.get("/metrics", headers={"Authorization": "Bearer x"}).status_code, 401)
        with self.Session.begin() as db:
            now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
            db.add(PlannedRun(user_id=self.alice, date=now.date(), action="start_day", target_minute=540,
                              planned_at=now - datetime.timedelta(minutes=2), location="office", status="planned"))
        r = self.client.get("/metrics", headers={"Authorization": "Bearer metrics-token-1"})
        self.assertEqual(r.status_code, 200)
        self.assertIn('eportem_users{status="active"} 3', r.text)
        self.assertIn('eportem_runs_last_24h{status="planned"} 1', r.text)
        lag = float(next(line for line in r.text.splitlines() if line.startswith("eportem_scheduler_lag")).split()[1])
        self.assertGreaterEqual(lag, 110)

    def test_metrics_off_without_a_token(self):
        self.assertEqual(self.client.get("/metrics").status_code, 401)
        from fastapi.testclient import TestClient

        from eportem.web.app import create_app
        plain = TestClient(create_app(load_settings({"EPORTEM_SECRET_KEY": KEY}), self.Session, self.engine,
                                      self.sched))
        self.assertEqual(plain.get("/metrics").status_code, 404)


class TestHeartbeat(ApiCase):

    def test_at_most_once_a_minute_and_never_blocking(self):
        hb = ops.Heartbeat("https://hc.example.com/ping/abc", every=60)
        with patch("requests.post") as get:
            self.assertTrue(hb.beat(now=1000))
            self.assertFalse(hb.beat(now=1030))
            self.assertTrue(hb.beat(now=1061))
            for t in list(__import__("threading").enumerate()):
                if t.name.startswith("Thread") and t.daemon:
                    t.join(timeout=1)
        self.assertEqual(get.call_count, 2)
        self.assertFalse(ops.Heartbeat(None).beat())

    def test_a_failing_ping_is_only_logged(self):
        hb = ops.Heartbeat("https://hc.example.com/ping/abc")
        import requests
        with patch("requests.post", side_effect=requests.ConnectionError("down")), \
                self.assertLogs("eportem.ops", "WARNING"):
            hb._ping()


class TestBackup(ApiCase):

    def test_backup_copies_and_rotates(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = load_settings({"EPORTEM_SECRET_KEY": KEY, "EPORTEM_DATA_DIR": tmp,
                                      "EPORTEM_DATABASE_URL": self.url})
            made = [ops.backup(settings, keep=2, now=datetime.datetime(2026, 11, 18, 3, i)) for i in range(3)]
            left = sorted(p.name for p in (Path(tmp) / "backups").iterdir())
            self.assertEqual(left, [made[1].name, made[2].name])
            self.assertEqual(made[2].stat().st_mode & 0o777, 0o600)
            with sqlite3.connect(made[2]) as db:
                self.assertEqual(db.execute("select count(*) from users").fetchone()[0], 3)
        with self.assertRaisesRegex(ValueError, "only handles SQLite"):
            ops.backup(load_settings({"EPORTEM_SECRET_KEY": KEY,
                                      "EPORTEM_DATABASE_URL": "postgresql+psycopg://u@db.example.com/e"}))


class TestLogsAndReports(ApiCase):

    def test_json_logs_scrub_tokens(self):
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "token xoxb-123-abc used", None, None)
        line = json.loads(ops.JsonFormatter().format(record))
        self.assertEqual(line["level"], "INFO")
        self.assertNotIn("xoxb-123-abc", line["message"])

    def test_error_reports_drop_request_data_and_scrub(self):
        event = {"request": {"data": "password=x", "cookies": "s=1", "headers": {"Authorization": "x"}},
                 "exception": {"values": [{"value": "failed /botSECRET/sendMessage"}]}}
        out = ops._scrub_event(event, None)
        self.assertEqual(out["request"], {})
        self.assertNotIn("SECRET", out["exception"]["values"][0]["value"])

    def test_error_reports_only_with_a_dsn(self):
        self.assertFalse(ops.init_error_reports(load_settings({"EPORTEM_SECRET_KEY": KEY})))
        with patch("sentry_sdk.init") as init:
            on = ops.init_error_reports(load_settings({"EPORTEM_SECRET_KEY": KEY,
                                                       "EPORTEM_SENTRY_DSN": "https://k@errors.example.com/1"}))
        self.assertTrue(on)
        self.assertFalse(init.call_args.kwargs["send_default_pii"])

    def test_setup_logging_formats(self):
        root = logging.getLogger()
        saved = root.handlers[:], root.level
        try:
            ops.setup_logging(load_settings({"EPORTEM_SECRET_KEY": KEY}))
            self.assertIsInstance(root.handlers[0].formatter, ops.JsonFormatter)
        finally:
            root.handlers[:], _ = saved[0], root.setLevel(saved[1])
