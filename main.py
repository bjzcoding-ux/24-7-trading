"""
main.py — 24/7 Politician Copy Trading Bot

Cycle (every CHECK_INTERVAL_MINUTES):
  1. ✅ Stop-loss check — auto-sell any position down 8%+
  2. ✅ Cash reserve check — skip buys if cash < 20% of portfolio
  3. Scrape Capitol Trades for Tim Moore's recent trades (last 30 days)
  4. Skip trades already in DB / already holding
  5. Place LIMIT orders on Alpaca (buy at ask+0.2%, sell at bid-0.2%)
  6. Log everything

Journal (after 4:15 PM ET / 20:15 UTC, once per day):
  - Writes journal/<date>.md with P&L, positions, trades

Run:
  python3 main.py           ← loops forever
  python3 main.py --once    ← single cycle and exit
  python3 main.py --journal ← write today's journal and exit
"""

import argparse
import logging
import os
from datetime import datetime, timezone, timedelta

import schedule
import time

import db
import journal
import notify
import research
import scraper
import trader
from config import (
    CHECK_INTERVAL_MINUTES,
    TARGET_POLITICIAN_ID,
    TARGET_POLITICIAN_DISPLAY,
    LOG_FILE,
    STOP_LOSS_PCT,
    CASH_RESERVE_PCT,
)

# ── Logging ──────────────────────────────────────────────────────────────────

os.makedirs("logs", exist_ok=True)
os.makedirs("journal", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE),
    ],
)
logger = logging.getLogger("main")

# Track whether we've written today's journal already
_journal_written_date: str = ""


# ── Stop-loss cycle ───────────────────────────────────────────────────────────

def run_stop_loss_check():
    logger.info("--- Stop-loss scan (threshold: -%.0f%%) ---", STOP_LOSS_PCT * 100)
    stopped = trader.check_stop_losses()
    if stopped:
        for sym in stopped:
            db.mark_skipped(
                {"id": f"stoploss-{sym}", "ticker": sym, "trade_date": ""},
                "stop_loss_triggered",
            )
            notify.stop_loss_triggered(sym, 0, 0)


# ── Main trading cycle ────────────────────────────────────────────────────────

def run_cycle():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    logger.info("=" * 60)
    logger.info("CYCLE START — %s", now)
    logger.info("Tracking: %s", TARGET_POLITICIAN_DISPLAY)

    # 1. Stop-loss check first
    run_stop_loss_check()

    # 2. Scrape Capitol Trades
    try:
        trades = scraper.get_recent_trades(
            politician_id=TARGET_POLITICIAN_ID,
            politician_display=TARGET_POLITICIAN_DISPLAY,
        )
    except Exception as exc:
        logger.error("Scrape failed: %s", exc)
        return

    if not trades:
        logger.info("No trades found for %s this cycle.", TARGET_POLITICIAN_DISPLAY)
        _log_cycle_end()
        return

    logger.info("Found %d trades. Checking for new ones...", len(trades))

    new_count = 0
    for trade in trades:
        if db.already_executed(trade["id"]):
            continue

        new_count += 1
        logger.info(
            "NEW TRADE → %s %s  |  filed=%s  |  ~$%.0f",
            trade["side"].upper(),
            trade["ticker"],
            trade["filed_date"],
            trade.get("value", 0),
        )

        # ── Claude Sonnet 4.6 research filter ────────────────────────────
        analysis = research.research_trade(trade)
        if analysis["decision"] == "SKIP":
            logger.info(
                "🧠 AI Research: SKIP %s — %s (confidence %s/10)",
                trade["ticker"], analysis["reasoning"], analysis.get("confidence"),
            )
            db.mark_skipped(trade, f"ai_research: {analysis['reasoning'][:60]}")
            notify.research_rejected(trade, analysis["reasoning"])
            continue

        logger.info(
            "🧠 AI Research: EXECUTE %s — %s (confidence %s/10)",
            trade["ticker"], analysis["reasoning"], analysis.get("confidence"),
        )

        # ── Execute on Alpaca ─────────────────────────────────────────────
        try:
            result = trader.execute_trade(trade)

            if result.get("status") == "skipped":
                reason = result.get("reason", "unknown")
                logger.info("Skipped %s: %s", trade["ticker"], reason)
                db.mark_skipped(trade, reason)
                notify.trade_skipped(trade, reason)
            else:
                logger.info(
                    "✅  %s %s  →  Alpaca order id=%s",
                    trade["side"].upper(), trade["ticker"],
                    result.get("id", "?"),
                )
                db.mark_executed(trade, result)
                notify.trade_executed(trade, result, analysis["reasoning"])

        except Exception as exc:
            logger.error("❌  Trade failed for %s: %s", trade["ticker"], exc)
            db.mark_error(trade, str(exc))

    if new_count == 0:
        logger.info("No new trades to copy this cycle.")

    _log_cycle_end()


