# helpers/stock_picker.py – 4-Rule Stock Pick Engine
#
# Rule 1: Highest CE OI changes from Option Triggers
# Rule 2: Call-Put diff should be between -1% to +1%
# Rule 3: Stock must be in the WBRam watchlist (local Excel or Google Sheet)
# Rule 4: Column O (LTP) in watchlist must be TRUE, then check price columns
#
# After filtering: Collect full analysis from ALL Quantsapp tools
# and generate the announcement.

import os
import re
import logging
import numpy as np
import pandas as pd
from datetime import datetime

from helpers.quantsapp_tools import collect_all_tool_data, _clean_symbol
from helpers.notify import send_telegram

logger = logging.getLogger(__name__)

# Try Google Sheet import; fall back gracefully
try:
    from helpers.google_sheet import load_watchlist, get_allowed_symbols, check_ltp_status, get_price_columns
    GSHEET_AVAILABLE = True
except ImportError:
    GSHEET_AVAILABLE = False


def apply_rule_1(df, min_ce_oi_change_pct=5.0):
    """
    Rule 1: Filter for highest CE OI changes.
    Keep rows where CE OI Change % >= threshold.
    Sort by CE OI Change % descending.
    """
    if df.empty:
        return df

    logger.info(f"Rule 1: Available columns: {list(df.columns)}")

    # Try to find CE OI change column with multiple matching strategies
    ce_change_col = None

    # Strategy 1: Exact pattern match
    for col in df.columns:
        col_upper = col.upper()
        if "CE" in col_upper and "OI" in col_upper and ("CHANGE" in col_upper or "CHG" in col_upper) and "%" in col_upper:
            ce_change_col = col
            break
        elif "CE" in col_upper and "OI" in col_upper and ("CHANGE" in col_upper or "CHG" in col_upper):
            ce_change_col = col

    # Strategy 2: Known column names (exact or partial match)
    if ce_change_col is None:
        known_names = ["Change %", "OT_CE_OI_Change_Pct", "CE OI Change %",
                       "CE OI Chg %", "CE Chg %", "CE Change %", "CE_OI_Change",
                       "OI Change %"]
        for col in df.columns:
            if col in known_names:
                ce_change_col = col
                break

    # Strategy 3: Quantsapp actual headers - detect garbled names like "Olchg(%)", "OIchg(%)"
    if ce_change_col is None:
        for col in df.columns:
            col_clean = col.upper().replace(" ", "")
            if "OICHG" in col_clean or "OLCHG" in col_clean or "OI_CHG" in col_clean:
                ce_change_col = col
                break

    # Strategy 4: Any column with "change"/"chg" and "%" in the name
    if ce_change_col is None:
        for col in df.columns:
            col_upper = col.upper()
            if ("CHANGE" in col_upper or "CHG" in col_upper) and "%" in col_upper:
                ce_change_col = col
                break

    # Strategy 5: Any column with "oi" in the name
    if ce_change_col is None:
        for col in df.columns:
            col_upper = col.upper()
            if "OI" in col_upper:
                ce_change_col = col
                break

    # Strategy 6: Column index 3 (OI Change % in typical Quantsapp layout)
    if ce_change_col is None and len(df.columns) >= 4:
        candidate = df.columns[3]
        logger.info(f"Rule 1: Trying column index 3 as OI Change: '{candidate}'")
        ce_change_col = candidate

    if ce_change_col is None:
        logger.warning("Rule 1: Could not find CE OI Change column. Skipping filter.")
        return df

    logger.info(f"Rule 1: Using column '{ce_change_col}' for CE OI Change %")

    df = df.copy()
    # Handle duplicate column names: use iloc to get the first matching column as a Series
    col_loc = df.columns.get_loc(ce_change_col)
    if isinstance(col_loc, slice) or (hasattr(col_loc, '__iter__') and not isinstance(col_loc, str)):
        # Duplicate column name — take the first occurrence
        if isinstance(col_loc, slice):
            first_idx = col_loc.start
        else:
            first_idx = np.where(col_loc)[0][0] if hasattr(col_loc, '__iter__') else col_loc
        ce_series = df.iloc[:, first_idx]
        logger.info(f"Rule 1: Duplicate column '{ce_change_col}' found, using column index {first_idx}")
    else:
        ce_series = df[ce_change_col]

    df["_ce_oi_change_num"] = pd.to_numeric(
        ce_series.astype(str).str.replace("%", "").str.replace(",", ""),
        errors="coerce"
    ).fillna(0)

    # Filter for minimum threshold
    filtered = df[df["_ce_oi_change_num"] >= min_ce_oi_change_pct].copy()

    # Sort by highest CE OI change
    filtered = filtered.sort_values("_ce_oi_change_num", ascending=False)

    logger.info(f"Rule 1: {len(filtered)} stocks with CE OI Change >= {min_ce_oi_change_pct}%")
    return filtered


