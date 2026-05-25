"""
main.py — 24/7 Politician Copy Trading Bot

Flow (every CHECK_INTERVAL_MINUTES):
  1. Scrape Capitol Trades for target politician's latest trades
  2. Skip any trade already in our local DB
  3. Execute new trades on Alpaca paper account
  4. Log everything to logs/bot.log

Run:
  python main.py           ← runs once then loops forever
  python main.py --once    ← single run and exit
"""

import argparse
import logging
import os
import time
from datetime import datetime

import schedule

import db
import scraper
import trader
from config import (
    CHECK_INTERVAL_MINUTES,
    TARGET_POLITICIAN,
    TARGET_POLITICIAN_ID,
    TARGET_POLITICIAN_DISPLAY,
    LOG_FILE,
)


# ── Logging setup ─────────────────────────────────────────────────────────────

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE),
    ],
)
logger = logging.getLogger("main")


# ── Core logic ────────────────────────────────────────────────────────────────

def run_cycle():
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    logger.info("=" * 60)
    logger.info("CYCLE START — %s", now)
    logger.info("Tracking: %s", TARGET_POLITICIAN_DISPLAY)

    # 1. Fetch trades
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
        return

    logger.info("Found %d trades total. Checking for new ones...", len(trades))

    new_count = 0
    for trade in trades:
        if db.already_executed(trade["id"]):
            continue

        new_count += 1
        logger.info(
            "NEW TRADE → %s %s  |  date=%s  |  ~$%.0f",
            trade["side"].upper(),
            trade["ticker"],
            trade["trade_date"],
            trade.get("value", trade.get("amount_low", 0)),
        )

        try:
            result = trader.execute_trade(trade)

            if result.get("status") == "skipped":
                reason = result.get("reason", "unknown")
                logger.info("Skipped %s: %s", trade["ticker"], reason)
                db.mark_skipped(trade, reason)
            else:
                logger.info(
                    "✅  Executed %s %s  →  Alpaca order id=%s",
                    trade["side"].upper(), trade["ticker"],
                    result.get("id", "?"),
                )
                db.mark_executed(trade, result)

        except Exception as exc:
            logger.error("❌  Trade execution failed for %s: %s", trade["ticker"], exc)
            db.mark_error(trade, str(exc))

    if new_count == 0:
        logger.info("No new trades to copy this cycle.")

    summary = db.get_summary()
    logger.info(
        "CYCLE END — executed=%d  skipped=%d  errors=%d",
        summary["total_executed"],
        summary["total_skipped"],
        summary["total_errors"],
    )


# ── Account check on startup ──────────────────────────────────────────────────

def startup_check():
    logger.info("━" * 60)
    logger.info("24/7 Politician Copy Bot — Starting up")
    logger.info("Target: %s | Alpaca: Paper Trading", TARGET_POLITICIAN_DISPLAY)
    try:
        acct = trader.get_account()
        equity = float(acct.get("portfolio_value") or acct.get("equity", 0))
        buying_power = float(acct.get("buying_power", 0))
        logger.info("Alpaca account OK — equity=$%.2f  buying_power=$%.2f", equity, buying_power)
    except Exception as exc:
        logger.error("Alpaca connection failed: %s", exc)
        raise SystemExit(1)
    logger.info("Check interval: every %d minutes", CHECK_INTERVAL_MINUTES)
    logger.info("━" * 60)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Politician copy trading bot")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    args = parser.parse_args()

    startup_check()
    run_cycle()

    if args.once:
        logger.info("--once flag set. Exiting after first cycle.")
        return

    # Schedule recurring runs
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(run_cycle)
    logger.info("Scheduler active. Running every %d minutes...", CHECK_INTERVAL_MINUTES)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
