"""
config.py — Load all settings from .env
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Alpaca ──────────────────────────────────────────────────────────────────
ALPACA_KEY        = os.getenv("ALPACA_KEY")
ALPACA_SECRET     = os.getenv("ALPACA_SECRET")
ALPACA_BASE_URL   = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

# ── Target Politician ────────────────────────────────────────────────────────
TARGET_POLITICIAN         = os.getenv("TARGET_POLITICIAN", "tim-moore")
TARGET_POLITICIAN_DISPLAY = os.getenv("TARGET_POLITICIAN_DISPLAY", "Tim Moore")
# Capitol Trades internal politician ID (from RSC payload research)
# Tim Moore = M001236 | Warren Davidson = D000626
TARGET_POLITICIAN_ID      = os.getenv("TARGET_POLITICIAN_ID", "M001236")

# ── Trade Sizing ─────────────────────────────────────────────────────────────
TRADE_FRACTION  = float(os.getenv("TRADE_FRACTION", 0.05))   # 5% of portfolio per trade
MIN_TRADE_USD   = float(os.getenv("MIN_TRADE_USD",  100))
MAX_TRADE_USD   = float(os.getenv("MAX_TRADE_USD",  5000))

# ── Risk Management ───────────────────────────────────────────────────────────
STOP_LOSS_PCT    = float(os.getenv("STOP_LOSS_PCT",   0.08))  # 8% — auto-sell if position drops 8%
CASH_RESERVE_PCT = float(os.getenv("CASH_RESERVE_PCT", 0.20)) # 20% — never deploy below 20% cash
LIMIT_ORDER_SLIP = float(os.getenv("LIMIT_ORDER_SLIP", 0.002)) # 0.2% above ask for limit buys

# ── Scheduler ────────────────────────────────────────────────────────────────
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", 30))

# ── Lookback window ──────────────────────────────────────────────────────────
# Only process trades FILED within the last N days.
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", 30))

# ── Capitol Trades ───────────────────────────────────────────────────────────
CAPITOL_TRADES_BASE  = "https://www.capitoltrades.com"
TRADES_URL           = f"{CAPITOL_TRADES_BASE}/trades"

# ── Local DB / Logs ──────────────────────────────────────────────────────────
DB_FILE      = "trades_db.json"
LOG_FILE     = "logs/bot.log"
JOURNAL_DIR  = "journal"
