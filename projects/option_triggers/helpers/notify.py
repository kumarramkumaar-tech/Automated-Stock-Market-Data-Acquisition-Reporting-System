import os
import requests
from dotenv import load_dotenv

# Try loading .env from CWD first, then from the project directory
load_dotenv()
if not os.getenv("TELEGRAM_TOKEN"):
    # Resolve .env relative to this file's project directory
    _project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(_project_dir, ".env"))

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
