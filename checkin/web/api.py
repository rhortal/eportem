"""`/api/v1`: everything a person can do, for scripts and integrations.
Authenticate with `Authorization: Bearer ept_...` (create tokens in the web UI
or with `python -m checkin create-token`). OpenAPI at /api/docs."""
import datetime
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from checkin import auth, device, service, skill
from checkin.db.models import (
    ApiToken,
    DayChangeRow,
    LocalHoliday,
    NotificationChannelRow,
    PlannedRun,
    SchedulePeriod,
    User,
    UserSchedule,
)
from checkin.db.repo import local_today
from checkin.web.app import Caller, _state, client_address, get_db, needs

router = APIRouter()
READ, WRITE, ADMIN = needs("read"), needs("write"), needs("admin")


def _replan(request, user, db):
    """Re-plan today inside the request's transaction."""
    sched = _state(request).scheduler
    if sched is not None:
        sched.replan(user.id, db=db)


def _now():
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


# --- me ---------------------------------------------------------------------------
class ProfileIn(BaseModel):
    email: str | None = None
    timezone: str | None = None
    locale: Literal["en", "es"] | None = None
    jitter_before_minutes: int | None = None
    jitter_after_minutes: int | None = None
    paused: bool | None = None


@router.get("/me")
def me(who: Caller = Depends(READ)):
    return service.profile(who.user)


@router.get("/status")
def status(who: Caller = Depends(READ), db=Depends(get_db)):
    """Who you are, today's plan and runs, the next run and the setup checklist."""
    return service.status(db, who.user)


@router.patch("/me")
def update_me(request: Request, body: ProfileIn, who: Caller = Depends(WRITE), db=Depends(get_db)):
    out = service.update_profile(db, _state(request).settings, who.user, who.actor,
                                 body.model_dump(exclude_unset=True))
    db.flush()
    _replan(request, who.user, db)
    return out


class PasswordIn(BaseModel):
    current: str = ""
    new: str


@router.put("/me/password", status_code=204)
def set_password(body: PasswordIn, who: Caller = Depends(WRITE), db=Depends(get_db)):
    service.change_password(db, who.user, who.actor, body.current, body.new)


# --- ePortem account ----------------------------------------------------------------
class AccountIn(BaseModel):
    username: str | None = None
    password: str | None = Field(None, description="Write only; never returned.")
    use_http: bool | None = None
    office_activity_id: str | None = None
    home_activity_id: str | None = None
    lunch_pause_id: str | None = None


@router.get("/eportem-account")
def get_account(who: Caller = Depends(READ), db=Depends(get_db)):
    from checkin.db.models import EportemAccount
    return service.account_view(db.get(EportemAccount, who.user.id))


@router.put("/eportem-account")
def put_account(request: Request, body: AccountIn, who: Caller = Depends(WRITE), db=Depends(get_db)):
    return service.set_account(db, _state(request).box, who.user, who.actor, body.model_dump(exclude_unset=True))


@router.post("/eportem-account/verify")
def verify_account(request: Request, who: Caller = Depends(WRITE), db=Depends(get_db)):
    """Log in to ePortem (a browser only if the saved session has expired) and
    read the dashboard. Never clocks. Fills in activity IDs it can work out."""
    s = _state(request)
    db.commit()  # nothing written yet; never hold a write lock across the login (D-019)
    return service.verify_account(db, s.Session, s.box, s.engine, who.user, who.actor)


@router.get("/eportem/state")
def eportem_state(request: Request, who: Caller = Depends(READ), db=Depends(get_db)):
    """What ePortem shows right now: working, on a break or not working, and the
    actions that can be sent from there. Reads the dashboard (logging in if the
    saved session expired); never clocks."""
    s = _state(request)
    db.commit()  # never hold a write lock across the login (D-019)
    return service.eportem_state(db, s.Session, s.box, s.engine, who.user)


# --- templates and schedule ---------------------------------------------------------
@router.get("/templates")
def templates(who: Caller = Depends(READ), db=Depends(get_db)):
    return service.list_templates(db, who.user)


@router.put("/templates/{key}")
def put_template(key: str, body: dict[str, Any] = Body(...), who: Caller = Depends(WRITE), db=Depends(get_db)):
    return service.save_template(db, who.user, who.actor, key, body)


@router.delete("/templates/{key}", status_code=204)
def delete_template(key: str, who: Caller = Depends(WRITE), db=Depends(get_db)):
    service.delete_template(db, who.user, who.actor, key)


