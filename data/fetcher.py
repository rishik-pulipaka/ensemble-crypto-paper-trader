"""Coinbase Exchange public market-data fetcher. No auth, no keys, no account.

Endpoints used (all public):
    GET /products/{pair}/candles?start=&end=&granularity=60   (max 300/request)
    GET /products/{pair}/ticker                                (latest price)

Rate limit: public endpoints allow ~10 req/s; we stay at ~4 req/s.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

BASE = "https://api.exchange.coinbase.com"
HEADERS = {"User-Agent": "ensemble-paper-bot-v1 (paper trading research)"}
REQ_PER_SEC = 4.0


def _get(url: str, params: dict | None = None, retries: int = 5) -> requests.Response:
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as e:  # noqa: BLE001 - retry loop
            last = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last}")


def fetch_candles(pair: str, start: datetime, end: datetime,
                  granularity: int = 60) -> pd.DataFrame:
    """Fetch [start, end) candles, paginating 300/request, newest-first API."""
    frames: list[pd.DataFrame] = []
    cursor_end = end
    while True:
        cursor_start = cursor_end - timedelta(seconds=granularity * 300)
        if cursor_start < start:
            cursor_start = start
        r = _get(
            f"{BASE}/products/{pair}/candles",
            params={
                "start": cursor_start.isoformat(),
                "end": cursor_end.isoformat(),
                "granularity": granularity,
            },
        )
        raw = r.json()
        if raw:
            df = pd.DataFrame(
                raw, columns=["ts", "low", "high", "open", "close", "volume"]
            )
            df = df[["ts", "open", "high", "low", "close", "volume"]]
            frames.append(df)
        if cursor_start <= start:
            break
        cursor_end = cursor_start
        time.sleep(1.0 / REQ_PER_SEC)
    if not frames:
        return pd.DataFrame(
            columns=["ts", "open", "high", "low", "close", "volume"]
        )
    out = pd.concat(frames, ignore_index=True).drop_duplicates("ts")
    out = out.sort_values("ts").reset_index(drop=True)
    return out


def backfill_years(pair: str, years: float, store, granularity: int = 60,
                   progress=None) -> int:
    """Fetch ~`years` of history into `store`. Returns bars inserted."""
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(days=365 * years)
    total = 0
    cursor_end = end
    while True:
        cursor_start = cursor_end - timedelta(seconds=granularity * 300)
        if cursor_start < start:
            cursor_start = start
        df = fetch_candles(pair, cursor_start, cursor_end, granularity)
        if not df.empty:
            total += store.upsert(pair, df)
        if progress:
            progress(pair, cursor_start, total)
        if cursor_start <= start:
            break
        cursor_end = cursor_start
    return total


def latest_bars(pair: str, n: int = 600,
                granularity: int = 60) -> pd.DataFrame:
    """Most recent `n` bars (for the live paper loop warmup)."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(seconds=granularity * (n + 5))
    return fetch_candles(pair, start, end, granularity)


def latest_price(pair: str) -> float:
    r = _get(f"{BASE}/products/{pair}/ticker")
    return float(r.json()["price"])
