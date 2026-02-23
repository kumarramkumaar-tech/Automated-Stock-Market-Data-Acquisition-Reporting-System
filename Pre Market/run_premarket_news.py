"""
Pre-Market News Scheduler
Runs the ET Prime news summary every day at 08:02 AM IST
and sends it to the configured Telegram channel.

Standalone project — place this folder at:
    D:\\Python Mini\\Pre Market

Usage:
    python run_premarket_news.py              # start scheduler (daily at 08:02)
    python run_premarket_news.py --now        # run once immediately (testing)
    python run_premarket_news.py --login      # open browser for ET Prime login
"""

import os
import sys
import time
import logging
from datetime import datetime

import schedule

from premarket_news import run_premarket_summary, create_driver, interactive_login

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

SCHEDULE_TIME = "08:02"


def handle_login():
    """Open a visible browser so the user can log in to ET Prime."""
    driver = create_driver(headless=False)
    try:
        interactive_login(driver)
    finally:
        driver.quit()


def main():
    # --- CLI flags ---
    if "--login" in sys.argv:
        handle_login()
        return

    if "--now" in sys.argv:
        run_premarket_summary()
        return

    # --- Schedule daily job ---
    schedule.every().day.at(SCHEDULE_TIME).do(run_premarket_summary)

    print("┌─────────────────────────────────────────────────────┐")
    print("│  Pre-Market News Scheduler                          │")
    print(f"│  Scheduled at: {SCHEDULE_TIME} AM every day               │")
    print("│  Target: Telegram @MarketprofileNoteBoOk            │")
    print("│  Press Ctrl+C to stop                               │")
    print("└─────────────────────────────────────────────────────┘")
    logger.info("Scheduler started — next run at %s", SCHEDULE_TIME)

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        print("\n[INFO] Scheduler stopped by user.")
        logger.info("Scheduler stopped by user.")


if __name__ == "__main__":
    main()
