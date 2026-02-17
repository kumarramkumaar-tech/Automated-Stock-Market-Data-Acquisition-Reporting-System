import os
import requests
from dotenv import load_dotenv

# Resolve .env from the project directory (where config.json lives)
_project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_path = os.path.join(_project_dir, ".env")

# Create .env with default credentials if it doesn't exist
if not os.path.exists(_env_path):
    try:
        with open(_env_path, "w") as f:
            f.write("TELEGRAM_TOKEN=8431734536:AAEMcfw0MrjrDGCJSmDwNI-iHhcHhLvVMoI\n")
            f.write("TELEGRAM_CHAT_ID=596635373\n")
        print(f"Created .env at {_env_path}")
    except Exception:
        pass

# Load .env from project directory first, then CWD as fallback
load_dotenv(_env_path)
load_dotenv()  # Also try CWD in case user has a custom .env

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
