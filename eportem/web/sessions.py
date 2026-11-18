"""Web sign-in sessions and CSRF protection.

The cookie holds a random id; the database keeps only its sha256 (a stolen
database can't be replayed as cookies). Every state-changing request made with
the cookie must carry the CSRF token: a hidden `csrf` form field, or the
`X-CSRF-Token` header (htmx sends it from the page). The token is an HMAC of
the session id with the instance key, so it needs no storage.
"""
import datetime
import hashlib
import hmac
import secrets

from sqlalchemy import delete

from eportem.db.models import User, WebSession, utcnow

COOKIE = "eportem_session"
LIFETIME = datetime.timedelta(days=14)
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def start(db, user, ip=None, user_agent=None):
    """A new session for `user`; returns the cookie value."""
    value = secrets.token_urlsafe(32)
    db.add(WebSession(id_hash=_digest(value), user_id=user.id, expires_at=utcnow() + LIFETIME,
                      ip=ip, user_agent=(user_agent or "")[:300]))
    return value


def load(db, value):
    """The active User for a cookie value, or None. Expired sessions are removed."""
    if not value:
        return None
    row = db.get(WebSession, _digest(value))
    if row is None:
        return None
    if row.expires_at <= utcnow():
        db.delete(row)
        return None
    user = db.get(User, row.user_id)
    return user if user and user.status == "active" else None


def end(db, value):
    if value:
        db.execute(delete(WebSession).where(WebSession.id_hash == _digest(value)))


def end_all(db, user_id):
    db.execute(delete(WebSession).where(WebSession.user_id == user_id))


def csrf_token(secret_key, value):
    return hmac.new(secret_key.encode("utf-8"), f"csrf:{value}".encode(), hashlib.sha256).hexdigest()


def csrf_ok(secret_key, value, presented):
    return bool(value and presented) and hmac.compare_digest(csrf_token(secret_key, value), presented)
