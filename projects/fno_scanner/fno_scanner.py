"""
FNO Scanner - Standalone Python Script
========================================
Scrapes FNO Scanner data from the web platform (under Tools tab).

Workflow:
1. Opens FNO Scanner page
2. Manual OTP login by user
3. Sets filters: Instrument=ALL, Expiry=ALL, Price Change, OI Change, IV Change %
4. Clicks Play to execute scan
5. Clicks Refresh, scrolls to bottom to load all data
6. Scrapes entire table data
7. Exports to Excel with analysis
8. Repeats every 30 minutes

Usage:
    python fno_scanner.py
"""
import json
import os
import sys
import time
import logging
from datetime import datetime

import pandas as pd
import schedule

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, StaleElementReferenceException
)
from webdriver_manager.chrome import ChromeDriverManager

from helpers.excel_utils import append_df_to_excel, format_fno_excel
from helpers.notify import send_telegram
from helpers.data_analysis import (
    analyze_fno_data, classify_buildup,
    generate_analysis_summary_text, write_analysis_to_excel
)
from helpers.report_visuals import generate_fno_visual_report, generate_daily_summary


# ============================================================
# Logging setup
# ============================================================
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/fno_scanner.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ============================================================
# Load configuration
# ============================================================
with open("config.json") as f:
    cfg = json.load(f)


# ============================================================
# Browser setup
# ============================================================
def setup_browser():
    """Initialize Chrome browser with appropriate options."""
    options = webdriver.ChromeOptions()
    if cfg.get("headless"):
        options.add_argument("--headless=new")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )
    return driver


# ============================================================
# Filter application helpers
# ============================================================
def wait_and_click(driver, selector, by=By.CSS_SELECTOR, timeout=10):
    """Wait for element to be clickable and click it."""
    element = WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((by, selector))
    )
    element.click()
    return element


def wait_for_element(driver, selector, by=By.CSS_SELECTOR, timeout=10):
    """Wait for element to be present."""
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((by, selector))
    )


def select_dropdown_option(driver, dropdown_selector, option_text, timeout=10):
    """
    Generic dropdown selector:
    1. Click the dropdown to open it
    2. Wait for options to appear
    3. Click the matching option
    """
    try:
        # Click dropdown
        dropdown = wait_and_click(driver, dropdown_selector, timeout=timeout)
        time.sleep(0.5)

        # Look for option in dropdown list
        options = driver.find_elements(
            By.XPATH,
            f"//li[contains(text(), '{option_text}')] | "
            f"//div[contains(text(), '{option_text}')] | "
            f"//option[contains(text(), '{option_text}')] | "
            f"//span[contains(text(), '{option_text}')]"
        )

        for opt in options:
            try:
                if opt.is_displayed():
                    opt.click()
                    logger.info(f"Selected dropdown option: {option_text}")
                    return True
            except StaleElementReferenceException:
                continue

        logger.warning(f"Could not find dropdown option: {option_text}")
        return False
    except Exception as e:
        logger.warning(f"Dropdown selection failed for '{option_text}': {e}")
        return False


def apply_filters(driver, filters):
    """
    Apply FNO Scanner filters on the page.

    Attempts to set:
    - Instrument: ALL
    - Expiry: ALL
    - Price Change, OI Change, IV Change % filters

    NOTE: The exact CSS selectors depend on the page structure.
    These may need adjustment based on the actual DOM.
    """
    logger.info("Applying FNO Scanner filters...")
    print("Attempting to apply filters automatically...")

    try:
        # Try common dropdown/filter selectors for FNO Scanner
        # Instrument dropdown
        instrument_selectors = [
            "select[name*='instrument']",
            "[class*='instrument'] select",
            "[data-field='instrument']",
            "#instrument-select",
            "[class*='Instrument'] [class*='dropdown']",
        ]

        for sel in instrument_selectors:
            try:
                select_dropdown_option(driver, sel, filters.get("instrument", "ALL"), timeout=3)
                print(f"  Instrument filter set to: {filters.get('instrument', 'ALL')}")
                break
            except Exception:
                continue

        # Expiry dropdown
        expiry_selectors = [
            "select[name*='expiry']",
            "[class*='expiry'] select",
            "[data-field='expiry']",
            "#expiry-select",
            "[class*='Expiry'] [class*='dropdown']",
        ]

        for sel in expiry_selectors:
            try:
                select_dropdown_option(driver, sel, filters.get("expiry", "ALL"), timeout=3)
                print(f"  Expiry filter set to: {filters.get('expiry', 'ALL')}")
                break
            except Exception:
                continue

        logger.info("Filter application attempted.")

    except Exception as e:
        logger.warning(f"Auto-filter application failed: {e}")
        print(f"Auto-filter application encountered issues: {e}")
        print("Please set filters manually if they were not applied correctly.")


