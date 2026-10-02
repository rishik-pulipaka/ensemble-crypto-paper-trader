"""Swing system config — single source of truth for the long-only daily-bar
trend system (swing-v1). Separate from intraday config.py; nothing here
touches the 1-min ensemble.

Design: long-only trend following on DAILY bars. Parameters are CANONICAL
(from the academic literature / classic turtle specs), fixed BEFORE seeing
results. Nothing is optimized. The whole development window is therefore
out-of-sample for these fixed parameters.
"""
from __future__ import annotations

from datetime import datetime, timezone

# ---------------------------------------------------------------- data
SWING_PAIRS = ["BTC-USD", "ETH-USD"]
SWING_GRANULARITY = 86400          # daily bars
SWING_DB_PAIR_SUFFIX = ":1D"       # stored as "BTC-USD:1D" in market.db
SWING_HISTORY_START = datetime(2015, 1, 1, tzinfo=timezone.utc)
WARMUP_DAYS = 400                  # indicator warmup before any signal

# ---------------------------------------------------------------- lockbox
# FRESH quarantine for the swing system: most recent 12 months of daily bars.
# Development + walk-forward NEVER see ts >= this. One-shot evaluation only
# via swing/evaluate_holdout.py (marker-guarded), and only for a system that
# already met the promising bar on its own OOS data.
SWING_HOLDOUT_START_TS = int(datetime(2025, 10, 2, tzinfo=timezone.utc).timestamp())

# ---------------------------------------------------------------- costs (realistic retail; small at this horizon, modeled anyway)
SWING_FEE_PER_SIDE = 0.005         # 50 bps
SWING_SLIPPAGE_PER_SIDE = 0.0005   # 5 bps

# ---------------------------------------------------------------- sizing
# Risk-based sizing (turtle method): size so the INITIAL stop distance
# risks ~1% of equity. notional = equity * 0.01 / stop_dist_frac, capped
# at 50% of equity (no leverage). This keeps risk-per-trade consistent
# with the stop structure; vol-targeting alone allowed ~10%/trade because
# a 3xATR stop on 50%-of-equity notional is far wider than the vol target
# implies. That inconsistency is a design bug, not a parameter choice.
STARTING_BANKROLL = 10_000.0
RISK_PER_TRADE_FRAC = 0.01
MAX_NOTIONAL_FRAC = 0.5            # cap each position at 50% of equity (no leverage,
                                   # max 100% combined across the 2 pairs)

# ---------------------------------------------------------------- variant A: time-series momentum (Moskowitz-Ooi-Pedersen)
TSMOM_FORMATION_DAYS = 365         # 12-month formation...
TSMOM_SKIP_DAYS = 21               # ...skipping the most recent month
# => signal return = close[t] / close[t-344] - 1, evaluated at month-end

# ---------------------------------------------------------------- variant B: Donchian breakout (turtle-style, long-only)
DONCHIAN_ENTRY = 100               # enter above max(high, 100d)
DONCHIAN_EXIT = 50                 # exit below min(low, 50d)
ATR_PERIOD = 20
ATR_TRAIL_MULT = 3.0               # trailing stop = highest close - 3*ATR(20)

# ---------------------------------------------------------------- variant C: dual moving-average cross (daily)
MA_FAST = 50
MA_SLOW = 200                      # long when SMA50 > SMA200 and close > SMA200

# ---------------------------------------------------------------- risk (hard limits)
SWING_MAX_DAILY_LOSS_FRAC = 0.03   # halt new entries rest of day if hit (daily loop:
                                   # effectively halts until next signal day)

# ---------------------------------------------------------------- validation bars
MIN_OOS_TRADES = 100               # below this: KILL on statistical power, no pass
PROMISING_SHARPE = 1.0
PROMISING_PF = 1.2
PROMISING_MAX_DD = 0.30
