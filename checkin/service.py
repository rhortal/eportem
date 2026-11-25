"""What people can do, shared by the API and the web UI. Every function takes an
open database session and the acting user, checks its input (raising
ServiceError with every problem) and writes an audit event. Secrets can be set
but are never returned."""
import datetime
import zoneinfo

from sqlalchemy import func, select

from checkin import auth
from checkin.core.calendar import OVERRIDE_KINDS, resolve, resolve_range
from checkin.core.schedule import ACTIONS, LOCATIONS, format_minutes, jitter_problems
from checkin.core.templates import (
    BUILTIN_TEMPLATES,
    TemplateError,
    parse_template,
    template_to_dict,
)
from checkin.db.models import (
    ApiToken,
    DayChangeRow,
    EportemAccount,
    LocalHoliday,
    NotificationChannelRow,
    PlannedRun,
    RunLog,
    SchedulePeriod,
    ScheduleTemplate,
    User,
    UserSchedule,
    utcnow,
)
from checkin.db.repo import DbCookieStore, load_calendar, local_today, new_user, templates_for

CHANNEL_FIELDS = {"telegram": ("token", "chat_id"), "slack": ("webhook_url", "bot_token", "user_token", "channel")}
SECRET_CHANNEL_FIELDS = {"token", "webhook_url", "bot_token", "user_token"}


class ServiceError(Exception):
    def __init__(self, problems, status=422):
        problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("; ".join(problems))
        self.problems, self.status = problems, status


class NotFound(ServiceError):
    def __init__(self, what):
        super().__init__(f"{what} not found", 404)


def _date(value, name):
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ServiceError(f"{name} must be a date like 2026-12-24") from None


# --- people ---------------------------------------------------------------------
def profile(user):
    return {"id": user.id, "username": user.username, "email": user.email, "role": user.role,
            "status": user.status, "plan": user.plan, "timezone": user.timezone, "locale": user.locale,
            "jitter_before_minutes": user.jitter_before_minutes, "jitter_after_minutes": user.jitter_after_minutes,
            "paused": user.paused}


def update_profile(db, settings, user, actor, data):
    problems = []
    allowed = {"email", "timezone", "locale", "jitter_before_minutes", "jitter_after_minutes", "paused"}
    unknown = set(data) - allowed
    if unknown:
        problems.append(f"unknown fields: {', '.join(sorted(unknown))}")
    if "timezone" in data:
        try:
            zoneinfo.ZoneInfo(data["timezone"])
        except (zoneinfo.ZoneInfoNotFoundError, ValueError, TypeError):
            problems.append(f"unknown time zone {data['timezone']!r}")
    if "locale" in data and data["locale"] not in ("en", "es"):
        problems.append("locale must be en or es")
    before = data.get("jitter_before_minutes", user.jitter_before_minutes)
    after = data.get("jitter_after_minutes", user.jitter_after_minutes)
    problems += jitter_problems(before, after, settings.window_minutes)
    if "paused" in data and not isinstance(data["paused"], bool):
        problems.append("paused must be true or false")
    if problems:
        raise ServiceError(problems)
    for k, v in data.items():
        setattr(user, k, v)
    auth.audit(db, user.id, actor, "profile.update", fields=sorted(data))
    return profile(user)


def change_password(db, user, actor, current, new):
    if user.password_hash and not auth.check_password(db, user.username, current):
        raise ServiceError("the current password is wrong", 403)
    try:
        user.password_hash = auth.hash_password(new)
    except ValueError as e:
        raise ServiceError(str(e)) from None
    auth.audit(db, user.id, actor, "password.change")


def create_user(db, settings, actor, username, password=None, email=None, role="user"):
    problems = []
    if not username or not username.replace("-", "").replace("_", "").replace(".", "").isalnum():
        problems.append("username: letters, digits, '-', '_' and '.' only")
    if role not in ("user", "admin"):
        problems.append("role must be user or admin")
    if db.scalar(select(User.id).where(User.username == username)):
        problems.append("that username is taken")
    if password is not None:
        problems += auth.password_problems(password)
    if problems:
        raise ServiceError(problems)
    user = new_user(settings, username, email=email, role=role, status="active",
                    password_hash=auth.hash_password(password) if password else None)
    db.add(user)
    db.flush()
    db.add(UserSchedule(user_id=user.id, template_key=settings.default_template, location_weeks=[{}],
                        holiday_country=settings.default_holiday_country,
                        holiday_region=settings.default_holiday_region))
    auth.audit(db, user.id, actor, "user.create", username=username, role=role)
    return user


