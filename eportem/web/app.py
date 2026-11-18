"""The FastAPI application: `/api/v1` (personal access tokens), health
endpoints, and (phase 6) the web UI. The scheduler runs in a background
thread of the same process (D-002)."""
import contextlib
import datetime
import threading

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from eportem import auth
from eportem.db.crypto import SecretBox
from eportem.db.engine import make_engine, make_sessionmaker
from eportem.db.models import SchedulerLock, User
from eportem.service import ServiceError

BAD_TOKEN_LIMIT = (30, 60)  # bad tokens per client address per minute


class AppState:
    def __init__(self, settings, sessionmaker, box, engine, scheduler):
        self.settings, self.Session, self.box, self.engine, self.scheduler = (
            settings, sessionmaker, box, engine, scheduler)
        self.bad_tokens = auth.RateLimiter(*BAD_TOKEN_LIMIT)
        self.logins = auth.RateLimiter(10, 300)  # sign-in attempts per user and per address


def _state(request: Request) -> AppState:
    return request.app.state.eportem


def get_db(request: Request):
    """One transaction per request: committed on success, rolled back on error."""
    with _state(request).Session() as db:
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise


def client_address(request):
    return request.client.host if request.client else "unknown"


class Caller:
    def __init__(self, user, scopes, via):
        self.user, self.scopes, self.via = user, scopes, via

    @property
    def actor(self):
        return f"{self.user.username} ({self.via})"


def caller(request: Request, db=Depends(get_db)):
    """The authenticated person: a bearer token, or (phase 6) a web session."""
    state = _state(request)
    address = client_address(request)
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        if state.bad_tokens.blocked(address):
            raise HTTPException(429, "too many bad tokens; wait a minute")
        found = auth.find_token(db, header[7:].strip())
        if found is None:
            state.bad_tokens.hit(address)
            raise HTTPException(401, "invalid, expired or revoked token", headers={"WWW-Authenticate": "Bearer"})
        user, token = found
        # Save last_used_at now: a request must not hold SQLite's write lock while
        # it talks to ePortem or Slack (D-019).
        db.commit()
        return Caller(user, token.scopes.split(","), f"token {token.prefix}")
    web = getattr(request.state, "web_user", None)
    if web is not None:
        return Caller(db.merge(web), ["admin"] if web.role == "admin" else ["write"], "web")
    raise HTTPException(401, "authentication required", headers={"WWW-Authenticate": "Bearer"})


def needs(scope):
    def check(who: Caller = Depends(caller)):
        if not auth.scopes_allow(who.scopes, scope):
            raise HTTPException(403, f"this needs the {scope} scope")
        if scope == "admin" and who.user.role != "admin":
            raise HTTPException(403, "admins only")
        return who
    return check


def ensure_first_admin(settings, sessionmaker):
    """EPORTEM_ADMIN_USERNAME/PASSWORD create an admin on start-up if none exists."""
    if not settings.admin_username:
        return False
    from eportem import service
    with sessionmaker.begin() as db:
        if db.scalar(select(User.id).where(User.role == "admin")):
            return False
        service.create_user(db, settings, "start-up", settings.admin_username,
                            settings.admin_password.get_secret_value(), settings.admin_email, role="admin")
        return True


def create_app(settings, sessionmaker=None, engine=None, scheduler=None, start_scheduler=False):
    from eportem.db.engine import migrate
    from eportem.scheduler.runner import Engine
    from eportem.scheduler.scheduler import Scheduler

    if sessionmaker is None:
        migrate(settings.effective_database_url)
        sessionmaker = make_sessionmaker(make_engine(settings.effective_database_url))
    box = SecretBox.from_settings(settings)
    engine = engine or Engine(settings)
    scheduler = scheduler or Scheduler(settings, sessionmaker, box, engine)
    ensure_first_admin(settings, sessionmaker)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        thread = None
        if start_scheduler:
            thread = threading.Thread(target=scheduler.run_forever, name="eportem-scheduler", daemon=True)
            thread.start()
        yield
        if thread:
            scheduler.stop()
            thread.join(timeout=30)

    app = FastAPI(title="ePortem", version="0.1.0", root_path=settings.root_path, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.eportem = AppState(settings, sessionmaker, box, engine, scheduler)

    @app.exception_handler(ServiceError)
    async def service_error(request, exc):
        return JSONResponse({"detail": exc.problems}, status_code=exc.status)

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz(request: Request):
        state = _state(request)
        problems = []
        try:
            with state.Session() as db:
                db.execute(text("SELECT 1"))
                if start_scheduler:
                    lock = db.get(SchedulerLock, "scheduler")
                    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
                    if lock is None or now - lock.heartbeat_at > datetime.timedelta(minutes=2):
                        problems.append("scheduler: no heartbeat in the last 2 minutes")
        except Exception as e:
            problems.append(f"database: {type(e).__name__}")
        if problems:
            return JSONResponse({"status": "unavailable", "problems": problems}, status_code=503)
        return {"status": "ready"}

    from eportem.web.api import router
    app.include_router(router, prefix="/api/v1")
    return app
