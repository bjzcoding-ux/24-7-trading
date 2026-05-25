"""
dashboard.py — Quick CLI snapshot of bot status and open positions.

Usage:
  python dashboard.py
"""

import json
import os
from datetime import datetime

import trader
import db


def fmt(val, prefix="$"):
    try:
        return f"{prefix}{float(val):,.2f}"
    except (TypeError, ValueError):
        return str(val)


def main():
    print("\n" + "═" * 58)
    print("  24/7 POLITICIAN COPY BOT — DASHBOARD")
    print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("═" * 58)

    # Account
    try:
        acct = trader.get_account()
        print(f"\n{'ACCOUNT':─<40}")
        print(f"  Portfolio value : {fmt(acct.get('portfolio_value'))}")
        print(f"  Buying power    : {fmt(acct.get('buying_power'))}")
        print(f"  Cash            : {fmt(acct.get('cash'))}")
        print(f"  Status          : {acct.get('status', '?').upper()}")
    except Exception as e:
        print(f"  ⚠️  Could not reach Alpaca: {e}")

    # Positions
    try:
        positions = trader.get_positions()
        print(f"\n{'OPEN POSITIONS':─<40}")
        if not positions:
            print("  (none)")
        for p in positions:
            pl = float(p.get("unrealized_pl", 0))
            pl_pct = float(p.get("unrealized_plpc", 0)) * 100
            sign = "+" if pl >= 0 else ""
            print(
                f"  {p['symbol']:<8}  {int(float(p['qty'])):>5} shares  "
                f"avg={fmt(p.get('avg_entry_price'))}  "
                f"now={fmt(p.get('current_price'))}  "
                f"P&L={sign}{fmt(p.get('unrealized_pl'))} ({sign}{pl_pct:.1f}%)"
            )
    except Exception as e:
        print(f"  ⚠️  Positions error: {e}")

    # Bot summary
    print(f"\n{'BOT ACTIVITY':─<40}")
    summary = db.get_summary()
    print(f"  Trades copied   : {summary['total_executed']}")
    print(f"  Trades skipped  : {summary['total_skipped']}")
    print(f"  Errors          : {summary['total_errors']}")
    if summary["last_executed"]:
        last = summary["last_executed"]
        print(f"  Last copy       : {last['side'].upper()} {last['ticker']} @ {last['copied_at'][:10]}")

    # Recent executed trades
    if os.path.exists("trades_db.json"):
        with open("trades_db.json") as f:
            data = json.load(f)
        executed = data.get("executed", [])[-10:]
        if executed:
            print(f"\n{'LAST 10 COPIED TRADES':─<40}")
            for t in reversed(executed):
                print(
                    f"  {t['copied_at'][:10]}  {t['side'].upper():<5}  "
                    f"{t['ticker']:<8}  (politician trade: {t['trade_date']})"
                )

    print("\n" + "═" * 58 + "\n")


if __name__ == "__main__":
    main()
