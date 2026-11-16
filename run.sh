#!/usr/bin/env bash
# Run main.py from the project's venv (what cron calls). Extra arguments go to
# main.py, e.g. ./run.sh --check. The exit code is main.py's.
#   ./run.sh --install   only create/repair the venv, don't run main.py
# Exit 75 means another run holds the lock and this one did nothing.
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)" || exit 1
cd "$ROOT" || exit 1

# Two overlapping runs (e.g. a slow login plus the next cron line) must not both
# clock. flock isn't available on macOS: run without a lock there.
if command -v flock >/dev/null 2>&1; then
  exec 9>"$ROOT/.run.lock" || exit 1
  if ! flock -n 9; then
    echo "Another run.sh is already running (lock: $ROOT/.run.lock); exiting without doing anything." >&2
    exit 75
  fi
fi

venv_works() {
  "$ROOT/venv/bin/python3" -c "import selenium, requests, dotenv" >/dev/null 2>&1
}

# A system Python minor upgrade leaves the venv unable to import its packages,
# so rebuild it then. It is built at its final path (a venv that is moved keeps
# stale paths in its scripts); the broken one is set aside and put back if the
# rebuild fails (no network, say), so there is still something to inspect.
if ! venv_works; then
  echo "Setting up the virtual environment..."
  OLD_VENV="$ROOT/venv.old.$$"
  if [ -e "$ROOT/venv" ] && ! mv "$ROOT/venv" "$OLD_VENV"; then
    echo "Could not move the old $ROOT/venv out of the way." >&2
    exit 1
  fi
  if ! python3 -m venv "$ROOT/venv" \
     || ! "$ROOT/venv/bin/python3" -m pip install -r "$ROOT/requirements.txt" \
     || ! venv_works; then
    rm -rf "$ROOT/venv"
    [ -e "$OLD_VENV" ] && mv "$OLD_VENV" "$ROOT/venv"
    echo "Could not build the virtual environment (see the errors above); not running main.py." >&2
    exit 1
  fi
  rm -rf "$OLD_VENV"
fi

if [ "${1:-}" = "--install" ]; then
  echo "Virtual environment is ready."
  exit 0
fi

exec "$ROOT/venv/bin/python3" "$ROOT/main.py" "$@"
