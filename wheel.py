"""
wheel.py — The Wheel Strategy (Cash-Secured Puts + Covered Calls)

How it works:
  STAGE 1 — SELL PUTS:
    Sell a cash-secured put 10% below current price, 2-4 weeks out.
    Collect premium. If expires worthless → sell another.
    If assigned (forced to buy) → move to Stage 2.

  STAGE 2 — SELL CALLS:
    Own the shares → sell covered call 10% above cost basis, 2-4 weeks out.
    Collect premium. If expires worthless → sell another.
    If called away (shares sold) → go back to Stage 1.

Rules:
  - Never sell a put without cash to cover assignment
  - Never sell a call below cost basis
  - Close early at 50% profit (buy back for 50% of premium received)
  - Run on the same stocks the copy-trading bot just bought
"""

import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta

import requests

from config import (
    ALPACA_KEY, ALPACA_SECRET, ALPACA_BASE_URL,
    CLICKUP_API_KEY, CLICKUP_LIST_ID, DB_FILE,
)

logger = logging.getLogger("wheel")

# ── Sessions ──────────────────────────────────────────────────────────────────

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

WHEEL_DB = "wheel_db.json"

# ── Manual wheel tickers (always run wheel on these regardless of politician trades) ──
# Add any stock you want to sell puts/calls on permanently
MANUAL_WHEEL_TICKERS = [
    "TSM",   # Taiwan Semiconductor — AI chip monopoly, 90% of advanced chips
]

# ── Wheel DB ──────────────────────────────────────────────────────────────────

def _load_wheel_db():
    if not os.path.exists(WHEEL_DB):
        return {"positions": {}, "premium_collected": 0.0, "cycles": []}
    with open(WHEEL_DB) as f:
        return json.load(f)


def _save_wheel_db(data):
    with open(WHEEL_DB, "w") as f:
        json.dump(data, f, indent=2)


