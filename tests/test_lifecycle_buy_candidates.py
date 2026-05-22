"""Tests for lifecycle_buy_candidates module."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_normalize_base_score_pullback_uses_trigger_score():
    """PULLBACK setup → trigger score 그대로 0~14."""
    from lifecycle_buy_candidates import normalize_base_score
    snap = {"setup": "PULLBACK", "score": 6, "score_track": "trigger"}
    assert normalize_base_score(snap) == 6.0


def test_normalize_base_score_base_forming_uses_trigger_score():
    from lifecycle_buy_candidates import normalize_base_score
    snap = {"setup": "BASE_FORMING", "score": 9, "score_track": "trigger"}
    assert normalize_base_score(snap) == 9.0


def test_normalize_base_score_trend_ok_scales_drift_to_14():
    """TREND_OK drift score 6 → 6 × 14/9 ≈ 9.33."""
    from lifecycle_buy_candidates import normalize_base_score
    snap = {"setup": "TREND_OK", "score": 6, "score_track": "drift"}
    result = normalize_base_score(snap)
    assert abs(result - (6 * 14 / 9)) < 0.01


def test_normalize_base_score_extended_uses_raw_score():
    """EXTENDED veto → _raw_score scaled drift→trigger."""
    from lifecycle_buy_candidates import normalize_base_score
    snap = {"setup": "EXTENDED", "score": None, "_raw_score": 5,
            "_raw_score_track": "drift"}
    result = normalize_base_score(snap)
    assert abs(result - (5 * 14 / 9)) < 0.01


def test_normalize_base_score_missing_returns_zero():
    """No score available → 0."""
    from lifecycle_buy_candidates import normalize_base_score
    assert normalize_base_score({"setup": "TREND_OK", "score": None,
                                   "_raw_score": None}) == 0.0
    assert normalize_base_score({}) == 0.0
