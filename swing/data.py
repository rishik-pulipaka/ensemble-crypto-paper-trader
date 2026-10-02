"""Daily-bar data for the swing system.

Fetches from Coinbase public REST (granularity=86400, max 300/request, no
auth), caches in the shared market.db under "<PAIR>:1D" keys.

The swing lockbox (SWING_HOLDOUT_START_TS) is enforced HERE at load time:
load_swing() refuses to return holdout bars. The only permitted access is
swing/evaluate_holdout.py.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.fetcher import fetch_candles
from data.store import CandleStore

from swing import swing_config as C


def swing_pair(pair: str) -> str:
    return pair + C.SWING_DB_PAIR_SUFFIX


def ensure_swing_data(pairs: list[str] | None = None,
                      progress=None) -> dict[str, pd.DataFrame]:
    """Backfill daily bars from SWING_HISTORY_START to now. Returns {pair: df}."""
    pairs = pairs or C.SWING_PAIRS
    store = CandleStore(ROOT / "data" / "market.db")
    out: dict[str, pd.DataFrame] = {}
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0,
                                             microsecond=0)
    for pair in pairs:
        key = pair + C.SWING_DB_PAIR_SUFFIX
        cov = store.coverage(key)
        have = cov["bars"] or 0
        if have < 3000:  # ~10y of daily bars is ~3650; backfill if short
            print(f"[swing-data] {pair}: have {have} daily bars, backfilling...",
                  flush=True)
            df = fetch_candles(pair, C.SWING_HISTORY_START, end,
                               granularity=C.SWING_GRANULARITY)
            n = store.upsert(key, df)
            print(f"[swing-data] {pair}: inserted {n} daily bars", flush=True)
        full = store.load(key)
        out[pair] = full
        if not full.empty:
            print(f"[swing-data] {pair}: {len(full)} daily bars "
                  f"({full['datetime'].iloc[0].date()} -> "
                  f"{full['datetime'].iloc[-1].date()})", flush=True)
    store.close()
    return out


def load_swing(pair: str, include_holdout: bool = False) -> pd.DataFrame:
    """Load daily bars for a pair. Holdout bars are EXCLUDED unless
    include_holdout=True (only evaluate_holdout.py may pass True)."""
    store = CandleStore(ROOT / "data" / "market.db")
    df = store.load(pair + C.SWING_DB_PAIR_SUFFIX)
    store.close()
    if not include_holdout:
        df = df[df["ts"] < C.SWING_HOLDOUT_START_TS].reset_index(drop=True)
    return df
