"""Swing backtest engine: daily-bar event loop, long-only.

Execution convention (no-lookahead): the signal's target decided at the
CLOSE of bar i-1 is implemented at the OPEN of bar i. Trailing stops are
checked intrabar (low[i] <= stop -> filled at stop price), which is the
standard stop-order assumption.

Position sizing: volatility-targeted at entry.
    notional = equity * min(0.5, 0.25 / ann_vol_60d)
Capped at 50% of equity per position; max one position per pair, so max
100% combined. No leverage, ever.

Costs: 50 bps/side fee + 5 bps/side slippage on notional, both sides.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from swing import swing_config as C
from swing.signals import add_indicators, VARIANTS

FEE_RT = C.SWING_FEE_PER_SIDE + C.SWING_SLIPPAGE_PER_SIDE  # per side, on notional


def run_pair(df: pd.DataFrame, variant: str, pair: str,
             bankroll: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run one variant on one pair's daily bars.

    Returns (trades, equity_curve). trades has one row per round trip.
    equity_curve has ts/equity per bar.
    """
    d = add_indicators(df)
    target = VARIANTS[variant](d).to_numpy()
    n = len(d)
    opens = d["open"].to_numpy()
    highs = d["high"].to_numpy()
    lows = d["low"].to_numpy()
    closes = d["close"].to_numpy()
    atrs = d["atr20"].to_numpy()
    ts = d["ts"].to_numpy()

    cash = bankroll
    pos = None  # dict(size_units, entry_px, notional, stop, peak_close, entry_ts)
    halt_until = -1
    day_start_equity = bankroll
    day_pnl = 0.0

    trades = []
    equity_rows = []

    # warmup: no signals before indicators are valid
    start_i = C.WARMUP_DAYS
    for i in range(n):
        # mark-to-market equity at close
        mtm = cash if pos is None else cash + pos["size"] * closes[i]
        equity_rows.append((ts[i], mtm))

        if i < start_i:
            continue

        # --- trailing stop check (intrabar, only when long) ---
        # ORDER MATTERS: check bar i's low against the stop carried from
        # bar i-1 FIRST, then ratchet the stop with bar i's close. Doing it
        # the other way would let the close inform the stop applied to the
        # same bar's low (lookahead).
        if pos is not None:
            if lows[i] <= pos["stop"]:
                exit_px = pos["stop"]
                proceeds = pos["size"] * exit_px
                cost = proceeds * FEE_RT
                cash += proceeds - cost
                pnl = (exit_px - pos["entry_px"]) * pos["size"] \
                    - pos["entry_cost"] - cost
                trades.append(_trade(pair, variant, pos, ts[i], exit_px,
                                     "trail_stop", pnl))
                day_pnl += pnl
                pos = None
            elif not np.isnan(atrs[i]) and closes[i] > pos["peak_close"]:
                pos["peak_close"] = closes[i]
                new_stop = closes[i] - C.ATR_TRAIL_MULT * atrs[i]
                pos["stop"] = max(pos["stop"], new_stop)

        # --- signal execution at OPEN of bar i from target decided at close i-1 ---
        # (i == 0 has no previous close; loop starts at start_i >= 1 anyway)
        # Sizing (turtle): risk RISK_PER_TRADE_FRAC of equity over the
        # initial 3xATR stop distance. notional = equity * 0.01 / stop_frac.
        sig = target[i - 1]
        if pos is None and sig == 1.0 and i > halt_until:
            atr = atrs[i - 1]
            entry_px = opens[i]
            if (not np.isnan(atr) and atr > 0 and entry_px > 0
                    and mtm > 0):
                stop_dist_frac = C.ATR_TRAIL_MULT * atr / entry_px
                frac = min(C.MAX_NOTIONAL_FRAC,
                           C.RISK_PER_TRADE_FRAC / stop_dist_frac)
                notional = mtm * frac
                size = notional / entry_px
                entry_cost = notional * FEE_RT
                cash -= notional + entry_cost
                stop0 = entry_px - C.ATR_TRAIL_MULT * atr
                pos = {"size": size, "entry_px": entry_px,
                       "notional": notional, "entry_cost": entry_cost,
                       "stop": stop0, "peak_close": entry_px,
                       "entry_ts": ts[i], "entry_i": i}
        elif pos is not None and sig == 0.0:
            exit_px = opens[i]
            proceeds = pos["size"] * exit_px
            cost = proceeds * FEE_RT
            cash += proceeds - cost
            pnl = (exit_px - pos["entry_px"]) * pos["size"] \
                - pos["entry_cost"] - cost
            trades.append(_trade(pair, variant, pos, ts[i], exit_px,
                                 "signal", pnl))
            day_pnl += pnl
            pos = None

        # --- daily loss halt: block new entries for 5 bars after a -3% day ---
        # (day pnl measured on closed trades; mark-to-market swings don't halt)
        if day_pnl < -C.SWING_MAX_DAILY_LOSS_FRAC * day_start_equity:
            halt_until = i + 5
            day_pnl = 0.0
            day_start_equity = mtm
        # reset day pnl tracking at each bar (daily bars => each bar is a day)
        if i > start_i:
            day_pnl = 0.0
            day_start_equity = mtm

    # close any open position at the last close (for clean accounting)
    if pos is not None:
        exit_px = closes[-1]
        proceeds = pos["size"] * exit_px
        cost = proceeds * FEE_RT
        pnl = (exit_px - pos["entry_px"]) * pos["size"] - pos["entry_cost"] - cost
        trades.append(_trade(pair, variant, pos, ts[-1], exit_px,
                             "final_close", pnl))
        cash += proceeds - cost

    trades_df = pd.DataFrame(trades)
    eq_df = pd.DataFrame(equity_rows, columns=["ts", "equity"])
    return trades_df, eq_df


