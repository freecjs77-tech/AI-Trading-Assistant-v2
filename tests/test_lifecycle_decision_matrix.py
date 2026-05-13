# tests/test_lifecycle_decision_matrix.py
"""score_v1 — exhaustive (setup_state × score) → decision tabulation.

Locks in spec §7.1 decision matrix. Any unexpected matrix change should
require explicit spec update + this test update — never silent.
"""
import os
from unittest.mock import patch

import pytest

import lifecycle_score_config as cfg
from lifecycle_signal import evaluate_decision


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


@pytest.fixture
def score_active_with_tracks_on():
    """Activate score_active mode + both tracks for matrix tests."""
    with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": "score_active"}), \
         patch.object(cfg, "TRIGGER_TRACK_ACTIVE", True), \
         patch.object(cfg, "DRIFT_TRACK_ACTIVE", True):
        yield


# ── PULLBACK × score → decision ───────────────────────────────────


def test_matrix_pullback_score_7_enter(score_active_with_tracks_on):
    """Trigger ENTER threshold.

    Active components: ema_reclaim(2) + higher_low(2) + rs_strong(2)
                       + breakout(2) + close_strong(1) + intraday_reversal(1) = 10
    """
    # Build today with 10 active points:
    #   ema_reclaim: yesterday.close(99) <= ema9(100) < today.close(110) → True (+2)
    #   higher_low: today.low(99.5) > yesterday.low(98) → True (+2)
    #   rs_strong: change_5d_pct(5.0) > market_ret_5d_pct(1.0) → True (+2)
    #   lower_wick: wick=(min(open=100,close=110)-low=99.5)=0.5; range=11; 0.5/11 < 0.4 → False
    #   tight_range: (110.5-99.5)/atr14(2.0)=5.5 > 0.7 → False
    #   vol_expansion: volume_ratio(1.0) < 1.2 → False
    #   breakout: close(110) > high_20d_prior(105) → True (+2)
    #   close_strong: (110-99.5)/(110.5-99.5)=10.5/11≈0.955 → True (+1)
    #   intraday_reversal: low(99.5) < open(100) AND close(110) > open(100) → True (+1)
    today = _today(close=110, ema9=100, low=99.5, high=110.5,
                   change_5d_pct=5.0)
    yesterday = _yesterday(close=99, low=98)
    result = evaluate_decision("PULLBACK", "CONFIRMED_TRIGGER", risk_tags=[],
                                today_raw=today, yesterday_snap=yesterday,
                                market_ret_5d_pct=1.0)
    assert result["score"] >= 7
    assert result["decision"] == "ENTER"


def test_matrix_pullback_score_3_to_6_probe(score_active_with_tracks_on):
    """Trigger PROBE band [3, 6].

    Active components: ema_reclaim(2) + higher_low(2) + close_strong(1) = 5
    lower_wick and intraday_reversal fail because open(101.5) > close(101).
    """
    # Build for ~5 active points:
    #   ema_reclaim: yesterday.close(99) <= ema9(100) < today.close(101) → True (+2)
    #   higher_low: today.low(99) > yesterday.low(98) → True (+2)
    #   rs_strong: change_5d_pct(0.0) == market_ret_5d_pct(0.0) → False (not strictly >)
    #   lower_wick: close(101) < open(101.5) → condition c >= o fails → False
    #   tight_range: (101.5-99)/2.0=1.25 > 0.7 → False
    #   vol_expansion: volume_ratio(1.0) < 1.2 → False
    #   breakout: close(101) > high_20d_prior(110) → False
    #   close_strong: (101-99)/(101.5-99)=2/2.5=0.8 >= 0.5 → True (+1)
    #   intraday_reversal: close(101) > open(101.5)? No → False
    today = _today(open=101.5, close=101, ema9=100, low=99, high=101.5,
                   change_5d_pct=0.0, volume_ratio=1.0,
                   high_20d_prior=110)
    yesterday = _yesterday(close=99, low=98)
    result = evaluate_decision("PULLBACK", "EARLY_TRIGGER", risk_tags=[],
                                today_raw=today, yesterday_snap=yesterday,
                                market_ret_5d_pct=0.0)
    assert 3 <= result["score"] <= 6
    assert result["decision"] == "PROBE"


