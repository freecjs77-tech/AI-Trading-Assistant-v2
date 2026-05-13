# tests/test_lifecycle_score_config.py
"""score_v1 config — sanity + rationale gate (mirrors test_lifecycle_config.py)."""
import re
from pathlib import Path

import lifecycle_score_config as cfg


def test_engine_version_present():
    assert cfg.ENGINE_VERSION == "score_v1"


def test_default_mode_is_active():
    """PR#2 default = score_active. PR#3 will keep this and flip DRIFT_TRACK_ACTIVE."""
    assert cfg.DEFAULT_ENGINE_MODE == cfg.MODE_SCORE_ACTIVE


def test_track_strings_lowercase():
    assert cfg.TRACK_TRIGGER == "trigger"
    assert cfg.TRACK_DRIFT == "drift"


def test_decision_strings_uppercase():
    for name in ("ENTER", "PROBE", "WATCH", "TRENDING", "AVOID"):
        assert getattr(cfg, f"DECISION_{name}") == name


def test_trigger_weights_sum_to_14():
    """If you change this, also change spec §6.1 'Max points'."""
    assert sum(cfg.TRIGGER_WEIGHTS.values()) == 14


def test_drift_weights_sum_to_9():
    """If you change this, also change spec §6.2 'Max points'."""
    assert sum(cfg.DRIFT_WEIGHTS.values()) == 9


def test_thresholds_make_sense():
    # PROBE threshold strictly less than ENTER threshold
    assert cfg.THRESHOLDS["trigger_probe"] < cfg.THRESHOLDS["trigger_enter"]
    assert cfg.THRESHOLDS["drift_probe"] < cfg.THRESHOLDS["drift_enter"]
    # Thresholds within achievable range
    assert cfg.THRESHOLDS["trigger_enter"] <= sum(cfg.TRIGGER_WEIGHTS.values())
    assert cfg.THRESHOLDS["drift_enter"] <= sum(cfg.DRIFT_WEIGHTS.values())


def test_drift_allow_enter_default_false():
    """Phase 1 conservative default. Calibration may flip."""
    assert cfg.DRIFT_ALLOW_ENTER is False


def test_trigger_track_active_in_pr2():
    """PR#2: trigger track promotes scores to PROBE/ENTER."""
    assert cfg.TRIGGER_TRACK_ACTIVE is True
    assert cfg.DRIFT_TRACK_ACTIVE is False


def test_drift_archetype_separation():
    """Spec §11.1: drift weights must NOT include trigger expansion features."""
    forbidden = {"vol_expansion", "breakout"}
    for name in cfg.DRIFT_WEIGHTS:
        assert name not in forbidden, (
            f"Drift archetype collapse: '{name}' is a trigger feature. "
            f"See spec §11.1 — archetype-collapse guardrail."
        )


def test_size_tiers_present():
    for tier in ("core", "starter_plus", "starter"):
        assert tier in cfg.SIZE_TIERS
        assert 0.0 < cfg.SIZE_TIERS[tier]["size_pct"] <= 0.40


def test_decision_to_tier_complete():
    """Every decision/badge combo maps to a tier (or None for non-actionable)."""
    actionable_combos = [
        (cfg.DECISION_ENTER, None),
        (cfg.DECISION_PROBE, cfg.BADGE_PROBE_STRONG),
        (cfg.DECISION_PROBE, None),
    ]
    for combo in actionable_combos:
        assert cfg.DECISION_TO_TIER[combo] is not None


# Rationale-comment gate — same pattern as test_lifecycle_config.py
THRESHOLD_NAMES = [
    "LOWER_WICK_MIN_RATIO", "CLOSE_STRONG_MIN_RATIO",
    "TIGHT_RANGE_MAX_ATR",  "VOL_EXPANSION_MIN_RATIO",
    "LOW_VOL_DRIFT_RATIO",  "TIGHT_CLUSTER_MAX_ATR",
    "MARKET_BENCHMARK_CACHE_MAX_AGE_DAYS",
]


def test_every_threshold_has_rationale_comment():
    src = Path(__file__).resolve().parents[1] / "lifecycle_score_config.py"
    lines = src.read_text(encoding="utf-8").splitlines()
    missing = []
    for name in THRESHOLD_NAMES:
        idx = next((i for i, l in enumerate(lines)
                    if re.match(rf"^{name}\s*=", l)), None)
        assert idx is not None, f"{name} not found in lifecycle_score_config.py"
        # Look for a # comment within 5 lines above OR inline on same line.
        line_with_value = lines[idx]
        if "#" in line_with_value:
            continue
        window = lines[max(0, idx - 5):idx]
        if not any(l.strip().startswith("#") for l in window):
            missing.append(f"{name}: no rationale comment within 5 lines above")
    assert not missing, "Missing rationale comments:\n" + "\n".join(missing)
