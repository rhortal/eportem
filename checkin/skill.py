"""The skill for AI agents, served by the app to people with an account (D-028).

The public website only says the skill exists; the files come from here:

- Signed in to the web UI, the API tokens page shows a text to paste into an
  agent. It holds a personal install link, `/skill/<link>/install.sh`, signed
  with the instance key for that person and valid for LINK_LIFETIME, so the
  agent can install without a password or a token in the text.
- Signed in with a token (the skill itself), `/api/v1/skill` gives the newest
  version and its checksum and `/api/v1/skill/checkin.zip` the files, which is
  how the skill updates itself.

The zip is the folder skill/checkin with a defaults.json naming this instance,
so the skill knows where to sign in. Same input, same bytes.
"""
import datetime
import functools
import hashlib
import hmac
import io
import json
import re
import time
import zipfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent / "skill"
LINK_LIFETIME = datetime.timedelta(hours=24)
ZIP_TIME = (2026, 1, 1, 0, 0, 0)  # fixed timestamps: the same files give the same checksum
_VERSION = re.compile(r'^VERSION = "([0-9.]+)"$', re.M)


def version(skill_dir=SKILL_DIR):
    match = _VERSION.search((skill_dir / "checkin" / "scripts" / "checkin.py").read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError("no VERSION in skill/checkin/scripts/checkin.py")
    return match.group(1)


@functools.lru_cache(maxsize=8)
def zip_bytes(app_url, skill_dir=SKILL_DIR):
    """The skill as a zip (folder `checkin/`), with this instance's address in
    defaults.json instead of any local one."""
    root = skill_dir / "checkin"
    files = sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts
                   and p.suffix != ".pyc" and p.relative_to(root).as_posix() != "defaults.json")
    entries = [(f"checkin/{p.relative_to(root).as_posix()}", p.read_bytes(), 0o755 if p.suffix == ".py" else 0o644)
               for p in files]
    entries.append(("checkin/defaults.json", (json.dumps({"app_url": app_url}, indent=2) + "\n").encode(), 0o644))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data, mode in sorted(entries):
            entry = zipfile.ZipInfo(name, ZIP_TIME)
            entry.external_attr, entry.compress_type = (0o100000 | mode) << 16, zipfile.ZIP_DEFLATED
            z.writestr(entry, data)
    return out.getvalue()


def info(app_url, skill_dir=SKILL_DIR):
    raw = zip_bytes(app_url, skill_dir)
    return {"name": "checkin", "version": version(skill_dir), "file": "checkin.zip",
            "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}


def _sign(secret_key, user_id, expires):
    return hmac.new(secret_key.encode(), f"skill:{user_id}:{expires}".encode(), hashlib.sha256).hexdigest()[:32]


def make_link(secret_key, user_id, now=None):
    """`<user id>.<expiry>.<signature>`: lets whoever holds it download the
    skill until it expires. Nothing else."""
    expires = int((now or time.time()) + LINK_LIFETIME.total_seconds())
    return f"{user_id}.{expires}.{_sign(secret_key, user_id, expires)}"


def check_link(secret_key, link, now=None):
    """The user id a valid, unexpired link was made for, else None."""
    parts = (link or "").split(".")
    if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    user_id, expires = int(parts[0]), int(parts[1])
    if expires < (now or time.time()) or not hmac.compare_digest(parts[2], _sign(secret_key, user_id, expires)):
        return None
    return user_id


def install_script(base, skill_dir=SKILL_DIR):
    """install.sh, downloading from `base` (the signed link's folder)."""
    return (skill_dir / "install.sh").read_text(encoding="utf-8").replace("{{BASE}}", base)
