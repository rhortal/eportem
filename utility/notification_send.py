"""Legacy adapter: the notification channels configured from config/.env.

The channels themselves live in eportem.core.notify; this module fills in
their credentials from the environment and names the environment variables in
its messages. Kept until the cutover in docs/refactor/PLAN.md (phase 8).
"""
import os

import requests  # noqa: F401  (tests patch utility.notification_send.requests.post)
from dotenv import load_dotenv

from eportem.core import notify as _core
from eportem.core.notify import (  # noqa: F401  (re-exported for the legacy scripts and tests)
    REDACTED,
    REQUEST_TIMEOUT,
    SLACK_API,
    SLACK_ERROR_HINTS,
    NotificationChannel,
    NotificationManager,
)
from eportem.core.notify import describe_error as _describe_error
from eportem.core.notify import scrub as _scrub

ENV_LABELS = {
    "telegram_token": "TELEGRAM_BOT_TOKEN",
    "telegram_chat": "TELEGRAM_CHAT_ID",
    "slack_webhook": "SLACK_WEBHOOK_URL",
    "slack_user_token": "SLACK_TOKEN",
    "slack_bot_token": "SLACK_BOT_TOKEN",
    "slack_channel": "SLACK_NOTIFY_CHANNEL",
}

__all__ = ["REDACTED", "REQUEST_TIMEOUT", "SLACK_API", "SLACK_ERROR_HINTS", "ENV_LABELS",
           "NotificationChannel", "NotificationManager", "TelegramChannel", "SlackChannel",
           "_describe_error", "_scrub"]


class TelegramChannel(_core.TelegramChannel):
    def __init__(self, token=None, chat_id=None):
        super().__init__(token or os.getenv('TELEGRAM_BOT_TOKEN'),
                         chat_id or os.getenv('TELEGRAM_CHAT_ID'), labels=ENV_LABELS)


class SlackChannel(_core.SlackChannel):
    def __init__(self, webhook_url=None, token=None, channel=None, bot_token=None):
        super().__init__(webhook_url=webhook_url or os.getenv('SLACK_WEBHOOK_URL'),
                         token=token or os.getenv('SLACK_TOKEN'),
                         channel=channel or os.getenv('SLACK_NOTIFY_CHANNEL'),
                         bot_token=bot_token or os.getenv('SLACK_BOT_TOKEN'),
                         labels=ENV_LABELS)


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
