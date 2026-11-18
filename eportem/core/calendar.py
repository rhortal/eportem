"""What happens on a given date for a user: one pure function, `resolve`.

The UI preview, the API, the planner and the end-of-day check all call it, so
they can't disagree (docs/refactor/PLAN.md section 5, decision D-011). Order,
first match wins:

1. Paused (or the account isn't active)            -> nothing
2. A time-off range covering the date              -> nothing ("On holiday")
3. A public holiday (region or local list)         -> nothing, unless a
   work-on-holiday or a `times` change covers the date (setting hours for a
   date is an explicit choice to work it)
4. Times: a one-day `times` change, else the template of a period covering
   the date, else the default template (no entry for that weekday = day off)
5. Location: a `location` or `business_trip` change, else the weekly pattern,
   else office
"""
import datetime
from dataclasses import dataclass, field
from functools import lru_cache

from eportem.core.templates import WEEKDAYS, DayTimes, Template

OVERRIDE_KINDS = ("time_off", "location", "business_trip", "times", "work_on_holiday")


@dataclass(frozen=True)
class LocationPattern:
    """home/office per weekday. With two weeks, they alternate: week A is the one
    containing `anchor` (any date in it), week B the next, and so on."""
    weeks: tuple = ({},)
    anchor: datetime.date | None = None

    def location_for(self, date):
        week = self.weeks[0]
        if len(self.weeks) == 2 and self.anchor is not None:
            monday = date - datetime.timedelta(days=date.weekday())
            anchor_monday = self.anchor - datetime.timedelta(days=self.anchor.weekday())
            week = self.weeks[((monday - anchor_monday).days // 7) % 2]
        return week.get(date.weekday())


@dataclass(frozen=True)
class Period:
    """Use `template` from `start` to `end` (inclusive). Yearly periods repeat
    on the same days every year and may wrap the new year (15 Dec–10 Jan)."""
    template: Template
    start: datetime.date
    end: datetime.date
    yearly: bool = False
    label: str = ""

    def covers(self, date):
        if not self.yearly:
            return self.start <= date <= self.end
        md, s, e = (date.month, date.day), (self.start.month, self.start.day), (self.end.month, self.end.day)
        return s <= md <= e if s <= e else (md >= s or md <= e)


@dataclass(frozen=True)
class DayChange:
    """A change for a date range: kind is one of OVERRIDE_KINDS."""
    kind: str
    start: datetime.date
    end: datetime.date
    location: str | None = None
    times: DayTimes | None = None
    note: str = ""

    def covers(self, date):
        return self.start <= date <= self.end


def regional_holidays(country, region, year):
    """{date: name} of public holidays, from the `holidays` package (imported
    only when used, so the legacy cron scripts don't need it)."""
    return dict(_regional_holidays(country, region, year))


@lru_cache(maxsize=64)
def _regional_holidays(country, region, year):
    import holidays
    return tuple(holidays.country_holidays(country, subdiv=region, years=year).items())


@dataclass(frozen=True)
class UserCalendar:
    default_template: Template
    location_pattern: LocationPattern = field(default_factory=LocationPattern)
    periods: tuple = ()
    changes: tuple = ()
    holiday_country: str | None = None
    holiday_region: str | None = None
    local_holidays: dict = field(default_factory=dict)  # date -> name
    paused: bool = False
    active: bool = True
    holiday_lookup: object = regional_holidays  # (country, region, year) -> {date: name}

    def public_holiday(self, date):
        if date in self.local_holidays:
            return self.local_holidays[date]
        if self.holiday_country:
            return self.holiday_lookup(self.holiday_country, self.holiday_region, date.year).get(date)
        return None


@dataclass(frozen=True)
class DayPlan:
    date: datetime.date
    works: bool
    reason: str                     # why nothing happens, or where the times came from
    times: DayTimes | None = None
    location: str | None = None
    location_source: str = ""
    business_trip_end: datetime.date | None = None
    on_time_off: bool = False        # for the "On holiday" Slack status
    template_key: str | None = None

    def actions(self):
        return self.times.actions() if self.works else []


def _last(changes, kind, date):
    """The most recently added change of this kind covering the date."""
    found = None
    for c in changes:
        if c.kind == kind and c.covers(date):
            found = c
    return found


def resolve(cal, date):
    """The plan for one date (see the module docstring for the order)."""
    if not cal.active:
        return DayPlan(date, False, "account not active")
    if cal.paused:
        return DayPlan(date, False, "paused")
    off = _last(cal.changes, "time_off", date)
    if off:
        return DayPlan(date, False, "time off" + (f": {off.note}" if off.note else ""), on_time_off=True)
    holiday = cal.public_holiday(date)
    if holiday and not (_last(cal.changes, "work_on_holiday", date) or _last(cal.changes, "times", date)):
        return DayPlan(date, False, f"public holiday: {holiday}")

    times_change = _last(cal.changes, "times", date)
    period = next((p for p in reversed(cal.periods) if p.covers(date)), None)
    template = period.template if period else cal.default_template
    if times_change and times_change.times:
        times, reason = times_change.times, "changed times for this day"
    else:
        times = template.day(date.weekday())
        reason = f"{template.name}" + (f" ({period.label or 'period'})" if period else "")
        if times is None:
            return DayPlan(date, False, f"{WEEKDAYS[date.weekday()]} is not a working day in {template.name}",
                           template_key=template.key)

    trip = _last(cal.changes, "business_trip", date)
    place = _last(cal.changes, "location", date)
    if place and place.location:
        location, source = place.location, "changed for this day"
    elif trip and trip.location:
        location, source = trip.location, "business trip"
    else:
        location = cal.location_pattern.location_for(date)
        source = "weekly pattern" if location else "default"
        location = location or "office"
    return DayPlan(date, True, reason, times, location, source,
                   business_trip_end=trip.end if trip else None, template_key=template.key)


def resolve_range(cal, start, days):
    return [resolve(cal, start + datetime.timedelta(days=i)) for i in range(days)]
