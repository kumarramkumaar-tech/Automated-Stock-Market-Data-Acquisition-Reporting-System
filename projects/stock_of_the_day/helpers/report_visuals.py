# helpers/report_visuals.py – Stock of the Day
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
import os
from helpers.notify import send_telegram


def generate_visual_report(file_path):
    """
    Creates a visual report with:
    1. Daily performance chart (Avg/Max/Min change)
    2. Top stocks bar chart
    Exports as PDF and sends to Telegram.
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        report_dir = "reports"
        os.makedirs(report_dir, exist_ok=True)

        fig, axes = plt.subplots(2, 1, figsize=(10, 10))

        # Chart 1: Daily summary trend
        try:
            summary_df = pd.read_excel(file_path, sheet_name="Daily_Summary")
            if not summary_df.empty:
                axes[0].plot(summary_df["Date"], summary_df["Avg Change %"], marker="o", label="Avg Change %")
                axes[0].plot(summary_df["Date"], summary_df["Max Change %"], "--", label="Max Change %")
                axes[0].plot(summary_df["Date"], summary_df["Min Change %"], "--", label="Min Change %")
                axes[0].set_title("Daily Performance Trend")
                axes[0].set_xlabel("Date")
                axes[0].set_ylabel("Change %")
                axes[0].legend()
                axes[0].grid(True)
        except Exception:
            axes[0].text(0.5, 0.5, "No daily summary data", ha="center", va="center")

        # Chart 2: Today's top stock rankings
        try:
            ranking_df = pd.read_excel(file_path, sheet_name="Stock_Rankings")
            if not ranking_df.empty:
                colors = ["gold", "silver", "#cd7f32", "#4CAF50", "#2196F3"]
                bars = axes[1].barh(
                    ranking_df["Symbol"][::-1],
                    ranking_df["Composite_Score"][::-1],
                    color=colors[:len(ranking_df)][::-1]
                )
                axes[1].set_title(f"Stock of the Day Rankings ({today})")
                axes[1].set_xlabel("Composite Score")
                for bar, score in zip(bars, ranking_df["Composite_Score"][::-1]):
                    axes[1].text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                                 f"{score:.1f}", va="center", fontsize=9)
        except Exception:
            axes[1].text(0.5, 0.5, "No ranking data yet", ha="center", va="center")

        plt.tight_layout()
        pdf_path = os.path.join(report_dir, f"Stock_Of_The_Day_Report_{today}.pdf")
        plt.savefig(pdf_path)
        plt.close()

        send_telegram(f"Stock of the Day visual report generated for {today}")
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
