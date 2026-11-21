#!/usr/bin/env python3
"""Scheduler entrypoint called by cron (via run.sh).

Exit codes:
  0  clocked an action, or nothing to do (holiday, no schedule today, EPORTEM_ENABLED
     is not YES), or --check passed, or --verify-day found everything recorded
  2  config/config.json or holiday_override.txt is invalid: nothing was clocked
  3  today has a schedule but the current time is outside every action's window
  4  --verify-day: a scheduled action was not recorded today, or was recorded twice

A failed run (exit 2, 3 or an exception) also sends a short alert on the
notification channels, on top of the cron mail.
"""
import argparse
import datetime
import json
import os
import sys

from checkin.core import schedule as core_schedule
from checkin.core.overrides import (
    OverrideFormatError,
    parse_date_range,
    parse_location_override,
    range_state,
)
from checkin.core.schedule import LOCATIONS, TASK_ACTIONS  # noqa: F401  (re-exported for tests)
from eportem_action import execute_action
from utility import alerts
from utility.action_log import actions_recorded_on
from utility.env_check import DISABLED_MESSAGE, is_enabled
from utility.env_loader import load_environment
from utility.paths import config_file, holiday_file, location_file

load_environment()

EXIT_OK = 0
EXIT_INVALID = 2
EXIT_NO_ACTION = 3
EXIT_UNVERIFIED = 4

# An action fires when the current time is within this many minutes of its target
WINDOW_MINUTES = 15
# --verify-day only judges an action once its window closed plus this much, which
# covers the Selenium retry budget (RETRY_BUDGET_SECONDS in eportem_action.py,
# 10 min) so a slow but successful run is not reported as missed.
VERIFY_GRACE_MINUTES = 15

HOLIDAY_STATUS_TEXT = "On holiday"
HOLIDAY_STATUS_EMOJI = ":palm_tree:"


class HolidayFileError(Exception):
    pass


class ConfigError(Exception):
    def __init__(self, problems):
        super().__init__("; ".join(problems))
        self.problems = problems


def _now():
    # One place to ask for the time, so tests can pin it
    return datetime.datetime.now()


def _remove_quietly(path):
    """Delete a stale override file; a second overlapping run may have beaten us to it."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _read_text(path):
    # utf-8-sig drops a BOM that some editors add
    with open(path, encoding="utf-8-sig") as f:
        return f.read().strip()


def read_holiday_file():
    """Return (start, end) from holiday_override.txt, or None when there is no
    file or it is empty. Raises HolidayFileError for anything that can't be
    understood: a holiday we can't read must not turn into a clocked-in day."""
    path = holiday_file()
    if not os.path.exists(path):
        return None
    try:
        text = _read_text(path)
    except (OSError, UnicodeDecodeError) as e:
        raise HolidayFileError(f"cannot read it ({e})") from e
    if not text:
        return None
    try:
        return parse_date_range(text)
    except OverrideFormatError as e:
        raise HolidayFileError(str(e)) from e

def get_today_holiday(remove_stale=True):
    """Return {"start", "end"} if today falls within the range set via
    holiday_override.py, else None. Raises HolidayFileError if the file exists
    but can't be parsed (it is never deleted automatically)."""
    parsed = read_holiday_file()
    if parsed is None:
        return None
    start_date, end_date = parsed

    state = range_state(start_date, end_date, _now().date())
    if state == "past":
        if remove_stale:
            _remove_quietly(holiday_file())  # every date in the range has passed
        return None
    if state == "active":
        return {"start": start_date, "end": end_date}
    return None

def is_holiday():
    """Check whether today falls within a holiday range set via holiday_override.py"""
    return get_today_holiday() is not None

def update_holiday_slack_status(holiday):
    """Set the Slack status for today's holiday, if SLACK_STATUS is enabled.
    Safe to call on every run - it's just an idempotent status update, not a
    one-time notification."""
    if os.getenv('SLACK_STATUS', 'NO') != 'YES':
        return

    expiration = int(datetime.datetime.combine(holiday["end"], datetime.time(23, 59)).timestamp())

    from utility.slack_status import SlackStatusUpdater
    try:
        SlackStatusUpdater().set_status(HOLIDAY_STATUS_TEXT, HOLIDAY_STATUS_EMOJI, expiration)
    except ValueError:
        # No token: the holiday is still honoured, only the status is skipped
        print("Slack status skipped: SLACK_TOKEN is not configured.")


