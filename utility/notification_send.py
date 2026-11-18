import os
import re
from abc import ABC, abstractmethod

import requests
from dotenv import load_dotenv

# Seconds to wait for Telegram/Slack. Without it a hung connection would block
# the run (and cron) long after the clock action was already recorded.
REQUEST_TIMEOUT = 15

REDACTED = "<redacted>"


def _scrub(text, *secrets):
    """Remove secrets from text that may be printed. requests puts the whole URL
    in its error messages, and the Telegram bot token / Slack webhook live in the
    URL, so they would otherwise end up in the cron failure mail."""
    text = str(text)
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), REDACTED)
    # Belt and braces for values we weren't told about (e.g. from another env).
    text = re.sub(r"/bot[^/\s'\"]+/", f"/bot{REDACTED}/", text)
    text = re.sub(r"(hooks\.slack\.com/services/)[^\s'\"]+", rf"\1{REDACTED}", text)
    text = re.sub(r"xox[a-z]-[\w-]+", REDACTED, text)
    return text


def _describe_error(error, *secrets):
    """Exception type plus a scrubbed message, safe to print."""
    return f"{type(error).__name__}: {_scrub(error, *secrets)}"


class NotificationChannel(ABC):
    name = "notification"

    @abstractmethod
    def send(self, message_text: str):
        """Return True if delivered, False if it failed, None if skipped because it
        isn't configured (never raise for a network problem)."""

