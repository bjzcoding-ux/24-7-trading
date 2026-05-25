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
    "filed_date":  str,   # ISO datetime when disclosure was published
    "asset_type":  str,   # "stock" | "etf" | "option" | "other"
    "country":     str,
  }
"""

import hashlib
import json
import logging
import re
import time

import requests

from config import TRADES_URL, TARGET_POLITICIAN_ID, TARGET_POLITICIAN_DISPLAY

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


def _extract_trades_from_rsc(rsc_text: str) -> list[dict]:
    """
    The RSC payload embeds the trade array as a JSON blob starting with
    '[{"_issuerId":...' embedded inside a React component data attribute.
    We locate and extract that array.
    """
    # Capitol Trades embeds: {"columns":"$c","data":[{...trades...}]}
    # The array starts right after '"data":'
    marker = '"data":['
    idx = rsc_text.find(marker)
    if idx == -1:
        # Fallback: look for the raw array start
        marker2 = '[{"_issuerId":'
        idx2 = rsc_text.find(marker2)
        if idx2 == -1:
            logger.warning("Could not find trade data marker in RSC payload")
            return []
        start = idx2
    else:
        start = idx + len(marker) - 1  # position of '['

    # Now extract the JSON array by counting brackets
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

        # Skip non-buy/sell records (receive, exchange, etc.)
        if tx_type not in ("buy", "sell"):
            return None

        raw_ticker = issuer.get("issuerTicker", "")
        ticker     = raw_ticker.split(":")[0].strip()
        if not ticker:
            return None

        pub_date = raw.get("pubDate", "")[:10]   # keep only YYYY-MM-DD

        return {
            "id":         _make_id(raw["_txId"]),
            "tx_id":      raw["_txId"],
            "politician": (
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
            "asset_type":  "stock",   # Capitol Trades shows stocks by default; options rare
            "country":     issuer.get("country", "us"),
        }
    except Exception as exc:
        logger.debug("Normalise failed for %s: %s", raw.get("_txId"), exc)
        return None


def get_recent_trades(
    politician_id: str     = None,
    politician_display: str = None,
    max_pages: int = 3,
    page_size: int = 96,
) -> list[dict]:
    """
    Return normalised recent trades for the target politician.
    Deduplicates by tx_id across pages.
    """
    politician_id     = politician_id     or TARGET_POLITICIAN_ID
    politician_display = politician_display or TARGET_POLITICIAN_DISPLAY

    all_trades: list[dict] = []
    seen_ids: set[str]     = set()

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
                logger.info("No trade records on page %d — stopping.", page)
                break

            page_new = 0
            for raw in raw_list:
                trade = _normalise(raw)
                if trade and trade["id"] not in seen_ids:
                    all_trades.append(trade)
                    seen_ids.add(trade["id"])
                    page_new += 1

            logger.info("Page %d: %d new trades (total so far: %d)", page, page_new, len(all_trades))
            if page_new == 0:
                break

            time.sleep(1)

        except Exception as exc:
            logger.warning("Page %d fetch failed: %s", page, exc)
            break

    logger.info("Total trades fetched for %s: %d", politician_display, len(all_trades))
    return all_trades
