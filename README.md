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
