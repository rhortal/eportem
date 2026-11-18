"""Turn a person's database rows into a ready-to-run ClockAction, and alerts."""
import threading

from sqlalchemy import select

from eportem.core import browser
from eportem.core.actions import ClockAction
from eportem.core.notify import NotificationManager, SlackChannel, SlackStatusUpdater, TelegramChannel
from eportem.core.target import Target
from eportem.db.models import EportemAccount, NotificationChannelRow
from eportem.db.repo import DbCookieStore, activity_ids


class _GatedDriver:
    """A webdriver that gives its browser slot back when it quits."""

    def __init__(self, driver, release):
        self._driver, self._release, self._released = driver, release, False

    def quit(self):
        try:
            self._driver.quit()
        finally:
            if not self._released:
                self._released = True
                self._release()

    def __getattr__(self, name):
        return getattr(self._driver, name)


class BrowserGate:
    """At most `limit` browsers at once across all runs (they are the heavy part)."""

    def __init__(self, limit):
        self._slots = threading.BoundedSemaphore(limit)

    def wrap(self, make_driver):
        def gated():
            self._slots.acquire()
            try:
                return _GatedDriver(make_driver(), self._slots.release)
            except BaseException:
                self._slots.release()
                raise
        return gated


class Engine:
    """How runs reach ePortem: the target site, how browsers start and log in.
    Tests swap make_driver/login_for (e.g. for the fake and a requests login)."""

    def __init__(self, settings, make_driver=None, login_for=None):
        self.target = Target(settings.target_url)
        self.gate = BrowserGate(settings.browser_concurrency)
        user_agent = settings.browser_user_agent or browser.USER_AGENT
        self._make_driver = make_driver or (lambda: browser.create_driver(
            headless=settings.headless, user_agent=user_agent, binary_location=settings.chromium_path,
            say=lambda *a: None, sandbox=settings.browser_sandbox, driver_path=settings.chromedriver_path))
        self._login_for = login_for or (lambda u, p: (lambda d: (browser.login(d, u, p), d)[1]))

    def make_driver(self):
        return self.gate.wrap(self._make_driver)()

    def login_for(self, username, password):
        return self._login_for(username, password)


def channels_for(db, box, user_id, purpose, say):
    """Core channel objects for a person: purpose 'notify' or 'alerts'."""
    rows = db.scalars(select(NotificationChannelRow).where(NotificationChannelRow.user_id == user_id))
    out = []
    for row in rows:
        if not getattr(row, purpose):
            continue
        cfg = box.decrypt_json(row.config_enc)
        if row.kind == "telegram":
            out.append(TelegramChannel(cfg.get("token"), cfg.get("chat_id"), say=say))
        elif row.kind == "slack":
            out.append(SlackChannel(cfg.get("webhook_url"), cfg.get("user_token"), cfg.get("channel"),
                                    cfg.get("bot_token"), say=say))
    return out


def status_updater_for(db, box, user_id, say):
    for row in db.scalars(select(NotificationChannelRow).where(
            NotificationChannelRow.user_id == user_id, NotificationChannelRow.kind == "slack",
            NotificationChannelRow.slack_status.is_(True))):
        token = box.decrypt_json(row.config_enc).get("user_token")
        if token:
            return SlackStatusUpdater(token, say=say)
    return None


def secrets_for(db, box, user_id):
    values = []
    account = db.get(EportemAccount, user_id)
    if account:
        values.append(box.decrypt(account.password_enc))
    for row in db.scalars(select(NotificationChannelRow).where(NotificationChannelRow.user_id == user_id)):
        values += [v for v in box.decrypt_json(row.config_enc).values() if isinstance(v, str) and len(v) > 6]
    return values


def build_action(db, sessionmaker, box, engine, user, run, plan, say, record, log_run):
    """The ClockAction for one planned run. Raises ValueError when the person's
    ePortem account isn't usable yet."""
    account = db.get(EportemAccount, user.id)
    ids = activity_ids(account)
    if account is None or ids is None:
        raise ValueError("the ePortem account or its activity IDs are not set up")
    password = box.decrypt(account.password_enc)
    login = engine.login_for(account.username, password)
    store = DbCookieStore(sessionmaker, user.id, box)

    def http_clock():
        from eportem.core.clock_http import HttpClock
        return HttpClock(target=engine.target, activity_ids=ids, cookie_store=store,
                         make_driver=engine.make_driver, login_driver=login, say=action.say)

    def relay(*args, **kwargs):  # into this run's log, whatever say the action has then
        action.say(*args, **kwargs)

    channels = channels_for(db, box, user.id, "notify", relay)
    updater = status_updater_for(db, box, user.id, relay)
    action = ClockAction(
        run.action, run.location, activity_ids=ids, target=engine.target,
        make_driver=engine.make_driver, login_driver=login, http_clock=http_clock,
        use_http=account.use_http, channels=lambda: channels, status_updater=lambda: updater,
        business_trip_end=lambda: plan.business_trip_end if plan else None,
        record=record, log_run=log_run, secrets=secrets_for(db, box, user.id), say=say)
    return action


def send_alert(db, box, user_id, text):
    """Tell the person on their alert channels. Never raises; returns the
    channels that failed."""
    try:
        manager = NotificationManager(say=lambda *a: None)
        for ch in channels_for(db, box, user_id, "alerts", say=lambda *a: None):
            manager.register_channel(ch)
        return manager.notify(text)
    except Exception:
        return ["alerts"]