def admin_update_user(db, actor, user, data):
    allowed = {"status": ("pending", "active", "suspended"), "role": ("user", "admin")}
    problems = [f"{k} must be one of {', '.join(allowed[k])}" for k, v in data.items()
                if k in allowed and v not in allowed[k]]
    problems += [f"unknown field {k}" for k in data if k not in allowed and k != "plan"]
    if problems:
        raise ServiceError(problems)
    for k, v in data.items():
        setattr(user, k, v)
    auth.audit(db, user.id, actor, "admin.user.update", **data)
    return profile(user)


# --- ePortem account --------------------------------------------------------------
def account_view(account):
    if account is None:
        return {"configured": False}
    return {"configured": True, "username": account.username, "use_http": account.use_http,
            "office_activity_id": account.office_activity_id, "home_activity_id": account.home_activity_id,
            "lunch_pause_id": account.lunch_pause_id,
            "verified_at": account.verified_at.isoformat() if account.verified_at else None}


def set_account(db, box, user, actor, data):
    account = db.get(EportemAccount, user.id)
    if account is None and not (data.get("username") and data.get("password")):
        raise ServiceError("username and password are required the first time")
    account = account or EportemAccount(user_id=user.id)
    for key in ("username", "use_http", "office_activity_id", "home_activity_id", "lunch_pause_id"):
        if key in data:
            setattr(account, key, data[key])
    if data.get("password"):
        account.password_enc = box.encrypt(data["password"])
        account.verified_at = None
    db.add(account)
    auth.audit(db, user.id, actor, "eportem_account.set",
               fields=sorted(k for k in data if k != "password") + (["password"] if "password" in data else []))
    return account_view(account)


def discover_activity_ids(buttons):
    """Work out the office, home and lunch activity IDs from the dashboard's
    buttons: work activities (name2 W) whose label mentions casa/home are home,
    the other work activity is the office; the pause labelled Comida is lunch.
    Only what is unambiguous is returned."""
    work = {(b.get("name"), b.get("name3") or "") for b in buttons
            if b.get("name2") == "W" and b.get("name") and b.get("id") in ("_ststart", "_stini")}
    home = {n for n, label in work if any(w in label.lower() for w in ("casa", "home", "remoto", "teletrabajo"))}
    office = {n for n, _ in work} - home
    lunch = {b.get("name") for b in buttons if b.get("name2") == "P" and b.get("name")
             and "comida" in (b.get("name3") or "").lower()}
    found = {}
    if len(home) == 1:
        found["home_activity_id"] = home.pop()
    if len(office) == 1:
        found["office_activity_id"] = office.pop()
    if len(lunch) == 1:
        found["lunch_pause_id"] = lunch.pop()
    return found


def _dashboard(db, sessionmaker, box, engine, user):
    """(account, password, the dashboard's clock buttons): saved session first,
    a browser login only if it expired. Never clocks. Raises ServiceError when
    there is no account, or returns the exception from a failed login."""
    from checkin.core.clock_http import HttpClock, parse_buttons
    account = db.get(EportemAccount, user.id)
    if account is None:
        raise ServiceError("set the ePortem account first")
    password = box.decrypt(account.password_enc)
    lines = []
    clock = HttpClock(target=engine.target, cookie_store=DbCookieStore(sessionmaker, user.id, box),
                      make_driver=engine.make_driver, login_driver=engine.login_for(account.username, password),
                      say=lambda *a: lines.append(" ".join(map(str, a))))
    try:
        buttons = parse_buttons(clock.fetch_dashboard()) if clock.load_cookies() else None
    except Exception:
        buttons = None
    try:
        if buttons is None:
            buttons = clock.ensure_session()
    except Exception as e:
        return account, password, e
    return account, password, buttons


def _login_problem(e, password):
    return ServiceError(f"could not log in to ePortem: {type(e).__name__}: "
                        f"{str(e).replace(password, '<redacted>')[:200]}", 502)


