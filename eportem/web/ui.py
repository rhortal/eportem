"""The web UI: server-rendered pages (Jinja2) with htmx for the small dynamic
bits (D-002). Every page uses eportem.service, like the API, so the two can't
drift. Forms post and redirect (with a "Saved." notice) or re-render with the
problems listed."""
import calendar as calendar_module
import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from eportem import auth, service
from eportem.core.calendar import resolve
from eportem.core.schedule import ACTIONS, format_minutes
from eportem.core.templates import WEEKDAYS
from eportem.db.models import (
    ApiToken,
    DayChangeRow,
    EportemAccount,
    LocalHoliday,
    NotificationChannelRow,
    PlannedRun,
    SchedulePeriod,
    ScheduleTemplate,
    User,
    UserSchedule,
)
from eportem.db.repo import load_calendar, local_today, templates_for
from eportem.web import sessions
from eportem.web.app import _state, client_address, get_db
from eportem.web.i18n import pick_locale, translator

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(HERE / "templates"))
router = APIRouter(include_in_schema=False)

SPANISH_REGIONS = [("", "—"), ("AN", "Andalucía"), ("AR", "Aragón"), ("AS", "Asturias"), ("CB", "Cantabria"),
                   ("CE", "Ceuta"), ("CL", "Castilla y León"), ("CM", "Castilla-La Mancha"), ("CN", "Canarias"),
                   ("CT", "Cataluña"), ("EX", "Extremadura"), ("GA", "Galicia"), ("IB", "Illes Balears"),
                   ("MC", "Murcia"), ("MD", "Madrid"), ("ML", "Melilla"), ("NC", "Navarra"), ("PV", "País Vasco"),
                   ("RI", "La Rioja"), ("VC", "Comunitat Valenciana")]


class LoginRequired(Exception):
    pass


def ui_user(request: Request, db=Depends(get_db)):
    user = getattr(request.state, "web_user", None)
    if user is None:
        raise LoginRequired()
    return db.merge(user)


def admin_user(user=Depends(ui_user)):
    if user.role != "admin":
        raise HTTPException(403, "admins only")
    return user


def csrf(request: Request, token: str = Form("", alias="csrf")):
    presented = token or request.headers.get("x-csrf-token", "")
    secret = _state(request).settings.secret_key.get_secret_value()
    if not sessions.csrf_ok(secret, getattr(request.state, "session_value", None), presented):
        raise HTTPException(403, "The page expired; try again.")


def page(request, name, user=None, status=200, **ctx):
    settings = _state(request).settings
    locale = pick_locale(user, request.headers.get("accept-language"), settings.default_locale)
    value = getattr(request.state, "session_value", None)
    token = sessions.csrf_token(settings.secret_key.get_secret_value(), value) if value else ""
    ctx.update(request=request, user=user, t=translator(locale), locale=locale, csrf=token,
               saved=request.query_params.get("saved"), format_minutes=format_minutes, WEEKDAYS=WEEKDAYS)
    return templates.TemplateResponse(request, name, ctx, status_code=status)


def back(path, saved=True):
    return RedirectResponse(f"{path}{'?saved=1' if saved else ''}", status_code=303)


def _form_problems(fn):
    """Run fn(); returns problems from a ServiceError (or None)."""
    try:
        fn()
        return None
    except service.ServiceError as e:
        return e.problems


def _replan(request, user, db):
    _state(request).scheduler.replan(user.id, db=db)


# --- sign in --------------------------------------------------------------------
@router.get("/login")
def login_form(request: Request):
    return page(request, "login.html", next=request.query_params.get("next", "/"))


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("/"),
          db=Depends(get_db)):
    state, address = _state(request), client_address(request)
    t = translator(pick_locale(None, request.headers.get("accept-language"), state.settings.default_locale))
    if state.logins.blocked(f"ip:{address}") or state.logins.blocked(f"user:{username}"):
        return page(request, "login.html", status=429, error=t("Too many attempts; wait a few minutes."), next=next)
    user = auth.check_password(db, username, password)
    if user is None:
        state.logins.hit(f"ip:{address}")
        state.logins.hit(f"user:{username}")
        auth.audit(db, None, address, "login.failed", username=username[:64])
        return page(request, "login.html", status=401, error=t("Wrong username or password."), next=next)
    state.logins.reset(f"user:{username}")
    value = sessions.start(db, user, address, request.headers.get("user-agent"))
    auth.audit(db, user.id, f"{user.username} (web)", "login")
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(sessions.COOKIE, value, max_age=int(sessions.LIFETIME.total_seconds()), httponly=True,
                        samesite="lax", secure=state.settings.effective_secure_cookies,
                        path=state.settings.root_path or "/")
    return response


