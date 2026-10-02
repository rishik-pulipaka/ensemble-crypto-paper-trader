"""Strategy base class.

Contract: subclass implements _raw_signals(df) returning a DataFrame with
columns [vote, entry, invalidation, conviction].
- vote: -1 (short), 0 (flat), +1 (long)
- entry: reference price for sizing
- invalidation: price where the thesis is dead (becomes the stop-loss)
- conviction: 0..1

generate() applies a CENTRAL one-bar shift: the signal published for bar t
is computed from data through bar t-1 ONLY. Backtest/paper engines execute
at bar t's open. Individual strategies cannot peek at the future even by
accident, and tests/test_no_lookahead.py verifies it by truncation.
"""
from __future__ import annotations

import pandas as pd

OUTPUT_COLS = ["vote", "entry", "invalidation", "conviction"]


class Strategy:
    name = "base"
    family = "base"  # one of: trend, mean_reversion, momentum, volatility, volume

    def _raw_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        raw = self._raw_signals(df).copy()
        for c in OUTPUT_COLS:
            if c not in raw.columns:
                raw[c] = 0.0 if c != "vote" else 0
        raw = raw[OUTPUT_COLS]
        # Sanitize: a vote whose invalidation equals (or NaNs with) the entry
        # has zero risk distance and is not a tradeable setup (e.g. zero-range
        # doji bars). Kill the vote centrally so no engine can act on it.
        bad = (
            raw["invalidation"].isna()
            | (raw["entry"] - raw["invalidation"]).abs() < 1e-9
        )
        raw.loc[bad, "vote"] = 0
        # Central no-lookahead shift: signal for bar t uses data <= t-1.
        out = raw.shift(1)
        out["vote"] = out["vote"].fillna(0).astype(int)
        return out
