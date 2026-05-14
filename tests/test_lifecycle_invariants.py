# tests/test_lifecycle_invariants.py
"""score_v1 CRITICAL invariants — safety contracts that must hold across all engine modes.

These tests are continuous-enforcement guardrails. Any failure here is a code bug.
Mitigation: flip LIFECYCLE_ENGINE_MODE=legacy immediately (see spec §14 Risk #4).
"""
import os
from unittest.mock import patch

import pytest

from lifecycle_signal import (
    evaluate_decision, hard_risk_veto, _derive_legacy_trigger_state,
    _evaluate_decision_score,
)
from lifecycle_score import compute_trigger_score, compute_drift_score


def _today(**overrides):
    base = {
        "open": 100.0, "close": 101.0, "high": 102.0, "low": 99.0,
        "ema9": 100.0, "ema21": 98.0, "ema65": 90.0,
        "atr14": 2.0, "atr14_pct": 2.0,
        "atr14_pct_5d_avg": 2.0, "atr14_pct_20d_avg": 2.0,
        "volume_ratio": 1.0, "high_20d_prior": 105.0,
        "change_5d_pct": 0.0,
    }
    base.update(overrides)
    return base


def _yesterday(**overrides):
    base = {"close": 99.0, "low": 98.0, "high": 100.0, "ema9": 99.5}
    base.update(overrides)
    return base


# ──────────────────────────────────────────────────────────────────
# Invariant Group A: Hard veto integrity
# ──────────────────────────────────────────────────────────────────


def test_invariant_failed_breakout_always_avoid_legacy():
    with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": "legacy"}):
        for setup in ("PULLBACK", "BASE_FORMING", "TREND_OK", "EXTENDED", "BROKEN"):
            result = evaluate_decision(setup, "CONFIRMED_TRIGGER",
                                       risk_tags=["FAILED_BREAKOUT"])
            assert result == "AVOID", f"setup={setup} broke FAILED_BREAKOUT invariant"


def test_invariant_failed_breakout_always_avoid_score_active():
    today_raw = _today(close=110, volume_ratio=2.0, high_20d_prior=105)
    yesterday = _yesterday(close=99)
    with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": "score_active"}):
        for setup in ("PULLBACK", "BASE_FORMING", "TREND_OK", "EXTENDED", "BROKEN"):
            result = evaluate_decision(setup, "CONFIRMED_TRIGGER",
                                       risk_tags=["FAILED_BREAKOUT"],
                                       today_raw=today_raw,
                                       yesterday_snap=yesterday,
                                       market_ret_5d_pct=0.0)
            assert isinstance(result, dict)
            assert result["decision"] == "AVOID"
            assert result["veto_reason"] == "FAILED_BREAKOUT"


def test_invariant_broken_setup_always_avoid_both_modes():
    today_raw = _today(close=110)
    for mode in ("legacy", "score_active"):
        with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": mode}):
            kwargs = {"risk_tags": []}
            if mode == "score_active":
                kwargs.update({"today_raw": today_raw, "yesterday_snap": _yesterday(),
                               "market_ret_5d_pct": 0.0})
            result = evaluate_decision("BROKEN", "WAIT", **kwargs)
            dec = result["decision"] if isinstance(result, dict) else result
            assert dec == "AVOID", f"mode={mode}: BROKEN failed AVOID invariant"


def test_invariant_extended_setup_always_avoid_both_modes():
    today_raw = _today(close=110)
    for mode in ("legacy", "score_active"):
        with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": mode}):
            kwargs = {"risk_tags": ["EXTENDED"]}
            if mode == "score_active":
                kwargs.update({"today_raw": today_raw, "yesterday_snap": _yesterday(),
                               "market_ret_5d_pct": 0.0})
            result = evaluate_decision("EXTENDED", "WAIT", **kwargs)
            dec = result["decision"] if isinstance(result, dict) else result
            assert dec == "AVOID", f"mode={mode}: EXTENDED failed AVOID invariant"


# ──────────────────────────────────────────────────────────────────
# Invariant Group B: AVOID output integrity (score_active path)
# ──────────────────────────────────────────────────────────────────


def test_invariant_avoid_has_null_public_score():
    today_raw = _today(close=130, volume_ratio=2.0)
    with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": "score_active"}):
        result = evaluate_decision("EXTENDED", "WAIT", risk_tags=["EXTENDED"],
                                   today_raw=today_raw, yesterday_snap=_yesterday(),
                                   market_ret_5d_pct=0.0)
    assert result["decision"] == "AVOID"
    assert result["score"] is None
    assert result["features"] is None
    assert result["score_components"] is None
    assert result["active_components"] is None


