# tests/test_lifecycle_score.py
"""score_v1 — component-level unit tests for each predicate.

Each component is tested in isolation: build the minimum-viable today/yesterday
dict that activates exactly the target predicate, assert the feature is True.
Then build a negative case, assert False.
"""
import pytest

from lifecycle_score import (
    compute_trigger_score, compute_drift_score, ScoreResult,
    _ema_reclaim, _higher_low, _rs_strong, _lower_wick, _tight_range,
    _vol_expansion, _breakout, _close_strong, _intraday_reversal,
    _ema_alignment, _close_above_ema9, _atr_contraction, _low_vol_drift,
    _tight_close_cluster,
)


def _today(**overrides):
    base = {
        "open":   100.0,
        "close":  101.0,
        "high":   102.0,
        "low":    99.0,
        "ema9":   100.0,
        "ema21":  98.0,
        "ema65":  90.0,
        "atr14":  2.0,
        "atr14_pct": 2.0,
        "atr14_pct_5d_avg":  2.0,
        "atr14_pct_20d_avg": 2.0,
        "volume_ratio": 1.0,
        "high_20d_prior": 105.0,
        "change_5d_pct": 0.0,
    }
    base.update(overrides)
    return base


def _yesterday(**overrides):
    base = {"close": 99.0, "low": 98.0, "high": 100.0, "ema9": 99.5}
    base.update(overrides)
    return base


# ── trigger components ────────────────────────────────────────────


def test_ema_reclaim_positive():
    assert _ema_reclaim(_today(close=101, ema9=100), _yesterday(close=99)) is True


def test_ema_reclaim_negative_when_yesterday_already_above():
    assert _ema_reclaim(_today(close=101, ema9=100), _yesterday(close=100.5)) is False


def test_ema_reclaim_no_yesterday_returns_false():
    assert _ema_reclaim(_today(), None) is False


def test_higher_low_positive():
    assert _higher_low(_today(low=99), _yesterday(low=98)) is True


def test_higher_low_negative():
    assert _higher_low(_today(low=97), _yesterday(low=98)) is False


def test_rs_strong_positive():
    assert _rs_strong(ret_5d_pct=3.0, market_ret_5d_pct=1.0) is True


def test_rs_strong_negative_or_equal():
    assert _rs_strong(ret_5d_pct=1.0, market_ret_5d_pct=1.0) is False
    assert _rs_strong(ret_5d_pct=0.0, market_ret_5d_pct=2.0) is False


def test_rs_strong_none_returns_false():
    assert _rs_strong(None, 1.0) is False
    assert _rs_strong(1.0, None) is False


def test_lower_wick_positive():
    # open=100, close=101 (green), low=95, high=102 → wick = 100-95 = 5, range = 7, ratio = 0.71
    assert _lower_wick(_today(open=100, close=101, low=95, high=102)) is True


def test_lower_wick_negative_when_red_candle():
    # close < open — not a strong recovery
    assert _lower_wick(_today(open=101, close=100, low=95, high=102)) is False


def test_lower_wick_zero_range():
    assert _lower_wick(_today(high=100, low=100, open=100, close=100)) is False


def test_tight_range_positive():
    # range = 1, atr = 2, ratio = 0.5 < 0.7
    assert _tight_range(_today(high=101, low=100, atr14=2.0)) is True


def test_tight_range_negative_when_wide():
    assert _tight_range(_today(high=105, low=100, atr14=2.0)) is False


def test_vol_expansion_positive():
    assert _vol_expansion(_today(volume_ratio=1.5)) is True


def test_vol_expansion_below_threshold():
    assert _vol_expansion(_today(volume_ratio=1.1)) is False


def test_breakout_positive():
    assert _breakout(_today(close=110, high_20d_prior=105)) is True


def test_breakout_negative():
    assert _breakout(_today(close=104, high_20d_prior=105)) is False


def test_close_strong_positive_upper_half():
    # close=101.5, low=99, high=102 → (1.5/3) >= 0.5
    assert _close_strong(_today(close=101.5, low=99, high=102)) is True


def test_close_strong_negative_lower_half():
    assert _close_strong(_today(close=99.5, low=99, high=102)) is False


def test_intraday_reversal_positive():
    # open=100, low=98, close=101 — opened, dipped, recovered above open
    assert _intraday_reversal(_today(open=100, low=98, close=101)) is True


def test_intraday_reversal_negative_no_dip():
    # open=100, low=100 — open equals the day's low; no dip-recovery pattern
    assert _intraday_reversal(_today(open=100, low=100, close=101)) is False


# ── drift components ──────────────────────────────────────────────


def test_ema_alignment_positive():
    assert _ema_alignment(_today(ema9=100, ema21=98, ema65=90)) is True