@router.post("/logout", dependencies=[Depends(csrf)])
def logout(request: Request, db=Depends(get_db)):
    sessions.end(db, getattr(request.state, "session_value", None))
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(sessions.COOKIE, path=_state(request).settings.root_path or "/")
    return response


# --- home -----------------------------------------------------------------------
def _setup_steps(db, user):
    account = db.get(EportemAccount, user.id)
    sched = db.get(UserSchedule, user.id)
    channels = db.scalar(select(func.count()).select_from(NotificationChannelRow)
                         .where(NotificationChannelRow.user_id == user.id))
    return [("ePortem account", "/account", bool(account and account.verified_at)),
            ("Working-day template", "/schedule", bool(sched)),
            ("Home days", "/schedule#home-days", bool(sched and any(sched.location_weeks or [{}]))),
            ("Notifications", "/notifications", bool(channels))]


def _week(cal, start):
    return [resolve(cal, start + datetime.timedelta(days=i)) for i in range(7)]


@router.get("/", response_class=HTMLResponse)
def home(request: Request, user=Depends(ui_user), db=Depends(get_db)):
    today = local_today(user)
    monday = today - datetime.timedelta(days=today.weekday())
    cal = load_calendar(db, user)
    runs = db.scalars(select(PlannedRun).where(PlannedRun.user_id == user.id, PlannedRun.date == today)
                      .order_by(PlannedRun.target_minute)).all()
    steps = _setup_steps(db, user)
    return page(request, "home.html", user, today=today, weeks=[("This week", _week(cal, monday)),
                ("Next week", _week(cal, monday + datetime.timedelta(days=7)))], runs=runs, steps=steps,
                setup_done=all(done for _, _, done in steps), actions=ACTIONS)


@router.post("/days/{date}/location", dependencies=[Depends(csrf)])
def toggle_location(request: Request, date: datetime.date, user=Depends(ui_user), db=Depends(get_db)):
    """Switch one day between home and office. If the day already has its own
    location change, removing it brings back the weekly pattern."""
    own = db.scalars(select(DayChangeRow).where(DayChangeRow.user_id == user.id, DayChangeRow.kind == "location",
                                                DayChangeRow.start_date == date, DayChangeRow.end_date == date)).all()
    if own:
        for row in own:
            db.delete(row)
        auth.audit(db, user.id, f"{user.username} (web)", "day_change.delete", date=date.isoformat())
    else:
        current = resolve(load_calendar(db, user), date).location or "office"
        service.add_change(db, user, f"{user.username} (web)", {
            "kind": "location", "start_date": date, "location": "office" if current == "home" else "home"})
    db.flush()
    _replan(request, user, db)
    plan = resolve(load_calendar(db, user), date)
    if request.headers.get("hx-request"):
        return page(request, "_day.html", user, day=plan, today=local_today(user))
    return back("/")


@router.post("/actions/{action}", dependencies=[Depends(csrf)])
def clock_now(request: Request, action: str, confirm: str = Form(""), location: str = Form(""),
              user=Depends(ui_user), db=Depends(get_db)):
    if confirm != "yes":
        return back("/", saved=False)
    run = service.prepare_manual_run(db, user, f"{user.username} (web)", action, location or None,
                                     datetime.datetime.now(datetime.UTC).replace(tzinfo=None))
    db.commit()
    _state(request).scheduler.run_now(run.id, user.id)
    return back("/")


# --- schedule -----------------------------------------------------------------------
def _schedule_page(request, db, user, problems=None, status=200):
    sched = db.get(UserSchedule, user.id)
    temps = templates_for(db, user.id)
    periods = db.scalars(select(SchedulePeriod).where(SchedulePeriod.user_id == user.id)).all()
    weeks = (sched.location_weeks if sched else None) or [{}]
    return page(request, "schedule.html", user, status=status, sched=sched, templates=list(temps.values()),
                current=temps.get(sched.template_key) if sched else None, week=weeks[0], periods=periods,
                regions=SPANISH_REGIONS, problems=problems)


