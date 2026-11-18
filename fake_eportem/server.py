"""The fake ePortem HTTP server (standard library only)."""
import datetime
import json
import secrets
import socket
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit

from eportem.core.activities import ActivityIds
from fake_eportem import pages

LOGIN_PATH = "/Usuario/Login"
DASHBOARD_PATH = "/aplicaciones/e-portem/registro/"
CLOCK_PATH = DASHBOARD_PATH + "reghorario.cshtml"
AUTH_COOKIE = ".ASPXAUTH"

# The activity IDs on the owner's account (from the captures). Other accounts in
# tests should use different ones, so nothing comes to depend on these.
CAPTURED_IDS = ActivityIds(office="1", home="1293", lunch_pause="2")


@dataclass
class Account:
    username: str
    password: str
    activity_ids: ActivityIds = CAPTURED_IDS
    state: str = "not_started"          # not_started, working, paused, stopped
    working_activity: str | None = None
    last_activity: str = ""
    logins: int = 0                      # successful logins
    login_attempts: int = 0              # every form submission


@dataclass
class Fault:
    """A failure to inject.

    where: "login" (form submission), "dashboard" or "clock".
    kind:  "error_500", "maintenance" (a 200 page without the clock box),
           "drop" (close the connection without answering), "slow" (wait
           `delay` seconds, then answer normally), "captcha" (login only:
           reject with the reCAPTCHA error).
    record: for "clock" faults, record the event before failing.
    times: how many requests it applies to.
    skip: let this many matching requests through first.
    username: only for this account (default: any).
    """
    where: str
    kind: str
    record: bool = False
    delay: float = 0.0
    times: int = 1
    skip: int = 0
    username: str | None = None


@dataclass
class _Session:
    username: str
    created: float = field(default_factory=time.monotonic)


class FakeEportem:
    def __init__(self, accounts, recaptcha=False, session_ttl=None, host="127.0.0.1", port=0):
        self.accounts = {a.username.upper(): a for a in accounts}
        self.recaptcha = recaptcha
        self.session_ttl = session_ttl
        self.events = []
        self.faults = []
        self.paths = []  # every path requested, in order
        self._sessions = {}
        self._lock = threading.RLock()
        self._server = ThreadingHTTPServer((host, port), _handler_for(self))
        self._server.daemon_threads = True
        self._thread = None

    # --- lifecycle -------------------------------------------------------
    @property
    def base_url(self):
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self):
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05},
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # --- test controls ---------------------------------------------------
    def add_fault(self, fault):
        with self._lock:
            self.faults.append(fault)

    def expire_sessions(self, username=None):
        with self._lock:
            for token, s in list(self._sessions.items()):
                if username is None or s.username == username.upper():
                    del self._sessions[token]

    def events_for(self, username):
        with self._lock:
            return [e for e in self.events if e["username"] == username.upper()]

    def reset(self):
        with self._lock:
            self.events.clear()
            self.faults.clear()
            self._sessions.clear()
            for a in self.accounts.values():
                a.state, a.working_activity, a.last_activity = "not_started", None, ""
                a.logins = a.login_attempts = 0

    # --- internals -------------------------------------------------------
    def _take_fault(self, where, username):
        with self._lock:
            for f in self.faults:
                if f.where == where and (f.username is None or f.username.upper() == (username or "")):
                    if f.skip > 0:
                        f.skip -= 1
                        return None
                    f.times -= 1
                    if f.times <= 0:
                        self.faults.remove(f)
                    return f
        return None

    def _session_user(self, token):
        with self._lock:
            s = self._sessions.get(token or "")
            if not s:
                return None
            if self.session_ttl is not None and time.monotonic() - s.created > self.session_ttl:
                del self._sessions[token]
                return None
            return self.accounts.get(s.username)

    def _login(self, form):
        """Returns (account, error)."""
        username = (form.get("usuario") or "").strip().upper()
        with self._lock:
            account = self.accounts.get(username)
            if account:
                account.login_attempts += 1
            if self.recaptcha and not form.get("recaptchaToken"):
                return None, pages.CAPTCHA_ERROR
            fault = self._take_fault("login", username)
            if fault and fault.kind == "captcha":
                return None, pages.CAPTCHA_ERROR
            if not account or form.get("password") != account.password:
                return None, "Usuario o contraseña incorrectos."
            account.logins += 1
            return account, None

    def _new_session(self, account):
        token = secrets.token_hex(16)
        with self._lock:
            self._sessions[token] = _Session(account.username.upper())
        return token

    def _clock(self, account, query, record=True):
        """Apply a clock request; returns the JSON answer."""
        action = query.get("action", "")
        code = query.get("_codactiv", "")
        kind = query.get("_tipoactiv", "")
        label = query.get("_descactiv", "")
        with self._lock:
            offered = pages.buttons_for(account.state, account)
            if not any(b[0] == action and (b[1] or "") == code for b in offered):
                return {"Message": "Acción no disponible"}
            if not record:
                return None
            if action == "_ststart":
                account.state = "paused" if kind == "P" else "working"
                account.working_activity = code if kind != "P" else None
            elif action == "_stpause":
                account.state = "paused"
            elif action == "_stini":
                account.state, account.working_activity = "working", code
            elif action == "_ststop":
                account.state = "stopped"
            account.last_activity = label
            self.events.append({
                "username": account.username.upper(), "action": action, "codactiv": code,
                "tipoactiv": kind, "descactiv": label, "state": account.state,
                "at": datetime.datetime.now().isoformat(timespec="seconds"),
            })
            entries = "".join(pages._entry(*b) for b in pages.buttons_for(account.state, account))
            active = {"working": "W", "paused": "P"}.get(account.state, "N")
            return {"isActive": active, "LastDescAct": label, "listActiv": entries}


