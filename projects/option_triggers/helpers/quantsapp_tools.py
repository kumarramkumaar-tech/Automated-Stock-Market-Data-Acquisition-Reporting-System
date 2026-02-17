# helpers/quantsapp_tools.py – Scrape ALL Quantsapp tools for a given stock
#
# For each stock pick, this module navigates to each Quantsapp tool page
# and extracts the relevant data columns. Returns a consolidated dict
# with one column per data point across all tools.
#
# Quantsapp Tools covered:
#   1. Option Triggers  – CE/PE OI, OI Change, Trigger signals
#   2. IV Analysis      – IV, IVP (IV Percentile), IV Rank, HV
#   3. OI Analysis      – Total CE/PE OI, OI distribution, Max OI strikes
#   4. PCR Analysis     – PCR by OI, PCR by Volume, trend
#   5. Buildup          – Long/Short Buildup, Unwinding, Covering
#   6. Futures OI       – Futures OI, OI change, basis
#   7. Max Pain         – Max Pain strike, distance from CMP
#   8. Multi Strike OI  – Strike-wise OI breakdown
#   9. Option Chain     – Full chain with Greeks

import re
import time
import logging
import pandas as pd
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException

logger = logging.getLogger(__name__)


def _clean_symbol(symbol):
    """
    Extract only the stock symbol name, stripping any expiry date suffix.
    e.g. "RBLBANK 24-FEB-26" -> "RBLBANK"
         "JSWSTEEL 24-FEB-26" -> "JSWSTEEL"
         "RELIANCE" -> "RELIANCE"
    """
    if not symbol:
        return symbol
    # Remove date patterns like "24-FEB-26", "24-Feb-2026", "2026-02-24", etc.
    cleaned = re.sub(r'\s+\d{1,2}-[A-Za-z]{3}-\d{2,4}', '', symbol).strip()
    cleaned = re.sub(r'\s+\d{4}-\d{2}-\d{2}', '', cleaned).strip()
    cleaned = re.sub(r'\s+\d{1,2}\s+[A-Za-z]{3}\s+\d{2,4}', '', cleaned).strip()
    # Fallback: just take the first word (the symbol name)
    if ' ' in cleaned:
        cleaned = cleaned.split()[0]
    return cleaned.upper()


def _wait_and_get_table(driver, wait_seconds=15):
    """Wait for a table to load and return all rows as list of lists."""
    try:
        WebDriverWait(driver, wait_seconds).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
        )
    except Exception:
        return []

    for attempt in range(3):
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            all_rows = []
            for row in rows:
                cols = [td.text.strip() for td in row.find_elements(By.TAG_NAME, "td")]
                if cols:
                    all_rows.append(cols)
            return all_rows
        except StaleElementReferenceException:
            if attempt < 2:
                logger.warning(f"StaleElementReferenceException on attempt {attempt + 1}, retrying...")
                time.sleep(2)
            else:
                logger.error("StaleElementReferenceException persisted after retries.")
                return []


def _get_page_text_data(driver, wait_seconds=10):
    """
    For tools that display data as cards/divs rather than tables,
    extract all visible text from the main content area.
    """
    try:
        WebDriverWait(driver, wait_seconds).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".main-content, .card, .data-container, main"))
        )
    except Exception:
        pass

    # Try multiple selectors for different Quantsapp page layouts
    selectors = [
        ".data-value", ".card-body", ".metric-value",
        "[class*='value']", "[class*='data']", ".info-row"
    ]

    for attempt in range(3):
        try:
            data = {}
            for selector in selectors:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for elem in elements:
                    text = elem.text.strip()
                    if text:
                        # Try to parse "Label: Value" or "Label\nValue" patterns
                        if ":" in text:
                            parts = text.split(":", 1)
                            data[parts[0].strip()] = parts[1].strip()
                        elif "\n" in text:
                            lines = text.split("\n")
                            if len(lines) >= 2:
                                data[lines[0].strip()] = lines[1].strip()
            return data
        except StaleElementReferenceException:
            if attempt < 2:
                logger.warning(f"StaleElement in _get_page_text_data attempt {attempt + 1}, retrying...")
                time.sleep(2)
            else:
                logger.error("StaleElement in _get_page_text_data persisted after retries.")
                return {}