@router.get("/schedule")
def get_schedule(who: Caller = Depends(READ), db=Depends(get_db)):
    sched = db.get(UserSchedule, who.user.id)
    if sched is None:
        raise HTTPException(404, "no schedule yet")
    return service.schedule_view(sched)


@router.put("/schedule")
def put_schedule(request: Request, body: dict[str, Any] = Body(...), who: Caller = Depends(WRITE),
                 db=Depends(get_db)):
    out = service.set_schedule(db, who.user, who.actor, body)
    db.flush()
    _replan(request, who.user, db)
    return out


@router.get("/periods")
def periods(who: Caller = Depends(READ), db=Depends(get_db)):
    rows = db.scalars(select(SchedulePeriod).where(SchedulePeriod.user_id == who.user.id).order_by(SchedulePeriod.id))
    return [service._row_view(r, service.PERIOD_FIELDS) for r in rows]


@router.post("/periods", status_code=201)
def add_period(request: Request, body: dict[str, Any] = Body(...), who: Caller = Depends(WRITE),
               db=Depends(get_db)):
    out = service.add_period(db, who.user, who.actor, body)
    _replan(request, who.user, db)
    return out


@router.delete("/periods/{row_id}", status_code=204)
def delete_period(request: Request, row_id: int, who: Caller = Depends(WRITE), db=Depends(get_db)):
    service.delete_owned(db, who.user, who.actor, SchedulePeriod, row_id, "period")
    db.flush()
    _replan(request, who.user, db)


@router.get("/days")
def day_changes(who: Caller = Depends(READ), db=Depends(get_db)):
    rows = db.scalars(select(DayChangeRow).where(DayChangeRow.user_id == who.user.id).order_by(DayChangeRow.id))
    return [service._row_view(r, service.CHANGE_FIELDS) for r in rows]


@router.post("/days", status_code=201)
def add_day_change(request: Request, body: dict[str, Any] = Body(...), who: Caller = Depends(WRITE),
                   db=Depends(get_db)):
    """Time off, a location for some days, a business trip, other times, or
    working on a public holiday. A later change wins over an earlier one."""
    out = service.add_change(db, who.user, who.actor, body)
    db.flush()
    _replan(request, who.user, db)
    return out


@router.delete("/days/{row_id}", status_code=204)
def delete_day_change(request: Request, row_id: int, who: Caller = Depends(WRITE), db=Depends(get_db)):
    service.delete_owned(db, who.user, who.actor, DayChangeRow, row_id, "day_change")
    db.flush()
    _replan(request, who.user, db)


@router.get("/local-holidays")
def local_holidays(who: Caller = Depends(READ), db=Depends(get_db)):
    rows = db.scalars(select(LocalHoliday).where(LocalHoliday.user_id == who.user.id).order_by(LocalHoliday.date))
    return [service._row_view(r, ("date", "name")) for r in rows]


@router.post("/local-holidays", status_code=201)
def add_local_holiday(request: Request, body: dict[str, Any] = Body(...), who: Caller = Depends(WRITE),
                      db=Depends(get_db)):
    out = service.add_local_holiday(db, who.user, who.actor, body)
    db.flush()
    _replan(request, who.user, db)
    return out


@router.delete("/local-holidays/{row_id}", status_code=204)
def delete_local_holiday(request: Request, row_id: int, who: Caller = Depends(WRITE), db=Depends(get_db)):
    service.delete_owned(db, who.user, who.actor, LocalHoliday, row_id, "local_holiday")
    db.flush()
    _replan(request, who.user, db)


@router.get("/calendar")
def calendar(start: datetime.date | None = Query(None, alias="from"), days: int = 14,
             who: Caller = Depends(READ), db=Depends(get_db)):
    """What will happen on each day, with the reason (same answer the scheduler uses)."""
    return service.calendar(db, who.user, start or local_today(who.user), days)


# --- channels -------------------------------------------------------------------------
@router.get("/channels")
def channels(request: Request, who: Caller = Depends(READ), db=Depends(get_db)):
    rows = db.scalars(select(NotificationChannelRow).where(NotificationChannelRow.user_id == who.user.id))
    return [service.channel_view(_state(request).box, r) for r in rows]


@router.post("/channels", status_code=201)
def add_channel(request: Request, body: dict[str, Any] = Body(...), who: Caller = Depends(WRITE),
                db=Depends(get_db)):
    return service.save_channel(db, _state(request).box, who.user, who.actor, body)


@router.patch("/channels/{row_id}")
def update_channel(request: Request, row_id: int, body: dict[str, Any] = Body(...), who: Caller = Depends(WRITE),
                   db=Depends(get_db)):
    row = service.owned(db, NotificationChannelRow, row_id, who.user, "channel")
    return service.save_channel(db, _state(request).box, who.user, who.actor, body, row)


