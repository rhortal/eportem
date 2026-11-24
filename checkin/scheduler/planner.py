"""Write a person's runs for a date from their calendar (docs/refactor/PLAN.md,
phase 4). Planning is idempotent: it adds missing runs, moves runs that haven't
started when the plan changed, and cancels runs the plan no longer has."""
import datetime
import random
import zoneinfo

from sqlalchemy import select

from checkin.core.calendar import resolve
from checkin.db.models import PlannedRun
from checkin.db.repo import load_calendar

OPEN = ("planned",)


def _utc(local_date, minutes, seconds, tz):
    local = datetime.datetime.combine(local_date, datetime.time()) + datetime.timedelta(
        minutes=minutes, seconds=seconds)
    return local.replace(tzinfo=tz).astimezone(datetime.UTC).replace(tzinfo=None)


def window_end_utc(run, tz, window_minutes):
    return _utc(run.date, run.target_minute + window_minutes, 59, tz)


# The day's edges never fall inside the working day (D-026): the clock-in goes
# only before the template's start, the clock-out only after its stop. Both
# spread over the person's whole offset (before + after), capped by the window.
EDGE_MARGIN_SECONDS = 30


def offset_range(action, user, window_minutes):
    """(lowest, highest) offset in seconds from the action's time."""
    before, after = user.jitter_before_minutes * 60, user.jitter_after_minutes * 60
    spread = min(max(before + after, 60), window_minutes * 60)
    if action == "start_day":
        return -spread, -EDGE_MARGIN_SECONDS
    if action == "stop_day":
        return EDGE_MARGIN_SECONDS, spread
    return -before, after


def _fits(run, tz, window_minutes, user):
    low, high = offset_range(run.action, user, window_minutes)
    offset = (run.planned_at - _utc(run.date, run.target_minute, 0, tz)).total_seconds()
    return low <= offset <= high


def plan_day(db, user, date, now_utc, window_minutes, rng=None):
    """Plan `date` for `user`. Returns (plan, [new or moved runs], [runs whose
    window already closed, now skipped]). Never plans a run outside its window:
    a run that can't start in time is created as `skipped` so it is reported."""
    rng = rng or random.Random()  # noqa: S311 (spreading start times, not security)
    tz = zoneinfo.ZoneInfo(user.timezone)
    plan = resolve(load_calendar(db, user), date)
    existing = {r.action: r for r in db.scalars(select(PlannedRun).where(
        PlannedRun.user_id == user.id, PlannedRun.date == date))}
    wanted = dict(plan.actions())
    changed, missed = [], []

    for action, run in existing.items():
        if run.status in OPEN and action not in wanted:
            run.status, run.error = "cancelled", f"no longer planned: {plan.reason}"
            changed.append(run)

    for action, target in plan.actions():
        run = existing.get(action)
        if run is not None and run.status not in OPEN:
            continue  # already done, running, or reported: never touched
        same = (run is not None and run.target_minute == target and run.location == plan.location
                and _fits(run, tz, window_minutes, user))
        if same:
            continue
        offset = rng.randint(*offset_range(action, user, window_minutes))
        planned_at = _utc(date, target, offset, tz)
        if run is None:
            run = PlannedRun(user_id=user.id, date=date, action=action)
            db.add(run)
        run.target_minute, run.location, run.planned_at, run.status, run.error = (
            target, plan.location, planned_at, "planned", None)
        if planned_at < now_utc:
            # Replanned (or started) late: go now if the window is still open.
            if now_utc <= window_end_utc(run, tz, window_minutes):
                run.planned_at = now_utc
            else:
                run.status, run.error = "skipped", "its window had already closed when it was planned"
                missed.append(run)
                continue
        changed.append(run)
    db.flush()
    return plan, changed, missed
