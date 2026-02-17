# helpers/stock_picker.py – 4-Rule Stock Pick Engine
#
# Rule 1: Highest CE OI changes from Option Triggers
# Rule 2: Call-Put diff should be between -1% to +1%
# Rule 3: Stock must be in the WBRam Google Sheet watchlist
# Rule 4: Column O (LTP) in Google Sheet must be TRUE, then check price columns
#
# After filtering: Collect full analysis from ALL Quantsapp tools
# and generate the announcement.

import logging
import pandas as pd
from datetime import datetime

from helpers.google_sheet import load_watchlist, get_allowed_symbols, check_ltp_status, get_price_columns
from helpers.quantsapp_tools import collect_all_tool_data
from helpers.notify import send_telegram

logger = logging.getLogger(__name__)


def apply_rule_1(df, min_ce_oi_change_pct=5.0):
    """
    Rule 1: Filter for highest CE OI changes.
    Keep rows where CE OI Change % >= threshold.
    Sort by CE OI Change % descending.
    """
    if df.empty:
        return df

    # Try to find CE OI change column
    ce_change_col = None
    for col in df.columns:
        col_upper = col.upper()
        if "CE" in col_upper and "OI" in col_upper and ("CHANGE" in col_upper or "CHG" in col_upper) and "%" in col_upper:
            ce_change_col = col
            break
        elif "CE" in col_upper and "OI" in col_upper and ("CHANGE" in col_upper or "CHG" in col_upper):
            ce_change_col = col

    if ce_change_col is None:
        # Fallback: use "Change %" if available (from unusual activity data)
        for col in df.columns:
            if col in ["Change %", "OT_CE_OI_Change_Pct"]:
                ce_change_col = col
                break

    if ce_change_col is None:
        logger.warning("Rule 1: Could not find CE OI Change column. Skipping filter.")
        return df

    df = df.copy()
    df["_ce_oi_change_num"] = pd.to_numeric(
        df[ce_change_col].astype(str).str.replace("%", "").str.replace(",", ""),
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
        logger.warning("Rule 2: Could not find or compute Call-Put diff. Skipping filter.")
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
    Rule 3: Stock must be in the WBRam Google Sheet watchlist.
    """
    if df.empty or not allowed_symbols:
        if not allowed_symbols:
            logger.warning("Rule 3: No symbols loaded from Google Sheet. Skipping filter.")
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
    filtered = df[df[symbol_col].astype(str).str.strip().str.upper().isin(allowed_upper)].copy()

    logger.info(f"Rule 3: {len(filtered)} stocks match Google Sheet watchlist (from {len(allowed_symbols)} allowed)")
    return filtered


def apply_rule_4(symbols_df, watchlist_df, cfg):
    """
    Rule 4: Check Column O (LTP) is TRUE in Google Sheet.
    Then check price columns and return qualifying symbols with price data.

    Returns list of dicts: [{symbol, ltp_status, price_data, ...}]
    """
    gs_cfg = cfg.get("google_sheet", {})
    ltp_column = gs_cfg.get("ltp_check_column", "O")
    price_columns = gs_cfg.get("price_columns", ["P", "Q", "R"])

    if watchlist_df.empty:
        logger.warning("Rule 4: Watchlist empty. Returning all symbols.")
        return [{"symbol": s, "ltp_ok": True, "price_data": {}} for s in symbols_df]

    qualified = []

    for symbol in symbols_df:
        ltp_ok, row_data = check_ltp_status(watchlist_df, symbol, ltp_column)

        if not ltp_ok:
            logger.info(f"Rule 4: {symbol} - Column {ltp_column} is NOT TRUE. Skipped.")
            continue

        price_data = get_price_columns(watchlist_df, symbol, price_columns)

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

    Returns:
      - picks: list of dicts with full analysis per stock
      - announcement: formatted message string
    """
    filter_cfg = cfg.get("filter_rules", {})
    tool_urls = cfg.get("quantsapp_tools_urls", {})
    wait_seconds = cfg.get("max_table_wait_seconds", 15)

    # --- Load Google Sheet watchlist ---
    logger.info("Loading WBRam Google Sheet watchlist...")
    watchlist_df = load_watchlist(cfg)
    allowed_symbols = get_allowed_symbols(watchlist_df)
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
    symbol_col = None
    for col in r3.columns:
        if col.upper() in ["SYMBOL", "STOCK", "NAME"]:
            symbol_col = col
            break
    if symbol_col is None:
        symbol_col = r3.columns[0]

    passing_symbols = r3[symbol_col].astype(str).str.strip().str.upper().unique().tolist()

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
