# Ensemble Crypto Paper Trader — v1

A paper-only systematic trading bot for BTC/ETH. Five strategies on genuinely
different logic vote through a regime-aware confluence engine; a hard-coded
risk manager caps every loss. It simulates fills against real market data.
It has never placed, and cannot place, a real order.

## KILL CRITERIA (read first)

**If walk-forward expectancy after fees is <= 0, the strategy set is DEAD.
Do not paper trade it. Do not fund it. Do not "tweak it until it works"
(that is curve-fitting).** `run_backtest.py` enforces this: it exits code 2
and prints KILL. `paper.py --calibrate` refuses to write tradable weights
under the same condition.

A dead backtest is the system working as designed. Most strategy sets die here.

## What it is

- **Data**: 1-minute BTC/ETH bars from Coinbase public REST (no auth, no keys).
  Cached in SQLite (`data/market.db`).
- **Strategies** (`strategies/library.py`):
  - `donchian_trend` — 20-bar channel breakout (votes only in trend regimes)
  - `vwap_mr` — 12h rolling VWAP z-score mean reversion (votes only in chop)
  - `momentum_roc` — 12-bar rate-of-change + RSI(14) filter (both regimes)
  - `vol_expansion` — range > 1.5x ATR(14) in the bar's direction (both)
  - `volume_participation` — volume > 1.5x 20-bar average (both)
- **Regime filter** (`regime.py`): ADX(14) >= 25 = trend, else chop.
- **Confluence** (`confluence.py`): weights = max(0, per-strategy per-regime
  expectancy) from walk-forward training, normalized. Entry needs >= 3 of 5
  strategies agreeing AND weighted score >= 45% of max. Sizing is half-Kelly
  from train stats, capped at 1% risk/trade, floored at 0 (no edge = no trade).
- **Risk** (`risk.py`): max 1% risk/trade, max 3 concurrent positions, 3%
  max daily loss halts all trading until next day, every position carries a
  stop (invalidation level) and 2R take-profit. **There is no flag to disable
  any of this.** Loosening risk requires editing risk.py on purpose.
- **Backtester** (`backtest.py`): indicators vectorized, bar loop for fills.
  Walk-forward: expanding train at 40/60/80% splits, each tested on the next
  unseen segment. Models taker-equivalent fees (15 bps/side) + slippage
  (5 bps/side). No-lookahead enforced by a central one-bar shift in
  `Strategy.generate()` and proven by `tests/test_no_lookahead.py`.
- **Paper engine** (`paper.py`): polls live bars every 60s, runs the full
  stack, simulates fills, persists to `data/paper.db`. Calibrate weights first
  with `paper.py --calibrate` (refuses if backtest is dead).
- **Dashboard** (`dashboard.py`): stdlib HTTP server, dark terminal UI.
  Every number comes from `data/paper.db`. Nothing mocked.

## Runbook

```bash
cd ~/workspace/trading-bot
pip install -r requirements.txt

# 1. prove no-lookahead
python3 tests/test_no_lookahead.py

# 2. backfill data + walk-forward backtest (takes a while first run)
python3 run_backtest.py
#    --pairs BTC-USD,ETH-USD --years 2 --bankroll 10000
# Exit 0 = PASS (positive OOS expectancy). Exit 2 = KILL (dead, stop here).

# 3. calibrate paper weights from history (refuses if backtest dead)
python3 paper.py --calibrate

# 4. start the paper loop (single cycle, good for schedulers)
python3 paper.py --once
#    or continuous:
python3 paper.py

# 5. dashboard (separate terminal)
python3 dashboard.py   # -> http://127.0.0.1:8787

# QA scripts (all must pass; they did at v1 sign-off)
python3 qa_checklist.py          # strategies sane on real data, regime switches
python3 qa_risk_confluence.py    # hand-verified confluence math + risk limits
python3 qa_paper.py              # paper persistence, no dup fills, reconciliation

# Faster initial backfill (6 workers; the fetcher in data/ is single-threaded)
python3 scripts/parallel_backfill.py --years 2 --workers 6
```

## Honest limitations

- Backtests lie by omission: no market impact modeled, fills assume the
  bar's range was tradable at our size (true at tiny size, false at scale).
- Fees are estimates. Real venues differ; re-check before any live use.
- Walk-forward reduces overfitting; it does not eliminate it. Regime
  changes (a strategy that worked 2024-2026) can still break.
- Crypto trades 24/7; the paper loop must actually run 24/7 to match the
  backtest. Gaps = divergence from tested behavior.
- **There is no live-trading code path in v1.** Adding one later means new
  code, new review, and real API keys that never live in this repo. Paper
  profitability does not imply live profitability.
- This is a research/education project, not financial advice. Expect it to
  fail the kill criteria. That outcome is valuable: it costs $0 to learn.

---

# Swing system (swing-v1) — long-only daily trend following

A NEW system, not v7 of the intraday loop. It follows the v1-v6 trajectory
gradient to its logical conclusion: longer holding periods where retail fees
stop being the binding constraint.

- **Data**: daily BTC/ETH bars from Coinbase public REST (no auth), 2015 to
  now, cached in `data/market.db` as `BTC-USD:1D` / `ETH-USD:1D`.
