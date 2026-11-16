import os
import sys

# Environment variables are loaded by the utility package import.

DISABLED_MESSAGE = "ePortem is disabled (EPORTEM_ENABLED is not YES); nothing done."


def is_enabled():
    """True only for the exact text YES (the kill switch that lets this host clock)."""
    return os.getenv('EPORTEM_ENABLED') == 'YES'


def check_env_variable():
    """Stop quietly (exit 0) unless EPORTEM_ENABLED is "YES". Turning the host off
    on purpose is not a failure, so it must not trigger a cron mail."""
    if not is_enabled():
        print(DISABLED_MESSAGE)
        sys.exit(0)


if __name__ == "__main__":
    check_env_variable()
    print("Environment variable check passed. Continuing with the program...")
