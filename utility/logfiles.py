"""Append to a log file with private permissions and size-based rotation.

Shared by logs/http_clock.log and logs/actions.log, so both are 0600 in a 0700
folder and neither grows without bound. (logs/capture.log is written by a shell
redirect in an `at` job, so it is not covered here.)
"""
import contextlib
import os

MAX_BYTES = 1_000_000
GENERATIONS = 5  # name.1 (newest) ... name.N (oldest); older ones are dropped


def generation_paths(path, generations=None):
    """The rotated files that exist, newest first (name.1, name.2, ...)."""
    generations = GENERATIONS if generations is None else generations
    found = (f"{path}.{i}" for i in range(1, generations + 1))
    return [p for p in found if os.path.exists(p)]


def rotate(path, generations=None):
    """Shift name -> name.1 -> name.2 ... dropping the oldest. A missing
    generation is skipped, so a gap never stops the shift."""
    generations = GENERATIONS if generations is None else generations
    with contextlib.suppress(FileNotFoundError):
        os.remove(f"{path}.{generations}")
    for i in range(generations - 1, 0, -1):
        with contextlib.suppress(FileNotFoundError):
            os.replace(f"{path}.{i}", f"{path}.{i + 1}")
    os.replace(path, f"{path}.1")


def append(path, text, max_bytes=None, generations=None):
    """Append text, rotating first if the file is over max_bytes. A rotation
    problem is printed and the append still goes ahead; a failure to append
    raises OSError for the caller's own guard to report. None means the
    module default (looked up per call)."""
    max_bytes = MAX_BYTES if max_bytes is None else max_bytes
    generations = GENERATIONS if generations is None else generations
    log_dir = os.path.dirname(path)
    os.makedirs(log_dir, mode=0o700, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(log_dir, 0o700)
    try:
        if os.path.getsize(path) > max_bytes:
            rotate(path, generations)
    except FileNotFoundError:
        pass
    except OSError as e:
        print(f"Could not rotate {path}: {e}")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(text)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)
