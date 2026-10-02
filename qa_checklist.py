#!/usr/bin/env python3
"""QA checklist runner. Verifies each item, prints PASS/FAIL, exits nonzero
on any failure. Run from the project root.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from data.store import CandleStore
from regime import classify
from strategies.library import ALL_STRATEGIES

ROOT = Path(__file__).resolve().parent
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = ""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    store = CandleStore(ROOT / config.DB_PATH)
    df = store.load("BTC-USD")
    store.close()
    print(f"data: {len(df)} BTC bars")
    check("data-nonempty", len(df) > 50000, f"{len(df)} bars")

    # --- 3. strategy sanity on real data ---------------------------------
    for s in ALL_STRATEGIES:
        try:
            sig = s.generate(df)
        except Exception as e:  # noqa: BLE001
            check(f"strategy-{s.name}-runs", False, repr(e))
            continue
        check(f"strategy-{s.name}-runs", True)
        votes = sig["vote"]
        check(f"strategy-{s.name}-votes-valid",
              set(votes.unique()) <= {-1, 0, 1},
              f"values={sorted(votes.unique())}")
        # no NaN votes; entry/invalidation finite wherever vote != 0
        check(f"strategy-{s.name}-no-nan-vote", not votes.isna().any())
        nz = sig[votes != 0]
        check(f"strategy-{s.name}-finite-levels",
              np.isfinite(nz["entry"]).all() and np.isfinite(nz["invalidation"]).all(),
              f"voting bars={len(nz)}")
        # conviction in [0,1]
        c = sig["conviction"].fillna(0)
        check(f"strategy-{s.name}-conviction-range",
              ((c >= 0) & (c <= 1)).all())
        # invalidation on the correct side of entry
        if len(nz):
            long_ok = ((nz["invalidation"] < nz["entry"]) | (nz["vote"] != 1)).all()
            short_ok = ((nz["invalidation"] > nz["entry"]) | (nz["vote"] != -1)).all()
            check(f"strategy-{s.name}-invalidation-side", bool(long_ok and short_ok))
        # votes actually fire (not all flat) and not all one direction
        check(f"strategy-{s.name}-fires",
              (votes != 0).sum() > 100, f"signals={(votes != 0).sum()}")
        longs = (votes == 1).sum()
        shorts = (votes == -1).sum()
        check(f"strategy-{s.name}-both-sides",
              longs > 10 and shorts > 10, f"L={longs} S={shorts}")

    # --- edge cases: zero volume, gaps, flat prices -----------------------
    edge = df.iloc[:5000].copy()
    edge.iloc[100:200, edge.columns.get_loc("volume")] = 0.0   # zero volume block
    edge.iloc[300:310, edge.columns.get_loc("close")] = edge["close"].iloc[299]  # flat
    for s in ALL_STRATEGIES:
        try:
            sig = s.generate(edge)
            ok = set(sig["vote"].unique()) <= {-1, 0, 1} and not sig["vote"].isna().any()
            check(f"strategy-{s.name}-edge-cases", ok)
        except Exception as e:  # noqa: BLE001
            check(f"strategy-{s.name}-edge-cases", False, repr(e))

    # --- 4. regime filter switches ----------------------------------------
    reg = classify(df)
    counts = reg.value_counts()
    print(f"  regime mix: {counts.to_dict()}")
    check("regime-has-trend", (reg == "trend").sum() > 1000,
          f"trend bars={(reg == 'trend').sum()}")
    check("regime-has-chop", (reg == "chop").sum() > 1000,
          f"chop bars={(reg == 'chop').sum()}")
    # switches: count transitions
    transitions = (reg != reg.shift(1)).sum()
    check("regime-switches", transitions > 50, f"transitions={transitions}")
    check("regime-not-stuck", transitions < len(reg) * 0.5)

    print()
    if FAILURES:
        print(f"FAILURES ({len(FAILURES)}):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("ALL QA CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
