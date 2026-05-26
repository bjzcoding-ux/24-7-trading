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

# ── Target Politicians (multi-politician support) ────────────────────────────
# Legacy single-politician vars (kept for backwards compat)
TARGET_POLITICIAN         = os.getenv("TARGET_POLITICIAN", "tim-moore")
TARGET_POLITICIAN_DISPLAY = os.getenv("TARGET_POLITICIAN_DISPLAY", "Tim Moore")
TARGET_POLITICIAN_ID      = os.getenv("TARGET_POLITICIAN_ID", "M001236")

# Multi-politician list — format: "ID:Display Name,ID:Display Name"
# e.g. "M001236:Tim Moore,K000389:Rohit Khanna,D000032:Byron Donalds"
_raw = os.getenv(
    "POLITICIANS",
    f"{TARGET_POLITICIAN_ID}:{TARGET_POLITICIAN_DISPLAY}"
)
POLITICIANS = []
for entry in _raw.split(","):
    entry = entry.strip()
    if ":" in entry:
        pid, display = entry.split(":", 1)
        POLITICIANS.append({"id": pid.strip(), "display": display.strip()})
    elif entry:
        POLITICIANS.append({"id": entry.strip(), "display": entry.strip()})

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

# ── ClickUp ──────────────────────────────────────────────────────────────────
CLICKUP_API_KEY = os.getenv("CLICKUP_API_KEY", "")
CLICKUP_LIST_ID = os.getenv("CLICKUP_LIST_ID", "901615120980")  # "24/7 Trading Bot" list

# ── Local DB / Logs ──────────────────────────────────────────────────────────
DB_FILE      = "trades_db.json"
LOG_FILE     = "logs/bot.log"
JOURNAL_DIR  = "journal"