def _search_symbol_on_page(driver, symbol, wait_seconds=5):
    """
    Try to search/select a symbol on the current Quantsapp tool page.
    Quantsapp typically has a search/dropdown for symbol selection.
    """
    search_selectors = [
        "input[placeholder*='search' i]",
        "input[placeholder*='symbol' i]",
        "input[placeholder*='stock' i]",
        "input[type='search']",
        ".symbol-search input",
        ".search-box input",
        "input.form-control",
    ]

    for selector in search_selectors:
        for attempt in range(2):
            try:
                search_input = driver.find_element(By.CSS_SELECTOR, selector)
                search_input.clear()
                search_input.send_keys(symbol)
                time.sleep(2)

                # Try clicking a dropdown suggestion
                suggestion_selectors = [
                    f"[class*='dropdown'] [class*='item']",
                    f"[class*='suggestion']",
                    f"[class*='option']",
                    f"li[class*='result']",
                    f".dropdown-menu a",
                ]
                for sug_sel in suggestion_selectors:
                    suggestions = driver.find_elements(By.CSS_SELECTOR, sug_sel)
                    for sug in suggestions:
                        if symbol.upper() in sug.text.upper():
                            sug.click()
                            time.sleep(3)
                            return True
                return True
            except StaleElementReferenceException:
                if attempt == 0:
                    time.sleep(2)
                    continue
                break
            except Exception:
                break

    return False


# ============================================================
# Individual tool scrapers
# ============================================================

def scrape_option_triggers(driver, symbol, url, wait_seconds=15):
    """
    Tool 1: Option Triggers
    Returns dict with CE/PE OI changes, trigger type, volumes.
    """
    result = {
        "OT_CE_OI": "", "OT_CE_OI_Change": "", "OT_CE_OI_Change_Pct": "",
        "OT_PE_OI": "", "OT_PE_OI_Change": "", "OT_PE_OI_Change_Pct": "",
        "OT_CE_Volume": "", "OT_PE_Volume": "",
        "OT_Trigger_Type": "", "OT_LTP": "", "OT_Change_Pct": "",
        "OT_Call_Put_Diff_Pct": "",
    }

    try:
        driver.get(url)
        time.sleep(3)
        _search_symbol_on_page(driver, symbol)

        rows = _wait_and_get_table(driver, wait_seconds)

        # Find rows matching our symbol
        for row in rows:
            row_text = " ".join(row).upper()
            if symbol.upper() in row_text:
                # Map columns based on typical Option Triggers layout
                if len(row) >= 10:
                    result["OT_CE_OI"] = row[2] if len(row) > 2 else ""
                    result["OT_CE_OI_Change"] = row[3] if len(row) > 3 else ""
                    result["OT_CE_OI_Change_Pct"] = row[4] if len(row) > 4 else ""
                    result["OT_PE_OI"] = row[5] if len(row) > 5 else ""
                    result["OT_PE_OI_Change"] = row[6] if len(row) > 6 else ""
                    result["OT_PE_OI_Change_Pct"] = row[7] if len(row) > 7 else ""
                    result["OT_LTP"] = row[8] if len(row) > 8 else ""
                    result["OT_Change_Pct"] = row[9] if len(row) > 9 else ""

                    # Calculate Call-Put diff
                    try:
                        ce_chg = float(result["OT_CE_OI_Change_Pct"].replace("%", "").replace(",", ""))
                        pe_chg = float(result["OT_PE_OI_Change_Pct"].replace("%", "").replace(",", ""))
                        result["OT_Call_Put_Diff_Pct"] = str(round(ce_chg - pe_chg, 2))
                    except (ValueError, TypeError):
                        result["OT_Call_Put_Diff_Pct"] = ""

                if len(row) >= 12:
                    result["OT_CE_Volume"] = row[10] if len(row) > 10 else ""
                    result["OT_PE_Volume"] = row[11] if len(row) > 11 else ""
                    result["OT_Trigger_Type"] = row[12] if len(row) > 12 else ""
                break

    except Exception as e:
        logger.warning(f"Option Triggers scrape failed for {symbol}: {e}")

    return result


