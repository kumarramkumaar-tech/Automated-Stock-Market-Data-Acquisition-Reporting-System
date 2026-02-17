# dashboard.py – Real-time Option Triggers Dashboard
#
# Usage:
#   python dashboard.py              → starts on http://localhost:5000
#   python dashboard.py --port 8080  → starts on http://localhost:8080
#
# Features:
#   - Real-time stock picks with full Columns A-N analysis
#   - Auto-refresh every 60 seconds (configurable)
#   - Downloadable Excel from dashboard
#   - Signal gauges (Bullish/Bearish/Mixed)
#   - IV Percentile color bars
#   - OI Strike visualization
#   - Buildup pattern tracking
#   - Daily summary & pick history

import json
import os
import sys
import logging
from datetime import datetime, date

import pandas as pd
from flask import Flask, render_template, jsonify, send_file, request

# ── Setup ────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

with open(CONFIG_PATH) as f:
    cfg = json.load(f)

OUTPUT_FILE = os.path.join(BASE_DIR, cfg.get("output_file", "output/Option_Triggers_Analysis.xlsx"))
WATCHLIST_FILE = os.path.join(BASE_DIR, cfg.get("watchlist", {}).get("local_file", "watchlist/WBRam_Watchlist.xlsx"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "dashboard_templates"))

# ── Data Loading Helpers ─────────────────────────────────────

def _safe_read_sheet(file_path, sheet_name):
    """Read an Excel sheet safely, returning empty DataFrame on error."""
    if not os.path.exists(file_path):
        return pd.DataFrame()
    try:
        return pd.read_excel(file_path, sheet_name=sheet_name)
    except Exception:
        return pd.DataFrame()


def _df_to_records(df):
    """Convert DataFrame to list of dicts, handling NaN."""
    if df.empty:
        return []
    return json.loads(df.fillna("").to_json(orient="records"))


def _get_market_status():
    """Return current market hours status."""
    mh = cfg.get("market_hours", {})
    extended_until = mh.get("extended_until", "")
    today = date.today()

    if extended_until:
        try:
            exp = datetime.strptime(extended_until, "%Y-%m-%d").date()
            if today <= exp:
                start, end = mh.get("start", "07:00"), mh.get("end", "21:00")
                mode = "EXTENDED"
            else:
                start, end = mh.get("normal_start", "08:30"), mh.get("normal_end", "16:15")
                mode = "NORMAL"
        except ValueError:
            start, end = mh.get("start", "08:30"), mh.get("end", "16:15")
            mode = "NORMAL"
    else:
        start, end = mh.get("start", "08:30"), mh.get("end", "16:15")
        mode = "NORMAL"

    now = datetime.now()
    sh, sm = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))
    market_open = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    market_close = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    is_open = market_open <= now <= market_close

    return {
        "is_open": is_open,
        "mode": mode,
        "start": start,
        "end": end,
        "extended_until": extended_until,
        "current_time": now.strftime("%H:%M:%S"),
    }


def _compute_signal_summary(picks):
    """Count bullish/bearish/mixed signals across all picks."""
    bullish = 0
    bearish = 0
    mixed = 0
    for p in picks:
        verdict = str(p.get("Overall_Verdict", "")).upper()
        if "BULLISH" in verdict:
            bullish += 1
        elif "BEARISH" in verdict:
            bearish += 1
        else:
            mixed += 1
    total = len(picks)
    return {"bullish": bullish, "bearish": bearish, "mixed": mixed, "total": total}


# ── API Routes ───────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the main dashboard page."""
    return render_template("dashboard.html")


@app.route("/api/status")
def api_status():
    """System status: market hours, last update, file info."""
    market = _get_market_status()
    file_exists = os.path.exists(OUTPUT_FILE)
    last_modified = ""
    if file_exists:
        ts = os.path.getmtime(OUTPUT_FILE)
        last_modified = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    return jsonify({
        "market": market,
        "output_file": OUTPUT_FILE,
        "file_exists": file_exists,
        "last_modified": last_modified,
        "interval_minutes": cfg.get("fetch_interval_minutes", 40),
    })


@app.route("/api/picks")
def api_picks():
    """Current stock picks with full analysis."""
    df = _safe_read_sheet(OUTPUT_FILE, "Stock_Picks")
    picks = _df_to_records(df)
    summary = _compute_signal_summary(picks)
    return jsonify({"picks": picks, "summary": summary, "count": len(picks)})


@app.route("/api/triggers")
def api_triggers():
    """Raw triggers data (latest scrape)."""
    df = _safe_read_sheet(OUTPUT_FILE, "Triggers_Raw")
    # Return last 50 rows (most recent)
    if len(df) > 50:
        df = df.tail(50)
    return jsonify({"triggers": _df_to_records(df), "count": len(df)})


@app.route("/api/history")
def api_history():
    """Pick history across all cycles."""
    df = _safe_read_sheet(OUTPUT_FILE, "Pick_History")
    return jsonify({"history": _df_to_records(df), "count": len(df)})


@app.route("/api/daily-summary")
def api_daily_summary():
    """Daily summary stats."""
    df = _safe_read_sheet(OUTPUT_FILE, "Daily_Summary")
    return jsonify({"summary": _df_to_records(df), "count": len(df)})


@app.route("/api/watchlist")
def api_watchlist():
    """WBRam watchlist symbols."""
    if not os.path.exists(WATCHLIST_FILE):
        return jsonify({"symbols": [], "count": 0})
    try:
        df = pd.read_excel(WATCHLIST_FILE)
        first_col = df.columns[0]
        symbols = df[first_col].dropna().astype(str).str.strip().tolist()
        return jsonify({"symbols": symbols, "count": len(symbols)})
    except Exception as e:
        return jsonify({"symbols": [], "count": 0, "error": str(e)})


@app.route("/api/download")
def api_download():
    """Download the Excel analysis file."""
    if not os.path.exists(OUTPUT_FILE):
        return jsonify({"error": "No analysis file found yet. Run a cycle first."}), 404
    return send_file(
        OUTPUT_FILE,
        as_attachment=True,
        download_name=f"Option_Triggers_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
    )


# ── Main ─────────────────────────────────────────────────────

if __name__ == "__main__":
    port = 5000
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    print("=" * 60)
    print("  OPTION TRIGGERS DASHBOARD")
    print(f"  http://localhost:{port}")
    print("=" * 60)
    print()

    app.run(host="0.0.0.0", port=port, debug=False)
