# helpers/report_utils.py – Option Triggers Report Utilities
#
# Generates detailed Excel reports with columns from EVERY Quantsapp tool.
# Each stock pick gets a full row with 40+ columns covering:
#   - Option Triggers (OT_*) – CE/PE OI, volumes, trigger type
#   - IV Analysis (IV_*) – IV, IVP, IV Rank, HV, signal
#   - OI Analysis (OI_*) – Total OI, max strikes, PCR, trend
#   - PCR Analysis (PCR_*) – PCR by OI/Volume, trend, signal
#   - Buildup (BU_*) – Buildup type, price/OI changes, signal
#   - Futures OI (FUT_*) – Futures OI, change, basis, signal
#   - Max Pain (MP_*) – Max pain strike, distance, signal
#   - Google Sheet (GS_*) – LTP status, price columns
#   - Overall Verdict

import pandas as pd
import os
import logging
from openpyxl import load_workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from datetime import datetime
from helpers.notify import send_telegram
from helpers.excel_utils import append_df_to_excel, write_sheet

logger = logging.getLogger(__name__)

# Full column order for the Stock_Picks sheet
PICK_COLUMNS = [
    # Identification
    "Symbol", "Analysis_Time",

    # Option Triggers Tool
    "OT_CE_OI", "OT_CE_OI_Change", "OT_CE_OI_Change_Pct",
    "OT_PE_OI", "OT_PE_OI_Change", "OT_PE_OI_Change_Pct",
    "OT_CE_Volume", "OT_PE_Volume",
    "OT_Trigger_Type", "OT_LTP", "OT_Change_Pct",
    "OT_Call_Put_Diff_Pct",

    # Column G: Writers Trap Indicator
    "TRAP_Indicator", "TRAP_Type", "TRAP_Return_Pct", "TRAP_Note",

    # Column H: IV Detailed with 3-month Hi/Lo
    "IV_Summary", "IV_Current", "IV_3M_High", "IV_3M_Low", "IV_Level",

    # IV Analysis Tool (basic)
    "IV", "IVP", "IV_Rank", "IVP_Status",
    "HV", "IV_vs_HV", "IV_Signal",

    # Column I: OI Strikes by Expiry (R1/R2 ranks)
    "OI_Strikes_Summary",
    "OI_Near_CE_R1", "OI_Near_CE_R2", "OI_Near_PE_R1", "OI_Near_PE_R2",
    "OI_Next_CE_R1", "OI_Next_CE_R2", "OI_Next_PE_R1", "OI_Next_PE_R2",

    # OI Analysis Tool
    "OI_Total_CE_OI", "OI_Total_PE_OI",
    "OI_CE_OI_Change", "OI_PE_OI_Change",
    "OI_Max_CE_Strike", "OI_Max_PE_Strike",
    "OI_PCR_from_OI", "OI_Trend",

    # PCR Analysis Tool
    "PCR_OI", "PCR_Volume", "PCR_Trend", "PCR_Signal",

    # Column J: Buildup Scrip FUT OI-H
    "BU_FUT_OIH", "BU_FUT_OIH_Detail",

    # Column K: Buildup Scrip Cycle
    "BU_Scrip_Cycle", "BU_Scrip_Cycle_Detail",

    # Buildup Tool (basic)
    "BU_Type", "BU_Price_Change_Pct", "BU_OI_Change_Pct", "BU_Signal",

    # Columns L, M, N: Buildup Sector
    "BU_Sector", "BU_Sector_Detail",            # Column L
    "BU_Sector_Cycle", "BU_Sector_Cycle_Detail", # Column M
    "BU_Sector_OIH", "BU_Sector_OIH_Detail",    # Column N

    # Futures OI Tool
    "FUT_OI", "FUT_OI_Change", "FUT_OI_Change_Pct",
    "FUT_Price", "FUT_Basis", "FUT_Signal",

    # Max Pain Tool
    "MP_Strike", "MP_Current_Price", "MP_Distance",
    "MP_Distance_Pct", "MP_Signal",

    # Google Sheet Data
    "GS_LTP_Status",

    # Overall
    "Overall_Verdict",
]

