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
# Column G-N: New detailed module scrapers
# ============================================================

def _click_tab(driver, tab_text, wait_seconds=5):
    """Click a tab/button on the current page matching the given text."""
    tab_selectors = [
        f"button", f"a", f"[role='tab']", f".nav-link", f".tab",
        f"[class*='tab']", f"li", f"span",
    ]
    for selector in tab_selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for elem in elements:
                if tab_text.upper() in elem.text.upper():
                    elem.click()
                    time.sleep(wait_seconds)
                    return True
        except (StaleElementReferenceException, Exception):
            continue
    return False


def scrape_writers_trap(driver, symbol, url, wait_seconds=15):
    """
    Column G – Open Trap / Writers Trap Indicator.
    Checks last 3 days: Call Writers Trap = Bullish, Put Writers Trap = Bearish.
    Also checks Return% to note if move already done (>+/-3%).

    Output example: "Bullish" or "Bearish >2% move already done"
    """
    result = {
        "TRAP_Indicator": "",     # Column G: Bullish / Bearish
        "TRAP_Type": "",          # Call Writers Trap / Put Writers Trap
        "TRAP_Return_Pct": "",    # Return % since trap
        "TRAP_Note": "",          # Column O: Note about move already done
    }

    try:
        driver.get(url)
        time.sleep(3)
        _search_symbol_on_page(driver, symbol)
        time.sleep(2)

        rows = _wait_and_get_table(driver, wait_seconds)
        page_data = _get_page_text_data(driver)

        # Search in table rows for the symbol
        for row in rows:
            row_text = " ".join(row).upper()
            if symbol.upper() in row_text:
                # Detect trap type from row text
                if "CALL" in row_text and ("TRAP" in row_text or "WRITER" in row_text):
                    result["TRAP_Type"] = "Call Writers Trap"
                    result["TRAP_Indicator"] = "Bullish"
                elif "PUT" in row_text and ("TRAP" in row_text or "WRITER" in row_text):
                    result["TRAP_Type"] = "Put Writers Trap"
                    result["TRAP_Indicator"] = "Bearish"

                # Extract return % from row
                for cell in row:
                    cell_clean = cell.replace("%", "").replace(",", "").strip()
                    try:
                        val = float(cell_clean)
                        if -50 < val < 50 and val != 0:
                            result["TRAP_Return_Pct"] = str(val)
                            break
                    except ValueError:
                        continue
                break

        # Also check page text for trap signals
        if not result["TRAP_Indicator"]:
            for key, val in page_data.items():
                key_upper = key.upper()
                val_upper = val.upper()
                combined = f"{key_upper} {val_upper}"
                if "CALL" in combined and "TRAP" in combined:
                    result["TRAP_Type"] = "Call Writers Trap"
                    result["TRAP_Indicator"] = "Bullish"
                    break
                elif "PUT" in combined and "TRAP" in combined:
                    result["TRAP_Type"] = "Put Writers Trap"
                    result["TRAP_Indicator"] = "Bearish"
                    break

        # Generate note if return already >+/-3%
        try:
            ret = float(result["TRAP_Return_Pct"])
            direction = result["TRAP_Indicator"]
            if direction == "Bullish" and ret > 3:
                result["TRAP_Note"] = f"Bullish >{ret:.0f}% move already done"
            elif direction == "Bullish" and ret > 2:
                result["TRAP_Note"] = f"Bullish >{ret:.0f}% move already done"
            elif direction == "Bearish" and ret < -3:
                result["TRAP_Note"] = f"Bearish >{abs(ret):.0f}% move already done"
            elif direction == "Bearish" and ret < -2:
                result["TRAP_Note"] = f"Bearish >{abs(ret):.0f}% move already done"
        except (ValueError, TypeError):
            pass

    except Exception as e:
        logger.warning(f"Writers Trap scrape failed for {symbol}: {e}")

    return result


