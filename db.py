"""
db.py — Simple JSON-based store to track which trades we've already copied.
Prevents duplicate orders if the bot runs multiple times.
"""
import json
import os
from datetime import datetime
from config import DB_FILE


def _load() -> dict:
    if not os.path.exists(DB_FILE):
        return {"executed": [], "skipped": [], "errors": []}
    with open(DB_FILE, "r") as f:
        return json.load(f)


def _save(data: dict):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def already_executed(trade_id: str) -> bool:
    data = _load()
    return trade_id in [t["id"] for t in data["executed"]]


def mark_executed(trade: dict, order_result: dict):
    data = _load()
    data["executed"].append({
        "id":           trade["id"],
        "ticker":       trade["ticker"],
        "side":         trade["side"],
        "trade_date":   trade["trade_date"],
        "filed_date":   trade["filed_date"],
        "politician":   trade["politician"],
        "copied_at":    datetime.utcnow().isoformat(),
        "alpaca_order": order_result,
    })
    _save(data)


def mark_skipped(trade: dict, reason: str):
    data = _load()
    data["skipped"].append({
        "id":       trade["id"],
        "ticker":   trade.get("ticker"),
        "reason":   reason,
        "skipped_at": datetime.utcnow().isoformat(),
    })
    _save(data)


def mark_error(trade: dict, error: str):
    data = _load()
    data["errors"].append({
        "id":       trade.get("id"),
        "ticker":   trade.get("ticker"),
        "error":    error,
        "at":       datetime.utcnow().isoformat(),
    })
    _save(data)


def get_summary() -> dict:
    data = _load()
    return {
        "total_executed": len(data["executed"]),
        "total_skipped":  len(data["skipped"]),
        "total_errors":   len(data["errors"]),
        "last_executed":  data["executed"][-1] if data["executed"] else None,
    }