def apply_rule_2(df, diff_min=-1.0, diff_max=1.0):
    """
    Rule 2: Call-Put diff should be between -1% to +1%.
    This means CE and PE OI changes are roughly balanced.
    """
    if df.empty:
        return df

    # Look for Call-Put diff column or compute it
    diff_col = None
    for col in df.columns:
        if "call_put_diff" in col.lower() or "diff" in col.lower():
            diff_col = col
            break

    if diff_col is None:
        # Try to compute from CE and PE change columns
        ce_col = pe_col = None
        for col in df.columns:
            col_upper = col.upper()
            if "CE" in col_upper and ("CHG" in col_upper or "CHANGE" in col_upper) and "%" in col_upper:
                ce_col = col
            elif "PE" in col_upper and ("CHG" in col_upper or "CHANGE" in col_upper) and "%" in col_upper:
                pe_col = col

        if ce_col and pe_col:
            df = df.copy()
            ce_vals = pd.to_numeric(
                df[ce_col].astype(str).str.replace("%", "").str.replace(",", ""),
                errors="coerce"
            ).fillna(0)
            pe_vals = pd.to_numeric(
                df[pe_col].astype(str).str.replace("%", "").str.replace(",", ""),
                errors="coerce"
            ).fillna(0)
            df["_call_put_diff"] = ce_vals - pe_vals
            diff_col = "_call_put_diff"
        elif "OT_Call_Put_Diff_Pct" in df.columns:
            diff_col = "OT_Call_Put_Diff_Pct"
            df = df.copy()
            df["_call_put_diff"] = pd.to_numeric(
                df[diff_col].astype(str).str.replace("%", "").str.replace(",", ""),
                errors="coerce"
            ).fillna(0)
            diff_col = "_call_put_diff"

    if diff_col is None:
        logger.warning("Rule 2: Could not find or compute Call-Put diff. Passing all stocks (diff computed later from tool data).")
        return df

    df = df.copy()
    if diff_col != "_call_put_diff":
        df["_call_put_diff"] = pd.to_numeric(
            df[diff_col].astype(str).str.replace("%", "").str.replace(",", ""),
            errors="coerce"
        ).fillna(0)

    filtered = df[(df["_call_put_diff"] >= diff_min) & (df["_call_put_diff"] <= diff_max)].copy()

    logger.info(f"Rule 2: {len(filtered)} stocks with Call-Put diff between {diff_min}% and {diff_max}%")
    return filtered


def apply_rule_3(df, allowed_symbols):
    """
    Rule 3: Stock must be in the WBRam watchlist (local Excel or Google Sheet).
    """
    if df.empty or not allowed_symbols:
        if not allowed_symbols:
            logger.warning("Rule 3: No symbols loaded from watchlist. Skipping filter.")
        return df

    # Find the symbol column
    symbol_col = None
    for col in df.columns:
        if col.upper() in ["SYMBOL", "STOCK", "NAME", "SCRIP"]:
            symbol_col = col
            break

    if symbol_col is None:
        symbol_col = df.columns[0]  # Fallback to first column

    df = df.copy()
    allowed_upper = [s.upper() for s in allowed_symbols]
    # Clean symbols (strip expiry dates) before matching against watchlist
    df["_clean_symbol"] = df[symbol_col].astype(str).str.strip().apply(_clean_symbol)
    filtered = df[df["_clean_symbol"].isin(allowed_upper)].copy()

    logger.info(f"Rule 3: {len(filtered)} stocks match watchlist (from {len(allowed_symbols)} allowed)")
    return filtered


