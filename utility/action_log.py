"""logs/actions.log: one line per clock action that was recorded, so that
`main.py --verify-day` can tell at the end of the day what is missing.

Line format (space separated): ISO timestamp, date, action, location, how
(http or browser). Kept apart from http_clock.log because that one is
rotated and holds free text; this one must stay easy to parse.
"""
import contextlib
import datetime
import os

from utility.paths import state_dir


def actions_log_path():
    return str(state_dir() / "logs" / "actions.log")


def record_action(action, location, how, now=None):
    """Append one line. Never raises: a logging problem must not change the
    outcome of a clock action that is already recorded."""
    try:
        path = actions_log_path()
        now = now or datetime.datetime.now()
        log_dir = os.path.dirname(path)
        os.makedirs(log_dir, mode=0o700, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(log_dir, 0o700)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write(f"{now:%Y-%m-%dT%H:%M:%S} {now:%Y-%m-%d} {action} {location} {how}\n")
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
    except Exception as e:
        print(f"Could not write actions.log: {e}")


def actions_recorded_on(date):
    """The actions recorded on `date`, in file order (an action twice appears
    twice). A missing file means none; unparseable lines are ignored."""
    found = []
    try:
        with open(actions_log_path(), "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3 and parts[1] == date.isoformat():
                    found.append(parts[2])
    except FileNotFoundError:
        pass
    return found
