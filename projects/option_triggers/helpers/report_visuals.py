# helpers/report_visuals.py – Option Triggers Visual Reports
#
# Generates multi-panel PDF reports for each stock pick showing:
#   - Tool-wise signal dashboard
#   - IVP gauge
#   - OI distribution
#   - Overall verdict card

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from datetime import datetime
import os
import logging

from helpers.notify import send_telegram, send_telegram_file

logger = logging.getLogger(__name__)

TOOL_COLORS = {
    "IV_Signal": "#27AE60",
    "OI_Trend": "#F39C12",
    "PCR_Signal": "#E74C3C",
    "BU_Signal": "#8E44AD",
    "FUT_Signal": "#3498DB",
    "MP_Signal": "#1ABC9C",
}


def generate_stock_report(pick_data, report_dir="reports"):
    """
    Generate a single-stock analysis PDF with all tool data.
    """
    os.makedirs(report_dir, exist_ok=True)

    symbol = pick_data.get("Symbol", "UNKNOWN")
    today = datetime.now().strftime("%Y-%m-%d_%H%M")

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle(
        f"Stock Analysis: {symbol} | {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        fontsize=16, fontweight="bold", y=0.98
    )

    # ---- Panel 1: Signal Dashboard (top-left) ----
    ax = axes[0][0]
    signals = {}
    for key, color in TOOL_COLORS.items():
        val = pick_data.get(key, "N/A")
        if val and val != "N/A":
            signals[key.replace("_Signal", "").replace("_Trend", "")] = val

    if signals:
        labels = list(signals.keys())
        colors_list = []
        for label, signal in signals.items():
            sig_upper = str(signal).upper()
            if "BULLISH" in sig_upper or "BUY" in sig_upper or "CHEAP" in sig_upper:
                colors_list.append("#27AE60")
            elif "BEARISH" in sig_upper or "SELL" in sig_upper or "EXPENSIVE" in sig_upper:
                colors_list.append("#E74C3C")
            else:
                colors_list.append("#F39C12")

        y_pos = range(len(labels))
        bars = ax.barh(y_pos, [1] * len(labels), color=colors_list, alpha=0.8, height=0.6)
        ax.set_yticks(list(y_pos))
        ax.set_yticklabels(labels, fontsize=11, fontweight="bold")
        ax.set_xlim(0, 2)
        ax.set_xticks([])

        for i, (label, signal) in enumerate(signals.items()):
            ax.text(0.5, i, str(signal), ha="center", va="center",
                    fontsize=9, fontweight="bold", color="white")
    else:
        ax.text(0.5, 0.5, "No signal data", ha="center", va="center", fontsize=14)

    ax.set_title("Tool Signal Dashboard", fontsize=13, fontweight="bold", pad=10)

    # ---- Panel 2: IVP Gauge (top-right) ----
    ax = axes[0][1]
    ivp_str = pick_data.get("IVP", "")
    ivp_status = pick_data.get("IVP_Status", "N/A")
    iv_signal = pick_data.get("IV_Signal", "N/A")
    iv_val = pick_data.get("IV", "N/A")
    hv_val = pick_data.get("HV", "N/A")
    iv_vs_hv = pick_data.get("IV_vs_HV", "N/A")

    try:
        ivp_val = float(str(ivp_str).replace("%", "").strip())
    except (ValueError, TypeError):
        ivp_val = None

    if ivp_val is not None:
        # Draw a semi-circular gauge
        theta = np.linspace(0, np.pi, 100)
        ax.plot(np.cos(theta), np.sin(theta), color="gray", linewidth=3)

        # Color sections
        sections = [(0, 20, "#27AE60"), (20, 40, "#82E0AA"), (40, 60, "#F7DC6F"),
                     (60, 80, "#F0B27A"), (80, 100, "#E74C3C")]
        for start, end, color in sections:
            t_start = np.pi * (1 - start / 100)
            t_end = np.pi * (1 - end / 100)
            t = np.linspace(t_start, t_end, 20)
            ax.fill_between(np.cos(t), 0, np.sin(t), alpha=0.3, color=color)

        # Needle
        needle_angle = np.pi * (1 - ivp_val / 100)
        ax.plot([0, 0.8 * np.cos(needle_angle)], [0, 0.8 * np.sin(needle_angle)],
                color="black", linewidth=3)
        ax.plot(0, 0, "ko", markersize=8)

        ax.set_xlim(-1.3, 1.3)
        ax.set_ylim(-0.3, 1.3)
        ax.set_aspect("equal")

        ax.text(0, -0.15, f"IVP: {ivp_val:.1f}% ({ivp_status})",
                ha="center", fontsize=13, fontweight="bold")
        ax.text(0, -0.28, f"IV: {iv_val} | HV: {hv_val} | {iv_vs_hv}",
                ha="center", fontsize=10, color="gray")
    else:
        ax.text(0.5, 0.5, f"IVP: {ivp_str or 'N/A'}\n{ivp_status}",
                ha="center", va="center", fontsize=14)

    ax.set_title("IV Percentile (IVP)", fontsize=13, fontweight="bold", pad=10)
    ax.axis("off")

    # ---- Panel 3: Key Metrics Table (bottom-left) ----
    ax = axes[1][0]
    ax.axis("off")

    metrics = [
        ("LTP", pick_data.get("OT_LTP", "N/A")),
        ("CE OI Change %", pick_data.get("OT_CE_OI_Change_Pct", "N/A")),
        ("Call-Put Diff %", pick_data.get("OT_Call_Put_Diff_Pct", "N/A")),
        ("PCR (OI)", pick_data.get("PCR_OI", "N/A")),
        ("Buildup", pick_data.get("BU_Type", "N/A")),
        ("Futures OI Chg %", pick_data.get("FUT_OI_Change_Pct", "N/A")),
        ("Max Pain", pick_data.get("MP_Strike", "N/A")),
        ("Support (PE OI)", pick_data.get("OI_Max_PE_Strike", "N/A")),
        ("Resistance (CE OI)", pick_data.get("OI_Max_CE_Strike", "N/A")),
    ]

    table_data = [[m[0], str(m[1])] for m in metrics]
    table = ax.table(
        cellText=table_data,
        colLabels=["Metric", "Value"],
        colWidths=[0.5, 0.5],
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.5)

    # Color header
    for j in range(2):
        table[0, j].set_facecolor("#3498DB")
        table[0, j].set_text_props(color="white", fontweight="bold")

    ax.set_title("Key Metrics", fontsize=13, fontweight="bold", pad=10)

    # ---- Panel 4: Overall Verdict (bottom-right) ----
    ax = axes[1][1]
    ax.axis("off")

    verdict = pick_data.get("Overall_Verdict", "N/A")
    verdict_upper = str(verdict).upper()

    if "BULLISH" in verdict_upper:
        bg_color = "#27AE60"
        emoji_text = "BULLISH"
    elif "BEARISH" in verdict_upper:
        bg_color = "#E74C3C"
        emoji_text = "BEARISH"
    else:
        bg_color = "#F39C12"
        emoji_text = "MIXED"

    rect = mpatches.FancyBboxPatch(
        (0.1, 0.2), 0.8, 0.6,
        boxstyle="round,pad=0.05",
        facecolor=bg_color, alpha=0.3, edgecolor=bg_color, linewidth=3
    )
    ax.add_patch(rect)
    ax.text(0.5, 0.6, emoji_text, ha="center", va="center",
            fontsize=24, fontweight="bold", color=bg_color)
    ax.text(0.5, 0.4, verdict, ha="center", va="center",
            fontsize=10, color="gray", wrap=True)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_title("Overall Verdict", fontsize=13, fontweight="bold", pad=10)

    plt.tight_layout(rect=[0, 0, 1, 0.96])

    pdf_path = os.path.join(report_dir, f"{symbol}_Analysis_{today}.pdf")
    plt.savefig(pdf_path, dpi=100)
    plt.close()

    return pdf_path