# Color schemes for different tool sections
SECTION_COLORS = {
    "OT_": "D4E6F1",     # Light blue – Option Triggers
    "TRAP_": "F5B7B1",   # Light red – Writers Trap (Col G)
    "IV_": "D5F5E3",     # Light green – IV Analysis (Col H)
    "IV":  "D5F5E3",     # Light green – IV Analysis
    "HV":  "D5F5E3",     # Light green – IV Analysis
    "OI_": "FCF3CF",     # Light yellow – OI Analysis (Col I)
    "PCR_": "FADBD8",    # Light pink – PCR
    "BU_FUT": "D2B4DE",  # Purple – Buildup FUT OI-H (Col J)
    "BU_Scrip": "D7BDE2",# Light purple – Buildup Scrip Cycle (Col K)
    "BU_Sector": "EBDEF0",# Very light purple – Sector (Cols L-N)
    "BU_": "E8DAEF",     # Light purple – Buildup (basic)
    "FUT_": "F6DDCC",    # Light orange – Futures
    "MP_": "D6EAF8",     # Light cyan – Max Pain
    "GS_": "FDEBD0",     # Light peach – Google Sheet
}

# Signal columns to color-code (green=bullish, red=bearish)
SIGNAL_COLUMNS = [
    "TRAP_Indicator", "IV_Signal", "OI_Trend", "PCR_Signal",
    "BU_Signal", "BU_FUT_OIH", "BU_Scrip_Cycle",
    "BU_Sector", "BU_Sector_Cycle", "BU_Sector_OIH",
    "FUT_Signal", "MP_Signal", "Overall_Verdict",
]


def save_picks_to_excel(picks, file_path):
    """
    Save stock picks with full tool analysis to Excel.
    Creates/updates 'Stock_Picks' sheet with all 40+ columns.
    Also appends to 'Pick_History' for historical tracking.
    """
    if not picks:
        return

    try:
        # Create DataFrame with all columns in order
        df = pd.DataFrame(picks)

        # Ensure all expected columns exist
        for col in PICK_COLUMNS:
            if col not in df.columns:
                df[col] = ""

        # Reorder columns
        existing_cols = [c for c in PICK_COLUMNS if c in df.columns]
        extra_cols = [c for c in df.columns if c not in PICK_COLUMNS]
        df = df[existing_cols + extra_cols]

        # Write to Stock_Picks (replace with latest)
        write_sheet(file_path, df, "Stock_Picks")

        # Append to Pick_History (cumulative log)
        append_df_to_excel(file_path, df, sheet_name="Pick_History")

        logger.info(f"Saved {len(picks)} picks to Excel ({file_path})")

    except Exception as e:
        logger.error(f"Failed to save picks: {e}")
        send_telegram(f"Failed to save picks to Excel: {e}")


def update_summary(file_path):
    """
    Create a daily summary from Pick_History.
    Shows per-day: count of picks, symbols, dominant signal.
    """
    if not os.path.exists(file_path):
        return

    try:
        df = pd.read_excel(file_path, sheet_name="Pick_History")
        if df.empty:
            return

        df["Date"] = pd.to_datetime(df["Analysis_Time"]).dt.date

        # Summary per day
        summary_rows = []
        for date, group in df.groupby("Date"):
            symbols = group["Symbol"].unique().tolist()
            verdicts = group["Overall_Verdict"].dropna().tolist()

            bullish = sum(1 for v in verdicts if "BULLISH" in str(v).upper())
            bearish = sum(1 for v in verdicts if "BEARISH" in str(v).upper())

            summary_rows.append({
                "Date": date,
                "Total Picks": len(group),
                "Unique Symbols": len(symbols),
                "Symbols": ", ".join(symbols[:10]),
                "Bullish Picks": bullish,
                "Bearish Picks": bearish,
                "Dominant Signal": "Bullish" if bullish > bearish else "Bearish" if bearish > bullish else "Mixed",
            })

        summary_df = pd.DataFrame(summary_rows)
        write_sheet(file_path, summary_df, "Daily_Summary")

        # Telegram for today
        today = datetime.now().date()
        today_row = summary_df[summary_df["Date"] == today]
        if not today_row.empty:
            r = today_row.iloc[0]
            msg = (
                f"*Option Triggers Daily Summary ({today})*\n"
                f"Total Picks: {r['Total Picks']}\n"
                f"Symbols: {r['Symbols']}\n"
                f"Bullish: {r['Bullish Picks']} | Bearish: {r['Bearish Picks']}\n"
                f"Dominant: {r['Dominant Signal']}"
            )
            send_telegram(msg)

    except Exception as e:
        logger.error(f"Summary update failed: {e}")


