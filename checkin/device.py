"""Signing in an agent without its ever seeing a password (D-028).

The OAuth 2.0 device authorization grant (RFC 8628), cut down to what CheckIn
needs:

1. The agent calls `start()` (POST /api/v1/device/code) and gets a long device
   code, which it keeps, and a short user code, which it shows the person with
   the address of the approval page.
2. The person opens that page in a browser where they are signed in, checks the
   code and the agent's name, and approves (`approve()`) or denies it.
3. The agent polls `poll()` (POST /api/v1/device/token) every few seconds. Once
   approved, the next poll creates an ordinary personal access token, returns
   it once and marks the grant used. Only hashes are stored, as for any token.

Codes live 10 minutes. The token expires after TOKEN_DAYS and shows up, and can
be revoked, on the API tokens page like any other.
"""
import datetime
import hashlib
import secrets

from sqlalchemy import delete, select

from checkin import auth
from checkin.db.models import DeviceGrant, User, utcnow

LIFETIME = datetime.timedelta(minutes=10)
INTERVAL = 5  # seconds the agent waits between polls
TOKEN_DAYS = 90
USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ"  # no vowels (no words), no look-alikes (RFC 8628 6.1)
USER_CODE_LENGTH = 8


class DeviceError(Exception):
    """An RFC 8628 error code (`authorization_pending`, `slow_down`,
    `access_denied`, `expired_token`, `invalid_grant`, `invalid_request`)."""

    def __init__(self, code, description=""):
        super().__init__(code)
        self.code, self.description = code, description


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalise_user_code(text):
    """"bcdf-ghjk", "BCDF GHJK" -> "BCDFGHJK"; anything else -> ""."""
    code = "".join(c for c in (text or "").upper() if c.isalnum())
    ok = len(code) == USER_CODE_LENGTH and all(c in USER_CODE_ALPHABET for c in code)
    return code if ok else ""


def show_user_code(code):
    return f"{code[:4]}-{code[4:]}"


def start(db, client_name, scopes, client_ip=None, now=None):
    """A new pending grant; returns (row, device code). Clears out old grants."""
    scopes = list(dict.fromkeys(scopes or ["read", "write"]))
    bad = [s for s in scopes if s not in auth.SCOPES]
    if bad or not scopes:
        raise DeviceError("invalid_scope", f"scopes must be some of {', '.join(auth.SCOPES)}")
    name = " ".join((client_name or "").split())[:60] or "An agent"
    now = now or utcnow()
    db.execute(delete(DeviceGrant).where(DeviceGrant.expires_at < now - datetime.timedelta(days=1)))
    device_code = secrets.token_urlsafe(32)
    while True:
        user_code = "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(USER_CODE_LENGTH))
        if db.scalar(select(DeviceGrant.id).where(DeviceGrant.user_code == user_code)) is None:
            break
    row = DeviceGrant(device_code_hash=_digest(device_code), user_code=user_code, client_name=name,
                      scopes=",".join(sorted(scopes, key=auth.SCOPES.index)), client_ip=(client_ip or "")[:64],
                      status="pending", created_at=now, expires_at=now + LIFETIME)
    db.add(row)
    db.flush()
    return row, device_code


def pending(db, user_code, now=None):
    """The pending, unexpired grant with this user code, or None."""
    code = normalise_user_code(user_code)
    if not code:
        return None
    row = db.scalar(select(DeviceGrant).where(DeviceGrant.user_code == code))
    if row is None or row.status != "pending" or row.expires_at <= (now or utcnow()):
        return None
    return row


def approve(db, row, user, scopes, actor):
    """The person allows the agent `scopes` (no more than it asked for, nor
    more than the person may have)."""
    allowed = [s for s in scopes if s in row.scopes.split(",")]
    if "admin" in allowed and user.role != "admin":
        allowed.remove("admin")
    if not allowed:
        raise DeviceError("invalid_scope", "choose at least one scope")
    row.status, row.user_id = "approved", user.id
    row.granted_scopes = ",".join(sorted(allowed, key=auth.SCOPES.index))
    auth.audit(db, user.id, actor, "device.approve", client=row.client_name, scopes=row.granted_scopes,
               ip=row.client_ip)


def deny(db, row, user, actor):
    row.status, row.user_id = "denied", user.id
    auth.audit(db, user.id, actor, "device.deny", client=row.client_name, ip=row.client_ip)


def poll(db, device_code, now=None):
    """The agent asks whether it may have its token. Returns (user, token row,
    token text) once, after approval; raises DeviceError otherwise."""
    now = now or utcnow()
    row = db.scalar(select(DeviceGrant).where(DeviceGrant.device_code_hash == _digest(device_code or "")))
    if row is None or row.status == "issued":
        raise DeviceError("invalid_grant", "unknown or already used device code")
    if row.expires_at <= now:
        raise DeviceError("expired_token", "the code expired; start again")
    if row.status == "denied":
        raise DeviceError("access_denied", "the person said no")
    too_soon = row.last_polled_at and (now - row.last_polled_at).total_seconds() < INTERVAL - 1
    row.last_polled_at = now
    if row.status == "pending":
        raise DeviceError("slow_down" if too_soon else "authorization_pending")
    user = db.get(User, row.user_id)
    if user is None or user.status != "active":
        raise DeviceError("access_denied", "the account is not active")
    token_row, token = auth.create_token(db, user, f"Agent: {row.client_name}"[:100], row.granted_scopes.split(","),
                                         now + datetime.timedelta(days=TOKEN_DAYS))
    row.status, row.token_id = "issued", token_row.id
    auth.audit(db, user.id, f"{user.username} (device)", "token.create", prefix=token_row.prefix,
               scopes=token_row.scopes, client=row.client_name)
    return user, token_row, token
