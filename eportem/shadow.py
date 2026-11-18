"""Compare the service in shadow mode (EPORTEM_DRY_RUN) with the cron scripts
(docs/refactor/PLAN.md phase 8): for each day, what cron recorded in
logs/actions.log next to what the service planned.

    python -m eportem shadow-report --user NAME --actions-log /legacy/logs/actions.log [--days 7]

A day matches when both have the same actions, at the same location, and every
planned time is inside the action's window. Exit 0 when every day matches.
"""
import datetime
import zoneinfo

from sqlalchemy import select

from eportem.core.schedule import format_minutes
from eportem.db.models import PlannedRun, User

DONE = ("recorded", "dry_run")


def read_actions_log(path):
    """{date: {action: (local datetime, location)}} from logs/actions.log and its
    rotated copies (the last line wins if an action was recorded twice)."""
    from pathlib import Path
    out = {}
    for p in [Path(f"{path}.{i}") for i in range(9, 0, -1)] + [Path(path)]:
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            try:
                ts = datetime.datetime.fromisoformat(parts[0])
            except ValueError:
                continue
            out.setdefault(ts.date(), {})[parts[2]] = (ts, parts[3])
    return out


def compare(db, username, actions_log, days, window_minutes, today=None):
    """[(date, ok, [lines])], oldest first."""
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise ValueError(f"no user {username}")
    tz = zoneinfo.ZoneInfo(user.timezone)
    today = today or datetime.datetime.now(tz).date()
    cron = read_actions_log(actions_log)
    report = []
    for i in range(days - 1, -1, -1):
        date = today - datetime.timedelta(days=i)
        runs = {r.action: r for r in db.scalars(select(PlannedRun).where(
            PlannedRun.user_id == user.id, PlannedRun.date == date, PlannedRun.status != "cancelled"))}
        done = cron.get(date, {})
        if not runs and not done:
            continue
        lines, ok = [], True
        for action in ("start_day", "lunch_break", "after_lunch", "stop_day"):
            run, rec = runs.get(action), done.get(action)
            if run is None and rec is None:
                continue
            shadow = "—"
            if run is not None:
                at = run.planned_at.replace(tzinfo=datetime.UTC).astimezone(tz)
                shadow = f"{at:%H:%M} {run.location} {run.status}"
            legacy = f"{rec[0]:%H:%M} {rec[1]}" if rec else "—"
            problems = []
            if run is None:
                problems.append("not planned by the service")
            elif rec is None:
                problems.append("cron did not record it")
            if run is not None and rec is not None and run.location != rec[1]:
                problems.append("different location")
            if run is not None:
                at = run.planned_at.replace(tzinfo=datetime.UTC).astimezone(tz)
                if abs(at.hour * 60 + at.minute - run.target_minute) > window_minutes:
                    problems.append("outside its window")
                if run.status not in DONE and run.status != "planned":
                    problems.append(f"status {run.status}")
            ok = ok and not problems
            lines.append(f"  {action:<12} target {format_minutes(run.target_minute) if run else '--:--'}  "
                         f"cron {legacy:<16} service {shadow:<26} {'; '.join(problems) or 'ok'}")
        report.append((date, ok, lines))
    return report
