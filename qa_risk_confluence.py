#!/usr/bin/env python3
"""QA: confluence math hand-verification + risk manager synthetic tests."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from confluence import decide, kelly_risk_fraction
from risk import RiskManager

FAIL = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    if not cond:
        FAIL.append(name)


# ---- 5a. kelly hand-check -------------------------------------------------
# p=0.6, b=2.0 -> kelly = (0.6*3 - 1)/2 = 0.4 -> half = 0.2 -> capped at 0.01
check("kelly-caps-at-1pct", kelly_risk_fraction(0.6, 2.0) == config.RISK_PER_TRADE,
      f"got {kelly_risk_fraction(0.6, 2.0)}")
# p=0.5, b=1.0 -> kelly = (0.5*2-1)/1 = 0 -> 0
check("kelly-no-edge-zero", kelly_risk_fraction(0.5, 1.0) == 0.0)
# p=0.55, b=1.0 -> kelly=(0.55*2-1)/1=0.1 -> half=0.05 -> capped 0.01
check("kelly-small-edge", kelly_risk_fraction(0.55, 1.0) == 0.01)
check("kelly-degenerate", kelly_risk_fraction(0.0, 2.0) == 0.0
      and kelly_risk_fraction(0.6, 0.0) == 0.0)

# ---- 5b. confluence hand-check --------------------------------------------
# bankroll 10000, win_rate 0.55 payoff 1.5 -> kelly=(0.55*2.5-1)/1.5=0.25 -> half 0.125 -> cap 0.01
# risk_usd = 100. Three longs agree, entries 100/102/101, invalidations 98/99/97.5,
# convictions 0.8/0.6/0.9, weights 0.5/0.3/0.2, regime trend.
signals = [
    {"name": "a", "family": "trend", "vote": 1, "entry": 100.0,
     "invalidation": 98.0, "conviction": 0.8},
    {"name": "b", "family": "momentum", "vote": 1, "entry": 102.0,
     "invalidation": 99.0, "conviction": 0.6},
    {"name": "c", "family": "volume", "vote": 1, "entry": 101.0,
     "invalidation": 97.5, "conviction": 0.9},
    {"name": "d", "family": "volatility", "vote": -1, "entry": 100.0,
     "invalidation": 102.0, "conviction": 0.9},  # dissenter
]
weights = {"a": 0.5, "b": 0.3, "c": 0.2, "d": 0.4}
# regime multipliers trend: trend 1.0, momentum 1.0, volume 0.8, volatility 0.7
# effective: a .5, b .3, c .16 ; dissenter d .28 (short side, loses count)
out = decide(signals, "trend", weights, 10000.0, 0.55, 1.5)
check("confluence-enters", out is not None)
# hand math: entry = (100*.5 + 102*.3 + 101*.16)/(.5+.3+.16)
exp_entry = (100 * 0.5 + 102 * 0.3 + 101 * 0.16) / 0.96
exp_inval = (98 * 0.5 + 99 * 0.3 + 97.5 * 0.16) / 0.96
check("confluence-entry", abs(out["entry"] - exp_entry) < 1e-9, f"{out['entry']}")
check("confluence-invalidation", abs(out["invalidation"] - exp_inval) < 1e-9)
check("confluence-risk", abs(out["risk_usd"] - 100.0) < 1e-9, f"{out['risk_usd']}")
exp_size = 100.0 / abs(exp_entry - exp_inval)
check("confluence-size", abs(out["size_units"] - exp_size) < 1e-9,
      f"{out['size_units']:.6f}")
check("confluence-agreeing", out["agreeing"] == ["a", "b", "c"], str(out["agreeing"]))
# score = weighted conviction / max_possible
maxp = 0.5 + 0.3 + 0.16 + 0.28
sc = (0.5 * 0.8 + 0.3 * 0.6 + 0.16 * 0.9) / maxp
check("confluence-score", abs(out["score"] - sc) < 1e-9 and sc >= config.SCORE_THRESHOLD)

# only 2 agree -> no trade
s2 = [dict(s, vote=0) for s in signals[:1]] + signals[1:]
s2[0]["vote"] = 0
out2 = decide([s for s in signals if s["name"] != "a"], "trend", weights,
              10000.0, 0.55, 1.5)
check("confluence-min-agree-blocks", out2 is None, "2 of 5 -> no trade")

# zero weights -> no trade
out3 = decide(signals, "trend", {k: 0.0 for k in weights}, 10000.0, 0.55, 1.5)
check("confluence-zero-weights-blocks", out3 is None)

# no edge (kelly 0) -> no trade even with agreement
out4 = decide(signals, "trend", weights, 10000.0, 0.5, 1.0)
check("confluence-no-edge-blocks", out4 is None)

# regime gating: trend-family strategy gets 0 multiplier in chop
out5 = decide(signals, "chop", weights, 10000.0, 0.55, 1.5)
# in chop: a(trend) mult 0 -> only b(.18), c(.2) vote long = 2 < MIN_AGREE
check("confluence-regime-gate", out5 is None, "trend strat gated out in chop")

# ---- 6. risk manager synthetic tests --------------------------------------
rm = RiskManager()
rm.new_day("2026-01-01", 10000.0)
ok, _ = rm.can_open()
check("risk-can-open-initially", ok)
for _ in range(config.MAX_POSITIONS):
    rm.register_open()
ok, reason = rm.can_open()
check("risk-max-positions-blocks", not ok and reason == "max positions", reason)

rm2 = RiskManager()
rm2.new_day("2026-01-01", 10000.0)
rm2.register_open()
rm2.register_close(-100.0)   # -1%
rm2.register_open()
rm2.register_close(-250.0)   # cumulative -3.5% -> halt
ok, reason = rm2.can_open()
check("risk-daily-halt-triggers", not ok and reason == "daily-loss halt",
      f"day_pnl={rm2.day_pnl} reason={reason}")
# halt resets next day
rm2.new_day("2026-01-02", 9650.0)
ok, _ = rm2.can_open()
check("risk-halt-resets-next-day", ok)

# exactly at the boundary: -3.0% should halt (<=)
rm3 = RiskManager()
rm3.new_day("2026-01-01", 10000.0)
rm3.register_open()
rm3.register_close(-300.0)
ok, _ = rm3.can_open()
check("risk-halt-at-boundary", not ok, "exactly -3% halts")

# SL/TP levels from real technical levels
lv = RiskManager.make_levels(1, 100.0, 97.0)
check("risk-long-levels", lv == {"stop": 97.0, "take_profit": 106.0}, str(lv))
lv = RiskManager.make_levels(-1, 100.0, 103.0)
check("risk-short-levels", lv == {"stop": 103.0, "take_profit": 94.0}, str(lv))

# exit detection: conservative on ambiguous bars
bar = {"open": 100, "high": 107, "low": 96, "close": 101}
check("risk-ambiguous-bar-stop-first",
      RiskManager.check_exits(1, {"stop": 97, "take_profit": 106}, bar) == "stop")
bar2 = {"open": 100, "high": 107, "low": 98, "close": 104}
check("risk-clean-tp", RiskManager.check_exits(1, {"stop": 97, "take_profit": 106}, bar2) == "take_profit")
bar3 = {"open": 100, "high": 105, "low": 98, "close": 104}
check("risk-no-exit", RiskManager.check_exits(1, {"stop": 90, "take_profit": 110}, bar3) is None)
# short side
bar4 = {"open": 100, "high": 102, "low": 93, "close": 95}
check("risk-short-tp", RiskManager.check_exits(-1, {"stop": 103, "take_profit": 94}, bar4) == "take_profit")

print()
if FAIL:
    print(f"FAILURES: {FAIL}")
    sys.exit(1)
print("ALL CONFLUENCE + RISK CHECKS PASSED")
