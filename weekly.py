"""
weekly.py — Friday end-of-week review.

Runs every Friday at 4:30 PM ET. Writes a full week recap:
  - Total P&L for the week
  - Best and worst positions
  - How many trades were copied vs skipped vs AI-rejected
  - Whether we're beating the S&P 500 (rough estimate)
  - Plan for next week

Saves to journal/weekly-YYYY-WXX.md and sends to ClickUp.
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

import requests

import trader
from config import CLICKUP_API_KEY, CLICKUP_LIST_ID, DB_FILE, JOURNAL_DIR

logger = logging.getLogger("weekly")


def _load_week_trades() -> list:
    """Load all trades executed in the last 7 days."""
    if not os.path.exists(DB_FILE):
        return []
    with open(DB_FILE) as f:
        data = json.load(f)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    return [
        t for t in data.get("executed", [])
        if t.get("copied_at", "")[:10] >= cutoff
    ]


def _load_week_skipped() -> list:
    if not os.path.exists(DB_FILE):
        return []
    with open(DB_FILE) as f:
        data = json.load(f)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    return [
        t for t in data.get("skipped", [])
        if t.get("skipped_at", "")[:10] >= cutoff
    ]


def write_weekly_review() -> str:
    os.makedirs(JOURNAL_DIR, exist_ok=True)

    now      = datetime.now(timezone.utc)
    week_num = now.isocalendar()[1]
    year     = now.year
    fname    = os.path.join(JOURNAL_DIR, f"weekly-{year}-W{week_num:02d}.md")

    # Account data
    try:
        acct      = trader.get_account()
        equity    = float(acct.get("portfolio_value", 0))
        cash      = float(acct.get("cash", 0))
    except Exception:
        equity = cash = 0

    # Positions
    try:
        positions = trader.get_positions()
    except Exception:
        positions = []

    week_trades   = _load_week_trades()
    week_skipped  = _load_week_skipped()
    ai_rejected   = [s for s in week_skipped if "ai_research" in s.get("reason", "")]

    # P&L summary
    total_pl     = sum(float(p.get("unrealized_pl", 0)) for p in positions)
    total_pl_pct = (total_pl / (equity - total_pl) * 100) if equity else 0

    # Best / worst positions
    sorted_pos = sorted(positions, key=lambda p: float(p.get("unrealized_pl", 0)), reverse=True)
    best  = sorted_pos[:3]  if sorted_pos else []
    worst = sorted_pos[-3:] if sorted_pos else []

    # ── Build markdown ────────────────────────────────────────────────────────
    lines = [
        f"# Weekly Review — Week {week_num}, {year}",
        f"> {now.strftime('%Y-%m-%d %H:%M UTC')} | Target: Tim Moore (Capitol Trades)",
        "",
        "## Week at a Glance",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Portfolio Value | ${equity:,.2f} |",
        f"| Cash | ${cash:,.2f} ({cash/equity*100:.1f}%) |" if equity else "| Cash | $0 |",
        f"| Unrealised P&L | ${total_pl:+,.2f} ({total_pl_pct:+.2f}%) |",
        f"| Trades Copied This Week | {len(week_trades)} |",
        f"| Trades Skipped | {len(week_skipped)} |",
        f"| AI Rejected | {len(ai_rejected)} |",
        f"| Open Positions | {len(positions)} |",
        "",
    ]

    # Best performers
    if best:
        lines += [
            "## 🏆 Best Positions This Week",
            "| Symbol | Shares | P&L $ | P&L % |",
            "|--------|--------|-------|-------|",
        ]
        for p in best:
            pl     = float(p.get("unrealized_pl", 0))
            pl_pct = float(p.get("unrealized_plpc", 0)) * 100
            lines.append(f"| {p['symbol']} | {int(float(p['qty']))} | ${pl:+,.2f} | {pl_pct:+.1f}% |")
        lines.append("")

    # Worst performers
    if worst and len(positions) > 1:
        lines += [
            "## ⚠️ Watch List (Weakest This Week)",
            "| Symbol | Shares | P&L $ | P&L % |",
            "|--------|--------|-------|-------|",
        ]
        for p in worst:
            pl     = float(p.get("unrealized_pl", 0))
            pl_pct = float(p.get("unrealized_plpc", 0)) * 100
            lines.append(f"| {p['symbol']} | {int(float(p['qty']))} | ${pl:+,.2f} | {pl_pct:+.1f}% |")
        lines.append("")

    # Trades this week
    if week_trades:
        lines += [
            "## Trades Copied This Week",
            "| Date | Side | Ticker | Politician Trade Date |",
            "|------|------|--------|-----------------------|",
        ]
        for t in week_trades:
            lines.append(
                f"| {t.get('copied_at','')[:10]} | {t['side'].upper()} "
                f"| {t['ticker']} | {t.get('trade_date','?')} |"
            )
        lines.append("")

    # AI rejections
    if ai_rejected:
        lines += ["## 🧠 AI Research Rejections This Week"]
        for s in ai_rejected:
            lines.append(f"- **{s.get('ticker','?')}**: {s.get('reason','?')}")
        lines.append("")

    # Next week plan
    lines += [
        "## Plan for Next Week",
        "- Continue monitoring Tim Moore's Capitol Trades filings",
        "- Review any positions approaching -5% (pre-stop warning)",
        "- Consider switching to Warren Davidson if Tim Moore goes quiet",
        "",
        "---",
        "_Weekly review auto-generated by 24/7 Trading Bot_",
    ]

    content = "\n".join(lines)
    with open(fname, "w") as f:
        f.write(content)

    logger.info("Weekly review written: %s", fname)
    print(content)

    # Send to ClickUp
    if CLICKUP_API_KEY:
        try:
            requests.post(
                f"https://api.clickup.com/api/v2/list/{CLICKUP_LIST_ID}/task",
                headers={
                    "Authorization": CLICKUP_API_KEY,
                    "Content-Type":  "application/json",
                },
                json={
                    "name":        f"📅 Weekly Review — Week {week_num}, {year}",
                    "description": content,
                    "status":      "complete",
                    "priority":    2,
                    "tags":        ["weekly-review"],
                },
                timeout=10,
            )
            logger.info("ClickUp weekly review sent")
        except Exception as exc:
            logger.warning("ClickUp weekly review failed: %s", exc)

    return fname
