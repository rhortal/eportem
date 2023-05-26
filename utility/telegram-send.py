import telegram

# Replace with your Telegram Bot's API token
TOKEN = '1745486736:AAEAPhpBIlK9oVS1QEQkSyD0WSbHLRcu23M'

# Define function to send message
def send_telegram_message(message_text):
    # Create Telegram Bot object
    bot = telegram.Bot(token=TOKEN)

    # Replace with the chat ID you want to send the message to
    chat_id = '414665210'

    # Send message
    bot.send_message(chat_id=chat_id, text=message_text)

# Example usage
if __name__ == '__main__':
    send_telegram_message("Hello from my function!")