import os
import sys
from dotenv import load_dotenv

def check_env_variable():
    # Load the environment variables from the .env file
    dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'config', '.env'))
    load_dotenv(dotenv_path)

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