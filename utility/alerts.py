"""Short alerts on the same channels as the clock notifications (Telegram and
Slack, honouring TELEGRAM_NOTIFY / SLACK_NOTIFY). Used for failed cron runs and
by `main.py --verify-day`. Sending never raises: an alert is a courtesy on top
of the cron mail, and must not change a run's exit code."""
import os

from utility.notification_send import NotificationManager, SlackChannel, TelegramChannel, _describe_error, _scrub

MAX_REASON_CHARS = 200

_SECRET_VARS = ("TELEGRAM_BOT_TOKEN", "SLACK_TOKEN", "SLACK_BOT_TOKEN",
                "SLACK_WEBHOOK_URL", "EPORTEM_PASSWORD")


def _secrets():
    return [os.getenv(k) for k in _SECRET_VARS]


def one_line(text, limit=MAX_REASON_CHARS):
    """Scrubbed, single line, shortened. Scrubbing comes first so a cut can't
    leave half a secret behind."""
    text = " ".join(_scrub(text, *_secrets()).split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def describe_exception(error):
    """Type and short message, never a traceback."""
    return one_line(_describe_error(error, *_secrets()))


def failure_text(action, now, reason):
    return (f"ePortem: {action or 'run'} FAILED at {now:%H:%M} - {one_line(reason)}. "
            "Check ePortem by hand; details in the cron mail.")


def send_alert(text):
    """Send `text` to every enabled channel. Returns True if nothing failed
    (including when no channel is enabled), False otherwise."""
    try:
        manager = NotificationManager()
        if os.getenv('TELEGRAM_NOTIFY') == "YES":
            manager.register_channel(TelegramChannel())
        if os.getenv('SLACK_NOTIFY') == "YES":
            manager.register_channel(SlackChannel())
        if not manager.channels:
            print("Alert not sent: TELEGRAM_NOTIFY and SLACK_NOTIFY are both off.")
            return True
        failed = manager.notify(text)
        if failed:
            print("Alert failed on: " + ", ".join(failed))
        return not failed
    except Exception as e:
        print(f"Alert failed: {describe_exception(e)}")
        return False