@router.get("/schedule", response_class=HTMLResponse)
def schedule(request: Request, user=Depends(ui_user), db=Depends(get_db)):
    return _schedule_page(request, db, user)


@router.post("/schedule/template", dependencies=[Depends(csrf)])
def use_template(request: Request, template_key: str = Form(...), user=Depends(ui_user), db=Depends(get_db)):
    problems = _form_problems(lambda: service.set_schedule(db, user, f"{user.username} (web)",
                                                           {"template_key": template_key}))
    if problems:
        return _schedule_page(request, db, user, problems, 422)
    _replan(request, user, db)
    return back("/schedule")


@router.post("/schedule/home-days", dependencies=[Depends(csrf)])
async def home_days(request: Request, user=Depends(ui_user), db=Depends(get_db)):
    form = await request.form()
    week = {str(d): ("home" if form.get(f"home_{d}") else "office") for d in range(7)}
    service.set_schedule(db, user, f"{user.username} (web)", {"location_weeks": [week]})
    _replan(request, user, db)
    return back("/schedule")


@router.post("/schedule/holidays", dependencies=[Depends(csrf)])
def holidays(request: Request, holiday_country: str = Form(""), holiday_region: str = Form(""),
             user=Depends(ui_user), db=Depends(get_db)):
    service.set_schedule(db, user, f"{user.username} (web)",
                         {"holiday_country": holiday_country, "holiday_region": holiday_region})
    _replan(request, user, db)
    return back("/schedule")


@router.post("/schedule/custom", dependencies=[Depends(csrf)])
async def save_custom(request: Request, user=Depends(ui_user), db=Depends(get_db)):
    """Save the edited week as the person's own template and use it."""
    form = await request.form()
    days = {}
    for d in range(7):
        if form.get(f"works_{d}"):
            day = {k: form.get(f"{k}_{d}", "") for k in ("start", "stop", "lunch_out", "lunch_back")}
            days[str(d)] = {k: v for k, v in day.items() if v}
    actor = f"{user.username} (web)"
    problems = _form_problems(lambda: service.save_template(db, user, actor, "custom", {
        "name": form.get("name") or "My week", "days": days}))
    if problems is None:
        problems = _form_problems(lambda: service.set_schedule(db, user, actor, {"template_key": "custom"}))
    if problems:
        return _schedule_page(request, db, user, problems, 422)
    _replan(request, user, db)
    return back("/schedule")


@router.post("/schedule/periods", dependencies=[Depends(csrf)])
def add_period(request: Request, template_key: str = Form(...), start_date: str = Form(...),
               end_date: str = Form(...), yearly: str = Form(""), label: str = Form(""),
               user=Depends(ui_user), db=Depends(get_db)):
    problems = _form_problems(lambda: service.add_period(db, user, f"{user.username} (web)", {
        "template_key": template_key, "start_date": start_date, "end_date": end_date, "yearly": bool(yearly),
        "label": label}))
    if problems:
        return _schedule_page(request, db, user, problems, 422)
    _replan(request, user, db)
    return back("/schedule")


@router.post("/schedule/periods/{row_id}/delete", dependencies=[Depends(csrf)])
def delete_period(request: Request, row_id: int, user=Depends(ui_user), db=Depends(get_db)):
    service.delete_owned(db, user, f"{user.username} (web)", SchedulePeriod, row_id, "period")
    db.flush()
    _replan(request, user, db)
    return back("/schedule")


# --- calendar -------------------------------------------------------------------------
def _calendar_page(request, db, user, month=None, problems=None, status=200):
    today = local_today(user)
    first = (month or today).replace(day=1)
    cal = load_calendar(db, user)
    weeks = []
    for week in calendar_module.Calendar().monthdatescalendar(first.year, first.month):
        weeks.append([resolve(cal, d) for d in week])
    changes = db.scalars(select(DayChangeRow).where(DayChangeRow.user_id == user.id)
                         .order_by(DayChangeRow.start_date)).all()
    local = db.scalars(select(LocalHoliday).where(LocalHoliday.user_id == user.id).order_by(LocalHoliday.date)).all()
    prev = (first - datetime.timedelta(days=1)).replace(day=1)
    nxt = (first + datetime.timedelta(days=32)).replace(day=1)
    return page(request, "calendar.html", user, status=status, first=first, weeks=weeks, today=today,
                changes=changes, local=local, prev=prev, next=nxt, problems=problems)


