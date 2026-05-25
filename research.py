"""
research.py — Claude Sonnet 4.6 research filter.

Before executing any politician trade, asks Claude:
  "Should I copy this trade right now given current market conditions?"

Claude considers:
  - What the company does and its sector
  - Whether the trade makes sense (e.g. don't buy if sector is crashing)
  - The politician's filing speed (fast = more relevant)
  - Basic risk assessment

Returns:
  {"decision": "EXECUTE" | "SKIP", "reasoning": str, "confidence": int (1-10)}
"""

import logging
import json

import anthropic

from config import ANTHROPIC_API_KEY

logger = logging.getLogger("research")

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def research_trade(trade: dict) -> dict:
    """
    Ask Claude Sonnet 4.6 whether to execute this politician trade.

    Returns dict with keys: decision, reasoning, confidence
    """
    if not ANTHROPIC_API_KEY:
        logger.debug("No Anthropic API key — skipping research, defaulting to EXECUTE")
        return {"decision": "EXECUTE", "reasoning": "No API key configured", "confidence": 5}

    ticker    = trade["ticker"]
    side      = trade["side"].upper()
    company   = trade.get("company", ticker)
    sector    = trade.get("sector", "unknown")
    value     = trade.get("value", 0)
    trade_date = trade.get("trade_date", "?")
    filed_date = trade.get("filed_date", "?")
    politician = trade.get("politician", "Tim Moore")

    # Calculate how many days between trade and filing
    try:
        from datetime import datetime
        td = datetime.strptime(trade_date, "%Y-%m-%d")
        fd = datetime.strptime(filed_date, "%Y-%m-%d")
        lag_days = (fd - td).days
    except Exception:
        lag_days = "unknown"

    prompt = f"""You are a trading research assistant helping evaluate whether to copy a US politician's stock trade.

## Trade Details
- **Politician:** {politician} (Republican, NC House)
- **Action:** {side} {ticker} ({company})
- **Sector:** {sector}
- **Disclosed Value:** ~${value:,.0f}
- **Trade Date:** {trade_date}
- **Filed Date:** {filed_date}
- **Disclosure Lag:** {lag_days} days

## Your Job
Evaluate whether copying this trade RIGHT NOW makes sense. Consider:
1. Is this company in a sector currently under stress or doing well?
2. Does a {lag_days}-day old trade still have momentum worth following?
3. Any obvious red flags (earnings coming up, regulatory issues, macro risks)?
4. Is {company} a solid company worth holding?

Be concise. Use your training knowledge about this company and sector.

## Response Format (JSON only, no other text)
{{
  "decision": "EXECUTE" or "SKIP",
  "reasoning": "2-3 sentences max explaining your call",
  "confidence": 1-10
}}"""

    try:
        client = _get_client()
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = message.content[0].text.strip()

        # Parse JSON response
        # Strip markdown code blocks if present
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        result = json.loads(raw.strip())

        # Validate
        if result.get("decision") not in ("EXECUTE", "SKIP"):
            result["decision"] = "EXECUTE"

        logger.info(
            "Research: %s %s → %s (confidence %s/10) — %s",
            side, ticker,
            result["decision"],
            result.get("confidence", "?"),
            result.get("reasoning", "")[:80],
        )
        return result

    except json.JSONDecodeError as exc:
        logger.warning("Research JSON parse failed for %s: %s", ticker, exc)
        return {"decision": "EXECUTE", "reasoning": "Parse error — defaulting to execute", "confidence": 5}
    except Exception as exc:
        logger.warning("Research failed for %s: %s — defaulting to EXECUTE", ticker, exc)
        return {"decision": "EXECUTE", "reasoning": f"Research error: {exc}", "confidence": 5}
