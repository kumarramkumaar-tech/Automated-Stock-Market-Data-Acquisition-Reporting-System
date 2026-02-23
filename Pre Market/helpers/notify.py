"""Telegram notification helpers for Pre-Market News project."""

import os
import time
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID_CHANNEL = os.getenv("TELEGRAM_CHAT_ID_PREMARKET")
CHAT_ID_PERSONAL = os.getenv("TELEGRAM_CHAT_ID")
CHAT_ID = CHAT_ID_CHANNEL or CHAT_ID_PERSONAL

logger = logging.getLogger("premarket_news")


def send_telegram(message):
    """Send a plain-text message to Telegram."""
    if not TOKEN or not CHAT_ID:
        print("[WARN] Telegram credentials missing in .env")
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        resp = requests.post(url, data={"chat_id": CHAT_ID, "text": message}, timeout=30)
        return resp.status_code == 200
    except Exception as e:
        print(f"[WARN] Telegram send failed: {e}")
        return False


def send_telegram_html(message, chat_id=None):
    """Send an HTML-formatted message to Telegram (supports channels)."""
    cid = chat_id or CHAT_ID
    if not TOKEN or not cid:
        print("[WARN] Telegram credentials missing (TELEGRAM_TOKEN / TELEGRAM_CHAT_ID_PREMARKET)")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": cid,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        if resp.status_code == 200:
            logger.info("Telegram message sent to %s", cid)
            return True
        # If message too long, split and retry
        if resp.status_code == 400 and "message is too long" in resp.text.lower():
            return _send_split(message, cid)
        # If channel send failed, fallback to personal chat
        if cid == CHAT_ID_CHANNEL and CHAT_ID_PERSONAL:
            logger.warning("Channel send failed (%s). Trying personal chat %s...", resp.status_code, CHAT_ID_PERSONAL)
            return send_telegram_html(message, chat_id=CHAT_ID_PERSONAL)
        logger.error("Telegram failed: %s — %s", resp.status_code, resp.text)
        return False
    except Exception as e:
        logger.error("Telegram error: %s", e)
        return False


def _send_split(message, chat_id):
    """Split a long message at section dividers and send in parts."""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    parts = message.split("─" * 30)
    for i, part in enumerate(parts):
        text = part.strip()
        if not text:
            continue
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            requests.post(url, json=payload, timeout=30)
            time.sleep(0.5)
        except Exception as e:
            logger.error("Split-send part %d failed: %s", i, e)
    return True
