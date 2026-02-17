# helpers/report_visuals.py – Options Chain Analyzer
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use("Agg")
import numpy as np
from datetime import datetime
import os
from helpers.notify import send_telegram


def generate_visual_report(file_path):
    """
    Creates options chain visual report with:
    1. OI distribution heatmap (Call OI vs Put OI by strike)
    2. PCR trend over time
    Exports as PDF and sends to Telegram.
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        report_dir = "reports"
        os.makedirs(report_dir, exist_ok=True)

        fig, axes = plt.subplots(2, 1, figsize=(12, 10))

        # Chart 1: OI Distribution by Strike (latest snapshot)
        try:
            chain_df = pd.read_excel(file_path, sheet_name="Chain_Log")
            if not chain_df.empty:
                chain_df["Fetched At"] = pd.to_datetime(chain_df["Fetched At"])
                latest = chain_df[chain_df["Fetched At"] == chain_df["Fetched At"].max()]

                latest["Call OI"] = pd.to_numeric(latest.get("Call OI", pd.Series()), errors="coerce").fillna(0)
                latest["Put OI"] = pd.to_numeric(latest.get("Put OI", pd.Series()), errors="coerce").fillna(0)
                latest["Strike"] = pd.to_numeric(latest["Strike"], errors="coerce")
                latest = latest.sort_values("Strike")

                x = np.arange(len(latest))
                width = 0.35

                axes[0].barh(x - width / 2, latest["Call OI"], width, label="Call OI", color="#FF6B6B")
                axes[0].barh(x + width / 2, latest["Put OI"], width, label="Put OI", color="#4CAF50")
                axes[0].set_yticks(x)
                axes[0].set_yticklabels(latest["Strike"].astype(int), fontsize=7)
                axes[0].set_title("Options Chain - OI Distribution by Strike")
                axes[0].set_xlabel("Open Interest")
                axes[0].legend()
                axes[0].grid(True, alpha=0.3)
        except Exception:
            axes[0].text(0.5, 0.5, "No chain data available", ha="center", va="center")

        # Chart 2: PCR trend over time
        try:
            analysis_df = pd.read_excel(file_path, sheet_name="Analysis")
            if not analysis_df.empty:
                analysis_df["DateTime"] = pd.to_datetime(
                    analysis_df["Date"].astype(str) + " " + analysis_df["Time"].astype(str)
                )
                axes[1].plot(analysis_df["DateTime"], analysis_df["PCR"], marker="o",
                             color="#2196F3", linewidth=2)
                axes[1].axhline(y=1.0, color="gray", linestyle="--", alpha=0.7, label="PCR = 1 (Neutral)")
                axes[1].fill_between(analysis_df["DateTime"], analysis_df["PCR"], 1.0,
                                     where=analysis_df["PCR"] > 1, alpha=0.2, color="green", label="Bullish")
                axes[1].fill_between(analysis_df["DateTime"], analysis_df["PCR"], 1.0,
                                     where=analysis_df["PCR"] < 1, alpha=0.2, color="red", label="Bearish")
                axes[1].set_title("Put-Call Ratio (PCR) Trend")
                axes[1].set_xlabel("Time")
                axes[1].set_ylabel("PCR")
                axes[1].legend()
                axes[1].grid(True, alpha=0.3)
        except Exception:
            axes[1].text(0.5, 0.5, "No analysis data available", ha="center", va="center")

        plt.tight_layout()
        pdf_path = os.path.join(report_dir, f"Options_Chain_Report_{today}.pdf")
        plt.savefig(pdf_path)
        plt.close()

        send_telegram(f"Options Chain visual report generated for {today}")
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
