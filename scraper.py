"""
scraper.py — Fetch recent trades for a target politician from Capitol Trades.

Uses Capitol Trades' internal Next.js RSC (React Server Component) payload,
which returns structured JSON without needing a headless browser.

Each trade dict returned:
  {
    "id":          str,   # unique: MD5 of txId
    "tx_id":       int,   # Capitol Trades internal transaction ID
    "politician":  str,
    "ticker":      str,   # e.g. "T", "NVDA" (stripped of ":US")
    "company":     str,
    "sector":      str,
    "side":        str,   # "buy" | "sell"
    "value":       float, # approximate USD value disclosed
    "price":       float, # price at time of trade
    "trade_date":  str,   # ISO date  e.g. "2026-05-18"
    "filed_date":  str,   # ISO date when disclosure was published
    "asset_type":  str,   # "stock" | "etf" | "option" | "other"
    "country":     str,
  }
"""

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone

import requests

from config import TRADES_URL, TARGET_POLITICIAN_ID, TARGET_POLITICIAN_DISPLAY, LOOKBACK_DAYS

logger = logging.getLogger("scraper")

RSC_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":                  "text/x-component",
    "RSC":                     "1",
    "Next-Router-State-Tree":  "%5B%22%22%2C%7B%7D%5D",
    "Referer":                 "https://www.capitoltrades.com/",
}


def _make_id(tx_id: int) -> str:
    return hashlib.md5(str(tx_id).encode()).hexdigest()


def _extract_trades_from_rsc(rsc_text: str) -> list:
    """
    Extract the trade JSON array from Capitol Trades' RSC payload.
    The array starts right after '"data":' in the React component payload.
    """
    marker = '"data":['
    idx = rsc_text.find(marker)
    if idx == -1:
        marker2 = '[{"_issuerId":'
        idx2 = rsc_text.find(marker2)
        if idx2 == -1:
            logger.warning("Could not find trade data marker in RSC payload")
            return []
        start = idx2
    else:
        start = idx + len(marker) - 1  # position of '['

    # Extract the JSON array by counting brackets
    depth   = 0
    in_str  = False
    escape  = False
    end_pos = start

    for i, ch in enumerate(rsc_text[start:], start=start):
        if escape:
            escape = False
            continue
        if ch == '\\' and in_str:
            escape = True
            continue
        if ch == '"' and not escape:
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                end_pos = i + 1
                break

    candidate = rsc_text[start:end_pos]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        logger.warning("JSON parse failed: %s", exc)
        return []


def _normalise(raw: dict):
    """Convert a raw Capitol Trades record to our internal format."""
    try:
        issuer     = raw.get("issuer", {})
        politician = raw.get("politician", {})
        tx_type    = raw.get("txType", "").lower()

        # Only process buy/sell
        if tx_type not in ("buy", "sell"):
            return None

        raw_ticker = issuer.get("issuerTicker", "")
        ticker     = raw_ticker.split(":")[0].strip()
        if not ticker:
            return None

        # Skip non-US stocks (Capitol Trades marks country on issuer)
        country = issuer.get("country", "us")

        pub_date = raw.get("pubDate", "")[:10]  # YYYY-MM-DD

        return {
            "id":          _make_id(raw["_txId"]),
            "tx_id":       raw["_txId"],
            "politician":  (
                f"{politician.get('nickname') or politician.get('firstName', '')} "
                f"{politician.get('lastName', '')}".strip()
                or TARGET_POLITICIAN_DISPLAY
            ),
            "ticker":      ticker,
            "company":     issuer.get("issuerName", ""),
            "sector":      issuer.get("sector", ""),
            "side":        tx_type,
            "value":       float(raw.get("value") or 0),
            "price":       float(raw.get("price") or 0),
            "trade_date":  raw.get("txDate", ""),
            "filed_date":  pub_date,
            "asset_type":  "stock",
            "country":     country,
        }
    except Exception as exc:
        logger.debug("Normalise failed for %s: %s", raw.get("_txId"), exc)
        return None


def get_recent_trades(
    politician_id: str      = None,
    politician_display: str = None,
    lookback_days: int      = None,
    max_pages: int          = 2,
    page_size: int          = 96,
) -> list:
    """
    Return normalised trades filed within the last `lookback_days` days.
    Sorted newest-first. Deduplicates by tx_id.
    """
    politician_id      = politician_id      or TARGET_POLITICIAN_ID
    politician_display = politician_display or TARGET_POLITICIAN_DISPLAY
    lookback_days      = lookback_days      or LOOKBACK_DAYS

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    all_trades: list = []
    seen_ids: set    = set()

    for page in range(1, max_pages + 1):
        try:
            resp = requests.get(
                TRADES_URL,
                params={
                    "politician": politician_id,
                    "pageSize":   page_size,
                    "page":       page,
                },
                headers=RSC_HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            raw_list = _extract_trades_from_rsc(resp.text)

            if not raw_list:
                break

            page_new   = 0
            stop_early = False

            for raw in raw_list:
                trade = _normalise(raw)
                if not trade:
                    continue

                # Check if this trade's filed_date is within the lookback window
                try:
                    filed_dt = datetime.strptime(trade["filed_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except ValueError:
                    filed_dt = datetime.now(timezone.utc)

                if filed_dt < cutoff:
                    # Capitol Trades returns newest-first; once we pass the cutoff, stop
                    stop_early = True
                    break

                if trade["id"] not in seen_ids:
                    all_trades.append(trade)
                    seen_ids.add(trade["id"])
                    page_new += 1

            logger.info(
                "Page %d: %d trades within last %d days (total: %d)",
                page, page_new, lookback_days, len(all_trades),
            )

            if stop_early or page_new == 0:
                break

            time.sleep(1)

        except Exception as exc:
            logger.warning("Page %d fetch failed: %s", page, exc)
            break

    logger.info(
        "Fetched %d trades for %s (last %d days)",
        len(all_trades), politician_display, lookback_days,
    )
    return all_trades
