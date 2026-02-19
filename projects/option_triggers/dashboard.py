# dashboard.py – Real-time Stock Market Dashboard
#
# Usage:
#   python dashboard.py              → starts on http://localhost:5000
#   python dashboard.py --port 8080  → starts on http://localhost:8080
#
# Features:
#   - Option Triggers: Stock picks with full Columns A-N analysis
#   - Unusual Activity: Unusual option activity data from Quantsapp
#   - FNO Scanner: Full F&O market scanner with buildup, signals, IV anomalies
#   - Auto-refresh every 10 minutes
#   - Downloadable Excel from dashboard (all modules)
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

# ── Unusual Activity Setup ───────────────────────────────────
ROOT_DIR = os.path.dirname(os.path.dirname(BASE_DIR))  # repo root
UA_CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")
ua_cfg = {}
if os.path.exists(UA_CONFIG_PATH):
    with open(UA_CONFIG_PATH) as f:
        ua_cfg = json.load(f)
UA_OUTPUT_FILE = os.path.join(ROOT_DIR, ua_cfg.get("output_file", "output/Quantsapp_Unusual_Activity.xlsx"))

# ── FNO Scanner Setup ────────────────────────────────────────
FNO_DIR = os.path.join(ROOT_DIR, "projects", "fno_scanner")
FNO_CONFIG_PATH = os.path.join(FNO_DIR, "config.json")
fno_cfg = {}
if os.path.exists(FNO_CONFIG_PATH):
    with open(FNO_CONFIG_PATH) as f:
        fno_cfg = json.load(f)
FNO_OUTPUT_FILE = os.path.join(FNO_DIR, fno_cfg.get("output_file", "output/FNO_Scanner_Data.xlsx"))

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
    """Download the Option Triggers Excel analysis file."""
    if not os.path.exists(OUTPUT_FILE):
        return jsonify({"error": "No analysis file found yet. Run a cycle first."}), 404
    return send_file(
        OUTPUT_FILE,
        as_attachment=True,
        download_name=f"Option_Triggers_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
    )


# ── Unusual Activity API Routes ──────────────────────────────

@app.route("/api/ua/status")
def api_ua_status():
    """Unusual Activity module status."""
    file_exists = os.path.exists(UA_OUTPUT_FILE)
    last_modified = ""
    if file_exists:
        ts = os.path.getmtime(UA_OUTPUT_FILE)
        last_modified = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    return jsonify({
        "file_exists": file_exists,
        "last_modified": last_modified,
        "output_file": UA_OUTPUT_FILE,
        "interval_minutes": ua_cfg.get("fetch_interval_minutes", 15),
    })


@app.route("/api/ua/data")
def api_ua_data():
    """Unusual Activity data log (last 100 rows)."""
    df = _safe_read_sheet(UA_OUTPUT_FILE, "Data_Log")
    if len(df) > 100:
        df = df.tail(100)
    records = _df_to_records(df)

    # Compute stats
    stats = {"total": len(records), "calls": 0, "puts": 0, "long_buildup": 0,
             "short_buildup": 0, "long_unwinding": 0, "short_covering": 0,
             "avg_change_pct": 0, "symbols": []}
    if records:
        for r in records:
            t = str(r.get("Type", "")).upper()
            if t == "CALL" or t == "CE":
                stats["calls"] += 1
            elif t == "PUT" or t == "PE":
                stats["puts"] += 1
            bu = str(r.get("Builtup Type", r.get("Buildup Type", ""))).upper()
            if "LONG BUILDUP" in bu or "LONG BUILD" in bu:
                stats["long_buildup"] += 1
            elif "SHORT BUILDUP" in bu or "SHORT BUILD" in bu:
                stats["short_buildup"] += 1
            elif "LONG UNWIND" in bu:
                stats["long_unwinding"] += 1
            elif "SHORT COVER" in bu:
                stats["short_covering"] += 1
        # Avg change %
        changes = []
        for r in records:
            try:
                v = float(str(r.get("Change %", "0")).replace("%", "").replace(",", ""))
                changes.append(v)
            except (ValueError, TypeError):
                pass
        if changes:
            stats["avg_change_pct"] = round(sum(changes) / len(changes), 2)
        # Unique symbols
        syms = set()
        for r in records:
            s = str(r.get("Symbol", "")).strip()
            if s:
                syms.add(s)
        stats["symbols"] = sorted(syms)

    return jsonify({"data": records, "stats": stats})


@app.route("/api/ua/summary")
def api_ua_summary():
    """Unusual Activity daily summary."""
    df = _safe_read_sheet(UA_OUTPUT_FILE, "Daily_Summary")
    return jsonify({"summary": _df_to_records(df), "count": len(df)})


