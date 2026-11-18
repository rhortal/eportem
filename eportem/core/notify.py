"""Telegram and Slack notifications, Slack status, and secret scrubbing.

Every channel takes its credentials as arguments. Messages that name a setting
use `labels`, so a caller can name its own settings (the legacy scripts pass
their environment variable names; the service names its form fields).
"""
import re
from abc import ABC, abstractmethod

import requests

from eportem.core.output import default_say

# Seconds to wait for Telegram/Slack. Without it a hung connection would block
# the run long after the clock action was already recorded.
REQUEST_TIMEOUT = 15

REDACTED = "<redacted>"

SLACK_API = "https://slack.com/api"
TELEGRAM_API = "https://api.telegram.org"

DEFAULT_LABELS = {
    "telegram_token": "the Telegram bot token",
    "telegram_chat": "the Telegram chat ID",
    "slack_webhook": "the Slack webhook URL",
    "slack_user_token": "the Slack user token",
    "slack_bot_token": "the Slack bot token",
    "slack_channel": "the Slack channel",
}


def scrub(text, *secrets):
    """Remove secrets from text that may be printed. requests puts the whole URL
    in its error messages, and the Telegram bot token / Slack webhook live in the
    URL, so they would otherwise end up in failure output."""
    text = str(text)
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), REDACTED)
    # Belt and braces for values we weren't told about (e.g. from another env).
    text = re.sub(r"/bot[^/\s'\"]+/", f"/bot{REDACTED}/", text)
    text = re.sub(r"(hooks\.slack\.com/services/)[^\s'\"]+", rf"\1{REDACTED}", text)
    text = re.sub(r"xox[a-z]-[\w-]+", REDACTED, text)
    return text


def describe_error(error, *secrets):
    """Exception type plus a scrubbed message, safe to print."""
    return f"{type(error).__name__}: {scrub(error, *secrets)}"


class NotificationChannel(ABC):
    name = "notification"

    @abstractmethod
    def send(self, message_text: str):
        """Return True if delivered, False if it failed, None if skipped because it
        isn't configured (never raise for a network problem)."""


