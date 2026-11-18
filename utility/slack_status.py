"""Legacy adapter: the Slack status updater with its token from SLACK_TOKEN.
The updater itself lives in eportem.core.notify."""
import os

import requests  # noqa: F401  (kept importable for tests that patch it here)

from eportem.core import notify as _core


class SlackStatusUpdater(_core.SlackStatusUpdater):
    def __init__(self, token=None):
        token = token or os.getenv('SLACK_TOKEN')
        if not token:
            raise ValueError("Slack OAuth token not found in SLACK_TOKEN environment variable.")
        super().__init__(token)


if __name__ == "__main__":
    # When run directly, load environment and set a test status
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "config", ".env")
    load_dotenv(env_path)
    updater = SlackStatusUpdater()
    updater.set_status("Testing software", ":test_tube:")