def scrape_iv_analysis(driver, symbol, url, wait_seconds=15):
    """
    Tool 2: IV Analysis
    Returns IV, IVP (IV Percentile), IV Rank, HV, IV vs HV status.

    IVP Classification:
      0-20:   Very Low  (cheap options, good for buying)
      20-40:  Low
      40-60:  Medium
      60-80:  High
      80-100: Very High (expensive options, good for selling)
    """
    result = {
        "IV": "", "IVP": "", "IV_Rank": "",
        "IVP_Status": "",  # Very Low / Low / Medium / High / Very High
        "HV": "", "IV_vs_HV": "",  # IV > HV = "Overpriced", IV < HV = "Underpriced"
        "IV_Signal": "",  # Buy/Sell/Neutral based on IVP
    }

    try:
        driver.get(url)
        time.sleep(3)
        _search_symbol_on_page(driver, symbol)
        time.sleep(2)

        # Try table first
        rows = _wait_and_get_table(driver, wait_seconds)
        for row in rows:
            row_text = " ".join(row).upper()
            if symbol.upper() in row_text:
                if len(row) >= 5:
                    result["IV"] = row[1] if len(row) > 1 else ""
                    result["IVP"] = row[2] if len(row) > 2 else ""
                    result["IV_Rank"] = row[3] if len(row) > 3 else ""
                    result["HV"] = row[4] if len(row) > 4 else ""
                break

        # Also try card/div layout for IV pages
        if not result["IV"]:
            page_data = _get_page_text_data(driver)
            for key, val in page_data.items():
                key_upper = key.upper()
                if "IVP" in key_upper or "IV PERCENTILE" in key_upper:
                    result["IVP"] = val
                elif "IV RANK" in key_upper:
                    result["IV_Rank"] = val
                elif "HV" in key_upper or "HISTORICAL" in key_upper:
                    result["HV"] = val
                elif "IV" in key_upper:
                    result["IV"] = val

        # Classify IVP
        try:
            ivp_val = float(result["IVP"].replace("%", "").strip())
            if ivp_val <= 20:
                result["IVP_Status"] = "Very Low"
                result["IV_Signal"] = "Options Cheap - Good for Buying"
            elif ivp_val <= 40:
                result["IVP_Status"] = "Low"
                result["IV_Signal"] = "Options Below Avg - Favorable Buy"
            elif ivp_val <= 60:
                result["IVP_Status"] = "Medium"
                result["IV_Signal"] = "Neutral"
            elif ivp_val <= 80:
                result["IVP_Status"] = "High"
                result["IV_Signal"] = "Options Expensive - Consider Selling"
            else:
                result["IVP_Status"] = "Very High"
                result["IV_Signal"] = "Options Very Expensive - Sell Strategies"
        except (ValueError, TypeError):
            result["IVP_Status"] = "N/A"
            result["IV_Signal"] = "N/A"

        # IV vs HV comparison
        try:
            iv_val = float(result["IV"].replace("%", "").strip())
            hv_val = float(result["HV"].replace("%", "").strip())
            if iv_val > hv_val * 1.1:
                result["IV_vs_HV"] = "Overpriced"
            elif iv_val < hv_val * 0.9:
                result["IV_vs_HV"] = "Underpriced"
            else:
                result["IV_vs_HV"] = "Fair"
        except (ValueError, TypeError):
            result["IV_vs_HV"] = "N/A"

    except Exception as e:
        logger.warning(f"IV Analysis scrape failed for {symbol}: {e}")

    return result


