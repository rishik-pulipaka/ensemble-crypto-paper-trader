#!/usr/bin/env python3
"""ONE-SHOT final holdout evaluation for the swing system. Read first.

The swing lockbox (ts >= SWING_HOLDOUT_START_TS = 2025-10-02, the most
recent 12 months of daily bars) is quarantined from all development. This
script is the ONLY permitted access, and it runs AT MOST ONCE — ever. It
writes .swing_holdout_used on completion and refuses to run again.

Eligibility: a variant that ALREADY met the promising bar on its own
walk-forward OOS data (expectancy > 0 after realistic fees, >=100 OOS
trades, Sharpe > 1.0 or PF > 1.2, max DD <= 30%).

- Holdout expectancy > 0 after realistic fees -> GENUINE. Pause and propose
  the paper session to Rishik.
- Otherwise -> MANUFACTURED FIT. Record in VERSION_LOG.md. Never reused.

Usage:
    python3 -m swing.evaluate_holdout --variant tsmom --reason "<why>"
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MARKER = ROOT / ".swing_holdout_used"
sys.path.insert(0, str(ROOT))

from swing import swing_config as C
from swing.data import load_swing
from swing.engine import run_pair, metrics


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True,
                    choices=["tsmom", "donchian", "ma_cross"])
    ap.add_argument("--reason", required=True)
    ap.add_argument("--bankroll", type=float, default=C.STARTING_BANKROLL)
    args = ap.parse_args()

    if MARKER.exists():
        print("REFUSED: the swing holdout has already been used once. "
              "It is never reused.")
        return 3

    print("=" * 70)
    print("SWING FINAL HOLDOUT EVALUATION — ONE SHOT. Cannot be undone.")
    print(f"Variant: {args.variant}")
    print(f"Eligibility reason: {args.reason}")
    print("=" * 70)

    all_trades = []
    for pair in C.SWING_PAIRS:
        df = load_swing(pair, include_holdout=True)
        df = df[df["ts"] >= C.SWING_HOLDOUT_START_TS].reset_index(drop=True)
        print(f"[holdout] {pair}: {len(df)} daily bars "
              f"({df['datetime'].iloc[0].date()} -> {df['datetime'].iloc[-1].date()})")
        trades, _ = run_pair(df, args.variant, pair, args.bankroll)
        # holdout attribution: entries within the holdout window (all of them
        # by construction, but a trade entered on the first bar needs warmup
        # history which predates the window — that's fine, indicators only)
        all_trades.append(trades)

    trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    m = metrics(trades, args.bankroll)
    print("\n=== SWING HOLDOUT METRICS (after realistic fees) ===")
    for k in ("n_trades", "total_pnl", "expectancy", "win_rate", "avg_win",
              "avg_loss", "profit_factor", "sharpe_daily", "max_drawdown",
              "final_equity", "return_pct"):
        print(f"  {k:18} {m.get(k, 0)}")

    exp = m.get("expectancy", 0)
    n = m.get("n_trades", 0)
    genuine = exp > 0 and n >= C.MIN_OOS_TRADES
    verdict = "GENUINE" if genuine else "MANUFACTURED"
    print(f"\nHOLDOUT VERDICT: {verdict} (expectancy={exp:.2f}, n={n})")

    with open(MARKER, "w") as fh:
        fh.write(f"used: {datetime.now(timezone.utc).isoformat()}\n")
        fh.write(f"variant: {args.variant}\nreason: {args.reason}\n")
        fh.write(f"verdict: {verdict}\n")
        for k, v in m.items():
            fh.write(f"{k}={v}\n")
    print(f"\n[lockbox] marker written to {MARKER}. The swing holdout is spent.")
    return 0 if verdict == "GENUINE" else 2


if __name__ == "__main__":
    sys.exit(main())
