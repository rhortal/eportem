#!/usr/bin/env sh
# Set up (or repair) the virtual environment without running main.py
exec "$(dirname "$0")/run.sh" --install
