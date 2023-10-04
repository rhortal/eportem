import os
import sys

def check_env_variable():
    epportem_enabled = os.environ.get('EPORTEM_ENABLED')
    if epportem_enabled != 'YES':
        sys.exit("EPORTEM_ENABLED environment variable is not set to 'YES'. Terminating the program.")

# Test the function
if __name__ == "__main__":
    try:
        check_env_variable()
        print("Environment variable check passed. Continuing with the program...")
    except SystemExit as e:
        print(e)
