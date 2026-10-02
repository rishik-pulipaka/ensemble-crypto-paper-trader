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


def simulate_maker(df: pd.DataFrame, sig: pd.DataFrame, regime_mask: np.ndarray,
                   bankroll: float, risk_frac: float, pair: str) -> pd.DataFrame:
    """Maker-entry backtest. Limit orders fill ONLY on price touch.

    Signal at bar t (vote/entry/invalidation, already one-bar shifted by
    generate(), so it uses data through t-1):
    - long: resting limit BUY at entry*(1-MAKER_OFFSET), valid MAKER_MAX_WAIT_BARS
    - short: resting limit SELL at entry*(1+MAKER_OFFSET)
    Fill when the bar's range touches the limit; fill price = limit (zero
    slippage — we get our price or nothing). Entry fee = MAKER_FEE_PER_SIDE.
    Exits: take-profit as a resting maker limit at the 2R target
    (MAKER_FEE_PER_SIDE); stop as an urgent taker exit at the invalidation
    level (MAKER_STOP_FEE_PER_SIDE + slippage). If stop and TP are both
    touched in one bar, the stop is assumed (conservative).
    Unfilled orders expire after MAKER_MAX_WAIT_BARS with no cost.
    Adverse selection is captured honestly: a buy limit fills precisely when
    price has dropped to our level.
    """
    ts, op, hi, lo, cl = _arrays(df)
    n = len(df)
    risk = RiskManager()
    equity = bankroll
    positions: dict[tuple, dict] = {}
    pending: dict[tuple, dict] = {}
    trades: list[dict] = []
    mfee = config.MAKER_FEE_PER_SIDE
    sfee = config.MAKER_STOP_FEE_PER_SIDE
    slip = config.SLIPPAGE_PER_SIDE
    offset = config.MAKER_OFFSET
    max_wait = config.MAKER_MAX_WAIT_BARS
    votes = sig["vote"].to_numpy()
    entries = sig["entry"].to_numpy()
    invalids = sig["invalidation"].to_numpy()

    for i in range(n):
        day = pd.Timestamp(ts[i], unit="s", tz="UTC").date()
        risk.new_day(day, equity)
        o, h, l, c = op[i], hi[i], lo[i], cl[i]

        # 1) manage open positions (stop checked before TP: conservative)
        for key in list(positions.keys()):
            p = positions[key]
            d = p["dir"]
            stopped = (d == 1 and l <= p["stop"]) or (d == -1 and h >= p["stop"])
            tp_hit = (d == 1 and h >= p["tp"]) or (d == -1 and l <= p["tp"])
            if not stopped and not tp_hit:
                continue
            if stopped:
                px = p["stop"] * (1 - slip * d)
                fee_rate = sfee
                reason = "stop"
            else:
                px = p["tp"]  # maker limit fill at our price
                fee_rate = mfee
                reason = "take_profit"
            gross = d * p["size"] * (px - p["fill"])
            fees = p["size"] * (p["fill"] * mfee + px * fee_rate)
            pnl = gross - fees
            equity += pnl
            risk.register_close(pnl)
            trades.append({
                "pair": pair, "direction": d,
                "entry_ts": int(p["entry_ts"]), "exit_ts": int(ts[i]),
                "entry_px": p["fill"], "exit_px": px,
                "size": p["size"], "pnl": pnl,
                "exit_reason": reason, "equity": equity,
            })
            del positions[key]

        # 2) manage pending orders: fill on touch, else expire
        for key in list(pending.keys()):
            o_ = pending[key]
            if i > o_["expiry_bar"]:
                del pending[key]
                continue
            d = o_["dir"]
            touched = (d == 1 and l <= o_["limit"]) or (d == -1 and h >= o_["limit"])
            if not touched:
                continue
            fill = o_["limit"]
            stop = o_["stop"]
            per_unit = abs(fill - stop)
            if per_unit <= 0:
                del pending[key]
                continue
            size = (o_["risk_usd"]) / per_unit
            size = min(size, equity / fill)  # 1x cap, no leverage
            if size * fill < 1.0:
                del pending[key]
                continue
            tp = fill + 2 * (fill - stop) if d == 1 else fill - 2 * (stop - fill)
            # sanity: stop/TP must bracket the fill on the correct sides
            if d == 1 and not (stop < fill < tp):
                del pending[key]
                continue
            if d == -1 and not (tp < fill < stop):
                del pending[key]
                continue
            ok, _ = risk.can_open()
            if not ok:
                del pending[key]
                continue
            positions[key] = {"dir": d, "size": size, "fill": fill,
                              "stop": stop, "tp": tp, "entry_ts": ts[i]}
            risk.register_open()
            del pending[key]

        # 3) maybe place a new resting order
        v = int(votes[i])
        if v == 0 or not regime_mask[i]:
            continue
        key = (pair, v)
        if key in positions or key in pending:
            continue
        entry_ref, inval_ref = entries[i], invalids[i]
        if not (np.isfinite(entry_ref) and np.isfinite(inval_ref)):
            continue
        limit = entry_ref * (1 - offset * v)
        # stop must be on the correct side of the limit price
        if v == 1 and not (inval_ref < limit):
            continue
        if v == -1 and not (inval_ref > limit):
            continue
        if abs(limit - inval_ref) <= 0:
            continue
        pending[key] = {"dir": v, "limit": limit, "stop": float(inval_ref),
                        "expiry_bar": i + max_wait - 1,
                        "risk_usd": equity * risk_frac}

    # close leftovers at last close (taker exit, conservative)
    for key, p in positions.items():
        d = p["dir"]
        px = cl[-1] * (1 - slip * d)
        gross = d * p["size"] * (px - p["fill"])
        fees = p["size"] * (p["fill"] * mfee + px * sfee)
        pnl = gross - fees
        equity += pnl
        trades.append({
            "pair": pair, "direction": d,
            "entry_ts": int(p["entry_ts"]), "exit_ts": int(ts[-1]),
            "entry_px": p["fill"], "exit_px": px,
            "size": p["size"], "pnl": pnl,
            "exit_reason": "eod", "equity": equity,
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


def walk_forward_maker(data: dict[str, pd.DataFrame], strategies,
                     bankroll: float) -> dict:
    """Maker-mode walk-forward: single regime-specialist strategy, OOS only.

    Same expanding-train / next-segment-test fold structure as the taker path
    (so the OOS segments are identical), but the train segment is unused —
    there are no ensemble weights to fit. The strategy and its parameters
    were fixed before seeing any of this data.
    """
    strats = {s.name: s for s in strategies}
    strat = strats[config.MAKER_STRATEGY]
    n = min(len(df) for df in data.values())
    data = {p: df.iloc[-n:].reset_index(drop=True) for p, df in data.items()}
    splits = [int(n * f) for f in config.WALK_FORWARD_SPLITS]
    oos_trades: list[pd.DataFrame] = []
    fold_info = []
    for k, s in enumerate(splits):
        e = splits[k + 1] if k + 1 < len(splits) else n
        fold_trades = []
        for pair, df in data.items():
            test = df.iloc[s:e].reset_index(drop=True)
            sig = strat.generate(test)
            reg = classify(test)
            mask = reg.isin(config.MAKER_REGIMES).to_numpy()
            t = simulate_maker(test, sig, mask, bankroll,
                               config.RISK_PER_TRADE, pair)
            fold_trades.append(t)
        ft = pd.concat(fold_trades, ignore_index=True) if fold_trades else pd.DataFrame()
        fold_info.append({"fold": k, "status": "ok", "trades": len(ft)})
        oos_trades.append(ft)
    trades = pd.concat(oos_trades, ignore_index=True) if oos_trades else pd.DataFrame()
    return {"trades": trades, "folds": fold_info, "bars": n}


def walk_forward_single(data: dict[str, pd.DataFrame], strategies,
                        bankroll: float) -> dict:
    """Single-strategy walk-forward (taker or maker engine).

    No ensemble weights — the strategy was selected before seeing the data.
    Same expanding-train / next-segment-test fold structure; only the test
    segments generate trades (OOS discipline preserved).
    """
    strats = {s.name: s for s in strategies}
    name = config.SINGLE_STRATEGY
    strat = strats[name]
    n = min(len(df) for df in data.values())
    data = {p: df.iloc[-n:].reset_index(drop=True) for p, df in data.items()}
    splits = [int(n * f) for f in config.WALK_FORWARD_SPLITS]
    oos_trades: list[pd.DataFrame] = []
    fold_info = []
    for k, s in enumerate(splits):
        e = splits[k + 1] if k + 1 < len(splits) else n
        fold_trades = []
        for pair, df in data.items():
            test = df.iloc[s:e].reset_index(drop=True)
            sig = strat.generate(test)
            reg = classify(test)
            mask = reg.isin(config.SINGLE_REGIMES).to_numpy()
            if config.EXECUTION_MODE == "maker":
                t = simulate_maker(test, sig, mask, bankroll,
                                   config.RISK_PER_TRADE, pair)
            else:
                t = simulate(test, sig["vote"].to_numpy(), sig["entry"].to_numpy(),
                             sig["invalidation"].to_numpy(), mask, bankroll,
                             config.RISK_PER_TRADE, pair)
            fold_trades.append(t)
        ft = pd.concat(fold_trades, ignore_index=True) if fold_trades else pd.DataFrame()
        fold_info.append({"fold": k, "status": "ok", "trades": len(ft)})
        oos_trades.append(ft)
    trades = pd.concat(oos_trades, ignore_index=True) if oos_trades else pd.DataFrame()
    return {"trades": trades, "folds": fold_info, "bars": n}


def walk_forward(data: dict[str, pd.DataFrame], strategies,
                 bankroll: float) -> dict:
    """Expanding-train / next-segment-test. Returns OOS trades + diagnostics."""
    if config.SINGLE_STRATEGY:
        return walk_forward_single(data, strategies, bankroll)
    if config.EXECUTION_MODE == "maker":
        return walk_forward_maker(data, strategies, bankroll)
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