def verify_account(db, sessionmaker, box, engine, user, actor):
    """Log in (browser only if the saved session expired) and read the dashboard.
    Never clocks. Fills in activity IDs it can work out and that aren't set."""
    account, password, buttons = _dashboard(db, sessionmaker, box, engine, user)
    if isinstance(buttons, Exception):
        auth.audit(db, user.id, actor, "eportem_account.verify", ok=False, error=type(buttons).__name__)
        raise _login_problem(buttons, password) from None
    found = discover_activity_ids(buttons)
    for key, value in found.items():
        if not getattr(account, key):
            setattr(account, key, value)
    account.verified_at = account.last_login_at = utcnow()
    auth.audit(db, user.id, actor, "eportem_account.verify", ok=True, found=sorted(found))
    activities = sorted({(b.get("id"), b.get("name") or "", b.get("name2") or "", b.get("name3") or "")
                         for b in buttons})
    return {"account": account_view(account), "found": found,
            "activities": [dict(zip(("button", "id", "kind", "label"), a, strict=True)) for a in activities]}


def eportem_state(db, sessionmaker, box, engine, user):
    """What ePortem shows right now, read from its dashboard (never clocks):
    `working`, `on_break` or `not_working`, the actions CheckIn can send from
    here, and every button the dashboard offers (D-028)."""
    from checkin.core.clock_http import ButtonNotFound, select_button
    from checkin.db.repo import activity_ids
    account, password, buttons = _dashboard(db, sessionmaker, box, engine, user)
    if isinstance(buttons, Exception):
        raise _login_problem(buttons, password) from None
    # Not started (or stopped): start buttons. On a break: resume at either place.
    # Working: only a switch to the other place, which is not "back from lunch".
    resume_at = {b.get("name") for b in buttons if b.get("id") == "_stini" and b.get("name2") == "W"}
    state = ("not_working" if any(b.get("id") == "_ststart" for b in buttons) else
             "on_break" if len(resume_at) >= 2 else "working")
    fits = {"not_working": ("start_day",), "working": ("lunch_break", "stop_day"),
            "on_break": ("after_lunch", "stop_day")}[state]
    ids, available = activity_ids(account), []
    for action in fits:
        for location in (("home", "office") if action in ("start_day", "after_lunch") else ("office",)):
            try:
                select_button(buttons, action, location, ids)
            except (ButtonNotFound, ValueError, AttributeError):  # AttributeError: activity IDs not known yet
                continue
            available.append({"action": action, "location": location if action in ("start_day", "after_lunch")
                              else None})
    return {"state": state, "available_actions": available, "activity_ids_known": ids is not None,
            "buttons": [{"button": b.get("id"), "id": b.get("name"), "kind": b.get("name2"),
                         "label": b.get("name3")} for b in buttons],
            "read_at": utcnow().isoformat() + "Z"}


# --- templates and schedule --------------------------------------------------------
def list_templates(db, user):
    return [dict(template_to_dict(t), builtin=t.builtin) for t in templates_for(db, user.id).values()]


def save_template(db, user, actor, key, data):
    if key in BUILTIN_TEMPLATES:
        raise ServiceError("built-in templates can't be changed; save a copy under another key")
    try:
        template = parse_template({**data, "key": key})
    except TemplateError as e:
        raise ServiceError(e.problems) from None
    row = db.scalar(select(ScheduleTemplate).where(ScheduleTemplate.user_id == user.id,
                                                   ScheduleTemplate.key == key))
    row = row or ScheduleTemplate(user_id=user.id, key=key)
    row.name, row.description = template.name, template.description
    row.days = template_to_dict(template)["days"]
    db.add(row)
    auth.audit(db, user.id, actor, "template.save", key=key)
    return dict(template_to_dict(template), builtin=False)


def delete_template(db, user, actor, key):
    row = db.scalar(select(ScheduleTemplate).where(ScheduleTemplate.user_id == user.id,
                                                   ScheduleTemplate.key == key))
    if row is None:
        raise NotFound("template")
    sched = db.get(UserSchedule, user.id)
    in_use = (sched and sched.template_key == key) or db.scalar(select(SchedulePeriod.id).where(
        SchedulePeriod.user_id == user.id, SchedulePeriod.template_key == key))
    if in_use:
        raise ServiceError("the template is in use by the schedule or a period", 409)
    db.delete(row)
    auth.audit(db, user.id, actor, "template.delete", key=key)


