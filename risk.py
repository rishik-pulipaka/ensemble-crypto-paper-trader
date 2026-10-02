"""Risk manager: hard-coded, non-negotiable limits.

There is deliberately NO flag, env var, or config path that disables or
loosens these. Loosening risk requires editing this file, which is a
conscious act, not an accident.

Enforced:
  - RISK_PER_TRADE cap is applied in confluence.decide (sizing).
  - MAX_POSITIONS: engine must not open beyond this.
  - MAX_DAILY_LOSS: if realized day P&L <= -MAX_DAILY_LOSS * day_start_equity,
    halted_until_next_day. No new entries while halted.
  - Stops/take-profits: every position carries stop = invalidation level and
    tp = entry +/- TP_MULTIPLE * risk_distance at open. Checked every bar.

Paper/live engines call: new_day(date, equity), register_fill(...),
can_open(), check_exits(position, bar) -> 'stop' | 'take_profit' | None,
register_close(pnl).
"""
from __future__ import annotations

import config


class RiskManager:
    def __init__(self):
        self.day = None
        self.day_start_equity = config.STARTING_BANKROLL
        self.day_pnl = 0.0
        self.halted = False
        self.open_count = 0

    # -- daily bookkeeping ------------------------------------------------
    def new_day(self, day, equity: float):
        if self.day != day:
            self.day = day
            self.day_start_equity = equity
            self.day_pnl = 0.0
            self.halted = False  # halt resets daily; the loss does not

    def register_close(self, pnl: float):
        self.day_pnl += pnl
        self.open_count = max(0, self.open_count - 1)
        if self.day_pnl <= -config.MAX_DAILY_LOSS * self.day_start_equity:
            self.halted = True

    def register_open(self):
        self.open_count += 1

    # -- gates -------------------------------------------------------------
    def can_open(self) -> tuple[bool, str]:
        if self.halted:
            return False, "daily-loss halt"
        if self.open_count >= config.MAX_POSITIONS:
            return False, "max positions"
        return True, "ok"

    # -- exits --------------------------------------------------------------
    @staticmethod
    def make_levels(direction: int, entry: float, invalidation: float) -> dict:
        risk_dist = abs(entry - invalidation)
        if direction == 1:
            return {"stop": invalidation,
                    "take_profit": entry + config.TP_MULTIPLE * risk_dist}
        return {"stop": invalidation,
                "take_profit": entry - config.TP_MULTIPLE * risk_dist}

    @staticmethod
    def check_exits(direction: int, levels: dict, bar: dict) -> str | None:
        """Conservative intrabar: if both stop and TP touched, assume stop
        (worst fill) unless the bar opened beyond TP."""
        if direction == 1:
            stop_hit = bar["low"] <= levels["stop"]
            tp_hit = bar["high"] >= levels["take_profit"]
        else:
            stop_hit = bar["high"] >= levels["stop"]
            tp_hit = bar["low"] <= levels["take_profit"]
        if stop_hit and tp_hit:
            # bar spanned the whole range: adverse first (conservative)
            return "stop"
        if stop_hit:
            return "stop"
        if tp_hit:
            return "take_profit"
        return None