def test_invariant_avoid_preserves_internal_raw_score_for_analytics():
    today_raw = _today(close=130, volume_ratio=2.0, high_20d_prior=105,
                       change_5d_pct=5.0)
    with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": "score_active"}):
        result = evaluate_decision("EXTENDED", "WAIT", risk_tags=["EXTENDED"],
                                   today_raw=today_raw, yesterday_snap=_yesterday(),
                                   market_ret_5d_pct=1.0)
    # _raw_* fields preserved for calibration analytics
    assert result["_raw_score"] is not None
    assert result["_raw_features"] is not None
    assert result["_raw_score_track"] in ("trigger", "drift")


# ──────────────────────────────────────────────────────────────────
# Invariant Group C: Score consistency
# ──────────────────────────────────────────────────────────────────


def test_invariant_score_components_sum_equals_score():
    """Sum of active component weights MUST equal reported score."""
    today = _today(close=110, ema9=100, low=99, high=111, volume_ratio=1.5,
                   high_20d_prior=105, open=109, change_5d_pct=5.0)
    yesterday = _yesterday(close=99, low=98)
    res = compute_trigger_score(today, yesterday, market_ret_5d_pct=1.0)
    expected = sum(c["weight"] for c in res.components_list if c["active"])
    assert res.score == expected


def test_invariant_active_components_matches_features_true_count():
    today = _today(close=110, high=111, low=109, volume_ratio=1.5,
                   high_20d_prior=105, change_5d_pct=5.0)
    res = compute_trigger_score(today, _yesterday(close=99, low=98), market_ret_5d_pct=1.0)
    assert res.active_count == sum(1 for v in res.features.values() if v)


def test_invariant_components_list_order_matches_config():
    from lifecycle_score_config import TRIGGER_WEIGHTS, DRIFT_WEIGHTS

    t = compute_trigger_score(_today(), _yesterday(), market_ret_5d_pct=0.0)
    assert [c["name"] for c in t.components_list] == list(TRIGGER_WEIGHTS.keys())

    d = compute_drift_score(_today(), _yesterday(),
                            recent_3d_closes=[100, 100.3, 100.5],
                            market_ret_5d_pct=0.0)
    assert [c["name"] for c in d.components_list] == list(DRIFT_WEIGHTS.keys())


# ──────────────────────────────────────────────────────────────────
# Invariant Group D: Drift safety
# ──────────────────────────────────────────────────────────────────


def test_invariant_drift_never_enter_when_disabled():
    """DRIFT_ALLOW_ENTER = False → no drift_score level ever produces ENTER."""
    import lifecycle_score_config as cfg
    assert cfg.DRIFT_ALLOW_ENTER is False

    today_raw = _today(close=101, ema9=100, ema21=98, ema65=90,
                       atr14_pct_5d_avg=1.0, atr14_pct_20d_avg=2.0,
                       atr14_pct=1.0, change_5d_pct=5.0)
    yesterday = _yesterday(close=99, low=98)
    with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": "score_active"}):
        # Force DRIFT_TRACK_ACTIVE for this test
        with patch.object(cfg, "DRIFT_TRACK_ACTIVE", True):
            result = evaluate_decision("TREND_OK", "WAIT", risk_tags=[],
                                       today_raw=today_raw,
                                       yesterday_snap=yesterday,
                                       recent_3d_closes=[100, 100.3, 100.5],
                                       market_ret_5d_pct=1.0)
            assert result["decision"] != "ENTER"
            # Strong drift may emit PROBE+PROBE_STRONG, never ENTER.
            assert isinstance(result["decision_badges"], list)


# ──────────────────────────────────────────────────────────────────
# Invariant Group E: Sizing safety
# ──────────────────────────────────────────────────────────────────


def test_invariant_suggested_size_zero_for_non_actionable():
    # AVOID, WATCH, TRENDING are all non-actionable; none should carry sizing.
    # PR#3: DRIFT_TRACK_ACTIVE=True — use data with inverted EMA alignment so
    # drift_score stays below drift_probe threshold → TREND_OK → TRENDING (size=0).
    today_bad_drift = _today(
        close=97.0, high=100.0, low=96.0,
        ema9=98.0, ema21=99.0, ema65=100.0,   # inverted alignment → ema_alignment False
    )
    yesterday_bad_drift = _yesterday(close=98.0, low=97.0, high=99.0)  # close>today → no higher_low
    with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": "score_active"}):
        result = evaluate_decision("TREND_OK", "WAIT", risk_tags=[],
                                   today_raw=today_bad_drift,
                                   yesterday_snap=yesterday_bad_drift,
                                   market_ret_5d_pct=0.0)
    assert result["decision"] == "TRENDING", (
        f"Expected TRENDING (drift_score<threshold), got {result['decision']} "
        f"(score={result.get('score')})"
    )
    assert result["suggested_size_pct"] == 0.0
    assert result["suggested_entry_tier"] is None


