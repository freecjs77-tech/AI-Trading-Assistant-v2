# Trade Lifecycle Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a per-ticker daily setup/trigger/decision state machine for the active US + KR universes, with persistent ticker-keyed snapshots, lifecycle pages, and a daily Telegram brief. Purely additive — `signal_judge` and `momentum_scanner` outputs stay byte-identical.

**Architecture:** A new isolated module set (`lifecycle_config` / `lifecycle_signal` / `lifecycle_history` / `lifecycle_report`) wired into `pipeline.py` as Step 4c4 (US) and Step 4c5 (KR). Both steps read existing market data + momentum history, write to `history/lifecycle_history_{us,kr}.json`, and feed `report_generator` (nav link), `telegram_sender` (brief), and `generate_site` (copy). Failure of either step is isolated — Step 5 still ships portfolio reports.

**Tech Stack:** Python 3.10+ stdlib, pandas/numpy (already in project), yfinance (bootstrap only), Jinja2 (templates), pytest (tests). No new dependencies.

**Spec:** [`docs/superpowers/specs/2026-05-08-trade-lifecycle-phase-a-design.md`](../specs/2026-05-08-trade-lifecycle-phase-a-design.md)
**Roadmap:** [`docs/superpowers/specs/2026-05-08-trade-lifecycle-roadmap.md`](../specs/2026-05-08-trade-lifecycle-roadmap.md)

---

## File Structure

### New files

| File | Responsibility |
|---|---|
| `lifecycle_config.py` | All thresholds (EMA windows, PULLBACK distance, BASE compression bounds, EXTENDED gates, BROKEN, trigger gates, FAILED_BREAKOUT toggle, active-set lookbacks, risk-tag thresholds). Every constant has a rationale comment within 5 lines above its definition. |
| `lifecycle_signal.py` | Pure functions: `evaluate_setup_state(raw)` → str, `evaluate_trigger_state(today_raw, yesterday_raw, setup_state)` → str, `evaluate_decision(setup, trigger, regime=None)` → str, `compute_risk_tags(today_raw, yesterday_snapshot)` → list[str], plus `process_ticker(...)` and `process_universe(...)` orchestrators. Imports `lifecycle_config` only. |
| `lifecycle_history.py` | JSON schema + atomic I/O (mirrors `portfolio_stop_history`'s tmp-rename pattern), `active_set(market, momentum_history, lifecycle_state, portfolio, today)`, first-run `bootstrap_emas(tickers)`, derived-field reconstruction (`setup_streak`, `days_in_pullback`, `trigger_age_days`), `compute_transitions(yesterday_snap, today_snap)`. |
| `lifecycle_report.py` | `generate_lifecycle_pages(us_result, kr_result, output_dir)` — Jinja2 render + sort + section building. |
| `templates/lifecycle_us.html` | US lifecycle page (sections [1]–[6] from spec §10.1). |
| `templates/lifecycle_kr.html` | KR lifecycle page — identical layout, KR data. |
| `tests/test_lifecycle_config.py` | Threshold sanity + rationale-comment-present test. |
| `tests/test_lifecycle_signal.py` | Pure-function unit tests for each state, precedence test, decision-table test, risk-tag test. |
| `tests/test_lifecycle_history.py` | Schema round-trip, atomic write, active-set rule, derived-field reconstruction, transitions log shape, archival path. |
| `tests/test_lifecycle_golden.py` | The 6 named scenarios from spec §9 — regression contract. |
| `tests/test_lifecycle_e2e.py` | Smoke test that wires pipeline-style inputs through `process_universe` → render → empty-section handling. |

### Modified files

| File | Change |
|---|---|
| `fetch_market_data.py` | Add `ema9`, `ema21`, `ema65`, `ema21_slope_5d`, `ema65_slope_5d` to per-ticker output. Computed from existing 200-day price window. |
| `pipeline.py` | Insert Step 4c4 (US lifecycle) and Step 4c5 (KR lifecycle) between current Step 4c3 and Step 4d. Each wrapped in try/except — failures must not block Step 5. Pass results to `generate_report`, `send_lifecycle_brief`, and `generate_lifecycle_pages` in Step 5. |
| `report_generator.py` | Accept `lifecycle_us=None, lifecycle_kr=None` kwargs in `generate_report`; surface "→ Lifecycle US/KR" links in main nav. Render unchanged otherwise. |
| `telegram_sender.py` | Add `send_lifecycle_brief(us_result, kr_result, base_url, date_str)`. |
| `generate_site.py` | Copy `reports/lifecycle_*.html` into `deploy/` (mirror existing `portfolio_stops_*.html` block at line 75). |
| `.github/workflows/daily-report.yml` | Add `history/lifecycle_history_us.json` and `history/lifecycle_history_kr.json` to the gh-pages restore list at line 29-36. |
| `CLAUDE.md` | Register the plan under "진행 중인 계획". |

### Runtime artifacts

```
history/lifecycle_history_us.json
history/lifecycle_history_kr.json
reports/lifecycle_us_<DATE>.html
reports/lifecycle_kr_<DATE>.html
```

---

## Conventions used by every task

- **Branch:** all work happens on the current worktree branch (`claude/sad-leavitt-89c203`).
- **Test runner:** `pytest tests/<file> -v`. Project uses no special pytest config — direct invocation works.
- **Encoding:** Windows host has cp949 default. Test files and source must avoid emojis in `print()`. `pipeline.py` already calls `sys.stdout.reconfigure(encoding="utf-8")`.
- **Path style:** every new file lives at the repo root (no `lifecycle/` package directory) — matches existing pattern (`momentum_signal.py`, `portfolio_stop_signal.py`).
- **Commit message format:** `<type>(lifecycle): <subject>` where `<type>` ∈ `feat`, `test`, `chore`, `docs`, `fix`. Add `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.

---

## Task 1: Scaffold `lifecycle_config.py` with thresholds + rationale

**Files:**
- Create: `lifecycle_config.py`
- Test: `tests/test_lifecycle_config.py`

- [ ] **Step 1: Write the failing test for rationale comments + value sanity**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_lifecycle_config.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'lifecycle_config'`.

- [ ] **Step 3: Write `lifecycle_config.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_lifecycle_config.py -v
```
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add lifecycle_config.py tests/test_lifecycle_config.py
git commit -m "feat(lifecycle): add lifecycle_config.py with thresholds + rationale gate"
```

---

## Task 2: Extend `fetch_market_data.py` with EMA9/21/65 + slopes

**Files:**
- Modify: `fetch_market_data.py:411-498` (the indicator-build block + return dict)
- Test: `tests/test_fetch_market_data_ema_lifecycle.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fetch_market_data_ema_lifecycle.py
"""Phase A — fetch_market_data must emit ema9/21/65 + slopes."""
import numpy as np
import pandas as pd
import pytest

from fetch_market_data import compute_indicators


def _synthetic_df(close_values: list[float], days: int = 200) -> pd.DataFrame:
    """Build a yfinance-shaped DataFrame from a list of closes."""
    if len(close_values) < days:
        # pad with the first value
        close_values = [close_values[0]] * (days - len(close_values)) + close_values
    close = np.array(close_values[-days:], dtype=float)
    idx = pd.date_range("2025-09-01", periods=days, freq="B")
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99,
         "Close": close, "Volume": [1_000_000] * days},
        index=idx,
    )


def test_emit_ema9_ema21_ema65():
    # Steady uptrend: closes 100 → 199.
    closes = [100 + i * 0.5 for i in range(200)]
    df = _synthetic_df(closes)
    out = compute_indicators(df)
    assert "ema9" in out and out["ema9"] is not None
    assert "ema21" in out and out["ema21"] is not None
    assert "ema65" in out and out["ema65"] is not None
    # Steady uptrend: ema9 > ema21 > ema65.
    assert out["ema9"] > out["ema21"] > out["ema65"]


def test_emit_ema_slopes_5d():
    closes = [100 + i * 0.5 for i in range(200)]
    df = _synthetic_df(closes)
    out = compute_indicators(df)
    assert "ema21_slope_5d" in out and out["ema21_slope_5d"] is not None
    assert "ema65_slope_5d" in out and out["ema65_slope_5d"] is not None
    # In a steady uptrend, both slopes are positive.
    assert out["ema21_slope_5d"] > 0
    assert out["ema65_slope_5d"] > 0


def test_ema_slopes_negative_in_downtrend():
    closes = [200 - i * 0.5 for i in range(200)]
    df = _synthetic_df(closes)
    out = compute_indicators(df)
    assert out["ema21_slope_5d"] < 0
    assert out["ema65_slope_5d"] < 0


def test_short_history_returns_none_for_long_emas():
    # Only 30 days of data — ema65 cannot be reliable.
    closes = [100 + i for i in range(30)]
    df = _synthetic_df(closes, days=30)
    out = compute_indicators(df)
    # ema9 still emits, ema65 may or may not — but if it does, slope must
    # also emit; never half-emit.
    if out.get("ema65") is not None:
        assert out.get("ema65_slope_5d") is not None
```

- [ ] **Step 2: Locate `compute_indicators` and verify entry point**

The current `fetch_market_data.py` has the indicator computation inline inside its main per-ticker block (around line 396-540). The test imports `compute_indicators(df)` — extract or expose the existing logic as a callable. If a function with that name doesn't exist yet, this step is also "create the entry point."

Run: `grep -n "^def compute_indicators\|^def _compute_indicators\|^def compute_for_ticker" fetch_market_data.py`

If no exported function matches, in Step 3 wrap the existing inline block into a callable named `compute_indicators(df, *, forward_div=None, cached_divs=None)` that returns the same dict the inline block currently builds. The body of the wrapper is the existing code from `if len(df) < 26: return ...` through the closing `return {...}` block — moved verbatim, then ema9/21/65/slopes added before the return.

- [ ] **Step 3: Run test to verify it fails**

```
pytest tests/test_fetch_market_data_ema_lifecycle.py -v
```
Expected: FAIL — either `ImportError: cannot import name 'compute_indicators'` OR `KeyError: 'ema9'`.

- [ ] **Step 4: Add EMA computations + slopes inside the indicator block**

In `fetch_market_data.py`, after the existing `vol_ma20 = volume.rolling(20).mean()` line (around line 417) and before the `last_close = float(close.iloc[-1])` line, add:

```python
        # ── Phase A: lifecycle EMAs ──
        # EMA9/21/65 + 5-day slopes (used by lifecycle_signal state machine).
        from lifecycle_config import (
            EMA_FAST, EMA_MEDIUM, EMA_LONG,
            EMA_LONG_SLOPE_WINDOW, EMA_MEDIUM_SLOPE_WINDOW,
        )
        ema9_series  = close.ewm(span=EMA_FAST,   adjust=False).mean()
        ema21_series = close.ewm(span=EMA_MEDIUM, adjust=False).mean()
        ema65_series = close.ewm(span=EMA_LONG,   adjust=False).mean()

        def _slope(series, window: int):
            if len(series) <= window:
                return None
            cur = series.iloc[-1]
            prev = series.iloc[-1 - window]
            if pd.isna(cur) or pd.isna(prev) or not np.isfinite(cur) or not np.isfinite(prev):
                return None
            return round(float(cur - prev), 6)

        ema21_slope = _slope(ema21_series, EMA_MEDIUM_SLOPE_WINDOW)
        ema65_slope = _slope(ema65_series, EMA_LONG_SLOPE_WINDOW)
```

Then in the return dict (around line 466), add these keys alongside the existing `ma20`/`ma50`/`ma200`:

```python
            "ema9":              safe(ema9_series),
            "ema21":             safe(ema21_series),
            "ema65":             safe(ema65_series),
            "ema21_slope_5d":    ema21_slope,
            "ema65_slope_5d":    ema65_slope,
```

- [ ] **Step 5: If `compute_indicators` does not yet exist as a callable, expose it**

If the existing code is inline inside `fetch_one_ticker` (or whatever the per-ticker function is), refactor minimally: the test only needs `compute_indicators(df)` to be importable and to return the dict.

The minimal extraction: copy the body from `if len(df) < 26: return {"error": ...}` through the final `return {...}` into a top-level function `def compute_indicators(df: pd.DataFrame, forward_div=None, cached_divs=None) -> dict:` and have the existing per-ticker code call it instead. No behavior change.

- [ ] **Step 6: Run test to verify it passes**

```
pytest tests/test_fetch_market_data_ema_lifecycle.py -v
```
Expected: 4 passed.

- [ ] **Step 7: Run existing fetch_market_data tests to verify no regression**

```
pytest tests/test_fetch_market_data_atr.py -v
```
Expected: all passing (was passing before; no fields removed).

- [ ] **Step 8: Commit**

```bash
git add fetch_market_data.py tests/test_fetch_market_data_ema_lifecycle.py
git commit -m "feat(lifecycle): emit ema9/21/65 + 5d slopes from fetch_market_data"
```

---

## Task 3: `lifecycle_signal.evaluate_setup_state` — TDD all 5 states + precedence

**Files:**
- Create: `lifecycle_signal.py`
- Test: `tests/test_lifecycle_signal.py`

- [ ] **Step 1: Write the failing tests for the 5 states + precedence**

```python
# tests/test_lifecycle_signal.py
"""Phase A — pure-function unit tests for lifecycle_signal."""
import pytest

from lifecycle_signal import evaluate_setup_state


