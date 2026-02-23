"""
Pre-Market News Scheduler
Runs the ET news summary every 2 hours from 08:00 to 15:00 IST
and sends it to the configured Telegram channel.

Standalone project — place this folder at:
    D:\\Python Mini\\Pre Market

Usage:
    python run_premarket_news.py              # start scheduler (every 2h, 08–15)
    python run_premarket_news.py --now        # run once immediately (testing)
    python run_premarket_news.py --test       # test Telegram bot connectivity
    python run_premarket_news.py --login      # open browser for ET Prime login
"""

import os
import sys
import time
import logging
from datetime import datetime

import schedule

from premarket_news import run_premarket_summary, create_driver, interactive_login
from helpers.notify import test_telegram_connection

# --- Logging ---
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/premarket_news.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("premarket_scheduler")

# Every 2 hours from 08:00 to 15:00 (market hours)
SCHEDULE_TIMES = ["08:00", "10:00", "12:00", "14:00"]


def handle_login():
    """Open a visible browser so the user can log in to ET Prime."""
    driver = create_driver(headless=False)
    try:
        interactive_login(driver)
    finally:
        driver.quit()


def main():
    # --- CLI flags ---
    if "--test" in sys.argv:
        test_telegram_connection()
        return

    if "--login" in sys.argv:
        handle_login()
        return

    if "--now" in sys.argv:
        run_premarket_summary()
        return

    # --- Schedule jobs every 2 hours from 08:00 to 14:00 ---
    for t in SCHEDULE_TIMES:
        schedule.every().day.at(t).do(run_premarket_summary)

    times_str = ", ".join(SCHEDULE_TIMES)
    print("┌─────────────────────────────────────────────────────┐")
    print("│  Market News Scheduler                              │")
    print(f"│  Runs at: {times_str}          │")
    print("│  Target: Telegram @MarketprofileNoteBoOk            │")
    print("│  Press Ctrl+C to stop                               │")
    print("└─────────────────────────────────────────────────────┘")
    logger.info("Scheduler started — runs at %s", times_str)

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        print("\n[INFO] Scheduler stopped by user.")
        logger.info("Scheduler stopped by user.")


if __name__ == "__main__":
    main()
