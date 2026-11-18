"""Running the service: logs, error reports, the heartbeat, metrics and backups
(docs/refactor/PLAN.md phase 7, D-009)."""
import datetime
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

import requests
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from eportem.core.notify import scrub
from eportem.db.models import PlannedRun, SchedulerLock, User

log = logging.getLogger("eportem.ops")


# --- logs --------------------------------------------------------------------------
class JsonFormatter(logging.Formatter):
    def format(self, record):
        out = {"time": datetime.datetime.fromtimestamp(record.created, datetime.UTC).isoformat(timespec="seconds"),
               "level": record.levelname, "logger": record.name, "message": scrub(record.getMessage())}
        if record.exc_info:
            out["error"] = scrub(self.formatException(record.exc_info))
        return json.dumps(out, ensure_ascii=False)


def setup_logging(settings):
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if settings.log_format == "json"
                         else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level)


# --- error reports ------------------------------------------------------------------------
def _scrub_event(event, hint):
    """Before an error report leaves: no request bodies, cookies or headers, and
    token-shaped strings removed from messages."""
    request = event.get("request") or {}
    for key in ("data", "cookies", "headers", "query_string"):
        request.pop(key, None)
    for exc in (event.get("exception") or {}).get("values", []):
        if "value" in exc:
            exc["value"] = scrub(exc["value"])
    if "message" in event:
        event["message"] = scrub(event["message"])
    return event


def init_error_reports(settings, version="0.1.0"):
    """Sentry or GlitchTip when EPORTEM_SENTRY_DSN is set. Returns True if on."""
    if not settings.sentry_dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        log.warning("EPORTEM_SENTRY_DSN is set but sentry-sdk is not installed; error reports are off")
        return False
    sentry_sdk.init(dsn=settings.sentry_dsn.get_secret_value(), environment=settings.sentry_environment,
                    release=f"eportem@{version}", send_default_pii=False, traces_sample_rate=0,
                    before_send=_scrub_event)
    return True


# --- heartbeat ----------------------------------------------------------------------------
class Heartbeat:
    """Pings a healthchecks.io-style URL at most every `every` seconds, in the
    background, so a slow or failing ping never delays the scheduler."""

    def __init__(self, url, every=60, timeout=10):
        self.url, self.every, self.timeout = url, every, timeout
        self._last = 0.0
        self._lock = threading.Lock()

    def beat(self, now=None):
        if not self.url:
            return False
        now = time.monotonic() if now is None else now
        with self._lock:
            if now - self._last < self.every:
                return False
            self._last = now
        threading.Thread(target=self._ping, daemon=True).start()
        return True

    def _ping(self):
        try:
            requests.get(self.url, timeout=self.timeout)
        except requests.RequestException as e:
            log.warning("heartbeat ping failed: %s", type(e).__name__)


# --- metrics ------------------------------------------------------------------------------
def metrics_text(db, now=None):
    """Prometheus text format, read from the database."""
    now = now or datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    lines = []

    def metric(name, kind, help_text, samples):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {kind}")
        for labels, value in samples:
            label_text = ",".join(f'{k}="{v}"' for k, v in labels.items())
            lines.append(f"{name}{{{label_text}}} {value}" if label_text else f"{name} {value}")

    users = db.execute(select(User.status, func.count()).group_by(User.status)).all()
    metric("eportem_users", "gauge", "People by account status.", [({"status": s}, n) for s, n in users])
    day_ago = now - datetime.timedelta(hours=24)
    runs = db.execute(select(PlannedRun.status, func.count()).where(PlannedRun.planned_at >= day_ago)
                      .group_by(PlannedRun.status)).all()
    metric("eportem_runs_last_24h", "gauge", "Runs planned in the last 24 hours, by status.",
           [({"status": s}, n) for s, n in runs])
    via = db.execute(select(PlannedRun.via, func.count()).where(PlannedRun.planned_at >= day_ago,
                                                                PlannedRun.status == "recorded")
                     .group_by(PlannedRun.via)).all()
    metric("eportem_recorded_last_24h", "gauge", "Recorded runs in the last 24 hours, by how they were sent.",
           [({"via": v or "unknown"}, n) for v, n in via])
    oldest_due = db.scalar(select(func.min(PlannedRun.planned_at)).where(PlannedRun.status == "planned",
                                                                         PlannedRun.planned_at <= now))
    lag = (now - oldest_due).total_seconds() if oldest_due else 0
    metric("eportem_scheduler_lag_seconds", "gauge", "How late the oldest due run is (0 when none is waiting).",
           [({}, round(lag, 1))])
    lock = db.get(SchedulerLock, "scheduler")
    age = (now - lock.heartbeat_at).total_seconds() if lock else -1
    metric("eportem_scheduler_heartbeat_age_seconds", "gauge", "Seconds since the scheduler last ticked "
           "(-1: never).", [({}, round(age, 1))])
    return "\n".join(lines) + "\n"


# --- backups ------------------------------------------------------------------------------
def backup(settings, keep=7, now=None):
    """Copy the SQLite database with SQLite's online backup (safe while the
    service runs) to <data dir>/backups/, keeping the newest `keep`. Returns the
    new file's path."""
    url = make_url(settings.effective_database_url)
    if url.get_backend_name() != "sqlite" or not url.database:
        raise ValueError("backup only handles SQLite; use your database's own tools (pg_dump) for Postgres")
    folder = Path(settings.data_dir) / "backups"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = (now or datetime.datetime.now()).strftime("%Y%m%d-%H%M%S")
    target = folder / f"eportem-{stamp}.db"
    source = sqlite3.connect(url.database)
    try:
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    target.chmod(0o600)
    for old in sorted(folder.glob("eportem-*.db"), reverse=True)[keep:]:
        old.unlink()
    return target