def _raw(**overrides):
    """Build a 'today' raw dict with sensible defaults for a TREND_OK ticker."""
    base = {
        "close": 100.0,
        "high":  101.0,
        "low":    99.0,
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_lifecycle_signal.py -v
```
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `evaluate_setup_state` with strict precedence order**

Create `lifecycle_signal.py`:

```python
# lifecycle_signal.py
"""Phase A — pure-function lifecycle state machine.

State machines:
  setup_state    ∈ {TREND_OK, PULLBACK, BASE_FORMING, EXTENDED, BROKEN}
  trigger_state  ∈ {WAIT, EARLY_TRIGGER, CONFIRMED_TRIGGER}
  entry_decision ∈ {ENTER_OK, EARLY, STAGING, AVOID}

setup_state evaluation order is strict (first match wins):
  1. BROKEN  2. EXTENDED  3. BASE_FORMING  4. PULLBACK  5. TREND_OK
"""
from __future__ import annotations

from typing import Optional

from lifecycle_config import (
    PULLBACK_MAX_DIST_FROM_EMA9,
    BASE_FORMING_DAYS_MIN, BASE_FORMING_DAYS_MAX,
    BASE_VOL_CONTRACTION_RATIO,
    EXTENDED_DIST_FROM_EMA9, EXTENDED_RSI_MIN,
    TRIGGER_CONFIRM_VOL_RATIO_MIN, TRIGGER_CONFIRM_CLOSE_HIGH_RATIO,
    FAILED_BREAKOUT_REQUIRE_BELOW_PRIOR_LOW,
    RISK_OVERHEAT_RSI, RISK_PARABOLIC_RET_1D, RISK_PARABOLIC_VOL_RATIO,
)


def _is_trend_ok(r: dict) -> bool:
    """ema9 > ema21 > ema65 AND ema65 slope positive AND close > ema21."""
    e9, e21, e65 = r.get("ema9"), r.get("ema21"), r.get("ema65")
    if e9 is None or e21 is None or e65 is None:
        return False
    if not (e9 > e21 > e65):
        return False
    if (r.get("ema65_slope_5d") or 0) <= 0:
        return False
    if (r.get("close") or 0) <= e21:
        return False
    return True


def _is_broken(r: dict) -> bool:
    e21, e65 = r.get("ema21"), r.get("ema65")
    close = r.get("close")
    if e21 is None or e65 is None or close is None:
        return False
    return (e21 < e65) or (close < e65)


def _is_extended(r: dict) -> bool:
    e9, e21, e65 = r.get("ema9"), r.get("ema21"), r.get("ema65")
    close = r.get("close")
    rsi = r.get("rsi14")
    if e9 is None or e21 is None or e65 is None or close is None or rsi is None:
        return False
    if not (e9 > e21 > e65):
        return False
    dist_pct = abs(close - e9) / e9
    return dist_pct > EXTENDED_DIST_FROM_EMA9 and rsi > EXTENDED_RSI_MIN


def _is_base_forming(r: dict) -> bool:
    if not _is_trend_ok(r):
        return False
    days = r.get("days_sideways") or 0
    if not (BASE_FORMING_DAYS_MIN <= days <= BASE_FORMING_DAYS_MAX):
        return False
    a5  = r.get("atr14_pct_5d_avg")
    a20 = r.get("atr14_pct_20d_avg")
    if a5 is None or a20 is None or a5 >= a20:
        return False
    v5  = r.get("volume_5d_avg")
    v20 = r.get("volume_20d_avg")
    if v5 is None or v20 is None or v5 >= v20 * BASE_VOL_CONTRACTION_RATIO:
        return False
    if (r.get("ema21_slope_5d") or 0) <= 0:
        return False
    return True


def _is_pullback(r: dict) -> bool:
    if not _is_trend_ok(r):
        return False
    e9 = r.get("ema9")
    close = r.get("close")
    e21 = r.get("ema21")
    if e9 is None or close is None or e21 is None:
        return False
    if abs(close - e9) / e9 > PULLBACK_MAX_DIST_FROM_EMA9:
        return False
    if close < e21:
        return False
    return True


def evaluate_setup_state(raw: dict) -> str:
    """Strict precedence: BROKEN > EXTENDED > BASE_FORMING > PULLBACK > TREND_OK."""
    if _is_broken(raw):
        return "BROKEN"
    if _is_extended(raw):
        return "EXTENDED"
    if _is_base_forming(raw):
        return "BASE_FORMING"
    if _is_pullback(raw):
        return "PULLBACK"
    if _is_trend_ok(raw):
        return "TREND_OK"
    return "BROKEN"  # No alignment + no break = degraded; treat as out-of-trend.
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_lifecycle_signal.py -v
```
Expected: 13 passed (every test in the file from this task).

- [ ] **Step 5: Commit**

```bash
git add lifecycle_signal.py tests/test_lifecycle_signal.py
git commit -m "feat(lifecycle): evaluate_setup_state with 5-state precedence"
```

---

## Task 4: `evaluate_trigger_state` + helper inputs

**Files:**
- Modify: `lifecycle_signal.py`
- Modify: `tests/test_lifecycle_signal.py`

- [ ] **Step 1: Append failing trigger tests**

Add to the bottom of `tests/test_lifecycle_signal.py`:

```python
from lifecycle_signal import evaluate_trigger_state


def _trig(**overrides):
    """Today + yesterday raw — defaults are 'no trigger'."""
    today = {
        "close": 100.0, "high": 101.0, "low": 99.0,
        "ema9": 99.5, "volume_ratio": 1.0,
    }
    yesterday = {"close": 99.0, "high": 100.0, "ema9": 99.5}
    today.update(overrides.get("today", {}))
    yesterday.update(overrides.get("yesterday", {}))
    return today, yesterday


def test_trigger_wait_when_setup_not_in_pullback_or_base():
    today, yesterday = _trig()
    assert evaluate_trigger_state(today, yesterday, setup_state="TREND_OK") == "WAIT"
    assert evaluate_trigger_state(today, yesterday, setup_state="EXTENDED") == "WAIT"
    assert evaluate_trigger_state(today, yesterday, setup_state="BROKEN") == "WAIT"


def test_trigger_early_on_ema9_reclaim():
    today, yesterday = _trig(
        today={"close": 100.0, "ema9": 99.0},
        yesterday={"close": 98.5, "ema9": 99.0},  # closed below ema9 yesterday
    )
    assert evaluate_trigger_state(today, yesterday, setup_state="PULLBACK") == "EARLY_TRIGGER"


def test_trigger_early_on_prior_high_break():
    today, yesterday = _trig(today={"high": 102.0}, yesterday={"high": 100.0})
    assert evaluate_trigger_state(today, yesterday, setup_state="PULLBACK") == "EARLY_TRIGGER"


def test_trigger_confirmed_volume_and_close_in_top_20pct():
    today, yesterday = _trig(
        today={
            "close": 100.8, "high": 101.0, "low": 100.0, "ema9": 99.0,
            "volume_ratio": 1.5,
        },
        yesterday={"close": 98.5, "ema9": 99.0, "high": 100.0},
    )
    assert evaluate_trigger_state(today, yesterday, setup_state="PULLBACK") == "CONFIRMED_TRIGGER"


def test_trigger_volume_below_threshold_stays_early():
    today, yesterday = _trig(
        today={
            "close": 100.8, "high": 101.0, "low": 100.0, "ema9": 99.0,
            "volume_ratio": 0.9,
        },
        yesterday={"close": 98.5, "ema9": 99.0, "high": 100.0},
    )
    assert evaluate_trigger_state(today, yesterday, setup_state="PULLBACK") == "EARLY_TRIGGER"


def test_trigger_close_in_lower_half_stays_wait():
    # prior-high break BUT close in lower 50% — fails close gate AND fails
    # ema9 reclaim (closed below ema9). Result: WAIT.
    today, yesterday = _trig(
        today={
            "close": 99.5, "high": 102.0, "low": 99.0, "ema9": 100.0,
            "volume_ratio": 1.5,
        },
        yesterday={"close": 99.8, "ema9": 99.5, "high": 100.0},  # was above ema9
    )
    assert evaluate_trigger_state(today, yesterday, setup_state="PULLBACK") == "WAIT"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_lifecycle_signal.py::test_trigger_wait_when_setup_not_in_pullback_or_base -v
```
Expected: FAIL — `evaluate_trigger_state` not defined.

- [ ] **Step 3: Implement `evaluate_trigger_state`**

Append to `lifecycle_signal.py`:

```python
def _close_in_upper_band(today: dict) -> bool:
    """today_close >= today_high * ratio + today_low * (1-ratio)."""
    h = today.get("high"); l = today.get("low"); c = today.get("close")
    if h is None or l is None or c is None or h == l:
        return False
    return c >= h * TRIGGER_CONFIRM_CLOSE_HIGH_RATIO + l * (1 - TRIGGER_CONFIRM_CLOSE_HIGH_RATIO)


def _is_early_trigger(today: dict, yesterday: dict) -> bool:
    e9 = today.get("ema9")
    if e9 is not None and yesterday.get("close") is not None and today.get("close") is not None:
        if yesterday["close"] <= e9 < today["close"]:
            return True
    if (today.get("high") is not None and yesterday.get("high") is not None
            and today["high"] > yesterday["high"]):
        return True
    return False


def _is_confirmed_trigger(today: dict, yesterday: dict) -> bool:
    if not _is_early_trigger(today, yesterday):
        return False
    if (today.get("volume_ratio") or 0) < TRIGGER_CONFIRM_VOL_RATIO_MIN:
        return False
    return _close_in_upper_band(today)


def evaluate_trigger_state(today: dict, yesterday: dict, setup_state: str) -> str:
    """Trigger only meaningful when setup ∈ {PULLBACK, BASE_FORMING}; else WAIT."""
    if setup_state not in ("PULLBACK", "BASE_FORMING"):
        return "WAIT"
    if _is_confirmed_trigger(today, yesterday):
        return "CONFIRMED_TRIGGER"
    if _is_early_trigger(today, yesterday):
        return "EARLY_TRIGGER"
    return "WAIT"
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_lifecycle_signal.py -v
```
Expected: all (≥19) passed.

- [ ] **Step 5: Commit**

```bash
git add lifecycle_signal.py tests/test_lifecycle_signal.py
git commit -m "feat(lifecycle): evaluate_trigger_state with WAIT/EARLY/CONFIRMED"
```

---

## Task 5: `evaluate_decision` (with `regime=None` Phase B hook)

**Files:**
- Modify: `lifecycle_signal.py`
- Modify: `tests/test_lifecycle_signal.py`

- [ ] **Step 1: Append failing decision tests**

```python
from lifecycle_signal import evaluate_decision


@pytest.mark.parametrize("setup,trigger,expected", [
    ("PULLBACK",     "CONFIRMED_TRIGGER", "ENTER_OK"),
    ("BASE_FORMING", "CONFIRMED_TRIGGER", "ENTER_OK"),
    ("PULLBACK",     "EARLY_TRIGGER",     "EARLY"),
    ("BASE_FORMING", "EARLY_TRIGGER",     "EARLY"),
    ("TREND_OK",     "WAIT",              "STAGING"),
    ("EXTENDED",     "WAIT",              "AVOID"),
    ("BROKEN",       "WAIT",              "AVOID"),
])
def test_decision_table(setup, trigger, expected):
    assert evaluate_decision(setup, trigger) == expected


def test_decision_failed_breakout_forces_avoid():
    assert evaluate_decision("PULLBACK", "EARLY_TRIGGER",
                             risk_tags=["FAILED_BREAKOUT"]) == "AVOID"


def test_decision_regime_none_is_default_phase_b_hook():
    # In Phase A regime=None should be a no-op. The function must accept it.
    assert evaluate_decision("PULLBACK", "CONFIRMED_TRIGGER", regime=None) == "ENTER_OK"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_lifecycle_signal.py -v -k decision
```
Expected: FAIL — `evaluate_decision` not defined.

- [ ] **Step 3: Implement `evaluate_decision`**

Append to `lifecycle_signal.py`:

```python
def evaluate_decision(
    setup_state: str,
    trigger_state: str,
    *,
    risk_tags: Optional[list[str]] = None,
    regime: Optional[str] = None,  # Phase B hook — unused in A.
) -> str:
    risk_tags = risk_tags or []
    if "FAILED_BREAKOUT" in risk_tags:
        return "AVOID"
    if setup_state in ("EXTENDED", "BROKEN"):
        return "AVOID"
    if setup_state in ("PULLBACK", "BASE_FORMING"):
        if trigger_state == "CONFIRMED_TRIGGER":
            return "ENTER_OK"
        if trigger_state == "EARLY_TRIGGER":
            return "EARLY"
    if setup_state == "TREND_OK":
        return "STAGING"
    return "AVOID"
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_lifecycle_signal.py -v
```
Expected: all (≥28) passed.

- [ ] **Step 5: Commit**

```bash
git add lifecycle_signal.py tests/test_lifecycle_signal.py
git commit -m "feat(lifecycle): evaluate_decision with regime=None Phase B hook"
```

---

## Task 6: `compute_risk_tags` including FAILED_BREAKOUT detection

**Files:**
- Modify: `lifecycle_signal.py`
- Modify: `tests/test_lifecycle_signal.py`

- [ ] **Step 1: Append failing risk-tag tests**

```python
from lifecycle_signal import compute_risk_tags


def test_risk_overheat_when_rsi_ge_80():
    today = {"rsi14": 80.5, "close": 100, "ema9": 95}
    assert "OVERHEAT" in compute_risk_tags(today, yesterday_snapshot=None)


def test_risk_parabolic_when_big_day_and_volume():
    today = {"rsi14": 50, "close": 110, "ema9": 100,
             "change_pct": 9.0, "volume_ratio": 2.5}
    assert "PARABOLIC" in compute_risk_tags(today, yesterday_snapshot=None)


def test_risk_extended_mirror():
    today = {"rsi14": 78, "close": 120, "ema9": 100, "ema21": 95, "ema65": 90}
    tags = compute_risk_tags(today, yesterday_snapshot=None)
    assert "EXTENDED" in tags


def test_failed_breakout_yesterday_confirmed_today_below_ema9():
    today = {"close": 99.0, "ema9": 100.0, "low": 98.5}
    yesterday_snapshot = {"trigger": "CONFIRMED_TRIGGER",
                          "raw": {"low": 98.0}}
    tags = compute_risk_tags(today, yesterday_snapshot=yesterday_snapshot)
    assert "FAILED_BREAKOUT" in tags


def test_failed_breakout_strict_form_requires_below_prior_low(monkeypatch):
    # Toggle strict form on for this test.
    import lifecycle_config
    monkeypatch.setattr(lifecycle_config,
                        "FAILED_BREAKOUT_REQUIRE_BELOW_PRIOR_LOW", True)
    # Below ema9 but above yesterday_low → should NOT trigger under strict.
    today = {"close": 99.0, "ema9": 100.0, "low": 98.5}
    yesterday_snapshot = {"trigger": "CONFIRMED_TRIGGER",
                          "raw": {"low": 98.0}}
    assert "FAILED_BREAKOUT" not in compute_risk_tags(today, yesterday_snapshot=yesterday_snapshot)


def test_failed_breakout_no_yesterday_snapshot_no_tag():
    today = {"close": 99.0, "ema9": 100.0}
    assert "FAILED_BREAKOUT" not in compute_risk_tags(today, yesterday_snapshot=None)
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_lifecycle_signal.py -v -k risk
```
Expected: FAIL — `compute_risk_tags` not defined.

- [ ] **Step 3: Implement `compute_risk_tags`**

Append to `lifecycle_signal.py`:

```python
def compute_risk_tags(today: dict, yesterday_snapshot: Optional[dict]) -> list[str]:
    """Risk tags are derived metadata. Multiple may attach simultaneously."""
    # Re-import inside the function to allow monkeypatch to work in tests.
    from lifecycle_config import FAILED_BREAKOUT_REQUIRE_BELOW_PRIOR_LOW as STRICT
    tags: list[str] = []

    if (today.get("rsi14") or 0) >= RISK_OVERHEAT_RSI:
        tags.append("OVERHEAT")

    chg = today.get("change_pct")
    vr = today.get("volume_ratio")
    if (chg is not None and (chg / 100.0) >= RISK_PARABOLIC_RET_1D
            and vr is not None and vr >= RISK_PARABOLIC_VOL_RATIO):
        tags.append("PARABOLIC")

    # EXTENDED mirror — same predicate as setup_state's EXTENDED.
    if _is_extended(today):
        tags.append("EXTENDED")

    # FAILED_BREAKOUT — yesterday CONFIRMED + today close < ema9 (loose form).
    if yesterday_snapshot and yesterday_snapshot.get("trigger") == "CONFIRMED_TRIGGER":
        e9 = today.get("ema9")
        c = today.get("close")
        if e9 is not None and c is not None and c < e9:
            ok = True
            if STRICT:
                yl = (yesterday_snapshot.get("raw") or {}).get("low")
                ok = yl is not None and c < yl
            if ok:
                tags.append("FAILED_BREAKOUT")

    return tags
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_lifecycle_signal.py -v
```
Expected: all (≥34) passed.

- [ ] **Step 5: Commit**

```bash
git add lifecycle_signal.py tests/test_lifecycle_signal.py
git commit -m "feat(lifecycle): compute_risk_tags with FAILED_BREAKOUT loose+strict"
```

---

## Task 7: `lifecycle_history` schema, atomic I/O, snapshot append

**Files:**
- Create: `lifecycle_history.py`
- Test: `tests/test_lifecycle_history.py`

- [ ] **Step 1: Write failing schema + I/O tests**

```python
# tests/test_lifecycle_history.py
"""Phase A — lifecycle_history schema + atomic I/O."""
import json
import os
from pathlib import Path

import pytest

from lifecycle_history import (
    new_empty_state, load_lifecycle_history, save_lifecycle_history,
    append_snapshot, append_transition,
)


def test_new_empty_state_shape():
    s = new_empty_state(market="US")
    assert s["schema_version"] == "1.0.0"
    assert s["generator_version"].startswith("lifecycle_phase_a/")
    assert s["tickers"] == {}
    assert s["transitions"] == []


def test_round_trip(tmp_path: Path):
    s = new_empty_state(market="US")
    p = tmp_path / "lifecycle_history_us.json"
    save_lifecycle_history(s, str(p))
    loaded = load_lifecycle_history(str(p))
    assert loaded["schema_version"] == "1.0.0"
    assert loaded["tickers"] == {}


def test_load_missing_file_returns_empty():
    s = load_lifecycle_history("/nonexistent/path.json", market="US")
    assert s["tickers"] == {}


def test_atomic_write_no_partial_on_failure(tmp_path: Path, monkeypatch):
    """A failed save must leave the existing file intact."""
    p = tmp_path / "lifecycle_history_us.json"
    save_lifecycle_history(new_empty_state(market="US"), str(p))
    original = p.read_text()
    # Force os.replace to fail.
    import lifecycle_history as lh
    monkeypatch.setattr(lh.os, "replace",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("simulated")))
    with pytest.raises(OSError):
        save_lifecycle_history(new_empty_state(market="US"), str(p))
    assert p.read_text() == original  # unchanged.