@router.delete("/channels/{row_id}", status_code=204)
def delete_channel(row_id: int, who: Caller = Depends(WRITE), db=Depends(get_db)):
    service.delete_owned(db, who.user, who.actor, NotificationChannelRow, row_id, "channel")


@router.post("/channels/{row_id}/test")
def test_channel(request: Request, row_id: int, who: Caller = Depends(WRITE), db=Depends(get_db)):
    """Send a test message through this channel only."""
    row = service.owned(db, NotificationChannelRow, row_id, who.user, "channel")
    lines = []
    box = _state(request).box
    cfg = box.decrypt_json(row.config_enc)
    from checkin.core.notify import SlackChannel, TelegramChannel
    say = lambda *a: lines.append(" ".join(str(x) for x in a))  # noqa: E731
    channel = (TelegramChannel(cfg.get("token"), cfg.get("chat_id"), say=say) if row.kind == "telegram" else
               SlackChannel(cfg.get("webhook_url"), cfg.get("user_token"), cfg.get("channel"), cfg.get("bot_token"),
                            say=say))
    ok = channel.send("CheckIn: test message") is True
    return {"delivered": ok, "log": lines}


# --- runs -------------------------------------------------------------------------------
@router.get("/runs")
def runs(start: datetime.date | None = Query(None, alias="from"), end: datetime.date | None = Query(None, alias="to"),
         who: Caller = Depends(READ), db=Depends(get_db)):
    today = local_today(who.user)
    return service.list_runs(db, who.user, start or today - datetime.timedelta(days=7), end or today)


@router.get("/runs/{run_id}/log")
def run_log(run_id: int, who: Caller = Depends(READ), db=Depends(get_db)):
    return service.run_log(db, who.user, run_id)


class ClockNowIn(BaseModel):
    location: Literal["home", "office"] | None = None
    confirm: bool = Field(False, description="Must be true: this records a real clock event.")


@router.post("/actions/{action}", status_code=202)
def clock_now(request: Request, action: str, body: ClockNowIn, who: Caller = Depends(WRITE), db=Depends(get_db)):
    """Clock an action now, outside the schedule. Records a real event."""
    if not body.confirm:
        raise HTTPException(400, "set confirm to true: this records a real clock event")
    run = service.prepare_manual_run(db, who.user, who.actor, action, body.location, _now())
    db.commit()
    started = _state(request).scheduler.run_now(run.id, who.user.id)
    return {"run_id": run.id, "started": started}


# --- tokens -------------------------------------------------------------------------------
class TokenIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scopes: list[Literal["read", "write", "admin"]] = ["read"]
    expires_in_days: int | None = Field(None, ge=1, le=3650)


@router.get("/tokens")
def tokens(who: Caller = Depends(READ), db=Depends(get_db)):
    return service.list_tokens(db, who.user)


@router.post("/tokens", status_code=201)
def create_token(body: TokenIn, who: Caller = Depends(WRITE), db=Depends(get_db)):
    """The token is in the answer once; only its hash is kept."""
    if not auth.scopes_allow(who.scopes, max(body.scopes, key=auth.SCOPES.index)):
        raise HTTPException(403, "a token can't have more scopes than the caller")
    try:
        row, token = auth.create_token(db, who.user, body.name, body.scopes, auth.expires_in(body.expires_in_days))
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    auth.audit(db, who.user.id, who.actor, "token.create", prefix=row.prefix, scopes=row.scopes)
    return {**service.token_view(row), "token": token}


@router.delete("/tokens/current", status_code=204)
def revoke_current_token(who: Caller = Depends(READ), db=Depends(get_db)):
    """Revoke the token this request was made with (signing an agent out)."""
    if not who.via.startswith("token "):
        raise HTTPException(400, "this request was not made with a token")
    row = db.scalar(select(ApiToken).where(ApiToken.prefix == who.via.removeprefix("token ")))
    row.revoked_at = _now()
    auth.audit(db, who.user.id, who.actor, "token.revoke", prefix=row.prefix)


@router.delete("/tokens/{token_id}", status_code=204)
def revoke_token(token_id: int, who: Caller = Depends(WRITE), db=Depends(get_db)):
    row = service.owned(db, ApiToken, token_id, who.user, "token")
    row.revoked_at = _now()
    auth.audit(db, who.user.id, who.actor, "token.revoke", prefix=row.prefix)


# --- agents signing in (device flow, D-028) -------------------------------------------------
class DeviceCodeIn(BaseModel):
    client_name: str = Field("An agent", max_length=60, description="Shown to the person who approves.")
    scopes: list[Literal["read", "write", "admin"]] = ["read", "write"]


