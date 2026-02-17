import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(message):
    """Send a text message to Telegram using bot."""
    if not TOKEN or not CHAT_ID:
        print("Telegram credentials missing in .env file")
        return

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, data={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        })
    except Exception as e:
        print("Failed to send Telegram message:", e)


def send_telegram_file(file_path):
    """Send a file (PDF/Excel/image) to Telegram."""
    if not TOKEN or not CHAT_ID:
        print("Telegram file credentials missing")
        return

    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    try:
        with open(file_path, "rb") as f:
            requests.post(url, data={"chat_id": CHAT_ID}, files={"document": f})
    except Exception as e:
        print("Failed to send Telegram file:", e)