def test_append_snapshot_creates_ticker_block():
    s = new_empty_state(market="US")
    snap = {"date": "2026-05-08", "setup": "TREND_OK", "trigger": "WAIT",
            "decision": "STAGING", "raw": {"close": 100, "high": 101,
            "low": 99, "ema9": 99, "ema21": 95, "ema65": 90,
            "dist_ema9_pct": 1.0, "dist_ema21_pct": 5.0,
            "volume_ratio": 1.0, "atr_pct": 2.0,
            "sector": "Technology", "risk_tags": []}}
    append_snapshot(s, "NVDA", snap)
    assert s["tickers"]["NVDA"]["first_seen"] == "2026-05-08"
    assert s["tickers"]["NVDA"]["last_seen"] == "2026-05-08"
    assert len(s["tickers"]["NVDA"]["snapshots"]) == 1


def test_append_snapshot_extends_existing_ticker():
    s = new_empty_state(market="US")
    s["tickers"]["NVDA"] = {"first_seen": "2026-05-07", "last_seen": "2026-05-07",
                             "snapshots": [{"date": "2026-05-07", "setup": "TREND_OK",
                                            "trigger": "WAIT", "decision": "STAGING",
                                            "raw": {}}]}
    snap = {"date": "2026-05-08", "setup": "PULLBACK", "trigger": "WAIT",
            "decision": "STAGING", "raw": {}}
    append_snapshot(s, "NVDA", snap)
    assert s["tickers"]["NVDA"]["last_seen"] == "2026-05-08"
    assert len(s["tickers"]["NVDA"]["snapshots"]) == 2


def test_append_transition_event_id_format():
    s = new_empty_state(market="US")
    append_transition(s, ticker="NVDA", date_str="2026-05-08",
                      event="SETUP_CHANGE", from_value="EXTENDED", to_value="PULLBACK")
    t = s["transitions"][0]
    assert t["event_id"] == "NVDA_2026-05-08_SETUP_CHANGE_v1"
    assert t["event"] == "SETUP_CHANGE"
    assert t["from"] == "EXTENDED"
    assert t["to"] == "PULLBACK"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_lifecycle_history.py -v
