"""V1 diagnostics for honest V2/V4 specification.

Splits V1 trades into fit (first 70% by expiry) and eval (last 30%).
V2 filters may ONLY be chosen from the fit window. The eval window stays
untouched until V2/V4/V5 validation.

Usage: python3 -m kalshi.diagnose --version v1
"""
import argparse
import sqlite3
import sys

from .engine import generate_trades, summarize
from .kalshi_config import DB_PATH
from . import strategies


def split_ts(frac=0.7):
    con = sqlite3.connect(DB_PATH)
    exps = sorted(r[0] for r in con.execute("SELECT expiration_ts FROM markets"))
    con.close()
    return exps[int(len(exps) * frac)]


def bucket_report(trades, key_fn, label):
    buckets = {}
    for t in trades:
        buckets.setdefault(key_fn(t), []).append(t["pnl"])
    print(f"\n-- by {label} --")
    for k in sorted(buckets):
        pnls = buckets[k]
        m = sum(pnls) / len(pnls)
        print(f"  {k}: n={len(pnls):4d} exp={m*100:+6.2f}c total=${sum(pnls):+.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v1", choices=["v1", "v3"])
    a = ap.parse_args()
    rule = {"v1": strategies.v1_rule, "v3": strategies.v3_rule}[a.version]()
    cut = split_ts(0.7)
    trades = generate_trades(rule)
    fit = [t for t in trades if t["expiration_ts"] < cut]
    evl = [t for t in trades if t["expiration_ts"] >= cut]
    print(f"cut ts: {cut}  fit n={len(fit)}  eval n={len(evl)} (eval UNTOUCHED)")

    print("\n===== FIT WINDOW (only data V2/V4 may learn from) =====")
    s = summarize(fit)
    print(f"n={s['n']} exp={s.get('expectancy_c', 0):+.2f}c "
          f"win={s.get('win_rate', 0):.1%} PF={s.get('profit_factor', 0):.2f}")
    bucket_report(fit, lambda t: t["series"], "series")

    # entry volume buckets (fill candle volume not stored; use market volume)
    con = sqlite3.connect(DB_PATH)
    vol = {r[0]: r[1] for r in con.execute("SELECT ticker, volume FROM markets")}
    con.close()
    def vbucket(t):
        v = vol.get(t["ticker"], 0)
        if v < 1000: return "<1k"
        if v < 10000: return "1k-10k"
        if v < 100000: return "10k-100k"
        return ">100k"
    bucket_report(fit, vbucket, "market volume")

    # entry price buckets
    def pbucket(t):
        p = t["fill_price"]
        if p < 0.87: return "85-87c"
        if p < 0.90: return "87-90c"
        if p < 0.95: return "90-95c"
        return "95c+"
    if a.version == "v1":
        bucket_report(fit, pbucket, "fill price")
    else:
        def pbucket3(t):
            p = t["fill_price"]
            if p > 0.13: return "13-15c"
            if p > 0.10: return "10-13c"
            if p > 0.05: return "5-10c"
            return "<5c"
        bucket_report(fit, pbucket3, "fill price")

    print("\n===== EVAL WINDOW (do not use for filter selection) =====")
    s = summarize(evl)
    print(f"n={s['n']} exp={s.get('expectancy_c', 0):+.2f}c "
          f"win={s.get('win_rate', 0):.1%} PF={s.get('profit_factor', 0):.2f}")
    print("\nNOTE: eval-window numbers shown for context only. V2/V4 filters "
          "must be chosen from fit-window diagnostics above.")


if __name__ == "__main__":
    main()