def _trade(pair, variant, pos, exit_ts, exit_px, reason, pnl):
    return {
        "pair": pair,
        "variant": variant,
        "entry_ts": pos["entry_ts"],
        "entry_px": pos["entry_px"],
        "exit_ts": int(exit_ts),
        "exit_px": float(exit_px),
        "size": pos["size"],
        "notional": pos["notional"],
        "exit_reason": reason,
        "pnl": float(pnl),
    }


def metrics(trades: pd.DataFrame, bankroll: float,
            eq: pd.DataFrame | None = None) -> dict:
    """Same table shape as the intraday metrics(). Sharpe ann. x sqrt(365)."""
    m: dict = {"n_trades": len(trades)}
    if trades.empty:
        return m
    pnl = trades["pnl"]
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    m["total_pnl"] = float(pnl.sum())
    m["expectancy"] = float(pnl.mean())
    m["win_rate"] = float(len(wins) / len(pnl))
    m["avg_win"] = float(wins.mean()) if len(wins) else 0.0
    m["avg_loss"] = float(losses.mean()) if len(losses) else 0.0
    m["profit_factor"] = float(wins.sum() / -losses.sum()) \
        if losses.sum() < 0 else float("inf")
    if eq is not None and len(eq) > 1:
        rets = eq["equity"].pct_change().dropna()
        if rets.std() > 0:
            m["sharpe_daily"] = float(rets.mean() / rets.std() * np.sqrt(365))
        else:
            m["sharpe_daily"] = 0.0
        running_max = eq["equity"].cummax()
        m["max_drawdown"] = float(((eq["equity"] - running_max)
                                  / running_max).min())
        m["final_equity"] = float(eq["equity"].iloc[-1])
        m["return_pct"] = float((eq["equity"].iloc[-1] / bankroll - 1) * 100)
    else:
        eq2 = bankroll + pnl.cumsum()
        running_max = eq2.cummax()
        m["max_drawdown"] = float(((eq2 - running_max) / running_max).min())
        m["final_equity"] = float(eq2.iloc[-1])
        m["return_pct"] = float((eq2.iloc[-1] / bankroll - 1) * 100)
        m["sharpe_daily"] = 0.0
    return m