def schedule_view(sched):
    return {"template_key": sched.template_key, "location_weeks": sched.location_weeks,
            "pattern_anchor": sched.pattern_anchor.isoformat() if sched.pattern_anchor else None,
            "holiday_country": sched.holiday_country, "holiday_region": sched.holiday_region}


def set_schedule(db, user, actor, data):
    sched = db.get(UserSchedule, user.id) or UserSchedule(user_id=user.id, template_key="european-9-18",
                                                          location_weeks=[{}])
    problems = []
    if "template_key" in data and data["template_key"] not in templates_for(db, user.id):
        problems.append(f"unknown template {data['template_key']!r}")
    weeks = data.get("location_weeks", sched.location_weeks)
    if not isinstance(weeks, list) or len(weeks) not in (1, 2):
        problems.append("location_weeks must hold one week, or two for alternating weeks")
    else:
        for i, week in enumerate(weeks):
            for wd, loc in (week or {}).items():
                if wd not in {str(d) for d in range(7)} or loc not in LOCATIONS:
                    problems.append(f"location_weeks[{i}]: weekday {wd!r} -> {loc!r} is not valid")
    anchor = data.get("pattern_anchor")
    if anchor is not None:
        anchor = _date(anchor, "pattern_anchor")
    if isinstance(weeks, list) and len(weeks) == 2 and not (anchor or sched.pattern_anchor):
        problems.append("alternating weeks need pattern_anchor (a date in week A)")
    if problems:
        raise ServiceError(problems)
    for key in ("template_key", "location_weeks"):
        if key in data:
            setattr(sched, key, data[key])
    for key in ("holiday_country", "holiday_region"):
        if key in data:
            setattr(sched, key, data[key] or None)  # empty: no public holidays / whole country
    if "pattern_anchor" in data:
        sched.pattern_anchor = anchor
    db.add(sched)
    auth.audit(db, user.id, actor, "schedule.set", fields=sorted(data))
    return schedule_view(sched)


def _row_view(row, fields):
    out = {"id": row.id}
    for f in fields:
        v = getattr(row, f)
        out[f] = v.isoformat() if isinstance(v, datetime.date) else v
    return out


PERIOD_FIELDS = ("template_key", "start_date", "end_date", "yearly", "label")
CHANGE_FIELDS = ("kind", "start_date", "end_date", "location", "times", "note")


def add_period(db, user, actor, data):
    if data.get("template_key") not in templates_for(db, user.id):
        raise ServiceError(f"unknown template {data.get('template_key')!r}")
    start, end = _date(data.get("start_date"), "start_date"), _date(data.get("end_date"), "end_date")
    if not data.get("yearly") and end < start:
        raise ServiceError("end_date is before start_date")
    row = SchedulePeriod(user_id=user.id, template_key=data["template_key"], start_date=start, end_date=end,
                         yearly=bool(data.get("yearly")), label=data.get("label", ""))
    db.add(row)
    db.flush()
    auth.audit(db, user.id, actor, "period.add", id=row.id)
    return _row_view(row, PERIOD_FIELDS)


def add_change(db, user, actor, data):
    problems = []
    kind = data.get("kind")
    if kind not in OVERRIDE_KINDS:
        problems.append(f"kind must be one of {', '.join(OVERRIDE_KINDS)}")
    start = _date(data.get("start_date"), "start_date")
    end = _date(data.get("end_date") or data.get("start_date"), "end_date")
    if end < start:
        problems.append("end_date is before start_date")
    location = data.get("location")
    if kind == "location" and location not in LOCATIONS:
        problems.append("a location change needs location home or office")
    if location is not None and location not in LOCATIONS:
        problems.append("location must be home or office")
    times = data.get("times")
    if kind == "times":
        try:
            parse_template({"key": "x", "name": "x", "days": {"0": times}})
        except TemplateError as e:
            problems += [p.replace('days["0"]', "times") for p in e.problems]
    if problems:
        raise ServiceError(problems)
    row = DayChangeRow(user_id=user.id, kind=kind, start_date=start, end_date=end, location=location,
                       times=times if kind == "times" else None, note=data.get("note", ""))
    db.add(row)
    db.flush()
    auth.audit(db, user.id, actor, "day_change.add", id=row.id, kind=kind)
    return _row_view(row, CHANGE_FIELDS)


