"""Local SQLite cache for OHLCV bars.

Schema:
    candles(pair TEXT, ts INTEGER, open REAL, high REAL, low REAL,
            close REAL, volume REAL, PRIMARY KEY (pair, ts))
ts is unix epoch seconds, bar open time.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    pair   TEXT NOT NULL,
    ts     INTEGER NOT NULL,
    open   REAL NOT NULL,
    high   REAL NOT NULL,
    low    REAL NOT NULL,
    close  REAL NOT NULL,
    volume REAL NOT NULL,
    PRIMARY KEY (pair, ts)
);
CREATE INDEX IF NOT EXISTS idx_candles_pair_ts ON candles(pair, ts);
"""


class CandleStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.executescript(SCHEMA)

    def upsert(self, pair: str, df: pd.DataFrame) -> int:
        """Insert bars; ignore duplicates. df needs ts/open/high/low/close/volume."""
        rows = [
            (pair, int(r.ts), float(r.open), float(r.high), float(r.low),
             float(r.close), float(r.volume))
            for r in df.itertuples()
        ]
        cur = self.conn.executemany(
            "INSERT OR IGNORE INTO candles(pair,ts,open,high,low,close,volume)"
            " VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        self.conn.commit()
        return cur.rowcount

    def load(self, pair: str, start_ts: int | None = None,
             end_ts: int | None = None) -> pd.DataFrame:
        q = ("SELECT ts, open, high, low, close, volume FROM candles "
             "WHERE pair = ?")
        params: list = [pair]
        if start_ts is not None:
            q += " AND ts >= ?"
            params.append(start_ts)
        if end_ts is not None:
            q += " AND ts <= ?"
            params.append(end_ts)
        q += " ORDER BY ts ASC"
        df = pd.read_sql_query(q, self.conn, params=params)
        if not df.empty:
            df["datetime"] = pd.to_datetime(df["ts"], unit="s", utc=True)
        return df

    def coverage(self, pair: str) -> dict:
        cur = self.conn.execute(
            "SELECT COUNT(*), MIN(ts), MAX(ts) FROM candles WHERE pair = ?",
            (pair,),
        )
        n, lo, hi = cur.fetchone()
        return {"bars": n, "first_ts": lo, "last_ts": hi}

    def close(self):
        self.conn.close()
