# lifecycle_score_config.py
"""Score engine v1 — weights, thresholds, sizes, string constants.

See docs/superpowers/specs/2026-05-13-lifecycle-probabilistic-engine-design.md
for the rationale behind each value. Calibration phase (Phase 4) is the
expected place to tune weights and thresholds based on live data.
"""

ENGINE_VERSION = "score_v1"

# ── String constants (avoid typo drift across modules) ──
TRACK_TRIGGER = "trigger"
TRACK_DRIFT   = "drift"

DECISION_ENTER    = "ENTER"
DECISION_PROBE    = "PROBE"
DECISION_WATCH    = "WATCH"
DECISION_TRENDING = "TRENDING"
DECISION_AVOID    = "AVOID"

BADGE_PROBE_STRONG = "PROBE_STRONG"

VETO_FAILED_BREAKOUT = "FAILED_BREAKOUT"
VETO_BROKEN          = "BROKEN"
VETO_EXTENDED        = "EXTENDED"
VETO_UNKNOWN_SETUP   = "UNKNOWN_SETUP"

# Engine modes — selected via LIFECYCLE_ENGINE_MODE env var.
MODE_LEGACY        = "legacy"        # Phase A boolean path (rollback target)
MODE_SCORE_SHADOW  = "score_shadow"  # Scores computed/stored; decision from Phase A
MODE_SCORE_ACTIVE  = "score_active"  # Score-driven decisions

# Default mode for this PR (PR#2 = score_active). PR#3 keeps this and flips DRIFT_TRACK_ACTIVE.
DEFAULT_ENGINE_MODE = MODE_SCORE_ACTIVE   # PR#2 — score_active is new default

# IMPORTANT — Component ordering invariant:
# `score_components[]` lists in the history JSON MUST follow the iteration
# order of the dict below. UI rendering, analytics diffs, and snapshot
# comparison all assume this stable order. Renaming or reordering keys
# constitutes a schema-breaking change (bump ENGINE_VERSION).
TRIGGER_WEIGHTS = {
    "ema_reclaim":       2,  # Phase A arm 1 reused; matches existing semantics
    "higher_low":        2,  # Institutional accumulation signal
    "rs_strong":         2,  # vs market (SPY/KS200), key leader filter
    "lower_wick":        1,  # Buy support with strong close
    "tight_range":       1,  # ATR-relative compression
    "vol_expansion":     2,  # Phase A confirm threshold (1.2x) reused
    "breakout":          2,  # 20d prior high (close-based, not wick)
    "close_strong":      1,  # Upper 50% (relaxed from Phase A 0.8/upper 20%)
    "intraday_reversal": 1,  # Weak open → strong close
}

DRIFT_WEIGHTS = {
    "ema_alignment":       1,  # ema9>21>65 (already true via TREND_OK; explicit)
    "close_above_ema9":    1,  # Riding the fast line
    "higher_low":          2,  # Same predicate as trigger; shared semantics
    "atr_contraction":     1,  # 5d avg ATR% < 20d avg ATR%
    "rs_strong":           2,  # vs market; key drift indicator
    "low_vol_drift":       1,  # ATR% < 0.8 × 20d avg
    "tight_close_cluster": 1,  # 3-day close range / atr14 < 0.5
}

# Decision thresholds — see spec §7.1
THRESHOLDS = {
    "trigger_probe":  3,
    "trigger_enter":  7,
    "drift_probe":    4,
    "drift_enter":    6,
}

# Track activation — flipped progressively across PRs:
#   PR#1: both False  (scores computed but decisions still from Phase A in shadow mode)
#   PR#2: TRIGGER True, DRIFT False  (PULLBACK/BASE_FORMING decisions from score)
#   PR#3: both True   (TREND_OK PROBE/PROBE_STRONG from drift_score)
TRIGGER_TRACK_ACTIVE = True    # PR#2 — trigger track active
DRIFT_TRACK_ACTIVE   = True    # PR#3 — drift track active (TREND_OK → PROBE)

# Drift never auto-promotes to ENTER until Phase 4 calibration validates.
DRIFT_ALLOW_ENTER = False

# Component sub-thresholds — externalized for calibration tuning.
LOWER_WICK_MIN_RATIO    = 0.4   # (min(open, close) - low) / range
CLOSE_STRONG_MIN_RATIO  = 0.5   # (close - low) / range — upper 50%
TIGHT_RANGE_MAX_ATR     = 0.7   # (high - low) / atr14
VOL_EXPANSION_MIN_RATIO = 1.2   # volume / 20d avg
LOW_VOL_DRIFT_RATIO     = 0.8   # atr14_pct / 20d avg
TIGHT_CLUSTER_MAX_ATR   = 0.5   # 3d close range / atr14

# Market benchmark cache — see spec §8.2
MARKET_BENCHMARK_CACHE_MAX_AGE_DAYS = 3
US_BENCHMARK_TICKER = "SPY"
KR_BENCHMARK_TICKER = "069500.KS"  # KODEX 200 ETF

# Sizing hints — display-only, never auto-executed. See spec §7.2
SIZE_TIERS = {
    "core":         {"size_pct": 0.35, "range": (0.30, 0.40)},
    "starter_plus": {"size_pct": 0.25, "range": (0.25, 0.30)},  # PROBE_STRONG (badge carries conviction)
    "starter":      {"size_pct": 0.25, "range": (0.20, 0.30)},
    None:           {"size_pct": 0.0,  "range": (0.0, 0.0)},
}

DECISION_TO_TIER = {
    (DECISION_ENTER,    None):               "core",
    (DECISION_PROBE,    BADGE_PROBE_STRONG): "starter_plus",
    (DECISION_PROBE,    None):               "starter",
    (DECISION_WATCH,    None):               None,
    (DECISION_TRENDING, None):               None,
    (DECISION_AVOID,    None):               None,
}
