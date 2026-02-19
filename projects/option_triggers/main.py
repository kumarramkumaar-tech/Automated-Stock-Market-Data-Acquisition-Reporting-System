# main.py – Option Triggers Module (Priority Project 1)
#
# MARKET HOURS: Normal 08:30-16:15 IST; Extended 07:00-21:00 until 2026-02-20
#
# Automated 40-minute cycle that:
#   1. Opens Quantsapp Option Triggers page
#   2. Scrapes all trigger data
#   3. Applies 4-Rule Filter:
#      Rule 1: Highest CE OI Changes
#      Rule 2: Call-Put diff between -1% to +1%
#      Rule 3: Stock must be in WBRam local Excel watchlist
#      Rule 4: Column O (LTP) must be TRUE, then check price columns
#   4. For each qualifying stock, navigates to ALL Quantsapp tools:
#      - Option Triggers (CE/PE OI, volumes, trigger type)
#      - IV Analysis (IV, IVP, IV Rank, HV, IV vs HV)
#      - OI Analysis (Total OI, max strikes, support/resistance)
#      - PCR Analysis (PCR by OI/Volume, trend)
#      - Buildup (Long/Short Buildup, Unwinding, Covering)
#      - Futures OI (OI change, basis, signal)
#      - Max Pain (Max pain strike, distance from CMP)
#   5. Saves 40+ column Excel with per-tool analysis
#   6. Generates PDF visual reports per stock
#   7. Sends Telegram announcement:
#      "Stock Pick from WBRam Excel is <STOCK NAME>" + full analysis
#
# ── FNO Scanner Integration ─────────────────────────────────
# The FNO Scanner module runs as a companion process alongside this script.
# It provides the MAIN reference data file for all FNO trading analysis.
#
# FNO Scanner Schedule:
#   - Runs every 30 minutes during market hours (09:00 AM - 04:15 PM IST)
#   - Weekdays only (Mon-Fri)
#   - Output: projects/fno_scanner/output/FNO_Scanner_Data.xlsx
#   - Sheets: FNO_Data, Futures_Data, Signals, Top_OI_Gainers, Top_OI_Losers,
#             Top_IV_Movers, Top_Price_Movers, Buildup_Summary, Daily_Summary
#
# How to run FNO Scanner alongside Option Triggers:
#   Terminal 1: cd projects/option_triggers && python main.py
#   Terminal 2: cd projects/fno_scanner && python fno_scanner.py
#
# The unified dashboard (python dashboard.py) reads from ALL modules:
#   - Option Triggers: output/Option_Triggers_Analysis.xlsx
#   - Unusual Activity: output/Quantsapp_Unusual_Activity.xlsx (root)
#   - FNO Scanner:      projects/fno_scanner/output/FNO_Scanner_Data.xlsx

import json
import os
import sys
import time
import logging
import subprocess
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

from helpers.excel_utils import append_df_to_excel, write_sheet
from helpers.notify import send_telegram, send_telegram_file
from helpers.report_utils import save_picks_to_excel, update_summary, format_excel
from helpers.report_visuals import generate_visual_report, generate_summary_report
from helpers.stock_picker import run_stock_picker
from helpers.quantsapp_tools import _wait_and_get_table, collect_all_tool_data, _clean_symbol


# ── Logging ──────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/option_triggers.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Also log to console
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger("").addHandler(console)


# ── Load Config ──────────────────────────────────────────────
with open("config.json") as f:
    cfg = json.load(f)


# ── Setup Browser ────────────────────────────────────────────
# Two modes:
#   1. Attach to existing Chrome (if --remote-debugging-port is running)
#   2. Launch new Chrome (fallback)

DEBUGGING_PORT = cfg.get("chrome_debugging_port", 9222)

options = webdriver.ChromeOptions()

# Try attaching to an already-running Chrome with remote debugging
attach_mode = False
try:
    import urllib.request
    urllib.request.urlopen(f"http://127.0.0.1:{DEBUGGING_PORT}/json/version", timeout=2)
    attach_mode = True
except Exception:
    pass

if attach_mode:
    # ── Attach to existing Chrome session ──
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{DEBUGGING_PORT}")
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options,
    )
    print("=" * 60)
    print("  OPTION TRIGGERS MODULE – Priority Project 1")
    print("  (Attached to existing Chrome session)")
    print("=" * 60)
    print()
    logger.info("Attached to existing Chrome on port %s", DEBUGGING_PORT)

    # Navigate to Option Triggers page in existing browser
    driver.get(cfg["start_url"])
    time.sleep(3)