def test_matrix_pullback_score_below_3_watch(score_active_with_tracks_on):
    """Score < 3 → WATCH.

    Active components: close_strong(1) only = 1
    ema_reclaim fails (close=99 <= ema9=100), higher_low fails (today.low=98 <= yesterday.low=99).
    """
    # close(99) <= ema9(100) → ema_reclaim False
    # today.low(98) vs yesterday.low(99): 98 > 99? No → higher_low False
    # rs_strong: -2.0 > 2.0? No → False
    # lower_wick: close(99) < open(100) → c >= o fails → False
    # tight_range: (99.5-98)/2.0=0.75 > 0.7 → False
    # vol_expansion: 0.5 < 1.2 → False
    # breakout: 99 > 110? No → False
    # close_strong: (99-98)/(99.5-98)=1/1.5≈0.667 >= 0.5 → True (+1)
    # intraday_reversal: close(99) > open(100)? No → False
    today = _today(close=99, ema9=100, low=98, high=99.5,
                   change_5d_pct=-2.0, volume_ratio=0.5,
                   high_20d_prior=110)
    yesterday = _yesterday(close=99, low=99)  # today.low(98) > 99? No → higher_low False
    result = evaluate_decision("PULLBACK", "WAIT", risk_tags=[],
                                today_raw=today, yesterday_snap=yesterday,
                                market_ret_5d_pct=2.0)
    assert result["score"] < 3
    assert result["decision"] == "WATCH"


# ── BASE_FORMING shares trigger track ─────────────────────────────


def test_matrix_base_forming_uses_trigger_track(score_active_with_tracks_on):
    today = _today(close=110, ema9=100, change_5d_pct=5.0,
                   atr14_pct_5d_avg=1.5, atr14_pct_20d_avg=2.0,
                   volume_5d_avg=800_000, volume_20d_avg=1_000_000)
    yesterday = _yesterday(close=99, low=98)
    result = evaluate_decision("BASE_FORMING", "CONFIRMED_TRIGGER", risk_tags=[],
                                today_raw=today, yesterday_snap=yesterday,
                                market_ret_5d_pct=1.0)
    assert result["score_track"] == "trigger"


# ── TREND_OK × drift_score → decision ─────────────────────────────


def test_matrix_trend_ok_drift_above_6_probe_strong(score_active_with_tracks_on):
    """Drift >= 6 → PROBE with PROBE_STRONG badge (drift ENTER disabled).

    Active components: ema_alignment(1) + close_above_ema9(1) + higher_low(2)
                       + atr_contraction(1) + rs_strong(2) + low_vol_drift(1)
                       + tight_close_cluster(1) = 9
    """
    # ema_alignment: 100>98>90 → True (+1)
    # close_above_ema9: 105 > 100 → True (+1)
    # higher_low: today.low(99,default) > yesterday.low(98) → True (+2)
    # atr_contraction: atr14_pct_5d_avg(1.0) < atr14_pct_20d_avg(2.0) → True (+1)
    # rs_strong: change_5d_pct(5.0) > market_ret_5d_pct(1.0) → True (+2)
    # low_vol_drift: atr14_pct(1.0) < 0.8*2.0=1.6 → True (+1)
    # tight_close_cluster: spread=0.4/atr14=2.0=0.2 < 0.5 → True (+1)
    today = _today(close=105, ema9=100, ema21=98, ema65=90,
                   atr14_pct=1.0, atr14_pct_5d_avg=1.0, atr14_pct_20d_avg=2.0,
                   atr14=2.0, change_5d_pct=5.0)
    yesterday = _yesterday(close=99, low=98)
    result = evaluate_decision("TREND_OK", "WAIT", risk_tags=[],
                                today_raw=today, yesterday_snap=yesterday,
                                recent_3d_closes=[104.8, 105.0, 105.2],
                                market_ret_5d_pct=1.0)
    assert result["score"] >= 6
    assert result["decision"] == "PROBE"
    assert "PROBE_STRONG" in result["decision_badges"]
    assert result["suggested_entry_tier"] == "starter_plus"


