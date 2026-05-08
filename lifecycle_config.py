# lifecycle_config.py
"""Phase A trade-lifecycle thresholds. Single source of truth.

Every numeric threshold below carries a rationale comment within 5 lines
above its definition. The rationale-comment test in
tests/test_lifecycle_config.py enforces this.
"""

LIFECYCLE_VERSION = "lifecycle_phase_a/0.1.0"

# ── EMA structure ──────────────────────────────────────
# Short-term momentum; matches existing momentum_scanner conventions.
EMA_FAST = 9
# Medium-term swing support; standard institutional reference.
EMA_MEDIUM = 21
# Long-term trend filter. 65 chosen over 50 (too common, less differentiation)
# and 75 (too slow for growth names). ~13 weeks — aligns with quarterly earnings.
EMA_LONG = 65
# 5-day slope window for ema65 — TREND_OK gate.
EMA_LONG_SLOPE_WINDOW = 5
# Same length, different EMA — used by BASE_FORMING to distinguish healthy
# compression from dead sideways.
EMA_MEDIUM_SLOPE_WINDOW = 5

# ── PULLBACK ───────────────────────────────────────────
# 3% chosen because:
#   - typical strong-trend pullback range in US large-cap growth
#   - tighter (1-2%) misses healthy intraday wicks
#   - looser (5%+) starts admitting weak structures
# Phase D will revisit using forward-return data.
PULLBACK_MAX_DIST_FROM_EMA9 = 0.03

# ── BASE_FORMING ───────────────────────────────────────
# 5-15 day window covers VCP-style bases without admitting multi-month dead
# zones. <5d is noise; >15d usually means trend has aged out.
BASE_FORMING_DAYS_MIN = 5
BASE_FORMING_DAYS_MAX = 15
# (high-low)/median_price ≤ 8% over the sideways window — roughly 1.5x typical
# large-cap ATR. Admits slow consolidations, rejects choppy ranges.
BASE_RANGE_MAX_PCT = 0.08
# 5d avg volume must be < 85% of 20d avg. Tighter (0.7) too restrictive;
# looser (0.95) admits non-contractions.
BASE_VOL_CONTRACTION_RATIO = 0.85

# ── EXTENDED ───────────────────────────────────────────
# >12% above EMA9. 12% alone wrongly tags high-vol names (SOXL/IONQ/CRCL)
# where 12% extension is normal — paired with RSI gate below.
EXTENDED_DIST_FROM_EMA9 = 0.12
# AND RSI14 > 72. Below traditional 80; by 80 the move is nearly over.
# 72 catches earlier exhaustion characteristic of growth-name climaxes.
EXTENDED_RSI_MIN = 72

# ── BROKEN ─────────────────────────────────────────────
# Definition: ema21 < ema65 OR close < ema65.
# (No constant — definition is structural, not numeric. ema9<ema21 is
# intentionally NOT included; it triggers on every healthy pullback.)

# ── Trigger ────────────────────────────────────────────
# 1.2x avg20 — modest threshold to avoid false positives without being so
# strict that most legitimate triggers fail. Higher (1.5x) misses many real
# CONFIRMED entries in normal-volume regimes.
TRIGGER_CONFIRM_VOL_RATIO_MIN = 1.2
# Close must be in upper 20% of day's range. Rejects gap-up-then-fade
# (the classic exhaustion shape).
TRIGGER_CONFIRM_CLOSE_HIGH_RATIO = 0.8

# Controls the FAILED_BREAKOUT risk_tag detection (§4.5).
# False = loose (close < ema9 only) — Phase A default.
# True  = strict (also requires close < yesterday_low).
# Phase D measures whether the strict form gives better expectancy.
FAILED_BREAKOUT_REQUIRE_BELOW_PRIOR_LOW = False

# ── Active set ─────────────────────────────────────────
# 14d momentum lookback covers the typical EXTENDED→PULLBACK→TRIGGER cycle.
ACTIVE_M123_LOOKBACK_DAYS = 14
# 10d non-broken lookback ensures recently-faded names stay in scope long
# enough to capture a base, but drop out before zombie tickers accumulate.
ACTIVE_NONBROKEN_LOOKBACK_DAYS = 10

# Hard ceiling on active-set size — protects against runaway growth.
# §12.3 — if exceeded, truncate to the 500 most recently-active.
ACTIVE_SET_MAX_SIZE = 500

# ── Risk tags ──────────────────────────────────────────
# RSI ≥ 80 — classic textbook overbought. OVERHEAT is descriptive, not
# blocking; stays purely in risk_tags.
RISK_OVERHEAT_RSI = 80
# 1-day return ≥ 8% — sharp single-day move characteristic of climax bars.
RISK_PARABOLIC_RET_1D = 0.08
# Combined with the above — volume ≥ 2.0x avg20 confirms participation.
RISK_PARABOLIC_VOL_RATIO = 2.0
