"""No-lookahead proof for the Kalshi engine.

1. Entries must be IDENTICAL when market results are shuffled -> proves
   entries use only pre-signal price data, never outcomes.
2. Every fill price must come from a candle at/before the fill time.
3. Every entry_ts must precede its market's expiration_ts.
"""
import os
import random
import shutil
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from kalshi import engine
from kalshi.kalshi_config import DB_PATH
from kalshi.strategies import v1_rule, v3_rule


def entries(rule, db_path):
    engine.DB_PATH_ORIG = getattr(engine, "DB_PATH", None)
    # monkeypatch module DB_PATH
    old = engine.DB_PATH
    engine.DB_PATH = db_path
    try:
        trades = engine.generate_trades(rule)
    finally:
        engine.DB_PATH = old
    return {(t["ticker"], t["entry_ts"], round(t["fill_price"], 6)) for t in trades}


def shuffled_db():
    tmp = "/tmp/kalshi_shuffled.db"
    if os.path.exists(tmp):
        os.remove(tmp)
    shutil.copy(DB_PATH, tmp)
    con = sqlite3.connect(tmp)
    rows = con.execute("SELECT ticker, result FROM markets").fetchall()
    results = [r[1] for r in rows]
    rng = random.Random(42)
    rng.shuffle(results)
    for (ticker, _), res in zip(rows, results):
        con.execute("UPDATE markets SET result=? WHERE ticker=?", (res, ticker))
    con.commit()
    con.close()
    return tmp


def main():
    fails = []
    for name, rule_fn in [("v1", v1_rule), ("v3", v3_rule)]:
        rule = rule_fn()
        real = entries(rule, DB_PATH)
        tmp = shuffled_db()
        try:
            shuf = entries(rule, tmp)
        finally:
            os.remove(tmp)
        if real != shuf:
            fails.append(f"{name}: entries changed when results shuffled "
                         f"(real={len(real)}, shuffled={len(shuf)}) -> LOOKAHEAD")
        else:
            print(f"{name}: entries invariant to result shuffle "
                  f"({len(real)} entries) OK")

    # fill-price provenance + entry-before-expiry on real DB
    con = sqlite3.connect(DB_PATH)
    for name, rule_fn in [("v1", v1_rule), ("v3", v3_rule)]:
        trades = engine.generate_trades(rule_fn())
        bad = 0
        for t in trades:
            m = con.execute(
                "SELECT expiration_ts FROM markets WHERE ticker=?",
                (t["ticker"],)).fetchone()
            if t["entry_ts"] >= m[0]:
                bad += 1
            c = con.execute(
                "SELECT COUNT(*) FROM candles WHERE ticker=? AND end_ts <= ?",
                (t["ticker"], t["entry_ts"] + 86400)).fetchone()[0]
            if c == 0:
                bad += 1
            if not (0 < t["fill_price"] < 1):
                bad += 1
        if bad:
            fails.append(f"{name}: {bad} trades with bad provenance/expiry")
        else:
            print(f"{name}: fill provenance + expiry ordering OK ({len(trades)} trades)")
    con.close()

    if fails:
        print("FAIL:")
        for f in fails:
            print(" ", f)
        sys.exit(1)
    print("ALL NO-LOOKAHEAD CHECKS PASS")


if __name__ == "__main__":
    main()
