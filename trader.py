"""
trader.py — Execute trades on Alpaca paper account.

Supports:
  - Market & limit orders for stocks
  - Basic options contract placement (if Alpaca options enabled)
  - Position sizing based on portfolio equity
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


# ── Account ──────────────────────────────────────────────────────────────────

def get_account() -> dict:
    resp = SESSION.get(f"{ALPACA_BASE_URL}/v2/account")
    resp.raise_for_status()
    return resp.json()


def get_portfolio_value() -> float:
    acct = get_account()
    return float(acct.get("portfolio_value") or acct.get("equity", 10_000))


def get_positions() -> list[dict]:
    resp = SESSION.get(f"{ALPACA_BASE_URL}/v2/positions")
    resp.raise_for_status()
    return resp.json()


def get_position(symbol: str):
    try:
        resp = SESSION.get(f"{ALPACA_BASE_URL}/v2/positions/{symbol}")
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            return None
        raise


# ── Quote ────────────────────────────────────────────────────────────────────

def get_latest_price(symbol: str):
    """Fetch latest trade price from Alpaca market data."""
    try:
        resp = SESSION.get(
            f"https://data.alpaca.markets/v2/stocks/{symbol}/trades/latest",
            headers={
                "APCA-API-KEY-ID":     ALPACA_KEY,
                "APCA-API-SECRET-KEY": ALPACA_SECRET,
            }
        )
        resp.raise_for_status()
        return float(resp.json()["trade"]["p"])
    except Exception as exc:
        logger.warning("Price fetch failed for %s: %s", symbol, exc)
        return None


# ── Order sizing ─────────────────────────────────────────────────────────────

def calculate_qty(symbol: str, politician_amount_mid: float) -> int:
    """
    Determine how many shares to buy/sell.
    Uses TRADE_FRACTION of portfolio, capped to MIN/MAX_TRADE_USD.
    Optionally scales proportionally to the politician's disclosed amount.
    """
    portfolio = get_portfolio_value()
    target_usd = min(
        max(portfolio * TRADE_FRACTION, MIN_TRADE_USD),
        MAX_TRADE_USD,
    )

    price = get_latest_price(symbol)
    if not price or price <= 0:
        logger.warning("No price for %s — skipping", symbol)
        return 0

    qty = int(target_usd / price)
    return max(qty, 1)


# ── Orders ───────────────────────────────────────────────────────────────────

def place_market_order(symbol: str, qty: int, side: str) -> dict:
    """Place a market order. side = 'buy' | 'sell'."""
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
    logger.info("Order placed: %s %d %s — id=%s", side.upper(), qty, symbol, result.get("id"))
    return result


def close_position(symbol: str) -> dict:
    """Close entire existing position in symbol."""
    resp = SESSION.delete(f"{ALPACA_BASE_URL}/v2/positions/{symbol}")
    resp.raise_for_status()
    result = resp.json()
    logger.info("Closed position: %s", symbol)
    return result


# ── Main entry ───────────────────────────────────────────────────────────────

def execute_trade(trade: dict) -> dict:
    """
    Given a normalised trade dict from scraper.py, execute the equivalent
    order on Alpaca.

    Returns the Alpaca order result or raises on failure.
    """
    symbol     = trade["ticker"]
    side       = trade["side"]           # "buy" | "sell"
    asset_type = trade.get("asset_type", "stock")
    amount_mid = float(trade.get("value") or trade.get("amount_low", 0) or 0)

    if asset_type == "option":
        logger.info("Options trade for %s — executing as underlying stock order", symbol)
        # Alpaca options API requires contract symbol; fall back to stock for now
        # TODO: look up option chain and match contract

    if side == "sell":
        # Only sell if we actually hold the position
        pos = get_position(symbol)
        if not pos:
            logger.info("No position in %s to sell — skipping", symbol)
            return {"status": "skipped", "reason": "no_position"}
        qty = int(float(pos.get("qty", 1)))
    else:
        qty = calculate_qty(symbol, amount_mid)
        if qty == 0:
            return {"status": "skipped", "reason": "zero_qty"}

    return place_market_order(symbol, qty, side)
