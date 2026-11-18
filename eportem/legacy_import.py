"""Bring one person's set-up from the cron scripts into the service database
(docs/refactor/PLAN.md phase 3; used at the cutover, phase 8).

    python -m eportem migrate
    python -m eportem import-legacy --user NAME [--email ADDRESS] [--from DIR] [--dry-run]

Reads, from DIR (default: this repository):
- config/.env: ePortem credentials, EPORTEM_HTTP, EPORTEM_ENABLED (not YES =
  paused), Telegram and Slack settings
- config/config.json: becomes the person's template (a built-in one when the
  times match exactly) and home/office pattern
- holiday_override.txt, location_override.txt, business_trip_override.txt:
  current and future ones become day changes
- config/.session_cookies.json: the saved ePortem session, so the first run
  needs no browser login
- logs/actions.log (and its rotated copies): the recorded actions become run
  history, so actions cron already did today are not clocked again

Running it again updates the account, schedule and channels from the files and
adds only changes and history that aren't there yet. Secrets are never printed.
"""
import datetime
import json
import zoneinfo
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import delete, select

from eportem.core.cookies import FileCookieStore
from eportem.core.overrides import OverrideFormatError, parse_date_range, parse_location_override
from eportem.core.schedule import TASK_ACTIONS, parse_time, validate_week_schedule
from eportem.core.templates import DayTimes, Template, matching_builtin, template_to_dict
from eportem.db.models import (
    DayChangeRow,
    EportemAccount,
    EportemSession,
    NotificationChannelRow,
    PlannedRun,
    ScheduleTemplate,
    User,
    UserSchedule,
)
from eportem.db.repo import new_user

IMPORTED_TEMPLATE_KEY = "imported"


class ImportError_(Exception):
    def __init__(self, problems):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class Report:
    lines: list = field(default_factory=list)

    def add(self, text):
        self.lines.append(text)


def _http_flag(value):
    value = (value or "NO").strip().upper()
    return value not in ("", "NO", "FALSE", "0")


def week_template(config):
    """(Template, location weeks) from a config.json dict. Raises ImportError_."""
    problems = validate_week_schedule(config)
    days, locations = {}, {}
    for wd, entry in sorted(config.get("schedule", {}).items()):
        if problems:
            break
        t = {TASK_ACTIONS[k]: parse_time(v) for k, v in entry.items() if k in TASK_ACTIONS}
        if "start_day" not in t or "stop_day" not in t:
            problems.append(f'schedule["{wd}"]: needs start_the_day and stop_the_day to become a template')
            continue
        day = DayTimes(t["start_day"], t["stop_day"], t.get("lunch_break"), t.get("after_lunch"))
        problems += [f'schedule["{wd}"]: {p}' for p in day.problems()]
        days[int(wd)] = day
        locations[str(wd)] = entry.get("location", "office")
    if problems:
        raise ImportError_(problems)
    template = Template(IMPORTED_TEMPLATE_KEY, "Imported from config.json", days,
                        "The schedule the cron scripts used")
    return matching_builtin(template) or template, [locations]


def _read_actions_log(path):
    files = [Path(f"{path}.{i}") for i in range(9, 0, -1)] + [Path(path)]
    for p in files:
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) >= 5:
                try:
                    yield datetime.datetime.fromisoformat(parts[0]), parts[2], parts[3], parts[4]
                except ValueError:
                    continue


