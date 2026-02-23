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

    logger.info("Attempting Telegram send to chat_id=%s", cid)

    try:
        resp = requests.post(url, json=payload, timeout=30)
        if resp.status_code == 200:
            logger.info("Telegram message sent successfully to %s", cid)
            return True
        # If message too long, split and retry
        if resp.status_code == 400 and "message is too long" in resp.text.lower():
            return _send_split(message, cid)
        logger.warning("Telegram send failed to %s: %s — %s", cid, resp.status_code, resp.text)
        # If channel send failed, fallback to personal chat
        if cid == CHAT_ID_CHANNEL and CHAT_ID_PERSONAL:
            logger.info("Falling back to personal chat %s ...", CHAT_ID_PERSONAL)
            print(f"[INFO] Channel failed. Trying personal chat {CHAT_ID_PERSONAL}...")
            return send_telegram_html(message, chat_id=CHAT_ID_PERSONAL)
        logger.error("Telegram failed (no fallback available): %s — %s", resp.status_code, resp.text)
        return False
    except Exception as e:
        logger.error("Telegram error: %s", e)
        return False


def test_telegram_connection():
    """Diagnose Telegram bot setup — call with --test flag."""
    print("\n=== Telegram Connection Test ===\n")
    print(f"  TELEGRAM_TOKEN:              {'SET' if TOKEN else 'MISSING'}")
    print(f"  TELEGRAM_CHAT_ID_PREMARKET:  {CHAT_ID_CHANNEL or 'NOT SET'}")
    print(f"  TELEGRAM_CHAT_ID (personal): {CHAT_ID_PERSONAL or 'NOT SET'}")
    print(f"  Active chat_id:              {CHAT_ID or 'NONE'}")
    print()

    if not TOKEN:
        print("[FAIL] No TELEGRAM_TOKEN in .env file.")
        return False

    # Step 1: Verify bot token with getMe
    print("Step 1: Checking bot token (getMe)...")
    try:
        resp = requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe", timeout=10)
        data = resp.json()
        if data.get("ok"):
            bot = data["result"]
            print(f"  [OK] Bot: @{bot.get('username', '?')} ({bot.get('first_name', '?')})")
        else:
            print(f"  [FAIL] Invalid token: {data}")
            return False
    except Exception as e:
        print(f"  [FAIL] Network error: {e}")
        return False

    # Step 2: Try sending a test message to channel
    if CHAT_ID_CHANNEL:
        print(f"\nStep 2: Sending test to channel {CHAT_ID_CHANNEL}...")
        ok = _test_send(CHAT_ID_CHANNEL)
        if ok:
            print("  [OK] Channel works!")
        else:
            print("  [FAIL] Channel failed. Make sure your bot is an ADMIN of the channel.")

    # Step 3: Try sending a test message to personal chat
    if CHAT_ID_PERSONAL:
        print(f"\nStep 3: Sending test to personal chat {CHAT_ID_PERSONAL}...")
        ok = _test_send(CHAT_ID_PERSONAL)
        if ok:
            print("  [OK] Personal chat works!")
        else:
            print("  [FAIL] Personal chat failed. Open Telegram, search your bot, tap START.")

    if not CHAT_ID_CHANNEL and not CHAT_ID_PERSONAL:
        print("\n[FAIL] No chat IDs configured in .env")
        return False

    print("\n=== Test Complete ===\n")
    return True


def _test_send(chat_id):
    """Send a short test message to verify a chat_id works."""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": "Test from Pre-Market News Bot"}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            return True
        print(f"    Error {resp.status_code}: {resp.text}")
        return False
    except Exception as e:
        print(f"    Network error: {e}")
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
