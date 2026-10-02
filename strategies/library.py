"""The five strategy implementations. Genuinely different logic:
trend = price structure (breakout), mean_reversion = value (VWAP),
momentum = velocity (ROC/RSI), volatility = range expansion (ATR),
volume = participation (relative volume).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from strategies.base import Strategy
from strategies.indicators import atr, donchian, rolling_vwap, rsi


class DonchianTrend(Strategy):
    name = "donchian_trend"
    family = "trend"  # votes only in trend regimes

    def _raw_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        hi, lo = donchian(df, config.DONCHIAN_PERIOD)
        # NOTE: bands exclude the current bar (shift 1). Comparing today's
        # close against a band that includes today's high can never fire,
        # because close <= high by definition.
        hi = hi.shift(1)
        lo = lo.shift(1)
        a = atr(df, config.ATR_PERIOD)
        close = df["close"]
        vote = pd.Series(0, index=df.index)
        vote[close > hi] = 1
        vote[close < lo] = -1
        out = pd.DataFrame(index=df.index)
        out["vote"] = vote
        out["entry"] = close
        # invalidation: breakout fails back through the opposite band
        out["invalidation"] = np.where(vote == 1, lo, np.where(vote == -1, hi, np.nan))
        dist = (close - hi).where(vote == 1, (lo - close).where(vote == -1, 0.0))
        out["conviction"] = (dist / a.replace(0, np.nan)).clip(0, 1).fillna(0)
        return out


class VwapMeanReversion(Strategy):
    name = "vwap_mr"
    family = "mean_reversion"  # votes only in chop regimes

    def _raw_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        vwap = rolling_vwap(df, config.VWAP_WINDOW)
        dev = df["close"] - vwap
        sd = dev.rolling(config.VWAP_WINDOW, min_periods=config.VWAP_WINDOW).std()
        z = dev / sd.replace(0, np.nan)
        close = df["close"]
        vote = pd.Series(0, index=df.index)
        vote[z <= -config.VWAP_Z_ENTRY] = 1   # stretched below value -> long
        vote[z >= config.VWAP_Z_ENTRY] = -1  # stretched above value -> short
        out = pd.DataFrame(index=df.index)
        out["vote"] = vote
        out["entry"] = close
        # invalidation: keeps stretching another 1.5 sigma against us
        stop_dist = 1.5 * sd
        out["invalidation"] = np.where(
            vote == 1, close - stop_dist, np.where(vote == -1, close + stop_dist, np.nan)
        )
        out["conviction"] = (z.abs() / (2 * config.VWAP_Z_ENTRY)).clip(0, 1).fillna(0)
        return out


class MomentumROC(Strategy):
    name = "momentum_roc"
    family = "momentum"  # votes in both regimes (weight-adjusted)

    def _raw_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"]
        roc = close / close.shift(config.ROC_PERIOD) - 1
        r = rsi(close, config.RSI_PERIOD)
        a = atr(df, config.ATR_PERIOD)
        vote = pd.Series(0, index=df.index)
        long_sig = (roc > config.MOMENTUM_MIN_ROC) & (r > 55)
        short_sig = (roc < -config.MOMENTUM_MIN_ROC) & (r < 45)
        vote[long_sig] = 1
        vote[short_sig] = -1
        out = pd.DataFrame(index=df.index)
        out["vote"] = vote
        out["entry"] = close
        out["invalidation"] = np.where(
            vote == 1, close - 1.5 * a, np.where(vote == -1, close + 1.5 * a, np.nan)
        )
        out["conviction"] = ((r - 50).abs() / 50).clip(0, 1).fillna(0)
        return out


class VolatilityExpansion(Strategy):
    name = "vol_expansion"
    family = "volatility"  # votes in both regimes (weight-adjusted)

    def _raw_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        a = atr(df, config.ATR_PERIOD)
        rng = df["high"] - df["low"]
        expand = rng > a * config.ATR_EXPANSION_MULT
        up_bar = df["close"] > df["open"]
        vote = pd.Series(0, index=df.index)
        vote[expand & up_bar] = 1
        vote[expand & ~up_bar] = -1
        out = pd.DataFrame(index=df.index)
        out["vote"] = vote
        out["entry"] = df["close"]
        out["invalidation"] = np.where(
            vote == 1, df["close"] - a, np.where(vote == -1, df["close"] + a, np.nan)
        )
        out["conviction"] = (rng / (a * config.ATR_EXPANSION_MULT) - 1).clip(0, 1).fillna(0)
        return out


class VolumeParticipation(Strategy):
    name = "volume_participation"
    family = "volume"  # votes in both regimes (weight-adjusted)

    def _raw_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        sma_v = df["volume"].rolling(config.VOLUME_LOOKBACK,
                                     min_periods=config.VOLUME_LOOKBACK).mean()
        part = df["volume"] > sma_v * config.VOLUME_MULT
        up_bar = df["close"] > df["open"]
        vote = pd.Series(0, index=df.index)
        vote[part & up_bar] = 1
        vote[part & ~up_bar] = -1
        out = pd.DataFrame(index=df.index)
        out["vote"] = vote
        out["entry"] = df["close"]
        # invalidation: the bar's opposite extreme (thesis = directional bar)
        out["invalidation"] = np.where(
            vote == 1, df["low"], np.where(vote == -1, df["high"], np.nan)
        )
        out["conviction"] = (
            df["volume"] / (sma_v * config.VOLUME_MULT) - 1
        ).clip(0, 1).fillna(0)
        return out


ALL_STRATEGIES: list[Strategy] = [
    DonchianTrend(),
    VwapMeanReversion(),
    MomentumROC(),
    VolatilityExpansion(),
    VolumeParticipation(),
]
