# Strategy Iteration Log

Autonomous iteration loop. Each version attacks v1's root cause (fee economics:
v1 strategies grossed ~$31 on a typical 2R winner but paid ~$30 round-trip at
40bps — fees consumed ~96% of gross, and gross edge was ~zero anyway).

Variant count is tracked here for multiple-testing discipline. Every version
adds to the burden: a barely-positive result after N failed attempts is
treated as noise until proven otherwise on 200+ out-of-sample trades.

## LOCKBOX — final holdout (quarantined 2026-10-01, enforced in code)
- Range: **2026-06-14T16:29:00Z → 2026-10-02** (most recent ~15% of history:
  157,546 1-min bars/pair; larger than 3 months, per the 15%-or-3mo rule).
- Enforced by `HOLDOUT_START_TS` in config.py: `run_backtest.py` excludes
  ts >= boundary from ALL development and walk-forward evaluation.
- The ONLY permitted access is `evaluate_holdout.py`, which runs AT MOST
  ONCE (marker file `.holdout_used`), and only for a version that already
  met the full PROMISING bar on its own OOS data.
- Survives holdout (expectancy > 0, realistic fees) → GENUINE: pause loop,
  propose 3-week paper session. Dies on holdout → MANUFACTURED FIT: record
  here, keep iterating. Holdout never reused.
- v1/v2 were evaluated before quarantine on overlapping data; both are dead
  and discarded, so no design contamination carries forward. From v3 on, the
  quarantine is absolute.

**Total variants tested: 5**

## v5 — ETH-only momentum_roc, 1-hour, taker, 50bps
- Hypothesis: edge concentrates in less-efficient markets. Per-pair
  diagnostic: ETH momentum gross +$120.60/trade (1,391 trades, wr 0.41)
  vs BTC +$45.72. If OOS holds, fees become survivable.
- Result: KILL. 655 OOS trades, expectancy -$33.99/trade, win rate 38.2%,
  profit factor 0.46, Sharpe -9.11. Holdout untouched.
- Lesson: the +$120 gross was a full-period artifact; it did NOT survive
  walk-forward OOS. Edge instability is now the confirmed second problem
  (alongside fees). The gross edge exists in some periods and vanishes in
  others. Next (v6): best-combination — ETH + 1h + momentum + 3R targets
  (payoff-structure hypothesis: momentum profits are fat-tailed).

## v4 — momentum_roc alone, 1-hour bars, taker, 50bps
- Hypothesis: start from the best GROSS edge (+$42-46/trade) and shrink fee
  drag via timeframe — wider stops → smaller notional for same risk dollars
  → smaller absolute fees. momentum_roc only, 1h bars, BTC+ETH.
- Result: KILL. 1,267 OOS trades, expectancy -$37.45/trade, win rate 36.8%,
  profit factor 0.37, Sharpe -12.25. Holdout untouched.
- Lesson: gross edge didn't survive OOS (scan was full-period; walk-forward
  folds were worse), and fee drag at 50bps still overwhelmed. Two-part
  problem: edge instability + fee level. Next: isolate WHERE the gross edge
  lives — per-pair diagnostic showed ETH momentum gross +$120.60/trade
  (1,391 trades, wr 0.41) vs BTC +$45.72. If that holds OOS, fees become
  survivable.

## v3 — maker-only mean reversion (vwap_mr, chop, 15-min)
- Hypothesis: spread capture. Maker fees (10bps) are 5x cheaper than taker
  (50bps); profit from passive limit execution, not prediction. Limit buys
  5bps below signal, filled only on touch; TP as maker limit, stops as taker.
- Result: KILL. 892 OOS trades (good sample), expectancy -$43.04/trade,
  win rate 24.2%, profit factor 0.23, Sharpe -16.32. Holdout untouched.
- Lesson: maker execution multiplies existing edge; it doesn't create it.
  vwap_mr gross was negative (-$2-10/trade) — cheaper fees on a losing
  strategy just lose differently. Adverse selection is real: limit buys fill
  exactly when price is falling through our level, and 24% win rate proves
  the dip keeps dipping. Next: start from the strategy with the best GROSS
  edge (momentum_roc +$42-46/trade) and attack fee drag via notional.

## v2 — 15-min bars, realistic fees (50bps/side)
- Hypothesis: fee-RATIO. Bigger per-trade moves on 15-min bars make the fixed
  bps fee a smaller fraction of gross. Same 5 strategies, bar counts preserved
  (VWAP rescaled to 48 bars to keep 12h wall-time). FEE 50bps/side + 10bps
  slip (realistic retail taker). BTC+ETH, 70k bars/pair.
- Result: KILL. 3/3 folds dead, 0 OOS trades (all train weights = 0).
- Diagnostic (train window, 1% risk): best gross expectancy was momentum_roc
  +$10.35/trade and donchian +$3-6/trade at ZERO fees — but fee drag at
  50bps/side on risk-based sizing is ~$100+/trade (fee is on notional, edge
  is on risk). Net: -$10 to -$28/trade across the board.
- Lesson: timeframe doesn't fix fee economics when fees scale with notional
  and edge scales with risk. The binding constraint is the FEE RATE itself,
  not the fee ratio. Next: attack the rate via maker execution (~5-10x
  cheaper than taker).

## v1 — 5-strategy ensemble, 1-min BTC, optimistic fees
- Hypothesis: ensemble confluence across 5 strategy families beats noise.
- Config: 1-min bars, FEE 15bps/side + 5bps slip (optimistic), BTC-USD only.
- Result: KILL. Walk-forward: 3/3 folds dead, 0 OOS trades (all weights = 0).
  Per-strategy train expectancy after fees: -$4 to -$12/trade (1,000-2,300
  trades each — statistically solid). Best gross edge: Donchian +$3.22/trade
  pre-fee.
- Lesson: fee ratio is the binding constraint, not signal quality. Typical
  1-min trade captures moves too small to survive realistic costs.
