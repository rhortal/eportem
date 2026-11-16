import os
import sys

# Environment variables are loaded by the utility package import.


def check_env_variable():
    """Exit non-zero unless EPORTEM_ENABLED is "YES" (the switch that lets
    this host clock at all)."""
    if os.getenv('EPORTEM_ENABLED') != 'YES':
        sys.exit("EPORTEM_ENABLED environment variable is not set to 'YES'. Terminating the program.")


if __name__ == "__main__":
    try:
        check_env_variable()
        print("Environment variable check passed. Continuing with the program...")
    except SystemExit as e:
        print(e)
