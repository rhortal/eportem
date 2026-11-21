"""Passwords, personal access tokens, rate limits and the audit log (D-006).

- Passwords: argon2id (argon2-cffi defaults).
- Tokens: `ept_<prefix>_<secret>`. Only sha256(token) is stored, with the
  prefix in clear so a token can be recognised in a list. Shown once.
  Scopes: read, write, admin (admin implies write implies read).
"""
import datetime
import hashlib
import hmac
import secrets
import threading
import time
from collections import deque

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select

from checkin.db.models import ApiToken, AuditEvent, User, utcnow

SCOPES = ("read", "write", "admin")
TOKEN_PREFIX = "ept"  # noqa: S105 (a label, not a secret)
MIN_PASSWORD_LENGTH = 10

_hasher = PasswordHasher()
# Verifying against this when the user doesn't exist keeps the timing the same.
_DUMMY_HASH = _hasher.hash("not a real password")


def hash_password(password):
    problems = password_problems(password)
    if problems:
        raise ValueError("; ".join(problems))
    return _hasher.hash(password)


def password_problems(password):
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        return [f"the password must have at least {MIN_PASSWORD_LENGTH} characters"]
    return []


def check_password(db, username, password):
    """The active User for these credentials, or None. Rehashes old hashes."""
    user = db.scalar(select(User).where(User.username == username))
    stored = user.password_hash if user and user.password_hash else _DUMMY_HASH
    try:
        _hasher.verify(stored, password or "")
    except (VerificationError, InvalidHashError):
        return None
    if user is None or not user.password_hash or user.status != "active":
        return None
    if _hasher.check_needs_rehash(stored):
        user.password_hash = _hasher.hash(password)
    return user


def _digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def scopes_allow(granted, needed):
    """admin > write > read."""
    rank = {s: i for i, s in enumerate(SCOPES)}
    return max((rank[s] for s in granted if s in rank), default=-1) >= rank[needed]


def create_token(db, user, name, scopes=("read",), expires_at=None):
    """Store a new token; returns (row, the token text, shown only now)."""
    bad = [s for s in scopes if s not in SCOPES]
    if bad or not scopes:
        raise ValueError(f"scopes must be some of {', '.join(SCOPES)}")
    if "admin" in scopes and user.role != "admin":
        raise ValueError("only admins can create admin tokens")
    prefix = secrets.token_hex(4)
    token = f"{TOKEN_PREFIX}_{prefix}_{secrets.token_urlsafe(32)}"
    row = ApiToken(user_id=user.id, name=name, prefix=prefix, token_hash=_digest(token),
                   scopes=",".join(sorted(set(scopes), key=SCOPES.index)), expires_at=expires_at)
    db.add(row)
    db.flush()
    return row, token


def find_token(db, token, now=None):
    """(User, ApiToken) for a valid, unrevoked, unexpired token of an active
    user, else None. Records when it was last used."""
    parts = (token or "").split("_", 2)  # the secret part may itself contain "_"
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        return None
    row = db.scalar(select(ApiToken).where(ApiToken.prefix == parts[1]))
    if row is None or not hmac.compare_digest(row.token_hash, _digest(token)):
        return None
    now = now or utcnow()
    if row.revoked_at or (row.expires_at and row.expires_at <= now):
        return None
    user = db.get(User, row.user_id)
    if user is None or user.status != "active":
        return None
    row.last_used_at = now
    return user, row


def audit(db, user_id, actor, event, **detail):
    """Record who changed what. Never store secrets in detail."""
    db.add(AuditEvent(user_id=user_id, actor=actor, kind=event, detail=detail or None))


class RateLimiter:
    """At most `limit` events per `window` seconds per key (in memory, per process)."""

    def __init__(self, limit, window):
        self.limit, self.window = limit, window
        self._events = {}
        self._lock = threading.Lock()

    def hit(self, key, now=None):
        """Count an event; False when the key is over its limit."""
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._events.setdefault(key, deque())
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def blocked(self, key, now=None):
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._events.get(key, deque())
            while q and now - q[0] > self.window:
                q.popleft()
            return len(q) >= self.limit

    def reset(self, key):
        with self._lock:
            self._events.pop(key, None)


def expires_in(days):
    return utcnow() + datetime.timedelta(days=days) if days else None
