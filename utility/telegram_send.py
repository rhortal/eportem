import requests
import os

# Define function to send message
def send_telegram_message(message_text):
    # Get the directory of the current file
    current_dir = os.path.dirname(os.path.realpath(__file__))

    # Construct the file path
    file_path = os.path.join(current_dir, '../config/telegram.txt')

    # Read the Telegram parameters
    with open(file_path, "r") as f:
        send, token, userID = f.read().splitlines()

    if send == "YES":
        # Create url
        url = f'https://api.telegram.org/bot{token}/sendMessage'

        # Create json link with message
        data = {'chat_id': userID, 'text': message_text}

        # POST the message
        requests.post(url, data)

# Example usage
if __name__ == '__main__':
    send_telegram_message("Hello from my function!")