class TelegramChannel(NotificationChannel):
    name = "telegram"

    def __init__(self, token=None, chat_id=None):
        self.token = token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID')

    def send(self, message_text: str):
        if not self.token or not self.chat_id:
            print("Telegram notification skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not configured.")
            return None  # not set up is not a failure
        url = f'https://api.telegram.org/bot{self.token}/sendMessage'
        data = {'chat_id': self.chat_id, 'text': message_text}
        try:
            response = requests.post(url, data, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            print(f"Telegram notification failed: {_describe_error(e, self.token, url)}")
            return False
        if response.status_code == 200:
            print("Telegram notification sent successfully.")
            return True
        print(f"Telegram notification failed with status code {response.status_code}: "
              f"{_scrub(response.text, self.token)}")
        return False

SLACK_API = "https://slack.com/api"

# Plain one-line explanations for the Slack API errors people actually hit.
# {var} is the env var that holds the token that was rejected.
SLACK_ERROR_HINTS = {
    "not_authed": "the token was not accepted. Check {var}.",
    "invalid_auth": "the token was not accepted. Check {var}.",
    "token_revoked": "the token was revoked. Reinstall the Slack app and put the new token in {var}.",
    "channel_not_found": "the destination was not found. Check SLACK_NOTIFY_CHANNEL "
                         "(it must be a channel or user ID, not a name).",
    "not_in_channel": "the app is not in that channel; invite it, or use your user ID in SLACK_NOTIFY_CHANNEL.",
}


class SlackChannel(NotificationChannel):
    """Sends with an Incoming Webhook if one is configured, otherwise with the
    Web API: the app's bot token (SLACK_BOT_TOKEN, so the message comes from the
    app and Slack alerts you), otherwise the user token SLACK_TOKEN (posts as you
    to your own DM, silently). A channel can be given to send somewhere else."""
    name = "slack"

    def __init__(self, webhook_url=None, token=None, channel=None, bot_token=None):
        self.webhook_url = webhook_url or os.getenv('SLACK_WEBHOOK_URL')
        self.token = token or os.getenv('SLACK_TOKEN')
        self.bot_token = bot_token or os.getenv('SLACK_BOT_TOKEN')
        self.channel = channel or os.getenv('SLACK_NOTIFY_CHANNEL')

    def send(self, message_text: str):
        if self.webhook_url:  # an explicit webhook wins, so existing setups keep working
            return self._send_webhook(message_text)
        if self.bot_token:
            return self._send_with_bot(message_text)
        if self.token:
            return self._send_with_user_token(message_text)
        print("Slack notification skipped: none of SLACK_BOT_TOKEN, SLACK_TOKEN or "
              "SLACK_WEBHOOK_URL is configured.")
        return None  # not set up is not a failure

    def _send_webhook(self, message_text):
        data = {'text': message_text}
        try:
            response = requests.post(self.webhook_url, json=data, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            print(f"Slack notification failed: {_describe_error(e, self.webhook_url)}")
            return False
        if response.status_code == 200:
            print("Slack notification sent successfully.")
            return True
        print(f"Slack notification failed with status code {response.status_code}: "
              f"{_scrub(response.text, self.webhook_url)}")
        return False

    def _secrets(self):
        return (self.token, self.bot_token)

    def _var_for(self, token):
        return "SLACK_BOT_TOKEN" if token and token == self.bot_token else "SLACK_TOKEN"

    def _api_call(self, method, payload, token):
        """POST to a Slack Web API method with the given token. Returns (body, None)
        when Slack answered ok, or (None, reason) with a printable, scrubbed reason.
        Slack answers HTTP 200 even for errors, so the body's "ok" is what counts."""
        headers = {"Authorization": f"Bearer {token}"}
        try:
            response = requests.post(f"{SLACK_API}/{method}", json=payload,
                                     headers=headers, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            return None, _describe_error(e, *self._secrets())
        try:
            body = response.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            return None, (f"{method} returned a non-JSON response (HTTP "
                          f"{response.status_code}): {_scrub(response.text, *self._secrets())}")
        if not response.ok:
            return None, f"{method} returned HTTP {response.status_code}"
        if not body.get("ok"):
            return None, self._slack_error(body, method, token)
        return body, None

    def _slack_error(self, body, method, token):
        error = str(body.get("error", "unknown_error"))
        var = self._var_for(token)
        if error == "missing_scope":
            needed = _scrub(body.get("needed") or "chat:write", *self._secrets())
            if method == "auth.test":
                # Not about posting: the user token can't even look up your user ID.
                return (f"SLACK_TOKEN lacks a scope needed to find your user ID (Slack says it "
                        f"needs: {needed}). Add it under User Token Scopes in the Slack app, "
                        "reinstall the app, and put the new token in SLACK_TOKEN.")
            if var == "SLACK_BOT_TOKEN":
                return (f"the bot token lacks the chat:write scope (Slack says it needs: {needed}). "
                        "Add chat:write under Bot Token Scopes in the Slack app, reinstall the app, "
                        "and put the new Bot User OAuth Token (xoxb-...) in SLACK_BOT_TOKEN.")
            return (f"the token lacks the chat:write scope (Slack says it needs: {needed}). "
                    "Add it under User Token Scopes in the Slack app, reinstall the app, "
                    "and put the new token in SLACK_TOKEN.")
        hint = SLACK_ERROR_HINTS.get(error)
        return hint.format(var=var) if hint else _scrub(error, *self._secrets())

    def _user_id(self):
        """The user token owner's user ID. Posting to it with a user token lands in
        your own DM; with the bot token it lands in your DM with the app. (A bot
        token's own auth.test would return the bot's ID, hence the user token.)
        Returns (user_id, None) or (None, reason)."""
        body, reason = self._api_call("auth.test", {}, self.token)
        if reason:
            return None, reason
        user_id = body.get("user_id")
        if not user_id:
            return None, "auth.test did not return a user_id"
        return user_id, None

    def _post(self, message_text, token, find_user):
        channel = self.channel
        if not channel:
            if not find_user:
                print("Slack notification failed: SLACK_BOT_TOKEN is set but there is nobody to "
                      "send to; set SLACK_NOTIFY_CHANNEL to your Slack user ID (or a channel ID), "
                      "or set SLACK_TOKEN.")
                return False
            channel, reason = self._user_id()
            if reason:
                print(f"Slack notification failed: {reason}")
                return False
        _, reason = self._api_call("chat.postMessage", {"channel": channel, "text": message_text}, token)
        if reason:
            print(f"Slack notification failed: {reason}")
            return False
        print("Slack notification sent successfully.")
        return True

    def _send_with_bot(self, message_text):
        return self._post(message_text, self.bot_token, find_user=bool(self.token))

    def _send_with_user_token(self, message_text):
        return self._post(message_text, self.token, find_user=True)

class NotificationManager:
    def __init__(self):
        self.channels = []

    def register_channel(self, channel):
        self.channels.append(channel)

    def notify(self, message_text: str):
        """Send to every channel; one failing channel never stops the others.
        Returns the names of the channels that failed (skipped ones don't count)."""
        failed = []
        for channel in self.channels:
            name = getattr(channel, "name", type(channel).__name__)
            try:
                result = channel.send(message_text)
            except Exception as e:  # a bug in one channel must not hide the rest
                print(f"{name} notification failed: {_describe_error(e)}")
                result = False
            if result is False:
                failed.append(name)
        return failed

if __name__ == '__main__':
    # Load environment variables from eportem/config/.env
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "config", ".env")
    load_dotenv(env_path)

    manager = NotificationManager()
    if os.getenv('TELEGRAM_NOTIFY') == "YES":
        manager.register_channel(TelegramChannel())
    if os.getenv('SLACK_NOTIFY') == "YES":
        manager.register_channel(SlackChannel())

    manager.notify("Hello from the notification manager!")