def click_play_button(driver):
    """Click the Play/Execute button to run the scanner."""
    play_selectors = [
        "[class*='play']",
        "button[class*='play']",
        "[class*='Play']",
        "button[title*='Play']",
        "button[title*='play']",
        "[class*='scan-btn']",
        "[class*='execute']",
        "button[class*='run']",
        ".fa-play",
        "[class*='fa-play']",
        "i.fa-play",
        "button i.fa-play",
    ]

    for sel in play_selectors:
        try:
            wait_and_click(driver, sel, timeout=3)
            logger.info("Play button clicked.")
            print("  Play button clicked.")
            time.sleep(2)
            return True
        except Exception:
            continue

    # Try XPath for play button
    play_xpaths = [
        "//button[contains(@class, 'play')]",
        "//button[contains(@title, 'Play')]",
        "//i[contains(@class, 'fa-play')]/..",
        "//button[contains(@class, 'scan')]",
    ]

    for xpath in play_xpaths:
        try:
            wait_and_click(driver, xpath, by=By.XPATH, timeout=3)
            logger.info("Play button clicked (XPath).")
            print("  Play button clicked.")
            time.sleep(2)
            return True
        except Exception:
            continue

    logger.warning("Could not find Play button automatically.")
    return False


def click_refresh_button(driver):
    """Click the Refresh button to reload data."""
    refresh_selectors = [
        "[class*='refresh']",
        "button[class*='refresh']",
        "button[title*='Refresh']",
        "button[title*='refresh']",
        ".fa-refresh",
        ".fa-sync",
        "[class*='fa-refresh']",
        "[class*='fa-sync']",
        "i.fa-refresh",
        "i.fa-sync",
    ]

    for sel in refresh_selectors:
        try:
            wait_and_click(driver, sel, timeout=3)
            logger.info("Refresh button clicked.")
            print("  Refresh button clicked.")
            time.sleep(3)
            return True
        except Exception:
            continue

    # Fallback: page refresh
    logger.info("Using page refresh as fallback.")
    driver.refresh()
    time.sleep(5)
    return True


# ============================================================
# Scroll to load all data
# ============================================================
def scroll_to_bottom(driver, pause=None, max_attempts=None):
    """
    Scroll down repeatedly to load all lazy-loaded table data.
    Scrolls the page (and any scrollable table container) until no new
    content loads.
    """
    pause = pause or cfg.get("scroll_pause_seconds", 2)
    max_attempts = max_attempts or cfg.get("max_scroll_attempts", 20)

    # Try to find scrollable table container
    scrollable_selectors = [
        "[class*='table-container']",
        "[class*='scanner-table']",
        "[class*='ag-body-viewport']",
        "[class*='virtual-scroll']",
        "[class*='scroll']",
        ".table-responsive",
    ]

    scroll_target = None
    for sel in scrollable_selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            if el.is_displayed():
                scroll_target = el
                break
        except NoSuchElementException:
            continue

    last_height = 0
    attempts = 0

    while attempts < max_attempts:
        if scroll_target:
            # Scroll within the container
            driver.execute_script(
                "arguments[0].scrollTop = arguments[0].scrollHeight", scroll_target
            )
        else:
            # Scroll the entire page
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")

        time.sleep(pause)

        if scroll_target:
            new_height = driver.execute_script(
                "return arguments[0].scrollHeight", scroll_target
            )
        else:
            new_height = driver.execute_script("return document.body.scrollHeight")

        if new_height == last_height:
            # No new content loaded, we've reached the bottom
            break

        last_height = new_height
        attempts += 1

    logger.info(f"Scrolling completed after {attempts} scroll attempts.")
    print(f"  Scrolled {attempts} times to load all data.")