def test_ema_alignment_negative_when_collapsed():
    assert _ema_alignment(_today(ema9=98, ema21=100, ema65=90)) is False


def test_close_above_ema9():
    assert _close_above_ema9(_today(close=101, ema9=100)) is True
    assert _close_above_ema9(_today(close=99, ema9=100)) is False


def test_atr_contraction_positive():
    assert _atr_contraction(_today(atr14_pct_5d_avg=1.5, atr14_pct_20d_avg=2.0)) is True


def test_atr_contraction_negative():
    assert _atr_contraction(_today(atr14_pct_5d_avg=2.5, atr14_pct_20d_avg=2.0)) is False


def test_low_vol_drift_positive():
    # atr14_pct = 1.4, 20d_avg = 2.0, ratio = 0.7 < 0.8
    assert _low_vol_drift(_today(atr14_pct=1.4, atr14_pct_20d_avg=2.0)) is True


def test_low_vol_drift_negative():
    assert _low_vol_drift(_today(atr14_pct=1.8, atr14_pct_20d_avg=2.0)) is False


def test_tight_close_cluster_positive():
    # closes spread 0.5, atr = 2.0, ratio = 0.25 < 0.5
    assert _tight_close_cluster(_today(atr14=2.0), [100.0, 100.3, 100.5]) is True


def test_tight_close_cluster_negative_wide_spread():
    assert _tight_close_cluster(_today(atr14=2.0), [100.0, 102.0, 100.5]) is False


def test_tight_close_cluster_insufficient_history():
    assert _tight_close_cluster(_today(atr14=2.0), [100.0, 100.5]) is False


def test_tight_close_cluster_none_history():
    assert _tight_close_cluster(_today(atr14=2.0), None) is False


# ── ScoreResult invariants ────────────────────────────────────────


def test_trigger_score_invariants_active_count_matches_features():
    today = _today(close=110, ema9=100, high=111, low=109, volume_ratio=1.5,
                   high_20d_prior=105, open=109, change_5d_pct=5.0)
    yesterday = _yesterday(close=99, low=98)
    res = compute_trigger_score(today, yesterday, market_ret_5d_pct=1.0)
    assert isinstance(res, ScoreResult)
    assert res.track == "trigger"
    assert res.active_count == sum(1 for v in res.features.values() if v)
    # score == sum of (weight for component where active=True)
    assert res.score == sum(c["weight"] for c in res.components_list if c["active"])


def test_drift_score_no_volume_expansion_component():
    """Spec §6.2: drift MUST NOT include vol_expansion (archetype separation)."""
    today = _today()
    res = compute_drift_score(today, _yesterday(), recent_3d_closes=[100, 100.3, 100.5],
                              market_ret_5d_pct=1.0)
    assert "vol_expansion" not in res.features
    assert "breakout" not in res.features


def test_score_components_ordering_matches_config():
    """Spec §6.5: components_list MUST follow config dict iteration order."""
    from lifecycle_score_config import TRIGGER_WEIGHTS, DRIFT_WEIGHTS

    res = compute_trigger_score(_today(), _yesterday(), market_ret_5d_pct=1.0)
    names_in_order = [c["name"] for c in res.components_list]
    assert names_in_order == list(TRIGGER_WEIGHTS.keys())

    res = compute_drift_score(_today(), _yesterday(),
                              recent_3d_closes=[100, 100.3, 100.5], market_ret_5d_pct=1.0)
    names_in_order = [c["name"] for c in res.components_list]
    assert names_in_order == list(DRIFT_WEIGHTS.keys())


def test_zero_data_returns_zero_score():
    """All missing data → all features False → score 0 (NEVER auto-promoted)."""
    minimal = {}
    res = compute_trigger_score(minimal, None, market_ret_5d_pct=None)
    assert res.score == 0
    assert res.active_count == 0
    assert all(v is False for v in res.features.values())


def test_rs_delta_pct_computed_when_both_present():
    res = compute_trigger_score(_today(change_5d_pct=4.0), _yesterday(),
                                market_ret_5d_pct=1.5)
    assert res.rs_delta_pct == 2.5


def test_rs_delta_pct_none_when_missing():
    res = compute_trigger_score(_today(change_5d_pct=None), _yesterday(),
                                market_ret_5d_pct=1.5)
    assert res.rs_delta_pct is None


# ── score_tier helper ─────────────────────────────────────────────


def test_compute_score_tier_trigger_weak():
    from lifecycle_score import compute_score_tier
    assert compute_score_tier(3, "trigger") == "WEAK"


def test_compute_score_tier_trigger_mid():
    from lifecycle_score import compute_score_tier
    assert compute_score_tier(4, "trigger") == "MID"
    assert compute_score_tier(5, "trigger") == "MID"


def test_compute_score_tier_trigger_strong():
    from lifecycle_score import compute_score_tier
    assert compute_score_tier(6, "trigger") == "STRONG"


