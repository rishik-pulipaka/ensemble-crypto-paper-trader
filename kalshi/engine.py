"""Binary-market event-study backtest engine.

For each settled market: scan daily candles in time order, apply an entry
rule that uses ONLY candles ending at/before the signal time (no lookahead),
fill at the next candle's open (or the signal candle's close if none),
hold to settlement, apply the exact Kalshi taker fee.

A trade is a dict:
    ticker, series, entry_ts, fill_price, fee, pnl, result, side
pnl is per single contract, in dollars. Buy-yes: pnl = settle - fill - fee.
Sell-yes (short): pnl = fill - fee - settle. settle = 1.0 if result=='yes'.
"""
import sqlite3

from .kalshi_config import DB_PATH, MAX_TTE_DAYS, taker_fee


def load_market(ticker, mkt_table="markets", cnd_table="candles"):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    m = con.execute(f"SELECT * FROM {mkt_table} WHERE ticker=?", (ticker,)).fetchone()
    candles = con.execute(
        f"SELECT * FROM {cnd_table} WHERE ticker=? ORDER BY end_ts", (ticker,)).fetchall()
    con.close()
    return m, [dict(c) for c in candles]


def all_dev_tickers(series=None, mkt_table="markets"):
    con = sqlite3.connect(DB_PATH)
    q = f"SELECT ticker, series, expiration_ts FROM {mkt_table}"
    if series:
        q += f" WHERE series IN ({','.join('?' * len(series))})"
        rows = con.execute(q, series).fetchall()
    else:
        rows = con.execute(q).fetchall()
    con.close()
    return rows


def generate_trades(rule, mkt_table="markets", cnd_table="candles"):
    """rule: dict with side ('buy_yes'|'sell_yes'), entry_price_threshold,
    entry_price_field ('yes_ask'|'yes_bid'), optional filters:
      max_tte_days, min_entry_volume, exclude_series (set), only_series (set),
      fit_before_ts (only markets expiring before this; for walk-forward),
      eval_after_ts (only markets expiring at/after this).
    mkt_table/cnd_table let the lockbox evaluator run against quarantine
    tables without touching dev data.
    Returns list of trade dicts. Deterministic, no randomness."""
    side = rule["side"]
    thr = rule["entry_price_threshold"]
    field = rule["entry_price_field"]  # 'yes_ask' or 'yes_bid'
    o_col, c_col = ("ask_o", "ask_c") if field == "yes_ask" else ("bid_o", "bid_c")
    max_tte = rule.get("max_tte_days", MAX_TTE_DAYS)
    min_vol = rule.get("min_entry_volume", 0)
    min_mkt_vol = rule.get("min_market_volume", 0)
    excl = rule.get("exclude_series", set())
    only = rule.get("only_series", None)
    fit_before = rule.get("fit_before_ts")
    eval_after = rule.get("eval_after_ts")

    trades = []
    for ticker, series, exp_ts in all_dev_tickers(mkt_table=mkt_table):
        if series in excl:
            continue
        if only is not None and series not in only:
            continue
        if fit_before is not None and exp_ts >= fit_before:
            continue
        if eval_after is not None and exp_ts < eval_after:
            continue
        m, candles = load_market(ticker, mkt_table, cnd_table)
        if not candles:
            continue
        if min_mkt_vol and (m["volume"] or 0) < min_mkt_vol:
            continue
        open_ts = m["open_ts"]
        # scan for the FIRST qualifying signal candle
        sig_idx = None
        for i, c in enumerate(candles):
            end_ts = c["end_ts"]
            if open_ts and end_ts < open_ts:
                continue
            tte_days = (exp_ts - end_ts) / 86400.0
            if tte_days > max_tte or tte_days < 0:
                continue
            px = c[c_col]
            if px is None:
                continue
            if min_vol and (c["volume"] or 0) < min_vol:
                continue
            hit = px >= thr if side == "buy_yes" else px <= thr
            if hit:
                sig_idx = i
                break
        if sig_idx is None:
            continue
        # fill at next candle's open; fallback to signal candle's close
        nxt = candles[sig_idx + 1] if sig_idx + 1 < len(candles) else None
        if nxt is not None and nxt[o_col] is not None:
            fill = nxt[o_col]
            fill_ts = nxt["end_ts"] - 86400  # approx open time of next day
        else:
            fill = candles[sig_idx][c_col]
            fill_ts = candles[sig_idx]["end_ts"]
        if fill is None or fill <= 0 or fill >= 1:
            continue
        fee = taker_fee(fill)
        settle = 1.0 if m["result"] == "yes" else 0.0
        if side == "buy_yes":
            pnl = settle - fill - fee
        else:
            pnl = fill - fee - settle
        trades.append({
            "ticker": ticker, "series": series,
            "entry_ts": fill_ts, "fill_price": fill, "fee": fee,
            "pnl": pnl, "result": m["result"], "side": side,
            "expiration_ts": exp_ts,
        })
    trades.sort(key=lambda t: t["entry_ts"])
    return trades


def summarize(trades):
    """Aggregate stats. Returns dict; empty dict if no trades."""
    n = len(trades)
    if n == 0:
        return {"n": 0}
    import math
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    mean = sum(pnls) / n
    var = sum((p - mean) ** 2 for p in pnls) / n
    std = math.sqrt(var)
    # sequential equity for max drawdown (1 contract per trade)
    eq, peak, dd = 0.0, 0.0, 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    fees = sum(t["fee"] for t in trades)
    gross = sum(pnls) + fees
    return {
        "n": n,
        "expectancy": mean,                       # $/contract
        "expectancy_c": mean * 100,               # cents/contract
        "win_rate": len(wins) / n,
        "avg_win": sum(wins) / len(wins) if wins else 0,
        "avg_loss": sum(losses) / len(losses) if losses else 0,
        "profit_factor": (sum(wins) / -sum(losses)) if losses and sum(losses) else float("inf"),
        "sharpe_per_trade": (mean / std) if std else 0,
        "total_pnl": sum(pnls),
        "total_fees": fees,
        "gross_pnl": gross,
        "max_drawdown": dd,
        "fee_share_of_gross": (fees / gross) if gross > 0 else None,
    }
