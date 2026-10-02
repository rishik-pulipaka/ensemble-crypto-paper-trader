"""Paper trading engine. PAPER ONLY.

This module NEVER places real orders. There is no exchange-auth code, no
API-key handling, no order-placement function anywhere in this project.
Fills are simulated against real market data (bid/ask approximated from
the bar + spread/slippage model in config).

State persisted to SQLite (PAPER_DB_PATH):
    paper_state(key TEXT PRIMARY KEY, value TEXT)   -- equity, bankroll, etc.
    paper_positions(...)  -- open simulated positions
    paper_trades(...)     -- closed simulated trades
    paper_votes(...)      -- latest per-strategy votes for the dashboard

Run:  python3 paper.py [--once] [--poll 60]
  --once  run a single cycle and exit (for cron/scheduler use)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from backtest import compute_weights, ensemble_votes
from confluence import kelly_risk_fraction
from data.fetcher import latest_bars
from data.store import CandleStore
from regime import classify
from risk import RiskManager
from strategies.library import ALL_STRATEGIES

ROOT = Path(__file__).resolve().parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_state(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS paper_positions(
    id INTEGER PRIMARY KEY AUTOINCREMENT, pair TEXT, direction INTEGER,
    size REAL, entry_px REAL, stop_px REAL, tp_px REAL,
    entry_ts INTEGER, strategies TEXT, risk_usd REAL);
CREATE TABLE IF NOT EXISTS paper_trades(
    id INTEGER PRIMARY KEY AUTOINCREMENT, pair TEXT, direction INTEGER,
    size REAL, entry_px REAL, exit_px REAL, entry_ts INTEGER, exit_ts INTEGER,
    pnl REAL, exit_reason TEXT, strategies TEXT, equity REAL);
CREATE TABLE IF NOT EXISTS paper_votes(
    pair TEXT, strategy TEXT, vote INTEGER, conviction REAL,
    regime TEXT, ts INTEGER, PRIMARY KEY (pair, strategy));
CREATE TABLE IF NOT EXISTS paper_equity(ts INTEGER PRIMARY KEY, equity REAL);
"""


