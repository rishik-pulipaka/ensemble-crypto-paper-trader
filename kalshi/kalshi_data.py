"""Fetch settled Kalshi markets + daily candles into SQLite.

Public unauthenticated endpoints only. No keys, no trading.
Dev data = markets expiring BEFORE LOCKBOX_START_TS (historical tier).
Lockbox markets are NEVER fetched here; see evaluate_holdout.py.

Usage:
    python3 -m kalshi.kalshi_data --fetch        # full dev universe
    python3 -m kalshi.kalshi_data --stats        # report what is cached
"""
import argparse
import json
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import datetime

from .kalshi_config import (API_BASE, CANDLE_INTERVAL, DB_PATH,
                            LOCKBOX_START_TS, MIN_VOLUME, SERIES)

UA = {"User-Agent": "research-paper-bot", "Accept": "application/json"}
REQ_PER_SEC = 5.0


def _get(path, retries=5):
    url = API_BASE + path
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=UA)
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                time.sleep(2 ** attempt + 1)
                continue
            raise
        except Exception:
            if attempt < retries - 1:
                time.sleep(2 ** attempt + 1)
                continue
            raise
    raise RuntimeError("unreachable")


def _throttle(last):
    dt = time.time() - last
    if dt < 1.0 / REQ_PER_SEC:
        time.sleep(1.0 / REQ_PER_SEC - dt)
    return time.time()


def _ts(iso):
    if not iso:
        return None
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def init_db():
    con = sqlite3.connect(DB_PATH, timeout=60.0)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""CREATE TABLE IF NOT EXISTS markets (
        ticker TEXT PRIMARY KEY, series TEXT, event_ticker TEXT, title TEXT,
        market_type TEXT, result TEXT, expiration_ts INTEGER, open_ts INTEGER,
        close_ts INTEGER, volume REAL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS candles (
        ticker TEXT, end_ts INTEGER,
        bid_o REAL, bid_h REAL, bid_l REAL, bid_c REAL,
        ask_o REAL, ask_h REAL, ask_l REAL, ask_c REAL, volume REAL,
        PRIMARY KEY (ticker, end_ts))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_candles_ticker ON candles(ticker)")
    con.commit()
    return con


def _price_block(c, side):
    """Candles carry yes_bid/yes_ask as nested dicts; parse defensively."""
    blk = c.get("yes_" + side)
    if isinstance(blk, dict):
        def g(k):
            v = blk.get(k + "_dollars", blk.get(k))
            return float(v) if v is not None else None
        return g("open"), g("high"), g("low"), g("close")
    # flat fallback
    def g2(k):
        v = c.get(f"yes_{side}_{k}_dollars", c.get(f"yes_{side}_{k}"))
        return float(v) if v is not None else None
    return g2("open"), g2("high"), g2("low"), g2("close")


def fetch_markets(series):
    """All archived settled markets for a series (cursor pagination)."""
    out, cursor, last = [], "", time.time()
    while True:
        last = _throttle(last)
        path = f"/historical/markets?series_ticker={series}&limit=1000"
        if cursor:
            path += "&cursor=" + urllib.parse.quote(cursor, safe="")
        d = _get(path)
        out.extend(d.get("markets", []))
        cursor = d.get("cursor") or ""
        if not cursor:
            break
    return out


def fetch_candles(ticker, start_ts, end_ts):
    t = urllib.parse.quote(ticker, safe="")
    d = _get(f"/historical/markets/{t}/candlesticks?start_ts={start_ts}"
             f"&end_ts={end_ts}&period_interval={CANDLE_INTERVAL}")
    return d.get("candlesticks", [])


def fetch_all():
    con = init_db()
    cur = con.cursor()
    total_mkts, total_candles = 0, 0
    last = time.time()
    for series in SERIES:
        markets = fetch_markets(series)
        kept = 0
        for m in markets:
            if m.get("result") not in ("yes", "no"):
                continue
            exp = _ts(m.get("expiration_time"))
            if exp is None or exp >= LOCKBOX_START_TS:
                continue  # lockbox: never touch
            vol = float(m.get("volume_fp") or 0)
            if vol < MIN_VOLUME:
                continue
            cur.execute(
                "INSERT OR REPLACE INTO markets VALUES (?,?,?,?,?,?,?,?,?,?)",
                (m["ticker"], series, m.get("event_ticker"), m.get("title"),
                 m.get("market_type"), m.get("result"), exp,
                 _ts(m.get("open_time")), _ts(m.get("close_time")), vol))
            kept += 1
            # candles in the market's active window (+/- 1 day margin)
            ot, ct = _ts(m.get("open_time")), _ts(m.get("close_time"))
            if ot and ct:
                last = _throttle(last)
                try:
                    candles = fetch_candles(m["ticker"], ot - 86400, ct + 86400)
                except Exception as e:
                    print(f"  candle fetch failed {m['ticker']}: {e}")
                    continue
                rows = []
                for c in candles:
                    end_ts = c.get("end_period_ts")
                    if end_ts is None:
                        continue
                    bo, bh, bl, bc = _price_block(c, "bid")
                    ao, ah, al, ac = _price_block(c, "ask")
                    v = c.get("volume_fp")
                    rows.append((m["ticker"], int(end_ts), bo, bh, bl, bc,
                                 ao, ah, al, ac,
                                 float(v) if v is not None else None))
                cur.executemany(
                    "INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    rows)
                total_candles += len(rows)
        con.commit()
        total_mkts += kept
        print(f"{series}: {kept} dev markets kept, {total_candles} candles total",
              flush=True)
    con.close()
    print(f"DONE: {total_mkts} markets, {total_candles} candles -> {DB_PATH}")


def stats():
    con = sqlite3.connect(DB_PATH)
    n_m = con.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
    n_c = con.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
    print(f"markets: {n_m}, candles: {n_c}")
    for row in con.execute(
            "SELECT series, COUNT(*), MIN(expiration_ts), MAX(expiration_ts) "
            "FROM markets GROUP BY series ORDER BY 2 DESC"):
        lo = datetime.utcfromtimestamp(row[2]).date()
        hi = datetime.utcfromtimestamp(row[3]).date()
        print(f"  {row[0]}: {row[1]} markets, {lo} -> {hi}")
    # lockbox safety: nothing at/after boundary
    bad = con.execute("SELECT COUNT(*) FROM markets WHERE expiration_ts >= ?",
                      (LOCKBOX_START_TS,)).fetchone()[0]
    print(f"lockbox violations in dev table: {bad}")
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()
    if a.fetch:
        fetch_all()
    if a.stats or not (a.fetch or a.stats):
        stats()