def _load_local_watchlist(cfg):
    """
    Load watchlist from local Excel file.
    Tries primary path first, then fallback path.
    Resolves relative paths from the project directory (where config.json lives).
    """
    wl_cfg = cfg.get("watchlist", cfg.get("google_sheet", {}))
    primary_file = wl_cfg.get("local_file", "watchlist/WBRam_Watchlist.xlsx")
    fallback_file = wl_cfg.get("local_file_fallback", "watchlist/WBRam_Watchlist.xlsx")

    # Resolve relative paths from the script's directory (project root)
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Try primary path first, then fallback
    for filepath in [primary_file, fallback_file]:
        if not filepath:
            continue
        # Try path as-is first (absolute or relative to CWD)
        candidates = [filepath]
        # Also try resolving relative to the project directory
        if not os.path.isabs(filepath):
            candidates.append(os.path.join(script_dir, filepath))
        for candidate in candidates:
            if os.path.exists(candidate):
                try:
                    df = pd.read_excel(candidate)
                    logger.info(f"Loaded {len(df)} rows from watchlist: {candidate}")
                    return df
                except Exception as e:
                    logger.warning(f"Failed to read {candidate}: {e}")

    logger.warning(f"No watchlist found at: {primary_file} or {fallback_file}")
    return pd.DataFrame()


def _get_allowed_symbols_local(watchlist_df):
    """Extract stock symbols from the first column of the local watchlist."""
    if watchlist_df.empty:
        return []
    first_col = watchlist_df.columns[0]
    symbols = watchlist_df[first_col].dropna().astype(str).str.strip().str.upper().tolist()
    return [s for s in symbols if s and s != ""]


def _check_ltp_local(watchlist_df, symbol, ltp_column="O"):
    """Check Column O (LTP) is TRUE for a symbol in the local watchlist."""
    if watchlist_df.empty:
        return False, {}

    first_col = watchlist_df.columns[0]
    mask = watchlist_df[first_col].astype(str).str.strip().str.upper() == symbol.upper()
    matching = watchlist_df[mask]

    if matching.empty:
        return False, {}

    row = matching.iloc[0]
    col_index = ord(ltp_column.upper()) - ord('A')  # O=14
    ltp_value = None

    if col_index < len(watchlist_df.columns):
        col_name = watchlist_df.columns[col_index]
        ltp_value = row[col_name]

    is_true = False
    if ltp_value is not None:
        val_str = str(ltp_value).strip().upper()
        is_true = val_str in ["TRUE", "YES", "1", "T"]

    return is_true, row.to_dict()


def _get_price_cols_local(watchlist_df, symbol, price_columns=None):
    """Read price columns (P, Q, R) from local watchlist."""
    if watchlist_df.empty:
        return {}
    if price_columns is None:
        price_columns = ["P", "Q", "R"]

    first_col = watchlist_df.columns[0]
    mask = watchlist_df[first_col].astype(str).str.strip().str.upper() == symbol.upper()
    matching = watchlist_df[mask]
    if matching.empty:
        return {}

    row = matching.iloc[0]
    result = {}
    for col_letter in price_columns:
        col_index = ord(col_letter.upper()) - ord('A')
        if col_index < len(watchlist_df.columns):
            col_name = watchlist_df.columns[col_index]
            result[col_name] = row[col_name]
    return result