class PaperEngine:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or ROOT / config.PAPER_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.executescript(SCHEMA)
        self.risk = RiskManager()
        if self._get("bankroll") is None:
            self._set("bankroll", config.STARTING_BANKROLL)
            self._set("weights", json.dumps({}))
            self._set("kelly", json.dumps({"win_rate": 0.0, "payoff": 0.0}))

    # -- state helpers ---------------------------------------------------
    def _get(self, key: str):
        r = self.conn.execute(
            "SELECT value FROM paper_state WHERE key=?", (key,)).fetchone()
        return r[0] if r else None

    def _set(self, key: str, value):
        self.conn.execute(
            "INSERT OR REPLACE INTO paper_state(key,value) VALUES(?,?)",
            (key, str(value)))
        self.conn.commit()

    @property
    def bankroll(self) -> float:
        return float(self._get("bankroll"))

    def set_weights(self, weights: dict, win_rate: float, payoff: float):
        self._set("weights", json.dumps(weights))
        self._set("kelly", json.dumps({"win_rate": win_rate, "payoff": payoff}))

    # -- one cycle --------------------------------------------------------
    def cycle(self, store: CandleStore) -> dict:
        """Poll latest bars, run the full stack, manage simulated fills."""
        now = datetime.now(timezone.utc)
        weights = json.loads(self._get("weights") or "{}")
        kelly = json.loads(self._get("kelly") or "{}")
        summary = {"ts": now.isoformat(), "pairs": {}}

        # sync risk manager with persisted state (survives restarts)
        self.risk.new_day(now.date(), self.bankroll)
        db_open = self.conn.execute(
            "SELECT COUNT(*) FROM paper_positions").fetchone()[0]
        self.risk.open_count = db_open

        for pair in config.PAIRS:
            df = latest_bars(pair, n=600, granularity=config.GRANULARITY_SECONDS)
            if df.empty:
                continue
            store.upsert(pair, df)
            full = store.load(pair)
            if len(full) < 700:
                continue
            window = full.iloc[-700:].reset_index(drop=True)

            reg = classify(window)
            regime_now = str(reg.iloc[-1])
            sigs = {s.name: s.generate(window) for s in ALL_STRATEGIES}

            # dashboard votes (latest bar)
            ts_now = int(window["ts"].iloc[-1])
            for s in ALL_STRATEGIES:
                row = sigs[s.name].iloc[-1]
                self.conn.execute(
                    "INSERT OR REPLACE INTO paper_votes(pair,strategy,vote,"
                    "conviction,regime,ts) VALUES(?,?,?,?,?,?)",
                    (pair, s.name, int(row["vote"]), float(row["conviction"] or 0),
                     regime_now, ts_now))

            # manage open simulated positions against the newest bar
            bar = {"open": float(window["open"].iloc[-1]),
                   "high": float(window["high"].iloc[-1]),
                   "low": float(window["low"].iloc[-1]),
                   "close": float(window["close"].iloc[-1])}
            self._manage_positions(pair, bar, now)

            # maybe open: build the consensus for the latest bar only.
            # Uncalibrated (no weights) => stay flat. Never trade on defaults.
            if weights:
                votes, entries, invalids = ensemble_votes(
                    window, ALL_STRATEGIES, weights, reg)
            else:
                n = len(window)
                votes = np.zeros(n, dtype=int)
                entries = np.full(n, np.nan)
                invalids = np.full(n, np.nan)
            v, e, iv = votes[-1], entries[-1], invalids[-1]
            action = None
            if v != 0 and np.isfinite(e) and np.isfinite(iv):
                rows = []
                for s in ALL_STRATEGIES:
                    r0 = sigs[s.name].iloc[-1]
                    if int(r0["vote"]) != int(v):
                        continue
                    rows.append({"name": s.name, "family": s.family,
                                 "vote": int(v), "entry": float(r0["entry"]),
                                 "invalidation": float(r0["invalidation"]),
                                 "conviction": float(r0["conviction"] or 0)})
                from confluence import decide as _decide
                wflat = {s.name: (weights.get(s.name, {}) or {}).get(regime_now, 0.0)
                         for s in ALL_STRATEGIES}
                action = _decide(rows, regime_now, wflat, self.bankroll,
                                 kelly.get("win_rate", 0.0), kelly.get("payoff", 0.0))
            opened = False
            if action:
                ok, _ = self.risk.can_open()
                # one position per (pair, direction)
                exists = self.conn.execute(
                    "SELECT 1 FROM paper_positions WHERE pair=? AND direction=?",
                    (pair, action["direction"])).fetchone()
                if ok and not exists:
                    self._open_position(pair, action, bar, now)
                    opened = True
            summary["pairs"][pair] = {"regime": regime_now, "vote": int(v),
                                      "opened": opened,
                                      "price": bar["close"]}
            self.conn.commit()

        # equity snapshot
        eq = self._equity_mark_to_market()
        self.conn.execute("INSERT OR REPLACE INTO paper_equity(ts,equity) VALUES(?,?)",
                          (int(now.timestamp()), eq))
        self.conn.commit()
        summary["equity"] = eq
        return summary

    # -- position management ------------------------------------------------
    def _manage_positions(self, pair: str, bar: dict, now: datetime):
        rows = self.conn.execute(
            "SELECT id,direction,size,entry_px,stop_px,tp_px,entry_ts "
            "FROM paper_positions WHERE pair=?", (pair,)).fetchall()
        for pid, direction, size, entry_px, stop_px, tp_px, entry_ts in rows:
            levels = {"stop": stop_px, "take_profit": tp_px}
            res = RiskManager.check_exits(direction, levels, bar)
            if res is None:
                continue
            slip = config.SLIPPAGE_PER_SIDE
            px = (stop_px if res == "stop" else tp_px) * (1 - slip * direction)
            fee = config.FEE_PER_SIDE
            gross = direction * size * (px - entry_px)
            fees = size * (entry_px * fee + px * fee)
            pnl = gross - fees
            new_eq = self.bankroll + pnl
            self._set("bankroll", new_eq)
            self.risk.register_close(pnl)
            self.conn.execute(
                "INSERT INTO paper_trades(pair,direction,size,entry_px,exit_px,"
                "entry_ts,exit_ts,pnl,exit_reason,strategies,equity)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (pair, direction, size, entry_px, px, entry_ts,
                 int(now.timestamp()), pnl, res, "", new_eq))
            self.conn.execute("DELETE FROM paper_positions WHERE id=?", (pid,))
        self.conn.commit()

    def _open_position(self, pair: str, action: dict, bar: dict, now: datetime):
        slip = config.SLIPPAGE_PER_SIDE
        d = action["direction"]
        fill = bar["open"] * (1 + slip * d)
        levels = RiskManager.make_levels(d, fill, action["invalidation"])
        self.conn.execute(
            "INSERT INTO paper_positions(pair,direction,size,entry_px,stop_px,"
            "tp_px,entry_ts,strategies,risk_usd) VALUES(?,?,?,?,?,?,?,?,?)",
            (pair, d, action["size_units"], fill, levels["stop"],
             levels["take_profit"], int(now.timestamp()),
             ",".join(action["agreeing"]), action["risk_usd"]))
        self.risk.register_open()
        self.conn.commit()

    def _equity_mark_to_market(self) -> float:
        eq = self.bankroll
        for (pair, direction, size, entry_px) in self.conn.execute(
                "SELECT pair,direction,size,entry_px FROM paper_positions"):
            try:
                from data.fetcher import latest_price
                px = latest_price(pair)
                eq += direction * size * (px - entry_px)
            except Exception:
                pass
        return eq

    def close(self):
        self.conn.close()


