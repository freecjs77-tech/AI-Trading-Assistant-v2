# lifecycle_signal.py
"""Phase A — pure-function lifecycle state machine.

State machines:
  setup_state    ∈ {TREND_OK, PULLBACK, BASE_FORMING, EXTENDED, BROKEN}
  trigger_state  ∈ {WAIT, EARLY_TRIGGER, CONFIRMED_TRIGGER}
  entry_decision ∈ {ENTER_OK, EARLY, STAGING, AVOID}

setup_state evaluation order is strict (first match wins):
  1. BROKEN  2. EXTENDED  3. BASE_FORMING  4. PULLBACK  5. TREND_OK
"""
from __future__ import annotations

from typing import Optional

from lifecycle_config import (
    PULLBACK_MAX_DIST_FROM_EMA9,
    BASE_FORMING_DAYS_MIN, BASE_FORMING_DAYS_MAX,
    BASE_VOL_CONTRACTION_RATIO,
    EXTENDED_DIST_FROM_EMA9, EXTENDED_RSI_MIN,
    TRIGGER_CONFIRM_VOL_RATIO_MIN, TRIGGER_CONFIRM_CLOSE_HIGH_RATIO,
    FAILED_BREAKOUT_REQUIRE_BELOW_PRIOR_LOW,
    RISK_OVERHEAT_RSI, RISK_PARABOLIC_RET_1D, RISK_PARABOLIC_VOL_RATIO,
)


def _is_trend_ok(r: dict) -> bool:
    """ema9 > ema21 > ema65 AND ema65 slope positive.

    NOTE: close > ema21 is NOT required here — a close that has dipped below
    ema21 (but above ema65) still belongs in TREND_OK rather than BROKEN.
    The PULLBACK predicate separately rejects close < ema21 (so a deep
    intra-ema pullback falls straight through to TREND_OK — which is correct).
    """
    e9, e21, e65 = r.get("ema9"), r.get("ema21"), r.get("ema65")
    if e9 is None or e21 is None or e65 is None:
        return False
    if not (e9 > e21 > e65):
        return False
    if (r.get("ema65_slope_5d") or 0) <= 0:
        return False
    return True


def _is_broken(r: dict) -> bool:
    e21, e65 = r.get("ema21"), r.get("ema65")
    close = r.get("close")
    if e21 is None or e65 is None or close is None:
        return False
    return (e21 < e65) or (close < e65)


def _is_extended(r: dict) -> bool:
    e9, e21, e65 = r.get("ema9"), r.get("ema21"), r.get("ema65")
    close = r.get("close")
    rsi = r.get("rsi14")
    if e9 is None or e21 is None or e65 is None or close is None or rsi is None:
        return False
    if not (e9 > e21 > e65):
        return False
    dist_pct = abs(close - e9) / e9
    return dist_pct > EXTENDED_DIST_FROM_EMA9 and rsi > EXTENDED_RSI_MIN


def _is_base_forming(r: dict) -> bool:
    if not _is_trend_ok(r):
        return False
    days = r.get("days_sideways") or 0
    if not (BASE_FORMING_DAYS_MIN <= days <= BASE_FORMING_DAYS_MAX):
        return False
    a5  = r.get("atr14_pct_5d_avg")
    a20 = r.get("atr14_pct_20d_avg")
    if a5 is None or a20 is None or a5 >= a20:
        return False
    v5  = r.get("volume_5d_avg")
    v20 = r.get("volume_20d_avg")
    if v5 is None or v20 is None or v5 >= v20 * BASE_VOL_CONTRACTION_RATIO:
        return False
    if (r.get("ema21_slope_5d") or 0) <= 0:
        return False
    return True


def _is_pullback(r: dict) -> bool:
    if not _is_trend_ok(r):
        return False
    e9 = r.get("ema9")
    close = r.get("close")
    e21 = r.get("ema21")
    if e9 is None or close is None or e21 is None:
        return False
    if abs(close - e9) / e9 > PULLBACK_MAX_DIST_FROM_EMA9:
        return False
    if close < e21:
        return False
    return True


def evaluate_setup_state(raw: dict) -> str:
    """Strict precedence: BROKEN > EXTENDED > BASE_FORMING > PULLBACK > TREND_OK."""
    if _is_broken(raw):
        return "BROKEN"
    if _is_extended(raw):
        return "EXTENDED"
    if _is_base_forming(raw):
        return "BASE_FORMING"
    if _is_pullback(raw):
        return "PULLBACK"
    if _is_trend_ok(raw):
        return "TREND_OK"
    return "BROKEN"  # No alignment + no break = degraded; treat as out-of-trend.
