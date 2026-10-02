"""Validate one Kalshi version. Same discipline as run_backtest.py.

Exit 0 = PASS (positive OOS expectancy after fees, meaningful sample).
Exit 2 = KILL (expectancy <= 0, or no trades). Never lower the bar.

Usage:
    python3 -m kalshi.validate --version v1
    python3 -m kalshi.validate --version v3 --haircut   # V3 with adv-selection haircut
"""
import argparse
import sys

from . import strategies
from .engine import generate_trades, summarize
from .kalshi_config import V3

RULES = {
    "v1": strategies.v1_rule,
    "v2": strategies.v2_rule,
    "v3": strategies.v3_rule,
    "v4": strategies.v4_rule,
    "v5": strategies.v5_rule,
}


def fmt_money(x):
    return f"${x:,.2f}"


def report(version, trades, haircut=0.0):
    s = summarize(trades)
    print(f"\n===== {version} =====")
    if s["n"] == 0:
        print("NO TRADES -> KILL")
        return s
    if haircut:
        adj = [t["pnl"] - haircut for t in trades]
        s_adj = summarize([{**t, "pnl": p} for t, p in zip(trades, adj)])
        print(f"(adverse-selection haircut applied: -{haircut*100:.1f}c/contract)")
        s = s_adj
    print(f"trades (resolved contracts): {s['n']}")
    print(f"expectancy: {s['expectancy_c']:+.2f}c/contract  ({fmt_money(s['expectancy'])})")
    print(f"win rate: {s['win_rate']:.1%}  avg win {fmt_money(s['avg_win'])}  "
          f"avg loss {fmt_money(s['avg_loss'])}")
    print(f"profit factor: {s['profit_factor']:.2f}  "
          f"sharpe/trade: {s['sharpe_per_trade']:+.3f}")
    print(f"total PnL: {fmt_money(s['total_pnl'])}  fees paid: {fmt_money(s['total_fees'])}  "
          f"gross: {fmt_money(s['gross_pnl'])}")
    if s["fee_share_of_gross"] is not None:
        print(f"fees as share of gross: {s['fee_share_of_gross']:.1%}")
    print(f"max drawdown (1 contract/trade, sequential): {fmt_money(s['max_drawdown'])}")
    # per-series breakdown for diagnostics
    by_series = {}
    for t in trades:
        by_series.setdefault(t["series"], []).append(t["pnl"])
    print("\nper-series:")
    for ser, pnls in sorted(by_series.items(), key=lambda kv: sum(kv[1])):
        m = sum(pnls) / len(pnls)
        print(f"  {ser}: n={len(pnls):4d}  exp={m*100:+6.2f}c  total={fmt_money(sum(pnls))}")
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, choices=list(RULES))
    ap.add_argument("--haircut", action="store_true",
                    help="apply adverse-selection haircut (V3)")
    a = ap.parse_args()
    rule = RULES[a.version]()
    trades = generate_trades(rule)
    haircut = V3["adverse_selection_haircut"] if (a.haircut and a.version == "v3") else 0.0
    s = report(rule["version"], trades, haircut)
    if rule.get("exploratory_in_sample"):
        print("\n>>> EXPLORATORY ONLY: in-sample for filter selection. "
              "Cannot pass. Honest verdict below.")
        # fall through to honest assessment: ~zero edge = KILL
    if s["n"] == 0 or s["expectancy"] <= 0:
        print("\n>>> KILL: expectancy <= 0 after fees. Do not paper trade. Do not fund.")
        sys.exit(2)
    if s["n"] < 100:
        print(f"\n>>> KILL: only {s['n']} trades (<100). Sample too thin to trust.")
        sys.exit(2)
    if rule.get("exploratory_in_sample"):
        print("\n>>> KILL (exploratory): +0.02c ~ zero edge; the faint V2 signal "
              "died on more data. Do not paper trade. Do not fund.")
        sys.exit(2)
    print("\n>>> PASS: positive OOS expectancy with meaningful sample.")
    sys.exit(0)


if __name__ == "__main__":
    main()
