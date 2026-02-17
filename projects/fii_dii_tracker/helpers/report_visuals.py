# helpers/report_visuals.py – FII/DII Activity Tracker
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use("Agg")
from datetime import datetime
import os
from helpers.notify import send_telegram


def generate_visual_report(file_path):
    """
    Creates FII/DII visual report with:
    1. Daily FII vs DII Net Flow bar chart
    2. Cumulative flow trend line chart
    Exports as PDF and sends to Telegram.
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        report_dir = "reports"
        os.makedirs(report_dir, exist_ok=True)

        fig, axes = plt.subplots(2, 1, figsize=(12, 10))

        # Chart 1: Daily FII vs DII Net Flow
        try:
            summary_df = pd.read_excel(file_path, sheet_name="Daily_Summary")
            if not summary_df.empty:
                summary_df["Date"] = pd.to_datetime(summary_df["Date"])
                x = range(len(summary_df))
                width = 0.35

                bars1 = axes[0].bar([i - width / 2 for i in x], summary_df["FII Net"],
                                     width, label="FII Net", color="#FF6B6B")
                bars2 = axes[0].bar([i + width / 2 for i in x], summary_df["DII Net"],
                                     width, label="DII Net", color="#4CAF50")

                axes[0].axhline(y=0, color="black", linewidth=0.8)
                axes[0].set_title("Daily FII vs DII Net Flow (Cr)")
                axes[0].set_xlabel("Date")
                axes[0].set_ylabel("Net Flow (Cr)")
                axes[0].set_xticks(list(x))
                axes[0].set_xticklabels(
                    summary_df["Date"].dt.strftime("%m-%d"),
                    rotation=45, fontsize=8
                )
                axes[0].legend()
                axes[0].grid(True, alpha=0.3)
        except Exception:
            axes[0].text(0.5, 0.5, "No daily summary data", ha="center", va="center")

        # Chart 2: Cumulative Flow Trend
        try:
            cum_df = pd.read_excel(file_path, sheet_name="Cumulative_Flow")
            if not cum_df.empty:
                cum_df["Date"] = pd.to_datetime(cum_df["Date"])
                axes[1].plot(cum_df["Date"], cum_df["FII Cumulative"],
                             marker="o", label="FII Cumulative", color="#FF6B6B", linewidth=2)
                axes[1].plot(cum_df["Date"], cum_df["DII Cumulative"],
                             marker="s", label="DII Cumulative", color="#4CAF50", linewidth=2)
                axes[1].axhline(y=0, color="black", linewidth=0.8)
                axes[1].fill_between(cum_df["Date"], cum_df["FII Cumulative"],
                                     alpha=0.1, color="#FF6B6B")
                axes[1].fill_between(cum_df["Date"], cum_df["DII Cumulative"],
                                     alpha=0.1, color="#4CAF50")
                axes[1].set_title("Cumulative FII/DII Flow Trend")
                axes[1].set_xlabel("Date")
                axes[1].set_ylabel("Cumulative Flow (Cr)")
                axes[1].legend()
                axes[1].grid(True, alpha=0.3)
        except Exception:
            axes[1].text(0.5, 0.5, "No cumulative data available", ha="center", va="center")

        plt.tight_layout()
        pdf_path = os.path.join(report_dir, f"FII_DII_Report_{today}.pdf")
        plt.savefig(pdf_path)
        plt.close()

        send_telegram(f"FII/DII visual report generated for {today}")
        send_telegram_file(pdf_path)

    except Exception as e:
        send_telegram(f"Visual report failed: {e}")


def generate_weekly_report(file_path):
    """
    Creates a weekly summary report with aggregated FII/DII flows.
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        report_dir = "reports"
        os.makedirs(report_dir, exist_ok=True)

        cum_df = pd.read_excel(file_path, sheet_name="Cumulative_Flow")
        if cum_df.empty:
            return

        cum_df["Date"] = pd.to_datetime(cum_df["Date"])
        # Last 5 trading days
        weekly = cum_df.tail(5)

        fig, ax = plt.subplots(figsize=(10, 6))

        ax.bar(weekly["Date"].dt.strftime("%a %m/%d"), weekly["FII Net"],
               label="FII Net", color="#FF6B6B", alpha=0.8)
        ax.bar(weekly["Date"].dt.strftime("%a %m/%d"), weekly["DII Net"],
               bottom=weekly["FII Net"], label="DII Net", color="#4CAF50", alpha=0.8)
        ax.axhline(y=0, color="black", linewidth=0.8)
        ax.set_title("Weekly FII/DII Flow Summary")
        ax.set_ylabel("Net Flow (Cr)")
        ax.legend()
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        pdf_path = os.path.join(report_dir, f"FII_DII_Weekly_{today}.pdf")
        plt.savefig(pdf_path)
        plt.close()

        send_telegram(f"FII/DII weekly report generated for week ending {today}")
        send_telegram_file(pdf_path)

    except Exception as e:
        send_telegram(f"Weekly report failed: {e}")


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