def test_invariant_legacy_trigger_state_consistent_with_score():
    """Derived trigger_state must align with score thresholds."""
    from lifecycle_score_config import THRESHOLDS
    assert _derive_legacy_trigger_state(None, None) == "WAIT"
    assert _derive_legacy_trigger_state(THRESHOLDS["trigger_enter"], "trigger") == "CONFIRMED_TRIGGER"
    assert _derive_legacy_trigger_state(THRESHOLDS["trigger_probe"], "trigger") == "EARLY_TRIGGER"
    assert _derive_legacy_trigger_state(THRESHOLDS["trigger_probe"] - 1, "trigger") == "WAIT"
    # Drift never CONFIRMED
    assert _derive_legacy_trigger_state(9, "drift") == "EARLY_TRIGGER"


# ──────────────────────────────────────────────────────────────────
# Invariant Group F: Tier integrity (spec §7)
# ──────────────────────────────────────────────────────────────────


def test_invariant_score_tier_exhaustive():
    """score_tier must be in {WEAK, MID, STRONG, None} across all paths."""
    import lifecycle_score_config as cfg
    valid = {"WEAK", "MID", "STRONG", None}
    today_raw = _today(close=110, ema9=100, low=99.5, change_5d_pct=5.0)
    yesterday = _yesterday(close=99, low=98)

    with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": "score_active"}):
        # Patch both tracks active so we exercise the full grid
        with patch.object(cfg, "TRIGGER_TRACK_ACTIVE", True), \
             patch.object(cfg, "DRIFT_TRACK_ACTIVE", True):
            for setup in ("PULLBACK", "BASE_FORMING", "TREND_OK"):
                result = evaluate_decision(setup, "WAIT", risk_tags=[],
                                           today_raw=today_raw, yesterday_snap=yesterday,
                                           recent_3d_closes=[109, 110, 110.5],
                                           market_ret_5d_pct=1.0)
                assert result.get("score_tier") in valid, (
                    f"setup={setup}: score_tier={result.get('score_tier')} not in {valid}"
                )


def test_invariant_score_tier_band_membership():
    """When score_tier is non-null, the score must fall within that band."""
    import lifecycle_score_config as cfg
    from lifecycle_score import compute_score_tier

    # trigger track at each tier
    for score_target, expected_tier in [(3, "WEAK"), (4, "MID"), (5, "MID"), (6, "STRONG")]:
        actual_tier = compute_score_tier(score_target, "trigger")
        if actual_tier is not None:
            lo, hi = cfg.SCORE_TIER_BANDS["trigger"][actual_tier]
            assert lo <= score_target <= hi
            assert actual_tier == expected_tier

    # drift track at each tier
    for score_target, expected_tier in [(4, "WEAK"), (5, "MID"), (6, "STRONG"), (9, "STRONG")]:
        actual_tier = compute_score_tier(score_target, "drift")
        if actual_tier is not None:
            lo, hi = cfg.SCORE_TIER_BANDS["drift"][actual_tier]
            assert lo <= score_target <= hi
            assert actual_tier == expected_tier


def test_invariant_drift_strong_implies_probe_strong_badge():
    """Spec §3.4: score_tier='STRONG' AND track='drift' → 'PROBE_STRONG' in decision_badges."""
    import lifecycle_score_config as cfg
    # Construct inputs producing drift score >= 6
    today_raw = _today(close=101, ema9=100, ema21=98, ema65=90,
                       atr14_pct=1.0, atr14_pct_5d_avg=1.0, atr14_pct_20d_avg=2.0,
                       atr14=2.0, change_5d_pct=5.0)
    yesterday = _yesterday(close=99, low=98)
    with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": "score_active"}), \
         patch.object(cfg, "DRIFT_TRACK_ACTIVE", True):
        result = evaluate_decision("TREND_OK", "WAIT", risk_tags=[],
                                   today_raw=today_raw, yesterday_snap=yesterday,
                                   recent_3d_closes=[100.5, 101.0, 101.0],
                                   market_ret_5d_pct=1.0)
        if result.get("score_tier") == "STRONG" and result.get("score_track") == "drift":
            assert "PROBE_STRONG" in result.get("decision_badges", []), (
                f"drift STRONG must imply PROBE_STRONG badge; got decision_badges="
                f"{result.get('decision_badges')}"
            )


def test_invariant_rs_tier_threshold_consistency():
    """rs_tier matches band semantics."""
    from lifecycle_score import compute_rs_tier
    # STRONG ≥ 10
    assert compute_rs_tier(10.0) == "STRONG"
    assert compute_rs_tier(99.0) == "STRONG"
    # MID [5, 10)
    assert compute_rs_tier(5.0) == "MID"
    assert compute_rs_tier(9.99) == "MID"
    # WEAK [0, 5)
    assert compute_rs_tier(0.0) == "WEAK"
    assert compute_rs_tier(4.99) == "WEAK"
    # Below 0 → None
    assert compute_rs_tier(-0.01) is None
    assert compute_rs_tier(-100.0) is None


def test_invariant_rs_tier_null_when_no_market_data():
    """rs_delta_pct=None → rs_tier=None (no market benchmark)."""
    from lifecycle_score import compute_rs_tier
    assert compute_rs_tier(None) is None
