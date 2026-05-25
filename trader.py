"""
trader.py — Execute trades on Alpaca paper account.

Features:
  - Limit orders (0.2% above ask for buys — better fills than market)
  - Cash reserve check (never buy if cash < 20% of portfolio)
  - Stop loss monitoring (auto-sell any position down 8%+)
  - Position-based deduplication (no double-buys)
  - Graceful skip for foreign/OTC tickers not on Alpaca
"""

import logging
import requests

from config import (
    ALPACA_KEY, ALPACA_SECRET, ALPACA_BASE_URL,
    TRADE_FRACTION, MIN_TRADE_USD, MAX_TRADE_USD,
    STOP_LOSS_PCT, CASH_RESERVE_PCT, LIMIT_ORDER_SLIP,
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

# In-memory position cache for the lifetime of one bot run
_positions_cache: dict = {}
_positions_loaded       = False


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
    return float(get_account().get("portfolio_value") or 10_000)


def get_cash() -> float:
    return float(get_account().get("cash") or 0)


def get_positions() -> list:
    resp = SESSION.get(f"{ALPACA_BASE_URL}/v2/positions")
    resp.raise_for_status()
    return resp.json()


def get_position(symbol: str):
    _load_positions()
    return _positions_cache.get(symbol.upper())


def already_holding(symbol: str) -> bool:
    return get_position(symbol) is not None


# ── Cash reserve check ───────────────────────────────────────────────────────

def has_buying_power() -> bool:
    """
    Returns True only if cash is above the CASH_RESERVE_PCT threshold.
    e.g. with $100K portfolio and 20% reserve, we need >$20K cash to buy.
    """
    try:
        acct      = get_account()
        portfolio = float(acct.get("portfolio_value") or 10_000)
        cash      = float(acct.get("cash") or 0)
        reserve   = portfolio * CASH_RESERVE_PCT
        ok        = cash > reserve
        if not ok:
            logger.info(
                "Cash reserve check FAILED — cash=$%.0f, required>$%.0f (%.0f%% of $%.0f portfolio)",
                cash, reserve, CASH_RESERVE_PCT * 100, portfolio,
            )
        return ok
    except Exception as exc:
        logger.warning("Cash reserve check error: %s", exc)
        return False


# ── Quote ────────────────────────────────────────────────────────────────────

def get_latest_price(symbol: str):
    """Returns latest trade price, or None if symbol not on Alpaca."""
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
            logger.info("Ticker %s not on Alpaca (foreign/OTC) — skipping", symbol)
        else:
            logger.warning("Price fetch error for %s: %s", symbol, e)
        return None
    except Exception as exc:
        logger.warning("Price fetch failed for %s: %s", symbol, exc)
        return None


def get_latest_quote(symbol: str):
    """Returns (ask_price, bid_price) or (None, None)."""
    try:
        resp = requests.get(
            f"https://data.alpaca.markets/v2/stocks/{symbol}/quotes/latest",
            headers=DATA_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        q = resp.json()["quote"]
        return float(q.get("ap") or q.get("bp") or 0), float(q.get("bp") or 0)
    except Exception:
        # Fall back to latest trade price
        price = get_latest_price(symbol)
        return price, price


# ── Order sizing ─────────────────────────────────────────────────────────────

def calculate_qty(symbol: str, price: float) -> int:
    """Shares to buy = TRADE_FRACTION of portfolio, clamped to MIN/MAX."""
    portfolio  = get_portfolio_value()
    target_usd = min(max(portfolio * TRADE_FRACTION, MIN_TRADE_USD), MAX_TRADE_USD)
    qty        = int(target_usd / price) if price > 0 else 0
    return max(qty, 1)


# ── Orders ───────────────────────────────────────────────────────────────────

def place_limit_order(symbol: str, qty: int, side: str, limit_price: float) -> dict:
    """Place a day limit order."""
    limit_price = round(limit_price, 2)
    payload = {
        "symbol":        symbol,
        "qty":           str(qty),
        "side":          side,
        "type":          "limit",
        "time_in_force": "day",
        "limit_price":   str(limit_price),
    }
    resp = SESSION.post(f"{ALPACA_BASE_URL}/v2/orders", json=payload)
    resp.raise_for_status()
    result = resp.json()
    logger.info(
        "Limit order placed: %s %d %s @ $%.2f — id=%s",
        side.upper(), qty, symbol, limit_price, result.get("id"),
    )
    # Update local cache
    if side == "buy":
        _positions_cache[symbol.upper()] = {"symbol": symbol, "qty": str(qty)}
    elif side == "sell" and symbol.upper() in _positions_cache:
        del _positions_cache[symbol.upper()]
    return result


def place_market_order(symbol: str, qty: int, side: str) -> dict:
    """Market order — used for stop-loss exits where speed matters."""
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
        "Market order placed: %s %d %s — id=%s",
        side.upper(), qty, symbol, result.get("id"),
    )
    if side == "sell" and symbol.upper() in _positions_cache:
        del _positions_cache[symbol.upper()]
    return result


# ── Stop Loss ─────────────────────────────────────────────────────────────────

def check_stop_losses() -> list:
    """
    Scan all open positions. Auto-sell any that are down >= STOP_LOSS_PCT.
    Returns list of symbols that were stopped out.
    """
    stopped = []
    try:
        positions = get_positions()
    except Exception as exc:
        logger.warning("Could not fetch positions for stop-loss check: %s", exc)
        return stopped

    for pos in positions:
        symbol  = pos["symbol"]
        pl_pct  = float(pos.get("unrealized_plpc", 0))   # e.g. -0.09 = -9%
        pl_usd  = float(pos.get("unrealized_pl", 0))
        qty     = int(float(pos.get("qty", 0)))

        if pl_pct <= -STOP_LOSS_PCT:
            logger.warning(
                "STOP LOSS triggered: %s is down %.1f%% ($%.2f) — selling %d shares",
                symbol, pl_pct * 100, pl_usd, qty,
            )
            try:
                place_market_order(symbol, qty, "sell")
                stopped.append(symbol)
            except Exception as exc:
                logger.error("Stop loss sell failed for %s: %s", symbol, exc)

    if stopped:
        logger.info("Stop losses executed: %s", ", ".join(stopped))
    else:
        logger.info("Stop loss check: all positions OK (threshold: -%.0f%%)", STOP_LOSS_PCT * 100)

    return stopped


# ── Main entry ───────────────────────────────────────────────────────────────

def execute_trade(trade: dict) -> dict:
    """
    Execute a single politician trade on Alpaca.
    Returns order result or {"status": "skipped", "reason": ...}.
    """
    symbol = trade["ticker"].upper()
    side   = trade["side"]

    # ── BUY ──────────────────────────────────────────────────────────────────
    if side == "buy":

        # Don't double-buy
        if already_holding(symbol):
            logger.info("Already holding %s — skipping duplicate buy", symbol)
            return {"status": "skipped", "reason": "already_holding"}

        # Cash reserve check
        if not has_buying_power():
            return {"status": "skipped", "reason": "cash_reserve_limit"}

        # Get ask price
        ask, _ = get_latest_quote(symbol)
        if ask is None or ask <= 0:
            return {"status": "skipped", "reason": "not_on_alpaca"}

        # Limit price = ask + 0.2% (ensures fill while avoiding overpay)
        limit_price = ask * (1 + LIMIT_ORDER_SLIP)
        qty         = calculate_qty(symbol, ask)
        if qty == 0:
            return {"status": "skipped", "reason": "zero_qty"}

        logger.info(
            "Placing BUY limit: %s x%d @ $%.2f (ask=$%.2f + %.1f%%)",
            symbol, qty, limit_price, ask, LIMIT_ORDER_SLIP * 100,
        )
        return place_limit_order(symbol, qty, "buy", limit_price)

    # ── SELL ─────────────────────────────────────────────────────────────────
    elif side == "sell":
        pos = get_position(symbol)
        if not pos:
            logger.info("No position in %s to sell — skipping", symbol)
            return {"status": "skipped", "reason": "no_position"}

        qty = int(float(pos.get("qty", 1)))
        if qty <= 0:
            return {"status": "skipped", "reason": "zero_qty"}

        # Use limit slightly below bid for sells
        _, bid = get_latest_quote(symbol)
        if bid and bid > 0:
            limit_price = bid * (1 - LIMIT_ORDER_SLIP)
            return place_limit_order(symbol, qty, "sell", limit_price)
        else:
            return place_market_order(symbol, qty, "sell")

    return {"status": "skipped", "reason": "unknown_side"}
