"""Vectorized-indicator, bar-loop backtester with walk-forward validation.

No-lookahead guarantee: every strategy's generate() and regime.classify()
centrally shift outputs by one bar, so the signal acted on at bar t uses
data through bar t-1 only. Execution happens at bar t's open.
tests/test_no_lookahead.py proves it by truncation.

Costs modeled per side: FEE_PER_SIDE + SLIPPAGE_PER_SIDE (see config).

Walk-forward: expanding train windows at WALK_FORWARD_SPLITS, each tested
on the next unseen segment. Strategy weights are fit on train only
(weight = max(0, per-strategy per-regime expectancy after fees)).
Kelly sizing stats (win rate, payoff) also come from train only.
All reported metrics are out-of-sample.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from confluence import decide, kelly_risk_fraction
from regime import classify
from risk import RiskManager


def _arrays(df: pd.DataFrame):
    return (
        df["ts"].to_numpy(),
        df["open"].to_numpy(),
        df["high"].to_numpy(),
        df["low"].to_numpy(),
        df["close"].to_numpy(),
    )


def simulate(df: pd.DataFrame, votes: np.ndarray, entries: np.ndarray,
             invalids: np.ndarray, regime_mask: np.ndarray,
             bankroll: float, risk_frac: float,
             pair: str, collect_votes: bool = False) -> pd.DataFrame:
    """Core engine. votes/entries/invalids/regime_mask aligned to df.

    Opens when vote != 0 and regime_mask true. One position per
    (pair, direction) at a time. Exits at stop / 2R take-profit.
    Returns trades DataFrame.
    """
    ts, op, hi, lo, cl = _arrays(df)
    n = len(df)
    risk = RiskManager()
    equity = bankroll
    positions: dict[tuple, dict] = {}
    trades: list[dict] = []
    fee, slip = config.FEE_PER_SIDE, config.SLIPPAGE_PER_SIDE

    for i in range(n):
        day = pd.Timestamp(ts[i], unit="s", tz="UTC").date()
        risk.new_day(day, equity)

        bar = {"open": op[i], "high": hi[i], "low": lo[i], "close": cl[i]}

        # 1) manage open positions (only those opened on earlier bars)
        for key in list(positions.keys()):
            p = positions[key]
            if p["open_bar"] >= i:
                continue
            res = RiskManager.check_exits(p["dir"], p["levels"], bar)
            if res is None:
                continue
            if res == "stop":
                px = p["levels"]["stop"] * (1 - slip * p["dir"])
            else:
                px = p["levels"]["take_profit"] * (1 - slip * p["dir"])
            gross = p["dir"] * p["size"] * (px - p["fill"])
            fees = p["size"] * (p["fill"] * fee + px * fee)
            pnl = gross - fees
            equity += pnl
            risk.register_close(pnl)
            trades.append({
                "pair": pair, "direction": p["dir"],
                "entry_ts": int(p["entry_ts"]), "exit_ts": int(ts[i]),
                "entry_px": p["fill"], "exit_px": px,
                "size": p["size"], "pnl": pnl,
                "exit_reason": res, "equity": equity,
                "strategies": ",".join(p.get("agreeing", [])),
            })
            del positions[key]

        # 2) maybe open
        v = votes[i]
        if v == 0 or not regime_mask[i]:
            continue
        ok, _ = risk.can_open()
        if not ok:
            continue
        key = (pair, int(v))
        if key in positions:
            continue
        entry_ref, inval_ref = entries[i], invalids[i]
        if not (np.isfinite(entry_ref) and np.isfinite(inval_ref)):
            continue
        per_unit = abs(entry_ref - inval_ref)
        if per_unit <= 0:
            continue
        fill = op[i] * (1 + slip * v)
        risk_usd = equity * risk_frac
        size = risk_usd / per_unit
        size = min(size, equity / fill)  # 1x cap, no leverage
        if size * fill < 1.0:
            continue
        levels = RiskManager.make_levels(int(v), fill, inval_ref)
        # stop must be on the correct side of fill, else skip (bad signal)
        if v == 1 and not (levels["stop"] < fill < levels["take_profit"]):
            continue
        if v == -1 and not (levels["take_profit"] < fill < levels["stop"]):
            continue
        positions[key] = {
            "dir": int(v), "size": size, "fill": fill,
            "levels": levels, "open_bar": i, "entry_ts": ts[i],
            "agreeing": [],
        }
        risk.register_open()

    # close leftovers at last close (conservative: exit at close - slip)
    for key, p in positions.items():
        px = cl[-1] * (1 - slip * p["dir"])
        gross = p["dir"] * p["size"] * (px - p["fill"])
        fees = p["size"] * (p["fill"] * fee + px * fee)
        pnl = gross - fees
        equity += pnl
        trades.append({
            "pair": pair, "direction": p["dir"],
            "entry_ts": int(p["entry_ts"]), "exit_ts": int(ts[-1]),
            "entry_px": p["fill"], "exit_px": px,
            "size": p["size"], "pnl": pnl,
            "exit_reason": "eod", "equity": equity,
            "strategies": ",".join(p.get("agreeing", [])),
        })
    return pd.DataFrame(trades)


def single_strategy_stats(df: pd.DataFrame, sig: pd.DataFrame, family: str,
                          regime: pd.Series, bankroll: float) -> dict:
    """Per-strategy, per-regime expectancy on a train window (1% fixed risk)."""
    out = {}
    for r in ("trend", "chop"):
        mask = (regime == r).to_numpy()
        votes = sig["vote"].to_numpy()
        trades = simulate(
            df, votes, sig["entry"].to_numpy(), sig["invalidation"].to_numpy(),
            mask, bankroll, config.RISK_PER_TRADE, pair="train",
        )
        if len(trades) >= 10:
            out[r] = float(trades["pnl"].mean())
        else:
            out[r] = 0.0
    return out


def compute_weights(train_data: dict[str, pd.DataFrame], strategies,
                     bankroll: float) -> dict[str, dict[str, float]]:
    """weights[strategy_name][regime] = max(0, expectancy), normalized.

    Returns also a flat dict for confluence keyed by strategy name with
    per-regime expectancy preserved separately.
    """
    raw: dict[str, dict[str, float]] = {}
    for s in strategies:
        per_regime = {"trend": [], "chop": []}
        for pair, df in train_data.items():
            sig = s.generate(df)
            reg = classify(df)
            stats = single_strategy_stats(df, sig, s.family, reg, bankroll)
            for r in ("trend", "chop"):
                per_regime[r].append(stats[r])
        raw[s.name] = {r: max(0.0, float(np.mean(v))) if v else 0.0
                       for r, v in per_regime.items()}
    # normalize per regime so weights sum to 1 (0 if all zero)
    weights: dict[str, dict[str, float]] = {s.name: {} for s in strategies}
    for r in ("trend", "chop"):
        tot = sum(raw[s.name][r] for s in strategies)
        for s in strategies:
            weights[s.name][r] = (raw[s.name][r] / tot) if tot > 0 else 0.0
    return weights


def ensemble_votes(df: pd.DataFrame, strategies, weights, regime) -> tuple:
    """Build per-bar consensus vote/entry/invalidation series for the engine."""
    sigs = {s.name: s.generate(df) for s in strategies}
    n = len(df)
    votes = np.zeros(n, dtype=int)
    entries = np.full(n, np.nan)
    invalids = np.full(n, np.nan)
    reg = regime.to_numpy()
    names = [s.name for s in strategies]
    fams = {s.name: s.family for s in strategies}
    for i in range(n):
        r = reg[i]
        rows = []
        for sname in names:
            v = int(sigs[sname]["vote"].iloc[i])
            if v == 0:
                continue
            fam = fams[sname]
            mult = config.REGIME_WEIGHT_MULT[r][fam]
            w = weights[sname][r] * mult
            if w <= 0 or mult <= 0:
                continue
            rows.append({
                "name": sname, "family": fam, "vote": v,
                "entry": float(sigs[sname]["entry"].iloc[i]),
                "invalidation": float(sigs[sname]["invalidation"].iloc[i]),
                "conviction": float(sigs[sname]["conviction"].iloc[i]),
                "_w": w,
            })
        longs = [x for x in rows if x["vote"] == 1]
        shorts = [x for x in rows if x["vote"] == -1]
        side, group = None, []
        if len(longs) >= config.MIN_AGREE and len(longs) >= len(shorts):
            side, group = 1, longs
        elif len(shorts) >= config.MIN_AGREE and len(shorts) > len(longs):
            side, group = -1, shorts
        if side is None:
            continue
        maxp = sum(x["_w"] for x in rows)
        sc = sum(x["_w"] * x["conviction"] for x in group)
        if maxp <= 0 or sc < config.SCORE_THRESHOLD * maxp:
            continue
        tw = sum(x["_w"] for x in group)
        votes[i] = side
        entries[i] = sum(x["entry"] * x["_w"] for x in group) / tw
        invalids[i] = sum(x["invalidation"] * x["_w"] for x in group) / tw
    return votes, entries, invalids


def train_ensemble_stats(train_data, strategies, weights, bankroll):
    """Win rate + payoff of the ensemble on train (for Kelly sizing OOS)."""
    all_trades = []
    for pair, df in train_data.items():
        reg = classify(df)
        votes, entries, invalids = ensemble_votes(df, strategies, weights, reg)
        mask = np.ones(len(df), dtype=bool)
        t = simulate(df, votes, entries, invalids, mask, bankroll,
                     config.RISK_PER_TRADE, pair=pair)
        all_trades.append(t)
    trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    if trades.empty or len(trades) < config.MIN_TRADES_FOR_STATS:
        return 0.0, 0.0
    wins = trades[trades["pnl"] > 0]
    wr = len(wins) / len(trades)
    payoff = (wins["pnl"].mean() / (-trades[trades["pnl"] <= 0]["pnl"].mean())
              if (trades["pnl"] <= 0).any() else 0.0)
    return float(wr), float(payoff)


def walk_forward(data: dict[str, pd.DataFrame], strategies,
                 bankroll: float) -> dict:
    """Expanding-train / next-segment-test. Returns OOS trades + diagnostics."""
    # align on shortest pair
    n = min(len(df) for df in data.values())
    data = {p: df.iloc[-n:].reset_index(drop=True) for p, df in data.items()}
    splits = [int(n * f) for f in config.WALK_FORWARD_SPLITS]
    oos_trades: list[pd.DataFrame] = []
    fold_info = []
    for k, s in enumerate(splits):
        train = {p: df.iloc[:s].reset_index(drop=True) for p, df in data.items()}
        e = splits[k + 1] if k + 1 < len(splits) else n
        test = {p: df.iloc[s:e].reset_index(drop=True) for p, df in data.items()}
        weights = compute_weights(train, strategies, bankroll)
        if all(weights[s.name][r] == 0 for s in strategies for r in ("trend", "chop")):
            fold_info.append({"fold": k, "status": "dead-no-positive-expectancy"})
            continue
        wr, payoff = train_ensemble_stats(train, strategies, weights, bankroll)
        from confluence import kelly_risk_fraction
        risk_frac = kelly_risk_fraction(wr, payoff)
        fold_trades = []
        for pair, df in test.items():
            reg = classify(df)
            votes, entries, invalids = ensemble_votes(df, strategies, weights, reg)
            mask = np.ones(len(df), dtype=bool)
            t = simulate(df, votes, entries, invalids, mask, bankroll,
                         risk_frac, pair=pair)
            fold_trades.append(t)
        ft = pd.concat(fold_trades, ignore_index=True) if fold_trades else pd.DataFrame()
        fold_info.append({"fold": k, "status": "ok", "trades": len(ft),
                          "risk_frac": risk_frac, "train_wr": wr})
        oos_trades.append(ft)
    trades = pd.concat(oos_trades, ignore_index=True) if oos_trades else pd.DataFrame()
    return {"trades": trades, "folds": fold_info, "bars": n}


def metrics(trades: pd.DataFrame, bankroll: float) -> dict:
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
    m["profit_factor"] = float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf")
    # daily Sharpe from exit-day P&L
    eq = bankroll + pnl.cumsum()
    t = trades.copy()
    t["day"] = pd.to_datetime(t["exit_ts"], unit="s", utc=True).dt.date
    daily_pnl = t.groupby("day")["pnl"].sum()
    daily_rets = daily_pnl / bankroll
    if len(daily_rets) > 1 and daily_rets.std() > 0:
        m["sharpe_daily"] = float(daily_rets.mean() / daily_rets.std() * (365 ** 0.5))
    else:
        m["sharpe_daily"] = 0.0
    running_max = eq.cummax()
    m["max_drawdown"] = float(((eq - running_max) / running_max).min())
    m["final_equity"] = float(eq.iloc[-1])
    m["return_pct"] = float((eq.iloc[-1] / bankroll - 1) * 100)
    return m
