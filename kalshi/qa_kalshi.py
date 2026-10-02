"""Kalshi QA checklist: fee math, lockbox, data sanity.

All must pass before any version result is trusted.
"""
import math
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kalshi.kalshi_config import DB_PATH, LOCKBOX_START_TS, taker_fee

fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" ({detail})" if detail and not cond else ""))
    if not cond:
        fails.append(name)


# 1. fee formula hand-verification: ceil(0.07 * P * (1-P)) cents
cases = [
    (0.85, math.ceil(0.07 * 0.85 * 0.15 * 100) / 100),   # 0.8925c -> 1c
    (0.50, math.ceil(0.07 * 0.25 * 100) / 100),           # 1.75c -> 2c
    (0.90, math.ceil(0.07 * 0.09 * 100) / 100),           # 0.63c -> 1c
    (0.15, math.ceil(0.07 * 0.15 * 0.85 * 100) / 100),    # 0.8925c -> 1c
    (0.99, math.ceil(0.07 * 0.99 * 0.01 * 100) / 100),    # 0.0693c -> 1c
]
for p, want in cases:
    got = taker_fee(p)
    check(f"fee({p}) == {want:.2f}", abs(got - want) < 1e-9, f"got {got}")

# 2. lockbox: dev table must contain NOTHING expiring at/after the boundary
con = sqlite3.connect(DB_PATH)
bad = con.execute("SELECT COUNT(*) FROM markets WHERE expiration_ts >= ?",
                  (LOCKBOX_START_TS,)).fetchone()[0]
check("lockbox quarantine intact", bad == 0, f"{bad} violations")

# 3. data sanity
n_m = con.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
n_c = con.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
check("dev markets present", n_m >= 500, f"n={n_m}")
check("candles present", n_c >= 5000, f"n={n_c}")

# results are binary
bad_res = con.execute(
    "SELECT COUNT(*) FROM markets WHERE result NOT IN ('yes','no')").fetchone()[0]
check("results binary", bad_res == 0, f"{bad_res}")

# 4. hand-verify one trade's PnL arithmetic end-to-end
from kalshi.engine import generate_trades
from kalshi.strategies import v1_rule
trades = generate_trades(v1_rule())
if trades:
    t = trades[0]
    settle = 1.0 if t["result"] == "yes" else 0.0
    want = settle - t["fill_price"] - t["fee"]
    check("trade PnL arithmetic", abs(t["pnl"] - want) < 1e-9,
          f"pnl={t['pnl']} want={want}")
    check("fee matches formula", abs(t["fee"] - taker_fee(t["fill_price"])) < 1e-9)
else:
    check("v1 produced trades", False, "zero trades")
con.close()

print()
if fails:
    print("QA FAILURES:", fails)
    sys.exit(1)
print("ALL QA CHECKS PASS")
