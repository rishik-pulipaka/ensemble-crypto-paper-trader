"""Kalshi gauntlet config. Binary prediction-market backtests. Paper only.

No API keys, no credentials, no trading code anywhere in this module.
All data comes from Kalshi's PUBLIC unauthenticated market-data endpoints.
"""
import math
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "kalshi.db")
MARKER_DIR = os.path.join(BASE_DIR, "kalshi")

API_BASE = "https://api.elections.kalshi.com/trade-api/v2"

# Lockbox: markets expiring on/after this timestamp are quarantined.
# 2026-07-02T00:00:00Z. The ONLY permitted access is evaluate_holdout.py,
# which runs AT MOST ONCE (marker file) for a version meeting the bar.
LOCKBOX_START_TS = 1782950400

# Dev universe: series with meaningful settled history + volume.
# NOTE (2026-10-02): KXNBA/KXNHL are now championship FUTURES (all expire
# after the lockbox). Game moneylines live under KXNBAGAME/KXNHLGAME.
# KXBTC/KXETH/KXINX DROPPED: 40k+ markets paginated, zero expired before
# the lockbox (all recent); pagination is a black hole for thin markets.
SERIES = [
    "KXNFLGAME",  # NFL moneylines
    "KXNBAGAME",  # NBA moneylines
    "KXNHLGAME",  # NHL moneylines
    "KXFED",      # Fed decisions
    "KXCPI",      # CPI prints
]

MIN_VOLUME = 100.0          # contracts; skip thinner markets
MAX_TTE_DAYS = 14           # entry only within 14 days of expiration
CANDLE_INTERVAL = 1440      # daily candles

# Kalshi taker fee schedule (effective 2026-07-07): ceil(0.07 * P * (1-P)),
# P in dollars, result in cents. Maker is $0 on standard markets; every
# backtest here assumes TAKER fills (conservative).
def taker_fee(price_dollars: float) -> float:
    return math.ceil(0.07 * price_dollars * (1.0 - price_dollars) * 100.0) / 100.0


# ---- Version definitions (params frozen before seeing results) ----
V1 = {
    "name": "kalshi-v1",
    "hypothesis": "Favorite-longshot bias fade: crowd underprices high-probability "
                  "contracts. Buy YES the first day yes_ask closes >= 85c within "
                  "14 days of expiry. Hold to settlement.",
    "side": "buy_yes",
    "entry_price_threshold": 0.85,
    "entry_price_field": "yes_ask",
}

V2 = {
    "name": "kalshi-v2",
    "hypothesis": "V1 + market-selection filters learned from V1 losers "
                  "(fit on first 70% of dev by expiry, evaluated on last 30%).",
    "side": "buy_yes",
    "entry_price_threshold": 0.85,
    "entry_price_field": "yes_ask",
    # filters filled in after V1 diagnostics; see strategies.py
}

V3 = {
    "name": "kalshi-v3",
    "hypothesis": "Tail-selling: sell far-OTM YES (bid <= 15c), harvest the "
                  "longshot overpricing premium. Report raw AND with the "
                  "measured -8.6c adverse-selection haircut (50thycal).",
    "side": "sell_yes",
    "entry_price_threshold": 0.15,
    "entry_price_field": "yes_bid",
    "adverse_selection_haircut": 0.086,
}

V4 = {
    "name": "kalshi-v4",
    "hypothesis": "Event-type specialization: trade only the categories V1-V3 "
                  "show the crowd prices worst.",
    "side": "buy_yes",
    "entry_price_threshold": 0.85,
    "entry_price_field": "yes_ask",
}

V5 = {
    "name": "kalshi-v5",
    "hypothesis": "Ensemble of whatever actually worked in V1-V4.",
    "side": "ensemble",
}
