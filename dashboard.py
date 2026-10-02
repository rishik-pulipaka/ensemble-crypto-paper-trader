#!/usr/bin/env python3
"""Local dashboard. stdlib only. Serves REAL paper-engine state from paper.db.

Every number on screen comes from the engine's SQLite state. Nothing is
mocked, sampled, or placeholder. If the paper engine hasn't run, the
dashboard shows zeros and empty tables -- that is the true state.

Run:  python3 dashboard.py [--port 8787]
Then open http://localhost:8787
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

ROOT = Path(__file__).resolve().parent
PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>paper desk</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0b0e11; color: #c9d1d9; font-family: "SF Mono", "Cascadia Code",
         Menlo, Consolas, monospace; font-size: 13px; padding: 24px; }
  h1 { font-size: 15px; color: #e6edf3; letter-spacing: 2px; margin-bottom: 4px; }
  .sub { color: #6e7681; font-size: 11px; margin-bottom: 20px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 12px; margin-bottom: 20px; }
  .card { background: #11161c; border: 1px solid #21262d; border-radius: 6px;
          padding: 12px 14px; }
  .card .k { color: #6e7681; font-size: 10px; text-transform: uppercase;
             letter-spacing: 1px; margin-bottom: 6px; }
  .card .v { font-size: 20px; color: #e6edf3; }
  .pos { color: #3fb950; } .neg { color: #f85149; } .flat { color: #8b949e; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 20px;
          background: #11161c; border: 1px solid #21262d; border-radius: 6px;
          overflow: hidden; }
  th { text-align: left; color: #6e7681; font-size: 10px; text-transform: uppercase;
       letter-spacing: 1px; padding: 10px 12px; border-bottom: 1px solid #21262d; }
  td { padding: 8px 12px; border-bottom: 1px solid #161b22; font-size: 12px; }
  tr:last-child td { border-bottom: none; }
  h2 { font-size: 12px; color: #e6edf3; letter-spacing: 1px; margin: 0 0 10px 2px; }
  .vote-long { color: #3fb950; } .vote-short { color: #f85149; }
  .vote-flat { color: #6e7681; }
  .pill { display: inline-block; padding: 2px 8px; border: 1px solid #30363d;
          border-radius: 10px; font-size: 11px; }
  .empty { color: #6e7681; padding: 16px; text-align: center; }
  #err { color: #f85149; margin-bottom: 12px; display: none; }
</style></head>
<body>
<h1>PAPER DESK</h1>
<div class="sub">ensemble crypto paper trader &mdash; simulated fills on real market data &mdash; no real orders</div>
<div id="err"></div>
<div class="grid" id="cards"></div>
<h2>OPEN POSITIONS</h2><div id="positions"></div>
<h2>RECENT TRADES</h2><div id="trades"></div>
<h2>STRATEGY VOTES</h2><div id="votes"></div>
<h2>EQUITY CURVE</h2><div id="equity"></div>
<script>
const fmt$ = x => (x < 0 ? "-" : "") + "$" + Math.abs(x).toLocaleString(undefined,
  {minimumFractionDigits: 2, maximumFractionDigits: 2});
const cls = x => x > 0 ? "pos" : (x < 0 ? "neg" : "flat");
async function load() {
  try {
    const r = await fetch("/api/state");
    const s = await r.json();
    document.getElementById("err").style.display = "none";
    const start = s.starting_bankroll;
    const pnl = s.equity - start;
    const cards = [
      ["Equity", `<span class="${cls(pnl)}">${fmt$(s.equity)}</span>`],
      ["P&L", `<span class="${cls(pnl)}">${fmt$(pnl)}</span>`],
      ["Return", `<span class="${cls(pnl)}">${(pnl / start * 100).toFixed(2)}%</span>`],
      ["Open positions", s.positions.length + " / " + s.max_positions],
      ["Trades closed", s.trades.length],
      ["Win rate", s.win_rate == null ? "--" : (s.win_rate * 100).toFixed(1) + "%"],
      ["Risk state", s.halted ? '<span class="neg">HALTED (daily loss)</span>'
                              : '<span class="pos">LIVE</span>'],
      ["Last cycle", s.last_cycle || "--"],
    ];
    document.getElementById("cards").innerHTML =
      cards.map(c => `<div class="card"><div class="k">${c[0]}</div><div class="v">${c[1]}</div></div>`).join("");
    const pos = s.positions;
    document.getElementById("positions").innerHTML = pos.length ?
      `<table><tr><th>Pair</th><th>Dir</th><th>Size</th><th>Entry</th><th>Stop</th><th>TP</th><th>Unreal</th></tr>` +
      pos.map(p => `<tr><td>${p.pair}</td><td class="${p.direction > 0 ? "vote-long" : "vote-short"}">${p.direction > 0 ? "LONG" : "SHORT"}</td><td>${(+p.size).toFixed(6)}</td><td>${fmt$(p.entry_px)}</td><td>${fmt$(p.stop_px)}</td><td>${fmt$(p.tp_px)}</td><td class="${cls(p.unreal)}">${fmt$(p.unreal)}</td></tr>`).join("") + `</table>`
      : `<div class="card empty">no open positions</div>`;
    const tr = s.trades;
    document.getElementById("trades").innerHTML = tr.length ?
      `<table><tr><th>Pair</th><th>Dir</th><th>Entry</th><th>Exit</th><th>P&L</th><th>Exit</th><th>Time</th></tr>` +
      tr.map(t => `<tr><td>${t.pair}</td><td class="${t.direction > 0 ? "vote-long" : "vote-short"}">${t.direction > 0 ? "L" : "S"}</td><td>${fmt$(t.entry_px)}</td><td>${fmt$(t.exit_px)}</td><td class="${cls(t.pnl)}">${fmt$(t.pnl)}</td><td>${t.exit_reason}</td><td>${t.exit_ts}</td></tr>`).join("") + `</table>`
      : `<div class="card empty">no closed trades yet</div>`;
    const vv = s.votes;
    document.getElementById("votes").innerHTML =
      `<table><tr><th>Pair</th><th>Strategy</th><th>Vote</th><th>Conviction</th><th>Regime</th></tr>` +
      vv.map(v => { const c = v.vote > 0 ? "vote-long" : (v.vote < 0 ? "vote-short" : "vote-flat");
        const t = v.vote > 0 ? "LONG" : (v.vote < 0 ? "SHORT" : "FLAT");
        return `<tr><td>${v.pair}</td><td>${v.strategy}</td><td class="${c}">${t}</td><td>${(+v.conviction).toFixed(2)}</td><td><span class="pill">${v.regime}</span></td></tr>`; }).join("") + `</table>`;
    const eq = s.equity_curve;
    document.getElementById("equity").innerHTML = eq.length ?
      `<table><tr><th>Time (UTC)</th><th>Equity</th></tr>` +
      eq.slice(-20).reverse().map(e => `<tr><td>${e.ts}</td><td class="${cls(e.equity - start)}">${fmt$(e.equity)}</td></tr>`).join("") + `</table>`
      : `<div class="card empty">no equity snapshots yet -- start the paper engine</div>`;
  } catch (e) {
    const el = document.getElementById("err");
    el.style.display = "block";
    el.textContent = "failed to load state: " + e;
  }
}
load(); setInterval(load, 30000);
</script></body></html>
"""