def delete_owned(db, user, actor, model, row_id, what):
    row = db.get(model, row_id)
    if row is None or row.user_id != user.id:
        raise NotFound(what)
    db.delete(row)
    auth.audit(db, user.id, actor, f"{what}.delete", id=row_id)


def add_local_holiday(db, user, actor, data):
    date = _date(data.get("date"), "date")
    if db.scalar(select(LocalHoliday.id).where(LocalHoliday.user_id == user.id, LocalHoliday.date == date)):
        raise ServiceError("there is already a local holiday on that date", 409)
    row = LocalHoliday(user_id=user.id, date=date, name=data.get("name") or "Local holiday")
    db.add(row)
    db.flush()
    auth.audit(db, user.id, actor, "local_holiday.add", id=row.id)
    return _row_view(row, ("date", "name"))


def calendar(db, user, start, days):
    if not 1 <= days <= 62:
        raise ServiceError("days must be 1 to 62")
    out = []
    for plan in resolve_range(load_calendar(db, user), start, days):
        out.append({"date": plan.date.isoformat(), "works": plan.works, "reason": plan.reason,
                    "location": plan.location, "location_source": plan.location_source,
                    "business_trip_end": plan.business_trip_end.isoformat() if plan.business_trip_end else None,
                    "actions": [{"action": a, "time": format_minutes(m)} for a, m in plan.actions()]})
    return out


def setup_steps(db, user):
    """The setup checklist: (label, page, done)."""
    account = db.get(EportemAccount, user.id)
    sched = db.get(UserSchedule, user.id)
    channels = db.scalar(select(func.count()).select_from(NotificationChannelRow)
                         .where(NotificationChannelRow.user_id == user.id))
    return [("ePortem account", "/account", bool(account and account.verified_at)),
            ("Working-day template", "/schedule", bool(sched)),
            ("Home days", "/schedule#home-days", bool(sched and any(sched.location_weeks or [{}]))),
            ("Notifications", "/notifications", bool(channels))]


def status(db, user, now_utc=None):
    """One answer to "how do things stand?": who, today's plan and runs, the
    next run, the setup checklist. Made for agents and scripts (D-028)."""
    now_utc = now_utc or utcnow()
    today = local_today(user, now_utc.replace(tzinfo=datetime.UTC))
    runs = db.scalars(select(PlannedRun).where(PlannedRun.user_id == user.id, PlannedRun.date >= today)
                      .order_by(PlannedRun.planned_at)).all()
    upcoming = [r for r in runs if r.status == "planned" and r.planned_at >= now_utc]
    return {"user": profile(user), "today": calendar(db, user, today, 1)[0],
            "runs_today": [run_view(r, user.timezone) for r in runs if r.date == today],
            "next_run": run_view(upcoming[0], user.timezone) if upcoming else None,
            "setup": [{"step": label, "page": page, "done": done} for label, page, done in setup_steps(db, user)]}


# --- channels ----------------------------------------------------------------------
def channel_view(box, row):
    cfg = box.decrypt_json(row.config_enc)
    shown = {k: ("(set)" if cfg.get(k) else None) if k in SECRET_CHANNEL_FIELDS else cfg.get(k)
             for k in CHANNEL_FIELDS[row.kind]}
    return {"id": row.id, "kind": row.kind, "notify": row.notify, "alerts": row.alerts,
            "slack_status": row.slack_status, "config": shown}


