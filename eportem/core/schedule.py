"""Clock actions, times of day and the weekly schedule format.

The weekly format is the one `config/config.json` has always used:
{"schedule": {"0": {"location": "office", "start_the_day": "9:00", ...}}},
weekday "0" = Monday. Times are kept as minutes since midnight.
"""
import re

ACTIONS = ("start_day", "lunch_break", "after_lunch", "stop_day")
LOCATIONS = ("home", "office")

# Schedule key -> action name
TASK_ACTIONS = {
    "start_the_day": "start_day",
    "lunch_break": "lunch_break",
    "after_lunch_break": "after_lunch",
    "stop_the_day": "stop_day",
}

MINUTES_PER_DAY = 24 * 60
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_time(value):
    """Return minutes since midnight for 'H:MM'/'HH:MM', else None."""
    m = _TIME_RE.match(value) if isinstance(value, str) else None
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def format_minutes(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def validate_week_schedule(config):
    """Return a list of human-readable problems (empty if the config is fine)."""
    problems = []
    if not isinstance(config, dict) or "schedule" not in config:
        return ['top level must be an object with a "schedule" key']
    schedule = config["schedule"]
    if not isinstance(schedule, dict):
        return ['"schedule" must be an object keyed by weekday "0".."6"']
    for key, day in schedule.items():
        where = f'schedule["{key}"]'
        if key not in {str(i) for i in range(7)}:
            problems.append(f'{where}: weekday key must be "0" (Monday) to "6" (Sunday)')
        if not isinstance(day, dict):
            problems.append(f"{where}: must be an object")
            continue
        for name, value in day.items():
            if name == "day":
                if not isinstance(value, str):
                    problems.append(f'{where}["day"]: must be a string')
            elif name == "location":
                if value not in LOCATIONS:
                    problems.append(f'{where}["location"]: must be "home" or "office", got {value!r}')
            elif name in TASK_ACTIONS:
                if parse_time(value) is None:
                    problems.append(f'{where}["{name}"]: must be a time like "9:00" or "13:30" '
                                    f'(00:00-23:59), got {value!r}')
            else:
                problems.append(f'{where}: unknown key "{name}" (allowed: day, location, {", ".join(TASK_ACTIONS)})')
    return problems


def day_for(config, weekday):
    """The schedule entry for weekday (0 = Monday), or None."""
    return config["schedule"].get(str(weekday))


def day_targets(day):
    """[(schedule key, minutes since midnight)] in the order of the entry."""
    return [(name, parse_time(day[name])) for name in day if name in TASK_ACTIONS]


def window_bounds(target, window_minutes):
    """The first and last minute of the window around target, clamped to the day."""
    return max(target - window_minutes, 0), min(target + window_minutes, MINUTES_PER_DAY - 1)


def due_task(day, minutes, window_minutes):
    """(schedule key, target) of the first action whose window contains `minutes`,
    or None. If two windows overlap, the first one in the entry wins."""
    for task, target in day_targets(day):
        if abs(minutes - target) <= window_minutes:
            return task, target
    return None


def jitter_problems(before, after, window_minutes):
    """Why a random offset of `before` minutes early to `after` minutes late
    isn't allowed with this window (empty when it is). Each person sets their
    own; the window is the instance's safety rule: an action never runs
    outside it, and above all never late."""
    problems = []
    for label, value in (("before", before), ("after", after)):
        if not isinstance(value, int) or value < 0:
            problems.append(f"the random offset {label} must be 0 or more minutes")
        elif value > window_minutes:
            problems.append(f"the random offset {label} ({value} min) must not be larger than "
                            f"the {window_minutes}-minute window")
    return problems


def actions_due_for_verify(day, minutes, window_minutes, grace_minutes):
    """The actions whose window closed at least grace_minutes before `minutes`."""
    return [TASK_ACTIONS[name] for name, target in day_targets(day)
            if minutes >= target + window_minutes + grace_minutes]
