"""Working-day templates: named working weeks people pick from a list.

A template gives, for each weekday (0 = Monday), the day's times or nothing
(a day off). A day either has a lunch break (out and back) or runs straight
through. Built-in templates are read-only; a user customises a copy.
Times are minutes since midnight; `parse_template`/`template_to_dict` convert
to and from the JSON stored in the database ("9:00" strings).
"""
from dataclasses import dataclass, field

from checkin.core.schedule import format_minutes, parse_time

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True)
class DayTimes:
    start: int
    stop: int
    lunch_out: int | None = None
    lunch_back: int | None = None

    @property
    def has_lunch(self):
        return self.lunch_out is not None

    def actions(self):
        """[(action, minutes)] in the order they happen."""
        out = [("start_day", self.start)]
        if self.has_lunch:
            out += [("lunch_break", self.lunch_out), ("after_lunch", self.lunch_back)]
        return out + [("stop_day", self.stop)]

    def problems(self):
        if (self.lunch_out is None) != (self.lunch_back is None):
            return ["a lunch break needs both an out and a back time"]
        times = [t for _, t in self.actions()]
        if any(b <= a for a, b in zip(times, times[1:], strict=False)):
            return ["times must be in order: start, lunch out, lunch back, stop"]
        return []

    def describe(self):
        if self.has_lunch:
            return (f"{format_minutes(self.start)}–{format_minutes(self.stop)}, lunch "
                    f"{format_minutes(self.lunch_out)}–{format_minutes(self.lunch_back)}")
        return f"{format_minutes(self.start)}–{format_minutes(self.stop)}, no lunch break"


@dataclass(frozen=True)
class Template:
    key: str
    name: str
    days: dict = field(default_factory=dict)  # weekday -> DayTimes (missing = day off)
    description: str = ""
    builtin: bool = False

    def day(self, weekday):
        return self.days.get(weekday)


def _t(text):
    return parse_time(text)


def _day(start, stop, lunch_out=None, lunch_back=None):
    return DayTimes(_t(start), _t(stop), _t(lunch_out) if lunch_out else None,
                    _t(lunch_back) if lunch_back else None)


def _weekdays(day, friday=None):
    return {d: (friday if d == 4 and friday else day) for d in range(5)}


_EUROPEAN = _day("9:00", "18:00", "13:30", "14:30")
_SPANISH = _day("9:00", "18:00", "14:30", "15:30")

BUILTIN_TEMPLATES = {t.key: t for t in (
    Template("european-9-18", "European day, 9–18", _weekdays(_EUROPEAN),
             "9:00 to 18:00 with lunch 13:30–14:30, Monday to Friday", True),
    Template("spanish-9-18", "Spanish day, 9–18", _weekdays(_SPANISH),
             "9:00 to 18:00 with lunch 14:30–15:30, Monday to Friday", True),
    Template("spanish-friday-short", "Spanish day, short Friday",
             _weekdays(_SPANISH, friday=_day("8:00", "15:00")),
             "Monday to Thursday 9:00 to 18:00 with lunch 14:30–15:30; Friday 8:00 to 15:00", True),
    Template("summer-8-15", "Summer hours (jornada intensiva)", _weekdays(_day("8:00", "15:00")),
             "8:00 to 15:00 with no lunch break, Monday to Friday", True),
    Template("continuous-8-16", "Continuous day", _weekdays(_day("8:00", "16:00")),
             "8:00 to 16:00 with no lunch break, Monday to Friday", True),
    Template("part-time-morning", "Part-time mornings", _weekdays(_day("9:00", "14:00")),
             "9:00 to 14:00, Monday to Friday", True),
)}


class TemplateError(ValueError):
    def __init__(self, problems):
        super().__init__("; ".join(problems))
        self.problems = problems


def parse_template(data, key=None, name=None):
    """A Template from {"key", "name", "description", "days": {"0": {"start": "9:00",
    "stop": "18:00", "lunch_out": "13:30", "lunch_back": "14:30"}, ...}}.
    Raises TemplateError listing every problem."""
    problems = []
    days = {}
    raw_days = data.get("days")
    if not isinstance(raw_days, dict):
        raise TemplateError(['"days" must be an object keyed by weekday "0".."6"'])
    for wd, raw in raw_days.items():
        where = f'days["{wd}"]'
        if wd not in {str(i) for i in range(7)}:
            problems.append(f'{where}: weekday must be "0" (Monday) to "6" (Sunday)')
            continue
        if raw is None:
            continue  # explicit day off
        if not isinstance(raw, dict):
            problems.append(f"{where}: must be an object or null")
            continue
        unknown = set(raw) - {"start", "stop", "lunch_out", "lunch_back"}
        if unknown:
            problems.append(f"{where}: unknown keys {sorted(unknown)}")
        values = {}
        for k in ("start", "stop", "lunch_out", "lunch_back"):
            v = raw.get(k)
            if v in (None, ""):
                if k in ("start", "stop"):
                    problems.append(f'{where}["{k}"]: required')
                continue
            m = parse_time(v)
            if m is None:
                problems.append(f'{where}["{k}"]: must be a time like "9:00", got {v!r}')
            values[k] = m
        if not any(p.startswith(where) for p in problems):
            day = DayTimes(values["start"], values["stop"], values.get("lunch_out"), values.get("lunch_back"))
            problems += [f"{where}: {p}" for p in day.problems()]
            days[int(wd)] = day
    key = key or data.get("key") or ""
    name = name or data.get("name") or ""
    if not key:
        problems.append('"key" is required')
    if not name:
        problems.append('"name" is required')
    if problems:
        raise TemplateError(problems)
    return Template(key, name, days, data.get("description", ""))


def template_to_dict(template):
    def day(d):
        out = {"start": format_minutes(d.start), "stop": format_minutes(d.stop)}
        if d.has_lunch:
            out.update(lunch_out=format_minutes(d.lunch_out), lunch_back=format_minutes(d.lunch_back))
        return out
    return {"key": template.key, "name": template.name, "description": template.description,
            "days": {str(wd): day(d) for wd, d in sorted(template.days.items())}}


def matching_builtin(template):
    """The built-in template with exactly these days, or None."""
    for t in BUILTIN_TEMPLATES.values():
        if t.days == template.days:
            return t
    return None
