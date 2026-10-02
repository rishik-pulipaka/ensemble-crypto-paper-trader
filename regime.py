"""ADX-based regime classifier: 'trend' vs 'chop'.

Causal (uses the same centrally-shifted convention: classify() shifts by 1
so the regime published for bar t uses data through bar t-1).
"""
from __future__ import annotations

import pandas as pd

import config
from strategies.indicators import adx


def classify(df: pd.DataFrame) -> pd.Series:
    a = adx(df, config.ADX_PERIOD)
    regime = pd.Series("chop", index=df.index)
    regime[a >= config.ADX_TREND_THRESHOLD] = "trend"
    regime[a.isna()] = "chop"  # warmup => chop (conservative)
    return regime.shift(1).fillna("chop")
