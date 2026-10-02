"""Single source of truth for every threshold in the bot.

Nothing else in the codebase hard-codes a tunable. Change it here.
All money figures are fractions unless noted.
"""

# ---------------------------------------------------------------- data
PAIRS = ["BTC-USD", "ETH-USD"]
GRANULARITY_SECONDS = 900         # v2: 15-minute bars (resampled from 1-min).
                                  # Hypothesis: bigger per-trade moves make the
                                  # fixed bps fee a smaller fraction of gross.
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
TP_MULTIPLE = 2.0             # take profit at 2R
STARTING_BANKROLL = 10000.0   # paper starting equity (USD)

# ---------------------------------------------------------------- backtest
WALK_FORWARD_SPLITS = [0.40, 0.60, 0.80]  # expanding-train / next-segment-test
MIN_TRADES_FOR_STATS = 30     # fewer OOS trades => stats unreliable, say so

# ---------------------------------------------------------------- paper engine
PAPER_POLL_SECONDS = 60
PAPER_DB_PATH = "data/paper.db"
DASHBOARD_PORT = 8787
