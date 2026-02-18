"""
Data Science Analysis module for FNO Scanner.

Analyzes each instrument's FNO data like a data science analyst:
- OI buildup classification (Long/Short/Long Unwinding/Short Covering)
- IV analysis and anomaly detection
- Price-OI correlation
- Top movers identification
- Per-instrument summary statistics
- Trend signals
"""
import pandas as pd
import numpy as np
from datetime import datetime
from helpers.notify import send_telegram


def classify_buildup(row):
    """
    Classify OI buildup based on Price Change and OI Change:
    - Long Buildup:       Price UP   + OI UP
    - Short Buildup:      Price DOWN + OI UP
    - Long Unwinding:     Price DOWN + OI DOWN
    - Short Covering:     Price UP   + OI DOWN
    """
    price_chg = row.get("Price Change %", 0)
    oi_chg = row.get("OI Change %", 0)

    try:
        price_chg = float(price_chg)
        oi_chg = float(oi_chg)
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
    else:
        return "Neutral"


def analyze_fno_data(df, top_n=20):
    """
    Perform comprehensive FNO data analysis.

    Returns a dict of DataFrames:
    - 'buildup_summary': Buildup classification counts per instrument
    - 'top_oi_gainers': Top N by OI Change %
    - 'top_oi_losers': Bottom N by OI Change %
    - 'top_iv_movers': Top N by IV Change %
    - 'top_price_movers': Top N by Price Change %
    - 'instrument_summary': Per-instrument aggregated stats
    - 'iv_anomalies': Instruments with unusually high IV changes
    - 'signals': Actionable signals based on combined analysis
    """
    if df.empty:
        return {}

    df = df.copy()

    # Ensure numeric columns
    numeric_cols = ["Price Change %", "OI Change %", "IV Change %",
                    "Price Change", "OI Change", "IV Change", "LTP", "OI", "Volume"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Classify buildup
    df["Buildup Classification"] = df.apply(classify_buildup, axis=1)

    results = {}

    # --- 1. Buildup Summary ---
    if "Symbol" in df.columns:
        buildup_summary = df.groupby(["Symbol", "Buildup Classification"]).size().unstack(
            fill_value=0
        ).reset_index()
        results["buildup_summary"] = buildup_summary

    # --- 2. Top OI Gainers ---
    if "OI Change %" in df.columns:
        top_oi_gainers = df.nlargest(top_n, "OI Change %")[
            _pick_cols(df, ["Symbol", "Expiry", "Strike", "Type", "LTP",
                            "OI", "OI Change", "OI Change %",
                            "Buildup Classification"])
        ].reset_index(drop=True)
        results["top_oi_gainers"] = top_oi_gainers

        # Top OI Losers
        top_oi_losers = df.nsmallest(top_n, "OI Change %")[
            _pick_cols(df, ["Symbol", "Expiry", "Strike", "Type", "LTP",
                            "OI", "OI Change", "OI Change %",
                            "Buildup Classification"])
        ].reset_index(drop=True)
        results["top_oi_losers"] = top_oi_losers

    # --- 3. Top IV Movers ---
    if "IV Change %" in df.columns:
        top_iv_movers = df.reindex(
            df["IV Change %"].abs().sort_values(ascending=False).index
        ).head(top_n)[
            _pick_cols(df, ["Symbol", "Expiry", "Strike", "Type", "LTP",
                            "IV", "IV Change", "IV Change %",
                            "Buildup Classification"])
        ].reset_index(drop=True)
        results["top_iv_movers"] = top_iv_movers

    # --- 4. Top Price Movers ---
    if "Price Change %" in df.columns:
        top_price_movers = df.reindex(
            df["Price Change %"].abs().sort_values(ascending=False).index
        ).head(top_n)[
            _pick_cols(df, ["Symbol", "Expiry", "Strike", "Type", "LTP",
                            "Price Change", "Price Change %",
                            "OI Change %", "Buildup Classification"])
        ].reset_index(drop=True)
        results["top_price_movers"] = top_price_movers

    # --- 5. Per-Instrument Summary ---
    if "Symbol" in df.columns:
        agg_dict = {}
        if "Price Change %" in df.columns:
            agg_dict["Price Change %"] = ["mean", "max", "min"]
        if "OI Change %" in df.columns:
            agg_dict["OI Change %"] = ["mean", "max", "min", "sum"]
        if "IV Change %" in df.columns:
            agg_dict["IV Change %"] = ["mean", "max", "min"]
        if "Volume" in df.columns:
            agg_dict["Volume"] = "sum"

        if agg_dict:
            instrument_summary = df.groupby("Symbol").agg(agg_dict)
            instrument_summary.columns = [
                f"{col[0]} ({col[1]})" for col in instrument_summary.columns
            ]
            instrument_summary = instrument_summary.round(2).reset_index()

            # Add entry count
            counts = df.groupby("Symbol").size().reset_index(name="Contract Count")
            instrument_summary = instrument_summary.merge(counts, on="Symbol")
            results["instrument_summary"] = instrument_summary

    # --- 6. IV Anomalies (|IV Change %| > 2 std deviations from mean) ---
    if "IV Change %" in df.columns:
        iv_mean = df["IV Change %"].mean()
        iv_std = df["IV Change %"].std()
        if pd.notna(iv_std) and iv_std > 0:
            threshold = iv_mean + (2 * iv_std)
            iv_anomalies = df[df["IV Change %"].abs() > abs(threshold)][
                _pick_cols(df, ["Symbol", "Expiry", "Strike", "Type", "LTP",
                                "IV", "IV Change %", "OI Change %",
                                "Buildup Classification"])
            ].reset_index(drop=True)
            results["iv_anomalies"] = iv_anomalies

    # --- 7. Actionable Signals ---
    signals = _generate_signals(df)
    if not signals.empty:
        results["signals"] = signals

    return results


def _pick_cols(df, cols):
    """Return only columns that exist in the DataFrame."""
    return [c for c in cols if c in df.columns]


def _generate_signals(df):
    """
    Generate actionable signals based on combined analysis:
    - Strong Long Buildup: Price up >2% + OI up >5%
    - Strong Short Buildup: Price down >2% + OI up >5%
    - IV Spike with OI: IV Change >3% + OI Change >5%
    - High Volume Breakout: Top volume with price change > 2%
    """
    signals = []

    for _, row in df.iterrows():
        symbol = row.get("Symbol", "")
        expiry = row.get("Expiry", "")
        strike = row.get("Strike", "")
        opt_type = row.get("Type", "")

        try:
            price_chg = float(row.get("Price Change %", 0) or 0)
            oi_chg = float(row.get("OI Change %", 0) or 0)
            iv_chg = float(row.get("IV Change %", 0) or 0)
        except (ValueError, TypeError):
            continue

        signal_type = None
        strength = None

        # Strong Long Buildup
        if price_chg > 2 and oi_chg > 5:
            signal_type = "Strong Long Buildup"
            strength = "HIGH" if price_chg > 4 and oi_chg > 10 else "MEDIUM"

        # Strong Short Buildup
        elif price_chg < -2 and oi_chg > 5:
            signal_type = "Strong Short Buildup"
            strength = "HIGH" if price_chg < -4 and oi_chg > 10 else "MEDIUM"

        # Aggressive Short Covering
        elif price_chg > 3 and oi_chg < -5:
            signal_type = "Aggressive Short Covering"
            strength = "HIGH" if price_chg > 5 and oi_chg < -10 else "MEDIUM"

        # Aggressive Long Unwinding
        elif price_chg < -3 and oi_chg < -5:
            signal_type = "Aggressive Long Unwinding"
            strength = "HIGH" if price_chg < -5 and oi_chg < -10 else "MEDIUM"

        # IV Spike with OI surge
        elif abs(iv_chg) > 3 and abs(oi_chg) > 5:
            signal_type = "IV Spike + OI Surge"
            strength = "HIGH" if abs(iv_chg) > 5 else "MEDIUM"

        if signal_type:
            signals.append({
                "Symbol": symbol,
                "Expiry": expiry,
                "Strike": strike,
                "Type": opt_type,
                "Signal": signal_type,
                "Strength": strength,
                "Price Change %": price_chg,
                "OI Change %": oi_chg,
                "IV Change %": iv_chg,
            })

    return pd.DataFrame(signals)


def generate_analysis_summary_text(results, timestamp=None):
    """
    Generate a human-readable text summary for Telegram notification.
    """
    if not results:
        return "No FNO data to analyze."

    ts = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"FNO Scanner Analysis ({ts})", "=" * 40]

    # Signals
    if "signals" in results and not results["signals"].empty:
        sig_df = results["signals"]
        lines.append(f"\nACTIONABLE SIGNALS ({len(sig_df)} found):")
        high_signals = sig_df[sig_df["Strength"] == "HIGH"]
        if not high_signals.empty:
            lines.append("  HIGH PRIORITY:")
            for _, r in high_signals.head(10).iterrows():
                lines.append(
                    f"  {r['Symbol']} {r.get('Strike', '')} {r.get('Type', '')} "
                    f"| {r['Signal']} | Price: {r['Price Change %']:+.1f}% "
                    f"OI: {r['OI Change %']:+.1f}% IV: {r['IV Change %']:+.1f}%"
                )

    # Top OI Gainers
    if "top_oi_gainers" in results and not results["top_oi_gainers"].empty:
        lines.append(f"\nTOP OI GAINERS:")
        for _, r in results["top_oi_gainers"].head(5).iterrows():
            sym = r.get("Symbol", "")
            oi_pct = r.get("OI Change %", 0)
            buildup = r.get("Buildup Classification", "")
            lines.append(f"  {sym}: OI Change {oi_pct:+.1f}% [{buildup}]")

    # IV Anomalies
    if "iv_anomalies" in results and not results["iv_anomalies"].empty:
        lines.append(f"\nIV ANOMALIES ({len(results['iv_anomalies'])} detected):")
        for _, r in results["iv_anomalies"].head(5).iterrows():
            sym = r.get("Symbol", "")
            iv_pct = r.get("IV Change %", 0)
            lines.append(f"  {sym}: IV Change {iv_pct:+.1f}%")

    # Buildup distribution
    if "buildup_summary" in results and not results["buildup_summary"].empty:
        lines.append("\nBUILDUP DISTRIBUTION:")
        bs = results["buildup_summary"]
        for col in bs.columns:
            if col != "Symbol":
                total = bs[col].sum()
                if total > 0:
                    lines.append(f"  {col}: {total}")

    return "\n".join(lines)


def write_analysis_to_excel(file_path, results, sheet_prefix=""):
    """Write analysis DataFrames to separate sheets in the Excel file."""
    if not results:
        return

    try:
        with pd.ExcelWriter(file_path, engine="openpyxl", mode="a",
                            if_sheet_exists="replace") as writer:
            sheet_map = {
                "signals": "Signals",
                "top_oi_gainers": "Top_OI_Gainers",
                "top_oi_losers": "Top_OI_Losers",
                "top_iv_movers": "Top_IV_Movers",
                "top_price_movers": "Top_Price_Movers",
                "instrument_summary": "Instrument_Summary",
                "iv_anomalies": "IV_Anomalies",
                "buildup_summary": "Buildup_Summary",
            }
            for key, sheet_name in sheet_map.items():
                if key in results and not results[key].empty:
                    full_sheet = f"{sheet_prefix}{sheet_name}" if sheet_prefix else sheet_name
                    results[key].to_excel(writer, sheet_name=full_sheet[:31], index=False)

    except Exception as e:
        print(f"Failed to write analysis to Excel: {e}")
