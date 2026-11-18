import os

import requests

from utility.notification_send import REQUEST_TIMEOUT, _describe_error, _scrub


class SlackStatusUpdater:
    def __init__(self, token=None):
        self.token = token or os.getenv('SLACK_TOKEN')
        if not self.token:
            raise ValueError("Slack OAuth token not found in SLACK_TOKEN environment variable.")

    def set_status(self, text, emoji, expiration=0):
        """
        Set the Slack status for the authenticated user.

        Args:
            text (str): The status text to display.
            emoji (str): The emoji to use for the status.
            expiration (int): Unix timestamp when the status should expire (0 = no expiration).

        Returns True if Slack accepted it, False otherwise (never raises for a network problem).
        """
        url = "https://slack.com/api/users.profile.set"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        profile = {
            "status_text": text,
            "status_emoji": emoji,
            "status_expiration": expiration
        }
        data = {"profile": profile}
        try:
            response = requests.post(url, json=data, headers=headers, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            print(f"Failed to update Slack status: {_describe_error(e, self.token)}")
            return False
        try:
            resp_json = response.json()
        except Exception:
            resp_json = {}
        if response.ok and resp_json.get("ok"):
            print("Slack status updated successfully.")
            return True
        print(f"Failed to update Slack status: {_scrub(response.text, self.token)}")
        return False

if __name__ == "__main__":
    # When run directly, load environment and set a test status
    import os

    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "config", ".env")
    load_dotenv(env_path)
    updater = SlackStatusUpdater()
    updater.set_status("Testing software", ":test_tube:")