def generate_visual_report(file_path, report_dir="reports"):
    """
    Generate visual reports for all current stock picks.
    Reads from Stock_Picks sheet, creates PDF for each, sends to Telegram.
    """
    try:
        if not os.path.exists(file_path):
            return

        df = pd.read_excel(file_path, sheet_name="Stock_Picks")
        if df.empty:
            return

        os.makedirs(report_dir, exist_ok=True)

        for _, row in df.iterrows():
            pick_data = row.to_dict()
            symbol = pick_data.get("Symbol", "Unknown")

            try:
                pdf_path = generate_stock_report(pick_data, report_dir)
                send_telegram(f"Analysis report generated for *{symbol}*")
                send_telegram_file(pdf_path)
            except Exception as e:
                logger.error(f"Visual report failed for {symbol}: {e}")
                send_telegram(f"Visual report failed for {symbol}: {e}")

    except Exception as e:
        logger.error(f"Visual report generation failed: {e}")
        send_telegram(f"Visual report generation failed: {e}")


def generate_summary_report(file_path, report_dir="reports"):
    """
    Generate a combined summary PDF for all picks of the day.
    """
    try:
        if not os.path.exists(file_path):
            return

        df = pd.read_excel(file_path, sheet_name="Stock_Picks")
        if df.empty:
            return

        os.makedirs(report_dir, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")

        fig, ax = plt.subplots(figsize=(14, max(6, len(df) * 1.5)))
        ax.axis("off")

        # Build summary table
        cols = ["Symbol", "IVP_Status", "BU_Type", "PCR_Signal", "OI_Trend", "Overall_Verdict"]
        available_cols = [c for c in cols if c in df.columns]

        if available_cols:
            table_data = df[available_cols].fillna("N/A").values.tolist()
            headers = [c.replace("_", " ") for c in available_cols]

            table = ax.table(
                cellText=table_data,
                colLabels=headers,
                loc="center",
                cellLoc="center",
            )
            table.auto_set_font_size(False)
            table.set_fontsize(9)
            table.scale(1, 1.8)

            # Color header
            for j in range(len(headers)):
                table[0, j].set_facecolor("#2C3E50")
                table[0, j].set_text_props(color="white", fontweight="bold")

            # Color-code verdict cells
            verdict_col_idx = available_cols.index("Overall_Verdict") if "Overall_Verdict" in available_cols else None
            if verdict_col_idx is not None:
                for i in range(len(table_data)):
                    val = str(table_data[i][verdict_col_idx]).upper()
                    if "BULLISH" in val:
                        table[i + 1, verdict_col_idx].set_facecolor("#D5F5E3")
                    elif "BEARISH" in val:
                        table[i + 1, verdict_col_idx].set_facecolor("#FADBD8")

        ax.set_title(
            f"Option Triggers - Stock Picks Summary ({today})",
            fontsize=14, fontweight="bold", pad=20
        )

        plt.tight_layout()
        pdf_path = os.path.join(report_dir, f"Option_Triggers_Summary_{today}.pdf")
        plt.savefig(pdf_path, dpi=100)
        plt.close()

        send_telegram(f"Daily summary report generated for {today}")
        send_telegram_file(pdf_path)

    except Exception as e:
        logger.error(f"Summary report failed: {e}")
        send_telegram(f"Summary report failed: {e}")
