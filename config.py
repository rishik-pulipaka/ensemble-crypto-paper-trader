"""Single source of truth for every threshold in the bot.

Nothing else in the codebase hard-codes a tunable. Change it here.
All money figures are fractions unless noted.
"""

# ---------------------------------------------------------------- data
PAIRS = ["ETH-USD"]  # v5: ETH only. Diagnostic showed ETH momentum gross
                     # +$120.60/trade vs BTC +$45.72 (1h, zero fees).
                     # Hypothesis: edge concentrates in less-efficient,
                     # higher-volatility markets.
GRANULARITY_SECONDS = 3600         # v4: 1-hour bars (resampled from 1-min).
                                  # Hypothesis: wider stops -> smaller notional
                                  # for same risk -> smaller absolute fee drag.
HISTORY_YEARS = 2                 # target depth for the initial backfill
DB_PATH = "data/market.db"        # relative to project root (always 1-min)

# ---------------------------------------------------------------- costs
# Taker-equivalent fees + slippage, applied per side.
# v2 uses REALISTIC retail costs: 50 bps/side fee (midpoint of the 40-60 bps
# retail taker range on major venues) + 10 bps/side slippage.
# Round-trip drag ~= 120 bps. v1's 15 bps/side was optimistic; any version
# that cannot survive realistic costs is dead on arrival in production.
FEE_PER_SIDE = 0.005
SLIPPAGE_PER_SIDE = 0.001

# ---------------------------------------------------------------- v3: maker execution
# (retained for evaluate_holdout.py and future maker experiments)
MAKER_STRATEGY = "vwap_mr"        # single regime-specialist (mean reversion)
MAKER_REGIMES = ["chop"]          # only trade chop regimes
MAKER_FEE_PER_SIDE = 0.001        # 10 bps maker (passive fills)
MAKER_STOP_FEE_PER_SIDE = 0.005   # 50 bps taker (urgent stop exits)
MAKER_OFFSET = 0.0005             # limit 5 bps better than signal price
MAKER_MAX_WAIT_BARS = 4           # resting order valid 4 bars, then cancel

# ---------------------------------------------------------------- v4: single momentum, hourly
# Edge hypothesis: start from the best GROSS edge (momentum_roc +$42-46/trade
# gross) and minimize fee drag via timeframe. Longer timeframe -> wider stops
# -> smaller notional for the same risk dollars -> smaller absolute fees.
# v4 tests momentum_roc alone on 1-hour bars with honest taker execution.
EXECUTION_MODE = "taker"          # "taker" | "maker"
SINGLE_STRATEGY = "momentum_roc"  # None = ensemble mode; set = single-strategy
SINGLE_REGIMES = ["trend", "chop"]

# ---------------------------------------------------------------- strategies
# v2: bar counts preserved from v1 EXCEPT VWAP_WINDOW, which is rescaled to
# keep its 12h wall-time meaning on 15-min bars (48 x 15min = 12h). The
# hypothesis under test is timeframe, not parameter values.
DONCHIAN_PERIOD = 20          # bars for channel high/low
VWAP_WINDOW = 48              # rolling window (bars) for session VWAP proxy; 48 = 12h @15m
VWAP_Z_ENTRY = 2.0            # |z| >= this to vote
RSI_PERIOD = 14
ROC_PERIOD = 12               # rate-of-change lookback (bars)
MOMENTUM_MIN_ROC = 0.002      # 0.2% move over ROC_PERIOD to vote
ATR_PERIOD = 14
ATR_EXPANSION_MULT = 1.5      # range > ATR*mult => expansion vote
VOLUME_LOOKBACK = 20
VOLUME_MULT = 1.5             # volume > SMA*mult => participation

# ---------------------------------------------------------------- regime
ADX_PERIOD = 14
ADX_TREND_THRESHOLD = 25.0    # ADX >= this => trend regime, else chop

# Regime weight multipliers: applied to a strategy's base weight.
# Trend strategies only vote in trend; mean-reversion only in chop.
# Momentum / volatility / volume vote in both, scaled by regime.
REGIME_WEIGHT_MULT = {
    "trend":         {"trend": 1.0, "mean_reversion": 0.0, "momentum": 1.0,
                      "volatility": 0.7, "volume": 0.8},
    "chop":          {"trend": 0.0, "mean_reversion": 1.0, "momentum": 0.6,
                      "volatility": 0.8, "volume": 1.0},
}

# ---------------------------------------------------------------- confluence
MIN_AGREE = 3                 # minimum strategies agreeing in one direction
SCORE_THRESHOLD = 0.45        # |weighted score| as fraction of max possible

# ---------------------------------------------------------------- risk (HARD LIMITS - the risk manager enforces these;
# there is no flag, env var, or config path that disables them)
RISK_PER_TRADE = 0.01         # 1% of bankroll risked per trade (cap)
MAX_POSITIONS = 3             # max concurrent open positions
MAX_DAILY_LOSS = 0.03         # halt all trading if down 3% on the day
TP_MULTIPLE = 3.0             # v6: take profit at 3R (was 2R).
                              # Hypothesis: momentum profits come from fat
                              # tails; 2R cuts winners short. 3R lets the
                              # edge compound; lower win rate compensated
                              # by larger winners.
STARTING_BANKROLL = 10000.0   # paper starting equity (USD)

# ---------------------------------------------------------------- backtest
WALK_FORWARD_SPLITS = [0.40, 0.60, 0.80]  # expanding-train / next-segment-test
MIN_TRADES_FOR_STATS = 30     # fewer OOS trades => stats unreliable, say so

# ---------------------------------------------------------------- LOCKBOX
# FINAL HOLDOUT — quarantined 2026-10-01. This data is LOCKED.
# Range: 2026-06-14T16:29:00Z -> 2026-10-02 (most recent ~15% of history,
# 157k+ 1-min bars per pair; larger than 3 months, per the 15%-or-3mo rule).
# NO version may be designed, tuned, or evaluated on this data during the
# iteration loop — not even once, not even for "just checking."
# The ONLY permitted access is evaluate_holdout.py, which runs ONCE for a
# version that has already met the full PROMISING bar on its own OOS data,
# and which refuses to run a second time (marker file .holdout_used).
# Touching this boundary to peek at holdout data invalidates the experiment.
HOLDOUT_START_TS = 1781454540  # 2026-06-14T16:29:00Z; DO NOT CHANGE

# ---------------------------------------------------------------- paper engine
PAPER_POLL_SECONDS = 60
PAPER_DB_PATH = "data/paper.db"
DASHBOARD_PORT = 8787
