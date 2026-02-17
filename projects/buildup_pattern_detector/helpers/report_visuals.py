# helpers/report_visuals.py – Buildup Pattern Detector
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use("Agg")
import numpy as np
from datetime import datetime
import os
from helpers.notify import send_telegram


PATTERN_COLORS = {
    "Long Buildup": "#00AA00",
    "Short Buildup": "#CC0000",
    "Long Unwinding": "#FF8800",
    "Short Covering": "#0066CC",
}


def generate_visual_report(file_path):
    """
    Creates buildup pattern visual report with:
    1. Daily pattern distribution stacked bar chart
    2. Sector-wise buildup heatmap
    Exports as PDF and sends to Telegram.
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        report_dir = "reports"
        os.makedirs(report_dir, exist_ok=True)

        fig, axes = plt.subplots(2, 1, figsize=(12, 10))

        # Chart 1: Daily pattern distribution
        try:
            summary_df = pd.read_excel(file_path, sheet_name="Daily_Summary")
            if not summary_df.empty:
                summary_df["Date"] = pd.to_datetime(summary_df["Date"])
                x = range(len(summary_df))
                bottom = np.zeros(len(summary_df))

                for pattern, color in PATTERN_COLORS.items():
                    if pattern in summary_df.columns:
                        values = summary_df[pattern].fillna(0).values
                        axes[0].bar(x, values, bottom=bottom, label=pattern,
                                    color=color, alpha=0.85)
                        bottom += values

                axes[0].set_title("Daily Buildup Pattern Distribution")
                axes[0].set_xlabel("Date")
                axes[0].set_ylabel("Signal Count")
                axes[0].set_xticks(list(x))
                axes[0].set_xticklabels(
                    summary_df["Date"].dt.strftime("%m-%d"),
                    rotation=45, fontsize=8
                )
                axes[0].legend(loc="upper left")
                axes[0].grid(True, alpha=0.3)
        except Exception:
            axes[0].text(0.5, 0.5, "No daily summary data", ha="center", va="center")

        # Chart 2: Sector buildup heatmap
        try:
            sector_df = pd.read_excel(file_path, sheet_name="Sector_Buildup")
            if not sector_df.empty:
                sectors = sector_df["Sector"].values
                patterns = [c for c in sector_df.columns if c != "Sector"]
                data = sector_df[patterns].values.astype(float)

                im = axes[1].imshow(data, cmap="RdYlGn", aspect="auto")
                axes[1].set_xticks(range(len(patterns)))
                axes[1].set_xticklabels(patterns, rotation=30, fontsize=8, ha="right")
                axes[1].set_yticks(range(len(sectors)))
                axes[1].set_yticklabels(sectors, fontsize=9)
                axes[1].set_title(f"Sector Buildup Heatmap ({today})")

                # Add value annotations
                for i in range(len(sectors)):
                    for j in range(len(patterns)):
                        val = int(data[i][j])
                        if val > 0:
                            axes[1].text(j, i, str(val), ha="center", va="center",
                                         fontsize=10, fontweight="bold")

                plt.colorbar(im, ax=axes[1], shrink=0.8)
        except Exception:
            axes[1].text(0.5, 0.5, "No sector data available", ha="center", va="center")

        plt.tight_layout()
        pdf_path = os.path.join(report_dir, f"Buildup_Pattern_Report_{today}.pdf")
        plt.savefig(pdf_path)
        plt.close()

        send_telegram(f"Buildup Pattern visual report generated for {today}")
        send_telegram_file(pdf_path)

    except Exception as e:
        send_telegram(f"Visual report failed: {e}")


def send_telegram_file(file_path):
    """Send a file to Telegram."""
    import requests
    from dotenv import load_dotenv
    load_dotenv()
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram file credentials missing")
        return
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    with open(file_path, "rb") as f:
        requests.post(url, data={"chat_id": chat_id}, files={"document": f})