def calibrate_from_backtest():
    """Fit weights + Kelly stats on cached history, store into paper DB.

    Run once before starting the paper loop (and re-run weekly).
    Refuses to write tradable weights if walk-forward expectancy <= 0.
    """
    from backtest import train_ensemble_stats, walk_forward
    engine = PaperEngine()
    store = CandleStore(ROOT / config.DB_PATH)
    data = {}
    for p in config.PAIRS:
        df = store.load(p)
        if len(df) < 50000:
            print(f"calibrate: skipping {p} (only {len(df)} bars, need 50000+)")
            continue
        data[p] = df
    store.close()
    if not data:
        print("CALIBRATION REFUSED: no pair has enough history.")
        return False
    result = walk_forward(data, ALL_STRATEGIES, config.STARTING_BANKROLL)
    from backtest import metrics as _metrics
    m = _metrics(result["trades"], config.STARTING_BANKROLL)
    if m.get("expectancy", 0) <= 0 or m.get("n_trades", 0) < config.MIN_TRADES_FOR_STATS:
        print("CALIBRATION REFUSED: walk-forward expectancy <= 0. "
              "No weights written; paper engine stays flat.")
        return False
    # refit weights on ALL history for live use
    n = min(len(df) for df in data.values())
    full = {p: df.iloc[-n:].reset_index(drop=True) for p, df in data.items()}
    weights = compute_weights(full, ALL_STRATEGIES, config.STARTING_BANKROLL)
    wr, payoff = train_ensemble_stats(full, ALL_STRATEGIES, weights,
                                     config.STARTING_BANKROLL)
    engine.set_weights(weights, wr, payoff)
    print(f"calibrated: weights written, train wr={wr:.2f} payoff={payoff:.2f}")
    engine.close()
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--poll", type=int, default=config.PAPER_POLL_SECONDS)
    ap.add_argument("--calibrate", action="store_true",
                    help="fit weights from history, then exit")
    args = ap.parse_args()
    if args.calibrate:
        sys.exit(0 if calibrate_from_backtest() else 2)
    engine = PaperEngine()
    store = CandleStore(ROOT / config.DB_PATH)
    try:
        while True:
            try:
                s = engine.cycle(store)
                print(f"[{s['ts']}] equity=${s['equity']:,.2f} " +
                      " ".join(f"{p}:{v['regime']}/{v['vote']}"
                              for p, v in s["pairs"].items()), flush=True)
            except Exception as e:  # noqa: BLE001 - loop must survive
                print(f"[error] {e}", flush=True)
            if args.once:
                break
            time.sleep(args.poll)
    finally:
        engine.close()
        store.close()


if __name__ == "__main__":
    main()
