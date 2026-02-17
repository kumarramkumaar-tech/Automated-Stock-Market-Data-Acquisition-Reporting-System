# main.py – Project 2: Options Chain Analyzer
# Scrapes Quantsapp options chain data, computes Max Pain, PCR,
# Support/Resistance levels, and sends analysis via Telegram.

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
from helpers.report_utils import analyze_chain, update_summary, format_excel
from helpers.report_visuals import generate_visual_report


# --- Logging setup ---
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/options_chain.log",
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
print("  OPTIONS CHAIN ANALYZER")
print("=" * 60)
print("\n1. Login manually with OTP on Quantsapp")
print("2. Navigate to Options Chain page")
print(f"3. Select symbol: {cfg.get('default_symbol', 'NIFTY')}")
input("\nPress Enter after login and symbol selection...")


def fetch_options_chain():
    """
    Scrape options chain table from Quantsapp.
    Expected columns: Strike, Call OI, Call Chg OI, Call Volume, Call IV, Call LTP,
                      Put LTP, Put IV, Put Volume, Put Chg OI, Put OI
    """
    try:
        WebDriverWait(driver, cfg["max_table_wait_seconds"]).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
        )
    except Exception as e:
        logging.warning(f"Options chain table not found: {e}")
        return pd.DataFrame()

    rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    all_rows = []
    for row in rows:
        cols = [td.text.strip() for td in row.find_elements(By.TAG_NAME, "td")]
        if len(cols) >= 11:
            all_rows.append(cols[:11])

    # Standard options chain column layout
    columns = [
        "Call OI", "Call Chg OI", "Call Volume", "Call IV", "Call LTP",
        "Strike",
        "Put LTP", "Put IV", "Put Volume", "Put Chg OI", "Put OI"
    ]

    if not all_rows:
        return pd.DataFrame()

    # Detect actual column count and adjust
    actual_cols = len(all_rows[0]) if all_rows else 0
    if actual_cols < 11:
        columns = columns[:actual_cols]

    df = pd.DataFrame(all_rows, columns=columns)
    df["Symbol"] = cfg.get("default_symbol", "NIFTY")
    df["Fetched At"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return df


def run_cycle():
    """Fetch options chain, save to Excel, run analysis."""
    try:
        logging.info("Starting options chain fetch cycle.")
        if cfg.get("auto_refresh_page", False):
            driver.refresh()
            time.sleep(5)

        df = fetch_options_chain()
        if df.empty:
            msg = f"No options chain data at {datetime.now().strftime('%H:%M:%S')}."
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

        msg = f"Options Chain: {len(df)} strikes fetched at {datetime.now().strftime('%H:%M:%S')}"
        print(msg)
        logging.info(msg)
        send_telegram(msg)

        # Run analysis
        try:
            for symbol in cfg.get("symbols_to_track", [cfg.get("default_symbol", "NIFTY")]):
                analyze_chain(cfg["output_file"], symbol=symbol)
            format_excel(cfg["output_file"])
        except Exception as inner_e:
            logging.warning(f"Analysis failed: {inner_e}")

    except Exception as e:
        err = f"Error during options chain fetch: {e}"
        logging.error(err, exc_info=True)
        print(err)
        send_telegram(err)
        time.sleep(60)


# --- Scheduler setup ---
run_cycle()

schedule.every(cfg["fetch_interval_minutes"]).minutes.do(run_cycle)

# Daily summary and visual report at 23:59
schedule.every().day.at("23:59").do(lambda: update_summary(cfg["output_file"]))
schedule.every().day.at("23:59").do(lambda: generate_visual_report(cfg["output_file"]))

print(f"\nRunning every {cfg['fetch_interval_minutes']} minutes. Press Ctrl+C to stop.")

try:
    while True:
        schedule.run_pending()
        time.sleep(1)
except KeyboardInterrupt:
    stop_msg = "Options Chain Analyzer stopped by user."
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
