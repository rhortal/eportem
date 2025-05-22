import os
import requests
from abc import ABC, abstractmethod
from dotenv import load_dotenv

class NotificationChannel(ABC):
    @abstractmethod
    def send(self, message_text: str):
        pass

class TelegramChannel(NotificationChannel):
    def __init__(self, token=None, chat_id=None):
        self.token = token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID')

    def send(self, message_text: str):
        url = f'https://api.telegram.org/bot{self.token}/sendMessage'
        data = {'chat_id': self.chat_id, 'text': message_text}
        response = requests.post(url, data)
        if response.status_code == 200:
            print("Telegram notification sent successfully.")
        else:
            print(f"Telegram notification failed with status code {response.status_code}: {response.text}")

class SlackChannel(NotificationChannel):
    def __init__(self, webhook=None):
        self.webhook = webhook or os.getenv('SLACK_WEBHOOK')

    def send(self, message_text: str):
        url = f'https://hooks.slack.com/services/{self.webhook}'
        data = {'text': message_text}
        response = requests.post(url, json=data)
        if response.status_code == 200:
            print("Slack notification sent successfully.")
        else:
            print(f"Slack notification failed with status code {response.status_code}: {response.text}")

class NotificationManager:
    def __init__(self):
        self.channels = []

    def register_channel(self, channel):
        self.channels.append(channel)

    def notify(self, message_text: str):
        for channel in self.channels:
            channel.send(message_text)

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