@router.get("/calendar", response_class=HTMLResponse)
def calendar_view(request: Request, month: str = "", user=Depends(ui_user), db=Depends(get_db)):
    try:
        first = datetime.date.fromisoformat(f"{month}-01") if month else None
    except ValueError:
        first = None
    return _calendar_page(request, db, user, first)


@router.post("/calendar/changes", dependencies=[Depends(csrf)])
def add_change(request: Request, kind: str = Form(...), start_date: str = Form(...), end_date: str = Form(""),
               location: str = Form(""), start: str = Form(""), stop: str = Form(""), lunch_out: str = Form(""),
               lunch_back: str = Form(""), note: str = Form(""), user=Depends(ui_user), db=Depends(get_db)):
    data = {"kind": kind, "start_date": start_date, "end_date": end_date or start_date, "note": note,
            "location": location or None}
    if kind == "times":
        data["times"] = {k: v for k, v in (("start", start), ("stop", stop), ("lunch_out", lunch_out),
                                           ("lunch_back", lunch_back)) if v}
    problems = _form_problems(lambda: service.add_change(db, user, f"{user.username} (web)", data))
    if problems:
        return _calendar_page(request, db, user, problems=problems, status=422)
    db.flush()
    _replan(request, user, db)
    return back("/calendar")


@router.post("/calendar/changes/{row_id}/delete", dependencies=[Depends(csrf)])
def delete_change(request: Request, row_id: int, user=Depends(ui_user), db=Depends(get_db)):
    service.delete_owned(db, user, f"{user.username} (web)", DayChangeRow, row_id, "day_change")
    db.flush()
    _replan(request, user, db)
    return back("/calendar")


@router.post("/calendar/holidays", dependencies=[Depends(csrf)])
def add_local_holiday(request: Request, date: str = Form(...), name: str = Form(""), user=Depends(ui_user),
                      db=Depends(get_db)):
    problems = _form_problems(lambda: service.add_local_holiday(db, user, f"{user.username} (web)",
                                                                {"date": date, "name": name}))
    if problems:
        return _calendar_page(request, db, user, problems=problems, status=422)
    db.flush()
    _replan(request, user, db)
    return back("/calendar")


@router.post("/calendar/holidays/{row_id}/delete", dependencies=[Depends(csrf)])
def delete_local_holiday(request: Request, row_id: int, user=Depends(ui_user), db=Depends(get_db)):
    service.delete_owned(db, user, f"{user.username} (web)", LocalHoliday, row_id, "local_holiday")
    db.flush()
    _replan(request, user, db)
    return back("/calendar")


# --- ePortem account --------------------------------------------------------------------
@router.get("/account", response_class=HTMLResponse)
def account(request: Request, user=Depends(ui_user), db=Depends(get_db)):
    return page(request, "account.html", user, account=service.account_view(db.get(EportemAccount, user.id)))


@router.post("/account", dependencies=[Depends(csrf)])
def save_account(request: Request, username: str = Form(""), password: str = Form(""), use_http: str = Form(""),
                 office_activity_id: str = Form(""), home_activity_id: str = Form(""),
                 lunch_pause_id: str = Form(""), user=Depends(ui_user), db=Depends(get_db)):
    data = {"username": username, "use_http": bool(use_http), "office_activity_id": office_activity_id or None,
            "home_activity_id": home_activity_id or None, "lunch_pause_id": lunch_pause_id or None}
    if password:
        data["password"] = password
    problems = _form_problems(lambda: service.set_account(db, _state(request).box, user,
                                                          f"{user.username} (web)", data))
    if problems:
        return page(request, "account.html", user, status=422, problems=problems,
                    account=service.account_view(db.get(EportemAccount, user.id)))
    return back("/account")


@router.post("/account/verify", dependencies=[Depends(csrf)])
def verify_account(request: Request, user=Depends(ui_user), db=Depends(get_db)):
    s = _state(request)
    db.commit()  # D-019
    try:
        result = service.verify_account(db, s.Session, s.box, s.engine, user, f"{user.username} (web)")
        problems = None
    except service.ServiceError as e:
        result, problems = None, e.problems
    return page(request, "account.html", user, status=200 if result else 422, verify=result, problems=problems,
                account=service.account_view(db.get(EportemAccount, user.id)))