# ============================================================
# Table scraping
# ============================================================
def scrape_fno_table(driver):
    """
    Scrape the FNO Scanner table data.

    Dynamically detects columns from table headers, then extracts all rows.
    Returns a DataFrame with all scraped data.
    """
    try:
        WebDriverWait(driver, cfg["max_table_wait_seconds"]).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
        )
    except TimeoutException:
        # Try alternate table selectors
        alt_selectors = [
            "[class*='ag-row']",
            "[class*='scanner'] table tr",
            "[role='row']",
        ]
        found = False
        for sel in alt_selectors:
            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                )
                found = True
                break
            except TimeoutException:
                continue

        if not found:
            logger.warning("FNO Scanner table not found.")
            return pd.DataFrame()

    # --- Extract column headers ---
    headers = []
    header_selectors = [
        "table thead th",
        "table thead td",
        "[class*='ag-header-cell-text']",
        "[role='columnheader']",
    ]

    for sel in header_selectors:
        header_elements = driver.find_elements(By.CSS_SELECTOR, sel)
        if header_elements:
            headers = [h.text.strip() for h in header_elements if h.text.strip()]
            if headers:
                break

    # Fallback headers if auto-detection fails
    if not headers:
        headers = [
            "Symbol", "Expiry", "Type", "Strike", "LTP",
            "Price Change", "Price Change %", "OI", "OI Change",
            "OI Change %", "IV", "IV Change", "IV Change %",
            "Volume", "Buildup"
        ]
        logger.info("Using fallback column headers.")

    # --- Extract table rows ---
    all_rows = []

    # Standard HTML table
    rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    if rows:
        for row in rows:
            cols = [td.text.strip() for td in row.find_elements(By.TAG_NAME, "td")]
            if cols and any(c for c in cols):  # Skip empty rows
                all_rows.append(cols)
    else:
        # AG-Grid or virtual table rows
        ag_rows = driver.find_elements(By.CSS_SELECTOR, "[class*='ag-row'], [role='row']")
        for row in ag_rows:
            cells = row.find_elements(By.CSS_SELECTOR, "[class*='ag-cell'], [role='gridcell'], td")
            cols = [c.text.strip() for c in cells]
            if cols and any(c for c in cols):
                all_rows.append(cols)

    if not all_rows:
        logger.warning("No data rows found in FNO Scanner table.")
        return pd.DataFrame()

    # Normalize column count
    max_cols = len(headers)
    normalized_rows = []
    for row in all_rows:
        if len(row) >= max_cols:
            normalized_rows.append(row[:max_cols])
        else:
            # Pad shorter rows
            normalized_rows.append(row + [""] * (max_cols - len(row)))

    df = pd.DataFrame(normalized_rows, columns=headers)
    df["Fetched At"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Add buildup classification
    df["Buildup Classification"] = df.apply(classify_buildup, axis=1)

    logger.info(f"Scraped {len(df)} rows from FNO Scanner.")
    return df


# ============================================================
# Futures table scraping (if separate FUT section exists)
# ============================================================
def scrape_futures_table(driver):
    """
    Scrape Futures data if displayed in a separate section/tab.
    Returns a DataFrame with futures data.
    """
    fut_selectors = [
        "[class*='futures'] table tbody tr",
        "[class*='fut-table'] tbody tr",
        "[data-tab='futures'] table tbody tr",
    ]

    for sel in fut_selectors:
        rows = driver.find_elements(By.CSS_SELECTOR, sel)
        if rows:
            all_rows = []
            for row in rows:
                cols = [td.text.strip() for td in row.find_elements(By.TAG_NAME, "td")]
                if cols and any(c for c in cols):
                    all_rows.append(cols)

            if all_rows:
                # Futures headers
                fut_headers = [
                    "Symbol", "Expiry", "LTP", "Fut Price Change",
                    "Fut Price Change %", "Fut OI", "Fut OI Change",
                    "Fut OI Change %", "Fut Volume", "Fut Buildup"
                ]

                max_cols = len(fut_headers)
                normalized = []
                for r in all_rows:
                    if len(r) >= max_cols:
                        normalized.append(r[:max_cols])
                    else:
                        normalized.append(r + [""] * (max_cols - len(r)))

                df = pd.DataFrame(normalized, columns=fut_headers)
                df["Fetched At"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                logger.info(f"Scraped {len(df)} futures rows.")
                return df

    return pd.DataFrame()


# ============================================================
# Core cycle: fetch + analyze + export
# ============================================================
def run_cycle(driver):
    """
    Perform one complete FNO Scanner cycle:
    1. Click Refresh / Play
    2. Wait for data load
    3. Scroll to bottom
    4. Scrape all data
    5. Export to Excel
    6. Run data analysis
    7. Send Telegram notification
    """
    cycle_start = datetime.now()
    try:
        logging.info("=" * 60)
        logging.info(f"Starting FNO Scanner cycle at {cycle_start.strftime('%H:%M:%S')}")
        print(f"\n{'='*60}")
        print(f"FNO Scanner Cycle - {cycle_start.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")

        # Step 1: Refresh page or click refresh button
        if cfg.get("auto_refresh_page", False):
            print("Step 1: Refreshing page...")
            click_refresh_button(driver)
            time.sleep(3)

        # Step 2: Click Play to execute scan
        print("Step 2: Executing scan (Play)...")
        click_play_button(driver)
        time.sleep(3)

        # Step 3: Wait for table to load
        print("Step 3: Waiting for data to load...")
        try:
            WebDriverWait(driver, cfg["max_table_wait_seconds"]).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
            )
        except TimeoutException:
            logger.warning("Table load timeout - attempting to proceed anyway.")

        # Step 4: Scroll to bottom to load all data
        print("Step 4: Scrolling to load all data...")
        scroll_to_bottom(driver)

        # Step 5: Scrape FNO data
        print("Step 5: Scraping FNO Scanner data...")
        df = scrape_fno_table(driver)

        # Also try to scrape Futures data
        df_fut = scrape_futures_table(driver)

        if df.empty and df_fut.empty:
            msg = f"No FNO data captured at {cycle_start.strftime('%H:%M:%S')}."
            logger.warning(msg)
            print(msg)
            send_telegram(msg)
            return

        # Step 6: Export to Excel with retry for locked files
        print("Step 6: Exporting to Excel...")
        output_file = cfg["output_file"]
        sheet_name = cfg["sheet_name"]

        if not df.empty:
            for attempt in range(cfg.get("max_retry_attempts", 3)):
                try:
                    append_df_to_excel(output_file, df, sheet_name=sheet_name)
                    break
                except PermissionError:
                    print(f"  Excel file locked - retry {attempt + 1}/3 in 10 sec...")
                    time.sleep(10)
            else:
                raise PermissionError("Excel file still locked after retries.")

        # Export Futures data if available
        if not df_fut.empty:
            for attempt in range(cfg.get("max_retry_attempts", 3)):
                try:
                    append_df_to_excel(output_file, df_fut, sheet_name="Futures_Data")
                    break
                except PermissionError:
                    time.sleep(10)

        # Also save as CSV for backup
        csv_dir = os.path.join("output", "csv")
        os.makedirs(csv_dir, exist_ok=True)
        csv_file = os.path.join(
            csv_dir,
            f"FNO_Scanner_{cycle_start.strftime('%Y%m%d_%H%M%S')}.csv"
        )
        if not df.empty:
            df.to_csv(csv_file, index=False)

        # Step 7: Run data analysis
        print("Step 7: Running data analysis...")
        total_rows = len(df) + len(df_fut)

        if not df.empty:
            analysis_results = analyze_fno_data(
                df, top_n=cfg.get("analysis_top_n", 20)
            )

            # Write analysis to Excel
            write_analysis_to_excel(output_file, analysis_results)

            # Generate analysis summary text
            summary_text = generate_analysis_summary_text(
                analysis_results,
                timestamp=cycle_start.strftime("%Y-%m-%d %H:%M:%S")
            )
            print(f"\n{summary_text}")

            # Send detailed Telegram notification
            msg = (
                f"FNO Scanner - {cycle_start.strftime('%H:%M:%S')}\n"
                f"FNO Rows: {len(df)}"
            )
            if not df_fut.empty:
                msg += f" | Futures Rows: {len(df_fut)}"
            msg += f"\n\n{summary_text}"

            # Telegram has 4096 char limit
            if len(msg) > 4000:
                send_telegram(msg[:4000])
            else:
                send_telegram(msg)

        # Step 8: Format Excel
        print("Step 8: Formatting Excel...")
        format_fno_excel(output_file)

        # Success
        elapsed = (datetime.now() - cycle_start).total_seconds()
        success_msg = (
            f"FNO Scanner cycle complete - {total_rows} total rows "
            f"at {cycle_start.strftime('%H:%M:%S')} ({elapsed:.0f}s)"
        )
        print(f"\n{success_msg}")
        logger.info(success_msg)

    except Exception as e:
        err = f"Error during FNO Scanner cycle at {cycle_start.strftime('%H:%M:%S')}: {e}"
        logger.error(err, exc_info=True)
        print(err)
        send_telegram(err)
        time.sleep(30)


# ============================================================
# Main entry point
# ============================================================
def main():
    """Main entry point for FNO Scanner."""
    print("=" * 60)
    print("  FNO Scanner - Stock Market Automation")
    print("  Standalone Python Script")
    print("=" * 60)

    # Initialize browser
    print("\nStarting browser...")
    driver = setup_browser()

    try:
        # Navigate to FNO Scanner
        url = cfg["start_url"]
        print(f"Opening: {url}")
        driver.get(url)

        # Manual login step
        print("\n" + "-" * 60)
        print("MANUAL STEPS REQUIRED:")
        print("  1. Login with OTP on the page")
        print("  2. Navigate to Tools > FNO Scanner")
        print("  3. Set filters:")
        print(f"     - Instrument: {cfg['filters']['instrument']}")
        print(f"     - Expiry: {cfg['filters']['expiry']}")
        print("     - Price Change: as needed")
        print("     - OI Change: as needed")
        print("     - IV Change %: as needed")
        print("  4. Click Play to execute the scan once")
        print("  5. Verify data is displayed in the table")
        print("-" * 60)
        input("\nPress Enter after login, filters are set, and data is visible...")

        # Try to auto-apply filters (may or may not work depending on page state)
        try:
            apply_filters(driver, cfg["filters"])
        except Exception as e:
            logger.info(f"Auto-filter skipped (user already set filters): {e}")

        # First immediate run
        print("\nStarting first scan cycle...")
        run_cycle(driver)

        # Schedule recurring cycles
        interval = cfg["fetch_interval_minutes"]
        schedule.every(interval).minutes.do(lambda: run_cycle(driver))

        # Daily summary and visual report at end of day
        daily_time = cfg.get("daily_summary_time", "23:59")
        schedule.every().day.at(daily_time).do(
            lambda: generate_daily_summary(cfg["output_file"])
        )
        schedule.every().day.at(daily_time).do(
            lambda: generate_fno_visual_report(cfg["output_file"])
        )

        print(f"\nFNO Scanner running every {interval} minutes.")
        print(f"Daily summary at {daily_time}.")
        print("Press Ctrl+C to stop.\n")

        send_telegram(
            f"FNO Scanner started. Fetching every {interval} minutes. "
            f"Daily report at {daily_time}."
        )

        # Continuous loop
        while True:
            schedule.run_pending()
            time.sleep(1)

    except KeyboardInterrupt:
        stop_msg = "FNO Scanner stopped by user."
        print(f"\n{stop_msg}")
        logger.info(stop_msg)
        try:
            # Generate final summary before exit
            generate_daily_summary(cfg["output_file"])
            format_fno_excel(cfg["output_file"])
        except Exception:
            pass
        try:
            send_telegram(stop_msg)
        except Exception:
            pass
    finally:
        try:
            driver.quit()
            print("Browser closed.")
        except Exception:
            pass


if __name__ == "__main__":
    main()
