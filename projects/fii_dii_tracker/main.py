# main.py – Project 3: FII/DII Activity Tracker
# Scrapes FII/DII buy/sell data from Quantsapp/NSE, tracks net flows,
# cumulative trends, sentiment classification, and sends reports via Telegram.

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
from helpers.report_utils import update_summary, format_excel
from helpers.report_visuals import generate_visual_report, generate_weekly_report


# --- Logging setup ---
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/fii_dii_tracker.log",
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
print("  FII/DII ACTIVITY TRACKER")
print("=" * 60)
print("\n1. Login manually with OTP on Quantsapp")
print("2. Navigate to FII/DII data page")
print("3. Ensure the data table is visible")
input("\nPress Enter after login and page is ready...")


def fetch_fii_dii_data():
    """
    Scrape FII/DII activity table from Quantsapp.
    Expected columns: Date, Category, Buy Value, Sell Value, Net Value
    OR: Date, FII Buy, FII Sell, DII Buy, DII Sell
    """
    try:
        WebDriverWait(driver, cfg["max_table_wait_seconds"]).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
        )
    except Exception as e:
        logging.warning(f"FII/DII table not found: {e}")
        return pd.DataFrame()

    rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    all_rows = []
    for row in rows:
        cols = [td.text.strip() for td in row.find_elements(By.TAG_NAME, "td")]
        if len(cols) >= 5:
            all_rows.append(cols)

    if not all_rows:
        return pd.DataFrame()

    # Try to detect the table format
    num_cols = len(all_rows[0])

    if num_cols >= 7:
        # Format: Date, Segment, FII Buy, FII Sell, FII Net, DII Buy, DII Sell, DII Net
        columns = ["Date", "Segment", "FII Buy", "FII Sell", "FII Net",
                    "DII Buy", "DII Sell", "DII Net"][:num_cols]
    elif num_cols >= 5:
        # Format: Date, Category, Buy Value, Sell Value, Net Value
        columns = ["Date", "Category", "Buy Value", "Sell Value", "Net Value"][:num_cols]
    else:
        columns = [f"Col_{i}" for i in range(num_cols)]

    df = pd.DataFrame(all_rows, columns=columns)

    # If in category format, pivot to get FII/DII columns
    if "Category" in df.columns:
        df_pivot = _pivot_category_format(df)
        if df_pivot is not None:
            df = df_pivot

    df["Fetched At"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return df


def _pivot_category_format(df):
    """Convert Category-based format to FII/DII column format."""
    try:
        fii_rows = df[df["Category"].str.contains("FII|FPI", case=False, na=False)]
        dii_rows = df[df["Category"].str.contains("DII", case=False, na=False)]

        if fii_rows.empty and dii_rows.empty:
            return None

        result_rows = []
        dates = df["Date"].unique()

        for date in dates:
            fii = fii_rows[fii_rows["Date"] == date]
            dii = dii_rows[dii_rows["Date"] == date]

            row = {"Date": date}
            if not fii.empty:
                row["FII Buy"] = fii.iloc[0].get("Buy Value", 0)
                row["FII Sell"] = fii.iloc[0].get("Sell Value", 0)
            if not dii.empty:
                row["DII Buy"] = dii.iloc[0].get("Buy Value", 0)
                row["DII Sell"] = dii.iloc[0].get("Sell Value", 0)

            result_rows.append(row)

        return pd.DataFrame(result_rows)

    except Exception:
        return None


def run_cycle():
    """Fetch FII/DII data, save to Excel, compute net flows."""
    try:
        logging.info("Starting FII/DII fetch cycle.")
        if cfg.get("auto_refresh_page", False):
            driver.refresh()
            time.sleep(5)

        df = fetch_fii_dii_data()
        if df.empty:
            msg = f"No FII/DII data at {datetime.now().strftime('%H:%M:%S')}."
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

        msg = f"FII/DII: {len(df)} rows fetched at {datetime.now().strftime('%H:%M:%S')}"
        print(msg)
        logging.info(msg)
        send_telegram(msg)

        # Update summary and format
        try:
            update_summary(cfg["output_file"])
            format_excel(cfg["output_file"])
        except Exception as inner_e:
            logging.warning(f"Summary/format failed: {inner_e}")

    except Exception as e:
        err = f"Error during FII/DII fetch: {e}"
        logging.error(err, exc_info=True)
        print(err)
        send_telegram(err)
        time.sleep(60)


# --- Scheduler setup ---
run_cycle()

schedule.every(cfg["fetch_interval_minutes"]).minutes.do(run_cycle)

# Daily report at 23:59
schedule.every().day.at("23:59").do(lambda: update_summary(cfg["output_file"]))
schedule.every().day.at("23:59").do(lambda: generate_visual_report(cfg["output_file"]))

# Weekly report every Friday at 23:55
schedule.every().friday.at("23:55").do(lambda: generate_weekly_report(cfg["output_file"]))

print(f"\nRunning every {cfg['fetch_interval_minutes']} minutes. Press Ctrl+C to stop.")

try:
    while True:
        schedule.run_pending()
        time.sleep(1)
except KeyboardInterrupt:
    stop_msg = "FII/DII Activity Tracker stopped by user."
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
