# main.py – Project 1: Stock of the Day Screener
# Scrapes Quantsapp unusual activity, scores stocks by OI/volume/price,
# picks "Stock of the Day" and sends ranked report via Telegram.

import json
import os
import time
import logging
from datetime import datetime

import pandas as pd
import schedule

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from helpers.excel_utils import append_df_to_excel
from helpers.notify import send_telegram
from helpers.report_utils import update_summary, format_excel, pick_stock_of_the_day
from helpers.report_visuals import generate_visual_report


# --- Logging setup ---
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/stock_of_the_day.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# --- Load configuration ---
with open("config.json") as f:
    cfg = json.load(f)

# --- Setup browser ---
options = webdriver.ChromeOptions()
if cfg.get("headless"):
    options.add_argument("--headless=new")
options.add_argument("--start-maximized")

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
driver.get(cfg["start_url"])

print("=" * 60)
print("  STOCK OF THE DAY SCREENER")
print("=" * 60)
print("\n1. Login manually with OTP on Quantsapp")
print("2. Apply filters: Signal Type=IV, Opt Type=ALL, Built-up Type=ALL")
input("\nPress Enter after login and filters are set...")


def fetch_table_data():
    """Scrape Unusual Option Activity table from Quantsapp."""
    try:
        WebDriverWait(driver, cfg["max_table_wait_seconds"]).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
        )
    except Exception as e:
        logging.warning(f"Table not found: {e}")
        return pd.DataFrame()

    rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    all_rows = []
    for row in rows:
        cols = [td.text.strip() for td in row.find_elements(By.TAG_NAME, "td")]
        if len(cols) >= 11:
            all_rows.append(cols[:11])

    columns = [
        "Signal Type", "Symbol", "Expiry", "Strike", "Type",
        "Signal Prev Val", "Signal Cur Val", "Change %",
        "Price Change %", "Builtup Type", "Timestamp"
    ]

    df = pd.DataFrame(all_rows, columns=columns)
    df["Fetched At"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return df


def run_cycle():
    """Fetch data, append to Excel, compute scores, pick top stocks."""
    try:
        logging.info("Starting fetch cycle.")
        if cfg.get("auto_refresh_page", False):
            driver.refresh()
            time.sleep(5)

        df = fetch_table_data()
        if df.empty:
            msg = f"No data captured this cycle at {datetime.now().strftime('%H:%M:%S')}."
            logging.warning(msg)
            print(msg)
            send_telegram(msg)
            return

        # Retry write if file locked
        for attempt in range(cfg.get("max_retry_attempts", 3)):
            try:
                append_df_to_excel(cfg["output_file"], df, sheet_name=cfg["sheet_name"])
                break
            except PermissionError:
                print("Excel file is open — waiting 10 sec before retry...")
                time.sleep(10)
        else:
            raise PermissionError("Excel file still locked after retries.")

        msg = f"Stock Screener: {len(df)} rows fetched at {datetime.now().strftime('%H:%M:%S')}"
        print(msg)
        logging.info(msg)
        send_telegram(msg)

        # Update summary and format
        try:
            update_summary(cfg["output_file"])
            format_excel(cfg["output_file"])
        except Exception as inner_e:
            logging.warning(f"Report update/format failed: {inner_e}")

        # Pick Stock of the Day after each cycle
        try:
            pick_stock_of_the_day(
                cfg["output_file"],
                weights=cfg.get("scoring_weights", {}),
                top_n=cfg.get("top_n_stocks", 5)
            )
        except Exception as inner_e:
            logging.warning(f"Stock ranking failed: {inner_e}")

    except Exception as e:
        err = f"Error during fetch cycle: {e}"
        logging.error(err, exc_info=True)
        print(err)
        send_telegram(err)
        time.sleep(60)


# --- Scheduler setup ---
run_cycle()

schedule.every(cfg["fetch_interval_minutes"]).minutes.do(run_cycle)

# Daily final report at 23:59
schedule.every().day.at("23:59").do(lambda: update_summary(cfg["output_file"]))
schedule.every().day.at("23:59").do(lambda: pick_stock_of_the_day(
    cfg["output_file"], cfg.get("scoring_weights", {}), cfg.get("top_n_stocks", 5)
))
schedule.every().day.at("23:59").do(lambda: generate_visual_report(cfg["output_file"]))

print(f"\nRunning every {cfg['fetch_interval_minutes']} minutes. Press Ctrl+C to stop.")

try:
    while True:
        schedule.run_pending()
        time.sleep(1)
except KeyboardInterrupt:
    stop_msg = "Stock of the Day Screener stopped by user."
    print("\n" + stop_msg)
    logging.info(stop_msg)
    try:
        send_telegram(stop_msg)
    except Exception:
        pass
    try:
        driver.quit()
    except Exception:
        pass