def scrape_iv_detailed(driver, symbol, url, wait_seconds=15):
    """
    Column H – IVR/IVP with 3-month Hi/Lo range.
    Navigates to IV Analysis and extracts current IVP plus
    the 3-month IV high and low for context.

    Output format: "Med IV = CMP IV = 32.07>> Hi-47.85--Lo-16.19"
    """
    result = {
        "IV_Summary": "",         # Column H: Formatted IV summary
        "IV_Current": "",         # Current IV value
        "IV_3M_High": "",         # 3-month IV high
        "IV_3M_Low": "",          # 3-month IV low
        "IV_Level": "",           # High / Med / Low
    }

    try:
        driver.get(url)
        time.sleep(3)
        _search_symbol_on_page(driver, symbol)
        time.sleep(2)

        page_data = _get_page_text_data(driver)
        rows = _wait_and_get_table(driver, wait_seconds)

        iv_current = ""
        ivp_current = ""
        iv_high = ""
        iv_low = ""

        # Extract IV data from page text
        for key, val in page_data.items():
            key_upper = key.upper()
            if "IVP" in key_upper or "IV PERCENTILE" in key_upper:
                ivp_current = val.replace("%", "").strip()
            elif "HIGH" in key_upper and "IV" in key_upper:
                iv_high = val.replace("%", "").strip()
            elif "LOW" in key_upper and "IV" in key_upper:
                iv_low = val.replace("%", "").strip()
            elif "IV" in key_upper and "RANK" not in key_upper:
                iv_current = val.replace("%", "").strip()

        # Try to extract from table rows
        for row in rows:
            row_text = " ".join(row).upper()
            if symbol.upper() in row_text:
                # Look for IV values in the row
                iv_candidates = []
                for cell in row:
                    cell_clean = cell.replace("%", "").replace(",", "").strip()
                    try:
                        val = float(cell_clean)
                        if 0 < val < 200:
                            iv_candidates.append(val)
                    except ValueError:
                        continue
                if len(iv_candidates) >= 3:
                    if not iv_current:
                        iv_current = str(iv_candidates[0])
                    if not iv_high:
                        iv_high = str(max(iv_candidates))
                    if not iv_low:
                        iv_low = str(min(iv_candidates))
                elif len(iv_candidates) >= 1 and not iv_current:
                    iv_current = str(iv_candidates[0])
                break

        result["IV_Current"] = iv_current
        result["IV_3M_High"] = iv_high
        result["IV_3M_Low"] = iv_low

        # Determine IV level
        try:
            curr = float(iv_current) if iv_current else 0
            hi = float(iv_high) if iv_high else curr * 1.5
            lo = float(iv_low) if iv_low else curr * 0.5
            mid = (hi + lo) / 2

            if curr >= hi * 0.8:
                result["IV_Level"] = "High"
            elif curr <= lo * 1.2:
                result["IV_Level"] = "Low"
            else:
                result["IV_Level"] = "Med"

            # Build formatted summary
            result["IV_Summary"] = (
                f"{result['IV_Level']} IV = CMP IV = {iv_current}>> "
                f"Hi-{iv_high}--Lo-{iv_low}"
            )
        except (ValueError, TypeError):
            if iv_current:
                result["IV_Summary"] = f"CMP IV = {iv_current}"

    except Exception as e:
        logger.warning(f"IV Detailed scrape failed for {symbol}: {e}")

    return result


