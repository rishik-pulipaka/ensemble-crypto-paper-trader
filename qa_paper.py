#!/usr/bin/env python3
"""QA: paper engine persistence across restarts, no duplicate fills,
portfolio math reconciliation. Uses a temp DB; no network needed
(position management is pure price math).
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paper import PaperEngine  # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    if not cond:
        FAIL.append(name)


tmp = Path(tempfile.mkdtemp())
db = tmp / "paper_test.db"
now = datetime.now(timezone.utc)
bar = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5}

# 1. open a position, close engine, reopen -> persists
eng = PaperEngine(db)
b0 = eng.bankroll
action = {"direction": 1, "size_units": 10.0, "invalidation": 97.0,
          "agreeing": ["a", "b", "c"], "risk_usd": 30.0}
eng._open_position("BTC-USD", action, bar, now)
eng.close()

eng2 = PaperEngine(db)
rows = eng2.conn.execute("SELECT COUNT(*) FROM paper_positions").fetchone()[0]
check("paper-persists-across-restart", rows == 1, f"positions={rows}")
check("paper-bankroll-unchanged-by-open", abs(eng2.bankroll - b0) < 1e-9)

# 2. stop-hit bar closes it exactly once
pos = eng2.conn.execute(
    "SELECT stop_px, tp_px, entry_px FROM paper_positions").fetchone()
stop_px, tp_px, entry_px = pos
kill_bar = {"open": 100.0, "high": 100.5, "low": stop_px - 1.0, "close": 99.0}
eng2._manage_positions("BTC-USD", kill_bar, now)
n_pos = eng2.conn.execute("SELECT COUNT(*) FROM paper_positions").fetchone()[0]
n_trd = eng2.conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
check("paper-stop-closes-position", n_pos == 0 and n_trd == 1)

# 3. same bar again -> no duplicate fill
eng2._manage_positions("BTC-USD", kill_bar, now)
n_trd2 = eng2.conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
check("paper-no-duplicate-fill", n_trd2 == 1, f"trades={n_trd2}")

# 4. reconciliation: bankroll moved by exactly the trade pnl, nothing else
tr = eng2.conn.execute(
    "SELECT pnl, entry_px, exit_px, size, direction FROM paper_trades").fetchone()
pnl, epx, xpx, size, direction = tr
import config
slip, fee = config.SLIPPAGE_PER_SIDE, config.FEE_PER_SIDE
exp_exit = stop_px * (1 - slip * 1)
exp_pnl = 1 * size * (exp_exit - epx) - size * (epx * fee + exp_exit * fee)
check("paper-pnl-math", abs(pnl - exp_pnl) < 1e-6, f"pnl={pnl:.4f} expected={exp_pnl:.4f}")
check("paper-bankroll-reconciles", abs(eng2.bankroll - (b0 + pnl)) < 1e-6,
      f"bankroll={eng2.bankroll:.2f}")

# 5. daily-loss halt state survives in risk manager within a session
eng2.risk.new_day("2026-01-01", eng2.bankroll)
eng2.risk.register_open()
eng2.risk.register_close(-eng2.bankroll * 0.05)
ok, reason = eng2.risk.can_open()
check("paper-risk-halt-wired", not ok, reason)
eng2.close()

print()
if FAIL:
    print(f"FAILURES: {FAIL}")
    sys.exit(1)
print("ALL PAPER PERSISTENCE CHECKS PASSED")
