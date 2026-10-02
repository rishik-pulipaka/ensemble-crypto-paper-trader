"""ONE-SHOT lockbox evaluator for Kalshi versions.

Runs AT MOST ONCE (marker file). Fetch the quarantined markets
(expiring in [LOCKBOX_START_TS, now]) into SEPARATE tables so dev data
is never contaminated, run the given version's rule, report, then burn
the marker so it can never run again.

Only run this for a version that PASSED on its own OOS dev data with a
meaningful sample. Usage:
    python3 -m kalshi.evaluate_lockbox --version v1
"""
import argparse
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kalshi import strategies
from kalshi.engine import generate_trades, summarize
from kalshi.kalshi_config import (DB_PATH, LOCKBOX_START_TS, MARKER_DIR,
                                  MIN_VOLUME, SERIES)
from kalshi.kalshi_data import (_get, _price_block, _throttle, _ts,
                                fetch_candles, init_db)
from kalshi.validate import report

MARKER = os.path.join(MARKER_DIR, ".lockbox_used")
NOW_TS = int(time.time())

RULES = {
    "v1": strategies.v1_rule,
    "v3": strategies.v3_rule,
}


def fetch_lockbox():
    con = init_db()
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS lockbox_markets (
        ticker TEXT PRIMARY KEY, series TEXT, event_ticker TEXT, title TEXT,
        market_type TEXT, result TEXT, expiration_ts INTEGER, open_ts INTEGER,
        close_ts INTEGER, volume REAL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS lockbox_candles (
        ticker TEXT, end_ts INTEGER,
        bid_o REAL, bid_h REAL, bid_l REAL, bid_c REAL,
        ask_o REAL, ask_h REAL, ask_l REAL, ask_c REAL, volume REAL,
        PRIMARY KEY (ticker, end_ts))""")
    con.commit()
    last = time.time()
    n_m, n_c = 0, 0
    for series in SERIES:
        cursor = ""
        while True:
            last = _throttle(last)
            path = f"/historical/markets?series_ticker={series}&limit=1000"
            if cursor:
                path += "&cursor=" + urllib.parse.quote(cursor, safe="")
            d = _get(path)
            for m in d.get("markets", []):
                if m.get("result") not in ("yes", "no"):
                    continue
                exp = _ts(m.get("expiration_time"))
                if exp is None or exp < LOCKBOX_START_TS or exp > NOW_TS:
                    continue
                vol = float(m.get("volume_fp") or 0)
                if vol < MIN_VOLUME:
                    continue
                cur.execute(
                    "INSERT OR REPLACE INTO lockbox_markets VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (m["ticker"], series, m.get("event_ticker"), m.get("title"),
                     m.get("market_type"), m.get("result"), exp,
                     _ts(m.get("open_time")), _ts(m.get("close_time")), vol))
                n_m += 1
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
                        "INSERT OR REPLACE INTO lockbox_candles VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        rows)
                    n_c += len(rows)
            con.commit()
            cursor = d.get("cursor") or ""
            if not cursor:
                break
        print(f"{series}: lockbox markets so far: {n_m}", flush=True)
    con.close()
    return n_m, n_c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, choices=list(RULES))
    a = ap.parse_args()
    if os.path.exists(MARKER):
        print("REFUSED: lockbox already evaluated once. One-shot rule stands.")
        sys.exit(3)
    print("Fetching quarantined lockbox markets "
          f"[{LOCKBOX_START_TS} .. {NOW_TS}] ...", flush=True)
    n_m, n_c = fetch_lockbox()
    print(f"lockbox: {n_m} markets, {n_c} candles")
    rule = RULES[a.version]()
    trades = generate_trades(rule, mkt_table="lockbox_markets",
                             cnd_table="lockbox_candles")
    s = report(rule["version"] + "-LOCKBOX", trades)
    with open(MARKER, "w") as f:
        f.write(f"used {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} "
                f"for {a.version}: n={s.get('n', 0)} "
                f"exp_c={s.get('expectancy_c', 0):+.2f}\n")
    print(f"\nmarker written to {MARKER} - lockbox is now burned.")
    if s.get("n", 0) == 0 or s.get("expectancy", 0) <= 0:
        print(">>> LOCKBOX KILL: no edge on truly unseen data.")
        sys.exit(2)
    print(">>> LOCKBOX PASS: edge survived unseen data.")


if __name__ == "__main__":
    main()