def _handler_for(fake):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Microsoft-IIS/10.0"
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # quiet in tests
            pass

        # --- helpers -----------------------------------------------------
        def _cookie(self, name):
            for part in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == name:
                    return v
            return None

        def _send(self, status, body, content_type="text/html; charset=utf-8", headers=()):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            for k, v in headers:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _redirect(self, location, headers=()):
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            for k, v in headers:
                self.send_header(k, v)
            self.end_headers()

        def _drop(self):
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        def _apply_fault(self, fault):
            """Returns True when the fault answered the request."""
            if fault is None:
                return False
            if fault.kind == "slow":
                time.sleep(fault.delay)
                return False
            if fault.kind == "error_500":
                self._send(500, "<h1>Server Error in '/' Application.</h1>")
            elif fault.kind == "maintenance":
                self._send(200, pages.maintenance_page())
            elif fault.kind == "drop":
                self._drop()
            else:
                return False
            return True

        def _account_or_login(self, path):
            account = fake._session_user(self._cookie(AUTH_COOKIE))
            if account is None:
                self._redirect(f"{LOGIN_PATH}?ReturnUrl={quote(path, safe='').lower()}")
            return account

        # --- routes ------------------------------------------------------
        def do_GET(self):  # noqa: N802 (http.server's name)
            url = urlsplit(self.path)
            with fake._lock:
                fake.paths.append(url.path)
            query = {k: v[0] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
            if url.path == LOGIN_PATH:
                self._send(200, pages.login_page(fake.recaptcha))
            elif url.path == "/_fake/recaptcha/api.js":
                self._send(200, pages.RECAPTCHA_JS, "application/javascript")
            elif url.path == "/_fake/events":
                with fake._lock:
                    self._send(200, json.dumps(fake.events), "application/json")
            elif url.path in ("/aplicaciones", "/aplicaciones/"):
                # Where the login lands. The real one shows the clock box (the
                # Selenium flow finds its button there straight after logging in);
                # eportem.contract checks that on the real site.
                if self._account_or_login("/aplicaciones"):
                    self._redirect(DASHBOARD_PATH)
            elif url.path == DASHBOARD_PATH:
                account = self._account_or_login(DASHBOARD_PATH)
                if account and not self._apply_fault(fake._take_fault("dashboard", account.username.upper())):
                    self._send(200, pages.dashboard_page(account.state, account))
            elif url.path == CLOCK_PATH:
                account = self._account_or_login(DASHBOARD_PATH)
                if account:
                    self._clock_route(account, query)
            else:
                self._send(200, "<html><body>Página no encontrada</body></html>")

        def _clock_route(self, account, query):
            fault = fake._take_fault("clock", account.username.upper())
            if fault and fault.kind == "slow":
                time.sleep(fault.delay)
                fault = None
            if fault:
                if fault.record:
                    fake._clock(account, query)
                self._apply_fault(fault)
                return
            result = fake._clock(account, query)
            self._send(200, json.dumps(result), "application/json; charset=utf-8")

        def do_POST(self):  # noqa: N802
            url = urlsplit(self.path)
            with fake._lock:
                fake.paths.append(url.path)
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode("utf-8") if length else ""
            if url.path == LOGIN_PATH:
                form = {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}
                account, error = fake._login(form)
                if error:
                    self._send(200, pages.login_page(fake.recaptcha, error))
                    return
                token = fake._new_session(account)
                target = parse_qs(url.query).get("ReturnUrl", ["/aplicaciones"])[0] or "/aplicaciones"
                self._redirect(target, headers=[
                    ("Set-Cookie", f"{AUTH_COOKIE}={token}; path=/; HttpOnly"),
                    ("Set-Cookie", f"ASP.NET_SessionId={secrets.token_hex(8)}; path=/; HttpOnly"),
                ])
            elif url.path == "/_fake/reset":
                fake.reset()
                self._send(200, "{}", "application/json")
            elif url.path == "/_fake/faults":
                fake.add_fault(Fault(**json.loads(body or "{}")))
                self._send(200, "{}", "application/json")
            elif url.path == "/_fake/expire":
                fake.expire_sessions(json.loads(body or "{}").get("username"))
                self._send(200, "{}", "application/json")
            else:
                self._send(404, "not found")

    return Handler
