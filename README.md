# 24/7 Politician Copy Trading Bot 🤖📈

Automatically copies stock trades filed by US politicians on [Capitol Trades](https://www.capitoltrades.com) — executed on your **Alpaca paper trading** account.

---

## How it works

```
Every 30 min
    └─ Scrape Capitol Trades → filter by target politician
         └─ Find trades not yet in local DB
              └─ Execute equivalent order on Alpaca
                   └─ Log result to trades_db.json + logs/bot.log
```

---

## Target Politician

| Name | Party | Why |
|------|-------|-----|
| **Tim Moore** (default) | R – NC | Most active trader in 2026, last trade 2026-05-18 |
| Warren Davidson | R – OH | **#1 performer 2025** — 78.8% return |
| Gil Cisneros | D – CA | Highest trade volume ($30.7M), 1,295 trades |

Change target in `.env`:
```env
TARGET_POLITICIAN=warren-davidson
TARGET_POLITICIAN_DISPLAY=Warren Davidson
```

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure credentials
```bash
cp .env.example .env
# Edit .env with your Alpaca keys (already set if you received this configured)
```

### 3. Run
```bash
# Single run (test)
python main.py --once

# Run forever (checks every 30 min)
python main.py

# Dashboard snapshot
python dashboard.py
```

### 4. Run as background service (macOS launchd)
```bash
# Add to cron (checks every 30 min):
crontab -e
*/30 * * * * cd /path/to/24-7-trading && python main.py --once >> logs/cron.log 2>&1
```

---

## Files

| File | Purpose |
|------|---------|
| `main.py` | Bot entry point & scheduler |
| `scraper.py` | Capitol Trades HTML scraper |
| `trader.py` | Alpaca API interface |
| `db.py` | Local trade deduplication store |
| `config.py` | All settings (loaded from `.env`) |
| `dashboard.py` | CLI status & P&L snapshot |
| `trades_db.json` | Auto-created — tracks copied trades |
| `logs/bot.log` | Auto-created — full run log |

---

## Alpaca Account

- **Mode:** Paper trading (no real money at risk)
- **Endpoint:** `https://paper-api.alpaca.markets`
- **Trade sizing:** 5% of portfolio per trade, capped at $5,000

---

## Disclaimer

This bot is for **paper trading / educational purposes only**. Political trade disclosures are lagged (up to 45 days by law). Past performance of politicians' portfolios does not guarantee future returns. Not financial advice.