def format_excel(file_path):
    """
    Apply comprehensive formatting to the Option Triggers Excel file.
    - Color-coded section headers per tool
    - Conditional formatting for signals (green/red)
    - Bold headers, auto-width, borders
    """
    if not os.path.exists(file_path):
        return

    try:
        wb = load_workbook(file_path)

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]

            # Bold headers with center alignment
            bold_font = Font(bold=True, size=10)
            thin_border = Border(
                left=Side(style="thin"),
                right=Side(style="thin"),
                top=Side(style="thin"),
                bottom=Side(style="thin"),
            )

            # Format header row
            for cell in ws[1]:
                cell.font = bold_font
                cell.alignment = Alignment(horizontal="center", wrap_text=True)
                cell.border = thin_border

                # Color-code headers by tool section
                header_text = str(cell.value or "")
                for prefix, color in SECTION_COLORS.items():
                    if header_text.startswith(prefix):
                        cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
                        break

                # Special columns
                if header_text == "Overall_Verdict":
                    cell.fill = PatternFill(start_color="F9E79F", end_color="F9E79F", fill_type="solid")
                elif header_text in ["Symbol", "Analysis_Time"]:
                    cell.fill = PatternFill(start_color="AED6F1", end_color="AED6F1", fill_type="solid")

            # Auto column width
            for col in ws.columns:
                max_length = 0
                col_letter = col[0].column_letter
                for cell in col:
                    val = str(cell.value) if cell.value is not None else ""
                    max_length = max(max_length, len(val))
                ws.column_dimensions[col_letter].width = min(max_length + 3, 30)

            # Color-code signal columns
            if sheet_name in ["Stock_Picks", "Pick_History"]:
                for row in ws.iter_rows(min_row=2):
                    for cell in row:
                        header = ws.cell(row=1, column=cell.column).value
                        if header in SIGNAL_COLUMNS:
                            val_str = str(cell.value or "").upper()
                            if "BULLISH" in val_str or "BUY" in val_str or "CHEAP" in val_str:
                                cell.font = Font(color="006600", bold=True)  # Dark green
                            elif "BEARISH" in val_str or "SELL" in val_str or "EXPENSIVE" in val_str:
                                cell.font = Font(color="CC0000", bold=True)  # Dark red
                            elif "NEUTRAL" in val_str or "MIXED" in val_str:
                                cell.font = Font(color="996600", bold=True)  # Dark orange

                        # IVP_Status special coloring
                        if header == "IVP_Status":
                            val_str = str(cell.value or "").upper()
                            if "VERY HIGH" in val_str:
                                cell.fill = PatternFill(start_color="FADBD8", fill_type="solid")
                            elif "HIGH" in val_str:
                                cell.fill = PatternFill(start_color="F5CBA7", fill_type="solid")
                            elif "VERY LOW" in val_str:
                                cell.fill = PatternFill(start_color="ABEBC6", fill_type="solid")
                            elif "LOW" in val_str:
                                cell.fill = PatternFill(start_color="D5F5E3", fill_type="solid")

                        # Buildup type coloring
                        if header == "BU_Type":
                            val_str = str(cell.value or "").upper()
                            if "LONG BUILDUP" in val_str:
                                cell.font = Font(color="006600", bold=True)
                            elif "SHORT BUILDUP" in val_str:
                                cell.font = Font(color="CC0000", bold=True)
                            elif "LONG UNWIND" in val_str:
                                cell.font = Font(color="CC6600")
                            elif "SHORT COVER" in val_str:
                                cell.font = Font(color="0066CC")

                        # Percentage columns: green/red
                        if header and "%" in str(header) or header and "Change" in str(header):
                            try:
                                val = float(str(cell.value).replace("%", "").replace(",", ""))
                                if val > 0:
                                    cell.font = Font(color="008000")
                                elif val < 0:
                                    cell.font = Font(color="FF0000")
                            except (ValueError, TypeError):
                                pass

                    # Add border to all data cells
                    for cell in row:
                        cell.border = thin_border

        wb.save(file_path)
        logger.info(f"Excel formatted: {file_path}")

    except Exception as e:
        logger.error(f"Excel formatting failed: {e}")
        send_telegram(f"Excel formatting failed: {e}")