```
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `lifecycle_history.py` (schema + I/O + append)**

```python
# lifecycle_history.py
"""Phase A — lifecycle history JSON I/O + schema + active-set + bootstrap.

File schema (per market):
  {
    "schema_version":  "1.0.0",
    "generator_version": "lifecycle_phase_a/0.1.0",
    "last_updated":     ISO-8601,
    "tickers": { TICKER: { first_seen, last_seen, snapshots: [...] } },
    "transitions": [ { event_id, date, ticker, event, from, to } ]
  }

Atomic writes via tmp + os.replace (mirrors portfolio_stop_history pattern).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional

from lifecycle_config import LIFECYCLE_VERSION

SCHEMA_VERSION = "1.0.0"


def new_empty_state(market: str) -> dict:
    return {
        "schema_version":    SCHEMA_VERSION,
        "generator_version": LIFECYCLE_VERSION,
        "market":            market,
        "last_updated":      None,
        "tickers":           {},
        "transitions":       [],
    }


def load_lifecycle_history(path: str, market: str = "US") -> dict:
    if not os.path.exists(path):
        return new_empty_state(market)
    try:
        with open(path, "rb") as f:
            raw = f.read()
        return json.loads(raw.rstrip(b" \t\n\r\x00").decode("utf-8"))
    except Exception as e:
        print(f"[lifecycle_history] WARN load failed ({e}) -- using empty state")
        return new_empty_state(market)


def save_lifecycle_history(state: dict, path: str) -> None:
    state["last_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def append_snapshot(state: dict, ticker: str, snapshot: dict) -> None:
    block = state["tickers"].setdefault(ticker, {
        "first_seen": snapshot["date"],
        "last_seen":  snapshot["date"],
        "snapshots":  [],
    })
    block["snapshots"].append(snapshot)
    block["last_seen"] = snapshot["date"]
    if snapshot["date"] < block["first_seen"]:
        block["first_seen"] = snapshot["date"]


def append_transition(state: dict, *, ticker: str, date_str: str,
                       event: str, from_value: Optional[str],
                       to_value: Optional[str]) -> None:
    state["transitions"].append({
        "event_id": f"{ticker}_{date_str}_{event}_v1",
        "date":     date_str,
        "ticker":   ticker,
        "event":    event,
        "from":     from_value,
        "to":       to_value,
    })
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_lifecycle_history.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add lifecycle_history.py tests/test_lifecycle_history.py
git commit -m "feat(lifecycle): add lifecycle_history with schema + atomic I/O"
```

---

## Task 8: Active-set computation

**Files:**
- Modify: `lifecycle_history.py`
- Modify: `tests/test_lifecycle_history.py`

- [ ] **Step 1: Append failing active-set tests**

```python
from lifecycle_history import compute_active_set


def test_active_set_includes_recent_m1_m2_m3():
    momentum_history = {
        "tickers": {
            "NVDA": {"snapshots": [{"date": "2026-05-08", "stage": "MOMENTUM_2"}]},
            "OLD":  {"snapshots": [{"date": "2026-04-01", "stage": "MOMENTUM_1"}]},  # >14d ago
        }
    }
    lifecycle_state = {"tickers": {}}
    portfolio = []
    s = compute_active_set(momentum_history=momentum_history,
                           lifecycle_state=lifecycle_state,
                           portfolio_tickers=set(portfolio),
                           today="2026-05-08")
    assert "NVDA" in s
    assert "OLD" not in s


def test_active_set_keeps_recent_nonbroken_lifecycle_tickers():
    momentum_history = {"tickers": {}}
    lifecycle_state = {
        "tickers": {
            "PLTR": {"last_seen": "2026-05-05",
                     "snapshots": [{"date": "2026-05-05", "setup": "PULLBACK"}]},
            "DEAD": {"last_seen": "2026-04-01",
                     "snapshots": [{"date": "2026-04-01", "setup": "TREND_OK"}]},
            "BRKN": {"last_seen": "2026-05-07",
                     "snapshots": [{"date": "2026-05-07", "setup": "BROKEN"}]},
        }
    }
    s = compute_active_set(momentum_history=momentum_history,
                           lifecycle_state=lifecycle_state,
                           portfolio_tickers=set(),
                           today="2026-05-08")
    assert "PLTR" in s    # recent + non-broken
    assert "DEAD" not in s   # >10d stale
    assert "BRKN" not in s   # most-recent state was BROKEN — drops out


def test_active_set_excludes_portfolio_tickers():
    momentum_history = {"tickers": {
        "AAPL": {"snapshots": [{"date": "2026-05-08", "stage": "MOMENTUM_3"}]},
    }}
    s = compute_active_set(momentum_history=momentum_history,
                           lifecycle_state={"tickers": {}},
                           portfolio_tickers={"AAPL"},
                           today="2026-05-08")
    assert "AAPL" not in s


def test_active_set_truncates_to_max_size():
    # Build 600 momentum-recent tickers; expect ≤500 in active set.
    momentum_history = {"tickers": {
        f"T{i:04d}": {"snapshots": [{"date": "2026-05-08", "stage": "MOMENTUM_1"}]}
        for i in range(600)
    }}
    s = compute_active_set(momentum_history=momentum_history,
                           lifecycle_state={"tickers": {}},
                           portfolio_tickers=set(),
                           today="2026-05-08")
    from lifecycle_config import ACTIVE_SET_MAX_SIZE
    assert len(s) <= ACTIVE_SET_MAX_SIZE
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_lifecycle_history.py -v -k active_set
```
Expected: FAIL.

- [ ] **Step 3: Implement `compute_active_set`**

Append to `lifecycle_history.py`:

```python
from datetime import date as _date_t


def _days_between(d1: str, d2: str) -> int:
    a = datetime.strptime(d1, "%Y-%m-%d").date()
    b = datetime.strptime(d2, "%Y-%m-%d").date()
    return (a - b).days


def compute_active_set(*, momentum_history: dict,
                        lifecycle_state: dict,
                        portfolio_tickers: set,
                        today: str) -> set[str]:
    """active_set(today) per spec §3.

    Membership rules:
      ticker IN active_set IFF
        ( ticker has M1/M2/M3 hit within ACTIVE_M123_LOOKBACK_DAYS
          OR ticker.setup_state != BROKEN within ACTIVE_NONBROKEN_LOOKBACK_DAYS )
        AND ticker NOT IN portfolio.
    """
    from lifecycle_config import (
        ACTIVE_M123_LOOKBACK_DAYS, ACTIVE_NONBROKEN_LOOKBACK_DAYS,
        ACTIVE_SET_MAX_SIZE,
    )
    candidates: dict[str, str] = {}  # ticker -> most-recent activity date.

    for tk, block in (momentum_history.get("tickers") or {}).items():
        snaps = block.get("snapshots") or []
        for snap in reversed(snaps):
            d = snap.get("date")
            if not d:
                continue
            if _days_between(today, d) <= ACTIVE_M123_LOOKBACK_DAYS:
                candidates[tk] = d
            break

    for tk, block in (lifecycle_state.get("tickers") or {}).items():
        snaps = block.get("snapshots") or []
        if not snaps:
            continue
        last = snaps[-1]
        d = last.get("date") or block.get("last_seen")
        if not d:
            continue
        if last.get("setup") == "BROKEN":
            continue
        if _days_between(today, d) <= ACTIVE_NONBROKEN_LOOKBACK_DAYS:
            existing = candidates.get(tk)
            if not existing or d > existing:
                candidates[tk] = d

    for tk in list(portfolio_tickers):
        candidates.pop(tk, None)

    if len(candidates) > ACTIVE_SET_MAX_SIZE:
        sorted_tickers = sorted(candidates.items(),
                                  key=lambda kv: kv[1], reverse=True)
        candidates = dict(sorted_tickers[:ACTIVE_SET_MAX_SIZE])
        print(f"[lifecycle_history] WARN active set truncated to {ACTIVE_SET_MAX_SIZE}")

    return set(candidates.keys())
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_lifecycle_history.py -v
```
Expected: all passed (existing 7 + 4 new = 11).

- [ ] **Step 5: Commit**

```bash
git add lifecycle_history.py tests/test_lifecycle_history.py
git commit -m "feat(lifecycle): compute_active_set with M123 + non-broken lookback"
```

---

## Task 9: Derived-field reconstruction (`setup_streak`, `days_in_pullback`, `trigger_age_days`)

**Files:**
- Modify: `lifecycle_history.py`
- Modify: `tests/test_lifecycle_history.py`

- [ ] **Step 1: Append failing derived-field tests**

```python
from lifecycle_history import derive_fields


def _ticker_history(*items):
    """items: list of (date, setup, trigger). Returns block in storage shape."""
    return {
        "first_seen": items[0][0],
        "last_seen": items[-1][0],
        "snapshots": [
            {"date": d, "setup": s, "trigger": t, "decision": "X", "raw": {}}
            for d, s, t in items
        ],
    }


def test_derive_setup_streak():
    block = _ticker_history(
        ("2026-05-04", "TREND_OK", "WAIT"),
        ("2026-05-05", "PULLBACK", "WAIT"),
        ("2026-05-06", "PULLBACK", "WAIT"),
        ("2026-05-07", "PULLBACK", "EARLY_TRIGGER"),
        ("2026-05-08", "PULLBACK", "CONFIRMED_TRIGGER"),
    )
    out = derive_fields(block)
    assert out["setup_streak"] == 4  # 4 consecutive PULLBACK days


def test_derive_days_in_pullback_counts_base_forming_too():
    block = _ticker_history(
        ("2026-05-05", "TREND_OK",     "WAIT"),
        ("2026-05-06", "PULLBACK",     "WAIT"),
        ("2026-05-07", "BASE_FORMING", "WAIT"),
        ("2026-05-08", "PULLBACK",     "CONFIRMED_TRIGGER"),
    )
    out = derive_fields(block)
    assert out["days_in_pullback"] == 3


def test_derive_trigger_age_days_zero_today():
    block = _ticker_history(
        ("2026-05-05", "PULLBACK", "WAIT"),
        ("2026-05-06", "PULLBACK", "WAIT"),
        ("2026-05-08", "PULLBACK", "CONFIRMED_TRIGGER"),
    )
    out = derive_fields(block)
    assert out["trigger_age_days"] == 0


def test_derive_trigger_age_counts_back_to_last_early_or_confirmed():
    block = _ticker_history(
        ("2026-05-04", "PULLBACK", "WAIT"),
        ("2026-05-05", "PULLBACK", "EARLY_TRIGGER"),
        ("2026-05-06", "PULLBACK", "WAIT"),
        ("2026-05-07", "PULLBACK", "WAIT"),
        ("2026-05-08", "PULLBACK", "WAIT"),
    )
    out = derive_fields(block)
    # Today is 2026-05-08; last EARLY_TRIGGER was 2026-05-05 → 3 days ago.
    assert out["trigger_age_days"] == 3


def test_derive_trigger_age_none_when_never_triggered():
    block = _ticker_history(
        ("2026-05-07", "PULLBACK", "WAIT"),
        ("2026-05-08", "PULLBACK", "WAIT"),
    )
    out = derive_fields(block)
    assert out["trigger_age_days"] is None
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_lifecycle_history.py -v -k derive
```
Expected: FAIL.

- [ ] **Step 3: Implement `derive_fields`**

Append to `lifecycle_history.py`:

```python
def derive_fields(ticker_block: dict) -> dict:
    """Recompute derived fields from snapshot history. Never stored."""
    snaps = ticker_block.get("snapshots") or []
    if not snaps:
        return {"setup_streak": 0, "days_in_pullback": 0, "trigger_age_days": None}

    # setup_streak — consecutive same setup back from latest.
    latest_setup = snaps[-1].get("setup")
    streak = 0
    for snap in reversed(snaps):
        if snap.get("setup") == latest_setup:
            streak += 1
        else:
            break

    # days_in_pullback — consecutive PULLBACK or BASE_FORMING days back from latest.
    in_pull = 0
    for snap in reversed(snaps):
        if snap.get("setup") in ("PULLBACK", "BASE_FORMING"):
            in_pull += 1
        else:
            break

    # trigger_age_days — days since last EARLY_TRIGGER or CONFIRMED_TRIGGER.
    today = snaps[-1].get("date")
    age = None
    for snap in reversed(snaps):
        if snap.get("trigger") in ("EARLY_TRIGGER", "CONFIRMED_TRIGGER"):
            age = _days_between(today, snap["date"])
            break

    return {
        "setup_streak":     streak,
        "days_in_pullback": in_pull,
        "trigger_age_days": age,
    }
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_lifecycle_history.py -v
```
Expected: all (≥16) passed.

- [ ] **Step 5: Commit**

```bash
git add lifecycle_history.py tests/test_lifecycle_history.py
git commit -m "feat(lifecycle): derived setup_streak/days_in_pullback/trigger_age"
```

---

## Task 10: `compute_transitions` — diff yesterday vs today snapshots

**Files:**
- Modify: `lifecycle_history.py`
- Modify: `tests/test_lifecycle_history.py`

- [ ] **Step 1: Append failing transition tests**

```python
from lifecycle_history import compute_transitions


def test_transition_setup_change():
    yesterday = {"setup": "EXTENDED", "trigger": "WAIT", "decision": "AVOID",
                  "raw": {"risk_tags": []}}
    today =     {"date": "2026-05-08",
                  "setup": "PULLBACK", "trigger": "WAIT", "decision": "STAGING",
                  "raw": {"risk_tags": []}}
    events = compute_transitions("NVDA", yesterday, today)
    types = {e["event"] for e in events}
    assert "SETUP_CHANGE" in types
    assert "DECISION_CHANGE" in types  # AVOID -> STAGING


def test_transition_no_change_no_event():
    same = {"date": "2026-05-08", "setup": "TREND_OK", "trigger": "WAIT",
             "decision": "STAGING", "raw": {"risk_tags": []}}
    events = compute_transitions("NVDA", same, same)
    assert events == []


def test_transition_failed_breakout_emitted_independently():
    yesterday = {"setup": "PULLBACK", "trigger": "CONFIRMED_TRIGGER",
                  "decision": "ENTER_OK", "raw": {"risk_tags": []}}
    today =     {"date": "2026-05-08",
                  "setup": "PULLBACK", "trigger": "WAIT", "decision": "AVOID",
                  "raw": {"risk_tags": ["FAILED_BREAKOUT"]}}
    events = compute_transitions("NVDA", yesterday, today)
    assert any(e["event"] == "FAILED_BREAKOUT" for e in events)
    assert any(e["event"] == "TRIGGER_CHANGE" for e in events)


def test_transition_risk_escalation_when_extended_first_appears():
    yesterday = {"setup": "TREND_OK", "trigger": "WAIT",
                  "decision": "STAGING", "raw": {"risk_tags": []}}
    today =     {"date": "2026-05-08",
                  "setup": "EXTENDED", "trigger": "WAIT",
                  "decision": "AVOID", "raw": {"risk_tags": ["EXTENDED"]}}
    events = compute_transitions("NVDA", yesterday, today)
    assert any(e["event"] == "RISK_ESCALATION" for e in events)


def test_transition_no_yesterday_emits_nothing():
    today =     {"date": "2026-05-08",
                  "setup": "PULLBACK", "trigger": "WAIT", "decision": "STAGING",
                  "raw": {"risk_tags": []}}
    assert compute_transitions("NVDA", None, today) == []
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_lifecycle_history.py -v -k transition
```
Expected: FAIL.

- [ ] **Step 3: Implement `compute_transitions`**

Append to `lifecycle_history.py`:

```python
def compute_transitions(ticker: str,
                         yesterday: Optional[dict],
                         today: dict) -> list[dict]:
    """Diff yesterday's snapshot against today's. Emit events per spec §5.3.

    Five event types:
      SETUP_CHANGE / TRIGGER_CHANGE / DECISION_CHANGE
      FAILED_BREAKOUT (independent — risk_tag presence)
      RISK_ESCALATION (when EXTENDED newly added to risk_tags)
    """
    if yesterday is None:
        return []
    out: list[dict] = []
    date_str = today["date"]

    def _evt(event: str, frm, to):
        out.append({
            "event_id": f"{ticker}_{date_str}_{event}_v1",
            "date":     date_str,
            "ticker":   ticker,
            "event":    event,
            "from":     frm,
            "to":       to,
        })

    if yesterday.get("setup") != today.get("setup"):
        _evt("SETUP_CHANGE", yesterday.get("setup"), today.get("setup"))
    if yesterday.get("trigger") != today.get("trigger"):
        _evt("TRIGGER_CHANGE", yesterday.get("trigger"), today.get("trigger"))
    if yesterday.get("decision") != today.get("decision"):
        _evt("DECISION_CHANGE", yesterday.get("decision"), today.get("decision"))

    today_tags = set((today.get("raw") or {}).get("risk_tags") or [])
    y_tags = set((yesterday.get("raw") or {}).get("risk_tags") or [])

    if "FAILED_BREAKOUT" in today_tags:
        _evt("FAILED_BREAKOUT", None, None)

    if "EXTENDED" in today_tags and "EXTENDED" not in y_tags:
        _evt("RISK_ESCALATION", None, "EXTENDED")

    return out
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_lifecycle_history.py -v
```
Expected: all (≥21) passed.

- [ ] **Step 5: Commit**

```bash
git add lifecycle_history.py tests/test_lifecycle_history.py
git commit -m "feat(lifecycle): compute_transitions with 5 event types"
```

---

## Task 11: `bootstrap_emas` — first-run yfinance pull

**Files:**
- Modify: `lifecycle_history.py`
- Modify: `tests/test_lifecycle_history.py`

- [ ] **Step 1: Append failing bootstrap test (uses fake fetcher)**

```python
from lifecycle_history import bootstrap_active_set


def test_bootstrap_uses_supplied_fetcher_returns_seed_state():
    """When lifecycle_history is missing on first run, bootstrap_active_set
    builds seed state from a momentum-history-style input."""
    momentum_history = {
        "tickers": {
            "NVDA": {"snapshots": [{"date": "2026-05-08", "stage": "MOMENTUM_2"}]},
            "PLTR": {"snapshots": [{"date": "2026-05-07", "stage": "MOMENTUM_1"}]},
        }
    }
    seed = bootstrap_active_set(market="US", momentum_history=momentum_history,
                                  portfolio_tickers=set(), today="2026-05-08")
    # Seed is a state dict ready to receive snapshots — empty tickers map but
    # marker fields populated so subsequent process_universe knows it bootstrapped.
    assert seed["schema_version"] == "1.0.0"
    assert "_bootstrap_meta" in seed
    assert set(seed["_bootstrap_meta"]["seed_tickers"]) == {"NVDA", "PLTR"}
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_lifecycle_history.py -v -k bootstrap
```

- [ ] **Step 3: Implement `bootstrap_active_set`**

Append to `lifecycle_history.py`:

```python
def bootstrap_active_set(*, market: str, momentum_history: dict,
                          portfolio_tickers: set, today: str) -> dict:
    """First-run seed state.

    Creates an empty lifecycle state plus a `_bootstrap_meta` marker recording
    which tickers were known on day-0. The actual snapshot data is built by
    process_universe on the same day's run — bootstrap merely says "these
    tickers will be valid in active_set today even though there is no history".
    """
    seed = compute_active_set(momentum_history=momentum_history,
                                lifecycle_state={"tickers": {}},
                                portfolio_tickers=portfolio_tickers,
                                today=today)
    state = new_empty_state(market)
    state["_bootstrap_meta"] = {
        "bootstrapped_on": today,
        "seed_tickers":    sorted(seed),
    }
    return state
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_lifecycle_history.py -v
```
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add lifecycle_history.py tests/test_lifecycle_history.py
git commit -m "feat(lifecycle): bootstrap_active_set for first-run seed state"
```

---

## Task 12: `process_universe` — orchestrator wiring signal + history

**Files:**
- Modify: `lifecycle_signal.py`
- Test: `tests/test_lifecycle_signal.py`

- [ ] **Step 1: Append failing orchestrator tests**

```python
from lifecycle_signal import process_universe


def _market_data(ticker: str, **overrides) -> dict:
    base = {
        "close": 100.0, "high": 101.0, "low": 99.0, "prev_close": 99.0,
        "ema9": 99.5, "ema21": 98.0, "ema65": 90.0,
        "ema21_slope_5d": 0.5, "ema65_slope_5d": 0.4,
        "rsi14": 60.0, "atr14_pct": 2.0, "volume_ratio": 1.0,
        "change_pct": 1.0, "sector": "Technology",
    }
    base.update(overrides)
    return {ticker: base}


def test_process_universe_returns_per_ticker_evaluation():
    md = _market_data("NVDA")
    result = process_universe(active_set={"NVDA"}, market_data=md,
                                yesterday_state={"tickers": {}}, today="2026-05-08")
    assert "NVDA" in result["snapshots"]
    snap = result["snapshots"]["NVDA"]
    assert snap["setup"] == "TREND_OK"
    assert snap["trigger"] == "WAIT"
    assert snap["decision"] == "STAGING"
    assert "raw" in snap and "close" in snap["raw"]


def test_process_universe_skips_ticker_missing_from_market_data():
    result = process_universe(active_set={"NVDA", "MISSING"}, market_data={},
                                yesterday_state={"tickers": {}}, today="2026-05-08")
    assert "skipped" in result and "MISSING" in result["skipped"]
    assert "NVDA" in result["skipped"]


def test_process_universe_uses_yesterday_for_failed_breakout():
    """Yesterday CONFIRMED_TRIGGER + today close < ema9 → FAILED_BREAKOUT tag."""
    md = _market_data("NVDA",
                       close=99.0, ema9=100.0, ema21=98.0, ema65=90.0,
                       low=98.5, change_pct=-0.5)
    yesterday_state = {"tickers": {"NVDA": {
        "first_seen": "2026-05-07", "last_seen": "2026-05-07",
        "snapshots": [{"date": "2026-05-07",
                        "setup": "PULLBACK",
                        "trigger": "CONFIRMED_TRIGGER",
                        "decision": "ENTER_OK",
                        "raw": {"low": 98.0, "risk_tags": []}}],
    }}}
    result = process_universe(active_set={"NVDA"}, market_data=md,
                                yesterday_state=yesterday_state, today="2026-05-08")
    snap = result["snapshots"]["NVDA"]
    assert "FAILED_BREAKOUT" in snap["raw"]["risk_tags"]
    assert snap["decision"] == "AVOID"
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_lifecycle_signal.py -v -k process_universe
```

- [ ] **Step 3: Implement `process_universe` and helpers**

Append to `lifecycle_signal.py`:

```python
def _build_today_raw_for_signal(md_entry: dict) -> dict:
    """Map fetch_market_data row to lifecycle_signal raw shape.

    fetch_market_data does not yet emit days_sideways / atr14_pct_5d_avg /
    volume_5d_avg / atr14_pct_20d_avg / volume_20d_avg. For Phase A, these
    optional fields are passed through if the upstream provides them; if
    absent, BASE_FORMING simply cannot match — that's acceptable. A later
    Phase A polish task can add them to fetch_market_data if BASE_FORMING
    coverage is too low in real data.
    """
    return {
        "close": md_entry.get("price") or md_entry.get("close"),
        "high":  md_entry.get("high"),
        "low":   md_entry.get("low"),
        "ema9":  md_entry.get("ema9"),
        "ema21": md_entry.get("ema21"),
        "ema65": md_entry.get("ema65"),
        "ema21_slope_5d": md_entry.get("ema21_slope_5d"),
        "ema65_slope_5d": md_entry.get("ema65_slope_5d"),
        "rsi14": md_entry.get("rsi14"),
        "atr14_pct": md_entry.get("atr14_pct"),
        "volume_ratio": md_entry.get("volume_ratio"),
        "change_pct":   md_entry.get("change_pct"),
        "days_sideways":      md_entry.get("days_sideways"),
        "atr14_pct_5d_avg":   md_entry.get("atr14_pct_5d_avg"),
        "atr14_pct_20d_avg":  md_entry.get("atr14_pct_20d_avg"),
        "volume_5d_avg":      md_entry.get("volume_5d_avg"),
        "volume_20d_avg":     md_entry.get("volume_20d_avg"),
        "sector": md_entry.get("sector") or md_entry.get("sector_etf"),
    }


def _make_snapshot(date_str: str, raw: dict, setup: str, trigger: str,
                    decision: str, risk_tags: list[str]) -> dict:
    e9, e21, c = raw.get("ema9"), raw.get("ema21"), raw.get("close")
    return {
        "date":     date_str,
        "setup":    setup,
        "trigger":  trigger,
        "decision": decision,
        "raw": {
            "close": c,
            "high":  raw.get("high"),
            "low":   raw.get("low"),
            "ema9":  e9,
            "ema21": e21,
            "ema65": raw.get("ema65"),
            "dist_ema9_pct":  round(abs(c - e9) / e9 * 100, 4) if (c and e9) else None,
            "dist_ema21_pct": round(abs(c - e21) / e21 * 100, 4) if (c and e21) else None,
            "volume_ratio":   raw.get("volume_ratio"),
            "atr_pct":        raw.get("atr14_pct"),
            "sector":         raw.get("sector"),
            "risk_tags":      risk_tags,
        },
    }


def process_universe(*, active_set: set[str], market_data: dict,
                       yesterday_state: dict, today: str,
                       regime: Optional[str] = None) -> dict:
    """Run setup/trigger/decision/risk_tags across the active set.

    Returns:
      {
        "as_of": today,
        "snapshots": {ticker: snapshot_dict},
        "skipped":   [ticker, ...],
      }
    """
    # market_data may be either a flat ticker -> entry map OR a
    # {"data": {ticker: entry}} envelope from screenshots/market_data_*.json.
    flat = market_data.get("data") if isinstance(market_data, dict) and "data" in market_data else market_data
    snapshots: dict[str, dict] = {}
    skipped: list[str] = []

    for ticker in sorted(active_set):
        entry = (flat or {}).get(ticker)
        if not entry or "error" in entry:
            skipped.append(ticker)
            continue
        today_raw = _build_today_raw_for_signal(entry)
        if today_raw["close"] is None or today_raw["ema9"] is None:
            skipped.append(ticker)
            continue
        y_block = (yesterday_state.get("tickers") or {}).get(ticker)
        y_snap = (y_block or {}).get("snapshots", [])
        yesterday = y_snap[-1] if y_snap else None
        # Yesterday raw for trigger evaluation.
        y_for_trigger = {
            "close": (yesterday or {}).get("raw", {}).get("close"),
            "ema9":  (yesterday or {}).get("raw", {}).get("ema9"),
            "high":  (yesterday or {}).get("raw", {}).get("high"),
        }
        setup = evaluate_setup_state(today_raw)
        trigger = evaluate_trigger_state(today_raw, y_for_trigger, setup)
        risk_tags = compute_risk_tags(today_raw, yesterday)
        decision = evaluate_decision(setup, trigger, risk_tags=risk_tags, regime=regime)
        snapshots[ticker] = _make_snapshot(today, today_raw, setup, trigger,
                                             decision, risk_tags)

    return {"as_of": today, "snapshots": snapshots, "skipped": skipped}
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_lifecycle_signal.py -v
```
Expected: all (≥37) passed.

- [ ] **Step 5: Commit**

```bash
git add lifecycle_signal.py tests/test_lifecycle_signal.py
git commit -m "feat(lifecycle): process_universe orchestrator with skipped list"
```

---

## Task 13: 6 Golden test scenarios

**Files:**
- Create: `tests/test_lifecycle_golden.py`
- Create: `tests/fixtures/lifecycle_golden/` (no files needed — scenarios built inline)

Each Golden scenario builds a synthetic 30-day price history and feeds it through a thin "advance one day at a time" loop, asserting the expected setup/trigger sequence. Spec §9.

- [ ] **Step 1: Write all 6 Golden tests**

```python
# tests/test_lifecycle_golden.py
"""Phase A — Golden regression contract (spec §9).