def scrape_oi_by_expiry(driver, symbol, url, wait_seconds=15):
    """
    Column I – Open Interest by Expiry with R1/R2 strike ranks.
    Scrapes OI analysis and identifies top 2 CE and PE strikes per expiry.

    Output format:
      JANCE-R1-200/R2-180
      JANPE-R1-165/R2-180
      FEBCE-R1-190/R2-180
      FEBPE-R1-190/R2-170
    """
    result = {
        "OI_Strikes_Summary": "",    # Column I: Full formatted summary
        "OI_Near_CE_R1": "",         # Near month CE Rank 1 strike
        "OI_Near_CE_R2": "",         # Near month CE Rank 2 strike
        "OI_Near_PE_R1": "",         # Near month PE Rank 1 strike
        "OI_Near_PE_R2": "",         # Near month PE Rank 2 strike
        "OI_Next_CE_R1": "",         # Next month CE Rank 1 strike
        "OI_Next_CE_R2": "",         # Next month CE Rank 2 strike
        "OI_Next_PE_R1": "",         # Next month PE Rank 1 strike
        "OI_Next_PE_R2": "",         # Next month PE Rank 2 strike
    }

    try:
        driver.get(url)
        time.sleep(3)
        _search_symbol_on_page(driver, symbol)
        time.sleep(2)

        rows = _wait_and_get_table(driver, wait_seconds)

        # Collect CE and PE OI data with strikes
        ce_strikes = []  # list of (oi_value, strike)
        pe_strikes = []

        for row in rows:
            if len(row) >= 5:
                try:
                    # Layout: CE OI | CE Chg | Strike | PE Chg | PE OI
                    strike = row[len(row) // 2].replace(",", "").strip()
                    ce_oi_str = row[0].replace(",", "").strip()
                    pe_oi_str = row[-1].replace(",", "").strip()

                    ce_oi = float(ce_oi_str) if ce_oi_str.replace(".", "").isdigit() else 0
                    pe_oi = float(pe_oi_str) if pe_oi_str.replace(".", "").isdigit() else 0

                    if ce_oi > 0:
                        ce_strikes.append((ce_oi, strike))
                    if pe_oi > 0:
                        pe_strikes.append((pe_oi, strike))
                except (ValueError, IndexError):
                    continue

        # Sort by OI descending and get top 2
        ce_strikes.sort(key=lambda x: x[0], reverse=True)
        pe_strikes.sort(key=lambda x: x[0], reverse=True)

        # Get current month abbreviation for expiry labels
        now = datetime.now()
        near_month = now.strftime("%b").upper()[:3]
        # Next month
        next_month_num = now.month + 1 if now.month < 12 else 1
        next_month_dt = now.replace(month=next_month_num) if now.month < 12 else now.replace(year=now.year + 1, month=1)
        next_month = next_month_dt.strftime("%b").upper()[:3]

        # Assign R1 and R2
        if len(ce_strikes) >= 1:
            result["OI_Near_CE_R1"] = ce_strikes[0][1]
        if len(ce_strikes) >= 2:
            result["OI_Near_CE_R2"] = ce_strikes[1][1]
        if len(pe_strikes) >= 1:
            result["OI_Near_PE_R1"] = pe_strikes[0][1]
        if len(pe_strikes) >= 2:
            result["OI_Near_PE_R2"] = pe_strikes[1][1]

        # Build formatted summary
        lines = []
        if result["OI_Near_CE_R1"]:
            lines.append(f"{near_month}CE-R1-{result['OI_Near_CE_R1']}/R2-{result.get('OI_Near_CE_R2', 'N/A')}")
        if result["OI_Near_PE_R1"]:
            lines.append(f"{near_month}PE-R1-{result['OI_Near_PE_R1']}/R2-{result.get('OI_Near_PE_R2', 'N/A')}")

        # Try to get next expiry data by clicking next expiry tab
        if _click_tab(driver, next_month, wait_seconds=3) or _click_tab(driver, "NEXT", wait_seconds=3):
            time.sleep(2)
            rows2 = _wait_and_get_table(driver, wait_seconds=10)
            ce2 = []
            pe2 = []
            for row in rows2:
                if len(row) >= 5:
                    try:
                        strike = row[len(row) // 2].replace(",", "").strip()
                        ce_oi = float(row[0].replace(",", "")) if row[0].replace(",", "").replace(".", "").isdigit() else 0
                        pe_oi = float(row[-1].replace(",", "")) if row[-1].replace(",", "").replace(".", "").isdigit() else 0
                        if ce_oi > 0:
                            ce2.append((ce_oi, strike))
                        if pe_oi > 0:
                            pe2.append((pe_oi, strike))
                    except (ValueError, IndexError):
                        continue

            ce2.sort(key=lambda x: x[0], reverse=True)
            pe2.sort(key=lambda x: x[0], reverse=True)

            if len(ce2) >= 1:
                result["OI_Next_CE_R1"] = ce2[0][1]
            if len(ce2) >= 2:
                result["OI_Next_CE_R2"] = ce2[1][1]
            if len(pe2) >= 1:
                result["OI_Next_PE_R1"] = pe2[0][1]
            if len(pe2) >= 2:
                result["OI_Next_PE_R2"] = pe2[1][1]

            if result["OI_Next_CE_R1"]:
                lines.append(f"{next_month}CE-R1-{result['OI_Next_CE_R1']}/R2-{result.get('OI_Next_CE_R2', 'N/A')}")
            if result["OI_Next_PE_R1"]:
                lines.append(f"{next_month}PE-R1-{result['OI_Next_PE_R1']}/R2-{result.get('OI_Next_PE_R2', 'N/A')}")

        result["OI_Strikes_Summary"] = "\n".join(lines) if lines else "N/A"

    except Exception as e:
        logger.warning(f"OI by Expiry scrape failed for {symbol}: {e}")

    return result


def _scrape_buildup_tab(driver, symbol, url, tab_name, wait_seconds=15):
    """
    Helper: Navigate to Buildup page and click a specific tab,
    then extract the buildup data for the symbol.
    Returns a list of buildup types found (e.g. ['Long Buildup', 'Short Covering']).
    """
    entries = []
    try:
        driver.get(url)
        time.sleep(3)

        # Click the specific tab
        _click_tab(driver, tab_name, wait_seconds=3)
        _search_symbol_on_page(driver, symbol)
        time.sleep(2)

        rows = _wait_and_get_table(driver, wait_seconds)
        page_data = _get_page_text_data(driver)

        for row in rows:
            row_text = " ".join(row).upper()
            if symbol.upper() in row_text:
                # Extract buildup type from the last column typically
                for cell in reversed(row):
                    cell_upper = cell.upper()
                    if any(bt in cell_upper for bt in ["LONG BUILDUP", "SHORT BUILDUP", "LONG UNWIND", "SHORT COVER"]):
                        entries.append(cell.strip())
                        break
                if not entries:
                    entries.append(row[-1].strip() if row else "")
                break

        # Also check page text
        if not entries:
            for key, val in page_data.items():
                combined = f"{key} {val}".upper()
                if symbol.upper() in combined:
                    for bt in ["Long Buildup", "Short Buildup", "Long Unwinding", "Short Covering"]:
                        if bt.upper() in combined:
                            entries.append(bt)

    except Exception as e:
        logger.warning(f"Buildup tab '{tab_name}' scrape failed for {symbol}: {e}")

    return entries


def _classify_buildup_short(buildup_types):
    """Convert buildup types list to short format: L=Long, LU=Long Unwinding, SC=Short Covering, SB=Short Buildup"""
    short_map = {
        "LONG BUILDUP": "L",
        "LONG BUILD": "L",
        "SHORT BUILDUP": "SB",
        "SHORT BUILD": "SB",
        "LONG UNWINDING": "LU",
        "LONG UNWIND": "LU",
        "SHORT COVERING": "SC",
        "SHORT COVER": "SC",
    }
    result = []
    for bt in buildup_types:
        bt_upper = bt.upper()
        matched = False
        for key, short in short_map.items():
            if key in bt_upper:
                result.append(short)
                matched = True
                break
        if not matched and bt.strip():
            result.append(bt.strip()[:3])
    return "-".join(result) if result else "N/A"


def scrape_buildup_fut_oi_h(driver, symbol, url, wait_seconds=15):
    """
    Column J – Buildup: Scrip FUTure OI-H (history).
    Reads OI history and outputs format like: L-LU-SC
    (Long Buildup, Long Unwinding, Short Covering pattern)
    """
    result = {
        "BU_FUT_OIH": "",         # Column J: Short format like L-LU-SC
        "BU_FUT_OIH_Detail": "",  # Full detail
    }

    try:
        entries = _scrape_buildup_tab(driver, symbol, url, "FUT OI", wait_seconds)

        if not entries:
            # Try alternate tab names
            entries = _scrape_buildup_tab(driver, symbol, url, "OI-H", wait_seconds)

        if not entries:
            entries = _scrape_buildup_tab(driver, symbol, url, "Future", wait_seconds)

        result["BU_FUT_OIH"] = _classify_buildup_short(entries)
        result["BU_FUT_OIH_Detail"] = " | ".join(entries) if entries else "N/A"

    except Exception as e:
        logger.warning(f"Buildup FUT OI-H scrape failed for {symbol}: {e}")

    return result


def scrape_buildup_scrip_cycle(driver, symbol, url, wait_seconds=15):
    """
    Column K – Buildup: Scrip Cycle.
    Shows the buildup cycle pattern for the stock.
    Format similar to OI strikes: current cycle position.
    """
    result = {
        "BU_Scrip_Cycle": "",       # Column K: Cycle pattern
        "BU_Scrip_Cycle_Detail": "",
    }

    try:
        entries = _scrape_buildup_tab(driver, symbol, url, "Scrip Cycle", wait_seconds)

        if not entries:
            entries = _scrape_buildup_tab(driver, symbol, url, "Cycle", wait_seconds)

        result["BU_Scrip_Cycle"] = _classify_buildup_short(entries)
        result["BU_Scrip_Cycle_Detail"] = " | ".join(entries) if entries else "N/A"

    except Exception as e:
        logger.warning(f"Buildup Scrip Cycle scrape failed for {symbol}: {e}")

    return result


def scrape_buildup_sector(driver, symbol, url, wait_seconds=15):
    """
    Columns L, M, N – Buildup: Sector, Sector Cycle, Sector OI-H.
    Gets sector-level buildup data in 3 separate columns.
    """
    result = {
        "BU_Sector": "",             # Column L: Sector buildup
        "BU_Sector_Cycle": "",       # Column M: Sector cycle
        "BU_Sector_OIH": "",         # Column N: Sector OI history
        "BU_Sector_Detail": "",
        "BU_Sector_Cycle_Detail": "",
        "BU_Sector_OIH_Detail": "",
    }

    try:
        # Column L: Sector tab
        entries_sector = _scrape_buildup_tab(driver, symbol, url, "Sector", wait_seconds)
        result["BU_Sector"] = _classify_buildup_short(entries_sector)
        result["BU_Sector_Detail"] = " | ".join(entries_sector) if entries_sector else "N/A"

        # Column M: Sector Cycle tab
        entries_cycle = _scrape_buildup_tab(driver, symbol, url, "Sector Cycle", wait_seconds)
        result["BU_Sector_Cycle"] = _classify_buildup_short(entries_cycle)
        result["BU_Sector_Cycle_Detail"] = " | ".join(entries_cycle) if entries_cycle else "N/A"

        # Column N: Sector OI-H tab
        entries_oih = _scrape_buildup_tab(driver, symbol, url, "Sector OI", wait_seconds)
        if not entries_oih:
            entries_oih = _scrape_buildup_tab(driver, symbol, url, "OI-H", wait_seconds)
        result["BU_Sector_OIH"] = _classify_buildup_short(entries_oih)
        result["BU_Sector_OIH_Detail"] = " | ".join(entries_oih) if entries_oih else "N/A"

    except Exception as e:
        logger.warning(f"Buildup Sector scrape failed for {symbol}: {e}")

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

    # ── Column G: Writers Trap Indicator ──
    if "writers_trap" in tool_urls:
        logger.info(f"  -> Scraping Writers Trap for {symbol} (Col G)")
        trap_data = scrape_writers_trap(driver, symbol, tool_urls["writers_trap"], wait_seconds)
        all_data.update(trap_data)

    # ── Column H: IV Detailed with 3-month Hi/Lo ──
    if "iv_analysis" in tool_urls:
        logger.info(f"  -> Scraping IV Detailed for {symbol} (Col H)")
        iv_detail = scrape_iv_detailed(driver, symbol, tool_urls["iv_analysis"], wait_seconds)
        all_data.update(iv_detail)

    # ── Column I: OI Strikes by Expiry (R1/R2 ranks) ──
    if "oi_analysis" in tool_urls:
        logger.info(f"  -> Scraping OI Strikes by Expiry for {symbol} (Col I)")
        oi_strikes = scrape_oi_by_expiry(driver, symbol, tool_urls["oi_analysis"], wait_seconds)
        all_data.update(oi_strikes)

    # ── Column J: Buildup Scrip FUT OI-H ──
    if "buildup" in tool_urls:
        logger.info(f"  -> Scraping Buildup FUT OI-H for {symbol} (Col J)")
        bu_fut = scrape_buildup_fut_oi_h(driver, symbol, tool_urls["buildup"], wait_seconds)
        all_data.update(bu_fut)

    # ── Column K: Buildup Scrip Cycle ──
    if "buildup" in tool_urls:
        logger.info(f"  -> Scraping Buildup Scrip Cycle for {symbol} (Col K)")
        bu_cycle = scrape_buildup_scrip_cycle(driver, symbol, tool_urls["buildup"], wait_seconds)
        all_data.update(bu_cycle)

    # ── Columns L, M, N: Buildup Sector, Sector Cycle, Sector OI-H ──
    if "buildup" in tool_urls:
        logger.info(f"  -> Scraping Buildup Sector data for {symbol} (Cols L-N)")
        bu_sector = scrape_buildup_sector(driver, symbol, tool_urls["buildup"], wait_seconds)
        all_data.update(bu_sector)

    # Generate overall verdict (include new signals)
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

    signal_keys = ["TRAP_Indicator", "IV_Signal", "OI_Trend", "PCR_Signal", "BU_Signal", "FUT_Signal", "MP_Signal"]

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
