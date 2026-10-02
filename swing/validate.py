#!/usr/bin/env python3
"""Walk-forward validation for the swing system.

Parameters are canonical and fixed (see swing_config.py) — nothing is
optimized, so the entire development window is out-of-sample. Folds exist
as honest reporting segments; trades are attributed to the fold containing
their ENTRY.

Folds: full years 2017..2024 + 2025-01-01 -> 2025-10-01 (pre-lockbox).
Warmup: 500 days before each fold start (indicator history, not counted).

Kill criteria (README):
  - best variant OOS expectancy <= 0 after fees  -> KILL, exit 2
  - best variant OOS trades < 100               -> KILL (insufficient stats), exit 2
Promising bar (holdout eligibility): expectancy > 0, >=100 trades,
  Sharpe > 1.0 or PF > 1.2, max DD <= 30%.

Usage: python3 -m swing.validate [--bankroll 10000]
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from swing import swing_config as C
from swing.data import ensure_swing_data, load_swing
from swing.engine import run_pair, metrics
from swing.signals import VARIANTS

FOLDS = [
    ("2017", "2017-01-01", "2018-01-01"),
    ("2018", "2018-01-01", "2019-01-01"),
    ("2019", "2019-01-01", "2020-01-01"),
    ("2020", "2020-01-01", "2021-01-01"),
    ("2021", "2021-01-01", "2022-01-01"),
    ("2022", "2022-01-01", "2023-01-01"),
    ("2023", "2023-01-01", "2024-01-01"),
    ("2024", "2024-01-01", "2025-01-01"),
    ("2025p", "2025-01-01", "2025-10-01"),
]
WARMUP_PAD_DAYS = 500


def _ts(s: str) -> int:
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp())


def run_variant(data: dict[str, pd.DataFrame], variant: str,
                bankroll: float) -> pd.DataFrame:
    """One continuous run per pair over the full dev window (params are fixed,
    so the whole window is OOS by construction). Trades attributed to folds
    by entry date for the fold table; aggregate metrics use everything."""
    all_trades = []
    eq_curves = []
    fold_rows = []
    per_pair_bankroll = bankroll / len(data)
    for pair, full in data.items():
        trades, eq = run_pair(full, variant, pair, per_pair_bankroll)
        for fname, fstart, fend in FOLDS:
            t0, t1 = _ts(fstart), _ts(fend)
            tin = trades[(trades["entry_ts"] >= t0)
                         & (trades["entry_ts"] < t1)]
            if len(tin):
                fold_rows.append((fname, pair, len(tin)))
        all_trades.append(trades)
        s = eq.set_index("ts")["equity"]
        eq_curves.append(s)
    agg = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    # combined equity: leading NaN (before a pair's first bar) = cash at start
    eq_all = pd.concat(eq_curves, axis=1)
    eq_all = eq_all.fillna(per_pair_bankroll).sum(axis=1)
    eq_df = pd.DataFrame({"ts": eq_all.index, "equity": eq_all.values})
    m = metrics(agg, bankroll, eq_df)
    return m, agg, fold_rows


def print_table(name: str, m: dict):
    rows = [
        ("OOS trades", f"{m.get('n_trades', 0)}"),
        ("Total P&L (after fees)", f"${m.get('total_pnl', 0):,.2f}"),
        ("Expectancy / trade", f"${m.get('expectancy', 0):,.2f}"),
        ("Win rate", f"{m.get('win_rate', 0) * 100:.1f}%"),
        ("Avg win", f"${m.get('avg_win', 0):,.2f}"),
        ("Avg loss", f"${m.get('avg_loss', 0):,.2f}"),
        ("Profit factor", f"{m.get('profit_factor', 0):.2f}"),
        ("Sharpe (daily, ann.)", f"{m.get('sharpe_daily', 0):.2f}"),
        ("Max drawdown", f"{m.get('max_drawdown', 0) * 100:.1f}%"),
        ("Final equity", f"${m.get('final_equity', 0):,.2f}"),
        ("Return", f"{m.get('return_pct', 0):.1f}%"),
    ]
    w = max(len(r[0]) for r in rows)
    print(f"\n=== {name} — WALK-FORWARD OOS (after fees+slippage) ===")
    for k, v in rows:
        print(f"  {k:<{w}}  {v}")
    print("=" * 62)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--bankroll", type=float, default=C.STARTING_BANKROLL)
    args = ap.parse_args()

    print("[swing] ensuring daily data (lockbox excluded from dev)...")
    ensure_swing_data()
    data = {p: load_swing(p) for p in C.SWING_PAIRS}
    for p, df in data.items():
        print(f"[swing] dev {p}: {len(df)} daily bars "
              f"({df['datetime'].iloc[0].date()} -> {df['datetime'].iloc[-1].date()})")

    results = {}
    for variant in VARIANTS:
        print(f"[swing] validating {variant}...", flush=True)
        m, trades, folds = run_variant(data, variant, args.bankroll)
        results[variant] = (m, trades, folds)
        print_table(f"swing/{variant}", m)
        for fname, pair, n in folds:
            if n:
                print(f"    fold {fname} {pair}: {n} trades")

    # select by OOS expectancy (1 selection among 3 — disclosed, mild)
    best = max(results, key=lambda v: results[v][0].get("expectancy", float("-inf")))
    bm, btrades, _ = results[best]
    print(f"\n[select] best variant by OOS expectancy: {best} "
          f"(1 selection among {len(results)} — disclosed)")

    report = ROOT / "swing_report.txt"
    with open(report, "w") as fh:
        fh.write(f"generated: {datetime.now(timezone.utc).isoformat()}\n")
        fh.write(f"bankroll: {args.bankroll}\n")
        for variant, (m, _, folds) in results.items():
            fh.write(f"\n[{variant}]\n")
            for k, v in m.items():
                fh.write(f"{k}={v}\n")
            fh.write(f"folds={folds}\n")
        fh.write(f"\nselected={best}\n")
    print(f"[report] wrote {report}")

    n = bm.get("n_trades", 0)
    exp = bm.get("expectancy", 0)
    if n < C.MIN_OOS_TRADES:
        print(f"\nKILL: only {n} OOS trades (< {C.MIN_OOS_TRADES}). Insufficient "
              "statistical power — cannot pass. Strategy set is DEAD.")
        return 2
    if exp <= 0:
        print("\nKILL: walk-forward OOS expectancy after fees <= 0. "
              "Strategy set is DEAD. Do not paper trade.")
        return 2
    promising = (bm.get("sharpe_daily", 0) > C.PROMISING_SHARPE
                 or bm.get("profit_factor", 0) > C.PROMISING_PF) \
        and bm.get("max_drawdown", 1) > -C.PROMISING_MAX_DD
    print("\nPASS: positive OOS expectancy with sufficient trades.")
    print(f"Promising bar (holdout eligibility): "
          f"{'MET' if promising else 'NOT MET'} "
          f"(Sharpe={bm.get('sharpe_daily', 0):.2f}, "
          f"PF={bm.get('profit_factor', 0):.2f}, "
          f"DD={bm.get('max_drawdown', 0) * 100:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
