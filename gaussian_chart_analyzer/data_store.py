"""
data_store.py - JSON-based persistence layer for symbol analysis history.

Stores Gaussian analysis results per symbol with timestamps,
allowing users to track analysis history over time.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from gaussian_chart_analyzer.gaussian_profile import GaussianResult


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
HISTORY_FILE = os.path.join(DATA_DIR, "gaussian_history.json")


def _ensure_data_dir():
    """Create data directory if it doesn't exist."""
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_history() -> Dict:
    """Load the full history from JSON file."""
    _ensure_data_dir()
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"symbols": {}}
    return {"symbols": {}}


def _save_history(data: Dict):
    """Save history to JSON file."""
    _ensure_data_dir()
    with open(HISTORY_FILE, 'w') as f:
        json.dump(data, f, indent=2, default=str)


def save_analysis(symbol: str, result: GaussianResult,
                  notes: str = "") -> str:
    """
    Save a Gaussian analysis result for a symbol.

    Returns:
        The analysis ID (timestamp-based)
    """
    history = _load_history()
    symbol = symbol.upper().strip()

    if symbol not in history["symbols"]:
        history["symbols"][symbol] = {"analyses": []}

    analysis_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    entry = {
        "id": analysis_id,
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "notes": notes,
        "mu": result.mu,
        "sigma": result.sigma,
        "amplitude": result.amplitude,
        "r_squared": result.r_squared,
        "skewness": result.skewness,
        "kurtosis": result.kurtosis,
        "poc_price": result.poc_price,
        "value_area_high": result.value_area_high,
        "value_area_low": result.value_area_low,
        "total_actual_volume": result.total_actual_volume,
        "total_gap_volume": result.total_gap_volume,
        "prices": result.prices,
        "actual_volumes": result.actual_volumes,
        "gaussian_volumes": result.gaussian_volumes,
        "volume_gaps": result.volume_gaps,
        "gap_percentages": result.gap_percentages,
    }

    history["symbols"][symbol]["analyses"].append(entry)
    _save_history(history)
    return analysis_id


def get_symbols() -> List[str]:
    """Get list of all symbols with saved analyses."""
    history = _load_history()
    return sorted(history["symbols"].keys())


def get_symbol_history(symbol: str) -> List[Dict]:
    """Get all analyses for a given symbol, newest first."""
    history = _load_history()
    symbol = symbol.upper().strip()
    if symbol in history["symbols"]:
        analyses = history["symbols"][symbol]["analyses"]
        return sorted(analyses, key=lambda x: x["timestamp"], reverse=True)
    return []


def get_analysis_by_id(symbol: str, analysis_id: str) -> Optional[Dict]:
    """Get a specific analysis by symbol and ID."""
    analyses = get_symbol_history(symbol)
    for a in analyses:
        if a["id"] == analysis_id:
            return a
    return None


def delete_analysis(symbol: str, analysis_id: str) -> bool:
    """Delete a specific analysis."""
    history = _load_history()
    symbol = symbol.upper().strip()
    if symbol in history["symbols"]:
        analyses = history["symbols"][symbol]["analyses"]
        history["symbols"][symbol]["analyses"] = [
            a for a in analyses if a["id"] != analysis_id
        ]
        # Remove symbol if no analyses left
        if not history["symbols"][symbol]["analyses"]:
            del history["symbols"][symbol]
        _save_history(history)
        return True
    return False


def delete_symbol(symbol: str) -> bool:
    """Delete all analyses for a symbol."""
    history = _load_history()
    symbol = symbol.upper().strip()
    if symbol in history["symbols"]:
        del history["symbols"][symbol]
        _save_history(history)
        return True
    return False


def get_all_latest_analyses() -> List[Dict]:
    """Get the most recent analysis for every symbol (for dashboard overview)."""
    history = _load_history()
    latest = []
    for symbol, data in history["symbols"].items():
        if data["analyses"]:
            # Sort by timestamp and get the latest
            sorted_analyses = sorted(
                data["analyses"], key=lambda x: x["timestamp"], reverse=True
            )
            entry = sorted_analyses[0].copy()
            entry["total_analyses"] = len(data["analyses"])
            latest.append(entry)
    return sorted(latest, key=lambda x: x["symbol"])
