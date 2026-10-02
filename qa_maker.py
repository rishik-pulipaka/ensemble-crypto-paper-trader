#!/usr/bin/env python3
"""QA for simulate_maker: fill logic, fees, expiry, no-lookahead.

Synthetic bars with known prices. Every assertion is hand-computable.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import config
from backtest import simulate_maker


def bars(prices: list[tuple], start_ts: int = 1_000_000) -> pd.DataFrame:
    """prices: list of (o,h,l,c). 60s apart."""
    n = len(prices)
    return pd.DataFrame({
        "ts": [start_ts + 60 * i for i in range(n)],
        "open": [p[0] for p in prices],
        "high": [p[1] for p in prices],
        "low": [p[2] for p in prices],
        "close": [p[3] for p in prices],
        "volume": [100.0] * n,
        "datetime": pd.to_datetime([start_ts + 60 * i for i in range(n)], unit="s", utc=True),
    })


def sig_df(n: int, vote_at: int, vote: int, entry: float, inval: float) -> pd.DataFrame:
    v = np.zeros(n, dtype=int)
    e = np.full(n, np.nan)
    iv = np.full(n, np.nan)
    v[vote_at] = vote
    e[vote_at] = entry
    iv[vote_at] = inval
    return pd.DataFrame({"vote": v, "entry": e, "invalidation": iv,
                         "conviction": np.abs(v).astype(float)})


def test_no_touch_no_fill():
    # long signal at bar 2, entry 100 -> limit 99.95; price never drops there
    df = bars([(100, 101, 99.98, 100.5)] * 10)
    sig = sig_df(10, 2, 1, 100.0, 98.0)
    t = simulate_maker(df, sig, np.ones(10, bool), 10000.0, 0.01, "T")
    assert len(t) == 0, f"expected no trades, got {len(t)}"
    print("[PASS] maker-no-touch-no-fill")


def test_fill_on_touch():
    # long signal bar 2, entry 100 -> limit 99.95; bar 4 dips to 99.90 -> fill at 99.95
    px = [(100, 101, 99.98, 100.5)] * 3 + [(100.4, 100.6, 99.90, 100.2)] + [(100, 101, 99.98, 100.5)] * 6
    df = bars(px)
    sig = sig_df(10, 2, 1, 100.0, 98.0)
    t = simulate_maker(df, sig, np.ones(10, bool), 10000.0, 0.01, "T")
    assert len(t) == 1, f"expected 1 trade, got {len(t)}"
    assert abs(t["entry_px"].iloc[0] - 99.95) < 1e-9, t["entry_px"].iloc[0]
    # entry fee must be maker rate: size*fill*0.001 embedded in pnl; check fill price exact
    print("[PASS] maker-fill-on-touch at limit price")


def test_no_fill_before_signal_bar():
    # dip happens at bar 0-1, BEFORE the signal at bar 2 -> must not fill
    px = [(100.4, 100.6, 99.90, 100.2)] * 2 + [(100, 101, 99.98, 100.5)] * 8
    df = bars(px)
    sig = sig_df(10, 2, 1, 100.0, 98.0)
    t = simulate_maker(df, sig, np.ones(10, bool), 10000.0, 0.01, "T")
    assert len(t) == 0, f"lookahead fill! got {len(t)} trades"
    print("[PASS] maker-no-fill-before-signal (no lookahead)")


def test_expiry():
    # touch comes at bar 8, but order placed bar 2 with max_wait=4 -> expires bar 5
    px = [(100, 101, 99.98, 100.5)] * 6 + [(100.4, 100.6, 99.90, 100.2)] + [(100, 101, 99.98, 100.5)] * 3
    df = bars(px)
    sig = sig_df(10, 2, 1, 100.0, 98.0)
    t = simulate_maker(df, sig, np.ones(10, bool), 10000.0, 0.01, "T")
    assert len(t) == 0, f"expired order filled! got {len(t)}"
    print("[PASS] maker-order-expiry")


def test_stop_before_tp_same_bar():
    # fill at 99.95 bar 3; bar 4 touches BOTH stop (98.0) and TP (~103.9) -> stop wins
    px = ([(100, 101, 99.98, 100.5)] * 3 + [(100.4, 100.6, 99.90, 100.2)]
          + [(104.0, 105.0, 97.0, 103.0)] + [(100, 101, 99.98, 100.5)] * 5)
    df = bars(px)
    sig = sig_df(10, 2, 1, 100.0, 98.0)
    t = simulate_maker(df, sig, np.ones(10, bool), 10000.0, 0.01, "T")
    assert len(t) == 1 and t["exit_reason"].iloc[0] == "stop", t[["exit_reason"]].to_dict()
    print("[PASS] maker-stop-beats-tp-same-bar (conservative)")


def test_tp_maker_fill():
    # fill at 99.95; price rises steadily; TP = 99.95 + 2*(99.95-98) = 103.85
    px = [(100, 101, 99.98, 100.5)] * 3 + [(100.4, 100.6, 99.90, 100.2)]
    px += [(101 + i, 102 + i, 100 + i, 101.5 + i) for i in range(5)]
    df = bars(px)
    sig = sig_df(10, 2, 1, 100.0, 98.0)
    t = simulate_maker(df, sig, np.ones(10, bool), 10000.0, 0.01, "T")
    assert len(t) == 1, f"expected 1 trade, got {len(t)}"
    assert t["exit_reason"].iloc[0] == "take_profit", t["exit_reason"].iloc[0]
    assert abs(t["exit_px"].iloc[0] - 103.85) < 1e-9, t["exit_px"].iloc[0]
    # pnl check: size = 100/|99.95-98| = 51.28; gross = 51.28*(103.85-99.95) = 200.0
    # fees = 51.28*(99.95*0.001 + 103.85*0.001) = 51.28*0.2038 = 10.45
    # pnl = 200 - 10.45 = 189.55
    assert abs(t["pnl"].iloc[0] - 189.55) < 0.05, t["pnl"].iloc[0]
    print("[PASS] maker-tp-fill with exact maker-fee pnl")


def test_short_side():
    # short signal bar 2, entry 100 -> limit 100.05; bar 4 spikes to 100.10 -> fill
    px = [(100, 100.02, 99.5, 99.8)] * 3 + [(99.9, 100.10, 99.7, 99.85)] + [(100, 100.02, 99.5, 99.8)] * 6
    df = bars(px)
    sig = sig_df(10, 2, -1, 100.0, 102.0)
    t = simulate_maker(df, sig, np.ones(10, bool), 10000.0, 0.01, "T")
    assert len(t) == 1, f"expected 1 trade, got {len(t)}"
    assert abs(t["entry_px"].iloc[0] - 100.05) < 1e-9
    assert t["direction"].iloc[0] == -1
    print("[PASS] maker-short-side fill")


if __name__ == "__main__":
    test_no_touch_no_fill()
    test_fill_on_touch()
    test_no_fill_before_signal_bar()
    test_expiry()
    test_stop_before_tp_same_bar()
    test_tp_maker_fill()
    test_short_side()
    print("\nALL MAKER QA CHECKS PASSED")
