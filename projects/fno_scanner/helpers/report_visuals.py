"""Visual report generation for FNO Scanner."""
import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime
from helpers.notify import send_telegram, send_telegram_file


def generate_fno_visual_report(file_path):
    """
    Generate visual PDF report from FNO Scanner data:
    - Buildup distribution pie chart
    - Top OI movers bar chart
    - IV change distribution histogram
    - Price vs OI scatter plot
    """
    try:
        df = pd.read_excel(file_path, sheet_name="FNO_Data")
        if df.empty:
            return

        numeric_cols = ["Price Change %", "OI Change %", "IV Change %"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.suptitle(
            f"FNO Scanner Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            fontsize=14, fontweight="bold"
        )

        # --- 1. Buildup Distribution Pie Chart ---
        ax1 = axes[0, 0]
        if "Buildup Classification" in df.columns:
            buildup_counts = df["Buildup Classification"].value_counts()
            colors = {
                "Long Buildup": "#2ecc71",
                "Short Buildup": "#e74c3c",
                "Long Unwinding": "#f39c12",
                "Short Covering": "#3498db",
                "Neutral": "#95a5a6",
                "Unknown": "#bdc3c7",
            }
            pie_colors = [colors.get(x, "#95a5a6") for x in buildup_counts.index]
            ax1.pie(buildup_counts.values, labels=buildup_counts.index,
                    autopct='%1.1f%%', colors=pie_colors, startangle=90)
            ax1.set_title("Buildup Distribution")
        else:
            ax1.text(0.5, 0.5, "No buildup data", ha='center', va='center')
            ax1.set_title("Buildup Distribution")

        # --- 2. Top OI Movers Bar Chart ---
        ax2 = axes[0, 1]
        if "OI Change %" in df.columns and "Symbol" in df.columns:
            top_oi = df.nlargest(10, "OI Change %")[["Symbol", "OI Change %"]]
            colors_bar = ["#2ecc71" if v > 0 else "#e74c3c"
                          for v in top_oi["OI Change %"]]
            ax2.barh(top_oi["Symbol"], top_oi["OI Change %"], color=colors_bar)
            ax2.set_xlabel("OI Change %")
            ax2.set_title("Top 10 OI Gainers")
            ax2.invert_yaxis()
        else:
            ax2.text(0.5, 0.5, "No OI data", ha='center', va='center')
            ax2.set_title("Top 10 OI Gainers")

        # --- 3. IV Change Distribution Histogram ---
        ax3 = axes[1, 0]
        if "IV Change %" in df.columns:
            iv_data = df["IV Change %"].dropna()
            if not iv_data.empty:
                ax3.hist(iv_data, bins=30, color="#9b59b6", edgecolor="black",
                         alpha=0.7)
                ax3.axvline(iv_data.mean(), color="red", linestyle="--",
                            label=f"Mean: {iv_data.mean():.2f}%")
                ax3.legend()
            ax3.set_xlabel("IV Change %")
            ax3.set_ylabel("Frequency")
            ax3.set_title("IV Change Distribution")
        else:
            ax3.text(0.5, 0.5, "No IV data", ha='center', va='center')
            ax3.set_title("IV Change Distribution")

        # --- 4. Price Change vs OI Change Scatter ---
        ax4 = axes[1, 1]
        if "Price Change %" in df.columns and "OI Change %" in df.columns:
            pc = df["Price Change %"].dropna()
            oc = df["OI Change %"].dropna()
            common_idx = pc.index.intersection(oc.index)
            if len(common_idx) > 0:
                ax4.scatter(pc[common_idx], oc[common_idx],
                            alpha=0.5, c="#3498db", s=20)
                ax4.axhline(0, color="gray", linestyle="--", linewidth=0.5)
                ax4.axvline(0, color="gray", linestyle="--", linewidth=0.5)

                # Quadrant labels
                ax4.text(0.95, 0.95, "Long Buildup", transform=ax4.transAxes,
                         ha='right', va='top', fontsize=8, color='green')
                ax4.text(0.05, 0.95, "Short Buildup", transform=ax4.transAxes,
                         ha='left', va='top', fontsize=8, color='red')
                ax4.text(0.05, 0.05, "Long Unwinding", transform=ax4.transAxes,
                         ha='left', va='bottom', fontsize=8, color='orange')
                ax4.text(0.95, 0.05, "Short Covering", transform=ax4.transAxes,
                         ha='right', va='bottom', fontsize=8, color='blue')

            ax4.set_xlabel("Price Change %")
            ax4.set_ylabel("OI Change %")
            ax4.set_title("Price vs OI Change (Buildup Map)")
        else:
            ax4.text(0.5, 0.5, "No price/OI data", ha='center', va='center')
            ax4.set_title("Price vs OI Change")

        plt.tight_layout()

        # Save PDF
        today = datetime.now().strftime("%Y-%m-%d")
        report_dir = "reports"
        os.makedirs(report_dir, exist_ok=True)
        pdf_path = os.path.join(report_dir, f"FNO_Scanner_Report_{today}.pdf")
        plt.savefig(pdf_path, dpi=150)
        plt.close()

        send_telegram(f"FNO Scanner visual report generated for {today}")
        send_telegram_file(pdf_path)

    except Exception as e:
        send_telegram(f"FNO visual report failed: {e}")


def generate_daily_summary(file_path):
    """
    Create a Daily_Summary sheet with per-day aggregate stats.
    """
    if not os.path.exists(file_path):
        return

    try:
        df = pd.read_excel(file_path, sheet_name="FNO_Data")
        if df.empty or "Fetched At" not in df.columns:
            return

        numeric_cols = ["Price Change %", "OI Change %", "IV Change %"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df["Date"] = pd.to_datetime(df["Fetched At"]).dt.date

        agg_dict = {"Date": "first"}
        if "Price Change %" in df.columns:
            agg_dict["Price Change %"] = ["mean", "max", "min"]
        if "OI Change %" in df.columns:
            agg_dict["OI Change %"] = ["mean", "max", "min"]
        if "IV Change %" in df.columns:
            agg_dict["IV Change %"] = ["mean", "max", "min"]

        summary = df.groupby("Date").agg({
            col: funcs for col, funcs in {
                "Price Change %": ["count", "mean", "max", "min"],
                "OI Change %": ["mean", "max", "min"],
                "IV Change %": ["mean", "max", "min"],
            }.items() if col in df.columns
        })

        summary.columns = [f"{c[0]} ({c[1]})" for c in summary.columns]
        summary = summary.round(2).reset_index()

        with pd.ExcelWriter(file_path, engine="openpyxl", mode="a",
                            if_sheet_exists="replace") as writer:
            summary.to_excel(writer, sheet_name="Daily_Summary", index=False)

        # Telegram notification for today's summary
        today = datetime.now().date()
        today_row = summary[summary["Date"] == today]
        if not today_row.empty:
            r = today_row.iloc[0]
            cols_info = []
            for col in summary.columns:
                if col != "Date":
                    cols_info.append(f"  {col}: {r[col]}")
            msg = (
                f"FNO Scanner Daily Summary ({today})\n"
                + "\n".join(cols_info)
                + "\nLogged in Excel."
            )
            send_telegram(msg)

    except Exception as e:
        send_telegram(f"Error updating FNO daily summary: {e}")