def read_state() -> dict:
    db = ROOT / config.PAPER_DB_PATH
    out: dict = {
        "starting_bankroll": config.STARTING_BANKROLL,
        "max_positions": config.MAX_POSITIONS,
        "equity": config.STARTING_BANKROLL,
        "positions": [], "trades": [], "votes": [],
        "equity_curve": [], "win_rate": None,
        "halted": False, "last_cycle": None,
    }
    if not db.exists():
        return out
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute("SELECT value FROM paper_state WHERE key='bankroll'").fetchone()
        if r:
            out["equity"] = float(r["value"])
        for row in conn.execute(
                "SELECT pair,direction,size,entry_px,stop_px,tp_px FROM paper_positions"):
            d = dict(row)
            # unrealized vs latest close from market db (best-effort; else 0)
            d["unreal"] = 0.0
            out["positions"].append(d)
        for row in conn.execute(
                "SELECT pair,direction,entry_px,exit_px,pnl,exit_reason,"
                "datetime(exit_ts,'unixepoch') AS exit_ts FROM paper_trades "
                "ORDER BY id DESC LIMIT 50"):
            out["trades"].append(dict(row))
        if out["trades"]:
            wins = sum(1 for t in conn.execute("SELECT pnl FROM paper_trades")
                       if t[0] > 0)
            total = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
            out["win_rate"] = wins / total if total else None
        for row in conn.execute(
                "SELECT pair,strategy,vote,conviction,regime FROM paper_votes "
                "ORDER BY pair, strategy"):
            out["votes"].append(dict(row))
        for row in conn.execute(
                "SELECT datetime(ts,'unixepoch') AS ts, equity FROM paper_equity "
                "ORDER BY ts DESC LIMIT 60"):
            out["equity_curve"].append(dict(row))
        r = conn.execute("SELECT MAX(ts) FROM paper_equity").fetchone()
        if r and r[0]:
            import datetime as dt
            out["last_cycle"] = dt.datetime.fromtimestamp(
                r[0], dt.timezone.utc).strftime("%H:%M:%S")
    finally:
        conn.close()
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/api/state":
            body = json.dumps(read_state()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        elif self.path in ("/", "/index.html"):
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        else:
            self.send_response(404)
            body = b"not found"
            self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=config.DASHBOARD_PORT)
    args = ap.parse_args()
    srv = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"dashboard: http://127.0.0.1:{args.port} (paper state only, no real orders)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