def import_legacy(db, settings, box, source, username, email=None, today=None, report=None):
    """Import into the open session `db` (the caller commits or rolls back).
    Returns the Report."""
    report = report or Report()
    source = Path(source)
    env = dotenv_values(source / "config" / ".env")
    tz = zoneinfo.ZoneInfo(settings.default_timezone)
    today = today or datetime.datetime.now(tz).date()

    # --- the person
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = new_user(settings, username, email=email, role="admin" if not db.scalar(
            select(User).where(User.role == "admin")) else "user")
        db.add(user)
        db.flush()
        report.add(f"created user {username} ({user.role})")
    else:
        report.add(f"user {username} exists; updating it")
    user.paused = env.get("EPORTEM_ENABLED") != "YES"
    if user.paused:
        report.add("EPORTEM_ENABLED is not YES: the person is paused")

    # --- ePortem account
    from utility.http_clock import ACTIVITY_IDS  # the legacy account's IDs
    if env.get("EPORTEM_USERNAME") and env.get("EPORTEM_PASSWORD"):
        account = db.get(EportemAccount, user.id) or EportemAccount(user_id=user.id)
        account.username = env["EPORTEM_USERNAME"]
        account.password_enc = box.encrypt(env["EPORTEM_PASSWORD"])
        account.office_activity_id = ACTIVITY_IDS.office
        account.home_activity_id = ACTIVITY_IDS.home
        account.lunch_pause_id = ACTIVITY_IDS.lunch_pause
        account.use_http = _http_flag(env.get("EPORTEM_HTTP"))
        db.add(account)
        report.add(f"ePortem account set (activity IDs {ACTIVITY_IDS.office}/{ACTIVITY_IDS.home}/"
                   f"{ACTIVITY_IDS.lunch_pause}, HTTP {'on' if account.use_http else 'off'})")
    else:
        report.add("no EPORTEM_USERNAME/EPORTEM_PASSWORD in config/.env: account not set")

    # --- schedule
    config_path = source / "config" / "config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise ImportError_([f"{config_path}: {e}"]) from e
    template, weeks = week_template(config)
    if not template.builtin:
        row = db.scalar(select(ScheduleTemplate).where(ScheduleTemplate.user_id == user.id,
                                                       ScheduleTemplate.key == template.key))
        row = row or ScheduleTemplate(user_id=user.id, key=template.key)
        row.name, row.description, row.days = template.name, template.description, template_to_dict(template)["days"]
        db.add(row)
    sched = db.get(UserSchedule, user.id) or UserSchedule(user_id=user.id)
    sched.template_key, sched.location_weeks = template.key, weeks
    sched.holiday_country = sched.holiday_country or settings.default_holiday_country
    sched.holiday_region = sched.holiday_region or settings.default_holiday_region
    db.add(sched)
    homes = [k for k, v in weeks[0].items() if v == "home"]
    report.add(f"schedule: template {template.key!r} ({template.name}); home on weekdays {homes or 'none'}")

    # --- overrides that still matter
    def add_change(kind, start, end, location=None):
        exists = db.scalar(select(DayChangeRow).where(
            DayChangeRow.user_id == user.id, DayChangeRow.kind == kind, DayChangeRow.start_date == start,
            DayChangeRow.end_date == end, DayChangeRow.location == location))
        if exists:
            report.add(f"{kind} {start}..{end} already imported")
            return
        db.add(DayChangeRow(user_id=user.id, kind=kind, start_date=start, end_date=end, location=location,
                            note="imported"))
        report.add(f"{kind} {start}..{end}" + (f" ({location})" if location else ""))

    for name, kind in (("holiday_override.txt", "time_off"), ("business_trip_override.txt", "business_trip")):
        path = source / name
        if path.exists() and path.read_text(encoding="utf-8-sig").strip():
            try:
                start, end = parse_date_range(path.read_text(encoding="utf-8-sig").strip())
            except OverrideFormatError as e:
                raise ImportError_([f"{path}: {e}"]) from e
            if end >= today:
                add_change(kind, start, end)
    path = source / "location_override.txt"
    if path.exists():
        try:
            location, date = parse_location_override(path.read_text(encoding="utf-8-sig").strip())
            if date >= today:
                add_change("location", date, date, location)
        except ValueError as e:
            report.add(f"ignored {path.name}: {e}")

    # --- notification channels (replaced on every import)
    db.execute(delete(NotificationChannelRow).where(NotificationChannelRow.user_id == user.id))
    if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
        on = env.get("TELEGRAM_NOTIFY") == "YES"
        secret = box.encrypt_json({"token": env["TELEGRAM_BOT_TOKEN"], "chat_id": env["TELEGRAM_CHAT_ID"]})
        db.add(NotificationChannelRow(user_id=user.id, kind="telegram", notify=on, alerts=on, config_enc=secret))
        report.add(f"Telegram channel ({'on' if on else 'off'})")
    slack = {k: env.get(v) or None for k, v in (("webhook_url", "SLACK_WEBHOOK_URL"), ("bot_token", "SLACK_BOT_TOKEN"),
                                                ("user_token", "SLACK_TOKEN"), ("channel", "SLACK_NOTIFY_CHANNEL"))}
    if any(slack[k] for k in ("webhook_url", "bot_token", "user_token")):
        notify, status = env.get("SLACK_NOTIFY") == "YES", env.get("SLACK_STATUS") == "YES"
        db.add(NotificationChannelRow(user_id=user.id, kind="slack", notify=notify, alerts=notify,
                                      slack_status=status, config_enc=box.encrypt_json(slack)))
        report.add(f"Slack channel (notifications {'on' if notify else 'off'}, status {'on' if status else 'off'})")

    # --- the saved ePortem session
    try:
        data = FileCookieStore(source / "config" / ".session_cookies.json").load()
    except (OSError, ValueError) as e:
        data = None
        report.add(f"saved session unreadable ({type(e).__name__}); the first run will log in")
    if data:
        row = db.get(EportemSession, user.id) or EportemSession(user_id=user.id, data_enc="")
        row.data_enc = box.encrypt_json(data)
        db.add(row)
        report.add(f"saved ePortem session (login {data.get('logged_in_at') or 'unknown'})")

    # --- history
    added = 0
    for ts, action, location, how in _read_actions_log(source / "logs" / "actions.log"):
        date = ts.date()
        if db.scalar(select(PlannedRun.id).where(PlannedRun.user_id == user.id, PlannedRun.date == date,
                                                 PlannedRun.action == action)):
            continue
        at_utc = ts.replace(tzinfo=tz).astimezone(datetime.UTC).replace(tzinfo=None)
        day = template.day(date.weekday())
        target = dict(day.actions()).get(action) if day else None
        db.add(PlannedRun(user_id=user.id, date=date, action=action, location=location, via=f"legacy-{how}",
                          target_minute=target if target is not None else ts.hour * 60 + ts.minute,
                          planned_at=at_utc, started_at=at_utc, finished_at=at_utc, status="recorded"))
        db.flush()
        added += 1
    report.add(f"history: {added} recorded action(s) added from logs/actions.log")
    return report
