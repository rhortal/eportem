"""The service's tables (docs/refactor/PLAN.md section 3). Times are stored in
UTC; dates are the user's local dates. Columns ending in `_enc` hold text
encrypted with eportem.db.crypto.SecretBox."""
import datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow():
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user")             # admin, user
    status: Mapped[str] = mapped_column(String(16), default="active")         # pending, active, suspended
    email_verified_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    plan: Mapped[str] = mapped_column(String(32), default="free")
    timezone: Mapped[str] = mapped_column(String(64))
    locale: Mapped[str] = mapped_column(String(8))
    jitter_before_minutes: Mapped[int] = mapped_column(Integer)
    jitter_after_minutes: Mapped[int] = mapped_column(Integer)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    eportem_account: Mapped["EportemAccount | None"] = relationship(back_populates="user", uselist=False,
                                                                    cascade="all, delete-orphan")
    schedule: Mapped["UserSchedule | None"] = relationship(back_populates="user", uselist=False,
                                                           cascade="all, delete-orphan")


class ApiToken(Base):
    __tablename__ = "api_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(16), unique=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[str] = mapped_column(String(100), default="read")         # comma-separated
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)


class WebSession(Base):
    __tablename__ = "web_sessions"
    id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)        # sha256 of the cookie value
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))


class EportemAccount(Base):
    __tablename__ = "eportem_accounts"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    username: Mapped[str] = mapped_column(String(100))
    password_enc: Mapped[str] = mapped_column(Text)
    office_activity_id: Mapped[str | None] = mapped_column(String(32))
    home_activity_id: Mapped[str | None] = mapped_column(String(32))
    lunch_pause_id: Mapped[str | None] = mapped_column(String(32))
    use_http: Mapped[bool] = mapped_column(Boolean, default=True)              # HTTP first, browser fallback
    verified_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    last_login_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    user: Mapped[User] = relationship(back_populates="eportem_account")


class EportemSession(Base):
    __tablename__ = "eportem_sessions"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    data_enc: Mapped[str] = mapped_column(Text)                                # the cookie store's JSON
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ScheduleTemplate(Base):
    """A person's own templates; the built-ins live in eportem.core.templates."""
    __tablename__ = "schedule_templates"
    __table_args__ = (UniqueConstraint("user_id", "key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    days: Mapped[dict] = mapped_column(JSON)                                   # template_to_dict()["days"]


class UserSchedule(Base):
    __tablename__ = "user_schedules"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    template_key: Mapped[str] = mapped_column(String(64))                     # built-in or own
    location_weeks: Mapped[list] = mapped_column(JSON, default=list)          # [{"0": "office", ...}, ...]
    pattern_anchor: Mapped[datetime.date | None] = mapped_column(Date)        # a date in week A
    holiday_country: Mapped[str | None] = mapped_column(String(8))
    holiday_region: Mapped[str | None] = mapped_column(String(16))
    user: Mapped[User] = relationship(back_populates="schedule")


class SchedulePeriod(Base):
    __tablename__ = "schedule_periods"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    template_key: Mapped[str] = mapped_column(String(64))
    start_date: Mapped[datetime.date] = mapped_column(Date)
    end_date: Mapped[datetime.date] = mapped_column(Date)
    yearly: Mapped[bool] = mapped_column(Boolean, default=False)
    label: Mapped[str] = mapped_column(String(100), default="")


class DayChangeRow(Base):
    """time_off, location, business_trip, times, work_on_holiday; later rows win."""
    __tablename__ = "day_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    start_date: Mapped[datetime.date] = mapped_column(Date)
    end_date: Mapped[datetime.date] = mapped_column(Date)
    location: Mapped[str | None] = mapped_column(String(16))
    times: Mapped[dict | None] = mapped_column(JSON)                           # {"start": "9:00", ...}
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class LocalHoliday(Base):
    __tablename__ = "local_holidays"
    __table_args__ = (UniqueConstraint("user_id", "date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    date: Mapped[datetime.date] = mapped_column(Date)
    name: Mapped[str] = mapped_column(String(100))


class NotificationChannelRow(Base):
    """kind telegram: {"token", "chat_id"}; kind slack: {"webhook_url", "bot_token",
    "user_token", "channel"} (encrypted in config_enc)."""
    __tablename__ = "notification_channels"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    config_enc: Mapped[str] = mapped_column(Text)
    notify: Mapped[bool] = mapped_column(Boolean, default=True)                # clock notifications
    alerts: Mapped[bool] = mapped_column(Boolean, default=True)                # failures, day check
    slack_status: Mapped[bool] = mapped_column(Boolean, default=False)         # slack only
    status_texts: Mapped[dict | None] = mapped_column(JSON)                    # own status texts/emoji


class PlannedRun(Base):
    """One action for one person on one date. The unique key is what stops a
    second clock: a run is claimed by moving it from planned to running."""
    __tablename__ = "planned_runs"
    __table_args__ = (UniqueConstraint("user_id", "date", "action"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    date: Mapped[datetime.date] = mapped_column(Date, index=True)
    action: Mapped[str] = mapped_column(String(16))
    target_minute: Mapped[int] = mapped_column(Integer)                        # local minutes since midnight
    planned_at: Mapped[datetime.datetime] = mapped_column(DateTime, index=True)  # UTC, with the jitter
    location: Mapped[str] = mapped_column(String(16))
    # planned, running, recorded, not_recorded, unknown, skipped, failed, cancelled
    status: Mapped[str] = mapped_column(String(16), default="planned", index=True)
    via: Mapped[str | None] = mapped_column(String(16))                       # http, browser, legacy
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    error: Mapped[str | None] = mapped_column(Text)


class RunLog(Base):
    __tablename__ = "run_logs"
    run_id: Mapped[int] = mapped_column(ForeignKey("planned_runs.id", ondelete="CASCADE"), primary_key=True)
    outcome: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    actor: Mapped[str] = mapped_column(String(100))                            # who did it
    kind: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict | None] = mapped_column(JSON)
    at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow, index=True)


class SchedulerLock(Base):
    __tablename__ = "scheduler_lock"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    holder: Mapped[str] = mapped_column(String(100))
    heartbeat_at: Mapped[datetime.datetime] = mapped_column(DateTime)
