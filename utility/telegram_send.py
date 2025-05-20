import requests
import os
from pathlib import Path

# Define function to send message
def send_telegram_message(message_text):
    # Get the directory of the current file
    current_dir = os.path.dirname(os.path.realpath(__file__))


    tsend = os.getenv('TELEGRAM_NOTIFY')
    ssend = os.getenv('SLACK_NOTIFY')
    telegramToken = os.getenv('TELEGRAM_BOT_TOKEN')
    userID = os.getenv('TELEGRAM_CHAT_ID')
    slackWebhook = os.getenv('SLACK_WEBHOOK')

    if tsend == "YES":
        # Send to Telegram
        # Create url
        url = f'https://api.telegram.org/bot{telegramToken}/sendMessage'

        # Create json link with message
        data = {'chat_id': userID, 'text': message_text}

        # POST the message
        requests.post(url, data)

    if ssend == "YES":
        # Send to Slack
        # Create url
        url = f'https://hooks.slack.com/services/{slackWebhook}'

        # Create json link with message
        data = {'text': message_text}

        # POST the message
        requests.post(url, json = data)

# Example usage
if __name__ == '__main__':
    send_telegram_message("Hello from my function!")
