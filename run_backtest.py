#!/usr/bin/env python3
"""Run the full walk-forward backtest on real historical data.

Usage:
    python3 run_backtest.py [--pairs BTC-USD,ETH-USD] [--years 2] [--bankroll 10000]

Steps: ensure data -> walk-forward -> print metrics table -> save report.
Exit code 2 with KILL message if walk-forward expectancy <= 0 (see README).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from backtest import metrics, walk_forward
from data.fetcher import backfill_years
from data.resample import to_ohlcv
from data.store import CandleStore
from strategies.library import ALL_STRATEGIES


def ensure_data(pairs: list[str], years: float) -> dict:
    store = CandleStore(Path(__file__).resolve().parent / config.DB_PATH)
    data = {}
    gran = config.GRANULARITY_SECONDS
    for pair in pairs:
        cov = store.coverage(pair)
        # DB always stores 1-min bars; need enough of them for `years` at any
        # resampled granularity.
        need = int(365 * years * 24 * 60 * 0.9)
        if cov["bars"] < need:
            print(f"[data] {pair}: have {cov['bars']} bars, backfilling ~{years}y...",
                  flush=True)
            backfill_years(pair, years, store, 60)
        df = store.load(pair)
        if gran != 60:
            df = to_ohlcv(df, gran)
        print(f"[data] {pair}: {len(df)} bars @ {gran}s "
              f"({df['datetime'].iloc[0].date()} -> {df['datetime'].iloc[-1].date()})")
        data[pair] = df
    store.close()
    return data


def print_table(m: dict):
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
    print("\n=== WALK-FORWARD OUT-OF-SAMPLE METRICS (after fees+slippage) ===")
    for k, v in rows:
        print(f"  {k:<{w}}  {v}")
    print("=" * 62)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default=",".join(config.PAIRS))
    ap.add_argument("--years", type=float, default=config.HISTORY_YEARS)
    ap.add_argument("--bankroll", type=float, default=config.STARTING_BANKROLL)
    args = ap.parse_args()

    pairs = [p.strip() for p in args.pairs.split(",")]
    t0 = datetime.now(timezone.utc)
    data = ensure_data(pairs, args.years)

    print("[backtest] running walk-forward...", flush=True)
    result = walk_forward(data, ALL_STRATEGIES, args.bankroll)
    for f in result["folds"]:
        print(f"[fold {f['fold']}] {f['status']}"
              + (f" trades={f['trades']} kelly_risk={f.get('risk_frac', 0):.4f}"
                 if f["status"] == "ok" else ""))
    m = metrics(result["trades"], args.bankroll)
    print_table(m)

    report_path = Path(__file__).resolve().parent / "backtest_report.txt"
    with open(report_path, "w") as fh:
        fh.write(f"generated: {datetime.now(timezone.utc).isoformat()}\n")
        fh.write(f"pairs: {pairs}  bankroll: {args.bankroll}\n")
        fh.write(f"folds: {result['folds']}\n")
        for k, v in m.items():
            fh.write(f"{k}={v}\n")
    print(f"[report] wrote {report_path}")
    print(f"[time] elapsed {(datetime.now(timezone.utc) - t0).total_seconds():.0f}s")

    # ---- KILL CRITERIA (README) ----
    if m.get("n_trades", 0) < config.MIN_TRADES_FOR_STATS:
        print("\nKILL: too few out-of-sample trades for reliable stats. "
              "Strategy set is DEAD. Do not paper trade.")
        return 2
    if m.get("expectancy", 0) <= 0:
        print("\nKILL: walk-forward expectancy after fees <= 0. "
              "Strategy set is DEAD. Do not paper trade.")
        return 2
    print("\nPASS: positive OOS expectancy. Paper trading may proceed "
          "(paper only, tiny size, keep watching it).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