_parse_time = core_schedule.parse_time
validate_config = core_schedule.validate_week_schedule


def load_config():
    """Read and validate config/config.json (once per run). Raises ConfigError
    listing every problem found."""
    path = config_file()
    try:
        with open(path, encoding="utf-8-sig") as f:
            config = json.load(f)
    except FileNotFoundError as e:
        raise ConfigError([f"file not found: {path}"]) from e
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError([f"cannot read {path}: {e}"]) from e
    except json.JSONDecodeError as e:
        raise ConfigError([f"not valid JSON: line {e.lineno}, column {e.colno}: {e.msg}"]) from e
    problems = validate_config(config)
    if problems:
        raise ConfigError(problems)
    return config


def _read_location_override(remove_stale=True):
    """Return today's override location ('home'/'office') or None. A malformed
    file is reported and ignored (the config location applies)."""
    path = location_file()
    if not os.path.exists(path):
        return None
    try:
        location, override_date = parse_location_override(_read_text(path))
    except (ValueError, OSError, UnicodeDecodeError) as e:
        print(f"Ignoring invalid location override file {path} ({e}); using the "
              f"location from config. Delete it or re-run override_location.py.",
              file=sys.stderr)
        return None
    today = _now().date()
    if override_date == today:
        return location
    if override_date < today and remove_stale:
        _remove_quietly(path)  # the day has passed
    return None


def determine_location(config, remove_stale=True):
    """Determine the current location (from override file or config)"""
    override = _read_location_override(remove_stale)
    if override:
        return override
    schedule = core_schedule.day_for(config, _now().weekday())
    if schedule:
        return schedule.get("location", "office")
    return "office"  # Default to office if not specified


_fmt = core_schedule.format_minutes
_targets = core_schedule.day_targets


def _report_no_action(now, day, stream):
    lines = [f"No action matches the current time ({now:%H:%M}). Today's targets and windows "
             f"(+/-{WINDOW_MINUTES} min):"]
    for name, target in _targets(day):
        low, high = core_schedule.window_bounds(target, WINDOW_MINUTES)
        lines.append(f"  {name}: {_fmt(target)} (window {_fmt(low)}-{_fmt(high)})")
    lines.append("If cron started this run, the crontab entry's time (base time + maximum "
                 "random sleep) is outside the window: fix the crontab.")
    print("\n".join(lines), file=stream)


def _join_names(names):
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _verify_day(config, now, location):
    """Compare today's scheduled actions whose window has closed with what
    logs/actions.log recorded. Returns EXIT_OK or EXIT_UNVERIFIED."""
    day = core_schedule.day_for(config, now.weekday())
    if not day:
        print("No schedule for today; nothing to verify.")
        return EXIT_OK
    minutes = now.hour * 60 + now.minute
    due = core_schedule.actions_due_for_verify(day, minutes, WINDOW_MINUTES, VERIFY_GRACE_MINUTES)
    if not due:
        print("No scheduled action is past its window yet; nothing to verify.")
        return EXIT_OK
    recorded = actions_recorded_on(now.date())
    missing = [a for a in due if recorded.count(a) == 0]
    doubled = [a for a in due if recorded.count(a) > 1]
    if not missing and not doubled:
        print(f"Day check OK: {_join_names(due)} recorded today ({location}).")
        return EXIT_OK
    parts = []
    if missing:
        parts.append(f"today's {_join_names(missing)} {'was' if len(missing) == 1 else 'were'} not recorded.")
    if doubled:
        parts.append(f"today's {_join_names(doubled)} {'was' if len(doubled) == 1 else 'were'} "
                     "recorded twice (possible double clock-in).")
    text = "ePortem: " + " ".join(parts) + " Check Registro Jornada."
    print(text, file=sys.stderr)
    print(f"Scheduled and due: {', '.join(due)}. Recorded today: "
          f"{', '.join(recorded) or 'nothing'}.", file=sys.stderr)
    alerts.send_alert(text)
    return EXIT_UNVERIFIED