Each scenario is a synthetic price+indicator history that drives a specific
state-machine path. Any rule change that breaks one of these tests must be
deliberate and the test file must be updated in the same commit.
"""
import pytest

from lifecycle_signal import (
    evaluate_setup_state, evaluate_trigger_state,
    evaluate_decision, compute_risk_tags,
)


# ── Scenario builder helpers ────────────────────────────
def _row(close, high, low, ema9, ema21, ema65, *,
          rsi=50, vol_ratio=1.0, slope65=0.3, slope21=0.3,
          days_sideways=0, atr5=2.0, atr20=2.0, vol5=1e6, vol20=1e6,
          change_pct=0.5):
    return {
        "close": close, "high": high, "low": low,
        "ema9": ema9, "ema21": ema21, "ema65": ema65,
        "rsi14": rsi, "volume_ratio": vol_ratio,
        "ema65_slope_5d": slope65, "ema21_slope_5d": slope21,
        "days_sideways": days_sideways,
        "atr14_pct_5d_avg": atr5, "atr14_pct_20d_avg": atr20,
        "volume_5d_avg": vol5, "volume_20d_avg": vol20,
        "atr14_pct": atr5,
        "change_pct": change_pct,
        "sector": "Technology",
    }


# ── Scenario 1: cooling_off — EXTENDED → TREND_OK → PULLBACK ───────────
def test_golden_cooling_off():
    days = [
        _row(close=120, high=121, low=118, ema9=105, ema21=98, ema65=90, rsi=78),  # EXTENDED
        _row(close=108, high=110, low=106, ema9=106, ema21=99, ema65=91),           # TREND_OK
        _row(close=104, high=107, low=103, ema9=105, ema21=100, ema65=91),          # PULLBACK
    ]
    setups = [evaluate_setup_state(d) for d in days]
    assert setups == ["EXTENDED", "TREND_OK", "PULLBACK"]


# ── Scenario 2: clean_entry — TREND_OK → PULLBACK → EARLY → CONFIRMED ──
def test_golden_clean_entry():
    days = [
        _row(close=100, high=101, low=99, ema9=99.5, ema21=97, ema65=90),
        _row(close=97.5, high=98, low=97, ema9=99,    ema21=97, ema65=90),
        _row(close=99.6, high=99.8, low=97.5, ema9=99, ema21=97, ema65=90),
        _row(close=101.5, high=101.8, low=100, ema9=99, ema21=97, ema65=90,
              vol_ratio=1.5),
    ]
    setups = [evaluate_setup_state(d) for d in days]
    assert setups[0] == "TREND_OK"
    # Day 2 close (97.5) is below ema9 (99) by ~1.5%, above ema21, alignment ok → PULLBACK.
    assert setups[1] == "PULLBACK"
    # Day 3 close (99.6) within 0.4% of ema9, above ema21 → PULLBACK.
    assert setups[2] == "PULLBACK"
    # Day 4 close (101.5), 2.5% above ema9 → still PULLBACK (≤3%).
    assert setups[3] == "PULLBACK"

    # Triggers — pass yesterday's row as the "yesterday" arg.
    trig_d3 = evaluate_trigger_state(days[2], days[1], setups[2])
    assert trig_d3 == "EARLY_TRIGGER"  # day-2 close 97.5 ≤ ema9 99, day-3 close 99.6 > 99
    trig_d4 = evaluate_trigger_state(days[3], days[2], setups[3])
    assert trig_d4 == "CONFIRMED_TRIGGER"  # vol 1.5x + close in upper 20% (101.5 vs high 101.8/low 100)
    assert evaluate_decision(setups[3], trig_d4) == "ENTER_OK"


# ── Scenario 3: failed_breakout ───────────────────────────────────────
def test_golden_failed_breakout():
    confirmed_day = _row(close=101.5, high=101.8, low=100, ema9=99, ema21=97, ema65=90,
                          vol_ratio=1.5)
    today = _row(close=98.5, high=99.5, low=97.5, ema9=100, ema21=97, ema65=90,
                  change_pct=-3.0)
    yesterday_snapshot = {
        "trigger": "CONFIRMED_TRIGGER",
        "raw": {"close": 101.5, "ema9": 99, "high": 101.8, "low": 100,
                 "risk_tags": []},
    }
    setup = evaluate_setup_state(today)
    trig = evaluate_trigger_state(today, yesterday_snapshot["raw"], setup)
    risk_tags = compute_risk_tags(today, yesterday_snapshot)
    assert trig == "WAIT"
    assert "FAILED_BREAKOUT" in risk_tags
    assert evaluate_decision(setup, trig, risk_tags=risk_tags) == "AVOID"


# ── Scenario 4: structure_break — TREND_OK → BROKEN ────────────────────
def test_golden_structure_break():
    pre = _row(close=100, high=101, low=99, ema9=99.5, ema21=97, ema65=90)
    post = _row(close=92, high=94, low=91, ema9=95, ema21=88, ema65=90)
    assert evaluate_setup_state(pre) == "TREND_OK"
    assert evaluate_setup_state(post) == "BROKEN"


# ── Scenario 5: weak_volume — PULLBACK + reclaim but vol < 1.2 → EARLY only ──
def test_golden_weak_volume():
    yesterday = _row(close=98.5, high=99, low=97.5, ema9=99, ema21=97, ema65=90)
    today = _row(close=99.6, high=100, low=98, ema9=99, ema21=97, ema65=90,
                  vol_ratio=0.9)
    setup = evaluate_setup_state(today)
    assert setup == "PULLBACK"
    trig = evaluate_trigger_state(today, yesterday, setup)
    assert trig == "EARLY_TRIGGER"


# ── Scenario 6: gap_up_exhaustion — close in lower half stays WAIT ────
def test_golden_gap_up_exhaustion():
    yesterday = _row(close=99.5, high=100, low=98, ema9=99, ema21=97, ema65=90)
    today = _row(close=100.5, high=104, low=100, ema9=99, ema21=97, ema65=90,
                  vol_ratio=2.0)
    # close 100.5 vs (high*0.8 + low*0.2) = 103.2 — below upper band.
    # AND close 100.5 > yesterday_close 99.5 + ema9 99 → ema9 reclaim does
    # NOT fire (yesterday_close 99.5 > ema9 99). prior-high 100 < today-high 104
    # → EARLY_TRIGGER fires. CONFIRMED gate fails on close-position.
    setup = evaluate_setup_state(today)
    trig = evaluate_trigger_state(today, yesterday, setup)
    assert trig == "EARLY_TRIGGER"
    # That's per the spec — the close-in-upper-20 gate stops CONFIRMED, not EARLY.
```

- [ ] **Step 2: Run Golden tests**

```
pytest tests/test_lifecycle_golden.py -v
```
Expected: 6 passed. If any fail, the rule implementation is wrong — fix the rule, not the test.

- [ ] **Step 3: Commit**

```bash
git add tests/test_lifecycle_golden.py
git commit -m "test(lifecycle): add 6 Golden scenarios — regression contract"
```

---

## Task 14: `lifecycle_report.generate_lifecycle_pages` (Jinja2 render)

**Files:**
- Create: `lifecycle_report.py`
- Test: `tests/test_lifecycle_report.py`

- [ ] **Step 1: Write failing render test**

```python
# tests/test_lifecycle_report.py
"""Phase A — lifecycle page render."""
import os
from pathlib import Path

import pytest

from lifecycle_report import generate_lifecycle_pages, build_page_context


def _result(market: str, snapshots: dict, transitions=None):
    return {
        "market":   market,
        "as_of":    "2026-05-08",
        "snapshots": snapshots,
        "transitions": transitions or [],
        "skipped":  [],
    }


def test_build_page_context_groups_by_decision():
    snaps = {
        "NVDA": {"date": "2026-05-08", "setup": "PULLBACK", "trigger": "CONFIRMED_TRIGGER",
                  "decision": "ENTER_OK",
                  "raw": {"close": 100, "ema9": 99, "ema21": 95, "ema65": 90,
                           "dist_ema9_pct": 1.0, "dist_ema21_pct": 5.0,
                           "volume_ratio": 1.5, "atr_pct": 2.0,
                           "sector": "Technology", "risk_tags": []}},
        "BAD":  {"date": "2026-05-08", "setup": "BROKEN", "trigger": "WAIT",
                  "decision": "AVOID",
                  "raw": {"close": 50, "ema9": 60, "ema21": 65, "ema65": 70,
                           "dist_ema9_pct": 16.0, "dist_ema21_pct": 23.0,
                           "volume_ratio": 0.5, "atr_pct": 4.0,
                           "sector": "Energy", "risk_tags": []}},
    }
    ctx = build_page_context(_result("US", snaps))
    assert {r["ticker"] for r in ctx["enter_ok"]} == {"NVDA"}
    # BROKEN/AVOID gets routed to broken_table per spec §10.1 [6].
    assert {r["ticker"] for r in ctx["broken_table"]} == {"BAD"}
    assert ctx["new_confirmed"][0]["ticker"] == "NVDA"  # trigger_age 0


def test_build_page_context_sorts_enter_ok_by_trigger_age_then_volume():
    # Two ENTER_OK tickers — newer trigger appears first.
    snaps = {
        "OLD": {"date": "2026-05-08", "setup": "PULLBACK", "trigger": "CONFIRMED_TRIGGER",
                 "decision": "ENTER_OK",
                 "raw": {"close": 100, "ema9": 99, "ema21": 95, "ema65": 90,
                          "dist_ema9_pct": 1.0, "dist_ema21_pct": 5.0,
                          "volume_ratio": 1.3, "atr_pct": 2.0,
                          "sector": "Tech", "risk_tags": []}},
        "NEW": {"date": "2026-05-08", "setup": "PULLBACK", "trigger": "CONFIRMED_TRIGGER",
                 "decision": "ENTER_OK",
                 "raw": {"close": 100, "ema9": 99, "ema21": 95, "ema65": 90,
                          "dist_ema9_pct": 1.0, "dist_ema21_pct": 5.0,
                          "volume_ratio": 2.0, "atr_pct": 2.0,
                          "sector": "Tech", "risk_tags": []}},
    }
    # Inject lifecycle history so OLD has trigger_age=2 and NEW has 0.
    lifecycle_state = {"tickers": {
        "OLD": {"first_seen": "2026-05-06", "last_seen": "2026-05-08",
                 "snapshots": [
                    {"date": "2026-05-06", "setup": "PULLBACK", "trigger": "CONFIRMED_TRIGGER",
                      "decision": "ENTER_OK", "raw": {}},
                    {"date": "2026-05-07", "setup": "PULLBACK", "trigger": "WAIT",
                      "decision": "EARLY", "raw": {}},
                    {"date": "2026-05-08", "setup": "PULLBACK", "trigger": "CONFIRMED_TRIGGER",
                      "decision": "ENTER_OK", "raw": {}},
                 ]},
        "NEW": {"first_seen": "2026-05-08", "last_seen": "2026-05-08",
                 "snapshots": [
                    {"date": "2026-05-08", "setup": "PULLBACK", "trigger": "CONFIRMED_TRIGGER",
                      "decision": "ENTER_OK", "raw": {}},
                 ]},
    }}
    ctx = build_page_context(_result("US", snaps), lifecycle_state=lifecycle_state)
    assert [r["ticker"] for r in ctx["enter_ok"]] == ["NEW", "OLD"]


def test_generate_lifecycle_pages_writes_html(tmp_path: Path):
    snaps = {"NVDA": {"date": "2026-05-08", "setup": "TREND_OK", "trigger": "WAIT",
                       "decision": "STAGING",
                       "raw": {"close": 100, "ema9": 99, "ema21": 95, "ema65": 90,
                                "dist_ema9_pct": 1.0, "dist_ema21_pct": 5.0,
                                "volume_ratio": 1.0, "atr_pct": 2.0,
                                "sector": "Tech", "risk_tags": []}}}
    paths = generate_lifecycle_pages(
        us_result=_result("US", snaps), kr_result=None,
        output_dir=str(tmp_path), template_dir=None)
    assert "us" in paths
    assert os.path.exists(paths["us"])
    html = Path(paths["us"]).read_text(encoding="utf-8")
    assert "NVDA" in html
    assert "STAGING" in html


def test_generate_lifecycle_pages_skips_when_result_none(tmp_path: Path):
    paths = generate_lifecycle_pages(us_result=None, kr_result=None,
                                       output_dir=str(tmp_path), template_dir=None)
    assert paths == {}
```

- [ ] **Step 2: Run failing test**

```
pytest tests/test_lifecycle_report.py -v
```
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `lifecycle_report.py` (depends on templates from Task 15)**

```python
# lifecycle_report.py
"""Phase A — lifecycle page renderer.

