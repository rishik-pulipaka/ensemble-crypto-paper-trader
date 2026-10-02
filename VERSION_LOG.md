# Strategy Iteration Log

Autonomous iteration loop. Each version attacks v1's root cause (fee economics:
v1 strategies grossed ~$31 on a typical 2R winner but paid ~$30 round-trip at
40bps — fees consumed ~96% of gross, and gross edge was ~zero anyway).

Variant count is tracked here for multiple-testing discipline. Every version
adds to the burden: a barely-positive result after N failed attempts is
treated as noise until proven otherwise on 200+ out-of-sample trades.

**Total variants tested: 2**

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
