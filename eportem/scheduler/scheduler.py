"""The scheduler: plans each person's day and runs their actions on time.

One `tick(now)` does everything due at `now` (UTC). `run_forever()` calls it
every few seconds in a thread. Rules (docs/refactor/PLAN.md phase 4, D-003):

- A run is claimed by moving it from `planned` to `running` with a
  conditional update; the unique (person, date, action) row means a restart
  or a second scheduler can never clock it twice.
- A run is never started after its window closes: it becomes `skipped`.
- A run left `running` by a crash becomes `unknown` (never retried) and the
  person is alerted, as for OutcomeUnknown.
- Only the replica holding the lock schedules.
"""
import datetime
import logging
import socket
import threading
import uuid
import zoneinfo
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select, update

from eportem.core.actions import ActionNotApplicable
from eportem.core.calendar import resolve
from eportem.core.clock_http import NotRecorded, OutcomeUnknown
from eportem.core.schedule import format_minutes
from eportem.db.models import DayCheck, PlannedRun, RunLog, SchedulerLock, User
from eportem.db.repo import load_calendar
from eportem.scheduler.planner import plan_day, window_end_utc
from eportem.scheduler.runner import build_action, send_alert

log = logging.getLogger("eportem.scheduler")
LOCK_NAME = "scheduler"
LOCK_STALE = datetime.timedelta(minutes=2)


def _naive_utc(now):
    return now.astimezone(datetime.UTC).replace(tzinfo=None) if now.tzinfo else now


