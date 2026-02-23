# helpers/report_visuals.py
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
import os
from helpers.notify import send_telegram

def generate_visual_report(file_path: str):
    """
    Reads Daily_Summary sheet, creates a simple chart,
    exports it as PDF, and sends to Telegram.
    """
    try:
        # --- Load daily summary ---
        df = pd.read_excel(file_path, sheet_name="Daily_Summary")
        if df.empty:
            return

        # --- Create chart ---
        plt.figure(figsize=(8, 5))
        plt.plot(df["Date"], df["Avg Change %"], marker="o", label="Avg Change %")
        plt.plot(df["Date"], df["Max Change %"], "--", label="Max Change %")
        plt.plot(df["Date"], df["Min Change %"], "--", label="Min Change %")
        plt.title("FNO Scanner Daily Performance")
        plt.xlabel("Date")
        plt.ylabel("Change %")
        plt.legend()
        plt.grid(True)

        # --- Save PDF ---
        today = datetime.now().strftime("%Y-%m-%d")
        report_dir = "reports"
        os.makedirs(report_dir, exist_ok=True)
        pdf_path = os.path.join(report_dir, f"FNO_Scanner_Report_{today}.pdf")
        plt.tight_layout()
        plt.savefig(pdf_path)
        plt.close()

        send_telegram(f"📊 Daily visual report generated for {today}")
        send_telegram_file(pdf_path)

    except Exception as e:
        send_telegram(f"⚠️ Visual report failed: {e}")


def send_telegram_file(file_path):
    """Send a file (PDF/image) to Telegram."""
    import requests, os
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