def _log_cycle_end():
    summary = db.get_summary()
    logger.info(
        "CYCLE END — executed=%d  skipped=%d  errors=%d",
        summary["total_executed"],
        summary["total_skipped"],
        summary["total_errors"],
    )


# ── End-of-day journal ────────────────────────────────────────────────────────

def run_journal_if_due():
    """Write the daily journal once after 4:15 PM ET (20:15 UTC)."""
    global _journal_written_date
    now   = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    # 4:15 PM ET = 20:15 UTC (21:15 UTC during EDT)
    market_close_utc = now.replace(hour=20, minute=15, second=0, microsecond=0)

    if now >= market_close_utc and _journal_written_date != today:
        logger.info("Writing end-of-day journal...")
        try:
            path = journal.write_journal()
            logger.info("Journal saved: %s", path)
            _journal_written_date = today
            # Send ClickUp daily summary
            try:
                acct      = trader.get_account()
                positions = trader.get_positions()
                summary   = db.get_summary()
                notify.daily_summary(
                    equity         = float(acct.get("portfolio_value", 0)),
                    cash           = float(acct.get("cash", 0)),
                    positions      = positions,
                    executed_today = summary["total_executed"],
                    stopped        = 0,
                )
            except Exception as exc:
                logger.warning("ClickUp daily summary failed: %s", exc)
        except Exception as exc:
            logger.error("Journal write failed: %s", exc)


# ── Startup check ─────────────────────────────────────────────────────────────

def startup_check():
    logger.info("━" * 60)
    logger.info("24/7 Politician Copy Bot — Starting up")
    logger.info("Target   : %s", TARGET_POLITICIAN_DISPLAY)
    logger.info("Stop loss: -%.0f%%  |  Cash reserve: %.0f%%", STOP_LOSS_PCT * 100, CASH_RESERVE_PCT * 100)

    try:
        acct      = trader.get_account()
        equity    = float(acct.get("portfolio_value") or 0)
        cash      = float(acct.get("cash") or 0)
        buy_power = float(acct.get("buying_power") or 0)
        logger.info(
            "Alpaca   : equity=$%.2f  cash=$%.2f  buying_power=$%.2f",
            equity, cash, buy_power,
        )
    except Exception as exc:
        logger.error("Alpaca connection failed: %s", exc)
        raise SystemExit(1)

    logger.info("Interval : every %d minutes", CHECK_INTERVAL_MINUTES)
    logger.info("━" * 60)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once",    action="store_true", help="Run one cycle and exit")
    parser.add_argument("--journal", action="store_true", help="Write today's journal and exit")
    args = parser.parse_args()

    startup_check()

    if args.journal:
        journal.write_journal()
        return

    run_cycle()

    if args.once:
        logger.info("--once flag set. Exiting.")
        return

    # Schedule recurring runs + daily journal check
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(run_cycle)
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(run_journal_if_due)

    logger.info("Scheduler active — every %d minutes.", CHECK_INTERVAL_MINUTES)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
