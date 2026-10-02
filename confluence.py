"""Confluence engine: weighted voting across the strategy library.

- Weights come from walk-forward per-regime expectancy (see backtest.py).
  Weight = max(0, expectancy); normalized to sum to 1. Zero/negative
  expectancy strategies get zero weight (they don't vote).
- Regime gating: trend strategies vote only in trend, mean-reversion only
  in chop; momentum/volatility/volume vote in both, scaled by
  REGIME_WEIGHT_MULT.
- Entry when: >= MIN_AGREE strategies agree in one direction AND
  |weighted score| >= SCORE_THRESHOLD * max_possible.
- Position sizing: fractional Kelly. kelly_f = (p*(b+1)-1)/b from the
  ensemble's walk-forward stats (p = win rate, b = avg_win/avg_loss);
  we trade half-Kelly, capped at RISK_PER_TRADE (1%), floored at 0.
  No edge (kelly_f <= 0) => risk 0 => no trades. That is correct behavior.

decide() is pure: given per-strategy signal rows + regime + bankroll state,
it returns an action dict or None. No side effects, no I/O.
"""
from __future__ import annotations

import math

import config


def kelly_risk_fraction(win_rate: float, payoff_ratio: float) -> float:
    """Half-Kelly risk fraction, clamped to [0, RISK_PER_TRADE].

    Returns 0 when there is no edge (or stats are degenerate).
    """
    if win_rate <= 0 or win_rate >= 1 or payoff_ratio <= 0:
        return 0.0
    kelly = (win_rate * (payoff_ratio + 1) - 1) / payoff_ratio
    half = kelly / 2
    return max(0.0, min(config.RISK_PER_TRADE, half))


def decide(signals: list[dict], regime: str, weights: dict[str, float],
           bankroll: float, win_rate: float, payoff_ratio: float) -> dict | None:
    """signals: [{name, family, vote, entry, invalidation, conviction}].

    Returns None (no trade) or:
      {direction, entry, invalidation, size_units, risk_usd,
       agreeing: [names], score: float}
    """
    # regime gating + weighting
    scored = []
    for s in signals:
        if s["vote"] == 0:
            continue
        fam = s["family"]
        mult = config.REGIME_WEIGHT_MULT[regime][fam]
        w = weights.get(s["name"], 0.0) * mult
        if w <= 0 or mult <= 0:
            continue
        scored.append((s, w))

    longs = [x for x in scored if x[0]["vote"] == 1]
    shorts = [x for x in scored if x[0]["vote"] == -1]
    side = None
    group: list = []
    if len(longs) >= config.MIN_AGREE and len(longs) >= len(shorts):
        side, group = 1, longs
    elif len(shorts) >= config.MIN_AGREE and len(shorts) > len(longs):
        side, group = -1, shorts
    if side is None:
        return None

    max_possible = sum(w for _, w in scored)
    side_score = sum(w * s["conviction"] for s, w in group)
    if max_possible <= 0 or side_score < config.SCORE_THRESHOLD * max_possible:
        return None

    # consensus entry/invalidation: conviction-weighted average
    tot_w = sum(w for _, w in group)
    entry = sum(s["entry"] * w for s, w in group) / tot_w
    inval = sum(s["invalidation"] * w for s, w in group) / tot_w

    risk_frac = kelly_risk_fraction(win_rate, payoff_ratio)
    if risk_frac <= 0:
        return None  # no measured edge => no trade
    risk_usd = bankroll * risk_frac
    per_unit_risk = abs(entry - inval)
    if per_unit_risk <= 0 or not math.isfinite(per_unit_risk):
        return None
    size_units = risk_usd / per_unit_risk
    # hard cap: 1x, no leverage, no margin
    max_units = bankroll / entry
    size_units = min(size_units, max_units)
    if size_units * entry < 1.0:  # dust: less than $1 notional
        return None

    return {
        "direction": side,
        "entry": entry,
        "invalidation": inval,
        "size_units": size_units,
        "risk_usd": risk_usd,
        "agreeing": [s["name"] for s, _ in group],
        "score": side_score / max_possible,
    }
