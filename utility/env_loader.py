from pathlib import Path
from dotenv import load_dotenv

def load_environment():
    """
    Load environment variables from the .env file located in the project config directory.
    """
    env_path = Path(__file__).parent.parent / "config" / ".env"
    load_dotenv(env_path)