"""Where an ePortem session (cookies, login time, browser User-Agent) is kept.

A store has load() -> dict or None (nothing saved), raising on a corrupt
record, and save(dict). The dict is {"logged_in_at", "last_used_at",
"user_agent", "cookies": [{"name", "value", "domain", "path"}]}.
"""
import datetime
import json
import os
import tempfile
from pathlib import Path


class MemoryCookieStore:
    """Keeps the session in memory (tests, dry runs)."""

    def __init__(self, data=None):
        self.data = data

    def describe(self):
        return "the saved session"

    def load(self):
        return self.data

    def save(self, data):
        self.data = data


class FileCookieStore:
    """A JSON file, written atomically with mode 600. An older plain list of
    cookies is still read, its mtime taken as the login time."""

    def __init__(self, path):
        self.path = Path(path)

    def describe(self):
        return f"the saved session file {self.path.name}"

    def load(self):
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text())
        if isinstance(data, list):
            data = {"cookies": data, "last_used_at": None,
                    "logged_in_at": datetime.datetime.fromtimestamp(self.path.stat().st_mtime).isoformat()}
        return data

    def save(self, data):
        """Written to a temp file with mode 600 and renamed over the old one, so a
        crash can't leave it truncated."""
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=self.path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps(data))
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