# --- notifications ------------------------------------------------------------------------
def _channels_page(request, db, user, problems=None, status=200, test=None):
    rows = db.scalars(select(NotificationChannelRow).where(NotificationChannelRow.user_id == user.id)).all()
    return page(request, "notifications.html", user, status=status, problems=problems, test=test,
                channels=[service.channel_view(_state(request).box, r) for r in rows])


@router.get("/notifications", response_class=HTMLResponse)
def notifications(request: Request, user=Depends(ui_user), db=Depends(get_db)):
    return _channels_page(request, db, user)


@router.post("/notifications", dependencies=[Depends(csrf)])
async def save_channel(request: Request, user=Depends(ui_user), db=Depends(get_db)):
    form = await request.form()
    row_id = form.get("id")
    row = service.owned(db, NotificationChannelRow, int(row_id), user, "channel") if row_id else None
    kind = row.kind if row else form.get("kind")
    fields = service.CHANNEL_FIELDS.get(kind, ())
    config = {k: form.get(k) for k in fields if form.get(k)}  # empty secret fields keep the stored value
    data = {"kind": kind, "config": config, "notify": bool(form.get("notify")), "alerts": bool(form.get("alerts")),
            "slack_status": bool(form.get("slack_status"))}
    problems = _form_problems(lambda: service.save_channel(db, _state(request).box, user,
                                                           f"{user.username} (web)", data, row))
    if problems:
        return _channels_page(request, db, user, problems, 422)
    return back("/notifications")


@router.post("/notifications/{row_id}/delete", dependencies=[Depends(csrf)])
def delete_channel(request: Request, row_id: int, user=Depends(ui_user), db=Depends(get_db)):
    service.delete_owned(db, user, f"{user.username} (web)", NotificationChannelRow, row_id, "channel")
    return back("/notifications")


@router.post("/notifications/{row_id}/test", dependencies=[Depends(csrf)])
def test_channel(request: Request, row_id: int, user=Depends(ui_user), db=Depends(get_db)):
    from eportem.core.notify import SlackChannel, TelegramChannel
    row = service.owned(db, NotificationChannelRow, row_id, user, "channel")
    db.commit()  # D-019
    cfg = _state(request).box.decrypt_json(row.config_enc)
    lines = []

    def say(*a):
        lines.append(" ".join(str(x) for x in a))
    channel = (TelegramChannel(cfg.get("token"), cfg.get("chat_id"), say=say) if row.kind == "telegram" else
               SlackChannel(cfg.get("webhook_url"), cfg.get("user_token"), cfg.get("channel"), cfg.get("bot_token"),
                            say=say))
    channel.send("ePortem: test message")
    return _channels_page(request, db, user, test={"id": row_id, "log": lines})


# --- history ---------------------------------------------------------------------------------
@router.get("/history", response_class=HTMLResponse)
def history(request: Request, user=Depends(ui_user), db=Depends(get_db)):
    today = local_today(user)
    runs = db.scalars(select(PlannedRun).where(PlannedRun.user_id == user.id,
                                               PlannedRun.date >= today - datetime.timedelta(days=30))
                      .order_by(PlannedRun.date.desc(), PlannedRun.target_minute)).all()
    return page(request, "history.html", user, runs=runs)


@router.get("/history/{run_id}", response_class=HTMLResponse)
def run_log(request: Request, run_id: int, user=Depends(ui_user), db=Depends(get_db)):
    return page(request, "log.html", user, log=service.run_log(db, user, run_id))


# --- tokens and profile --------------------------------------------------------------------------
@router.get("/tokens", response_class=HTMLResponse)
def tokens(request: Request, user=Depends(ui_user), db=Depends(get_db)):
    return page(request, "tokens.html", user, tokens=service.list_tokens(db, user))


@router.post("/tokens", dependencies=[Depends(csrf)])
async def create_token(request: Request, user=Depends(ui_user), db=Depends(get_db)):
    form = await request.form()
    scopes = [s for s in auth.SCOPES if form.get(f"scope_{s}")] or ["read"]
    days = int(form.get("expires_in_days") or 0) or None
    try:
        row, token = auth.create_token(db, user, (form.get("name") or "token")[:100], scopes, auth.expires_in(days))
    except ValueError as e:
        return page(request, "tokens.html", user, status=422, problems=[str(e)],
                    tokens=service.list_tokens(db, user))
    auth.audit(db, user.id, f"{user.username} (web)", "token.create", prefix=row.prefix, scopes=row.scopes)
    return page(request, "tokens.html", user, new_token=token, tokens=service.list_tokens(db, user))