class Scheduler:
    def __init__(self, settings, sessionmaker, box, engine, executor=None, rng=None, holder=None):
        self.settings, self.Session, self.box, self.engine = settings, sessionmaker, box, engine
        self.executor = executor  # None: run inline (tests); else a ThreadPoolExecutor
        self.rng = rng
        self.holder = holder or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self._planned = {}         # user_id -> local date planned
        self._started = False
        self._stop = threading.Event()

    # --- leadership --------------------------------------------------------
    def acquire_lock(self, now):
        with self.Session.begin() as db:
            lock = db.get(SchedulerLock, LOCK_NAME)
            if lock is None:
                db.add(SchedulerLock(name=LOCK_NAME, holder=self.holder, heartbeat_at=now))
                return True
            if lock.holder == self.holder or now - lock.heartbeat_at > LOCK_STALE:
                lock.holder, lock.heartbeat_at = self.holder, now
                return True
            return False

    # --- the tick ------------------------------------------------------------
    def tick(self, now=None):
        """Do everything due at `now`. Returns the ids of runs started."""
        now = _naive_utc(now or datetime.datetime.now(datetime.UTC))
        if not self.acquire_lock(now):
            return []
        first = not self._started
        if first:
            self._recover(now)
            self._started = True
        self._plan_all(now, alert_missed=first)
        started = self._dispatch(now)
        self._verify_days(now)
        return started

    def replan(self, user_id, now=None):
        """Call after a person's calendar or profile changed."""
        now = _naive_utc(now or datetime.datetime.now(datetime.UTC))
        with self.Session.begin() as db:
            user = db.get(User, user_id)
            if user:
                plan_day(db, user, self._local_date(user, now), now, self.settings.window_minutes, self.rng)

    def _local_date(self, user, now):
        return now.replace(tzinfo=datetime.UTC).astimezone(zoneinfo.ZoneInfo(user.timezone)).date()

    def _recover(self, now):
        with self.Session.begin() as db:
            stuck = db.scalars(select(PlannedRun).where(PlannedRun.status == "running")).all()
            for run in stuck:
                run.status, run.finished_at = "unknown", now
                run.error = "the service stopped while this run was in progress; it may or may not be recorded"
                send_alert(db, self.box, run.user_id,
                           f"ePortem: {run.action} on {run.date} may or may not have been recorded (the service "
                           "stopped during it). Check Registro Jornada by hand.")
                log.warning("run %s was running at start-up: marked unknown", run.id)

    def _plan_all(self, now, alert_missed):
        with self.Session.begin() as db:
            for user in db.scalars(select(User)).all():
                today = self._local_date(user, now)
                if self._planned.get(user.id) == today:
                    continue
                _, _, missed = plan_day(db, user, today, now, self.settings.window_minutes, self.rng)
                self._planned[user.id] = today
                if alert_missed and missed:
                    names = ", ".join(r.action for r in missed)
                    send_alert(db, self.box, user.id, f"ePortem: {names} on {today} were not clocked: the "
                               "service was not running during their window. Check Registro Jornada.")

    def _dispatch(self, now):
        started = []
        with self.Session.begin() as db:
            due = db.scalars(select(PlannedRun).where(PlannedRun.status == "planned",
                                                      PlannedRun.planned_at <= now)).all()
            due_ids = [(r.id, r.user_id) for r in due]
        for run_id, user_id in due_ids:
            if not self._claim(run_id, user_id, now):
                continue
            started.append(run_id)
            if self.executor:
                self.executor.submit(self._execute, run_id)
            else:
                self._execute(run_id)
        return started

    def _claim(self, run_id, user_id, now):
        """planned -> running, unless the window closed (-> skipped). True if claimed."""
        with self.Session.begin() as db:
            run, user = db.get(PlannedRun, run_id), db.get(User, user_id)
            tz = zoneinfo.ZoneInfo(user.timezone)
            if now > window_end_utc(run, tz, self.settings.window_minutes):
                done = db.execute(update(PlannedRun).where(PlannedRun.id == run_id, PlannedRun.status == "planned")
                                  .values(status="skipped", finished_at=now,
                                          error="its window closed before it could start"))
                if done.rowcount:
                    send_alert(db, self.box, user_id, f"ePortem: {run.action} on {run.date} was not clocked: its "
                               "window closed before it could start. Check Registro Jornada.")
                return False
            done = db.execute(update(PlannedRun).where(PlannedRun.id == run_id, PlannedRun.status == "planned")
                              .values(status="running", started_at=now, attempt=PlannedRun.attempt + 1))
            return done.rowcount == 1

    def _execute(self, run_id):
        """Run one claimed action and store its outcome. Never raises."""
        status, error, via, output, outcome = "failed", None, None, "", ""
        try:
            with self.Session() as db:
                run = db.get(PlannedRun, run_id)
                user = db.get(User, run.user_id)
                plan = resolve(load_calendar(db, user), run.date)
                lines = []
                result = {}

                def say(*args, **kwargs):
                    lines.append(" ".join(str(a) for a in args))

                def record(action, location, how):
                    result["via"] = how

                def log_run(action, location, run_outcome, text):
                    result["outcome"], result["output"] = run_outcome, text

                if self.settings.dry_run:
                    status, via = "dry_run", None
                    outcome = f"dry run: would clock {run.action} ({run.location})"
                    output = outcome + "\n"
                else:
                    action = build_action(db, self.Session, self.box, self.engine, user, run, plan, say,
                                          record, log_run)
                    try:
                        action.perform()
                        status, via = "recorded", result.get("via")
                    except OutcomeUnknown as e:
                        status, error = "unknown", str(e)
                    except (NotRecorded, ActionNotApplicable) as e:
                        status, error = "not_recorded", f"{type(e).__name__}: {e}"
                    except Exception as e:
                        status, error = "failed", f"{type(e).__name__}: {e}"
                    outcome = result.get("outcome", status)
                    output = result.get("output", "\n".join(lines))
        except Exception as e:  # building the action failed: nothing was sent
            status, error = "not_recorded", f"{type(e).__name__}: {e}"
            outcome = output = error
        self._finish(run_id, status, via, error, outcome, output)

    def _finish(self, run_id, status, via, error, outcome, output):
        now = _naive_utc(datetime.datetime.now(datetime.UTC))
        with self.Session.begin() as db:
            run = db.get(PlannedRun, run_id)
            run.status, run.via, run.error, run.finished_at = status, via, error, now
            db.merge(RunLog(run_id=run_id, outcome=outcome or status, text=output or ""))
            if status in ("unknown", "not_recorded", "failed"):
                what = {"unknown": "may or may not have been recorded", "not_recorded": "was NOT recorded",
                        "failed": "FAILED"}[status]
                send_alert(db, self.box, run.user_id, f"ePortem: {run.action} on {run.date} {what}. "
                           f"{(error or '')[:200]} Check Registro Jornada.")

    def _verify_days(self, now):
        """After a person's last action + verify_after_minutes, check the day once."""
        with self.Session.begin() as db:
            for user in db.scalars(select(User)).all():
                today = self._local_date(user, now)
                runs = db.scalars(select(PlannedRun).where(PlannedRun.user_id == user.id,
                                                           PlannedRun.date == today)).all()
                active = [r for r in runs if r.status != "cancelled"]
                if not active or db.scalar(select(DayCheck.id).where(DayCheck.user_id == user.id,
                                                                     DayCheck.date == today)):
                    continue
                last = max(r.target_minute for r in active)
                tz = zoneinfo.ZoneInfo(user.timezone)
                local_now = now.replace(tzinfo=datetime.UTC).astimezone(tz)
                if local_now.hour * 60 + local_now.minute < last + self.settings.verify_after_minutes:
                    continue
                bad = [r for r in active if r.status not in ("recorded", "dry_run")]
                detail = ", ".join(f"{r.action} {r.status}" for r in bad)
                db.add(DayCheck(user_id=user.id, date=today, ok=not bad, detail=detail))
                if bad:
                    send_alert(db, self.box, user.id, f"ePortem day check {today}: {detail}. "
                               "Check Registro Jornada.")

    # --- running in the background --------------------------------------------
    def run_forever(self, interval_seconds=10):
        workers = ThreadPoolExecutor(max_workers=8, thread_name_prefix="eportem-run")
        self.executor = workers
        try:
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception:
                    log.exception("scheduler tick failed")
                self._stop.wait(interval_seconds)
        finally:
            workers.shutdown(wait=True)

    def stop(self):
        self._stop.set()


def describe_run(run):
    return f"{run.date} {run.action} at {format_minutes(run.target_minute)} ({run.location}): {run.status}"