- **Variants** (`swing/signals.py`, all canonical parameters, fixed before
  seeing results — nothing optimized):
  - `tsmom` — 12-month (skip 1m) time-series momentum, monthly rebalance
    (Moskowitz-Ooi-Pedersen)
  - `donchian` — 100d breakout entry / 50d breakdown exit (turtle-style)
  - `ma_cross` — daily SMA50/SMA200 cross, long-only
- **Sizing** (`swing/engine.py`): turtle method — risk 1% of equity over the
  initial 3xATR(20) stop distance, capped at 50% notional per position
  (max one per pair, no leverage).
- **Exits**: signal reversal OR 3xATR trailing stop (ratcheted up only),
  whichever first. No profit targets.
- **Costs**: 50 bps/side fee + 5 bps/side slippage, both sides.
- **Execution**: signal decided at close of bar t-1, filled at open of bar t.
  Proven by `swing/qa_swing.py` (6/6 checks).
- **Validation**: `python3 -m swing.validate` — continuous run per pair over
  the full dev window (params fixed, so all OOS by construction), trades
  attributed to yearly folds for reporting. Kill: expectancy <= 0 or
  < 100 OOS trades → exit 2.
- **Lockbox**: most recent 12 months of daily bars quarantined
  (`SWING_HOLDOUT_START_TS` in `swing/swing_config.py`); only
  `swing/evaluate_holdout.py` may touch it, once, marker-guarded, and only
  for a variant meeting the promising bar.

## swing-v1 verdict: KILL (2026-10-02)

| variant | OOS trades | exp/trade | win% | PF | Sharpe | max DD |
|---------|-----------|-----------|------|-----|--------|--------|
| tsmom | 221 | -$6.19 | 29.4% | 0.79 | -0.36 | -21.6% |
| donchian | 165 | -$3.01 | 32.1% | 0.90 | -0.13 | -12.6% |
| ma_cross | 191 | -$2.43 | 28.3% | 0.91 | -0.11 | -13.6% |

All three negative after realistic fees with 165-221 OOS trades (solid
statistical power). Classic trend profile (low win rate, bigger winners)
but winners aren't big/frequent enough: PF 0.79-0.91 < 1. The swing
gradient is exhausted — longer holding fixed the fee problem (fees now a
few % of gross, not 96%) but revealed there is no gross edge either.
One genuine design bug was found and fixed during QA (vol-targeting let a
3xATR stop risk ~10%/trade; corrected to true 1%-risk turtle sizing —
a spec-compliance fix, not optimization).
Full report: `swing_report.txt`. Lockbox untouched (nothing earned it).

---

# Kalshi gauntlet (kalshi-v1..v5) — binary prediction markets

A structurally different game from crypto: binary $1/$0 settlement (pure
probability estimation), Kalshi taker fee = ceil(0.07*P*(1-P)) per contract,
episodic event-driven markets. Kalshi only (Polymarket geo-blocks US).

- **Data** (`kalshi/kalshi_data.py`, public unauthenticated endpoints):
  6,920 settled markets / 107k daily candles across KXNFLGAME, KXNBAGAME,
  KXNHLGAME, KXFED, KXCPI, cached in `data/kalshi.db`. KXBTC/KXETH/KXINX
  dropped (40k+ markets paginated, zero expired before lockbox).
- **Engine** (`kalshi/engine.py`): event-study backtest. Signal on daily
  candle close, fill at next open, hold to settlement. Proven by
  `kalshi/tests/test_kalshi_no_lookahead.py` and `kalshi/qa_kalshi.py`.
- **Validation**: `python3 -m kalshi.validate --version vN`. Exit 0 = PASS
  (positive OOS expectancy, 100+ trades). Exit 2 = KILL. V1/V3 params frozen
  a priori; V2/V4 filters chosen once from V1-V3 fit-window (70%) diagnostics,
  evaluated on the eval window (30%) only.
- **Lockbox**: markets expiring >= 2026-07-02 quarantined; only
  `kalshi/evaluate_lockbox.py` may touch them, once, marker-guarded.

## kalshi verdict: ALL KILL (2026-10-02)

| version | trades | exp/contract | win% | PF | verdict |
|---------|--------|-------------|------|-----|---------|
| v1 (buy 85c+ favorites) | 298 | -3.43c | 90.9% | 0.59 | KILL |
| v2 (v1 + fit filters, eval only) | 41 | +0.59c | 95.1% | 1.13 | KILL (thin) |
| v3 (sell <=15c tails) | 317 | -2.97c | 77.0% | 0.62 | KILL |
| v3 + adv-selection haircut | 317 | -11.57c | 24.3% | 0.05 | KILL |
| v4 (v1 on KXFED+KXNHLGAME, eval) | 41 | +0.59c | 95.1% | 1.13 | KILL (thin) |
| v5 (best filters, all dev, exploratory) | 128 | +0.02c | 94.5% | 1.00 | KILL |

Key lessons: V1's average fill was ~94c not 85c — it catches markets steaming
toward the favorite (momentum), not value. V3's tails hit 23% when priced at
15c — adverse selection is real and measured. The only positive readings
(V2/V4, +0.59c) came from n=41 eval samples and collapsed to exactly +0.02c
(PF 1.00) with n=128. Favorites are efficiently priced; tails are adversely
selected; the documented biases don't survive fees + adverse selection at
retail. Lockbox untouched — nothing earned it. No paper test.
