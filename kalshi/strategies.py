"""Version rule constructors. Params are FROZEN before seeing results.

V1 and V3 are fully specified up front. V2/V4/V5 are specified from
V1-V3 diagnostics with minimal, pre-declared filter families to bound
multiple-testing damage; each documents exactly what was learned.
"""
import sqlite3

from .kalshi_config import DB_PATH, V1, V2, V3, V4, V5, MAX_TTE_DAYS


def fit_eval_cut(frac=0.7):
    """70/30 split timestamp by market expiry. Computed from dev data."""
    con = sqlite3.connect(DB_PATH)
    exps = sorted(r[0] for r in con.execute("SELECT expiration_ts FROM markets"))
    con.close()
    return exps[int(len(exps) * frac)]


def v1_rule():
    """Favorite-longshot bias fade. Buy YES at first daily yes_ask close
    >= 85c within 14 days of expiry. No fitting, no filters."""
    return {
        "version": V1["name"],
        "side": "buy_yes",
        "entry_price_threshold": V1["entry_price_threshold"],
        "entry_price_field": V1["entry_price_field"],
        "max_tte_days": MAX_TTE_DAYS,
    }


def v2_rule(fit_before_ts=None, eval_after_ts=None):
    """V1 + market-selection filters. Filters chosen ONCE from V1
    diagnostics on the fit window only (first 70% of dev by expiry).
    Fit-window evidence (n=226, exp=-4.62c):
      - KXCPI (-8.35c) and KXNBAGAME (-6.83c) were clear losers ->
        exclude_series={KXCPI, KXNBAGAME}
      - market volume >100k bucket was least-bad (-2.07c vs -5.92c/-12.24c
        for thinner) -> min_market_volume=100000. (Candle-level volume is
        unpopulated in this dataset, so market volume is the proxy.)
      - TTE showed no exploitable variation (median 12.6d, 97% in 7-14d)
        -> max_tte_days left at 14.
    Evaluated ONLY on the eval window (last 30% by expiry)."""
    cut = fit_eval_cut(0.7)
    return {
        "version": V2["name"],
        "side": "buy_yes",
        "entry_price_threshold": V2["entry_price_threshold"],
        "entry_price_field": V2["entry_price_field"],
        "max_tte_days": MAX_TTE_DAYS,
        "exclude_series": {"KXCPI", "KXNBAGAME"},
        "min_market_volume": 100000,
        "eval_after_ts": cut,
    }


def v3_rule():
    """Tail-selling. Sell YES (take the bid) the first day yes_bid closes
    <= 15c within 14 days of expiry. Taker fill = conservative (a real
    maker would pay $0 fee but suffer adverse selection; we model taker
    AND report a -8.6c adverse-selection haircut scenario from 50thycal)."""
    return {
        "version": V3["name"],
        "side": "sell_yes",
        "entry_price_threshold": V3["entry_price_threshold"],
        "entry_price_field": V3["entry_price_field"],
        "max_tte_days": MAX_TTE_DAYS,
        "adverse_selection_haircut": V3["adverse_selection_haircut"],
    }


def v4_rule():
    """Event-type specialization from V1-V3 per-series diagnostics.
    Fit-window evidence:
      - V1: KXFED (-0.27c) and KXNHLGAME (-0.16c) were the only ~flat
        series; KXCPI (-8.35c) and KXNBAGAME (-6.83c) were clear losers.
      - V3: EVERY series negative (-1.37c to -6.55c); tail-selling has no
        viable category -> V4 stays buy-side only.
    V4 = V1 rule restricted to the two least-bad series + the V2 volume
    filter. Evaluated ONLY on the eval window (last 30% by expiry)."""
    cut = fit_eval_cut(0.7)
    return {
        "version": V4["name"],
        "side": "buy_yes",
        "entry_price_threshold": V4["entry_price_threshold"],
        "entry_price_field": V4["entry_price_field"],
        "max_tte_days": MAX_TTE_DAYS,
        "only_series": {"KXNHLGAME", "KXFED"},
        "min_market_volume": 100000,
        "eval_after_ts": cut,
    }


def v5_rule():
    """Ensemble of whatever actually worked in V1-V4.
    Honest accounting: V1 KILL (-3.43c), V2 KILL (thin, +0.59c/n=41),
    V3 KILL (-2.97c), V4 KILL (thin, +0.59c/n=41). Nothing passed.
    The ONLY positive direction was V2's filter set (exclude KXCPI/KXNBAGAME,
    market vol >= 100k) on the eval window. V5 tests that exact filter set
    on ALL dev data for maximum sample. This is IN-SAMPLE for the filter
    selection (filters were chosen on the 70% fit window which overlaps),
    so it CANNOT pass the bar -- it is exploratory only, to see whether
    the faint V2 signal survives contact with more data."""
    return {
        "version": V5["name"],
        "side": "buy_yes",
        "entry_price_threshold": V1["entry_price_threshold"],
        "entry_price_field": V1["entry_price_field"],
        "max_tte_days": MAX_TTE_DAYS,
        "exclude_series": {"KXCPI", "KXNBAGAME"},
        "min_market_volume": 100000,
        "exploratory_in_sample": True,
    }
