"""
journal.py — End-of-day P&L journal.

Writes a dated markdown file to journal/ after market close (4:15 PM ET).
Tracks: account value, daily P&L, open positions, trades executed today,
and a running total across all journal entries.
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

import trader
from config import JOURNAL_DIR, DB_FILE

logger = logging.getLogger("journal")


def _load_todays_trades() -> list:
    """Pull today's executed trades from trades_db.json."""
    if not os.path.exists(DB_FILE):
        return []
    with open(DB_FILE) as f:
        data = json.load(f)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return [
        t for t in data.get("executed", [])
        if t.get("copied_at", "").startswith(today)
    ]


def _load_all_journals() -> list:
    """Load all past journal files to compute running totals."""
    entries = []
    if not os.path.exists(JOURNAL_DIR):
        return entries
    for fname in sorted(os.listdir(JOURNAL_DIR)):
        if fname.endswith(".md"):
            path = os.path.join(JOURNAL_DIR, fname)
            with open(path) as f:
                entries.append(f.read())
    return entries


def write_journal() -> str:
    """
    Generate and save today's journal entry.
    Returns the file path written.
    """
    os.makedirs(JOURNAL_DIR, exist_ok=True)

    now   = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    fname = os.path.join(JOURNAL_DIR, f"{today}.md")

    # ── Gather data ──────────────────────────────────────────────────────────
    try:
        acct      = trader.get_account()
        equity    = float(acct.get("portfolio_value") or 0)
        cash      = float(acct.get("cash") or 0)
        buying_pw = float(acct.get("buying_power") or 0)
    except Exception as exc:
        logger.warning("Could not fetch account: %s", exc)
        equity = cash = buying_pw = 0

    try:
        positions = trader.get_positions()
    except Exception:
        positions = []

    todays_trades = _load_todays_trades()

    # Calculate total P&L across all positions
    total_unrealised = sum(float(p.get("unrealized_pl", 0)) for p in positions)
    total_unrealised_pct = (total_unrealised / (equity - total_unrealised) * 100) if equity else 0

    # ── Build markdown ───────────────────────────────────────────────────────
    lines = [
        f"# Trading Journal — {today}",
        f"> Generated {now.strftime('%Y-%m-%d %H:%M UTC')} | Target: Tim Moore (Capitol Trades)",
        "",
        "## Account Summary",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Portfolio Value | ${equity:,.2f} |",
        f"| Cash | ${cash:,.2f} |",
        f"| Buying Power | ${buying_pw:,.2f} |",
        f"| Unrealised P&L | ${total_unrealised:+,.2f} ({total_unrealised_pct:+.2f}%) |",
        f"| Open Positions | {len(positions)} |",
        "",
    ]

    # ── Open positions ────────────────────────────────────────────────────────
    if positions:
        lines += [
            "## Open Positions",
            "| Symbol | Qty | Avg Entry | Current | P&L $ | P&L % |",
            "|--------|-----|-----------|---------|-------|-------|",
        ]
        for p in sorted(positions, key=lambda x: float(x.get("unrealized_pl", 0))):
            pl     = float(p.get("unrealized_pl", 0))
            pl_pct = float(p.get("unrealized_plpc", 0)) * 100
            lines.append(
                f"| {p['symbol']} | {int(float(p['qty']))} "
                f"| ${float(p.get('avg_entry_price',0)):,.2f} "
                f"| ${float(p.get('current_price',0)):,.2f} "
                f"| ${pl:+,.2f} "
                f"| {pl_pct:+.2f}% |"
            )
        lines.append("")
    else:
        lines += ["## Open Positions", "_No open positions._", ""]

    # ── Today's trades ────────────────────────────────────────────────────────
    if todays_trades:
        lines += [
            "## Trades Executed Today",
            "| Time | Side | Ticker | Politician Trade Date |",
            "|------|------|--------|-----------------------|",
        ]
        for t in todays_trades:
            time_str = t.get("copied_at", "")[:16].replace("T", " ")
            lines.append(
                f"| {time_str} | {t['side'].upper()} | {t['ticker']} | {t.get('trade_date','?')} |"
            )
        lines.append("")
    else:
        lines += ["## Trades Executed Today", "_No new trades copied today._", ""]

    # ── Risk summary ─────────────────────────────────────────────────────────
    cash_pct = (cash / equity * 100) if equity else 0
    lines += [
        "## Risk Summary",
        f"| Check | Status |",
        f"|-------|--------|",
        f"| Cash Reserve (need >20%) | {'✅' if cash_pct >= 20 else '⚠️'} {cash_pct:.1f}% |",
        f"| Stop Loss Threshold | 8% per position |",
        f"| Max Trade Size | $5,000 (5% of portfolio) |",
        "",
        "---",
        f"_Journal auto-generated by 24/7 Trading Bot_",
    ]

    content = "\n".join(lines)

    with open(fname, "w") as f:
        f.write(content)

    logger.info("Journal written: %s", fname)
    print(content)
    return fname
