#!/usr/bin/env python3
"""Parallel historical backfill. Splits the time range into N disjoint
chunks, fetches each with its own worker thread (Coinbase public REST,
~300 candles/request), writes via INSERT OR IGNORE (idempotent).

Usage: python3 scripts/parallel_backfill.py [--years 2] [--workers 6]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from data.fetcher import fetch_candles

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / config.DB_PATH
LOCK = threading.Lock()
INSERTED = 0


def worker(pair: str, start, end, gran: int):
    global INSERTED
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL;")
    cur_start = start
    local = 0
    try:
        while cur_start < end:
            cur_end = min(end, cur_start + timedelta(seconds=gran * 300))
            try:
                df = fetch_candles(pair, cur_start, cur_end, gran)
            except Exception as e:  # noqa: BLE001 - keep going on transient errors
                print(f"[{pair}] chunk {cur_start.date()} error: {e}; retrying",
                      flush=True)
                time.sleep(5)
                continue
            if not df.empty:
                rows = [(pair, int(r.ts), float(r.open), float(r.high),
                         float(r.low), float(r.close), float(r.volume))
                        for r in df.itertuples()]
                with LOCK:
                    c = conn.executemany(
                        "INSERT OR IGNORE INTO candles(pair,ts,open,high,low,"
                        "close,volume) VALUES (?,?,?,?,?,?,?)", rows)
                    conn.commit()
                    INSERTED += c.rowcount
                    local += c.rowcount
            cur_start = cur_end
    finally:
        conn.close()
    print(f"[{pair}] worker done: {local} new bars", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=config.HISTORY_YEARS)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS candles (pair TEXT, ts INTEGER, open REAL,"
        " high REAL, low REAL, close REAL, volume REAL,"
        " PRIMARY KEY (pair, ts));")
    conn.close()

    for pair in config.PAIRS:
        end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        start = end - timedelta(days=365 * args.years)
        total_sec = (end - start).total_seconds()
        chunk = total_sec / args.workers
        print(f"[{pair}] {args.workers} workers over "
              f"{start.date()} -> {end.date()}", flush=True)
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = []
            for w in range(args.workers):
                ws = start + timedelta(seconds=chunk * w)
                we = start + timedelta(seconds=chunk * (w + 1))
                futs.append(ex.submit(worker, pair, ws, we,
                                      config.GRANULARITY_SECONDS))
            for f in futs:
                f.result()
        print(f"[{pair}] done. total inserted this run: {INSERTED}", flush=True)


if __name__ == "__main__":
    main()
