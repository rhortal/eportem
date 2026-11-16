#!/usr/bin/env bash
# Run the whole test suite; extra arguments go to unittest (e.g. -v, or a test module)
cd "$(dirname "$0")" || exit 1

if [ -x venv/bin/python3 ]; then
  PYTHON=venv/bin/python3
elif [ -x .venv/bin/python3 ]; then
  PYTHON=.venv/bin/python3
else
  echo "No venv found: run ./run.sh --install first." >&2
  exit 1
fi

exec "$PYTHON" -m unittest discover -s tests -t . "$@"