def scrape_oi_analysis(driver, symbol, url, wait_seconds=15):
    """
    Tool 3: OI Analysis
    Returns total CE/PE OI, OI changes, max OI strikes (support/resistance).
    """
    result = {
        "OI_Total_CE_OI": "", "OI_Total_PE_OI": "",
        "OI_CE_OI_Change": "", "OI_PE_OI_Change": "",
        "OI_Max_CE_Strike": "",  # Resistance
        "OI_Max_PE_Strike": "",  # Support
        "OI_PCR_from_OI": "",
        "OI_Trend": "",  # Bullish / Bearish / Neutral
    }

    try:
        driver.get(url)
        time.sleep(3)
        _search_symbol_on_page(driver, symbol)
        time.sleep(2)

        rows = _wait_and_get_table(driver, wait_seconds)
        page_data = _get_page_text_data(driver)

        # Parse table data (OI analysis often shows strike-wise data)
        max_ce_oi = 0
        max_pe_oi = 0
        total_ce_oi = 0
        total_pe_oi = 0

        for row in rows:
            if len(row) >= 5:
                try:
                    # Typical layout: CE OI | CE Chg | Strike | PE Chg | PE OI
                    ce_oi = float(row[0].replace(",", "")) if row[0].replace(",", "").replace(".", "").isdigit() else 0
                    pe_oi = float(row[-1].replace(",", "")) if row[-1].replace(",", "").replace(".", "").isdigit() else 0
                    strike = row[len(row) // 2]

                    total_ce_oi += ce_oi
                    total_pe_oi += pe_oi

                    if ce_oi > max_ce_oi:
                        max_ce_oi = ce_oi
                        result["OI_Max_CE_Strike"] = strike
                    if pe_oi > max_pe_oi:
                        max_pe_oi = pe_oi
                        result["OI_Max_PE_Strike"] = strike
                except (ValueError, IndexError):
                    continue

        if total_ce_oi > 0:
            result["OI_Total_CE_OI"] = str(int(total_ce_oi))
        if total_pe_oi > 0:
            result["OI_Total_PE_OI"] = str(int(total_pe_oi))

        # PCR from OI
        if total_ce_oi > 0:
            pcr = round(total_pe_oi / total_ce_oi, 3)
            result["OI_PCR_from_OI"] = str(pcr)
            if pcr > 1.2:
                result["OI_Trend"] = "Bullish (High Put Writing)"
            elif pcr < 0.8:
                result["OI_Trend"] = "Bearish (High Call Writing)"
            else:
                result["OI_Trend"] = "Neutral"

        # Also check page data for summary values
        for key, val in page_data.items():
            key_upper = key.upper()
            if "CE OI CHANGE" in key_upper:
                result["OI_CE_OI_Change"] = val
            elif "PE OI CHANGE" in key_upper:
                result["OI_PE_OI_Change"] = val

    except Exception as e:
        logger.warning(f"OI Analysis scrape failed for {symbol}: {e}")

    return result


def scrape_pcr_analysis(driver, symbol, url, wait_seconds=15):
    """
    Tool 4: PCR Analysis
    Returns PCR by OI, PCR by Volume, PCR trend and signal.
    """
    result = {
        "PCR_OI": "", "PCR_Volume": "",
        "PCR_Trend": "",   # Rising / Falling / Flat
        "PCR_Signal": "",  # Bullish / Bearish / Neutral
    }

    try:
        driver.get(url)
        time.sleep(3)
        _search_symbol_on_page(driver, symbol)
        time.sleep(2)

        page_data = _get_page_text_data(driver)
        rows = _wait_and_get_table(driver, wait_seconds)

        # Parse page data
        for key, val in page_data.items():
            key_upper = key.upper()
            if "PCR" in key_upper and "OI" in key_upper:
                result["PCR_OI"] = val
            elif "PCR" in key_upper and "VOL" in key_upper:
                result["PCR_Volume"] = val
            elif "PCR" in key_upper:
                result["PCR_OI"] = val

        # Check table for historical PCR values
        pcr_values = []
        for row in rows:
            for cell in row:
                try:
                    val = float(cell.replace(",", ""))
                    if 0 < val < 5:  # PCR is typically between 0 and 5
                        pcr_values.append(val)
                except (ValueError, TypeError):
                    continue

        # Determine trend from recent values
        if len(pcr_values) >= 3:
            recent = pcr_values[-3:]
            if recent[-1] > recent[0]:
                result["PCR_Trend"] = "Rising"
            elif recent[-1] < recent[0]:
                result["PCR_Trend"] = "Falling"
            else:
                result["PCR_Trend"] = "Flat"

        # Signal from PCR value
        try:
            pcr_val = float(result["PCR_OI"]) if result["PCR_OI"] else None
            if pcr_val:
                if pcr_val > 1.2:
                    result["PCR_Signal"] = "Bullish"
                elif pcr_val < 0.7:
                    result["PCR_Signal"] = "Bearish"
                else:
                    result["PCR_Signal"] = "Neutral"
        except (ValueError, TypeError):
            pass

    except Exception as e:
        logger.warning(f"PCR Analysis scrape failed for {symbol}: {e}")

    return result


def scrape_buildup(driver, symbol, url, wait_seconds=15):
    """
    Tool 5: Buildup Analysis
    Returns buildup type, price/OI changes, signal.
    """
    result = {
        "BU_Type": "",         # Long Buildup / Short Buildup / Long Unwinding / Short Covering
        "BU_Price_Change_Pct": "",
        "BU_OI_Change_Pct": "",
        "BU_Signal": "",       # Bullish / Bearish / Bullish Exit / Bearish Exit
    }

    try:
        driver.get(url)
        time.sleep(3)
        _search_symbol_on_page(driver, symbol)
        time.sleep(2)

        rows = _wait_and_get_table(driver, wait_seconds)

        for row in rows:
            row_text = " ".join(row).upper()
            if symbol.upper() in row_text:
                if len(row) >= 4:
                    result["BU_Price_Change_Pct"] = row[-3] if len(row) >= 3 else ""
                    result["BU_OI_Change_Pct"] = row[-2] if len(row) >= 2 else ""
                    result["BU_Type"] = row[-1] if len(row) >= 1 else ""

                # Classify signal
                bu_type = result["BU_Type"].upper()
                if "LONG BUILDUP" in bu_type or "LONG BUILD" in bu_type:
                    result["BU_Signal"] = "Bullish"
                elif "SHORT BUILDUP" in bu_type or "SHORT BUILD" in bu_type:
                    result["BU_Signal"] = "Bearish"
                elif "LONG UNWIND" in bu_type:
                    result["BU_Signal"] = "Bearish Exit"
                elif "SHORT COVER" in bu_type:
                    result["BU_Signal"] = "Bullish Exit"
                break

    except Exception as e:
        logger.warning(f"Buildup scrape failed for {symbol}: {e}")

    return result


def scrape_futures_oi(driver, symbol, url, wait_seconds=15):
    """
    Tool 6: Futures OI
    Returns futures OI, OI change, price, basis.
    """
    result = {
        "FUT_OI": "", "FUT_OI_Change": "", "FUT_OI_Change_Pct": "",
        "FUT_Price": "", "FUT_Basis": "",
        "FUT_Signal": "",  # OI up + Price up = Bullish, etc.
    }

    try:
        driver.get(url)
        time.sleep(3)
        _search_symbol_on_page(driver, symbol)
        time.sleep(2)

        rows = _wait_and_get_table(driver, wait_seconds)

        for row in rows:
            row_text = " ".join(row).upper()
            if symbol.upper() in row_text:
                if len(row) >= 6:
                    result["FUT_Price"] = row[1] if len(row) > 1 else ""
                    result["FUT_OI"] = row[2] if len(row) > 2 else ""
                    result["FUT_OI_Change"] = row[3] if len(row) > 3 else ""
                    result["FUT_OI_Change_Pct"] = row[4] if len(row) > 4 else ""
                    result["FUT_Basis"] = row[5] if len(row) > 5 else ""

                # Signal classification
                try:
                    oi_chg = float(result["FUT_OI_Change_Pct"].replace("%", "").replace(",", ""))
                    price = result["FUT_Price"]
                    # Price direction not directly available, use OI direction
                    if oi_chg > 0:
                        result["FUT_Signal"] = "OI Increasing - Active Interest"
                    elif oi_chg < 0:
                        result["FUT_Signal"] = "OI Decreasing - Unwinding"
                    else:
                        result["FUT_Signal"] = "Flat"
                except (ValueError, TypeError):
                    pass
                break

    except Exception as e:
        logger.warning(f"Futures OI scrape failed for {symbol}: {e}")

    return result


def scrape_max_pain(driver, symbol, url, wait_seconds=15):
    """
    Tool 7: Max Pain
    Returns max pain strike, current price, distance.
    """
    result = {
        "MP_Strike": "", "MP_Current_Price": "", "MP_Distance": "",
        "MP_Distance_Pct": "",
        "MP_Signal": "",  # Above Max Pain = Bearish Pressure, Below = Bullish Pressure
    }

    try:
        driver.get(url)
        time.sleep(3)
        _search_symbol_on_page(driver, symbol)
        time.sleep(2)

        page_data = _get_page_text_data(driver)

        for key, val in page_data.items():
            key_upper = key.upper()
            if "MAX PAIN" in key_upper:
                result["MP_Strike"] = val
            elif "LTP" in key_upper or "CURRENT" in key_upper or "CMP" in key_upper:
                result["MP_Current_Price"] = val

        # Calculate distance
        try:
            mp = float(result["MP_Strike"].replace(",", ""))
            cmp = float(result["MP_Current_Price"].replace(",", ""))
            distance = cmp - mp
            result["MP_Distance"] = str(round(distance, 2))
            result["MP_Distance_Pct"] = str(round((distance / mp) * 100, 2))

            if distance > 0:
                result["MP_Signal"] = f"Above Max Pain by {abs(distance):.0f} - Bearish Pressure"
            elif distance < 0:
                result["MP_Signal"] = f"Below Max Pain by {abs(distance):.0f} - Bullish Pressure"
            else:
                result["MP_Signal"] = "At Max Pain - Neutral"
        except (ValueError, TypeError):
            result["MP_Signal"] = "N/A"

    except Exception as e:
        logger.warning(f"Max Pain scrape failed for {symbol}: {e}")

    return result


# ============================================================
# Master function: Collect ALL tool data for a single stock
# ============================================================

def collect_all_tool_data(driver, symbol, tool_urls, wait_seconds=15):
    """
    Navigate to each Quantsapp tool page and collect all data for a symbol.
    Returns a single flat dict with all columns prefixed by tool abbreviation.

    Column mapping:
      OT_  = Option Triggers
      IV_  = IV/IVP Analysis
      OI_  = OI Analysis
      PCR_ = PCR Analysis
      BU_  = Buildup
      FUT_ = Futures OI
      MP_  = Max Pain
    """
    # Strip expiry date from symbol – use only the stock name for Quantsapp search
    clean_sym = _clean_symbol(symbol)
    if clean_sym != symbol:
        logger.info(f"Cleaned symbol: '{symbol}' -> '{clean_sym}'")
    symbol = clean_sym

    logger.info(f"Collecting all tool data for {symbol}...")
    all_data = {"Symbol": symbol, "Analysis_Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    # 1. Option Triggers
    if "option_triggers" in tool_urls:
        logger.info(f"  -> Scraping Option Triggers for {symbol}")
        ot_data = scrape_option_triggers(driver, symbol, tool_urls["option_triggers"], wait_seconds)
        all_data.update(ot_data)

    # 2. IV Analysis
    if "iv_analysis" in tool_urls:
        logger.info(f"  -> Scraping IV Analysis for {symbol}")
        iv_data = scrape_iv_analysis(driver, symbol, tool_urls["iv_analysis"], wait_seconds)
        all_data.update(iv_data)

    # 3. OI Analysis
    if "oi_analysis" in tool_urls:
        logger.info(f"  -> Scraping OI Analysis for {symbol}")
        oi_data = scrape_oi_analysis(driver, symbol, tool_urls["oi_analysis"], wait_seconds)
        all_data.update(oi_data)

    # 4. PCR Analysis
    if "pcr_analysis" in tool_urls:
        logger.info(f"  -> Scraping PCR Analysis for {symbol}")
        pcr_data = scrape_pcr_analysis(driver, symbol, tool_urls["pcr_analysis"], wait_seconds)
        all_data.update(pcr_data)

    # 5. Buildup
    if "buildup" in tool_urls:
        logger.info(f"  -> Scraping Buildup for {symbol}")
        bu_data = scrape_buildup(driver, symbol, tool_urls["buildup"], wait_seconds)
        all_data.update(bu_data)

    # 6. Futures OI
    if "futures_oi" in tool_urls:
        logger.info(f"  -> Scraping Futures OI for {symbol}")
        fut_data = scrape_futures_oi(driver, symbol, tool_urls["futures_oi"], wait_seconds)
        all_data.update(fut_data)

    # 7. Max Pain
    if "max_pain" in tool_urls:
        logger.info(f"  -> Scraping Max Pain for {symbol}")
        mp_data = scrape_max_pain(driver, symbol, tool_urls["max_pain"], wait_seconds)
        all_data.update(mp_data)

    # Generate overall verdict
    all_data["Overall_Verdict"] = _generate_verdict(all_data)

    logger.info(f"Completed all tool data for {symbol}")
    return all_data


def _generate_verdict(data):
    """
    Generate an overall bullish/bearish verdict from all tool signals.
    Counts bullish vs bearish indicators across all tools.
    """
    bullish_count = 0
    bearish_count = 0
    total_signals = 0

    signal_keys = ["IV_Signal", "OI_Trend", "PCR_Signal", "BU_Signal", "FUT_Signal", "MP_Signal"]

    for key in signal_keys:
        val = data.get(key, "").upper()
        if not val or val == "N/A":
            continue
        total_signals += 1
        if "BULLISH" in val or "BUY" in val or "CHEAP" in val or "FAVORABLE" in val:
            bullish_count += 1
        elif "BEARISH" in val or "SELL" in val or "EXPENSIVE" in val:
            bearish_count += 1

    if total_signals == 0:
        return "Insufficient Data"

    bull_pct = (bullish_count / total_signals) * 100
    bear_pct = (bearish_count / total_signals) * 100

    if bull_pct >= 60:
        return f"BULLISH ({bullish_count}/{total_signals} signals bullish)"
    elif bear_pct >= 60:
        return f"BEARISH ({bearish_count}/{total_signals} signals bearish)"
    else:
        return f"MIXED ({bullish_count}B/{bearish_count}Be/{total_signals - bullish_count - bearish_count}N)"
