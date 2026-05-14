# lifecycle_score.py
"""Score engine v1 — trigger_score (PULLBACK/BASE_FORMING) + drift_score (TREND_OK).

Pure functions. No I/O. Component-level explainability:
each call returns a ScoreResult with features{}, score_components[], and
the computed total.

See docs/superpowers/specs/2026-05-13-lifecycle-probabilistic-engine-design.md §6
for component definitions and the rationale behind each one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from lifecycle_score_config import (
    TRIGGER_WEIGHTS, DRIFT_WEIGHTS,
    LOWER_WICK_MIN_RATIO, CLOSE_STRONG_MIN_RATIO,
    TIGHT_RANGE_MAX_ATR, VOL_EXPANSION_MIN_RATIO,
    LOW_VOL_DRIFT_RATIO, TIGHT_CLUSTER_MAX_ATR,
    SCORE_TIER_BANDS, RS_TIER_BANDS,        # NEW
)


@dataclass
class ScoreResult:
    """Output of compute_trigger_score / compute_drift_score.

    Invariants enforced by _assemble() builder (not by this dataclass):
      - score = sum(weight for c in components_list if c.active)
      - active_count = sum(1 for v in features.values() if v)
      - features keys == TRIGGER_WEIGHTS.keys() OR DRIFT_WEIGHTS.keys()
      - components_list ordering == config dict iteration order
    Direct construction (e.g., in tests) bypasses these guarantees.
    """
    track: str                       # "trigger" or "drift"
    score: int = 0
    active_count: int = 0
    features: dict = field(default_factory=dict)
    components_list: list = field(default_factory=list)
    rs_delta_pct: Optional[float] = None  # ret_5d - market_ret_5d (raw margin)
    score_tier: Optional[str] = None      # NEW: "WEAK"|"MID"|"STRONG"|None
    rs_tier: Optional[str] = None         # NEW: "WEAK"|"MID"|"STRONG"|None


# ── Component predicates (each returns bool) ───────────────────────


def _ema_reclaim(today, yesterday) -> bool:
    """today.close > ema9 AND yesterday.close <= ema9 (Phase A arm 1)."""
    if not yesterday:
        return False
    e9 = today.get("ema9")
    yc = yesterday.get("close")
    tc = today.get("close")
    if e9 is None or yc is None or tc is None:
        return False
    return yc <= e9 < tc


def _higher_low(today, yesterday) -> bool:
    """today.low > yesterday.low."""
    if not yesterday:
        return False
    yl = yesterday.get("low")
    tl = today.get("low")
    if yl is None or tl is None:
        return False
    return tl > yl


def _rs_strong(ret_5d_pct: Optional[float],
               market_ret_5d_pct: Optional[float]) -> bool:
    """ret_5d > market_ret_5d. Either None → False."""
    if ret_5d_pct is None or market_ret_5d_pct is None:
        return False
    return ret_5d_pct > market_ret_5d_pct


def _lower_wick(today) -> bool:
    """(min(open,close) - low) / (high - low) >= 0.4 AND close >= open."""
    h, l, o, c = today.get("high"), today.get("low"), today.get("open"), today.get("close")
    if None in (h, l, o, c) or h == l:
        return False
    if c < o:
        return False
    wick = min(o, c) - l
    rng = h - l
    return wick / rng >= LOWER_WICK_MIN_RATIO


def _tight_range(today) -> bool:
    """(high - low) / atr14 < 0.7."""
    h, l, atr = today.get("high"), today.get("low"), today.get("atr14")
    if h is None or l is None or atr is None or atr <= 0:
        return False
    return (h - l) / atr < TIGHT_RANGE_MAX_ATR


def _vol_expansion(today) -> bool:
    """volume_ratio >= 1.2."""
    vr = today.get("volume_ratio")
    if vr is None:
        return False
    return vr >= VOL_EXPANSION_MIN_RATIO


def _breakout(today) -> bool:
    """close > high_20d_prior (excludes today)."""
    c = today.get("close")
    hp = today.get("high_20d_prior")
    if c is None or hp is None:
        return False
    return c > hp


def _close_strong(today) -> bool:
    """(close - low) / (high - low) >= 0.5 — upper 50%."""
    h, l, c = today.get("high"), today.get("low"), today.get("close")
    if None in (h, l, c) or h == l:
        return False
    return (c - l) / (h - l) >= CLOSE_STRONG_MIN_RATIO


def _intraday_reversal(today) -> bool:
    """low < open AND close > open."""
    o, l, c = today.get("open"), today.get("low"), today.get("close")
    if None in (o, l, c):
        return False
    return l < o and c > o


def _ema_alignment(today) -> bool:
    """ema9 > ema21 > ema65."""
    e9 = today.get("ema9")
    e21 = today.get("ema21")
    e65 = today.get("ema65")
    if None in (e9, e21, e65):
        return False
    return e9 > e21 > e65


def _close_above_ema9(today) -> bool:
    """close > ema9."""
    c = today.get("close")
    e9 = today.get("ema9")
    if c is None or e9 is None:
        return False
    return c > e9


def _atr_contraction(today) -> bool:
    """5d avg ATR% < 20d avg ATR%."""
    a5 = today.get("atr14_pct_5d_avg")
    a20 = today.get("atr14_pct_20d_avg")
    if a5 is None or a20 is None:
        return False
    return a5 < a20


def _low_vol_drift(today) -> bool:
    """atr14_pct < 0.8 * atr14_pct_20d_avg."""
    a = today.get("atr14_pct")
    a20 = today.get("atr14_pct_20d_avg")
    if a is None or a20 is None:
        return False
    return a < (a20 * LOW_VOL_DRIFT_RATIO)


def _tight_close_cluster(today, recent_3d_closes) -> bool:
    """(max(close[-3:]) - min(close[-3:])) / atr14 < 0.5."""
    atr = today.get("atr14")
    if atr is None or atr <= 0:
        return False
    if not recent_3d_closes or len(recent_3d_closes) < 3:
        return False
    closes = [c for c in recent_3d_closes if c is not None]
    if len(closes) < 3:
        return False
    spread = max(closes) - min(closes)
    return spread / atr < TIGHT_CLUSTER_MAX_ATR


# ── Score assembly ─────────────────────────────────────────────────


def compute_score_tier(score: Optional[int], track: Optional[str]) -> Optional[str]:
    """Map score+track to tier string. Returns None when score is None or
    falls outside any band (e.g., trigger score 0-2 = WATCH territory).

    Spec §3.1 / §4.3.
    """
    if score is None or track is None:
        return None
    bands = SCORE_TIER_BANDS.get(track)
    if not bands:
        return None
    for tier_name, (lo, hi) in bands.items():
        if lo <= score <= hi:
            return tier_name
    return None  # below WEAK band — e.g., trigger score 0-2


def compute_rs_tier(rs_delta_pct: Optional[float]) -> Optional[str]:
    """Map rs_delta_pct to tier. Returns None when not computed.
    Negative rs_delta_pct (underperforming market) → None, not WEAK.

    Spec §3.2 / §4.3.
    """
    if rs_delta_pct is None:
        return None
    for tier_name in ("STRONG", "MID", "WEAK"):
        if rs_delta_pct >= RS_TIER_BANDS[tier_name]:
            return tier_name
    return None  # rs_delta_pct < 0


def _assemble(weights: dict, features: dict, track: str,
              rs_delta_pct: Optional[float] = None) -> ScoreResult:
    """Build a ScoreResult preserving config-declaration ordering."""
    components_list = []
    score = 0
    active_count = 0
    for name in weights.keys():  # config-declared iteration order
        weight = weights[name]
        active = bool(features.get(name, False))
        components_list.append({"name": name, "weight": weight, "active": active})
        if active:
            score += weight
            active_count += 1
    return ScoreResult(
        track=track, score=score, active_count=active_count,
        features=dict(features), components_list=components_list,
        rs_delta_pct=rs_delta_pct,
        score_tier=compute_score_tier(score, track),    # NEW
        rs_tier=compute_rs_tier(rs_delta_pct),          # NEW
    )


def compute_trigger_score(today: dict, yesterday: Optional[dict],
                          market_ret_5d_pct: Optional[float]) -> ScoreResult:
    """Score for PULLBACK / BASE_FORMING setup. 9 components, max 14."""
    ret_5d = today.get("ret_5d_pct")
    if ret_5d is None:
        ret_5d = today.get("change_5d_pct")  # fetch_market_data field name

    features = {
        "ema_reclaim":       _ema_reclaim(today, yesterday),
        "higher_low":        _higher_low(today, yesterday),
        "rs_strong":         _rs_strong(ret_5d, market_ret_5d_pct),
        "lower_wick":        _lower_wick(today),
        "tight_range":       _tight_range(today),
        "vol_expansion":     _vol_expansion(today),
        "breakout":          _breakout(today),
        "close_strong":      _close_strong(today),
        "intraday_reversal": _intraday_reversal(today),
    }
    rs_delta = (
        round(ret_5d - market_ret_5d_pct, 4)
        if (ret_5d is not None and market_ret_5d_pct is not None) else None
    )
    return _assemble(TRIGGER_WEIGHTS, features, "trigger", rs_delta)


def compute_drift_score(today: dict, yesterday: Optional[dict],
                        recent_3d_closes: Optional[list],
                        market_ret_5d_pct: Optional[float]) -> ScoreResult:
    """Score for TREND_OK setup — quiet leader detection. 7 components, max 9."""
    ret_5d = today.get("ret_5d_pct")
    if ret_5d is None:
        ret_5d = today.get("change_5d_pct")

    features = {
        "ema_alignment":       _ema_alignment(today),
        "close_above_ema9":    _close_above_ema9(today),
        "higher_low":          _higher_low(today, yesterday),
        "atr_contraction":     _atr_contraction(today),
        "rs_strong":           _rs_strong(ret_5d, market_ret_5d_pct),
        "low_vol_drift":       _low_vol_drift(today),
        "tight_close_cluster": _tight_close_cluster(today, recent_3d_closes),
    }
    rs_delta = (
        round(ret_5d - market_ret_5d_pct, 4)
        if (ret_5d is not None and market_ret_5d_pct is not None) else None
    )
    return _assemble(DRIFT_WEIGHTS, features, "drift", rs_delta)
