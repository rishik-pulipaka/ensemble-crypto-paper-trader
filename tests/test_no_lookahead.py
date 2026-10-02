"""No-lookahead tests.

For every strategy (and the regime classifier): signals computed on a
truncated series must EXACTLY equal the first N signals computed on the
full series. If any implementation peeked at future bars, truncation would
change past outputs and this fails.

Second, stronger test: corrupting all data AFTER bar N must not change any
signal at bars < N.

Run:  python3 -m pytest tests/ -q   (or python3 tests/test_no_lookahead.py)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from regime import classify  # noqa: E402
from strategies.library import ALL_STRATEGIES  # noqa: E402


def make_df(n: int = 2000, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0002, 0.004, n)
    close = 50000 * np.exp(np.cumsum(rets))
    spread = np.abs(rng.normal(0, 0.001, n))
    df = pd.DataFrame({
        "ts": np.arange(n, dtype=np.int64) * 60,
        "open": close * (1 - spread / 2),
        "high": close * (1 + spread),
        "low": close * (1 - spread),
        "close": close,
        "volume": np.abs(rng.normal(5, 2, n)),
    })
    return df


def test_truncation():
    df = make_df()
    n = len(df) // 2
    for strat in ALL_STRATEGIES:
        full = strat.generate(df)
        trunc = strat.generate(df.iloc[:n])
        pd.testing.assert_frame_equal(
            trunc.reset_index(drop=True),
            full.iloc[:n].reset_index(drop=True),
            check_dtype=False,
            obj=f"strategy {strat.name}",
        )
        print(f"  ok truncation: {strat.name}")
    reg_full = classify(df)
    reg_trunc = classify(df.iloc[:n])
    pd.testing.assert_series_equal(
        reg_trunc.reset_index(drop=True),
        reg_full.iloc[:n].reset_index(drop=True),
        check_names=False, obj="regime",
    )
    print("  ok truncation: regime")


def test_future_corruption():
    df = make_df()
    n = len(df) // 2
    bad = df.copy()
    bad.iloc[n:, bad.columns.get_loc("close")] *= 100.0
    bad.iloc[n:, bad.columns.get_loc("volume")] *= 100.0
    for strat in ALL_STRATEGIES:
        clean = strat.generate(df)
        dirty = strat.generate(bad)
        pd.testing.assert_frame_equal(
            dirty.iloc[:n].reset_index(drop=True),
            clean.iloc[:n].reset_index(drop=True),
            check_dtype=False,
            obj=f"strategy {strat.name} (future corruption)",
        )
        print(f"  ok future-corruption: {strat.name}")


if __name__ == "__main__":
    print("truncation tests:")
    test_truncation()
    print("future-corruption tests:")
    test_future_corruption()
    print("ALL NO-LOOKAHEAD TESTS PASSED")
