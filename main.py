# main.py – final version (with daily visual PDF report)
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
from selenium.common.exceptions import StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager

from helpers.excel_utils import append_df_to_excel
from helpers.notify import send_telegram
from helpers.report_utils import update_summary, format_excel
from helpers.report_visuals import generate_visual_report


# --- Logging setup ---
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/automation.log",
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

print("Login manually with OTP and apply your filters (Signal Type=IV, etc).")
input("Press Enter after login and filters are set...")


# ------------------------------------------------------------
# Core scraping + automation logic
# ------------------------------------------------------------
def fetch_table_data():
    """Scrape table rows currently visible on the Unusual Option Activity page."""
    try:
        WebDriverWait(driver, cfg["max_table_wait_seconds"]).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
        )
    except Exception as e:
        logging.warning(f"Table not found: {e}")
        return pd.DataFrame()

    columns = [
        "Signal Type", "Symbol", "Expiry", "Strike", "Type",
        "Signal Prev Val", "Signal Cur Val", "Change %",
        "Price Change %", "Builtup Type", "Timestamp"
    ]

    max_retries = 3
    for attempt in range(max_retries):
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            all_rows = []
            for row in rows:
                cols = [td.text.strip() for td in row.find_elements(By.TAG_NAME, "td")]
                if len(cols) >= 11:
                    all_rows.append(cols[:11])
            break
        except StaleElementReferenceException:
            if attempt < max_retries - 1:
                logging.warning(f"StaleElementReferenceException on attempt {attempt + 1}, retrying...")
                time.sleep(2)
            else:
                logging.error("StaleElementReferenceException persisted after retries.")
                return pd.DataFrame()

    df = pd.DataFrame(all_rows, columns=columns)
    df["Fetched At"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return df


def run_cycle():
    """
    Perform one fetch + append to Excel with:
    - retry for locked Excel
    - Telegram notifications
    - update_summary & format_excel after successful append
    """
    try:
        logging.info("Starting fetch cycle.")
        if cfg.get("auto_refresh_page", False):
            driver.refresh()
            time.sleep(5)

        df = fetch_table_data()
        if df.empty:
            msg = f"⚠️ No data captured this cycle at {datetime.now().strftime('%H:%M:%S')}."
            logging.warning(msg)
            print(msg)
            send_telegram(msg)
            return

        # Retry write if file locked
        for attempt in range(3):
            try:
                append_df_to_excel(cfg["output_file"], df, sheet_name=cfg["sheet_name"])
                break
            except PermissionError:
                print("⚠️ Excel file is open — waiting 10 sec before retry…")
                time.sleep(10)
        else:
            raise PermissionError("Excel file still locked after 3 attempts.")

        # Success actions
        msg = f"✅ Quantsapp fetch complete — {len(df)} rows added at {datetime.now().strftime('%H:%M:%S')}"
        print(msg)
        logging.info(msg)
        send_telegram(msg)

        # Update summary and format Excel
        try:
            update_summary(cfg["output_file"])
            format_excel(cfg["output_file"])
        except Exception as inner_e:
            logging.warning(f"Report update/format failed: {inner_e}")
            send_telegram(f"⚠️ Report update/format failed: {inner_e}")

    except Exception as e:
        err = f"❌ Error during fetch cycle at {datetime.now().strftime('%H:%M:%S')}: {e}"
        logging.error(err, exc_info=True)
        print(err)
        send_telegram(err)
        time.sleep(60)


# ------------------------------------------------------------
# Scheduler setup
# ------------------------------------------------------------
# First immediate run
run_cycle()

# Recurring cycle
schedule.every(cfg["fetch_interval_minutes"]).minutes.do(run_cycle)

# Daily summary & visual report at 23:59
schedule.every().day.at("23:59").do(lambda: update_summary(cfg["output_file"]))
schedule.every().day.at("23:59").do(lambda: generate_visual_report(cfg["output_file"]))

# --- Manual test: run report generation now ---
generate_visual_report("output/Quantsapp_Unusual_Activity.xlsx")

print(f"Running every {cfg['fetch_interval_minutes']} minutes. Press Ctrl+C to stop safely.")

# Continuous loop
try:
    while True:
        schedule.run_pending()
        time.sleep(1)
except KeyboardInterrupt:
    stop_msg = "🟢 Automation stopped by user. Exiting cleanly..."
    print("\n" + stop_msg)
    logging.info("Automation stopped manually by user.")
    try:
        send_telegram(stop_msg)
    except Exception:
        pass
    try:
        driver.quit()
    except Exception:
        pass
