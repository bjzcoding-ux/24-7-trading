"""
research.py — Trade research filter.

No separate API key needed. This module reads a pre-analysis file
written by the Claude agent (the remote routine) before running the bot.

How it works:
  1. The Claude routine agent reads Capitol Trades
  2. It writes research/analysis.json with its verdict on each trade
  3. This module reads that file — EXECUTE or SKIP per ticker
  4. If no pre-analysis exists, defaults to EXECUTE (safe fallback)

This way Claude Sonnet 4.6 IS the research brain — no extra API calls,
no extra cost, no extra keys.
"""

import json
import logging
import os

logger = logging.getLogger("research")

ANALYSIS_FILE = "research/analysis.json"


def load_analysis() -> dict:
    """Load pre-written analysis from the Claude agent. Returns {} if not found."""
    if not os.path.exists(ANALYSIS_FILE):
        return {}
    try:
        with open(ANALYSIS_FILE) as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Could not load research analysis: %s", exc)
        return {}


def research_trade(trade: dict) -> dict:
    """
    Look up this trade's verdict from the Claude agent's pre-analysis.
    Falls back to EXECUTE if no analysis exists for this ticker.
    """
    ticker   = trade["ticker"].upper()
    analysis = load_analysis()

    if ticker in analysis:
        result = analysis[ticker]
        logger.info(
            "Research: %s %s → %s (confidence %s/10) — %s",
            trade["side"].upper(), ticker,
            result.get("decision", "EXECUTE"),
            result.get("confidence", "?"),
            result.get("reasoning", "")[:80],
        )
        return result

    # No pre-analysis for this ticker — default to execute
    logger.info("Research: no pre-analysis for %s — defaulting to EXECUTE", ticker)
    return {
        "decision":   "EXECUTE",
        "reasoning":  "No pre-analysis available — following politician signal",
        "confidence": 6,
    }
