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
TRADE_FRACTION  = float(os.getenv("TRADE_FRACTION", 0.05))   # 5% of portfolio
MIN_TRADE_USD   = float(os.getenv("MIN_TRADE_USD",  100))
MAX_TRADE_USD   = float(os.getenv("MAX_TRADE_USD",  5000))

# ── Scheduler ────────────────────────────────────────────────────────────────
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", 30))

# ── Lookback window ──────────────────────────────────────────────────────────
# Only process trades FILED within the last N days.
# Keeps the bot focused on genuinely new disclosures, not old history.
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", 30))

# ── Capitol Trades ───────────────────────────────────────────────────────────
CAPITOL_TRADES_BASE  = "https://www.capitoltrades.com"
TRADES_URL           = f"{CAPITOL_TRADES_BASE}/trades"

# ── Local DB ─────────────────────────────────────────────────────────────────
DB_FILE = "trades_db.json"
LOG_FILE = "logs/bot.log"
