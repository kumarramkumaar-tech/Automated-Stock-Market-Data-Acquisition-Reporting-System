# main.py – Project 4: Buildup Pattern Detector
# Scrapes Quantsapp data, classifies buildup patterns (Long/Short Buildup,
# Long Unwinding, Short Covering), detects reversals, and generates
# sector-wise heatmap reports via Telegram.

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
from helpers.report_utils import (
    classify_buildup, detect_reversals, compute_sector_buildup,
    update_summary, format_excel
)
from helpers.report_visuals import generate_visual_report


# --- Logging setup ---
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/buildup_detector.log",
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
print("  BUILDUP PATTERN DETECTOR")
print("=" * 60)
print("\n1. Login manually with OTP on Quantsapp")
print("2. Navigate to Unusual Option Activity page")
print("3. Apply filters: Signal Type=ALL, Opt Type=ALL, Built-up Type=ALL")
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

    # Classify buildup pattern based on price/OI changes
    df["Detected Pattern"] = df.apply(classify_buildup, axis=1)

    return df


def run_cycle():
    """Fetch data, classify patterns, detect reversals, update reports."""
    try:
        logging.info("Starting buildup detection cycle.")
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

        # Count patterns in this fetch
        pattern_counts = df["Detected Pattern"].value_counts()
        count_str = ", ".join(f"{p}: {c}" for p, c in pattern_counts.items())
        msg = f"Buildup: {len(df)} signals at {datetime.now().strftime('%H:%M:%S')}\n{count_str}"
        print(msg)
        logging.info(msg)
        send_telegram(msg)

        # Post-fetch analysis
        try:
            update_summary(cfg["output_file"])
            format_excel(cfg["output_file"])
        except Exception as inner_e:
            logging.warning(f"Summary/format failed: {inner_e}")

        # Detect pattern reversals
        if cfg.get("alert_on_reversal", True):
            try:
                detect_reversals(cfg["output_file"])
            except Exception as inner_e:
                logging.warning(f"Reversal detection failed: {inner_e}")

        # Update sector buildup
        try:
            compute_sector_buildup(cfg["output_file"])
        except Exception as inner_e:
            logging.warning(f"Sector buildup failed: {inner_e}")

    except Exception as e:
        err = f"Error during buildup detection: {e}"
        logging.error(err, exc_info=True)
        print(err)
        send_telegram(err)
        time.sleep(60)


# --- Scheduler setup ---
run_cycle()

schedule.every(cfg["fetch_interval_minutes"]).minutes.do(run_cycle)

# Daily report at 23:59
schedule.every().day.at("23:59").do(lambda: update_summary(cfg["output_file"]))
schedule.every().day.at("23:59").do(lambda: compute_sector_buildup(cfg["output_file"]))
schedule.every().day.at("23:59").do(lambda: generate_visual_report(cfg["output_file"]))

print(f"\nRunning every {cfg['fetch_interval_minutes']} minutes. Press Ctrl+C to stop.")

try:
    while True:
        schedule.run_pending()
        time.sleep(1)
except KeyboardInterrupt:
    stop_msg = "Buildup Pattern Detector stopped by user."
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
