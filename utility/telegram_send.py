import requests
import os
from dotenv import load_dotenv
from pathlib import Path

# Define function to send message
def send_telegram_message(message_text):
    # Get the directory of the current file
    current_dir = os.path.dirname(os.path.realpath(__file__))

    # Load the .env file
    dotenv_path = Path(os.path.join(current_dir, '../config/.env'))
    load_dotenv(dotenv_path=dotenv_path)

    send = os.getenv('TELEGRAM_NOTIFY')
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    userID = os.getenv('TELEGRAM_CHAT_ID')
    slackWebhook = os.getenv('SLACK_WEBHOOK')

    if send == "YES":
        # Send to Telegram
        # Create url
        url = f'https://api.telegram.org/bot{token}/sendMessage'

        # Create json link with message
        data = {'chat_id': userID, 'text': message_text}

        # POST the message
        requests.post(url, data)

        # Send to Slack
        # Create url
        url = f'https://hooks.slack.com/services/{slackWebhook}'

        # Create json link with message
        data = {'text': message_text}

        # POST the message
        whathappened = requests.post(url, json = data)
        print(whathappened.text)

# Example usage
if __name__ == '__main__':
    send_telegram_message("Hello from my function!")
