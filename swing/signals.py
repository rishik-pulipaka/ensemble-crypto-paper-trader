"""Long-only trend signals on daily bars. All canonical parameters, fixed
before seeing results — nothing is optimized.

NO-LOOKAHEAD CONVENTION (strict): for bar index i, every indicator uses
only data up to and including bar i (that day's close). The returned
`target` series gives the desired position (0/1) decided at the CLOSE of
bar i, to be implemented at the OPEN of bar i+1. The engine enforces this.

Variants:
  A tsmom     — 12-month (skip 1m) time-series momentum, monthly rebalance
  B donchian  — 100d breakout entry / 50d breakdown exit (+ ATR trailing stop
                handled by the engine)
  C ma_cross  — daily SMA50/SMA200 cross, long-only
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from swing import swing_config as C


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series,
                period: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Shared indicators, all causal (no future data). Returns a copy."""
    d = df.copy()
    c, h, l = d["close"], d["high"], d["low"]
    d["sma50"] = c.rolling(C.MA_FAST, min_periods=C.MA_FAST).mean()
    d["sma200"] = c.rolling(C.MA_SLOW, min_periods=C.MA_SLOW).mean()
    d["atr20"] = _wilder_atr(h, l, c, C.ATR_PERIOD)
    # 12m-skip-1m formation return, causal: uses close[i] and close[i-344]
    d["tsmom_ret"] = c / c.shift(C.TSMOM_FORMATION_DAYS - C.TSMOM_SKIP_DAYS) - 1.0
    # Donchian channels EXCLUDING the current bar (a breakout must exceed
    # prior bars; including the current bar makes close > max(high) impossible)
    d["dc_high"] = h.shift(1).rolling(C.DONCHIAN_ENTRY,
                                     min_periods=C.DONCHIAN_ENTRY).max()
    d["dc_low"] = l.shift(1).rolling(C.DONCHIAN_EXIT,
                                    min_periods=C.DONCHIAN_EXIT).min()
    # month-end mask for monthly-rebalance variants (tz dropped; daily bars,
    # month boundaries unaffected at this granularity)
    d["month"] = d["datetime"].dt.tz_localize(None).dt.to_period("M")
    d["is_month_end"] = d["month"] != d["month"].shift(-1)
    return d


def signal_tsmom(d: pd.DataFrame) -> pd.Series:
    """A: month-end 12-1m momentum. target decided at month-end close."""
    raw = pd.Series(np.nan, index=d.index, dtype=float)
    me = d["is_month_end"] & d["tsmom_ret"].notna()
    raw[me] = (d.loc[me, "tsmom_ret"] > 0).astype(float)
    return raw.ffill().fillna(0.0)


def signal_donchian(d: pd.DataFrame) -> pd.Series:
    """B: 100d breakout entry / 50d breakdown exit, evaluated daily at close."""
    target = pd.Series(0.0, index=d.index)
    state = 0.0
    hi = d["dc_high"].to_numpy()
    lo = d["dc_low"].to_numpy()
    cl = d["close"].to_numpy()
    for i in range(len(d)):
        if np.isnan(hi[i]) or np.isnan(lo[i]):
            target.iloc[i] = state
            continue
        if state == 0.0 and cl[i] > hi[i]:
            state = 1.0
        elif state == 1.0 and cl[i] < lo[i]:
            state = 0.0
        target.iloc[i] = state
    return target


def signal_ma_cross(d: pd.DataFrame) -> pd.Series:
    """C: long when SMA50 > SMA200 and close > SMA200, evaluated daily."""
    ok = d["sma50"].notna() & d["sma200"].notna()
    long = ok & (d["sma50"] > d["sma200"]) & (d["close"] > d["sma200"])
    return long.astype(float)


VARIANTS = {
    "tsmom": signal_tsmom,
    "donchian": signal_donchian,
    "ma_cross": signal_ma_cross,
}
