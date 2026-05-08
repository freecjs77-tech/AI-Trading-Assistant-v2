# tests/test_lifecycle_signal.py
"""Phase A — pure-function unit tests for lifecycle_signal."""
import pytest

from lifecycle_signal import evaluate_setup_state


def _raw(**overrides):
    """Build a 'today' raw dict with sensible defaults for a TREND_OK ticker.

    close is set 5% above ema9 so that the distance is clearly outside the
    3% PULLBACK zone — keeping the default firmly in TREND_OK territory.
    Tests that need PULLBACK / EXTENDED / BROKEN values override explicitly.
    """
    base = {
        "close": 104.5,   # ~5% above ema9=99.5, well outside 3% PULLBACK zone
        "high":  105.5,
        "low":   103.5,
        "ema9":   99.5,
        "ema21":  98.0,
        "ema65":  90.0,
        "ema21_slope_5d": 0.5,
        "ema65_slope_5d": 0.4,
        "rsi14":  60.0,
        "atr14_pct":      2.0,
        "volume_ratio":   1.0,
        # Aux fields for BASE_FORMING — provided by lifecycle_signal helpers.
        "days_sideways":           0,
        "atr14_pct_5d_avg":        2.0,
        "atr14_pct_20d_avg":       2.0,
        "volume_5d_avg":     1_000_000,
        "volume_20d_avg":    1_000_000,
    }
    base.update(overrides)
    return base


def test_trend_ok_default():
    assert evaluate_setup_state(_raw()) == "TREND_OK"


def test_pullback_within_3pct_of_ema9():
    raw = _raw(close=99.7, ema9=100.0, ema21=98.0)  # 0.3% below ema9, above ema21
    assert evaluate_setup_state(raw) == "PULLBACK"


def test_pullback_above_ema9_also_qualifies():
    raw = _raw(close=100.5, ema9=100.0, ema21=98.0)  # 0.5% above ema9
    assert evaluate_setup_state(raw) == "PULLBACK"


def test_base_forming_compression():
    raw = _raw(
        days_sideways=8,
        atr14_pct_5d_avg=1.5, atr14_pct_20d_avg=2.0,
        volume_5d_avg=800_000, volume_20d_avg=1_000_000,
        ema21_slope_5d=0.3,
    )
    assert evaluate_setup_state(raw) == "BASE_FORMING"


def test_base_forming_rejects_dead_sideways():
    # ema21 slope flat — compression-ish but trend is dead.
    raw = _raw(
        days_sideways=8,
        atr14_pct_5d_avg=1.5, atr14_pct_20d_avg=2.0,
        volume_5d_avg=800_000, volume_20d_avg=1_000_000,
        ema21_slope_5d=-0.1,
    )
    assert evaluate_setup_state(raw) == "TREND_OK"


def test_extended_distance_and_rsi_required():
    # >12% above ema9 AND rsi > 72.
    raw = _raw(close=120.0, ema9=100.0, ema21=98.0, rsi14=78)
    assert evaluate_setup_state(raw) == "EXTENDED"


def test_extended_distance_alone_not_sufficient():
    # 13% above EMA9 but RSI 60 — not EXTENDED.
    raw = _raw(close=113.0, ema9=100.0, ema21=98.0, rsi14=60)
    assert evaluate_setup_state(raw) != "EXTENDED"


def test_broken_close_below_ema65():
    raw = _raw(close=85.0, ema9=99.5, ema21=98.0, ema65=90.0)
    assert evaluate_setup_state(raw) == "BROKEN"


def test_broken_ema21_below_ema65():
    raw = _raw(ema21=85.0, ema65=90.0)
    assert evaluate_setup_state(raw) == "BROKEN"


def test_precedence_broken_beats_everything():
    # All EXTENDED conditions met but ema21 < ema65 — BROKEN wins.
    raw = _raw(close=120.0, ema9=100.0, ema21=89.0, ema65=90.0, rsi14=78)
    assert evaluate_setup_state(raw) == "BROKEN"


def test_precedence_extended_beats_pullback():
    # 14% above ema9 AND rsi 78 AND within 3% of ema9? — impossible by
    # definition. Build the legal precedence test: EXTENDED criteria
    # met AND base_forming criteria met -> EXTENDED wins (it sits higher).
    raw = _raw(
        close=120.0, ema9=100.0, ema21=95.0, rsi14=78,
        days_sideways=8,
        atr14_pct_5d_avg=1.5, atr14_pct_20d_avg=2.0,
        volume_5d_avg=800_000, volume_20d_avg=1_000_000,
    )
    assert evaluate_setup_state(raw) == "EXTENDED"


def test_precedence_base_forming_beats_pullback():
    # PULLBACK conditions met AND BASE_FORMING conditions met → BASE_FORMING wins.
    raw = _raw(
        close=99.7, ema9=100.0, ema21=98.0,
        days_sideways=8,
        atr14_pct_5d_avg=1.5, atr14_pct_20d_avg=2.0,
        volume_5d_avg=800_000, volume_20d_avg=1_000_000,
        ema21_slope_5d=0.3,
    )
    assert evaluate_setup_state(raw) == "BASE_FORMING"


def test_close_below_ema21_in_pullback_demoted_to_trend_ok():
    # 2% below ema9 — PULLBACK distance OK — but close < ema21 (PULLBACK
    # rejects this). Should fall through to TREND_OK or, if alignment fails,
    # something else. With our setup the alignment is fine -> TREND_OK.
    raw = _raw(close=97.0, ema9=99.0, ema21=98.5, ema65=90.0)
    # close < ema21 → PULLBACK predicate fails. ema9>ema21>ema65 so TREND_OK.
    assert evaluate_setup_state(raw) == "TREND_OK"
