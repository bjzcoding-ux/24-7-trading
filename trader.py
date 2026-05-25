"""
trader.py — Execute trades on Alpaca paper account.

Key design:
  - Uses Alpaca POSITIONS as the deduplication source of truth.
    Since trades_db.json resets each remote run, we check whether
    we already hold a stock before buying again.
  - Skips non-US / OTC tickers that Alpaca can't price.
  - Sizes orders as a fraction of portfolio equity, capped to MIN/MAX.
"""

import logging
import requests

from config import (
    ALPACA_KEY, ALPACA_SECRET, ALPACA_BASE_URL,
    TRADE_FRACTION, MIN_TRADE_USD, MAX_TRADE_USD,
)

logger = logging.getLogger("trader")

SESSION = requests.Session()
SESSION.headers.update({
    "APCA-API-KEY-ID":     ALPACA_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET,
    "Content-Type":        "application/json",
})

DATA_HEADERS = {
    "APCA-API-KEY-ID":     ALPACA_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET,
}

# Cache positions for the lifetime of one bot run (avoid repeated API calls)
_positions_cache: dict = {}   # symbol -> position dict
_positions_loaded = False


def _load_positions():
    global _positions_cache, _positions_loaded
    if _positions_loaded:
        return
    try:
        resp = SESSION.get(f"{ALPACA_BASE_URL}/v2/positions")
        resp.raise_for_status()
        for p in resp.json():
            _positions_cache[p["symbol"].upper()] = p
        logger.info("Loaded %d existing positions from Alpaca", len(_positions_cache))
    except Exception as exc:
        logger.warning("Could not load positions: %s", exc)
    _positions_loaded = True


# ── Account ──────────────────────────────────────────────────────────────────

def get_account() -> dict:
    resp = SESSION.get(f"{ALPACA_BASE_URL}/v2/account")
    resp.raise_for_status()
    return resp.json()


def get_portfolio_value() -> float:
    acct = get_account()
    return float(acct.get("portfolio_value") or acct.get("equity", 10_000))


def get_positions() -> list:
    resp = SESSION.get(f"{ALPACA_BASE_URL}/v2/positions")
    resp.raise_for_status()
    return resp.json()


def get_position(symbol: str):
    _load_positions()
    return _positions_cache.get(symbol.upper())


def already_holding(symbol: str) -> bool:
    """True if we currently have a position in this symbol."""
    return get_position(symbol) is not None


# ── Quote ────────────────────────────────────────────────────────────────────

def get_latest_price(symbol: str):
    """Fetch latest trade price. Returns None if symbol not found on Alpaca."""
    try:
        resp = requests.get(
            f"https://data.alpaca.markets/v2/stocks/{symbol}/trades/latest",
            headers=DATA_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        return float(resp.json()["trade"]["p"])
    except requests.HTTPError as e:
        if e.response.status_code in (404, 422):
            logger.info("Ticker %s not found on Alpaca (foreign/OTC) — skipping", symbol)
        else:
            logger.warning("Price fetch error for %s: %s", symbol, e)
        return None
    except Exception as exc:
        logger.warning("Price fetch failed for %s: %s", symbol, exc)
        return None


def is_tradeable(symbol: str) -> bool:
    """Check if Alpaca supports trading this symbol."""
    try:
        resp = SESSION.get(f"{ALPACA_BASE_URL}/v2/assets/{symbol}")
        resp.raise_for_status()
        asset = resp.json()
        return asset.get("tradable", False) and asset.get("status") == "active"
    except Exception:
        return False


# ── Order sizing ─────────────────────────────────────────────────────────────

def calculate_qty(symbol: str, notional_hint: float = 0) -> int:
    """
    How many shares to buy.
    Target = TRADE_FRACTION of portfolio, clamped to MIN/MAX_TRADE_USD.
    """
    portfolio  = get_portfolio_value()
    target_usd = min(max(portfolio * TRADE_FRACTION, MIN_TRADE_USD), MAX_TRADE_USD)

    price = get_latest_price(symbol)
    if not price or price <= 0:
        return 0

    qty = int(target_usd / price)
    return max(qty, 1)


# ── Orders ───────────────────────────────────────────────────────────────────

def place_market_order(symbol: str, qty: int, side: str) -> dict:
    payload = {
        "symbol":        symbol,
        "qty":           str(qty),
        "side":          side,
        "type":          "market",
        "time_in_force": "day",
    }
    resp = SESSION.post(f"{ALPACA_BASE_URL}/v2/orders", json=payload)
    resp.raise_for_status()
    result = resp.json()
    logger.info(
        "Order placed: %s %d %s — Alpaca id=%s",
        side.upper(), qty, symbol, result.get("id"),
    )
    # Update local cache
    if side == "buy":
        _positions_cache[symbol.upper()] = {"symbol": symbol, "qty": str(qty)}
    elif side == "sell" and symbol.upper() in _positions_cache:
        del _positions_cache[symbol.upper()]
    return result


# ── Main entry ───────────────────────────────────────────────────────────────

def execute_trade(trade: dict) -> dict:
    """
    Execute a single trade from the scraper on Alpaca.
    Returns order result dict, or {"status": "skipped", "reason": ...}.
    """
    symbol = trade["ticker"].upper()
    side   = trade["side"]   # "buy" | "sell"

    # ── BUY logic ────────────────────────────────────────────────────────────
    if side == "buy":
        # Don't double-buy if we already hold this
        if already_holding(symbol):
            logger.info("Already holding %s — skipping duplicate buy", symbol)
            return {"status": "skipped", "reason": "already_holding"}

        # Check Alpaca supports the ticker
        price = get_latest_price(symbol)
        if price is None:
            return {"status": "skipped", "reason": "not_on_alpaca"}

        qty = calculate_qty(symbol, trade.get("value", 0))
        if qty == 0:
            return {"status": "skipped", "reason": "zero_qty"}

        return place_market_order(symbol, qty, "buy")

    # ── SELL logic ───────────────────────────────────────────────────────────
    elif side == "sell":
        pos = get_position(symbol)
        if not pos:
            logger.info("No position in %s to sell — skipping", symbol)
            return {"status": "skipped", "reason": "no_position"}

        qty = int(float(pos.get("qty", 1)))
        if qty <= 0:
            return {"status": "skipped", "reason": "zero_qty"}

        return place_market_order(symbol, qty, "sell")

    return {"status": "skipped", "reason": "unknown_side"}