def test_matrix_trend_ok_drift_4_to_5_probe(score_active_with_tracks_on):
    """Drift score in [4, 5] → PROBE without PROBE_STRONG badge.

    Active components: ema_alignment(1) + close_above_ema9(1) + higher_low(2)
                       + atr_contraction(1) = 5
    rs_strong fails (change_5d_pct=0.5 <= market_ret=1.0).
    low_vol_drift fails (atr14_pct=1.7 >= 0.8*2.0=1.6).
    tight_close_cluster fails (spread=2.0/atr14=2.0=1.0 >= 0.5).
    """
    # ema_alignment: 100>98>90 → True (+1)
    # close_above_ema9: 101 > 100 → True (+1)
    # higher_low: today.low(99,default) > yesterday.low(98) → True (+2)
    # atr_contraction: 1.5 < 2.0 → True (+1)
    # rs_strong: 0.5 > 1.0? No → False
    # low_vol_drift: 1.7 < 0.8*2.0=1.6? No → False
    # tight_close_cluster: spread=|101-99|=2.0; atr14=2.0; 1.0 >= 0.5 → False
    today = _today(close=101, ema9=100, ema21=98, ema65=90,
                   atr14_pct=1.7, atr14_pct_5d_avg=1.5, atr14_pct_20d_avg=2.0,
                   atr14=2.0, change_5d_pct=0.5)
    yesterday = _yesterday(close=99, low=98)
    result = evaluate_decision("TREND_OK", "WAIT", risk_tags=[],
                                today_raw=today, yesterday_snap=yesterday,
                                recent_3d_closes=[99.0, 101.0, 101.0],
                                market_ret_5d_pct=1.0)
    assert 4 <= result["score"] <= 5
    assert result["decision"] == "PROBE"
    assert "PROBE_STRONG" not in result["decision_badges"]


def test_matrix_trend_ok_drift_below_4_trending(score_active_with_tracks_on):
    """Drift score < 4 → TRENDING.

    Active components: ema_alignment(1) + close_above_ema9(1) + tight_close_cluster(1) = 3
    higher_low fails (today.low=99 vs yesterday.low=100 → 99 > 100? No).
    atr_contraction fails (5d_avg == 20d_avg).
    rs_strong fails (change_5d_pct=-1.0 < market_ret=2.0).
    low_vol_drift fails (atr14_pct=2.0 >= 0.8*2.0=1.6).
    """
    # today.low = 99 (default from _today), yesterday.low = 100 → higher_low False
    today = _today(close=101, ema9=100, ema21=98, ema65=90,
                   atr14_pct=2.0, atr14_pct_5d_avg=2.0, atr14_pct_20d_avg=2.0,
                   change_5d_pct=-1.0)  # rs_strong fails
    yesterday = _yesterday(close=101.5, low=100)  # higher_low False
    result = evaluate_decision("TREND_OK", "WAIT", risk_tags=[],
                                today_raw=today, yesterday_snap=yesterday,
                                recent_3d_closes=[101.0, 100.8, 101.0],
                                market_ret_5d_pct=2.0)
    assert result["score"] < 4
    assert result["decision"] == "TRENDING"


# ── Veto rows ─────────────────────────────────────────────────────


def test_matrix_extended_setup_avoid(score_active_with_tracks_on):
    today = _today(close=125, ema9=100, rsi14=78)  # dist 25%, RSI 78
    result = evaluate_decision("EXTENDED", "WAIT", risk_tags=["EXTENDED"],
                                today_raw=today, yesterday_snap=_yesterday(),
                                market_ret_5d_pct=1.0)
    assert result["decision"] == "AVOID"
    assert result["veto_reason"] == "EXTENDED"


def test_matrix_broken_setup_avoid(score_active_with_tracks_on):
    today = _today(close=85, ema65=90)  # close < ema65
    result = evaluate_decision("BROKEN", "WAIT", risk_tags=[],
                                today_raw=today, yesterday_snap=_yesterday(),
                                market_ret_5d_pct=0.0)
    assert result["decision"] == "AVOID"
    assert result["veto_reason"] == "BROKEN"


# ── PR#1 behavior: tracks not yet active ─────────────────────────


def test_pr1_default_trigger_track_inactive_means_watch():
    """Without TRIGGER_TRACK_ACTIVE patch, even high score gets WATCH in PR#1."""
    today = _today(close=110, ema9=100, change_5d_pct=5.0)
    yesterday = _yesterday(close=99, low=98)
    with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": "score_active"}):
        # No DRIFT/TRIGGER_TRACK_ACTIVE patches — use PR#1 defaults
        result = evaluate_decision("PULLBACK", "CONFIRMED_TRIGGER", risk_tags=[],
                                    today_raw=today, yesterday_snap=yesterday,
                                    market_ret_5d_pct=1.0)
    assert result["score"] > 0
    assert result["decision"] == "WATCH"  # downgraded since track inactive
