"""logs/actions.log: one line per clock action that was recorded, so that
`main.py --verify-day` can tell at the end of the day what is missing.

Line format (space separated): ISO timestamp, date, action, location, how
(http or browser). Kept apart from http_clock.log because that one is
free text; this one must stay easy to parse. Both rotate (utility/logfiles.py).
"""
import datetime

from utility import logfiles
from utility.paths import state_dir


def actions_log_path():
    return str(state_dir() / "logs" / "actions.log")


def record_action(action, location, how, now=None):
    """Append one line. Never raises: a logging problem must not change the
    outcome of a clock action that is already recorded."""
    try:
        path = actions_log_path()
        now = now or datetime.datetime.now()
        logfiles.append(
            path, f"{now:%Y-%m-%dT%H:%M:%S} {now:%Y-%m-%d} {action} {location} {how}\n")
    except Exception as e:
        print(f"Could not write actions.log: {e}")


def actions_recorded_on(date):
    """The actions recorded on `date`, oldest first (an action twice appears
    twice). Reads the rotated generations too, so a rotation in the middle of
    the day can't make a recorded action look missing. A missing file means
    none; unparseable lines are ignored."""
    path = actions_log_path()
    found = []
    for p in [*reversed(logfiles.generation_paths(path)), path]:
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 3 and parts[1] == date.isoformat():
                        found.append(parts[2])
        except FileNotFoundError:
            pass
    return found
