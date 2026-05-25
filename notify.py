"""
notify.py — ClickUp notifications for every trade event.

Creates a task in the "24/7 Trading Bot" ClickUp list for:
  - Trade executed (green)
  - Trade skipped (grey)
  - Stop loss triggered (red)
  - Research rejection (orange)
  - Daily summary
"""

import logging
import requests
from datetime import datetime, timezone

from config import CLICKUP_API_KEY, CLICKUP_LIST_ID

logger = logging.getLogger("notify")

BASE = "https://api.clickup.com/api/v2"


def _post(endpoint: str, payload: dict) -> dict:
    if not CLICKUP_API_KEY:
        logger.debug("ClickUp not configured — skipping notification")
        return {}
    try:
        resp = requests.post(
            f"{BASE}{endpoint}",
            headers={
                "Authorization": CLICKUP_API_KEY,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("ClickUp notify failed: %s", exc)
        return {}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def trade_executed(trade: dict, order: dict, research_note: str = ""):
    """Green task — trade was copied successfully."""
    symbol = trade["ticker"]
    side   = trade["side"].upper()
    value  = trade.get("value", 0)

    desc = (
        f"**Politician:** {trade.get('politician', 'Tim Moore')}\n"
        f"**Trade Date:** {trade.get('trade_date', '?')}\n"
        f"**Filed:** {trade.get('filed_date', '?')}\n"
        f"**Disclosed Value:** ${value:,.0f}\n"
        f"**Alpaca Order ID:** {order.get('id', '?')}\n"
        f"**Company:** {trade.get('company', '?')}\n"
    )
    if research_note:
        desc += f"\n**AI Research:** {research_note}\n"

    _post(f"/list/{CLICKUP_LIST_ID}/task", {
        "name":     f"✅ {side} {symbol} — Copied @ {_now()}",
        "description": desc,
        "status":   "complete",
        "priority": 2,  # high
        "tags":     ["executed", side.lower(), symbol],
    })
    logger.info("ClickUp: notified trade executed %s %s", side, symbol)


def trade_skipped(trade: dict, reason: str):
    """Grey task — trade was skipped."""
    symbol = trade.get("ticker", "?")
    side   = trade.get("side", "?").upper()

    _post(f"/list/{CLICKUP_LIST_ID}/task", {
        "name":     f"⏭️ {side} {symbol} skipped — {reason}",
        "description": (
            f"**Reason:** {reason}\n"
            f"**Politician:** {trade.get('politician', 'Tim Moore')}\n"
            f"**Trade Date:** {trade.get('trade_date', '?')}\n"
            f"**Time:** {_now()}\n"
        ),
        "status":   "to do",
        "priority": 4,  # low
        "tags":     ["skipped", reason],
    })


def stop_loss_triggered(symbol: str, pl_pct: float, pl_usd: float):
    """Red task — stop loss fired."""
    _post(f"/list/{CLICKUP_LIST_ID}/task", {
        "name":     f"🔴 STOP LOSS: {symbol} — {pl_pct:.1f}% loss",
        "description": (
            f"**Symbol:** {symbol}\n"
            f"**Loss:** {pl_pct:.1f}% (${pl_usd:,.2f})\n"
            f"**Action:** Position auto-sold at market price\n"
            f"**Time:** {_now()}\n"
        ),
        "status":   "complete",
        "priority": 1,  # urgent
        "tags":     ["stop-loss", symbol],
    })
    logger.info("ClickUp: stop loss notification sent for %s", symbol)


def research_rejected(trade: dict, reason: str):
    """Orange task — Claude rejected the trade after research."""
    symbol = trade.get("ticker", "?")
    side   = trade.get("side", "?").upper()

    _post(f"/list/{CLICKUP_LIST_ID}/task", {
        "name":     f"🧠 {side} {symbol} — Rejected by AI research",
        "description": (
            f"**Symbol:** {symbol}\n"
            f"**AI Reasoning:** {reason}\n"
            f"**Politician Trade Date:** {trade.get('trade_date', '?')}\n"
            f"**Time:** {_now()}\n"
        ),
        "status":   "to do",
        "priority": 3,  # normal
        "tags":     ["ai-rejected", symbol],
    })


def daily_summary(equity: float, cash: float, positions: list, executed_today: int, stopped: int):
    """End-of-day summary task."""
    pos_lines = "\n".join(
        f"- {p['symbol']}: {int(float(p['qty']))} shares, "
        f"P&L ${float(p.get('unrealized_pl',0)):+,.2f} "
        f"({float(p.get('unrealized_plpc',0))*100:+.1f}%)"
        for p in positions
    ) or "No open positions"

    _post(f"/list/{CLICKUP_LIST_ID}/task", {
        "name":     f"📊 Daily Summary — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "description": (
            f"**Portfolio Value:** ${equity:,.2f}\n"
            f"**Cash:** ${cash:,.2f}\n"
            f"**Trades Copied Today:** {executed_today}\n"
            f"**Stop Losses Triggered:** {stopped}\n\n"
            f"**Open Positions:**\n{pos_lines}\n\n"
            f"**Time:** {_now()}\n"
        ),
        "status":   "complete",
        "priority": 3,
        "tags":     ["daily-summary"],
    })
    logger.info("ClickUp: daily summary sent")