class TelegramChannel(NotificationChannel):
    name = "telegram"

    def __init__(self, token=None, chat_id=None, say=default_say, labels=None):
        self.token = token
        self.chat_id = chat_id
        self.say = say
        self.labels = {**DEFAULT_LABELS, **(labels or {})}

    def send(self, message_text: str):
        if not self.token or not self.chat_id:
            self.say(f"Telegram notification skipped: {self.labels['telegram_token']} or "
                     f"{self.labels['telegram_chat']} is not configured.")
            return None  # not set up is not a failure
        url = f'{TELEGRAM_API}/bot{self.token}/sendMessage'
        data = {'chat_id': self.chat_id, 'text': message_text}
        try:
            response = requests.post(url, data, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            self.say(f"Telegram notification failed: {describe_error(e, self.token, url)}")
            return False
        if response.status_code == 200:
            self.say("Telegram notification sent successfully.")
            return True
        self.say(f"Telegram notification failed with status code {response.status_code}: "
                 f"{scrub(response.text, self.token)}")
        return False


# Plain one-line explanations for the Slack API errors people actually hit.
# {var} is the label of the token that was rejected, {channel} the channel setting.
SLACK_ERROR_HINTS = {
    "not_authed": "the token was not accepted. Check {var}.",
    "invalid_auth": "the token was not accepted. Check {var}.",
    "token_revoked": "the token was revoked. Reinstall the Slack app and put the new token in {var}.",
    "channel_not_found": "the destination was not found. Check {channel} "
                         "(it must be a channel or user ID, not a name).",
    "not_in_channel": "the app is not in that channel; invite it, or use your user ID in {channel}.",
}


class SlackChannel(NotificationChannel):
    """Sends with an Incoming Webhook if one is configured, otherwise with the
    Web API: the app's bot token (so the message comes from the app and Slack
    alerts you), otherwise the user token (posts as you to your own DM,
    silently). A channel can be given to send somewhere else."""
    name = "slack"

    def __init__(self, webhook_url=None, token=None, channel=None, bot_token=None,
                 say=default_say, labels=None):
        self.webhook_url = webhook_url
        self.token = token
        self.bot_token = bot_token
        self.channel = channel
        self.say = say
        self.labels = {**DEFAULT_LABELS, **(labels or {})}

    def send(self, message_text: str):
        if self.webhook_url:  # an explicit webhook wins, so existing setups keep working
            return self._send_webhook(message_text)
        if self.bot_token:
            return self._send_with_bot(message_text)
        if self.token:
            return self._send_with_user_token(message_text)
        L = self.labels
        self.say(f"Slack notification skipped: none of {L['slack_bot_token']}, {L['slack_user_token']} "
                 f"or {L['slack_webhook']} is configured.")
        return None  # not set up is not a failure

    def _send_webhook(self, message_text):
        data = {'text': message_text}
        try:
            response = requests.post(self.webhook_url, json=data, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            self.say(f"Slack notification failed: {describe_error(e, self.webhook_url)}")
            return False
        if response.status_code == 200:
            self.say("Slack notification sent successfully.")
            return True
        self.say(f"Slack notification failed with status code {response.status_code}: "
                 f"{scrub(response.text, self.webhook_url)}")
        return False

    def _secrets(self):
        return (self.token, self.bot_token)

    def _var_for(self, token):
        if token and token == self.bot_token:
            return self.labels["slack_bot_token"]
        return self.labels["slack_user_token"]

    def _api_call(self, method, payload, token):
        """POST to a Slack Web API method with the given token. Returns (body, None)
        when Slack answered ok, or (None, reason) with a printable, scrubbed reason.
        Slack answers HTTP 200 even for errors, so the body's "ok" is what counts."""
        headers = {"Authorization": f"Bearer {token}"}
        try:
            response = requests.post(f"{SLACK_API}/{method}", json=payload,
                                     headers=headers, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            return None, describe_error(e, *self._secrets())
        try:
            body = response.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            return None, (f"{method} returned a non-JSON response (HTTP "
                          f"{response.status_code}): {scrub(response.text, *self._secrets())}")
        if not response.ok:
            return None, f"{method} returned HTTP {response.status_code}"
        if not body.get("ok"):
            return None, self._slack_error(body, method, token)
        return body, None

    def _slack_error(self, body, method, token):
        L = self.labels
        error = str(body.get("error", "unknown_error"))
        var = self._var_for(token)
        if error == "missing_scope":
            needed = scrub(body.get("needed") or "chat:write", *self._secrets())
            if method == "auth.test":
                # Not about posting: the user token can't even look up your user ID.
                return (f"{L['slack_user_token']} lacks a scope needed to find your user ID (Slack says it "
                        f"needs: {needed}). Add it under User Token Scopes in the Slack app, "
                        f"reinstall the app, and put the new token in {L['slack_user_token']}.")
            if var == L["slack_bot_token"]:
                return (f"the bot token lacks the chat:write scope (Slack says it needs: {needed}). "
                        "Add chat:write under Bot Token Scopes in the Slack app, reinstall the app, "
                        f"and put the new Bot User OAuth Token (xoxb-...) in {L['slack_bot_token']}.")
            return (f"the token lacks the chat:write scope (Slack says it needs: {needed}). "
                    "Add it under User Token Scopes in the Slack app, reinstall the app, "
                    f"and put the new token in {L['slack_user_token']}.")
        hint = SLACK_ERROR_HINTS.get(error)
        return hint.format(var=var, channel=L["slack_channel"]) if hint else scrub(error, *self._secrets())

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
        L = self.labels
        channel = self.channel
        if not channel:
            if not find_user:
                self.say(f"Slack notification failed: {L['slack_bot_token']} is set but there is nobody to "
                         f"send to; set {L['slack_channel']} to your Slack user ID (or a channel ID), "
                         f"or set {L['slack_user_token']}.")
                return False
            channel, reason = self._user_id()
            if reason:
                self.say(f"Slack notification failed: {reason}")
                return False
        _, reason = self._api_call("chat.postMessage", {"channel": channel, "text": message_text}, token)
        if reason:
            self.say(f"Slack notification failed: {reason}")
            return False
        self.say("Slack notification sent successfully.")
        return True

    def _send_with_bot(self, message_text):
        return self._post(message_text, self.bot_token, find_user=bool(self.token))

    def _send_with_user_token(self, message_text):
        return self._post(message_text, self.token, find_user=True)


class NotificationManager:
    def __init__(self, say=default_say):
        self.channels = []
        self.say = say

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
                self.say(f"{name} notification failed: {describe_error(e)}")
                result = False
            if result is False:
                failed.append(name)
        return failed


class SlackStatusUpdater:
    """Sets the Slack status of the user token's owner."""

    def __init__(self, token, say=default_say):
        if not token:
            raise ValueError("No Slack user token configured.")
        self.token = token
        self.say = say

    def set_status(self, text, emoji, expiration=0):
        """Set the status. expiration is a Unix timestamp (0 = no expiration).
        Returns True if Slack accepted it, False otherwise (never raises for a
        network problem)."""
        url = f"{SLACK_API}/users.profile.set"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        data = {"profile": {"status_text": text, "status_emoji": emoji, "status_expiration": expiration}}
        try:
            response = requests.post(url, json=data, headers=headers, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            self.say(f"Failed to update Slack status: {describe_error(e, self.token)}")
            return False
        try:
            resp_json = response.json()
        except Exception:
            resp_json = {}
        if response.ok and resp_json.get("ok"):
            self.say("Slack status updated successfully.")
            return True
        self.say(f"Failed to update Slack status: {scrub(response.text, self.token)}")
        return False