def _record_premium(symbol, contract, premium, action):
    db = _load_wheel_db()
    db["premium_collected"] = db.get("premium_collected", 0) + premium
    db.setdefault("cycles", []).append({
        "symbol":    symbol,
        "contract":  contract,
        "premium":   premium,
        "action":    action,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _save_wheel_db(db)


def get_total_premium():
    return _load_wheel_db().get("premium_collected", 0.0)


# ── Alpaca Options API ────────────────────────────────────────────────────────

def _get_stock_price(symbol):
    try:
        resp = requests.get(
            f"https://data.alpaca.markets/v2/stocks/{symbol}/trades/latest",
            headers=DATA_HEADERS, timeout=10,
        )
        resp.raise_for_status()
        return float(resp.json()["trade"]["p"])
    except Exception as exc:
        logger.warning("Could not get price for %s: %s", symbol, exc)
        return None


def _get_options_chain(symbol, opt_type, dte_min=14, dte_max=28, limit=100):
    """Fetch options contracts for symbol within the expiry window."""
    now = datetime.now(timezone.utc)
    exp_min = (now + timedelta(days=dte_min)).strftime("%Y-%m-%d")
    exp_max = (now + timedelta(days=dte_max)).strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            f"https://data.alpaca.markets/v1beta1/options/snapshots/{symbol}",
            headers=DATA_HEADERS,
            params={
                "type":                 opt_type,
                "expiration_date_gte":  exp_min,
                "expiration_date_lte":  exp_max,
                "limit":                limit,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("snapshots", {})
    except Exception as exc:
        logger.warning("Options chain fetch failed for %s: %s", symbol, exc)
        return {}


def _parse_strike(contract_symbol):
    """Extract strike price from contract symbol e.g. AAPL260530P00200000 → 200.0"""
    try:
        return int(contract_symbol[-8:]) / 1000
    except Exception:
        return None


def _select_contract(contracts, target_strike, min_bid=0.05):
    """Find the contract closest to target_strike with a valid bid."""
    best = None
    best_diff = float("inf")
    for sym, snap in contracts.items():
        strike = _parse_strike(sym)
        if strike is None:
            continue
        bid = snap.get("latestQuote", {}).get("bp", 0) or 0
        ask = snap.get("latestQuote", {}).get("ap", 0) or 0
        if bid < min_bid:
            continue
        diff = abs(strike - target_strike)
        if diff < best_diff:
            best_diff = diff
            best = {
                "symbol": sym,
                "strike": strike,
                "bid":    bid,
                "ask":    ask,
                "mid":    round((bid + ask) / 2, 2),
            }
    return best


def _get_open_options_orders():
    """Get all open options orders from Alpaca."""
    try:
        resp = SESSION.get(
            f"{ALPACA_BASE_URL}/v2/orders",
            params={"status": "open", "asset_class": "us_option", "limit": 100},
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("Could not fetch open options orders: %s", exc)
        return []


def _get_options_positions():
    """Get current options positions from Alpaca."""
    try:
        resp = SESSION.get(f"{ALPACA_BASE_URL}/v2/positions")
        resp.raise_for_status()
        return [p for p in resp.json() if p.get("asset_class") == "us_option"]
    except Exception as exc:
        logger.warning("Could not fetch options positions: %s", exc)
        return []


def _get_stock_positions():
    """Get current stock (equity) positions from Alpaca."""
    try:
        resp = SESSION.get(f"{ALPACA_BASE_URL}/v2/positions")
        resp.raise_for_status()
        return [p for p in resp.json() if p.get("asset_class") == "us_equity"]
    except Exception as exc:
        logger.warning("Could not fetch stock positions: %s", exc)
        return []


def _place_options_order(contract_symbol, qty, side, limit_price):
    """Place an options limit order (sell to open or buy to close)."""
    limit_price = round(limit_price, 2)
    payload = {
        "symbol":        contract_symbol,
        "qty":           str(qty),
        "side":          side,
        "type":          "limit",
        "time_in_force": "day",
        "limit_price":   str(limit_price),
        "order_class":   "simple",
    }
    resp = SESSION.post(f"{ALPACA_BASE_URL}/v2/orders", json=payload)
    resp.raise_for_status()
    result = resp.json()
    logger.info(
        "Options order: %s %d x %s @ $%.2f — id=%s",
        side.upper(), qty, contract_symbol, limit_price, result.get("id"),
    )
    return result


# ── Stage 1: Sell Cash-Secured Put ───────────────────────────────────────────

def sell_cash_secured_put(symbol):
    """
    Sell 1 cash-secured put on symbol:
      - Strike ~10% below current price
      - Expiry 2-4 weeks out
      - Only if we have cash to cover assignment (100 * strike)
    Returns order result or None.
    """
    price = _get_stock_price(symbol)
    if not price:
        logger.warning("Wheel: could not get price for %s", symbol)
        return None

    target_strike = price * 0.90

    # Cash check — need 100 * strike to cover assignment
    try:
        acct = SESSION.get(f"{ALPACA_BASE_URL}/v2/account")
        acct.raise_for_status()
        cash = float(acct.json().get("cash", 0))
        required_cash = target_strike * 100
        if cash < required_cash:
            logger.info(
                "Wheel: not enough cash for %s CSP — need $%.0f have $%.0f",
                symbol, required_cash, cash,
            )
            return None
    except Exception as exc:
        logger.warning("Wheel: cash check failed: %s", exc)
        return None

    # Get options chain
    contracts = _get_options_chain(symbol, "put")
    if not contracts:
        logger.info("Wheel: no put contracts available for %s", symbol)
        return None

    contract = _select_contract(contracts, target_strike)
    if not contract:
        logger.info("Wheel: no suitable put contract found for %s", symbol)
        return None

    # Sell at mid price
    premium = contract["mid"]
    logger.info(
        "Wheel STAGE 1: Selling CSP %s | strike=$%.2f | premium=$%.2f/share ($%.2f/contract)",
        contract["symbol"], contract["strike"], premium, premium * 100,
    )

    try:
        result = _place_options_order(contract["symbol"], 1, "sell", premium)
        _record_premium(symbol, contract["symbol"], premium * 100, "sell_put")
        return result
    except Exception as exc:
        logger.error("Wheel: CSP order failed for %s: %s", symbol, exc)
        return None


# ── Stage 2: Sell Covered Call ────────────────────────────────────────────────

def sell_covered_call(symbol, qty, cost_basis):
    """
    Sell covered call on symbol:
      - Strike ~10% above cost_basis (never below cost basis)
      - Expiry 2-4 weeks out
      - Requires owning qty shares (must be >= 100 for 1 contract)
    Returns order result or None.
    """
    if qty < 100:
        logger.info(
            "Wheel: %s — only %d shares, need 100 for covered call", symbol, qty
        )
        return None

    target_strike = cost_basis * 1.10
    contracts_count = qty // 100

    contracts = _get_options_chain(symbol, "call")
    if not contracts:
        logger.info("Wheel: no call contracts available for %s", symbol)
        return None

    contract = _select_contract(contracts, target_strike)
    if not contract:
        logger.info("Wheel: no suitable call contract found for %s", symbol)
        return None

    # Safety: never sell call below cost basis
    if contract["strike"] < cost_basis:
        logger.warning(
            "Wheel: call strike $%.2f < cost basis $%.2f for %s — skipping",
            contract["strike"], cost_basis, symbol,
        )
        return None

    premium = contract["mid"]
    total_premium = premium * 100 * contracts_count

    logger.info(
        "Wheel STAGE 2: Selling CC %s | strike=$%.2f | premium=$%.2f/share ($%.2f total)",
        contract["symbol"], contract["strike"], premium, total_premium,
    )

    try:
        result = _place_options_order(contract["symbol"], contracts_count, "sell", premium)
        _record_premium(symbol, contract["symbol"], total_premium, "sell_call")
        return result
    except Exception as exc:
        logger.error("Wheel: CC order failed for %s: %s", symbol, exc)
        return None


# ── 50% Profit Close ──────────────────────────────────────────────────────────

def check_early_close():
    """
    Check all open short options positions.
    If current price is <= 50% of what we sold for → buy to close (lock in profit).
    """
    positions = _get_options_positions()
    closed = []

    for pos in positions:
        symbol   = pos["symbol"]
        qty      = abs(int(float(pos.get("qty", 0))))
        avg_cost = abs(float(pos.get("avg_entry_price", 0)))  # what we sold for
        cur_price = abs(float(pos.get("current_price", avg_cost)))

        # We sold (short), so profit = sold_price - current_price
        # Close early if current_price <= 50% of what we collected
        if avg_cost > 0 and cur_price <= avg_cost * 0.50:
            logger.info(
                "Wheel: 50%% profit hit on %s — closing early (sold $%.2f, now $%.2f)",
                symbol, avg_cost, cur_price,
            )
            try:
                result = _place_options_order(symbol, qty, "buy", cur_price * 1.05)
                closed.append(symbol)
                _record_premium(
                    symbol.split("2")[0], symbol,
                    (avg_cost - cur_price) * 100 * qty,
                    "early_close",
                )
            except Exception as exc:
                logger.error("Wheel: early close failed for %s: %s", symbol, exc)

    return closed


# ── Main Wheel Cycle ──────────────────────────────────────────────────────────

def run_wheel_cycle():
    """
    Main wheel cycle:
    1. Check for 50% profit closes
    2. For each stock position we own → try to sell covered call (Stage 2)
    3. For each stock recently bought by copy-trading → also try CSP on others (Stage 1)
    """
    logger.info("=== WHEEL CYCLE START ===")

    # 1. Close any 50% profit options first
    closed = check_early_close()
    if closed:
        logger.info("Wheel: closed early at 50%% profit: %s", ", ".join(closed))

    # 2. Stage 2 — sell covered calls on all stock positions we own
    stock_positions = _get_stock_positions()
    calls_sold = []
    for pos in stock_positions:
        symbol     = pos["symbol"]
        qty        = int(float(pos.get("qty", 0)))
        cost_basis = float(pos.get("avg_entry_price", 0))

        if qty < 100:
            continue  # need at least 100 shares for 1 contract

        # Don't sell call if we already have an open call on this symbol
        open_options = _get_options_positions()
        already_has_call = any(
            p["symbol"].startswith(symbol) and "C" in p["symbol"]
            for p in open_options
        )
        if already_has_call:
            logger.info("Wheel: %s already has open covered call — skipping", symbol)
            continue

        result = sell_covered_call(symbol, qty, cost_basis)
        if result:
            calls_sold.append(symbol)

    # 3. Stage 1 — sell cash-secured puts on top copy-trade stocks
    # Combines manually pinned tickers + most recently copied politician tickers
    top_tickers = list(dict.fromkeys(MANUAL_WHEEL_TICKERS + _get_top_copy_tickers(limit=3)))
    puts_sold = []
    for symbol in top_tickers:
        # Skip if we already own it (would do covered call instead)
        already_own = any(p["symbol"] == symbol for p in stock_positions)
        if already_own:
            continue

        # Skip if we already have an open put on this symbol
        open_options = _get_options_positions()
        already_has_put = any(
            p["symbol"].startswith(symbol) and "P" in p["symbol"]
            for p in open_options
        )
        if already_has_put:
            logger.info("Wheel: %s already has open put — skipping", symbol)
            continue

        result = sell_cash_secured_put(symbol)
        if result:
            puts_sold.append(symbol)

    total_premium = get_total_premium()
    logger.info(
        "=== WHEEL DONE — calls_sold=%s puts_sold=%s total_premium_collected=$%.2f ===",
        calls_sold, puts_sold, total_premium,
    )

    return {
        "calls_sold":      calls_sold,
        "puts_sold":       puts_sold,
        "early_closed":    closed,
        "total_premium":   total_premium,
    }


def _get_top_copy_tickers(limit=3):
    """Get the most recently copied tickers from trades_db.json."""
    if not os.path.exists(DB_FILE):
        return []
    try:
        with open(DB_FILE) as f:
            data = json.load(f)
        executed = data.get("executed", [])
        # Most recent buys
        buys = [t for t in executed if t.get("side") == "buy"]
        buys.sort(key=lambda x: x.get("copied_at", ""), reverse=True)
        seen = []
        for t in buys:
            ticker = t.get("ticker", "")
            if ticker and ticker not in seen:
                seen.append(ticker)
            if len(seen) >= limit:
                break
        return seen
    except Exception:
        return []


# ── Daily Wheel Summary ───────────────────────────────────────────────────────

def get_wheel_summary():
    """Returns a markdown summary of wheel strategy performance."""
    db = _load_wheel_db()
    total_premium = db.get("premium_collected", 0)
    cycles = db.get("cycles", [])

    # Count by action
    puts_sold  = sum(1 for c in cycles if c["action"] == "sell_put")
    calls_sold = sum(1 for c in cycles if c["action"] == "sell_call")
    closed     = sum(1 for c in cycles if c["action"] == "early_close")

    lines = [
        "## 🎡 Wheel Strategy Summary",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total Premium Collected | ${total_premium:,.2f} |",
        f"| Puts Sold | {puts_sold} |",
        f"| Calls Sold | {calls_sold} |",
        f"| Early Closes (50% profit) | {closed} |",
        f"| Total Contracts | {len(cycles)} |",
    ]

    if cycles:
        lines += ["", "### Recent Wheel Trades"]
        for c in cycles[-5:]:
            lines.append(
                f"- **{c['action'].upper()}** {c['symbol']} — "
                f"+${c['premium']:.2f} premium  _{c['timestamp'][:10]}_"
            )

    # Send to ClickUp
    if CLICKUP_API_KEY and total_premium > 0:
        try:
            requests.post(
                f"https://api.clickup.com/api/v2/list/{CLICKUP_LIST_ID}/task",
                headers={
                    "Authorization": CLICKUP_API_KEY,
                    "Content-Type":  "application/json",
                },
                json={
                    "name":        f"🎡 Wheel Update — ${total_premium:,.2f} premium collected",
                    "description": "\n".join(lines),
                    "status":      "complete",
                    "priority":    3,
                    "tags":        ["wheel-strategy"],
                },
                timeout=10,
            )
        except Exception:
            pass

    return "\n".join(lines)