def _run(args, ctx):
    """The body of main(). ctx collects what a failure alert needs to say."""
    # Validate everything first and report every problem, so a typo shows up in the cron mail
    problems = []
    config = None
    try:
        config = load_config()
    except ConfigError as e:
        problems.extend(f"{config_file()}: {p}" for p in e.problems)
    holiday = None
    try:
        holiday = get_today_holiday(remove_stale=not (args.check or args.verify_day))
    except HolidayFileError as e:
        problems.append(f"{holiday_file()}: {e}. Refusing to clock because today may be a "
                        f"holiday: fix the file, or delete it, or re-run holiday_override.py.")
    if problems:
        print("Nothing was clocked: invalid configuration.", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        more = f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""
        ctx["reason"] = f"invalid configuration: {problems[0]}{more}"
        return EXIT_INVALID

    if holiday:
        print("On holiday today - skipping check-in." if not args.verify_day
              else "On holiday today; nothing to verify.")
        if not (args.check or args.verify_day):
            update_holiday_slack_status(holiday)
        return EXIT_OK

    now = _now()
    if args.verify_day:
        return _verify_day(config, now, determine_location(config, remove_stale=False))
    day = core_schedule.day_for(config, now.weekday())
    if not day:
        print("No schedule for today.")
        return EXIT_OK

    location = determine_location(config, remove_stale=not args.check)
    minutes = now.hour * 60 + now.minute
    match = core_schedule.due_task(day, minutes, WINDOW_MINUTES)
    if match:
        task, target = match
        action = TASK_ACTIONS[task]
        if args.check:
            print(f"Config OK. Would run {action} ({location}) now ({now:%H:%M}); "
                  f"{task} is scheduled for {_fmt(target)}.")
            return EXIT_OK
        ctx["action"] = action
        execute_action(action, location)
        return EXIT_OK

    if args.check:
        print(f"Config OK. No action would run now ({now:%H:%M}); location would be {location}.")
        _report_no_action(now, day, sys.stdout)
        return EXIT_OK
    _report_no_action(now, day, sys.stderr)
    ctx["reason"] = f"the time {now:%H:%M} is outside every scheduled action's window"
    return EXIT_NO_ACTION


def _alert_failure(ctx, reason):
    """Tell the notification channels that this run failed. Never raises."""
    try:
        alerts.send_alert(alerts.failure_text(ctx.get("action"), _now(), reason))
    except Exception as e:
        print(f"Failure alert not sent: {e}", file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Clock the action scheduled for the current time (called by cron).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="Validate config/overrides and show which action would run now "
                           "and where, without clocking. Exits 0 unless validation fails.")
    mode.add_argument("--verify-day", action="store_true",
                      help="Compare today's scheduled actions (whose window has closed) with "
                           "logs/actions.log; alert and exit 4 if one is missing or doubled.")
    args = parser.parse_args(argv)

    # Quiet off switch: not a failure, so no mail and no alert. --check still
    # validates (it clocks nothing), with a note.
    if not is_enabled():
        if not args.check:
            print(DISABLED_MESSAGE)
            return EXIT_OK
        print("Note: " + DISABLED_MESSAGE.replace("; nothing done.", "; a real run would do nothing."))

    ctx = {"action": "verify-day" if args.verify_day else None}
    try:
        code = _run(args, ctx)
    except Exception as e:
        # The traceback still goes to cron (exit 1 as before); the alert is only a summary
        if not args.check:
            _alert_failure(ctx, alerts.describe_exception(e))
        raise
    if code in (EXIT_INVALID, EXIT_NO_ACTION) and not args.check:
        _alert_failure(ctx, ctx.get("reason", f"exit code {code}"))
    return code


if __name__ == "__main__":
    # Only for a real run, never on import (tests): every line gets HH:MM:SS
    from utility.timestamps import install
    install()
    sys.exit(main())
