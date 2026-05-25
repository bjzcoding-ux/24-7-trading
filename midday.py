"""
midday.py — 12:00 PM ET midday scan.

Runs at noon every market day. Does NOT copy new trades —
that's the hourly bot's job. Instead focuses on:

  1. Stop-loss check on all open positions
  2. Flag any position that's approaching the 8% stop (warn at 5%)
  3. Check cash reserve health
  4. Send ClickUp midday health report
"""

import logging
from datetime import datetime, timezone

import notify
import trader

logger = logging.getLogger("midday")


def run_midday_scan():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    logger.info("=" * 60)
    logger.info("MIDDAY SCAN — %s", now)

    # 1. Stop-loss check
    logger.info("--- Stop-loss scan ---")
    stopped = trader.check_stop_losses()
    for sym in stopped:
        notify.stop_loss_triggered(sym, 0, 0)

    # 2. Check positions approaching stop (warn at -5%)
    warnings = []
    try:
        positions = trader.get_positions()
        for p in positions:
            pl_pct = float(p.get("unrealized_plpc", 0)) * 100
            symbol = p["symbol"]
            pl_usd = float(p.get("unrealized_pl", 0))

            if -8 < pl_pct <= -5:
                logger.warning(
                    "⚠️  %s approaching stop loss: %.1f%% ($%.2f)",
                    symbol, pl_pct, pl_usd,
                )
                warnings.append((symbol, pl_pct, pl_usd))
    except Exception as exc:
        logger.warning("Could not check positions: %s", exc)
        positions = []

    # 3. Cash reserve health
    try:
        acct      = trader.get_account()
        equity    = float(acct.get("portfolio_value", 0))
        cash      = float(acct.get("cash", 0))
        cash_pct  = (cash / equity * 100) if equity else 0
        buying_pw = float(acct.get("buying_power", 0))
    except Exception:
        equity = cash = cash_pct = buying_pw = 0

    # 4. Build ClickUp midday report
    warning_text = ""
    if warnings:
        warning_text = "\n".join(
            f"- {sym}: {pct:.1f}% (${usd:,.2f}) — approaching stop"
            for sym, pct, usd in warnings
        )
    else:
        warning_text = "All positions healthy"

    stopped_text = ", ".join(stopped) if stopped else "None"

    pos_lines = ""
    try:
        for p in positions:
            pl     = float(p.get("unrealized_pl", 0))
            pl_pct = float(p.get("unrealized_plpc", 0)) * 100
            pos_lines += (
                f"\n- {p['symbol']}: {int(float(p['qty']))} shares  "
                f"P&L ${pl:+,.2f} ({pl_pct:+.1f}%)"
            )
    except Exception:
        pos_lines = " (unavailable)"

    import requests
    from config import CLICKUP_API_KEY, CLICKUP_LIST_ID
    if CLICKUP_API_KEY:
        try:
            requests.post(
                f"https://api.clickup.com/api/v2/list/{CLICKUP_LIST_ID}/task",
                headers={
                    "Authorization": CLICKUP_API_KEY,
                    "Content-Type":  "application/json",
                },
                json={
                    "name": f"🕛 Midday Scan — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                    "description": (
                        f"**Time:** {now}\n"
                        f"**Portfolio:** ${equity:,.2f}  |  Cash: ${cash:,.2f} ({cash_pct:.1f}%)\n"
                        f"**Buying Power:** ${buying_pw:,.2f}\n\n"
                        f"**Stop Losses Triggered:** {stopped_text}\n\n"
                        f"**Position Warnings (approaching -8%):**\n{warning_text}\n\n"
                        f"**All Positions:**{pos_lines if pos_lines else ' None'}\n"
                    ),
                    "status":   "complete",
                    "priority": 3,
                    "tags":     ["midday-scan"],
                },
                timeout=10,
            )
            logger.info("ClickUp midday report sent")
        except Exception as exc:
            logger.warning("ClickUp midday report failed: %s", exc)

    logger.info(
        "MIDDAY DONE — positions=%d  stopped=%d  warnings=%d  cash=%.1f%%",
        len(positions), len(stopped), len(warnings), cash_pct,
    )