generate_lifecycle_pages(us_result, kr_result, output_dir) → {market: path}
"""
from __future__ import annotations

import os
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from lifecycle_config import LIFECYCLE_VERSION
from lifecycle_history import derive_fields


def _attach_derived(snap: dict, ticker: str,
                     lifecycle_state: Optional[dict]) -> dict:
    out = dict(snap)
    if lifecycle_state and ticker in (lifecycle_state.get("tickers") or {}):
        derived = derive_fields(lifecycle_state["tickers"][ticker])
    else:
        derived = {"setup_streak": 1, "days_in_pullback": 0, "trigger_age_days": None}
    out["setup_streak"]     = derived["setup_streak"]
    out["days_in_pullback"] = derived["days_in_pullback"]
    out["trigger_age_days"] = derived["trigger_age_days"]
    return out


def build_page_context(result: dict,
                         lifecycle_state: Optional[dict] = None) -> dict:
    enter_ok, early, staging, avoid, broken_table = [], [], [], [], []
    new_confirmed = []
    for ticker, snap in (result.get("snapshots") or {}).items():
        row = _attach_derived(snap, ticker, lifecycle_state)
        row["ticker"] = ticker
        d = snap["decision"]
        s = snap["setup"]
        if s == "BROKEN":
            broken_table.append(row)
            continue
        if d == "ENTER_OK":
            enter_ok.append(row)
            if (row["trigger_age_days"] or 99) == 0 and snap["trigger"] == "CONFIRMED_TRIGGER":
                new_confirmed.append(row)
        elif d == "EARLY":
            early.append(row)
        elif d == "STAGING":
            staging.append(row)
        else:
            avoid.append(row)

    enter_ok.sort(key=lambda r: ((r["trigger_age_days"] if r["trigger_age_days"] is not None else 999),
                                   -(r["raw"].get("volume_ratio") or 0)))
    early.sort(key=lambda r: -(r["raw"].get("volume_ratio") or 0))
    staging.sort(key=lambda r: -(r["setup_streak"] or 0))

    return {
        "market":       result.get("market", "US"),
        "as_of":        result.get("as_of"),
        "version":      LIFECYCLE_VERSION,
        "new_confirmed": new_confirmed,
        "enter_ok":     enter_ok,
        "early":        early,
        "staging":      staging,
        "avoid":        avoid,
        "broken_table": broken_table,
        "transitions":  (result.get("transitions") or [])[-50:],
    }


def _render(market: str, result: dict, output_dir: str,
              template_dir: Optional[str], lifecycle_state: Optional[dict]) -> str:
    if template_dir is None:
        template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)
    tmpl = env.get_template(f"lifecycle_{market.lower()}.html")
    ctx = build_page_context(result, lifecycle_state=lifecycle_state)
    html = tmpl.render(**ctx)
    os.makedirs(output_dir, exist_ok=True)
    fname = f"lifecycle_{market.lower()}_{result['as_of']}.html"
    path = os.path.join(output_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def generate_lifecycle_pages(*, us_result: Optional[dict],
                                kr_result: Optional[dict],
                                output_dir: str,
                                template_dir: Optional[str] = None,
                                us_state: Optional[dict] = None,
                                kr_state: Optional[dict] = None) -> dict[str, str]:
    out: dict[str, str] = {}
    if us_result and us_result.get("snapshots"):
        out["us"] = _render("US", us_result, output_dir, template_dir, us_state)
    if kr_result and kr_result.get("snapshots"):
        out["kr"] = _render("KR", kr_result, output_dir, template_dir, kr_state)
    return out
```

- [ ] **Step 4: Don't run tests yet — templates needed**

`generate_lifecycle_pages` will fail without the templates created in Task 15. The render test in this task will pass only after Task 15 is complete. Move on.

- [ ] **Step 5: Commit module-only progress**

```bash
git add lifecycle_report.py tests/test_lifecycle_report.py
git commit -m "feat(lifecycle): lifecycle_report module + page-context tests"
```

---

## Task 15: `templates/lifecycle_us.html` + `templates/lifecycle_kr.html`

**Files:**
- Create: `templates/lifecycle_us.html`
- Create: `templates/lifecycle_kr.html`

- [ ] **Step 1: Write `templates/lifecycle_us.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Lifecycle US — {{ as_of }}</title>
<style>
  body { font-family: -apple-system, "Segoe UI", sans-serif; margin: 24px; color: #1a1a1a; }
  h1 { margin-bottom: 4px; }
  .as-of { color: #666; margin-bottom: 24px; }
  .card { border-radius: 8px; padding: 12px 16px; margin: 8px 0; }
  .card h3 { margin: 0 0 8px 0; }
  .card.enter-ok { background: #ecfdf5; border-left: 4px solid #10b981; }
  .card.early    { background: #fef3c7; border-left: 4px solid #f59e0b; }
  .card.staging  { background: #f3f4f6; border-left: 4px solid #9ca3af; }
  .card.avoid    { background: #fee2e2; border-left: 4px solid #ef4444; }
  .new-confirmed { background: #dbeafe; border-left: 4px solid #2563eb; padding: 12px 16px; margin: 16px 0; border-radius: 8px; }
  table { border-collapse: collapse; margin-top: 12px; width: 100%; font-size: 13px; }
  th, td { border-bottom: 1px solid #e5e7eb; padding: 6px 8px; text-align: left; }
  th { background: #f9fafb; }
  details summary { cursor: pointer; padding: 6px 0; color: #444; }
  .placeholder { background: #fff7ed; border-left: 4px solid #fb923c; padding: 12px 16px; margin: 8px 0; color: #92400e; border-radius: 6px; }
  .footer-note { color: #888; font-size: 12px; margin-top: 24px; }
  .recommended-size { color: #888; font-style: italic; font-size: 12px; }
</style>
</head>
<body>

<h1>🇺🇸 Lifecycle US</h1>
<div class="as-of">As of {{ as_of }} · {{ version }}</div>

<!-- Section [1]: MARKET STATE — Phase B placeholder -->
<div class="placeholder">
  <strong>[1] MARKET STATE</strong> — Market regime classifier coming in Phase B.
</div>

<!-- Section [3]: NEW CONFIRMED TODAY -->
{% if new_confirmed %}
<div class="new-confirmed">
  <strong>🆕 NEW CONFIRMED TODAY ({{ new_confirmed|length }})</strong>:
  {% for r in new_confirmed %}<a href="#row-{{ r.ticker }}">{{ r.ticker }}</a>{% if not loop.last %} · {% endif %}{% endfor %}
</div>
{% endif %}

<!-- Section [2]: ACTION PANEL -->
<div class="card enter-ok">
  <h3>🟢 ENTER_OK ({{ enter_ok|length }})</h3>
  {% if enter_ok %}{% for r in enter_ok %}{{ r.ticker }}{% if not loop.last %} · {% endif %}{% endfor %}<br>
  <span class="recommended-size">Recommended size: TBD — Phase C</span>
  {% else %}<em>none</em>{% endif %}
</div>
<div class="card early">
  <h3>🟡 EARLY ({{ early|length }})</h3>
  {% if early %}{% for r in early %}{{ r.ticker }}{% if not loop.last %} · {% endif %}{% endfor %}{% else %}<em>none</em>{% endif %}
</div>
<details><summary>⚪ STAGING ({{ staging|length }})</summary>
  <div class="card staging">{% for r in staging %}{{ r.ticker }}{% if not loop.last %} · {% endif %}{% endfor %}</div>
</details>
<details><summary>🔴 AVOID ({{ avoid|length }})</summary>
  <div class="card avoid">{% for r in avoid %}{{ r.ticker }}{% if not loop.last %} · {% endif %}{% endfor %}</div>
</details>

<!-- Section [4]: STATE TRANSITIONS -->
<h2>State transitions (last 50)</h2>
{% if transitions %}
<table>
  <thead><tr><th>Date</th><th>Ticker</th><th>Event</th><th>From</th><th>To</th></tr></thead>
  <tbody>
  {% for t in transitions|reverse %}
    <tr><td>{{ t.date }}</td><td>{{ t.ticker }}</td><td>{{ t.event }}</td>
        <td>{{ t['from'] or '—' }}</td><td>{{ t['to'] or '—' }}</td></tr>
  {% endfor %}
  </tbody>
</table>
{% else %}<p><em>No transitions yet.</em></p>{% endif %}

<!-- Section [5]: MAIN TABLE -->
<h2>Active set</h2>
<table>
  <thead>
    <tr>
      <th>Ticker</th><th>Sector</th><th>Setup</th><th>Trigger</th><th>Decision</th>
      <th>trig_age</th><th>dist_ema9 %</th><th>dist_ema21 %</th>
      <th>vol_ratio</th><th>atr %</th><th>days_in_pb</th><th>setup_streak</th>
      <th>risk_tags</th>
    </tr>
  </thead>
  <tbody>
  {% for group in [enter_ok, early, staging, avoid] %}{% for r in group %}
    <tr id="row-{{ r.ticker }}">
      <td><strong>{{ r.ticker }}</strong></td>
      <td>{{ r.raw.sector or '—' }}</td>
      <td>{{ r.setup }}</td>
      <td>{{ r.trigger }}</td>
      <td>{{ r.decision }}</td>
      <td>{{ r.trigger_age_days if r.trigger_age_days is not none else '—' }}</td>
      <td>{{ '%.2f'|format(r.raw.dist_ema9_pct) if r.raw.dist_ema9_pct is not none else '—' }}</td>
      <td>{{ '%.2f'|format(r.raw.dist_ema21_pct) if r.raw.dist_ema21_pct is not none else '—' }}</td>
      <td>{{ '%.2f'|format(r.raw.volume_ratio) if r.raw.volume_ratio is not none else '—' }}</td>
      <td>{{ '%.2f'|format(r.raw.atr_pct) if r.raw.atr_pct is not none else '—' }}</td>
      <td>{{ r.days_in_pullback }}</td>
      <td>{{ r.setup_streak }}</td>
      <td>{{ r.raw.risk_tags|join(', ') if r.raw.risk_tags else '—' }}</td>
    </tr>
  {% endfor %}{% endfor %}
  </tbody>
</table>

<!-- Section [6]: FAILED / BROKEN -->
{% if broken_table %}
<details><summary>FAILED / BROKEN ({{ broken_table|length }})</summary>
  <table>
    <thead><tr><th>Ticker</th><th>Sector</th><th>Setup</th><th>dist_ema9 %</th>
                <th>dist_ema21 %</th><th>risk_tags</th></tr></thead>
    <tbody>
    {% for r in broken_table %}
      <tr><td>{{ r.ticker }}</td><td>{{ r.raw.sector or '—' }}</td>
          <td>{{ r.setup }}</td>
          <td>{{ '%.2f'|format(r.raw.dist_ema9_pct) if r.raw.dist_ema9_pct is not none else '—' }}</td>
          <td>{{ '%.2f'|format(r.raw.dist_ema21_pct) if r.raw.dist_ema21_pct is not none else '—' }}</td>
          <td>{{ r.raw.risk_tags|join(', ') if r.raw.risk_tags else '—' }}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
</details>
{% endif %}

<p class="footer-note">
  Page footer: each market's date stamp uses its own local close.
  Lifecycle is advisory — no auto-trading. Composite scores are forbidden by design.
</p>

</body>
</html>
```

- [ ] **Step 2: Write `templates/lifecycle_kr.html`**

Identical structure to `lifecycle_us.html` except for the heading. Easiest: copy + change header.

```bash
cp templates/lifecycle_us.html templates/lifecycle_kr.html
```

Then in `templates/lifecycle_kr.html`, change:
```
<h1>🇺🇸 Lifecycle US</h1>
```
to:
```
<h1>🇰🇷 Lifecycle KR</h1>
```

- [ ] **Step 3: Run the lifecycle_report tests**

```
pytest tests/test_lifecycle_report.py -v
```
Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add templates/lifecycle_us.html templates/lifecycle_kr.html
git commit -m "feat(lifecycle): add lifecycle US/KR Jinja2 templates"
```

---

## Task 16: Pipeline Step 4c4 (US lifecycle) and Step 4c5 (KR lifecycle)

**Files:**
- Modify: `pipeline.py`
- Test: `tests/test_pipeline_lifecycle_step.py`

- [ ] **Step 1: Write failing pipeline-step test**

```python
# tests/test_pipeline_lifecycle_step.py
"""Phase A — lifecycle Step 4c4/4c5 wiring."""
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_pipeline_calls_lifecycle_step_when_market_data_available(tmp_path: Path,
                                                                       monkeypatch):
    """Verify pipeline.py imports and calls run_lifecycle_us / run_lifecycle_kr.

    This is a structural test — we patch the orchestrator entry point and
    confirm pipeline.py calls it. The real flow runs in test_lifecycle_e2e.
    """
    import pipeline
    monkeypatch.setattr(pipeline.os.environ, "get",
                         lambda k, d=None: {"SKIP_SCANNERS": "1",
                                              "SKIP_OCR": "1"}.get(k, d))
    # Easier: just confirm the symbols exist in pipeline source.
    src = Path("pipeline.py").read_text(encoding="utf-8")
    assert "[Step 4c4]" in src
    assert "[Step 4c5]" in src
    assert "run_lifecycle_us" in src or "from lifecycle_signal import" in src
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_pipeline_lifecycle_step.py -v
```
Expected: FAIL.

- [ ] **Step 3: Add an entry-point helper in `lifecycle_signal.py`**

Append to `lifecycle_signal.py`:

```python
def run_lifecycle(market: str, *, project_dir: str, market_data: dict,
                    momentum_history_path: str, portfolio_tickers: set,
                    today: str) -> dict:
    """One-call entry: load history, compute active set, evaluate, write back.

    Returns: { status, market, as_of, snapshots, transitions, skipped, ... }
    """
    import json
    import os as _os
    from lifecycle_history import (
        load_lifecycle_history, save_lifecycle_history,
        compute_active_set, append_snapshot, append_transition,
        compute_transitions, bootstrap_active_set,
    )

    history_dir = _os.path.join(project_dir, "history")
    _os.makedirs(history_dir, exist_ok=True)
    state_path = _os.path.join(history_dir, f"lifecycle_history_{market.lower()}.json")

    # Momentum history (read-only seed for active set).
    momentum_state = {"tickers": {}}
    if _os.path.exists(momentum_history_path):
        try:
            with open(momentum_history_path, "rb") as f:
                momentum_state = json.loads(f.read().rstrip(b" \t\n\r\x00").decode("utf-8"))
        except Exception as e:
            print(f"[lifecycle:{market}] WARN momentum history load failed ({e})")

    state = load_lifecycle_history(state_path, market=market)
    if not state["tickers"] and not state.get("_bootstrap_meta"):
        state = bootstrap_active_set(market=market,
                                       momentum_history=momentum_state,
                                       portfolio_tickers=portfolio_tickers,
                                       today=today)

    active = compute_active_set(momentum_history=momentum_state,
                                  lifecycle_state=state,
                                  portfolio_tickers=portfolio_tickers,
                                  today=today)
    if not active:
        return {"status": "ok", "market": market, "as_of": today,
                  "snapshots": {}, "transitions": [], "skipped": [],
                  "active_set_size": 0}

    proc = process_universe(active_set=active, market_data=market_data,
                              yesterday_state=state, today=today)

    new_transitions: list[dict] = []
    for ticker, today_snap in proc["snapshots"].items():
        y_block = (state.get("tickers") or {}).get(ticker)
        y_snap_list = (y_block or {}).get("snapshots", [])
        y_snap = y_snap_list[-1] if y_snap_list else None
        events = compute_transitions(ticker, y_snap, today_snap)
        new_transitions.extend(events)
        append_snapshot(state, ticker, today_snap)

    state["transitions"].extend(new_transitions)
    save_lifecycle_history(state, state_path)

    return {
        "status": "ok",
        "market": market,
        "as_of":  today,
        "snapshots":   proc["snapshots"],
        "transitions": new_transitions,
        "skipped":     proc["skipped"],
        "active_set_size": len(active),
        "state":       state,  # for the report renderer
    }
```

- [ ] **Step 4: Wire Step 4c4 + 4c5 into `pipeline.py`**

In `pipeline.py`, immediately after the existing Step 4c3 block (ends around line 422 with `stop_result_me = None` in the `except`), insert:

```python
        # Step 4c4: Lifecycle US (Phase A — Trend Structure + Setup/Trigger)
        # Pure-additive. Failure must NOT block Step 5.
        skip_lifecycle = os.environ.get("SKIP_LIFECYCLE", "").lower() in ("1", "true", "yes")
        lifecycle_us_result = None
        if skip_lifecycle:
            print("[Step 4c4] SKIP_LIFECYCLE=1 — lifecycle US 스킵")
        else:
            print("[Step 4c4] Lifecycle US (setup/trigger/decision)...")
            try:
                from lifecycle_signal import run_lifecycle
                _portfolio_tickers = {h["ticker"] for h in _parse_portfolio_for_report(portfolio_path)}
                _mom_us = os.path.join(project_dir, "history", "scanner_momentum_us_history.json")
                lifecycle_us_result = run_lifecycle(
                    "US", project_dir=project_dir,
                    market_data=market_data,
                    momentum_history_path=_mom_us,
                    portfolio_tickers=_portfolio_tickers,
                    today=today,
                )
                if lifecycle_us_result.get("status") == "ok":
                    n_snap = len(lifecycle_us_result["snapshots"])
                    n_trans = len(lifecycle_us_result["transitions"])
                    print(f"  OK [4c4] US: snapshots={n_snap} transitions={n_trans} "
                          f"active_set={lifecycle_us_result['active_set_size']}")
            except Exception as e:
                import traceback as _tb
                _tb.print_exc()
                print(f"  WARN [4c4] lifecycle US failed: {e}")
                lifecycle_us_result = None

        # Step 4c5: Lifecycle KR
        lifecycle_kr_result = None
        if skip_lifecycle:
            print("[Step 4c5] SKIP_LIFECYCLE=1 — lifecycle KR 스킵")
        else:
            print("[Step 4c5] Lifecycle KR (setup/trigger/decision)...")
            try:
                from lifecycle_signal import run_lifecycle
                _portfolio_tickers = {h["ticker"] for h in _parse_portfolio_for_report(portfolio_path)}
                _mom_kr = os.path.join(project_dir, "history", "scanner_momentum_kr_history.json")
                lifecycle_kr_result = run_lifecycle(
                    "KR", project_dir=project_dir,
                    market_data=market_data,
                    momentum_history_path=_mom_kr,
                    portfolio_tickers=_portfolio_tickers,
                    today=today,
                )
                if lifecycle_kr_result.get("status") == "ok":
                    n_snap = len(lifecycle_kr_result["snapshots"])
                    n_trans = len(lifecycle_kr_result["transitions"])
                    print(f"  OK [4c5] KR: snapshots={n_snap} transitions={n_trans} "
                          f"active_set={lifecycle_kr_result['active_set_size']}")
            except Exception as e:
                import traceback as _tb
                _tb.print_exc()
                print(f"  WARN [4c5] lifecycle KR failed: {e}")
                lifecycle_kr_result = None

```

- [ ] **Step 5: Run the structural test**

```
pytest tests/test_pipeline_lifecycle_step.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add lifecycle_signal.py pipeline.py tests/test_pipeline_lifecycle_step.py
git commit -m "feat(lifecycle): pipeline Step 4c4/4c5 + run_lifecycle entry point"
```

---

## Task 17: Wire `lifecycle_us`/`lifecycle_kr` into `report_generator` (nav)

**Files:**
- Modify: `report_generator.py`
- Modify: `pipeline.py` (call site for `generate_report`)
- Test: `tests/test_lifecycle_report_nav.py`

- [ ] **Step 1: Write failing nav test**

```python
# tests/test_lifecycle_report_nav.py
"""Lifecycle nav links surface in the main portfolio report."""
from pathlib import Path


def test_generate_report_accepts_lifecycle_kwargs():
    import inspect
    from report_generator import generate_report
    sig = inspect.signature(generate_report)
    assert "lifecycle_us" in sig.parameters
    assert "lifecycle_kr" in sig.parameters


def test_template_contains_lifecycle_nav_link():
    """Sanity: report_template.html should reference lifecycle_us / kr when
    pages exist. We only check the template wires the var; rendering is
    integration-tested in the e2e suite."""
    src = Path("templates/report_template.html").read_text(encoding="utf-8")
    assert "lifecycle_us_page" in src or "lifecycle_us" in src
```

- [ ] **Step 2: Run failing**

```
pytest tests/test_lifecycle_report_nav.py -v
```
Expected: FAIL.

- [ ] **Step 3: Add `lifecycle_us` / `lifecycle_kr` kwargs to `generate_report`**

In `report_generator.py:255-273`, extend the signature:

```python
def generate_report(
    market_data: dict,
    portfolio: list,
    signals: dict,
    history: dict,
    prev_signals: dict,
    output_path: str,
    template_dir: str | None = None,
    scanner_sp100: dict | None = None,
    scanner_etf: dict | None = None,
    scanner_kospi: dict | None = None,
    backtest_analysis: dict | None = None,
    nav_portfolio: str | None = None,
    active_nav: str = "portfolio",
    benchmark_data: dict | None = None,
    momentum_us: dict | None = None,
    momentum_kr: dict | None = None,
    portfolio_stop_result=None,
    lifecycle_us: dict | None = None,
    lifecycle_kr: dict | None = None,
) -> str:
```

Then near the existing `context["portfolio_stop_summary"]` block (line 506-514), add:

```python
    # ── Lifecycle pages ────────────────────────
    _lc_date = (lifecycle_us or {}).get("as_of") or (lifecycle_kr or {}).get("as_of") or date_str
    context["lifecycle_us_page"] = (
        f"lifecycle_us_{_lc_date}.html"
        if lifecycle_us and lifecycle_us.get("status") == "ok" and lifecycle_us.get("snapshots")
        else None
    )
    context["lifecycle_kr_page"] = (
        f"lifecycle_kr_{_lc_date}.html"
        if lifecycle_kr and lifecycle_kr.get("status") == "ok" and lifecycle_kr.get("snapshots")
        else None
    )
```

- [ ] **Step 4: Add nav link in `templates/report_template.html`**

Find the existing nav block in `templates/report_template.html` (where `momentum_us_page` / `portfolio_stop_page` etc. are linked). Add:

```html
{% if lifecycle_us_page %}
  <a href="{{ lifecycle_us_page }}" class="nav-link">→ Lifecycle US</a>
{% endif %}
{% if lifecycle_kr_page %}
  <a href="{{ lifecycle_kr_page }}" class="nav-link">→ Lifecycle KR</a>
{% endif %}
```

(Use `grep -n "momentum_us_page" templates/report_template.html` to find the exact location of the existing momentum nav and place these next to it.)

- [ ] **Step 5: Pass lifecycle results from pipeline to `generate_report` + `generate_lifecycle_pages`**

In `pipeline.py` Step 5 (search for `generate_report(` near line ~480-700; there are several call sites — modify each that hands off the main report):

```python
# At the call site
generate_report(
    ...
    lifecycle_us=lifecycle_us_result,
    lifecycle_kr=lifecycle_kr_result,
)
```

And after `generate_report` returns, render the lifecycle pages:

```python
try:
    from lifecycle_report import generate_lifecycle_pages
    _lc_paths = generate_lifecycle_pages(
        us_result=lifecycle_us_result, kr_result=lifecycle_kr_result,
        output_dir=os.path.join(project_dir, "reports"),
        us_state=(lifecycle_us_result or {}).get("state"),
        kr_state=(lifecycle_kr_result or {}).get("state"),
    )
    for m, p in _lc_paths.items():
        print(f"  Generated {m}: {p}")
except Exception as e:
    print(f"  WARN lifecycle page render failed: {e}")
```

(Place this after the existing `generate_portfolio_stop_page(...)` call.)

- [ ] **Step 6: Run tests**

```
pytest tests/test_lifecycle_report_nav.py -v
```
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add report_generator.py templates/report_template.html pipeline.py tests/test_lifecycle_report_nav.py
git commit -m "feat(lifecycle): wire lifecycle pages into report nav + page render"
```

---

## Task 18: Telegram brief — `send_lifecycle_brief`

**Files:**
- Modify: `telegram_sender.py`
- Modify: `pipeline.py` (call site)
- Test: `tests/test_telegram_lifecycle_brief.py`

- [ ] **Step 1: Write failing brief test**

```python
# tests/test_telegram_lifecycle_brief.py
"""Phase A — lifecycle Telegram brief format."""
from telegram_sender import _format_lifecycle_message


def _result(market, new_confirmed_tickers, enter_ok_count, early_count, failed_count):
    snaps = {}
    for tk in new_confirmed_tickers:
        snaps[tk] = {"setup": "PULLBACK", "trigger": "CONFIRMED_TRIGGER",
                       "decision": "ENTER_OK", "raw": {"risk_tags": []}}
    return {
        "market": market, "as_of": "2026-05-08",
        "snapshots": snaps,
        "_brief_summary": {
            "new_confirmed": new_confirmed_tickers,
            "enter_ok": enter_ok_count,
            "early": early_count,
            "failed_breakout": failed_count,
        },
    }


def test_brief_contains_us_and_kr_sections():
    us = _result("US", ["NVDA", "PLTR"], enter_ok_count=7, early_count=12,
                  failed_count=2)
    kr = _result("KR", ["005930.KS"], enter_ok_count=4, early_count=6,
                  failed_count=0)
    msg = _format_lifecycle_message(us, kr,
                                       base_url="https://example.com/",
                                       date_str="2026-05-08")
    assert "🇺🇸 US" in msg
    assert "🇰🇷 KR" in msg
    assert "NVDA" in msg
    assert "005930.KS" in msg
    assert "https://example.com/lifecycle_us_2026-05-08.html" in msg
    assert "https://example.com/lifecycle_kr_2026-05-08.html" in msg


def test_brief_omits_zero_lines():
    us = _result("US", [], enter_ok_count=0, early_count=0, failed_count=0)
    kr = _result("KR", [], enter_ok_count=0, early_count=0, failed_count=0)
    msg = _format_lifecycle_message(us, kr, base_url="https://example.com/",
                                       date_str="2026-05-08")
    # Both empty — message must be empty (suppressed at send level).
    assert msg.strip() == ""


def test_brief_handles_one_market_only():
    us = _result("US", ["NVDA"], enter_ok_count=3, early_count=2, failed_count=1)
    msg = _format_lifecycle_message(us, None, base_url="https://example.com/",
                                       date_str="2026-05-08")
    assert "🇺🇸 US" in msg
    assert "🇰🇷 KR" not in msg
```

- [ ] **Step 2: Run failing**

```
pytest tests/test_telegram_lifecycle_brief.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement `send_lifecycle_brief` + helpers**

Append to `telegram_sender.py`:

```python
def _summarize_lifecycle(result: dict | None) -> dict:
    if not result or not result.get("snapshots"):
        return {"new_confirmed": [], "enter_ok": 0, "early": 0, "failed_breakout": 0}
    snaps = result["snapshots"]
    nc, ok, early, fb = [], 0, 0, 0
    state = result.get("state") or {}
    for tk, s in snaps.items():
        if s["decision"] == "ENTER_OK":
            ok += 1
            # New confirmed = trigger_age == 0. Cheaply derive from yesterday absence.
            y = ((state.get("tickers") or {}).get(tk) or {}).get("snapshots", [])
            had_prior_confirmed = any(x.get("trigger") == "CONFIRMED_TRIGGER"
                                         for x in y[:-1])
            if not had_prior_confirmed and s["trigger"] == "CONFIRMED_TRIGGER":
                nc.append(tk)
        elif s["decision"] == "EARLY":
            early += 1
        if "FAILED_BREAKOUT" in (s.get("raw") or {}).get("risk_tags", []):
            fb += 1
    return {"new_confirmed": nc, "enter_ok": ok, "early": early, "failed_breakout": fb}


def _format_lifecycle_section(result: dict | None, flag: str, market: str,
                                  base_url: str, date_str: str) -> str:
    if not result or not result.get("snapshots"):
        return ""
    summary = result.get("_brief_summary") or _summarize_lifecycle(result)
    lines = [f"{flag} {market}"]
    if summary["new_confirmed"]:
        nc = " / ".join(summary["new_confirmed"][:5])
        more = "" if len(summary["new_confirmed"]) <= 5 else f" (+{len(summary['new_confirmed']) - 5})"
        lines.append(f"🆕 New CONFIRMED ({len(summary['new_confirmed'])}): {nc}{more}")
    if summary["enter_ok"]:
        lines.append(f"🟢 ENTER_OK total: {summary['enter_ok']}")
    if summary["early"]:
        lines.append(f"🟡 EARLY: {summary['early']}")
    if summary["failed_breakout"]:
        lines.append(f"🔴 FAILED_BREAKOUT: {summary['failed_breakout']}")
    base = base_url.rstrip("/") + "/" if base_url else ""
    lines.append(f"🔗 {base}lifecycle_{market.lower()}_{date_str}.html")
    return "\n".join(lines)


def _format_lifecycle_message(us_result: dict | None, kr_result: dict | None,
                                  base_url: str, date_str: str) -> str:
    parts: list[str] = []
    us_section = _format_lifecycle_section(us_result, "🇺🇸", "US", base_url, date_str)
    kr_section = _format_lifecycle_section(kr_result, "🇰🇷", "KR", base_url, date_str)
    if us_section:
        parts.append(us_section)
    if kr_section:
        parts.append(kr_section)
    if not parts:
        return ""
    return f"[Lifecycle Brief — {date_str}]\n\n" + "\n\n".join(parts)


def send_lifecycle_brief(us_result: dict | None, kr_result: dict | None,
                            base_url: str, date_str: str) -> bool:
    msg = _format_lifecycle_message(us_result, kr_result, base_url, date_str)
    if not msg.strip():
        return False
    return _send_message(msg)
```

- [ ] **Step 4: Wire into pipeline Step 5**

In `pipeline.py` Step 5 (after the existing `send_portfolio_risk_summary` call), add:

```python
try:
    from telegram_sender import send_lifecycle_brief
    _base = os.environ.get("REPORT_BASE_URL",
                          "https://freecjs77-tech.github.io/AI-Trading-Assistant-v2/")
    send_lifecycle_brief(lifecycle_us_result, lifecycle_kr_result,
                          base_url=_base, date_str=today)
except Exception as e:
    print(f"  WARN lifecycle telegram brief failed: {e}")
```

- [ ] **Step 5: Run tests**

```
pytest tests/test_telegram_lifecycle_brief.py -v
```
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add telegram_sender.py pipeline.py tests/test_telegram_lifecycle_brief.py
git commit -m "feat(lifecycle): send_lifecycle_brief telegram + pipeline wiring"
```

---

## Task 19: `generate_site.py` — copy `lifecycle_*.html` into `deploy/`

**Files:**
- Modify: `generate_site.py`
- Test: `tests/test_generate_site_lifecycle.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_generate_site_lifecycle.py
"""generate_site copies lifecycle pages mirror portfolio_stops pattern."""
from pathlib import Path


def test_generate_site_copies_lifecycle_pages_block_present():
    src = Path("generate_site.py").read_text(encoding="utf-8")
    assert "lifecycle_*.html" in src
    assert "lifecycle pages" in src.lower()
```

- [ ] **Step 2: Run failing**

```
pytest tests/test_generate_site_lifecycle.py -v
```

- [ ] **Step 3: Add the copy block**

In `generate_site.py`, after the existing `# Portfolio Stop Signal 페이지 복사` block (around line 79), add:

```python
    # Lifecycle 페이지 복사 (US/KR 별도 페이지)
    lifecycle_files = sorted(glob.glob(os.path.join(REPORTS_DIR, "lifecycle_*.html")))
    for f in lifecycle_files:
        shutil.copy2(f, DEPLOY_DIR)
    if lifecycle_files:
        print(f"lifecycle pages copied ({len(lifecycle_files)} files)")
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_generate_site_lifecycle.py -v
```
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add generate_site.py tests/test_generate_site_lifecycle.py
git commit -m "feat(lifecycle): copy lifecycle_*.html into deploy/"
```

---

## Task 20: Workflow — restore `lifecycle_history_*.json` from gh-pages

**Files:**
- Modify: `.github/workflows/daily-report.yml`
- Test: `tests/test_workflow_yaml_lifecycle.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_workflow_yaml_lifecycle.py
"""Workflow restores lifecycle history files from gh-pages."""
from pathlib import Path


def test_workflow_restores_lifecycle_history_files():
    yml = Path(".github/workflows/daily-report.yml").read_text(encoding="utf-8")
    assert "history/lifecycle_history_us.json" in yml
    assert "history/lifecycle_history_kr.json" in yml
```

- [ ] **Step 2: Run failing**

```
pytest tests/test_workflow_yaml_lifecycle.py -v
```

- [ ] **Step 3: Add lines to the restore block**

In `.github/workflows/daily-report.yml`, locate the `git checkout origin/gh-pages -- \` block (around line 29-36) and add two lines:

```yaml
            history/lifecycle_history_us.json \
            history/lifecycle_history_kr.json \
```

Place them between `history/portfolio_stops_wife.json \` and the trailing `history/ data/ 2>/dev/null || mkdir -p history data` line.

- [ ] **Step 4: Run tests**

```
pytest tests/test_workflow_yaml_lifecycle.py -v
```
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/daily-report.yml tests/test_workflow_yaml_lifecycle.py
git commit -m "ci(lifecycle): persist lifecycle_history_*.json across gh-pages runs"
```

---

## Task 21: E2E smoke test (pipeline-style data → empty result + populated result)

**Files:**
- Create: `tests/test_lifecycle_e2e.py`

- [ ] **Step 1: Write the e2e test**

```python
# tests/test_lifecycle_e2e.py
"""Phase A — end-to-end smoke through process_universe + render."""
import json
import os
from pathlib import Path

from lifecycle_signal import run_lifecycle


def _market_data():
    """Two synthetic tickers — one TREND_OK, one BROKEN."""
    return {
        "_meta": {"date": "2026-05-08", "is_trading_day": True},
        "data": {
            "FAKE_OK": {
                "price": 100.0, "high": 101, "low": 99, "prev_close": 99,
                "ema9": 99.5, "ema21": 98, "ema65": 90,
                "ema21_slope_5d": 0.5, "ema65_slope_5d": 0.4,
                "rsi14": 60, "atr14_pct": 2.0, "volume_ratio": 1.0,
                "change_pct": 1.0, "sector": "Technology",
            },
            "FAKE_BAD": {
                "price": 80.0, "high": 82, "low": 79, "prev_close": 81,
                "ema9": 90, "ema21": 95, "ema65": 100,
                "ema21_slope_5d": -0.5, "ema65_slope_5d": -0.3,
                "rsi14": 30, "atr14_pct": 4.0, "volume_ratio": 0.5,
                "change_pct": -1.5, "sector": "Energy",
            },
        },
    }


def test_run_lifecycle_round_trip(tmp_path: Path):
    # Build a fake momentum history that puts both tickers in scope.
    momentum_history = {
        "tickers": {
            "FAKE_OK":  {"snapshots": [{"date": "2026-05-08", "stage": "MOMENTUM_2"}]},
            "FAKE_BAD": {"snapshots": [{"date": "2026-05-08", "stage": "MOMENTUM_1"}]},
        }
    }
    (tmp_path / "history").mkdir()
    mom_path = tmp_path / "history" / "scanner_momentum_us_history.json"
    mom_path.write_text(json.dumps(momentum_history), encoding="utf-8")

    md = _market_data()
    result = run_lifecycle("US", project_dir=str(tmp_path),
                             market_data=md,
                             momentum_history_path=str(mom_path),
                             portfolio_tickers=set(), today="2026-05-08")
    assert result["status"] == "ok"
    assert "FAKE_OK" in result["snapshots"]
    assert result["snapshots"]["FAKE_OK"]["setup"] == "TREND_OK"
    assert result["snapshots"]["FAKE_BAD"]["setup"] == "BROKEN"
    # State persisted.
    state_file = tmp_path / "history" / "lifecycle_history_us.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert "FAKE_OK" in state["tickers"]


def test_run_lifecycle_two_days_emits_transitions(tmp_path: Path):
    momentum_history = {"tickers": {
        "FAKE": {"snapshots": [{"date": "2026-05-08", "stage": "MOMENTUM_2"}]},
    }}
    (tmp_path / "history").mkdir()
    mom_path = tmp_path / "history" / "scanner_momentum_us_history.json"
    mom_path.write_text(json.dumps(momentum_history), encoding="utf-8")

    # Day 1 — TREND_OK.
    md1 = {"_meta": {"date": "2026-05-07"}, "data": {"FAKE": {
        "price": 100, "high": 101, "low": 99, "prev_close": 99,
        "ema9": 99.5, "ema21": 98, "ema65": 90,
        "ema21_slope_5d": 0.5, "ema65_slope_5d": 0.4,
        "rsi14": 60, "atr14_pct": 2.0, "volume_ratio": 1.0,
        "change_pct": 1.0, "sector": "Tech",
    }}}
    run_lifecycle("US", project_dir=str(tmp_path),
                    market_data=md1,
                    momentum_history_path=str(mom_path),
                    portfolio_tickers=set(), today="2026-05-07")

    # Day 2 — distance to ema9 grows past 12% AND rsi to 78 → EXTENDED.
    md2 = {"_meta": {"date": "2026-05-08"}, "data": {"FAKE": {
        "price": 120, "high": 121, "low": 118, "prev_close": 100,
        "ema9": 105, "ema21": 98, "ema65": 90,
        "ema21_slope_5d": 0.5, "ema65_slope_5d": 0.4,
        "rsi14": 78, "atr14_pct": 2.0, "volume_ratio": 1.5,
        "change_pct": 20.0, "sector": "Tech",
    }}}
    result = run_lifecycle("US", project_dir=str(tmp_path),
                             market_data=md2,
                             momentum_history_path=str(mom_path),
                             portfolio_tickers=set(), today="2026-05-08")
    types = {e["event"] for e in result["transitions"]}
    assert "SETUP_CHANGE" in types
    assert "DECISION_CHANGE" in types
```

- [ ] **Step 2: Run e2e tests**

```
pytest tests/test_lifecycle_e2e.py -v
```
Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_lifecycle_e2e.py
git commit -m "test(lifecycle): e2e smoke through run_lifecycle"
```

---

## Task 22: CLAUDE.md registration

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add line under "진행 중인 계획"**

Open `CLAUDE.md`. Find the section "## 진행 중인 계획". Add this line at the end of that bullet list:

```
- [Trade Lifecycle Phase A](docs/superpowers/plans/2026-05-08-trade-lifecycle-phase-a.md) — Pipeline Step 4c4/4c5 신규 · setup_state(TREND_OK/PULLBACK/BASE_FORMING/EXTENDED/BROKEN) + trigger_state(WAIT/EARLY/CONFIRMED) + decision(ENTER_OK/EARLY/STAGING/AVOID) · 4c4 US + 4c5 KR (별도 history JSON) · `lifecycle_us/kr.html` 신규 + 메인 리포트 nav · Telegram lifecycle brief (🆕 New CONFIRMED) · `fetch_market_data`에 ema9/21/65 + slope 추가 · 자동매매 ❌ / 합성 점수 forbidden · roadmap의 Phase B/C/D는 별도
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(lifecycle): register Phase A plan in CLAUDE.md"
```

---

## Task 23: Full-suite regression check

**Files:**
- (no edits — verify existing tests still pass)

- [ ] **Step 1: Run the entire test suite**

```
pytest tests/ -v --tb=short
```

- [ ] **Step 2: Verify output**

Expected:
- All `test_lifecycle_*.py` tests pass.
- Existing `test_signal_judge.py`, `test_momentum_*.py`, `test_portfolio_stop_*.py`, `test_fetch_market_data_atr.py` continue passing — Phase A must not break any prior test.

If any prior test fails, the change is wrong. Fix the lifecycle code, not the prior test.

- [ ] **Step 3: Run a SKIP_LIFECYCLE skip-path verification**

```
SKIP_SCANNERS=1 SKIP_LIFECYCLE=1 python pipeline.py --skip-ocr
```

(PowerShell):

```
$env:SKIP_SCANNERS=1; $env:SKIP_LIFECYCLE=1; python pipeline.py --skip-ocr
```

Expected: pipeline completes without error and prints `[Step 4c4] SKIP_LIFECYCLE=1 — lifecycle US 스킵`.

- [ ] **Step 4: Commit (no-op if no edits)**

If you discovered a regression and fixed it, commit. Otherwise nothing to commit — proceed to Task 24.

---

## Task 24: Local end-to-end run (real data, real artifacts)

This task validates spec acceptance criteria #2 and #3.

**Files:** none (artifacts in `history/`, `reports/`)

- [ ] **Step 1: Run the full pipeline once**

```
python pipeline.py --skip-ocr
```

(PowerShell): same command works as-is.

- [ ] **Step 2: Verify artifacts**

```
ls history/lifecycle_history_us.json history/lifecycle_history_kr.json
ls reports/lifecycle_us_*.html reports/lifecycle_kr_*.html
```

Both lifecycle history JSON files and both HTML files must exist.

- [ ] **Step 3: Open the US page in a browser**

```
start reports/lifecycle_us_<TODAY>.html
```

Verify visually:
- Section [1] shows "Phase B placeholder".
- ENTER_OK / EARLY / STAGING / AVOID cards render.
- Main table populated with at least 5 tickers.
- Each ENTER_OK row has "Recommended size: TBD — Phase C" footer.

- [ ] **Step 4: Inspect the lifecycle JSON shape**

```
python -c "import json; s=json.load(open('history/lifecycle_history_us.json', encoding='utf-8')); print('schema_version:', s['schema_version']); print('tickers:', len(s['tickers'])); print('transitions:', len(s['transitions']))"
```

Expected: `schema_version: 1.0.0`, tickers ≥ 1 (more on a real run), transitions can be 0 on first run.

- [ ] **Step 5: Verify the Telegram brief delivery (optional — local only)**

If `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set in your local env, the brief sends automatically as part of Step 5. Otherwise skip this step — the gh-actions run will validate it.

- [ ] **Step 6: Commit any incidental fixes from real-data exposure**

If the live run uncovered an edge case (e.g. a ticker with `None` for an EMA, or a yfinance timeout), fix it inside the appropriate module + add a regression test, then commit:

```bash
git add lifecycle_signal.py tests/test_lifecycle_signal.py
git commit -m "fix(lifecycle): handle <specific edge case from real-data run>"
```

---

## Task 25: Open PR and let CI confirm acceptance criteria

**Files:** none

- [ ] **Step 1: Push the branch**

```
git push -u origin claude/sad-leavitt-89c203
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "feat(lifecycle): Phase A — trend-structure setup/trigger lifecycle" --body "$(cat <<'EOF'
## Summary
- Adds Phase A of the trade-lifecycle roadmap: per-ticker `setup_state` / `trigger_state` / `entry_decision` machine over a daily-evolving active set, with persistent ticker-keyed snapshots and transitions log.
- New pipeline Steps 4c4 (US) and 4c5 (KR), wrapped in failure isolation so they never block Step 5 portfolio reports.
- Adds `lifecycle_us.html` / `lifecycle_kr.html` pages, a Telegram lifecycle brief, and `fetch_market_data` extensions (`ema9`/`ema21`/`ema65` + 5-day slopes).
- 6 Golden scenarios pin the regression contract; `signal_judge` and `momentum_scanner` outputs remain byte-identical.

## Test plan
- [ ] `pytest tests/test_lifecycle_*.py -v` — all green
- [ ] `pytest tests/` — no regressions in pre-existing tests
- [ ] `python pipeline.py --skip-ocr` — produces both lifecycle pages + populated history JSON
- [ ] First gh-pages deploy carries the lifecycle pages forward
- [ ] After 5 trading days: `history/lifecycle_history_us.json` has ≥ 50 tickers × ≥ 5 days, ≥ 1 of each major transition event type

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Watch the CI run**

```
gh pr checks --watch
```

Expected: green build. The first deploy populates `history/lifecycle_history_*.json` for the next run.

- [ ] **Step 4: Merge after review**

This is for the human reviewer. Do not merge automatically.

---

## Self-review (run after writing the plan)

### Spec coverage check

| Spec section | Task |
|---|---|
| §3 Active set definition | Task 8 |
| §4.1 setup_state precedence (5 states) | Task 3 |
| §4.2 setup_state definitions | Task 3 |
| §4.3 trigger_state (3 values) | Task 4 |
| §4.4 entry_decision + regime=None hook | Task 5 |
| §4.5 risk_tags (incl. FAILED_BREAKOUT loose+strict) | Task 6 |
| §4.6 derived fields (recomputed on read) | Task 9 |
| §5.1 snapshot schema | Task 7 + Task 12 (`_make_snapshot`) |
| §5.2 lifecycle history file structure (versioning) | Task 7 |
| §5.3 transition events (5 types incl. FAILED_BREAKOUT independent) | Task 10 |
| §5.4 retention (no truncation; archival yearly — script not in scope here) | Task 7 (no-truncation behavior is implicit in `append_snapshot`) |
| §6.1 new files | Tasks 1, 3-15 |
| §6.2 modified files | Tasks 2, 16-22 |
| §7 pipeline integration (Step 4c4/4c5 failure isolation) | Task 16 |
| §8 config rationale comments | Task 1 (rationale-gate test) |
| §9 6 Golden scenarios | Task 13 |
| §10 UI sections [1]-[6] + sort order + placeholders | Tasks 14-15 |
| §11 Telegram brief shape + empty-section handling | Task 18 |
| §12 risk + rollback (atomic write Task 7; SKIP_LIFECYCLE Task 16) | Tasks 7, 16 |
| §13 acceptance criteria | Tasks 23-25 |
| §14 open questions (bootstrap edge case, time zone, holiday) | Tasks 11, 16 (holiday handling via `is_trading_day` already in `pipeline.py:175`) |

### Placeholder scan
- No "TBD" steps. ✓
- No "fill in details". ✓
- No bare "Add error handling" — failure isolation is concretely shown in the pipeline try/except. ✓
- "Recommended size: TBD — Phase C" appears as user-facing UI copy (intended — it's the placeholder per spec §10.2), not as a plan placeholder.

### Type / signature consistency
- `evaluate_setup_state(raw)` signature consistent across Tasks 3, 12, 13, e2e.
- `evaluate_trigger_state(today, yesterday, setup_state)` signature consistent across Tasks 4, 12, 13, e2e.
- `evaluate_decision(setup, trigger, *, risk_tags=None, regime=None)` consistent.
- `compute_risk_tags(today, yesterday_snapshot)` consistent across Tasks 6, 12, 13.
- `process_universe(*, active_set, market_data, yesterday_state, today, regime=None)` consistent across Tasks 12, 16, e2e.
- `run_lifecycle(market, *, project_dir, market_data, momentum_history_path, portfolio_tickers, today)` consistent across Task 16, pipeline integration, e2e.
- Snapshot keys (`date / setup / trigger / decision / raw{...}`) consistent across history append, transitions diff, render context, brief summary.
- Transition `event_id` format `{ticker}_{date}_{event}_v1` consistent across Tasks 7, 10.

### Verified accuracy of file/line references
- `fetch_market_data.py:411-498` indicator block — verified.
- `pipeline.py` Step 4c3 ends ≈ line 422 — verified.
- `report_generator.py:255-273` `generate_report` signature — verified.
- `templates/report_template.html` already references `momentum_us_page` etc. — verified.
- `generate_site.py:75-79` `portfolio_stops_*.html` block — verified, new block placed immediately after.
- `.github/workflows/daily-report.yml:29-36` restore block — verified.
- `portfolio_stop_history.py:62-65` atomic-write pattern — mirrored in `lifecycle_history.save_lifecycle_history`.
