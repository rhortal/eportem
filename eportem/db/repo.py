"""Between the database and the engine: build core objects from rows, and the
database-backed session store."""
import datetime

from sqlalchemy import select

from eportem.core.activities import ActivityIds
from eportem.core.calendar import DayChange, LocationPattern, Period, UserCalendar
from eportem.core.schedule import parse_time
from eportem.core.templates import BUILTIN_TEMPLATES, DayTimes, parse_template
from eportem.db.models import (
    DayChangeRow,
    EportemSession,
    LocalHoliday,
    SchedulePeriod,
    ScheduleTemplate,
    User,
    UserSchedule,
)


def new_user(settings, username, **fields):
    """A User with the instance's defaults for the per-person settings."""
    defaults = dict(timezone=settings.default_timezone, locale=settings.default_locale,
                    jitter_before_minutes=settings.default_jitter_before_minutes,
                    jitter_after_minutes=settings.default_jitter_after_minutes)
    return User(username=username, **{**defaults, **fields})


class DbCookieStore:
    """A person's ePortem session, encrypted in eportem_sessions. Each load and
    save uses its own short database session, so a slow clock run never holds
    a transaction open."""

    def __init__(self, sessionmaker, user_id, box):
        self.sessionmaker, self.user_id, self.box = sessionmaker, user_id, box

    def describe(self):
        return "the saved session"

    def load(self):
        with self.sessionmaker() as db:
            row = db.get(EportemSession, self.user_id)
            return self.box.decrypt_json(row.data_enc) if row else None

    def save(self, data):
        with self.sessionmaker.begin() as db:
            row = db.get(EportemSession, self.user_id)
            if row is None:
                db.add(EportemSession(user_id=self.user_id, data_enc=self.box.encrypt_json(data)))
            else:
                row.data_enc = self.box.encrypt_json(data)


def activity_ids(account):
    """The account's ActivityIds, or None until they are known (verification
    finds them on the dashboard)."""
    if not (account and account.office_activity_id and account.home_activity_id and account.lunch_pause_id):
        return None
    return ActivityIds(account.office_activity_id, account.home_activity_id, account.lunch_pause_id)


def templates_for(db, user_id):
    """Built-in templates plus this person's own, by key."""
    found = dict(BUILTIN_TEMPLATES)
    for row in db.scalars(select(ScheduleTemplate).where(ScheduleTemplate.user_id == user_id)):
        found[row.key] = parse_template({"days": row.days}, key=row.key, name=row.name)
    return found


def _times(data):
    if not data:
        return None
    lunch_out, lunch_back = data.get("lunch_out"), data.get("lunch_back")
    return DayTimes(parse_time(data["start"]), parse_time(data["stop"]),
                    parse_time(lunch_out) if lunch_out else None, parse_time(lunch_back) if lunch_back else None)


def load_calendar(db, user):
    """The person's UserCalendar from their rows."""
    templates = templates_for(db, user.id)
    sched = db.get(UserSchedule, user.id)
    default = templates.get(sched.template_key if sched else "", BUILTIN_TEMPLATES["european-9-18"])
    weeks = tuple({int(k): v for k, v in w.items()} for w in (sched.location_weeks if sched else [])) or ({},)
    pattern = LocationPattern(weeks, sched.pattern_anchor if sched else None)
    periods = tuple(
        Period(templates[p.template_key], p.start_date, p.end_date, p.yearly, p.label)
        for p in db.scalars(select(SchedulePeriod).where(SchedulePeriod.user_id == user.id)
                            .order_by(SchedulePeriod.id))
        if p.template_key in templates)
    changes = tuple(
        DayChange(c.kind, c.start_date, c.end_date, c.location, _times(c.times), c.note)
        for c in db.scalars(select(DayChangeRow).where(DayChangeRow.user_id == user.id).order_by(DayChangeRow.id)))
    local = {h.date: h.name for h in db.scalars(select(LocalHoliday).where(LocalHoliday.user_id == user.id))}
    return UserCalendar(default, pattern, periods, changes,
                        holiday_country=sched.holiday_country if sched else None,
                        holiday_region=sched.holiday_region if sched else None,
                        local_holidays=local, paused=user.paused, active=user.status == "active")


def local_today(user, now=None):
    import zoneinfo
    now = now or datetime.datetime.now(datetime.UTC)
    return now.astimezone(zoneinfo.ZoneInfo(user.timezone)).date()
