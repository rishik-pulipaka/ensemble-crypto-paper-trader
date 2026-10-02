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

**Total variants tested: 6**

## v6 — ETH momentum_roc, 1h, 3R targets, taker, 50bps
- Hypothesis: payoff structure. Momentum profits are fat-tailed; 2R cuts
  winners short. 3R lets the edge compound; lower win rate compensated by
  larger winners. Best-combination: ETH + 1h + momentum + 3R.
- Result: KILL. 475 OOS trades, expectancy -$37.46/trade, win rate 30.5%,
  avg win $156.63 (nearly 2x v5's $75.74 — the 3R worked mechanically),
  profit factor 0.56, Sharpe -6.13. Holdout untouched.
- Lesson: 3R did exactly what it should (bigger winners, PF 0.46→0.56,
  Sharpe -9.1→-6.1) but win rate fell 38%→30.5% and expectancy was
  unchanged (-$34→-$37). The payoff reshuffle moved losses around; it
  didn't create edge.

## TRAJECTORY ASSESSMENT (v3→v6)
- Expectancy/trade: -$43.04 → -$37.45 → -$33.99 → -$37.46. NOT trending
  toward positive; stalled/worse on the last step.
- Profit factor: 0.23 → 0.37 → 0.46 → 0.56. Improving, but from
  catastrophic toward bad — not converging on viable (>1.2).
- Sharpe: -16.3 → -12.3 → -9.1 → -6.1. Same story.
- Verdict: FLAT. Six versions, zero with positive expectancy, zero with
  200+ OOS trades and PF > 1.0. The loop stops here per the conditional
  cap (flat trajectory, not promising). No version earned the holdout shot.
- Root causes (confirmed across versions): (1) retail taker fees (50bps)
  create ~$50-100/trade drag against $100 risk — requires >53% win rate
  at 2R, which momentum can't deliver; (2) gross edges that appear in
  full-period scans (+$120 ETH momentum) do not survive walk-forward OOS
  (edge instability across time); (3) maker execution can't save negative
  gross (v3: PF 0.23, adverse selection verified).

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

## swing-v1 — long-only daily trend following (NEW system, not v7)
- Hypothesis: follow the v1-v6 trajectory gradient to its conclusion. v6's
  lesson was that longer timeframes shrink fee drag; the swing system takes
  it all the way: daily bars, holds of weeks/months, where 50bps/side fees
  are a few % of gross instead of 96%. Independent research ranked this the
  only angle with first-rate academic evidence (Moskowitz-Ooi-Pedersen;
  Hurst et al.). Three canonical variants, parameters fixed before seeing
  results (nothing optimized): tsmom (12-1m, monthly), donchian (100/50 +
  3xATR trailing stop), ma_cross (SMA50/200 daily).
- Data: 4,093 BTC + 3,788 ETH daily bars (2015/2016 -> 2026-10-02); dev
  window excludes the fresh 12-month lockbox (2025-10-02 -> 2026-10-02).
- Sizing: turtle 1%-risk over the 3xATR stop (a vol-targeting draft allowed
  ~10%/trade — fixed as a spec-compliance bug during QA, not optimization).
- Result: KILL. All three variants negative after realistic fees with
  165-221 OOS trades each (solid power):
  tsmom -$6.19/trade (PF 0.79, Sharpe -0.36, DD -21.6%);
  donchian -$3.01/trade (PF 0.90, Sharpe -0.13, DD -12.6%);
  ma_cross -$2.43/trade (PF 0.91, Sharpe -0.11, DD -13.6%).
- Lesson: the fee problem is SOLVED at this horizon, but there is no gross
  edge underneath — PF 0.79-0.91 with classic trend profile (26-32% win
  rate, ~2x payoff) still loses. The gradient is exhausted: this was the
  last structural direction with independent theoretical support.
- Lockbox untouched (nothing earned the one shot). QA 6/6 (no-lookahead
  proven, fees hand-verified, trailing stop verified, risk bounded,
  fresh-checkout clean).
- **Total variants tested: 7** (v1-v6 intraday + swing-v1).
