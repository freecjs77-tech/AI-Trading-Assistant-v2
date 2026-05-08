# tests/test_lifecycle_config.py
"""Phase A lifecycle config — sanity + rationale gate."""
import importlib
import re
from pathlib import Path

import lifecycle_config as cfg


def test_version_present():
    assert cfg.LIFECYCLE_VERSION.startswith("lifecycle_phase_a/")


def test_ema_windows_strictly_ordered():
    assert cfg.EMA_FAST < cfg.EMA_MEDIUM < cfg.EMA_LONG
    assert cfg.EMA_LONG_SLOPE_WINDOW > 0
    assert cfg.EMA_MEDIUM_SLOPE_WINDOW > 0


def test_pullback_distance_in_range():
    assert 0 < cfg.PULLBACK_MAX_DIST_FROM_EMA9 < 0.10


def test_base_forming_window():
    assert cfg.BASE_FORMING_DAYS_MIN >= 3
    assert cfg.BASE_FORMING_DAYS_MAX > cfg.BASE_FORMING_DAYS_MIN
    assert 0 < cfg.BASE_RANGE_MAX_PCT < 0.20
    assert 0 < cfg.BASE_VOL_CONTRACTION_RATIO < 1.0


def test_extended_thresholds():
    assert cfg.EXTENDED_DIST_FROM_EMA9 > cfg.PULLBACK_MAX_DIST_FROM_EMA9
    assert 70 <= cfg.EXTENDED_RSI_MIN <= 80


def test_trigger_thresholds():
    assert cfg.TRIGGER_CONFIRM_VOL_RATIO_MIN >= 1.0
    assert 0.5 < cfg.TRIGGER_CONFIRM_CLOSE_HIGH_RATIO < 1.0


def test_failed_breakout_default_loose():
    assert cfg.FAILED_BREAKOUT_REQUIRE_BELOW_PRIOR_LOW is False


def test_active_set_lookbacks():
    assert cfg.ACTIVE_M123_LOOKBACK_DAYS > 0
    assert cfg.ACTIVE_NONBROKEN_LOOKBACK_DAYS > 0


def test_risk_tag_thresholds():
    assert 75 <= cfg.RISK_OVERHEAT_RSI <= 90
    assert 0.05 < cfg.RISK_PARABOLIC_RET_1D < 0.20
    assert cfg.RISK_PARABOLIC_VOL_RATIO >= 1.5


# This is the rationale gate — every numeric threshold MUST have at least one
# comment line within 5 lines above its definition. If you change a threshold
# without explaining why, this test fails.
THRESHOLD_NAMES = [
    "EMA_FAST", "EMA_MEDIUM", "EMA_LONG",
    "EMA_LONG_SLOPE_WINDOW", "EMA_MEDIUM_SLOPE_WINDOW",
    "PULLBACK_MAX_DIST_FROM_EMA9",
    "BASE_FORMING_DAYS_MIN", "BASE_FORMING_DAYS_MAX",
    "BASE_RANGE_MAX_PCT", "BASE_VOL_CONTRACTION_RATIO",
    "EXTENDED_DIST_FROM_EMA9", "EXTENDED_RSI_MIN",
    "TRIGGER_CONFIRM_VOL_RATIO_MIN", "TRIGGER_CONFIRM_CLOSE_HIGH_RATIO",
    "FAILED_BREAKOUT_REQUIRE_BELOW_PRIOR_LOW",
    "ACTIVE_M123_LOOKBACK_DAYS", "ACTIVE_NONBROKEN_LOOKBACK_DAYS",
    "RISK_OVERHEAT_RSI", "RISK_PARABOLIC_RET_1D", "RISK_PARABOLIC_VOL_RATIO",
]


def test_every_threshold_has_rationale_comment():
    src = Path(__file__).resolve().parents[1] / "lifecycle_config.py"
    lines = src.read_text(encoding="utf-8").splitlines()
    missing = []
    for name in THRESHOLD_NAMES:
        idx = next((i for i, l in enumerate(lines)
                    if re.match(rf"^{name}\s*=", l)), None)
        assert idx is not None, f"{name} not found in lifecycle_config.py"
        window = lines[max(0, idx - 5):idx]
        if not any(l.lstrip().startswith("#") for l in window):
            missing.append(name)
    assert not missing, f"thresholds missing rationale comments: {missing}"
