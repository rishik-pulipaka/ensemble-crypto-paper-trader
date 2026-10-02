"""Resume Kalshi data fetch after interruption.

Skips tickers already in the dev markets table (with candles), fetches
candles only for NEW markets. Lockbox markets are never touched.

Usage: python3 -m kalshi.resume_fetch [--series KXNFLGAME,KXNBA]
"""
import argparse
import sqlite3
import time
import urllib.parse

from .kalshi_data import (_get, _price_block, _throttle, _ts, fetch_candles,
                          init_db)
from .kalshi_config import API_BASE, LOCKBOX_START_TS, MIN_VOLUME, SERIES


def cached_tickers(con):
    rows = con.execute("SELECT ticker FROM markets").fetchall()
    return {r[0] for r in rows}


def resume(series_list=None):
    con = init_db()
    seen = cached_tickers(con)
    cur = con.cursor()
    last = time.time()
    new_mkts, new_candles, skipped = 0, 0, 0
    for series in (series_list or SERIES):
        # paginate market list (cheap, no candles yet)
        cursor, fresh = "", []
        while True:
            last = _throttle(last)
            path = f"/historical/markets?series_ticker={series}&limit=1000"
            if cursor:
                path += "&cursor=" + urllib.parse.quote(cursor, safe="")
            d = _get(path)
            mkts = d.get("markets", [])
            for m in mkts:
                if m.get("result") not in ("yes", "no"):
                    continue
                exp = _ts(m.get("expiration_time"))
                if exp is None or exp >= LOCKBOX_START_TS:
                    continue
                vol = float(m.get("volume_fp") or 0)
                if vol < MIN_VOLUME:
                    continue
                if m["ticker"] in seen:
                    skipped += 1
                    continue
                fresh.append(m)
            cursor = d.get("cursor") or ""
            if not cursor:
                break
        print(f"{series}: {len(fresh)} new markets to fetch "
              f"({skipped} already cached)", flush=True)
        for m in fresh:
            cur.execute(
                "INSERT OR REPLACE INTO markets VALUES (?,?,?,?,?,?,?,?,?,?)",
                (m["ticker"], series, m.get("event_ticker"), m.get("title"),
                 m.get("market_type"), m.get("result"),
                 _ts(m.get("expiration_time")),
                 _ts(m.get("open_time")), _ts(m.get("close_time")),
                 float(m.get("volume_fp") or 0)))
            con.commit()  # short txn: never hold a write lock across network I/O
            new_mkts += 1
            ot, ct = _ts(m.get("open_time")), _ts(m.get("close_time"))
            if ot and ct:
                last = _throttle(last)
                try:
                    candles = fetch_candles(m["ticker"], ot - 86400, ct + 86400)
                except Exception as e:
                    print(f"  candle fetch failed {m['ticker']}: {e}", flush=True)
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
                con.commit()  # short txn per market
                new_candles += len(rows)
            seen.add(m["ticker"])
            if new_mkts % 25 == 0:
                print(f"  ...{new_mkts} new markets, {new_candles} new candles",
                      flush=True)
        con.commit()
    con.close()
    print(f"RESUME DONE: +{new_mkts} markets, +{new_candles} candles "
          f"({skipped} skipped as cached)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default="",
                    help="comma-separated series tickers, default all")
    a = ap.parse_args()
    sl = [s.strip() for s in a.series.split(",") if s.strip()] or None
    resume(sl)
