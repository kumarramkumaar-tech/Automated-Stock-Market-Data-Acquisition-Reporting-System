# helpers/report_utils.py – Buildup Pattern Detector
import pandas as pd
import os
from openpyxl import load_workbook
from openpyxl.styles import Font, Alignment, PatternFill
from datetime import datetime
from helpers.notify import send_telegram

# Buildup classification rules:
# Long Buildup:     Price UP + OI UP    (Bullish)
# Short Buildup:    Price DOWN + OI UP  (Bearish)
# Long Unwinding:   Price DOWN + OI DOWN (Bearish exit)
# Short Covering:   Price UP + OI DOWN  (Bullish exit)

BUILDUP_COLORS = {
    "Long Buildup": "00AA00",     # Green
    "Short Buildup": "CC0000",    # Red
    "Long Unwinding": "FF8800",   # Orange
    "Short Covering": "0066CC",   # Blue
}

SECTOR_MAP = {
    "RELIANCE": "Energy", "ONGC": "Energy", "BPCL": "Energy", "IOC": "Energy",
    "HDFCBANK": "Banking", "ICICIBANK": "Banking", "SBIN": "Banking",
    "KOTAKBANK": "Banking", "AXISBANK": "Banking", "BANKBARODA": "Banking",
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT", "TECHM": "IT",
    "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG", "BRITANNIA": "FMCG",
    "TATAMOTORS": "Auto", "MARUTI": "Auto", "M&M": "Auto", "BAJAJ-AUTO": "Auto",
    "SUNPHARMA": "Pharma", "DRREDDY": "Pharma", "CIPLA": "Pharma", "DIVISLAB": "Pharma",
    "TATASTEEL": "Metals", "JSWSTEEL": "Metals", "HINDALCO": "Metals",
    "ADANIENT": "Infra", "ADANIPORTS": "Infra", "LTIM": "Infra", "LT": "Infra",
}


def classify_buildup(row):
    """
    Classify buildup type based on price change and OI change.
    """
    try:
        price_chg = float(row.get("Price Change %", 0))
        oi_chg = float(row.get("Change %", 0))
    except (ValueError, TypeError):
        return "Unknown"

    if price_chg > 0 and oi_chg > 0:
        return "Long Buildup"
    elif price_chg < 0 and oi_chg > 0:
        return "Short Buildup"
    elif price_chg < 0 and oi_chg < 0:
        return "Long Unwinding"
    elif price_chg > 0 and oi_chg < 0:
        return "Short Covering"
    return "Unknown"


def detect_reversals(file_path):
    """
    Detect buildup pattern reversals (e.g., Short Buildup -> Short Covering).
    Sends Telegram alerts for significant reversals.
    """
    if not os.path.exists(file_path):
        return

    try:
        df = pd.read_excel(file_path, sheet_name="Pattern_Log")
        if df.empty or len(df) < 2:
            return

        df["Fetched At"] = pd.to_datetime(df["Fetched At"])

        # Get last two fetches per symbol
        latest_times = sorted(df["Fetched At"].unique())[-2:]
        if len(latest_times) < 2:
            return

        prev_fetch = df[df["Fetched At"] == latest_times[0]]
        curr_fetch = df[df["Fetched At"] == latest_times[1]]

        reversals = []
        for symbol in curr_fetch["Symbol"].unique():
            prev_row = prev_fetch[prev_fetch["Symbol"] == symbol]
            curr_row = curr_fetch[curr_fetch["Symbol"] == symbol]

            if prev_row.empty or curr_row.empty:
                continue

            prev_pattern = prev_row.iloc[0].get("Detected Pattern", "Unknown")
            curr_pattern = curr_row.iloc[0].get("Detected Pattern", "Unknown")

            if prev_pattern != curr_pattern and curr_pattern != "Unknown":
                reversals.append({
                    "Symbol": symbol,
                    "From": prev_pattern,
                    "To": curr_pattern,
                    "Time": datetime.now().strftime("%H:%M"),
                })

        if reversals:
            msg = "*Pattern Reversal Alerts*\n\n"
            for r in reversals:
                msg += f"*{r['Symbol']}*: {r['From']} -> {r['To']} at {r['Time']}\n"
            send_telegram(msg)

            # Write reversals to sheet
            rev_df = pd.DataFrame(reversals)
            rev_df["Date"] = datetime.now().strftime("%Y-%m-%d")
            from helpers.excel_utils import append_df_to_excel
            append_df_to_excel(file_path, rev_df, sheet_name="Reversals")

    except Exception as e:
        send_telegram(f"Reversal detection error: {e}")


