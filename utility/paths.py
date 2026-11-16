"""Where ePortem keeps its state files.

Everything is anchored to the repository, not the current directory, so an
override set from another directory is still the one main.py reads.
EPORTEM_STATE_DIR points them somewhere else (the tests use a temp dir).
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def state_dir():
    return Path(os.environ.get("EPORTEM_STATE_DIR") or REPO_ROOT)


def holiday_file():
    return state_dir() / "holiday_override.txt"


def location_file():
    return state_dir() / "location_override.txt"


def business_trip_file():
    return state_dir() / "business_trip_override.txt"


def config_file():
    return state_dir() / "config" / "config.json"