def test_compute_score_tier_trigger_below_probe_none():
    """Trigger score 0-2 = WATCH territory → no tier."""
    from lifecycle_score import compute_score_tier
    for s in (0, 1, 2):
        assert compute_score_tier(s, "trigger") is None


def test_compute_score_tier_trigger_above_enter_none():
    """Trigger score 7+ = ENTER (out of PROBE bucket) → no tier."""
    from lifecycle_score import compute_score_tier
    assert compute_score_tier(7, "trigger") is None
    assert compute_score_tier(14, "trigger") is None


def test_compute_score_tier_drift_weak():
    from lifecycle_score import compute_score_tier
    assert compute_score_tier(4, "drift") == "WEAK"


def test_compute_score_tier_drift_mid():
    from lifecycle_score import compute_score_tier
    assert compute_score_tier(5, "drift") == "MID"


def test_compute_score_tier_drift_strong():
    from lifecycle_score import compute_score_tier
    assert compute_score_tier(6, "drift") == "STRONG"
    assert compute_score_tier(9, "drift") == "STRONG"


def test_compute_score_tier_drift_below_probe_none():
    """Drift score 0-3 = TRENDING territory → no tier."""
    from lifecycle_score import compute_score_tier
    for s in (0, 1, 2, 3):
        assert compute_score_tier(s, "drift") is None


def test_compute_score_tier_none_inputs():
    from lifecycle_score import compute_score_tier
    assert compute_score_tier(None, "trigger") is None
    assert compute_score_tier(5, None) is None
    assert compute_score_tier(None, None) is None


def test_compute_score_tier_unknown_track_none():
    from lifecycle_score import compute_score_tier
    assert compute_score_tier(5, "unknown_track") is None


# ── rs_tier helper ────────────────────────────────────────────────


def test_compute_rs_tier_strong():
    from lifecycle_score import compute_rs_tier
    assert compute_rs_tier(10.0) == "STRONG"
    assert compute_rs_tier(15.5) == "STRONG"


def test_compute_rs_tier_mid():
    from lifecycle_score import compute_rs_tier
    assert compute_rs_tier(5.0) == "MID"
    assert compute_rs_tier(9.99) == "MID"


def test_compute_rs_tier_weak():
    from lifecycle_score import compute_rs_tier
    assert compute_rs_tier(0.0) == "WEAK"
    assert compute_rs_tier(4.99) == "WEAK"


def test_compute_rs_tier_below_zero_none():
    """Negative rs_delta_pct = underperforming market → None (not WEAK)."""
    from lifecycle_score import compute_rs_tier
    assert compute_rs_tier(-0.01) is None
    assert compute_rs_tier(-5.0) is None


def test_compute_rs_tier_none_input():
    from lifecycle_score import compute_rs_tier
    assert compute_rs_tier(None) is None


# ── ScoreResult tier fields populated by _assemble() ──────────────


def test_score_result_includes_score_tier_field():
    """compute_trigger_score must produce score_tier in result."""
    from lifecycle_score import compute_trigger_score
    today = _today(close=110, ema9=100, low=99.5, high=110.5, change_5d_pct=5.0)
    yesterday = _yesterday(close=99, low=98)
    res = compute_trigger_score(today, yesterday, market_ret_5d_pct=1.0)
    assert hasattr(res, "score_tier")
    assert res.score_tier in ("WEAK", "MID", "STRONG", None)


def test_score_result_includes_rs_tier_field():
    """compute_drift_score must produce rs_tier in result."""
    from lifecycle_score import compute_drift_score
    today = _today(close=101, ema9=100, ema21=98, ema65=90,
                   atr14_pct=1.5, atr14_pct_5d_avg=1.5, atr14_pct_20d_avg=2.0,
                   change_5d_pct=5.0)
    yesterday = _yesterday(close=99, low=98)
    res = compute_drift_score(today, yesterday,
                              recent_3d_closes=[100, 100.5, 101], market_ret_5d_pct=1.0)
    assert hasattr(res, "rs_tier")
    # 5.0 - 1.0 = 4.0 → WEAK tier
    assert res.rs_tier == "WEAK"


def test_score_result_tier_consistent_with_score():
    """score_tier band must contain the score."""
    from lifecycle_score import compute_trigger_score
    from lifecycle_score_config import SCORE_TIER_BANDS
    today = _today(close=110, ema9=100, low=99.5, high=110.5, change_5d_pct=5.0)
    yesterday = _yesterday(close=99, low=98)
    res = compute_trigger_score(today, yesterday, market_ret_5d_pct=1.0)
    if res.score_tier is not None:
        lo, hi = SCORE_TIER_BANDS[res.track][res.score_tier]
        assert lo <= res.score <= hi