def compute_sector_buildup(file_path):
    """
    Aggregate buildup patterns by sector.
    Writes sector-wise summary to 'Sector_Buildup' sheet.
    """
    if not os.path.exists(file_path):
        return

    try:
        df = pd.read_excel(file_path, sheet_name="Pattern_Log")
        if df.empty:
            return

        # Filter to today's data
        df["Fetched At"] = pd.to_datetime(df["Fetched At"])
        today = datetime.now().date()
        df_today = df[df["Fetched At"].dt.date == today]

        if df_today.empty:
            return

        # Map symbols to sectors
        df_today = df_today.copy()
        df_today["Sector"] = df_today["Symbol"].map(SECTOR_MAP).fillna("Other")

        # Count patterns per sector
        sector_summary = (
            df_today.groupby(["Sector", "Detected Pattern"])
            .size()
            .reset_index(name="Count")
        )

        # Pivot for readability
        pivot = sector_summary.pivot_table(
            index="Sector",
            columns="Detected Pattern",
            values="Count",
            fill_value=0
        ).reset_index()

        with pd.ExcelWriter(file_path, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
            pivot.to_excel(writer, sheet_name="Sector_Buildup", index=False)

        # Telegram summary
        msg = f"*Sector Buildup Summary ({today})*\n\n"
        for _, row in pivot.iterrows():
            sector = row["Sector"]
            parts = []
            for pattern in ["Long Buildup", "Short Buildup", "Long Unwinding", "Short Covering"]:
                if pattern in row and row[pattern] > 0:
                    parts.append(f"{pattern}: {int(row[pattern])}")
            if parts:
                msg += f"*{sector}*: {', '.join(parts)}\n"

        send_telegram(msg)

    except Exception as e:
        send_telegram(f"Sector buildup error: {e}")


def update_summary(file_path):
    """Creates daily summary of buildup patterns."""
    if not os.path.exists(file_path):
        return

    try:
        df = pd.read_excel(file_path, sheet_name="Pattern_Log")
        if df.empty or "Fetched At" not in df.columns:
            return

        df["Date"] = pd.to_datetime(df["Fetched At"]).dt.date

        # Count patterns per day
        summary = (
            df.groupby(["Date", "Detected Pattern"])
            .size()
            .reset_index(name="Count")
        )

        pivot = summary.pivot_table(
            index="Date",
            columns="Detected Pattern",
            values="Count",
            fill_value=0
        ).reset_index()

        # Add total column
        pattern_cols = [c for c in pivot.columns if c != "Date"]
        pivot["Total"] = pivot[pattern_cols].sum(axis=1)

        with pd.ExcelWriter(file_path, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
            pivot.to_excel(writer, sheet_name="Daily_Summary", index=False)

        today = datetime.now().date()
        today_row = pivot[pivot["Date"] == today]
        if not today_row.empty:
            r = today_row.iloc[0]
            msg = f"*Buildup Pattern Summary ({today})*\n"
            for pattern in ["Long Buildup", "Short Buildup", "Long Unwinding", "Short Covering"]:
                if pattern in r:
                    msg += f"{pattern}: {int(r[pattern])}\n"
            msg += f"Total Signals: {int(r['Total'])}"
            send_telegram(msg)

    except Exception as e:
        send_telegram(f"Error updating buildup summary: {e}")


def format_excel(file_path):
    """Auto-format all sheets with pattern-specific colors."""
    if not os.path.exists(file_path):
        return

    try:
        wb = load_workbook(file_path)

        for sheet_name in ["Pattern_Log", "Daily_Summary", "Sector_Buildup", "Reversals"]:
            if sheet_name not in wb.sheetnames:
                continue
            ws = wb[sheet_name]
            bold = Font(bold=True)
            for cell in ws[1]:
                cell.font = bold
                cell.alignment = Alignment(horizontal="center")

            for col in ws.columns:
                max_length = 0
                col_letter = col[0].column_letter
                for cell in col:
                    val = str(cell.value) if cell.value is not None else ""
                    max_length = max(max_length, len(val))
                ws.column_dimensions[col_letter].width = min(max_length + 2, 35)

        # Color-code Pattern_Log by buildup type
        if "Pattern_Log" in wb.sheetnames:
            ws = wb["Pattern_Log"]
            pattern_col = None
            for cell in ws[1]:
                if cell.value == "Detected Pattern":
                    pattern_col = cell.column
                    break

            if pattern_col:
                for row in ws.iter_rows(min_row=2):
                    pattern_cell = row[pattern_col - 1]
                    pattern = str(pattern_cell.value)
                    if pattern in BUILDUP_COLORS:
                        color = BUILDUP_COLORS[pattern]
                        pattern_cell.font = Font(color=color, bold=True)

            # Also color % columns
            for row in ws.iter_rows(min_row=2):
                for cell in row:
                    header = ws.cell(row=1, column=cell.column).value
                    if header and "%" in str(header):
                        try:
                            val = float(cell.value)
                            if val > 0:
                                cell.font = Font(color="008000")
                            elif val < 0:
                                cell.font = Font(color="FF0000")
                        except (ValueError, TypeError):
                            pass

        wb.save(file_path)

    except Exception as e:
        send_telegram(f"Excel formatting failed: {e}")
