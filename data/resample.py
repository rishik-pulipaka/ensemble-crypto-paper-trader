"""Resample 1-minute OHLCV bars to larger timeframes.

Pure aggregation, no fabrication: a bucket is emitted only if it contains
at least one source bar. Gaps in the source propagate as gaps (no forward
fill), so backtests never trade on invented bars.
"""
from __future__ import annotations

import pandas as pd


def to_ohlcv(df: pd.DataFrame, seconds: int) -> pd.DataFrame:
    """Aggregate 1-min bars to `seconds`-second bars.

    Expects columns [ts, open, high, low, close, volume] with ts = unix epoch
    (bar open time), sorted ascending. Returns same schema with ts aligned to
    bucket open time.
    """
    if seconds <= 60:
        return df.copy().reset_index(drop=True)
    d = df.copy()
    d["bucket"] = (d["ts"] // seconds) * seconds
    g = d.groupby("bucket", sort=True)
    out = pd.DataFrame({
        "ts": g["bucket"].first(),
        "open": g["open"].first(),
        "high": g["high"].max(),
        "low": g["low"].min(),
        "close": g["close"].last(),
        "volume": g["volume"].sum(),
    }).reset_index(drop=True)
    out["ts"] = out["ts"].astype(int)
    out["datetime"] = pd.to_datetime(out["ts"], unit="s", utc=True)
    return out[["ts", "open", "high", "low", "close", "volume", "datetime"]]
