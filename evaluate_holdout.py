#!/usr/bin/env python3
"""ONE-SHOT final holdout evaluation. Read the header before running.

The holdout (ts >= HOLDOUT_START_TS, 2026-06-14 -> 2026-10-02, ~15% of
history) is quarantined from all development. This script is the ONLY
permitted access, and it runs AT MOST ONCE — ever. It writes
.holdout_used on completion and refuses to run again.

Eligibility: a version that has ALREADY met the full PROMISING bar on its
own walk-forward OOS data (expectancy > 0 after realistic fees, 200+ OOS
trades, Sharpe > 1.0 or profit factor > 1.2, drawdown within limits).

- If holdout expectancy > 0 after realistic fees: GENUINE. Pause the loop
  and propose the 3-week paper session to Rishik.
- If holdout expectancy <= 0: MANUFACTURED FIT. Record it in VERSION_LOG.md
  and keep iterating. The holdout is NEVER reused for a second chance.

Usage:
    python3 evaluate_holdout.py --version vN --reason "<why it earned this shot>"
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MARKER = ROOT / ".holdout_used"

sys.path.insert(0, str(ROOT))

import config
from backtest import metrics, simulate

# NOTE: maker-mode holdout eval dispatches on config.EXECUTION_MODE at call time.
# Keep this import lazy to avoid circulars; simulate_maker lives in backtest.


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--reason", required=True)
    args = ap.parse_args()

    if MARKER.exists():
        print("REFUSED: the holdout has already been used once. It is never reused.")
        print(f"See {MARKER} for the original evaluation record.")
        return 3

    from data.resample import to_ohlcv
    from data.store import CandleStore
    from regime import classify
    from strategies.library import ALL_STRATEGIES
    import numpy as np

    print("=" * 70)
    print("FINAL HOLDOUT EVALUATION — ONE SHOT. This cannot be undone.")
    print(f"Version: {args.version}")
    print(f"Eligibility reason: {args.reason}")
    print("=" * 70)

    store = CandleStore(ROOT / config.DB_PATH)
    all_trades = []
    for pair in config.PAIRS:
        df = store.load(pair)
        df = df[df["ts"] >= config.HOLDOUT_START_TS].reset_index(drop=True)
        if config.GRANULARITY_SECONDS != 60:
            df = to_ohlcv(df, config.GRANULARITY_SECONDS)
        print(f"[holdout] {pair}: {len(df)} bars "
              f"({df['datetime'].iloc[0].date()} -> {df['datetime'].iloc[-1].date()})")

        if config.EXECUTION_MODE == "maker":
            from backtest import simulate_maker
            strat = next(s for s in ALL_STRATEGIES if s.name == config.MAKER_STRATEGY)
            sig = strat.generate(df)
            reg = classify(df)
            mask = reg.isin(config.MAKER_REGIMES).to_numpy()
            t = simulate_maker(df, sig, mask, config.STARTING_BANKROLL,
                               config.RISK_PER_TRADE, pair)
        else:
            # taker path: single best-effort ensemble via current config
            from backtest import compute_weights, ensemble_votes
            data1 = {pair: df}
            weights = compute_weights(data1, ALL_STRATEGIES, config.STARTING_BANKROLL)
            reg = classify(df)
            votes, entries, invalids = ensemble_votes(df, ALL_STRATEGIES, weights, reg)
            mask = np.ones(len(df), dtype=bool)
            from confluence import kelly_risk_fraction
            wr, payoff = 0.5, 1.0
            t = simulate(df, votes, entries, invalids, mask,
                         config.STARTING_BANKROLL,
                         kelly_risk_fraction(wr, payoff), pair)
        all_trades.append(t)
    store.close()

    import pandas as pd
    trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    m = metrics(trades, config.STARTING_BANKROLL)
    print("\n=== HOLDOUT METRICS (after realistic fees) ===")
    for k in ("n_trades", "total_pnl", "expectancy", "win_rate", "avg_win",
              "avg_loss", "profit_factor", "sharpe_daily", "max_drawdown",
              "final_equity", "return_pct"):
        print(f"  {k:18} {m.get(k, 0)}")

    exp = m.get("expectancy", 0)
    verdict = "GENUINE" if exp > 0 and m.get("n_trades", 0) >= 200 else "MANUFACTURED"
    print(f"\nHOLDOUT VERDICT: {verdict} (expectancy={exp:.2f}, n={m.get('n_trades', 0)})")

    with open(MARKER, "w") as fh:
        fh.write(f"used: {datetime.now(timezone.utc).isoformat()}\n")
        fh.write(f"version: {args.version}\nreason: {args.reason}\n")
        fh.write(f"verdict: {verdict}\n")
        for k, v in m.items():
            fh.write(f"{k}={v}\n")
    print(f"\n[lockbox] marker written to {MARKER}. The holdout is now spent.")
    return 0 if verdict == "GENUINE" else 2


if __name__ == "__main__":
    sys.exit(main())
