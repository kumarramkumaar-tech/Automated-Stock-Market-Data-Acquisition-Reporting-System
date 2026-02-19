"""
Test script: Simulates FNO Scanner data and runs the full analysis pipeline.
Generates sample FNO data resembling Quantsapp FNO Scanner output,
then runs data analysis, Excel export, formatting, and visual reports.
"""
import os
import sys
import random
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from helpers.data_analysis import (
    analyze_fno_data, classify_buildup,
    generate_analysis_summary_text, write_analysis_to_excel
)
from helpers.excel_utils import append_df_to_excel, format_fno_excel
from helpers.report_visuals import generate_fno_visual_report, generate_daily_summary


def generate_sample_fno_data(num_rows=150):
    """Generate realistic sample FNO Scanner data."""

    symbols = [
        "NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK",
        "ICICIBANK", "SBIN", "TATAMOTORS", "MARUTI", "BAJFINANCE",
        "HCLTECH", "WIPRO", "AXISBANK", "KOTAKBANK", "LT", "ITC",
        "HINDUNILVR", "ADANIENT", "ADANIPORTS", "TATASTEEL", "JSWSTEEL",
        "COALINDIA", "POWERGRID", "NTPC", "ONGC", "BHARTIARTL",
        "TECHM", "SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB"
    ]

    expiries = ["27-FEB-2026", "06-MAR-2026", "13-MAR-2026", "27-MAR-2026"]
    types = ["CE", "PE"]

    rows = []
    for _ in range(num_rows):
        symbol = random.choice(symbols)
        expiry = random.choice(expiries)
        opt_type = random.choice(types)

        # Realistic strike prices based on symbol
        if symbol == "NIFTY":
            strike = random.choice(range(22000, 24000, 50))
            ltp = round(random.uniform(10, 500), 2)
        elif symbol == "BANKNIFTY":
            strike = random.choice(range(48000, 52000, 100))
            ltp = round(random.uniform(20, 800), 2)
        else:
            strike = random.choice(range(500, 5000, 50))
            ltp = round(random.uniform(5, 300), 2)

        price_change = round(random.uniform(-50, 50), 2)
        price_change_pct = round(random.uniform(-15, 15), 2)
        oi = random.randint(1000, 500000)
        oi_change = random.randint(-50000, 80000)
        oi_change_pct = round(random.uniform(-30, 40), 2)
        iv = round(random.uniform(10, 80), 2)
        iv_change = round(random.uniform(-5, 5), 2)
        iv_change_pct = round(random.uniform(-10, 10), 2)
        volume = random.randint(100, 200000)

        rows.append({
            "Symbol": symbol,
            "Expiry": expiry,
            "Type": opt_type,
            "Strike": strike,
            "LTP": ltp,
            "Price Change": price_change,
            "Price Change %": price_change_pct,
            "OI": oi,
            "OI Change": oi_change,
            "OI Change %": oi_change_pct,
            "IV": iv,
            "IV Change": iv_change,
            "IV Change %": iv_change_pct,
            "Volume": volume,
        })

    df = pd.DataFrame(rows)
    df["Fetched At"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df["Buildup Classification"] = df.apply(classify_buildup, axis=1)
    return df


def main():
    print("=" * 60)
    print("  FNO Scanner - Test Run with Sample Data")
    print("=" * 60)

    os.makedirs("output", exist_ok=True)
    os.makedirs("reports", exist_ok=True)
    os.makedirs("logs", exist_ok=True)

    output_file = "output/FNO_Scanner_Data.xlsx"

    # Remove old test file
    if os.path.exists(output_file):
        os.remove(output_file)

    # --- Generate sample data ---
    print("\n[1/6] Generating 150 sample FNO rows...")
    df = generate_sample_fno_data(150)
    print(f"  Generated {len(df)} rows across {df['Symbol'].nunique()} symbols")
    print(f"  Columns: {list(df.columns)}")
    print(f"\n  Sample rows:")
    print(df.head(5).to_string(index=False))

    # --- Export to Excel ---
    print("\n[2/6] Exporting to Excel...")
    append_df_to_excel(output_file, df, sheet_name="FNO_Data")
    print(f"  Saved to {output_file}")

    # --- Run Data Analysis ---
    print("\n[3/6] Running Data Science Analysis...")
    results = analyze_fno_data(df, top_n=20)

    print(f"\n  Analysis results:")
    for key, val in results.items():
        if isinstance(val, pd.DataFrame):
            print(f"    {key}: {len(val)} rows")

    # --- Print analysis summary ---
    print("\n[4/6] Analysis Summary:")
    summary_text = generate_analysis_summary_text(results)
    print(summary_text)

    # --- Write analysis to Excel ---
    print("\n[5/6] Writing analysis sheets to Excel...")
    write_analysis_to_excel(output_file, results)

    # Format Excel
    format_fno_excel(output_file)
    print("  Excel formatted and analysis sheets added.")

    # --- Generate visual report ---
    print("\n[6/6] Generating visual PDF report...")
    generate_daily_summary(output_file)
    generate_fno_visual_report(output_file)

    # --- Print detailed breakdowns ---
    print("\n" + "=" * 60)
    print("  DETAILED ANALYSIS OUTPUT")
    print("=" * 60)

    if "signals" in results and not results["signals"].empty:
        print(f"\nACTIONABLE SIGNALS ({len(results['signals'])}):")
        print(results["signals"].to_string(index=False))

    if "top_oi_gainers" in results and not results["top_oi_gainers"].empty:
        print(f"\nTOP 10 OI GAINERS:")
        print(results["top_oi_gainers"].head(10).to_string(index=False))

    if "top_oi_losers" in results and not results["top_oi_losers"].empty:
        print(f"\nTOP 10 OI LOSERS:")
        print(results["top_oi_losers"].head(10).to_string(index=False))

    if "top_iv_movers" in results and not results["top_iv_movers"].empty:
        print(f"\nTOP 10 IV MOVERS:")
        print(results["top_iv_movers"].head(10).to_string(index=False))

    if "top_price_movers" in results and not results["top_price_movers"].empty:
        print(f"\nTOP 10 PRICE MOVERS:")
        print(results["top_price_movers"].head(10).to_string(index=False))

    if "iv_anomalies" in results and not results["iv_anomalies"].empty:
        print(f"\nIV ANOMALIES ({len(results['iv_anomalies'])}):")
        print(results["iv_anomalies"].to_string(index=False))

    if "instrument_summary" in results and not results["instrument_summary"].empty:
        print(f"\nINSTRUMENT SUMMARY:")
        print(results["instrument_summary"].to_string(index=False))

    if "buildup_summary" in results and not results["buildup_summary"].empty:
        print(f"\nBUILDUP DISTRIBUTION:")
        print(results["buildup_summary"].to_string(index=False))

    # Final status
    print("\n" + "=" * 60)
    print(f"  Excel: {output_file}")
    print(f"  Reports: reports/")
    print(f"  All {len(results)} analysis modules executed successfully.")
    print("=" * 60)


if __name__ == "__main__":
    main()
