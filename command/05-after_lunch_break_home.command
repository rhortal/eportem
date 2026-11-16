#!/usr/bin/env bash

# Run from the repository root with the project's venv (the system python
# doesn't have selenium)
repo_root="$(cd "$(dirname "$0")/.." && pwd)" || exit 1
cd "$repo_root" || exit 1

if [ -x venv/bin/python3 ]; then
  PYTHON=venv/bin/python3
elif [ -x .venv/bin/python3 ]; then
  PYTHON=.venv/bin/python3
else
  echo "Error: no virtual environment found in '$repo_root'. Run ./run.sh --install first."
  exit 1
fi

script_path="$repo_root/after_lunch.py"
if [ ! -f "$script_path" ]; then
  echo "Error: could not find script file '$script_path'"
  exit 1
fi

"$PYTHON" "$script_path" --location home