class DeviceTokenIn(BaseModel):
    device_code: str = Field(..., max_length=100)


def _device_error(e):
    status = 429 if e.code == "slow_down" else 400
    return JSONResponse({"error": e.code, "error_description": e.description}, status_code=status)


@router.post("/device/code")
def device_code(request: Request, body: DeviceCodeIn, db=Depends(get_db)):
    """Start signing an agent in. No authentication: show the person
    `verification_uri_complete` (or `verification_uri` and `user_code`), then
    poll `/device/token` every `interval` seconds."""
    s, address = _state(request), client_address(request)
    if not s.device_starts.hit(address):
        raise HTTPException(429, "too many sign-in codes from this address; wait a few minutes")
    try:
        row, code = device.start(db, body.client_name, body.scopes, address)
    except device.DeviceError as e:
        return _device_error(e)
    base = app_url(request)
    shown = device.show_user_code(row.user_code)
    return {"device_code": code, "user_code": shown, "verification_uri": f"{base}/device",
            "verification_uri_complete": f"{base}/device?code={shown}",
            "expires_in": int(device.LIFETIME.total_seconds()), "interval": device.INTERVAL}


@router.post("/device/token")
def device_token(body: DeviceTokenIn, db=Depends(get_db)):
    """Poll for the token. Until the person approves, a 400 with `error`
    `authorization_pending` (keep polling), `slow_down` (429: poll less often),
    `access_denied` or `expired_token` (stop). Then the token, once."""
    try:
        user, row, token = device.poll(db, body.device_code)
    except device.DeviceError as e:
        db.commit()  # keep last_polled_at, so slow_down works
        return _device_error(e)
    return {"access_token": token, "token_type": "Bearer", "scopes": row.scopes.split(","),
            "expires_at": row.expires_at.isoformat() + "Z", "username": user.username,
            "token_prefix": row.prefix}


# --- the skill for AI agents (D-028) ---------------------------------------------------------
def app_url(request):
    return (_state(request).settings.public_url or str(request.base_url)).rstrip("/")


@router.get("/skill")
def skill_info(request: Request, who: Caller = Depends(READ)):
    """The newest skill: version, sha256 and size of `/skill/checkin.zip`."""
    return skill.info(app_url(request))


@router.get("/skill/checkin.zip")
def skill_zip(request: Request, who: Caller = Depends(READ)):
    return Response(skill.zip_bytes(app_url(request)), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="checkin-skill.zip"'})


# --- admin ----------------------------------------------------------------------------------
class NewUserIn(BaseModel):
    username: str
    password: str | None = None
    email: str | None = None
    role: Literal["user", "admin"] = "user"


@router.get("/admin/users")
def admin_users(who: Caller = Depends(ADMIN), db=Depends(get_db)):
    return [service.profile(u) for u in db.scalars(select(User).order_by(User.id))]


@router.post("/admin/users", status_code=201)
def admin_create_user(request: Request, body: NewUserIn, who: Caller = Depends(ADMIN), db=Depends(get_db)):
    user = service.create_user(db, _state(request).settings, who.actor, body.username, body.password, body.email,
                               body.role)
    return service.profile(user)


@router.patch("/admin/users/{user_id}")
def admin_update_user(request: Request, user_id: int, body: dict[str, Any] = Body(...),
                      who: Caller = Depends(ADMIN), db=Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "user not found")
    out = service.admin_update_user(db, who.actor, user, body)
    db.flush()
    _replan(request, user, db)
    return out


@router.get("/admin/runs")
def admin_runs(status: str | None = None, days: int = Query(7, ge=1, le=90), who: Caller = Depends(ADMIN),
               db=Depends(get_db)):
    since = datetime.date.today() - datetime.timedelta(days=days)
    q = select(PlannedRun).where(PlannedRun.date >= since)
    if status:
        q = q.where(PlannedRun.status == status)
    return [dict(service.run_view(r), user_id=r.user_id) for r in db.scalars(q.order_by(PlannedRun.planned_at))]


@router.get("/admin/stats")
def admin_stats(who: Caller = Depends(ADMIN), db=Depends(get_db)):
    users = dict(db.execute(select(User.status, func.count()).group_by(User.status)).all())
    since = datetime.date.today() - datetime.timedelta(days=7)
    runs = dict(db.execute(select(PlannedRun.status, func.count()).where(PlannedRun.date >= since)
                           .group_by(PlannedRun.status)).all())
    return {"users": users, "runs_last_7_days": runs}
