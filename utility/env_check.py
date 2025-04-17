import os
import sys
# NOTE: environment variables are loaded by the utility package import

def check_env_variable():
    # Environment variables loaded by utility package import

    # Retrieve the value of EPORTEM_ENABLED environment variable
    epportem_enabled = os.getenv('EPORTEM_ENABLED')
    
    if epportem_enabled != 'YES':
        sys.exit("EPORTEM_ENABLED environment variable is not set to 'YES'. Terminating the program.")

# Test the function
if __name__ == "__main__":
    try:
        check_env_variable()
        print("Environment variable check passed. Continuing with the program...")
    except SystemExit as e:
        print(e)