@app.route("/api/ua/download")
def api_ua_download():
    """Download the Unusual Activity Excel file."""
    if not os.path.exists(UA_OUTPUT_FILE):
        return jsonify({"error": "No Unusual Activity file found yet."}), 404
    return send_file(
        UA_OUTPUT_FILE,
        as_attachment=True,
        download_name=f"Unusual_Activity_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
    )


# ── FNO Scanner API Routes ────────────────────────────────────

@app.route("/api/fno/status")
def api_fno_status():
    """FNO Scanner module status."""
    file_exists = os.path.exists(FNO_OUTPUT_FILE)
    last_modified = ""
    if file_exists:
        ts = os.path.getmtime(FNO_OUTPUT_FILE)
        last_modified = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    return jsonify({
        "file_exists": file_exists,
        "last_modified": last_modified,
        "output_file": FNO_OUTPUT_FILE,
        "interval_minutes": fno_cfg.get("fetch_interval_minutes", 30),
    })


@app.route("/api/fno/data")
def api_fno_data():
    """FNO Scanner main data (last 200 rows)."""
    df = _safe_read_sheet(FNO_OUTPUT_FILE, "FNO_Data")
    if len(df) > 200:
        df = df.tail(200)
    records = _df_to_records(df)

    # Compute stats
    stats = {"total": len(records), "long_buildup": 0, "short_buildup": 0,
             "long_unwinding": 0, "short_covering": 0, "neutral": 0,
             "avg_price_chg": 0, "avg_oi_chg": 0, "avg_iv_chg": 0, "symbols": []}
    if records:
        for r in records:
            bu = str(r.get("Buildup Classification", r.get("Buildup", ""))).upper()
            if "LONG BUILDUP" in bu:
                stats["long_buildup"] += 1
            elif "SHORT BUILDUP" in bu:
                stats["short_buildup"] += 1
            elif "LONG UNWINDING" in bu or "LONG UNWIND" in bu:
                stats["long_unwinding"] += 1
            elif "SHORT COVERING" in bu or "SHORT COVER" in bu:
                stats["short_covering"] += 1
            else:
                stats["neutral"] += 1

        # Averages
        for field, stat_key in [("Price Change %", "avg_price_chg"), ("OI Change %", "avg_oi_chg"), ("IV Change %", "avg_iv_chg")]:
            vals = []
            for r in records:
                try:
                    v = float(str(r.get(field, "0")).replace("%", "").replace(",", ""))
                    vals.append(v)
                except (ValueError, TypeError):
                    pass
            if vals:
                stats[stat_key] = round(sum(vals) / len(vals), 2)

        # Unique symbols
        syms = set()
        for r in records:
            s = str(r.get("Symbol", "")).strip()
            if s:
                syms.add(s)
        stats["symbols"] = sorted(syms)

    return jsonify({"data": records, "stats": stats})


@app.route("/api/fno/signals")
def api_fno_signals():
    """FNO Scanner actionable signals."""
    df = _safe_read_sheet(FNO_OUTPUT_FILE, "Signals")
    return jsonify({"signals": _df_to_records(df), "count": len(df)})


@app.route("/api/fno/top-movers")
def api_fno_top_movers():
    """FNO Scanner top OI/IV/Price movers."""
    oi_gainers = _safe_read_sheet(FNO_OUTPUT_FILE, "Top_OI_Gainers")
    oi_losers = _safe_read_sheet(FNO_OUTPUT_FILE, "Top_OI_Losers")
    iv_movers = _safe_read_sheet(FNO_OUTPUT_FILE, "Top_IV_Movers")
    price_movers = _safe_read_sheet(FNO_OUTPUT_FILE, "Top_Price_Movers")
    return jsonify({
        "oi_gainers": _df_to_records(oi_gainers),
        "oi_losers": _df_to_records(oi_losers),
        "iv_movers": _df_to_records(iv_movers),
        "price_movers": _df_to_records(price_movers),
    })


@app.route("/api/fno/buildup")
def api_fno_buildup():
    """FNO Scanner buildup summary."""
    df = _safe_read_sheet(FNO_OUTPUT_FILE, "Buildup_Summary")
    return jsonify({"buildup": _df_to_records(df), "count": len(df)})


@app.route("/api/fno/download")
def api_fno_download():
    """Download the FNO Scanner Excel file."""
    if not os.path.exists(FNO_OUTPUT_FILE):
        return jsonify({"error": "No FNO Scanner file found yet."}), 404
    return send_file(
        FNO_OUTPUT_FILE,
        as_attachment=True,
        download_name=f"FNO_Scanner_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
    )


# ── Main ─────────────────────────────────────────────────────

if __name__ == "__main__":
    port = 5000
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    print("=" * 60)
    print("  STOCK MARKET DASHBOARD")
    print(f"  http://localhost:{port}")
    print("  Modules: Option Triggers + Unusual Activity + FNO Scanner")
    print("=" * 60)
    print()

    app.run(host="0.0.0.0", port=port, debug=False)