def apply_rule_4(symbols_df, watchlist_df, cfg):
    """
    Rule 4: Check Column O (LTP) is TRUE in watchlist.
    Then check price columns and return qualifying symbols with price data.

    Returns list of dicts: [{symbol, ltp_status, price_data, ...}]
    """
    wl_cfg = cfg.get("watchlist", cfg.get("google_sheet", {}))
    ltp_column = wl_cfg.get("ltp_check_column", "O")
    price_columns = wl_cfg.get("price_columns", ["P", "Q", "R"])

    if watchlist_df.empty:
        logger.warning("Rule 4: Watchlist empty. Returning all symbols.")
        return [{"symbol": s, "ltp_ok": True, "price_data": {}} for s in symbols_df]

    qualified = []

    # Use local functions or gspread functions depending on availability
    for symbol in symbols_df:
        if GSHEET_AVAILABLE:
            ltp_ok, row_data = check_ltp_status(watchlist_df, symbol, ltp_column)
            price_data = get_price_columns(watchlist_df, symbol, price_columns) if ltp_ok else {}
        else:
            ltp_ok, row_data = _check_ltp_local(watchlist_df, symbol, ltp_column)
            price_data = _get_price_cols_local(watchlist_df, symbol, price_columns) if ltp_ok else {}

        if not ltp_ok:
            logger.info(f"Rule 4: {symbol} - Column {ltp_column} is NOT TRUE. Skipped.")
            continue

        qualified.append({
            "symbol": symbol,
            "ltp_ok": True,
            "price_data": price_data,
            "sheet_row": row_data,
        })
        logger.info(f"Rule 4: {symbol} - Column {ltp_column} is TRUE. Prices: {price_data}")

    logger.info(f"Rule 4: {len(qualified)} stocks passed LTP check")
    return qualified


def run_stock_picker(driver, triggers_df, cfg):
    """
    Master function: Run all 4 rules sequentially, then collect
    full Quantsapp tool analysis for each qualifying stock.

    Watchlist source priority:
      1. Local Excel (watchlist.local_file in config.json)
      2. Google Sheet (if gspread is available and configured)

    Returns:
      - picks: list of dicts with full analysis per stock
      - announcement: formatted message string
    """
    filter_cfg = cfg.get("filter_rules", {})
    tool_urls = cfg.get("quantsapp_tools_urls", {})
    wait_seconds = cfg.get("max_table_wait_seconds", 15)

    # --- Load watchlist: Local Excel first, then Google Sheet fallback ---
    logger.info("Loading WBRam watchlist...")
    watchlist_df = _load_local_watchlist(cfg)

    if watchlist_df.empty and GSHEET_AVAILABLE:
        logger.info("Local watchlist empty/missing. Trying Google Sheet...")
        watchlist_df = load_watchlist(cfg)
        allowed_symbols = get_allowed_symbols(watchlist_df)
    else:
        allowed_symbols = _get_allowed_symbols_local(watchlist_df)

    logger.info(f"Loaded {len(allowed_symbols)} symbols from watchlist")

    # --- Apply Rule 1: Highest CE OI Changes ---
    logger.info("Applying Rule 1: Highest CE OI Changes...")
    r1 = apply_rule_1(
        triggers_df,
        min_ce_oi_change_pct=filter_cfg.get("rule1_min_ce_oi_change_pct", 5.0)
    )

    # --- Apply Rule 2: Call-Put diff -1% to +1% ---
    logger.info("Applying Rule 2: Call-Put Diff filter...")
    r2 = apply_rule_2(
        r1,
        diff_min=filter_cfg.get("rule2_call_put_diff_min", -1.0),
        diff_max=filter_cfg.get("rule2_call_put_diff_max", 1.0)
    )

    # --- Apply Rule 3: Must be in Google Sheet ---
    logger.info("Applying Rule 3: Google Sheet watchlist filter...")
    r3 = apply_rule_3(r2, allowed_symbols)

    if r3.empty:
        logger.info("No stocks passed Rules 1-3. No picks this cycle.")
        return [], "No stocks qualified after Rules 1-3 this cycle."

    # Get unique symbols that passed Rules 1-3
    # Use _clean_symbol column if available (added by Rule 3), otherwise find symbol column
    if "_clean_symbol" in r3.columns:
        passing_symbols = r3["_clean_symbol"].dropna().unique().tolist()
    else:
        symbol_col = None
        for col in r3.columns:
            if col.upper() in ["SYMBOL", "STOCK", "NAME"]:
                symbol_col = col
                break
        if symbol_col is None:
            symbol_col = r3.columns[0]
        # Use iloc to ensure we get a Series (not DataFrame) even with duplicate column names
        col_idx = r3.columns.get_loc(symbol_col)
        if isinstance(col_idx, int):
            sym_series = r3.iloc[:, col_idx]
        else:
            sym_series = r3.iloc[:, col_idx[0]] if hasattr(col_idx, '__iter__') else r3.iloc[:, 0]
        passing_symbols = [
            _clean_symbol(s) for s in sym_series.astype(str).str.strip().str.upper().unique().tolist()
        ]

    # --- Apply Rule 4: LTP Column O = TRUE + price check ---
    logger.info("Applying Rule 4: LTP Column O check...")
    qualified = apply_rule_4(passing_symbols, watchlist_df, cfg)

    if not qualified:
        logger.info("No stocks passed Rule 4 (LTP check). No picks this cycle.")
        return [], "No stocks qualified after Rule 4 (LTP check) this cycle."

    # --- Collect FULL analysis from ALL Quantsapp tools ---
    picks = []
    for item in qualified:
        symbol = item["symbol"]
        logger.info(f"Collecting full Quantsapp tool analysis for: {symbol}")

        try:
            tool_data = collect_all_tool_data(driver, symbol, tool_urls, wait_seconds)

            # Merge with Google Sheet data
            tool_data["GS_LTP_Status"] = "TRUE"
            for k, v in item.get("price_data", {}).items():
                tool_data[f"GS_{k}"] = v

            picks.append(tool_data)

        except Exception as e:
            logger.error(f"Failed to collect tool data for {symbol}: {e}")
            picks.append({
                "Symbol": symbol,
                "Analysis_Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Error": str(e),
            })

    # --- Generate announcement ---
    announcement = _build_announcement(picks)

    return picks, announcement