def save_channel(db, box, user, actor, data, row=None):
    kind = row.kind if row else data.get("kind")
    if kind not in CHANNEL_FIELDS:
        raise ServiceError("kind must be telegram or slack")
    cfg = box.decrypt_json(row.config_enc) if row else {}
    for k, v in (data.get("config") or {}).items():
        if k not in CHANNEL_FIELDS[kind]:
            raise ServiceError(f"unknown {kind} setting {k!r}")
        cfg[k] = v or None
    if kind == "telegram" and not (cfg.get("token") and cfg.get("chat_id")):
        raise ServiceError("Telegram needs token and chat_id")
    if kind == "slack" and not any(cfg.get(k) for k in ("webhook_url", "bot_token", "user_token")):
        raise ServiceError("Slack needs webhook_url, bot_token or user_token")
    if data.get("slack_status") and not cfg.get("user_token"):
        raise ServiceError("the Slack status needs user_token")
    row = row or NotificationChannelRow(user_id=user.id, kind=kind)
    row.config_enc = box.encrypt_json(cfg)
    for flag in ("notify", "alerts", "slack_status"):
        if flag in data:
            setattr(row, flag, bool(data[flag]))
    db.add(row)
    db.flush()
    auth.audit(db, user.id, actor, "channel.save", id=row.id, kind=kind)
    return channel_view(box, row)


def owned(db, model, row_id, user, what):
    row = db.get(model, row_id)
    if row is None or row.user_id != user.id:
        raise NotFound(what)
    return row


# --- runs --------------------------------------------------------------------------
def run_view(run, timezone=None):
    """`time` is the schedule's time for the action; `planned_at` (UTC) is when
    the run really goes, with the random offset, and `at` the same in the
    person's time zone, when it is given."""
    out = {"id": run.id, "date": run.date.isoformat(), "action": run.action,
           "time": format_minutes(run.target_minute), "location": run.location, "status": run.status,
           "via": run.via, "planned_at": run.planned_at.isoformat() + "Z",
           "finished_at": run.finished_at.isoformat() + "Z" if run.finished_at else None, "error": run.error}
    if timezone:
        local = run.planned_at.replace(tzinfo=datetime.UTC).astimezone(zoneinfo.ZoneInfo(timezone))
        out["at"] = local.strftime("%H:%M:%S")
    return out


def list_runs(db, user, start, end):
    rows = db.scalars(select(PlannedRun).where(PlannedRun.user_id == user.id, PlannedRun.date >= start,
                                               PlannedRun.date <= end).order_by(PlannedRun.planned_at))
    return [run_view(r, user.timezone) for r in rows]


def run_log(db, user, run_id):
    run = owned(db, PlannedRun, run_id, user, "run")
    log = db.get(RunLog, run.id)
    return {"run": run_view(run, user.timezone), "outcome": log.outcome if log else None,
            "text": log.text if log else ""}


def prepare_manual_run(db, user, actor, action, location, now_utc):
    """A run for `action` today, due now (outside its normal time on purpose).
    Refuses when today's action is already recorded or in progress."""
    if action not in ACTIONS:
        raise ServiceError(f"action must be one of {', '.join(ACTIONS)}")
    today = local_today(user, now_utc.replace(tzinfo=datetime.UTC))
    plan = resolve(load_calendar(db, user), today)
    location = location or plan.location or "office"
    if location not in LOCATIONS:
        raise ServiceError("location must be home or office")
    run = db.scalar(select(PlannedRun).where(PlannedRun.user_id == user.id, PlannedRun.date == today,
                                             PlannedRun.action == action))
    if run and run.status in ("recorded", "running", "unknown"):
        raise ServiceError(f"today's {action} is already {run.status}", 409)
    local = now_utc.replace(tzinfo=datetime.UTC).astimezone(zoneinfo.ZoneInfo(user.timezone))
    run = run or PlannedRun(user_id=user.id, date=today, action=action)
    run.target_minute, run.planned_at, run.location = local.hour * 60 + local.minute, now_utc, location
    run.status, run.error = "planned", None
    db.add(run)
    db.flush()
    auth.audit(db, user.id, actor, "run.manual", id=run.id, action=action, location=location)
    return run


# --- tokens --------------------------------------------------------------------------
def token_view(row):
    return {"id": row.id, "name": row.name, "prefix": row.prefix, "scopes": row.scopes.split(","),
            "created_at": row.created_at.isoformat() + "Z",
            "last_used_at": row.last_used_at.isoformat() + "Z" if row.last_used_at else None,
            "expires_at": row.expires_at.isoformat() + "Z" if row.expires_at else None,
            "revoked": row.revoked_at is not None}


def list_tokens(db, user):
    return [token_view(t) for t in db.scalars(select(ApiToken).where(ApiToken.user_id == user.id))]