@router.post("/tokens/{token_id}/revoke", dependencies=[Depends(csrf)])
def revoke_token(request: Request, token_id: int, user=Depends(ui_user), db=Depends(get_db)):
    row = service.owned(db, ApiToken, token_id, user, "token")
    row.revoked_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    auth.audit(db, user.id, f"{user.username} (web)", "token.revoke", prefix=row.prefix)
    return back("/tokens")


@router.get("/profile", response_class=HTMLResponse)
def profile(request: Request, user=Depends(ui_user)):
    return page(request, "profile.html", user, window=_state(request).settings.window_minutes)


@router.post("/profile", dependencies=[Depends(csrf)])
def save_profile(request: Request, timezone: str = Form(...), locale: str = Form(...),
                 jitter_before_minutes: int = Form(...), jitter_after_minutes: int = Form(...),
                 email: str = Form(""), paused: str = Form(""), user=Depends(ui_user), db=Depends(get_db)):
    data = {"timezone": timezone, "locale": locale, "jitter_before_minutes": jitter_before_minutes,
            "jitter_after_minutes": jitter_after_minutes, "email": email or None, "paused": bool(paused)}
    problems = _form_problems(lambda: service.update_profile(db, _state(request).settings, user,
                                                             f"{user.username} (web)", data))
    if problems:
        return page(request, "profile.html", user, status=422, problems=problems,
                    window=_state(request).settings.window_minutes)
    db.flush()
    _replan(request, user, db)
    return back("/profile")


@router.post("/profile/password", dependencies=[Depends(csrf)])
def change_password(request: Request, current: str = Form(""), new: str = Form(...), user=Depends(ui_user),
                    db=Depends(get_db)):
    problems = _form_problems(lambda: service.change_password(db, user, f"{user.username} (web)", current, new))
    if problems:
        return page(request, "profile.html", user, status=422, problems=problems,
                    window=_state(request).settings.window_minutes)
    return back("/profile")


# --- admin -----------------------------------------------------------------------------------------
def _admin_page(request, db, user, problems=None, status=200):
    since = datetime.date.today() - datetime.timedelta(days=7)
    attention = db.scalars(select(PlannedRun).where(
        PlannedRun.date >= since, PlannedRun.status.in_(("unknown", "not_recorded", "failed", "skipped")))
        .order_by(PlannedRun.planned_at.desc())).all()
    names = dict(db.execute(select(User.id, User.username)).all())
    stats = dict(db.execute(select(PlannedRun.status, func.count()).where(PlannedRun.date >= since)
                            .group_by(PlannedRun.status)).all())
    return page(request, "admin.html", user, status=status, problems=problems,
                users=db.scalars(select(User).order_by(User.id)).all(), attention=attention, names=names,
                stats=stats, templates_in_use=dict(db.execute(select(ScheduleTemplate.user_id, func.count())
                                                              .group_by(ScheduleTemplate.user_id)).all()))


@router.get("/admin", response_class=HTMLResponse)
def admin(request: Request, user=Depends(admin_user), db=Depends(get_db)):
    return _admin_page(request, db, user)


@router.post("/admin/users", dependencies=[Depends(csrf)])
def admin_create_user(request: Request, username: str = Form(...), password: str = Form(...),
                      email: str = Form(""), role: str = Form("user"), user=Depends(admin_user), db=Depends(get_db)):
    problems = _form_problems(lambda: service.create_user(db, _state(request).settings, f"{user.username} (web)",
                                                          username, password, email or None, role))
    if problems:
        return _admin_page(request, db, user, problems, 422)
    return back("/admin")


@router.post("/admin/users/{user_id}/status", dependencies=[Depends(csrf)])
def admin_set_status(request: Request, user_id: int, status: str = Form(...), user=Depends(admin_user),
                     db=Depends(get_db)):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "user not found")
    service.admin_update_user(db, f"{user.username} (web)", target, {"status": status})
    if status != "active":
        sessions.end_all(db, user_id)
    db.flush()
    _replan(request, target, db)
    return back("/admin")