def _build_announcement(picks):
    """
    Build the Telegram announcement message for all stock picks.
    """
    if not picks:
        return "No stock picks this cycle."

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = f"*Stock Pick from WBRam Excel* ({now})\n"
    msg += "=" * 40 + "\n\n"

    for pick in picks:
        symbol = pick.get("Symbol", "Unknown")
        msg += f"*{symbol}*\n"
        msg += "-" * 30 + "\n"

        # Option Triggers data
        if pick.get("OT_CE_OI_Change_Pct"):
            msg += f"CE OI Change: {pick['OT_CE_OI_Change_Pct']}%\n"
        if pick.get("OT_Call_Put_Diff_Pct"):
            msg += f"Call-Put Diff: {pick['OT_Call_Put_Diff_Pct']}%\n"
        if pick.get("OT_LTP"):
            msg += f"LTP: {pick['OT_LTP']}\n"

        # IV Analysis
        if pick.get("IVP"):
            msg += f"IVP: {pick['IVP']} ({pick.get('IVP_Status', '')})\n"
        if pick.get("IV"):
            msg += f"IV: {pick['IV']}\n"
        if pick.get("IV_Signal"):
            msg += f"IV Signal: {pick['IV_Signal']}\n"

        # OI Analysis
        if pick.get("OI_Trend"):
            msg += f"OI Trend: {pick['OI_Trend']}\n"
        if pick.get("OI_Max_CE_Strike"):
            msg += f"Resistance (Max CE OI): {pick['OI_Max_CE_Strike']}\n"
        if pick.get("OI_Max_PE_Strike"):
            msg += f"Support (Max PE OI): {pick['OI_Max_PE_Strike']}\n"

        # PCR
        if pick.get("PCR_OI"):
            msg += f"PCR (OI): {pick['PCR_OI']} - {pick.get('PCR_Signal', '')}\n"

        # Buildup
        if pick.get("BU_Type"):
            msg += f"Buildup: {pick['BU_Type']} ({pick.get('BU_Signal', '')})\n"

        # Futures OI
        if pick.get("FUT_OI_Change_Pct"):
            msg += f"Futures OI Change: {pick['FUT_OI_Change_Pct']}%\n"
        if pick.get("FUT_Signal"):
            msg += f"Futures Signal: {pick['FUT_Signal']}\n"

        # Max Pain
        if pick.get("MP_Strike"):
            msg += f"Max Pain: {pick['MP_Strike']}\n"
        if pick.get("MP_Signal"):
            msg += f"Max Pain Signal: {pick['MP_Signal']}\n"

        # Overall Verdict
        if pick.get("Overall_Verdict"):
            msg += f"\n*VERDICT: {pick['Overall_Verdict']}*\n"

        msg += "\n"

    return msg