else:
    # ── Launch new Chrome ──
    if cfg.get("headless"):
        options.add_argument("--headless=new")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options,
    )
    driver.get(cfg["start_url"])

    print("=" * 60)
    print("  OPTION TRIGGERS MODULE – Priority Project 1")
    print("  (New Chrome window launched)")
    print("=" * 60)
    print()
    print("STEP 1: Login to Quantsapp manually with OTP")
    print("STEP 2: Navigate to Option Triggers page")
    print("STEP 3: Make sure the following tabs/tools are accessible:")
    print("   - Option Triggers / IV Analysis / OI Analysis")
    print("   - PCR Analysis / Buildup / Futures OI / Max Pain / Option Chain")
    print()
    input("Press Enter after login and setup is complete...")
    logger.info("New Chrome launched — user completed manual login.")


# ── Core: Scrape Option Triggers Table ───────────────────────
def fetch_option_triggers():
    """
    Scrape the Option Triggers table from Quantsapp.
    Returns DataFrame with all trigger rows.
    """
    try:
        driver.get(cfg["start_url"])
        time.sleep(5)

        WebDriverWait(driver, cfg["max_table_wait_seconds"]).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
        )
    except Exception as e:
        logger.warning(f"Option Triggers table not found: {e}")
        return pd.DataFrame()

    max_retries = 3
    all_rows = []
    for attempt in range(max_retries):
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            all_rows = []
            for row in rows:
                cols = [td.text.strip() for td in row.find_elements(By.TAG_NAME, "td")]
                if cols:
                    all_rows.append(cols)
            break
        except StaleElementReferenceException:
            if attempt < max_retries - 1:
                logger.warning(f"StaleElementReferenceException on attempt {attempt + 1}, retrying...")
                time.sleep(2)
            else:
                logger.error("StaleElementReferenceException persisted after retries.")
                return pd.DataFrame()

    if not all_rows:
        return pd.DataFrame()

    # Determine actual data width from rows
    actual_col_count = max(len(r) for r in all_rows)
    logger.info(f"Scraped rows have {actual_col_count} columns each")

    # Try to get headers from page
    try:
        header_els = driver.find_elements(By.CSS_SELECTOR, "table thead th")
        page_headers = [th.text.strip() for th in header_els]
    except (StaleElementReferenceException, Exception):
        page_headers = []

    # IMPORTANT: Trim headers to match actual data width, not the other way around.
    # Quantsapp often has more <th> headers than <td> data cells per row.
    if page_headers and len(page_headers) >= actual_col_count:
        headers = page_headers[:actual_col_count]
    elif page_headers:
        headers = page_headers
        # Pad if rows have more data than headers
        headers.extend([f"Col_{i}" for i in range(len(headers), actual_col_count)])
    else:
        # No page headers found - use fallback based on actual column count
        headers = []

    # If no usable headers, use defaults trimmed to actual data width
    if not headers:
        fallback = [
            "Symbol", "Price", "Price Change %", "OI Change %",
            "Trigger Type", "Volume", "CE OI Change %",
            "LTP", "LTP Change", "Strike",
            "PE LTP Change", "PE OI Change %", "PE Volume"
        ]
        if actual_col_count <= len(fallback):
            headers = fallback[:actual_col_count]
        else:
            headers = fallback + [f"Col_{i}" for i in range(len(fallback), actual_col_count)]

    logger.info(f"Using {len(headers)} headers: {headers}")

    # Normalize row lengths to match header count
    normalized = []
    for row in all_rows:
        if len(row) < len(headers):
            row.extend([""] * (len(headers) - len(row)))
        normalized.append(row[:len(headers)])

    df = pd.DataFrame(normalized, columns=headers)
    df["Fetched At"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    logger.info(f"Scraped {len(df)} rows from Option Triggers")
    return df


# ── CLI Flags ────────────────────────────────────────────────
TEST_MODE = "--test" in sys.argv  # Bypass 4-rule filter, run analysis on ALL scraped stocks


# ── Core: Full 40-Minute Cycle ───────────────────────────────
def run_cycle():
    """
    One complete 40-minute cycle:
      1. Scrape Option Triggers table
      2. Save raw data to Excel
      3. Apply 4-Rule filter to find stock picks
      4. For each pick: collect ALL Quantsapp tool data
      5. Save detailed 40+ column analysis to Excel
      6. Generate visual PDF reports
      7. Send Telegram announcements
    """
    cycle_start = datetime.now()
    logger.info(f"{'='*50}")
    logger.info(f"Starting cycle at {cycle_start.strftime('%H:%M:%S')}")

    try:
        # ── Step 1: Refresh and scrape Option Triggers ────
        if cfg.get("auto_refresh_page", False):
            driver.refresh()
            time.sleep(5)

        triggers_df = fetch_option_triggers()

        if triggers_df.empty:
            msg = f"No data from Option Triggers at {cycle_start.strftime('%H:%M:%S')}"
            logger.warning(msg)
            send_telegram(msg)
            return

        # ── Step 2: Save raw triggers to Excel ────────────
        output_file = cfg["output_file"]
        for attempt in range(cfg.get("max_retry_attempts", 3)):
            try:
                append_df_to_excel(output_file, triggers_df, sheet_name="Triggers_Raw")
                break
            except PermissionError:
                logger.warning(f"Excel locked – retry {attempt + 1}")
                time.sleep(10)
        else:
            raise PermissionError("Excel file locked after max retries")

        logger.info(f"Saved {len(triggers_df)} raw trigger rows to Excel")

        # ── Step 3: Run Stock Picker (or bypass in test mode) ──
        if TEST_MODE:
            # TEST MODE: Skip 4-rule filter, analyze ALL scraped symbols
            logger.info("TEST MODE: Bypassing 4-rule filter — analyzing ALL scraped symbols")
            send_telegram("TEST MODE: Bypassing 4-rule filter — analyzing all symbols")

            # Find symbol column
            sym_col = None
            for col in triggers_df.columns:
                if col.upper() in ["SYMBOL", "STOCK", "NAME", "SCRIP"]:
                    sym_col = col
                    break
            if sym_col is None:
                sym_col = triggers_df.columns[4] if len(triggers_df.columns) > 4 else triggers_df.columns[0]

            symbols = triggers_df[sym_col].dropna().astype(str).str.strip().unique().tolist()
            symbols = [_clean_symbol(s) for s in symbols if s]
            logger.info(f"TEST MODE: Found {len(symbols)} symbols to analyze: {symbols}")

            tool_urls = cfg.get("quantsapp_tools_urls", {})
            wait_seconds = cfg.get("max_table_wait_seconds", 15)

            picks = []
            for symbol in symbols:
                logger.info(f"TEST MODE: Collecting full analysis for {symbol}...")
                try:
                    tool_data = collect_all_tool_data(driver, symbol, tool_urls, wait_seconds)
                    picks.append(tool_data)
                except Exception as e:
                    logger.error(f"TEST MODE: Failed for {symbol}: {e}")
                    picks.append({
                        "Symbol": symbol,
                        "Analysis_Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Error": str(e),
                    })
            announcement = f"TEST MODE: Analyzed {len(picks)} symbols"
        else:
            logger.info("Running 4-Rule Stock Picker...")
            picks, announcement = run_stock_picker(driver, triggers_df, cfg)

        if not picks:
            msg = f"No stocks qualified after 4-rule filter at {cycle_start.strftime('%H:%M:%S')}"
            logger.info(msg)
            send_telegram(msg)

            # Still update summary and format
            try:
                update_summary(output_file)
                format_excel(output_file)
            except Exception as e:
                logger.warning(f"Post-cycle formatting failed: {e}")
            return

        # ── Step 4: Save detailed analysis to Excel ───────
        logger.info(f"Saving {len(picks)} stock picks with full tool analysis...")
        save_picks_to_excel(picks, output_file)

        # ── Step 5: Format Excel ──────────────────────────
        try:
            update_summary(output_file)
            format_excel(output_file)
        except Exception as e:
            logger.warning(f"Excel formatting failed: {e}")

        # ── Step 6: Generate visual reports ───────────────
        try:
            generate_visual_report(output_file, report_dir="reports")
        except Exception as e:
            logger.warning(f"Visual report failed: {e}")

        # ── Step 7: Send Telegram announcement ────────────
        for pick in picks:
            symbol = pick.get("Symbol", "Unknown")
            ivp_status = pick.get("IVP_Status", "N/A")
            bu_type = pick.get("BU_Type", "N/A")
            verdict = pick.get("Overall_Verdict", "N/A")

            trap_info = pick.get('TRAP_Indicator', '')
            trap_note = pick.get('TRAP_Note', '')
            iv_summary = pick.get('IV_Summary', '')
            oi_strikes = pick.get('OI_Strikes_Summary', '')
            bu_fut_oih = pick.get('BU_FUT_OIH', '')
            bu_scrip_cycle = pick.get('BU_Scrip_Cycle', '')
            bu_sector = pick.get('BU_Sector', '')
            bu_sector_cycle = pick.get('BU_Sector_Cycle', '')
            bu_sector_oih = pick.get('BU_Sector_OIH', '')

            msg = (
                f"*Stock Pick from WBRam Excel is \"{symbol}\"*\n"
                f"{'─' * 30}\n"
                f"*Option Triggers:*\n"
                f"  CE OI Change: {pick.get('OT_CE_OI_Change_Pct', 'N/A')}%\n"
                f"  PE OI Change: {pick.get('OT_PE_OI_Change_Pct', 'N/A')}%\n"
                f"  Call-Put Diff: {pick.get('OT_Call_Put_Diff_Pct', 'N/A')}%\n"
                f"  LTP: {pick.get('OT_LTP', 'N/A')}\n\n"
                f"*[G] Writers Trap:* {trap_info or 'N/A'}"
                f"{' - ' + trap_note if trap_note else ''}\n"
                f"*[H] IV Summary:* {iv_summary or 'N/A'}\n"
                f"*[I] OI Strikes:*\n  {oi_strikes or 'N/A'}\n\n"
                f"*[J] FUT OI-H:* {bu_fut_oih or 'N/A'}\n"
                f"*[K] Scrip Cycle:* {bu_scrip_cycle or 'N/A'}\n"
                f"*[L] Sector:* {bu_sector or 'N/A'}\n"
                f"*[M] Sector Cycle:* {bu_sector_cycle or 'N/A'}\n"
                f"*[N] Sector OI-H:* {bu_sector_oih or 'N/A'}\n\n"
                f"*IV Analysis:*\n"
                f"  IVP: {pick.get('IVP', 'N/A')} ({ivp_status})\n"
                f"  IV Signal: {pick.get('IV_Signal', 'N/A')}\n\n"
                f"*OI Analysis:*\n"
                f"  Resistance: {pick.get('OI_Max_CE_Strike', 'N/A')}\n"
                f"  Support: {pick.get('OI_Max_PE_Strike', 'N/A')}\n"
                f"  OI Trend: {pick.get('OI_Trend', 'N/A')}\n\n"
                f"*PCR:* {pick.get('PCR_OI', 'N/A')} ({pick.get('PCR_Signal', 'N/A')})\n"
                f"*Buildup:* {bu_type} ({pick.get('BU_Signal', 'N/A')})\n"
                f"*Futures OI:* {pick.get('FUT_OI_Change_Pct', 'N/A')}% ({pick.get('FUT_Signal', 'N/A')})\n"
                f"*Max Pain:* {pick.get('MP_Strike', 'N/A')} ({pick.get('MP_Signal', 'N/A')})\n\n"
                f"*VERDICT: {verdict}*"
            )
            send_telegram(msg)

        # ── Step 8: Send Excel file to Telegram ───────────
        try:
            send_telegram_file(output_file)
        except Exception as e:
            logger.warning(f"Failed to send Excel via Telegram: {e}")

        # Cycle complete
        duration = (datetime.now() - cycle_start).total_seconds()
        done_msg = (
            f"Cycle complete: {len(picks)} picks analyzed "
            f"in {duration:.0f}s at {datetime.now().strftime('%H:%M:%S')}"
        )
        logger.info(done_msg)
        send_telegram(done_msg)

    except Exception as e:
        err = f"Cycle error at {datetime.now().strftime('%H:%M:%S')}: {e}"
        logger.error(err, exc_info=True)
        send_telegram(err)
        time.sleep(60)


# ── Navigate back to Option Triggers before cycle ────────────
def pre_cycle():
    """Navigate back to Option Triggers page before each cycle."""
    try:
        driver.get(cfg["start_url"])
        time.sleep(3)
    except Exception as e:
        logger.warning(f"Pre-cycle navigation failed: {e}")


# ── Market Hours Config ──────────────────────────────────────
# Extended window: 7 AM - 9 PM for 3 days (expires 2026-02-20)
# After expiry, reverts to normal 08:30-16:15
from datetime import date as _date

_EXTENDED_EXPIRY = _date(2026, 2, 20)  # 3 days from 2026-02-17

# Normal market hours
_NORMAL_OPEN_HOUR = 8
_NORMAL_OPEN_MIN = 30
_NORMAL_CLOSE_HOUR = 16
_NORMAL_CLOSE_MIN = 15

# Extended hours
_EXTENDED_OPEN_HOUR = 7
_EXTENDED_OPEN_MIN = 0
_EXTENDED_CLOSE_HOUR = 21
_EXTENDED_CLOSE_MIN = 0


def _get_market_hours():
    """Return (open_hour, open_min, close_hour, close_min) based on date."""
    today = _date.today()
    if today <= _EXTENDED_EXPIRY:
        return _EXTENDED_OPEN_HOUR, _EXTENDED_OPEN_MIN, _EXTENDED_CLOSE_HOUR, _EXTENDED_CLOSE_MIN
    return _NORMAL_OPEN_HOUR, _NORMAL_OPEN_MIN, _NORMAL_CLOSE_HOUR, _NORMAL_CLOSE_MIN


def _market_hours_label():
    """Return human-readable market hours string."""
    oh, om, ch, cm = _get_market_hours()
    return f"{oh:02d}:{om:02d}-{ch:02d}:{cm:02d}"


def is_market_hours():
    """Check if current time is within the active market hours window."""
    now = datetime.now()
    oh, om, ch, cm = _get_market_hours()
    market_open = now.replace(hour=oh, minute=om, second=0, microsecond=0)
    market_close = now.replace(hour=ch, minute=cm, second=0, microsecond=0)
    return market_open <= now <= market_close


def guarded_cycle():
    """Only run the cycle during market hours."""
    if not is_market_hours():
        now = datetime.now().strftime("%H:%M:%S")
        label = _market_hours_label()
        logger.info(f"Outside market hours ({now}). Skipping cycle. Active: {label}")
        return
    pre_cycle()
    run_cycle()


# ── FNO Scanner Subprocess Management ────────────────────────
# FNO Scanner runs every 30 minutes during standard market hours (09:00-16:15)
# on weekdays only. It is the MAIN reference data file for all FNO trading analysis.

FNO_SCANNER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fno_scanner")
FNO_SCANNER_SCRIPT = os.path.join(FNO_SCANNER_DIR, "fno_scanner.py")
FNO_SCANNER_INTERVAL = 30  # minutes
FNO_MARKET_OPEN_HOUR, FNO_MARKET_OPEN_MIN = 9, 0
FNO_MARKET_CLOSE_HOUR, FNO_MARKET_CLOSE_MIN = 16, 15
_fno_process = None


def is_fno_market_hours():
    """Check if current time is within FNO market hours (09:00-16:15, weekdays)."""
    now = datetime.now()
    # Weekdays only (0=Monday, 4=Friday)
    if now.weekday() > 4:
        return False
    market_open = now.replace(hour=FNO_MARKET_OPEN_HOUR, minute=FNO_MARKET_OPEN_MIN, second=0, microsecond=0)
    market_close = now.replace(hour=FNO_MARKET_CLOSE_HOUR, minute=FNO_MARKET_CLOSE_MIN, second=0, microsecond=0)
    return market_open <= now <= market_close


def start_fno_scanner():
    """Launch FNO Scanner as a subprocess if not already running."""
    global _fno_process
    if not os.path.exists(FNO_SCANNER_SCRIPT):
        logger.warning(f"FNO Scanner script not found: {FNO_SCANNER_SCRIPT}")
        return

    # Check if already running
    if _fno_process is not None and _fno_process.poll() is None:
        logger.info("FNO Scanner already running (PID %s)", _fno_process.pid)
        return

    if not is_fno_market_hours():
        now = datetime.now().strftime("%H:%M:%S")
        logger.info(f"FNO Scanner: outside market hours ({now}). "
                     f"Active: {FNO_MARKET_OPEN_HOUR:02d}:{FNO_MARKET_OPEN_MIN:02d}-"
                     f"{FNO_MARKET_CLOSE_HOUR:02d}:{FNO_MARKET_CLOSE_MIN:02d} weekdays")
        return

    logger.info("Starting FNO Scanner subprocess...")
    try:
        _fno_process = subprocess.Popen(
            [sys.executable, FNO_SCANNER_SCRIPT],
            cwd=FNO_SCANNER_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        logger.info(f"FNO Scanner started (PID {_fno_process.pid})")
        send_telegram(f"FNO Scanner started (PID {_fno_process.pid}) — "
                       f"every {FNO_SCANNER_INTERVAL} min during 09:00-16:15 weekdays")
    except Exception as e:
        logger.error(f"Failed to start FNO Scanner: {e}")


def stop_fno_scanner():
    """Stop the FNO Scanner subprocess if running."""
    global _fno_process
    if _fno_process is not None and _fno_process.poll() is None:
        logger.info(f"Stopping FNO Scanner (PID {_fno_process.pid})...")
        _fno_process.terminate()
        try:
            _fno_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _fno_process.kill()
        logger.info("FNO Scanner stopped.")
    _fno_process = None


def check_fno_scanner():
    """Scheduled check: start FNO Scanner during market hours, stop outside."""
    if is_fno_market_hours():
        start_fno_scanner()
    else:
        stop_fno_scanner()


# ── Scheduler ────────────────────────────────────────────────

interval = cfg.get("fetch_interval_minutes", 40)

# Show active market hours
_hours_label = _market_hours_label()
_is_extended = _date.today() <= _EXTENDED_EXPIRY
_mode_note = f" (EXTENDED until {_EXTENDED_EXPIRY})" if _is_extended else ""

# First run – check market hours (test mode always runs immediately)
if TEST_MODE:
    print("=" * 60)
    print("  TEST MODE ACTIVE — Bypassing 4-rule filter")
    print("  All scraped symbols will get full Columns G-N analysis")
    print("=" * 60)
    logger.info("TEST MODE: Running immediately, bypassing filters")
    send_telegram(f"TEST MODE started — bypassing 4-rule filter, analyzing all symbols. Hours: {_hours_label}{_mode_note}")
    run_cycle()
    # In test mode, exit after one cycle
    print("\nTEST MODE: Single cycle complete. Exiting.")
    logger.info("TEST MODE: Single cycle complete. Exiting.")
    try:
        driver.quit()
    except Exception:
        pass
    sys.exit(0)
elif is_market_hours():
    logger.info("Running first cycle immediately on startup...")
    send_telegram(f"Option Triggers bot started — first scan running now. Hours: {_hours_label}{_mode_note}, every {interval} min.")
    run_cycle()
else:
    now_str = datetime.now().strftime("%H:%M:%S")
    msg = f"Option Triggers bot started at {now_str} (outside market hours {_hours_label}{_mode_note}). Waiting..."
    print(msg)
    logger.info(msg)
    send_telegram(msg)

# Schedule every 40 minutes (guarded by market hours check)
schedule.every(interval).minutes.do(guarded_cycle)

# ── FNO Scanner: Start on boot + check every 30 minutes ─────
check_fno_scanner()
schedule.every(FNO_SCANNER_INTERVAL).minutes.do(check_fno_scanner)

# Daily summary at 16:15 (market close)
schedule.every().day.at("16:15").do(lambda: (
    generate_summary_report(cfg["output_file"]),
    send_telegram("Market closed (04:15 PM). Daily summary generated."),
))

# Stop FNO Scanner at market close
schedule.every().day.at("16:16").do(stop_fno_scanner)

# Start-of-day notification
schedule.every().day.at("08:30").do(
    lambda: send_telegram(f"Market open. Option Triggers scanning started. Hours: {_market_hours_label()}")
)

# Start FNO Scanner at 09:00 on weekdays
schedule.every().day.at("09:00").do(start_fno_scanner)

print()
print(f"Running every {interval} minutes during market hours ({_hours_label}{_mode_note}).")
print(f"FNO Scanner: every {FNO_SCANNER_INTERVAL} min during 09:00-16:15 (weekdays)")
print(f"Output file: {cfg['output_file']}")
print(f"FNO output:  {FNO_SCANNER_DIR}/output/FNO_Scanner_Data.xlsx")
print(f"Reports: reports/")
print()

# ── Main Loop ────────────────────────────────────────────────
try:
    while True:
        schedule.run_pending()
        time.sleep(1)
except KeyboardInterrupt:
    stop_msg = "Option Triggers automation stopped by user."
    print("\n" + stop_msg)
    logger.info(stop_msg)
    stop_fno_scanner()
    try:
        send_telegram(stop_msg)
    except Exception:
        pass
    try:
        driver.quit()
    except Exception:
        pass
