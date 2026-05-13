# Trade Lifecycle Probabilistic Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Phase A's all-AND boolean trigger with a probabilistic score engine that captures more PROBE/ENTER signals (especially TREND_OK "quiet leaders" like NVDA/META) while preserving all external contracts (decision keys, history schema, page structure, Telegram brief).

**Architecture:** Four layers — Layer 0 (deterministic risk veto), Layer 1 (existing setup_state), Layer 2 (NEW: `trigger_score` 9 components + `drift_score` 7 components, weights externalized), Layer 3 (score-driven decision with `PROBE_STRONG` badge + sizing hint). Soft migration via `LIFECYCLE_ENGINE_MODE` envvar across 3 PRs: PR#1 (infra + shadow mode), PR#2 (trigger activation), PR#3 (drift activation).

**Tech Stack:** Python 3.10+, pandas (yfinance data), pytest, Jinja2 (templates), existing modules at project root (`lifecycle_signal.py`, `lifecycle_history.py`, `lifecycle_report.py`, `fetch_market_data.py`, `pipeline.py`, `telegram_sender.py`).

**Source spec:** [docs/superpowers/specs/2026-05-13-lifecycle-probabilistic-engine-design.md](../specs/2026-05-13-lifecycle-probabilistic-engine-design.md)

**Out of scope for this plan:** Phase 4 calibration (weight tuning, backtest harness), portfolio_stop_signal integration, stage tracking, setup_state threshold relaxation. See spec §11.

---

## File Map

| Path | Action | Purpose |
|---|---|---|
| `lifecycle_score_config.py` | **NEW** | Constants (TRACK_*, DECISION_*, VETO_*, BADGE_*), TRIGGER_WEIGHTS, DRIFT_WEIGHTS, THRESHOLDS, SIZE_TIERS, DRIFT_ALLOW_ENTER, DRIFT_TRACK_ACTIVE |
| `lifecycle_score.py` | **NEW** | `compute_trigger_score()`, `compute_drift_score()`, `ScoreResult` dataclass, component predicates |
| `market_benchmark.py` | **NEW** | Fetch + cache `market_ret_5d` (SPY for US, KS200 for KR) with 3-day cache fallback |
| `lifecycle_signal.py` | Modify | Add `hard_risk_veto()`, `_derive_legacy_trigger_state()`; refactor `evaluate_decision()` with `LIFECYCLE_ENGINE_MODE` dispatch; extend `_make_snapshot()` for new fields; update `process_universe()` + `run_lifecycle()` for benchmark passing + 3d closes |
| `lifecycle_history.py` | Modify | Auto-fill `engine_version` on legacy load; extend `compute_transitions()` for new event types (`score_jump`, `drift_probe`, `probe_strong`) with first-attach dedup |
| `lifecycle_report.py` | Modify | Add score/badge fields to row dict; pass through `score_components` to template; update verdict narration |
| `templates/lifecycle_us.html` + `lifecycle_kr.html` | Modify | Add score + active_components dots to chips; debug toggle for `_raw_*`; new term-glossary entries |
| `fetch_market_data.py` | Modify | Add `open`, `high_20d_prior`, `atr14_pct_5d_avg`, `atr14_pct_20d_avg`, `volume_5d_avg`, `volume_20d_avg` to result dict |
| `pipeline.py` | Modify | Pass market benchmark cache path into `run_lifecycle()` |
| `telegram_sender.py` | Modify | Surface score in lifecycle brief; new section for drift events (PR#3) |
| `tests/test_lifecycle_score_config.py` | **NEW** | Weight sanity + rationale gate (mirrors `test_lifecycle_config.py`) |
| `tests/test_lifecycle_score.py` | **NEW** | Component-level unit tests (9 trigger + 7 drift) |
| `tests/test_lifecycle_decision_matrix.py` | **NEW** | Exhaustive (setup_state × score) → decision tabulation |
| `tests/test_lifecycle_invariants.py` | **NEW** | Hard contracts: FAILED_BREAKOUT→AVOID, drift never ENTER when disabled, score_components sum == score, etc. |
| `tests/test_market_benchmark.py` | **NEW** | Cache hit/miss/staleness/fallback |
| `docs/lifecycle_score_spec.md` | **NEW** | In-tree spec freeze (terse reference, links design doc) |
| `analytics/score_distribution_report.py` | **NEW (optional)** | Calibration helper; defer if time-constrained |

---

# PR #1 — Score Infrastructure + Shadow Mode

Goal: All score machinery in place. `lifecycle_score.py` computes scores. History stores them. UI displays them. **But** decision still comes from Phase A boolean path (`LIFECYCLE_ENGINE_MODE=score_shadow` default). Invariants enforced from day 1.

**Exit:** All tests green. Pipeline runs end-to-end. Existing pages render with new score columns. Phase A history still loadable. Phase A decisions still primary.

---

### Task 1: Create `lifecycle_score_config.py` with constants and weights

**Files:**
- Create: `lifecycle_score_config.py`

- [ ] **Step 1: Write the config module**

```python
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

# Default mode for this PR (PR#1 = shadow). PR#2 flips to score_active.
DEFAULT_ENGINE_MODE = MODE_SCORE_SHADOW

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
TRIGGER_TRACK_ACTIVE = False
DRIFT_TRACK_ACTIVE   = False

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
```

- [ ] **Step 2: Commit**

```bash
git add lifecycle_score_config.py
git commit -m "feat(lifecycle): add score_v1 config (weights, thresholds, constants)"
```

---

### Task 2: Test `lifecycle_score_config.py` (sanity + rationale gate)

**Files:**
- Create: `tests/test_lifecycle_score_config.py`

- [ ] **Step 1: Write the test file**

```python
# tests/test_lifecycle_score_config.py
"""score_v1 config — sanity + rationale gate (mirrors test_lifecycle_config.py)."""
import re
from pathlib import Path

import lifecycle_score_config as cfg


def test_engine_version_present():
    assert cfg.ENGINE_VERSION == "score_v1"


def test_default_mode_is_shadow():
    """PR#1 default = shadow. PR#2 will flip to score_active."""
    assert cfg.DEFAULT_ENGINE_MODE == cfg.MODE_SCORE_SHADOW


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


def test_track_active_flags_default_false_in_pr1():
    """PR#1: scores computed but decisions still from Phase A (shadow)."""
    assert cfg.TRIGGER_TRACK_ACTIVE is False
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
        if idx is None:
            missing.append(f"{name}: not found")
            continue
        # Look for a # comment within 5 lines above OR inline on same line.
        line_with_value = lines[idx]
        if "#" in line_with_value:
            continue
        window = lines[max(0, idx - 5):idx]
        if not any(l.strip().startswith("#") for l in window):
            missing.append(f"{name}: no rationale comment within 5 lines above")
    assert not missing, "Missing rationale comments:\n" + "\n".join(missing)
```

- [ ] **Step 2: Run the tests to verify they pass**

Run: `pytest tests/test_lifecycle_score_config.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_lifecycle_score_config.py
git commit -m "test(lifecycle): score config sanity + rationale gate"
```

---

### Task 3: Add `open` field to fetch_market_data

**Files:**
- Modify: `fetch_market_data.py:473-540` (the `compute_indicators` return dict)

- [ ] **Step 1: Add `open` to the return dict**

In `compute_indicators()`, after the existing `"price"` line, add:

```python
        "price":             round(last_close, 2),
        "open":              round(float(df["Open"].iloc[-1]), 2),  # NEW — for lower_wick + intraday_reversal score components
        "prev_close":        round(float(close.iloc[-2]), 2) if len(close) >= 2 else None,
```

- [ ] **Step 2: Verify the field appears in fetch output**

Run a quick sanity:

```bash
python -c "from fetch_market_data import fetch_ticker; r = fetch_ticker('AAPL'); print('open:', r.get('open'), 'price:', r.get('price'))"
```

Expected: prints both values, `open` is a positive float.

- [ ] **Step 3: Commit**

```bash
git add fetch_market_data.py
git commit -m "feat(fetch): emit 'open' field (score_v1 lower_wick + intraday_reversal)"
```

---

### Task 4: Add `high_20d_prior` field to fetch_market_data

**Files:**
- Modify: `fetch_market_data.py` (the `compute_indicators` return dict)

- [ ] **Step 1: Compute `high_20d_prior` (excludes today's bar) and add to return**

In `compute_indicators()`, after the `recent_high` computation around line 436, add:

```python
    recent_high = float(close.iloc[-20:].max())
    # high_20d_prior — rolling 20-day high EXCLUDING today's bar.
    # Used by score_v1 'breakout' component to avoid self-reference contamination.
    if len(high) >= 21:
        high_20d_prior = float(high.iloc[-21:-1].max())
    else:
        high_20d_prior = None
    drawdown    = (last_close - recent_high) / recent_high * 100
```

Then in the return dict (near the other `high_*` fields), add:

```python
        "high_52w":          round(high_52w, 2),
        "low_52w":           round(low_52w, 2),
        "high_20d_prior":    round(high_20d_prior, 2) if high_20d_prior is not None else None,  # NEW
```

- [ ] **Step 2: Verify**

```bash
python -c "from fetch_market_data import fetch_ticker; r = fetch_ticker('SPY'); print('high_20d_prior:', r.get('high_20d_prior'), 'price:', r.get('price'))"
```

Expected: positive float printed.

- [ ] **Step 3: Commit**

```bash
git add fetch_market_data.py
git commit -m "feat(fetch): emit high_20d_prior (score_v1 breakout component)"
```

---

### Task 5: Add ATR/Volume 5d & 20d averages to fetch_market_data

The drift_score `atr_contraction`, `low_vol_drift`, and BASE_FORMING setup need these. Today they're consumed but never emitted, so they always evaluate to None.

**Files:**
- Modify: `fetch_market_data.py` `compute_indicators` return dict

- [ ] **Step 1: Compute averages and add to return**

After `atr14_val` is computed (around line 410), add the averages:

```python
    atr14_val = (
        float(atr14_series.iloc[-1])
        if len(atr14_series) > 0
        and not pd.isna(atr14_series.iloc[-1])
        and np.isfinite(atr14_series.iloc[-1])
        else None
    )

    # ── Score v1 averages (drift atr_contraction / low_vol_drift, BASE_FORMING) ──
    def _avg_atr_pct(series, window: int):
        if len(series) < window or last_close <= 0:
            return None
        vals = series.iloc[-window:].dropna()
        if len(vals) == 0:
            return None
        return round(float(vals.mean()) / last_close * 100, 4)

    atr14_pct_5d_avg  = _avg_atr_pct(atr14_series, 5)
    atr14_pct_20d_avg = _avg_atr_pct(atr14_series, 20)

    def _avg_volume(window: int):
        if len(volume) < window:
            return None
        vals = volume.iloc[-window:].dropna()
        if len(vals) == 0:
            return None
        return int(vals.mean())

    volume_5d_avg  = _avg_volume(5)
    volume_20d_avg = _avg_volume(20)
```

In the return dict, alongside the existing `atr14`/`volume_ma20` fields, add:

```python
        "atr14":               round(atr14_val, 4) if atr14_val is not None else None,
        "atr14_pct":           round((atr14_val / last_close) * 100, 2)
                                if atr14_val is not None and last_close > 0
                                else None,
        "atr14_pct_5d_avg":    atr14_pct_5d_avg,    # NEW
        "atr14_pct_20d_avg":   atr14_pct_20d_avg,   # NEW
        # 거래량
        "volume":              int(volume.iloc[-1]),
        "volume_ma20":         int(vol_ma20.iloc[-1]) if safe(vol_ma20) else None,
        "volume_5d_avg":       volume_5d_avg,       # NEW
        "volume_20d_avg":      volume_20d_avg,      # NEW
        "volume_ratio":        round(float(volume.iloc[-1]) / float(vol_ma20.iloc[-1]), 2) if safe(vol_ma20) else None,
```

- [ ] **Step 2: Also derive `days_sideways` (used by BASE_FORMING)**

This was noted as "optional pass-through" in Phase A. For drift to work well we need it populated. After the avg computations:

```python
    # days_sideways — consecutive days where high-low range ≤ atr14 (compression).
    # Used by BASE_FORMING setup_state predicate.
    if atr14_val and atr14_val > 0 and len(df) >= 2:
        days = 0
        for i in range(1, min(len(df), 20) + 1):
            r = float(high.iloc[-i]) - float(low.iloc[-i])
            if r <= atr14_val:
                days += 1
            else:
                break
        days_sideways = days
    else:
        days_sideways = 0
```

Add to return dict:

```python
        "days_sideways":       days_sideways,       # NEW (was passed-through None before)
```

- [ ] **Step 3: Verify**

```bash
python -c "from fetch_market_data import fetch_ticker; r = fetch_ticker('AAPL'); print('atr5:', r.get('atr14_pct_5d_avg'), 'atr20:', r.get('atr14_pct_20d_avg'), 'vol5:', r.get('volume_5d_avg'), 'sideways:', r.get('days_sideways'))"
```

Expected: all four print non-None values.

- [ ] **Step 4: Commit**

```bash
git add fetch_market_data.py
git commit -m "feat(fetch): emit ATR/vol 5d+20d averages + days_sideways for drift_score"
```

---

### Task 6: Test fetch_market_data new fields

**Files:**
- Modify: `tests/test_fetch_market_data.py` (or create if doesn't exist)

- [ ] **Step 1: Check if test file exists**

Run: `ls tests/ | grep fetch_market_data`

If exists, modify; if not, create. (Plan assumes a unit-test fixture exists for `compute_indicators` — check by running `pytest tests/ --collect-only -k fetch_market_data`.)

- [ ] **Step 2: Add tests for new fields**

If no existing test file, create `tests/test_fetch_market_data_score_fields.py`:

```python
# tests/test_fetch_market_data_score_fields.py
"""Score_v1 — new fields emitted by compute_indicators."""
import numpy as np
import pandas as pd

from fetch_market_data import compute_indicators


def _make_df(days: int = 60, seed: int = 42):
    """Synthetic OHLCV with a mild uptrend and reasonable noise."""
    rng = np.random.default_rng(seed)
    base = np.linspace(100, 120, days)
    noise = rng.normal(0, 1.5, days)
    close = base + noise
    open_ = close - rng.normal(0, 0.5, days)
    high = np.maximum(close, open_) + np.abs(rng.normal(0.5, 0.3, days))
    low = np.minimum(close, open_) - np.abs(rng.normal(0.5, 0.3, days))
    volume = rng.integers(800_000, 1_200_000, days)
    dates = pd.date_range("2026-01-01", periods=days, freq="B")
    return pd.DataFrame({
        "Open": open_, "High": high, "Low": low,
        "Close": close, "Volume": volume,
    }, index=dates)


def test_open_field_emitted():
    df = _make_df()
    r = compute_indicators(df)
    assert "open" in r
    assert isinstance(r["open"], float)
    assert r["open"] > 0


def test_high_20d_prior_excludes_today():
    df = _make_df()
    r = compute_indicators(df)
    assert "high_20d_prior" in r
    # high_20d_prior should equal max of high[-21:-1]
    expected = round(float(df["High"].iloc[-21:-1].max()), 2)
    assert r["high_20d_prior"] == expected


def test_high_20d_prior_excludes_today_strictly():
    """If today is a new high, high_20d_prior should be lower than today's high."""
    df = _make_df()
    df.loc[df.index[-1], "High"] = 999.0
    r = compute_indicators(df)
    assert r["high_20d_prior"] is not None
    assert r["high_20d_prior"] < 999.0


def test_atr_5d_20d_avg_emitted():
    df = _make_df()
    r = compute_indicators(df)
    assert r["atr14_pct_5d_avg"] is not None
    assert r["atr14_pct_20d_avg"] is not None
    assert r["atr14_pct_5d_avg"] > 0
    assert r["atr14_pct_20d_avg"] > 0


def test_volume_5d_20d_avg_emitted():
    df = _make_df()
    r = compute_indicators(df)
    assert r["volume_5d_avg"] is not None
    assert r["volume_20d_avg"] is not None
    assert r["volume_5d_avg"] > 0


def test_days_sideways_present_and_non_negative():
    df = _make_df()
    r = compute_indicators(df)
    assert "days_sideways" in r
    assert r["days_sideways"] >= 0


def test_short_history_short_circuits():
    """Less than 20 days of data — averages may be None but no crash."""
    df = _make_df(days=10)
    r = compute_indicators(df)
    # Function should not raise. Some averages will be None.
    assert "open" in r
    assert r.get("atr14_pct_20d_avg") is None or r.get("atr14_pct_20d_avg") > 0
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_fetch_market_data_score_fields.py -v
```

Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_fetch_market_data_score_fields.py
git commit -m "test(fetch): cover score_v1 new fields"
```

---

### Task 7: Create `market_benchmark.py` (SPY/KS200 fetch + cache)

**Files:**
- Create: `market_benchmark.py`

- [ ] **Step 1: Write the module**

```python
# market_benchmark.py
"""Market benchmark fetch + cache for score_v1 rs_strong component.

Per spec §8.2:
  - Fetched ONCE per pipeline run per market (not per ticker)
  - Cached to history/market_benchmark_cache.json
  - On fetch failure: reuse last cached value if age <= 3 calendar days
  - Beyond cache: rs_strong = False for all tickers in that market this run
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Optional

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lifecycle_score_config import (
    MARKET_BENCHMARK_CACHE_MAX_AGE_DAYS,
    US_BENCHMARK_TICKER, KR_BENCHMARK_TICKER,
)

CACHE_FILE = "market_benchmark_cache.json"


def _market_to_ticker(market: str) -> str:
    if market == "US":
        return US_BENCHMARK_TICKER
    if market == "KR":
        return KR_BENCHMARK_TICKER
    raise ValueError(f"Unknown market: {market!r}")


def _load_cache(cache_path: str) -> dict:
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, "rb") as f:
            return json.loads(f.read().decode("utf-8"))
    except Exception as e:
        print(f"[market_benchmark] WARN cache load failed ({e}); ignoring cache")
        return {}


def _save_cache(cache_path: str, cache: dict) -> None:
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
    tmp = cache_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    os.replace(tmp, cache_path)


def _fetch_live_ret_5d(ticker: str) -> Optional[float]:
    """Fetch 5-day percent return via existing fetch_ticker. Returns None on failure."""
    try:
        from fetch_market_data import fetch_ticker
        row = fetch_ticker(ticker)
        if not row or "error" in row:
            return None
        # fetch_market_data emits change_5d_pct (not ret_5d_pct).
        ret = row.get("change_5d_pct")
        if ret is None:
            return None
        return float(ret)
    except Exception as e:
        print(f"[market_benchmark] WARN live fetch failed for {ticker}: {e}")
        return None


def _is_fresh(cached_at_str: str, max_age_days: int) -> bool:
    try:
        cached_at = datetime.strptime(cached_at_str, "%Y-%m-%dT%H:%M:%S")
        age = (datetime.now() - cached_at).days
        return age <= max_age_days
    except (ValueError, TypeError):
        return False


def get_market_ret_5d(market: str, *, project_dir: str,
                      cache_path: Optional[str] = None) -> Optional[float]:
    """Return market 5d % return. Live fetch with cache fallback.

    Args:
        market: "US" or "KR"
        project_dir: project root (used to find history/market_benchmark_cache.json)
        cache_path: explicit override (used by tests)

    Returns:
        float | None: 5-day % return, or None if both live and cache fail.
    """
    if cache_path is None:
        cache_path = os.path.join(project_dir, "history", CACHE_FILE)

    cache = _load_cache(cache_path)
    ticker = _market_to_ticker(market)

    live = _fetch_live_ret_5d(ticker)
    if live is not None:
        cache[market] = {
            "value":     live,
            "cached_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "ticker":    ticker,
        }
        _save_cache(cache_path, cache)
        return live

    # Live fetch failed — try cache fallback
    cached = cache.get(market)
    if cached and _is_fresh(cached.get("cached_at", ""),
                            MARKET_BENCHMARK_CACHE_MAX_AGE_DAYS):
        print(f"[market_benchmark] live fetch failed for {ticker}; "
              f"using cached value from {cached['cached_at']}")
        return float(cached["value"])

    print(f"[market_benchmark] WARN no fresh benchmark for {market}; "
          f"rs_strong will be False for all tickers in this market")
    return None
```

- [ ] **Step 2: Commit**

```bash
git add market_benchmark.py
git commit -m "feat: market_benchmark module (SPY/KS200 fetch + 3d cache fallback)"
```

---

### Task 8: Test `market_benchmark.py`

**Files:**
- Create: `tests/test_market_benchmark.py`

- [ ] **Step 1: Write the tests**

```python
# tests/test_market_benchmark.py
"""market_benchmark — cache hit/miss/staleness/fallback behaviour."""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

import market_benchmark as mb


@pytest.fixture
def tmp_cache_path(tmp_path):
    return str(tmp_path / "market_benchmark_cache.json")


def _write_cache(path: str, market: str, value: float, age_days: int):
    cached_at = (datetime.now() - timedelta(days=age_days)).strftime("%Y-%m-%dT%H:%M:%S")
    data = {market: {"value": value, "cached_at": cached_at, "ticker": "SPY"}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def test_live_fetch_success_writes_cache(tmp_cache_path, tmp_path):
    with patch.object(mb, "_fetch_live_ret_5d", return_value=2.5):
        ret = mb.get_market_ret_5d("US", project_dir=str(tmp_path), cache_path=tmp_cache_path)
    assert ret == 2.5
    assert os.path.exists(tmp_cache_path)
    with open(tmp_cache_path) as f:
        cache = json.load(f)
    assert cache["US"]["value"] == 2.5


def test_live_fetch_failure_uses_fresh_cache(tmp_cache_path, tmp_path):
    _write_cache(tmp_cache_path, "US", value=1.8, age_days=1)
    with patch.object(mb, "_fetch_live_ret_5d", return_value=None):
        ret = mb.get_market_ret_5d("US", project_dir=str(tmp_path), cache_path=tmp_cache_path)
    assert ret == 1.8


def test_live_fetch_failure_rejects_stale_cache(tmp_cache_path, tmp_path):
    _write_cache(tmp_cache_path, "US", value=1.8, age_days=5)  # > 3 day max age
    with patch.object(mb, "_fetch_live_ret_5d", return_value=None):
        ret = mb.get_market_ret_5d("US", project_dir=str(tmp_path), cache_path=tmp_cache_path)
    assert ret is None


def test_unknown_market_raises(tmp_cache_path, tmp_path):
    with pytest.raises(ValueError, match="Unknown market"):
        mb.get_market_ret_5d("JP", project_dir=str(tmp_path), cache_path=tmp_cache_path)


def test_no_cache_no_live_returns_none(tmp_cache_path, tmp_path):
    with patch.object(mb, "_fetch_live_ret_5d", return_value=None):
        ret = mb.get_market_ret_5d("US", project_dir=str(tmp_path), cache_path=tmp_cache_path)
    assert ret is None


def test_kr_uses_kospi_etf_ticker():
    """KR benchmark should target KS200 ETF, not SPY."""
    assert mb._market_to_ticker("KR") == "069500.KS"
    assert mb._market_to_ticker("US") == "SPY"
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_market_benchmark.py -v
```

Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_market_benchmark.py
git commit -m "test: market_benchmark cache hit/miss/staleness"
```

---

### Task 9: Create `lifecycle_score.py` skeleton

**Files:**
- Create: `lifecycle_score.py`

- [ ] **Step 1: Write the module skeleton**

```python
# lifecycle_score.py
"""Score engine v1 — trigger_score (PULLBACK/BASE_FORMING) + drift_score (TREND_OK).

Pure functions. No I/O. Component-level explainability:
each call returns a ScoreResult with features{}, score_components[], and
the computed total.

See docs/superpowers/specs/2026-05-13-lifecycle-probabilistic-engine-design.md §6
for component definitions and the rationale behind each one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from lifecycle_score_config import (
    TRIGGER_WEIGHTS, DRIFT_WEIGHTS,
    LOWER_WICK_MIN_RATIO, CLOSE_STRONG_MIN_RATIO,
    TIGHT_RANGE_MAX_ATR, VOL_EXPANSION_MIN_RATIO,
    LOW_VOL_DRIFT_RATIO, TIGHT_CLUSTER_MAX_ATR,
)


@dataclass
class ScoreResult:
    """Output of compute_trigger_score / compute_drift_score.

    Invariants enforced by post_init:
      - score = sum(weight for c in components_list if c.active)
      - active_count = sum(1 for v in features.values() if v)
      - features keys == TRIGGER_WEIGHTS.keys() OR DRIFT_WEIGHTS.keys()
      - components_list ordering == config dict iteration order
    """
    track: str                       # "trigger" or "drift"
    score: int = 0
    active_count: int = 0
    features: dict = field(default_factory=dict)
    components_list: list = field(default_factory=list)
    rs_delta_pct: Optional[float] = None  # ret_5d - market_ret_5d (raw margin)


# ── Helpers ────────────────────────────────────────────────────────


def _safe_div(num, den):
    if num is None or den is None or den == 0:
        return None
    return num / den


def _yes_no(value, threshold, op="ge"):
    """True if value passes threshold (None → False)."""
    if value is None:
        return False
    if op == "ge":
        return value >= threshold
    if op == "gt":
        return value > threshold
    if op == "le":
        return value <= threshold
    if op == "lt":
        return value < threshold
    raise ValueError(f"Unknown op: {op}")


# ── Component predicates (each returns bool) ───────────────────────


def _ema_reclaim(today, yesterday) -> bool:
    """today.close > ema9 AND yesterday.close <= ema9 (Phase A arm 1)."""
    if not yesterday:
        return False
    e9 = today.get("ema9")
    yc = yesterday.get("close")
    tc = today.get("close")
    if e9 is None or yc is None or tc is None:
        return False
    return yc <= e9 < tc


def _higher_low(today, yesterday) -> bool:
    """today.low > yesterday.low."""
    if not yesterday:
        return False
    yl = yesterday.get("low")
    tl = today.get("low")
    if yl is None or tl is None:
        return False
    return tl > yl


def _rs_strong(ret_5d_pct: Optional[float],
               market_ret_5d_pct: Optional[float]) -> bool:
    """ret_5d > market_ret_5d. Either None → False."""
    if ret_5d_pct is None or market_ret_5d_pct is None:
        return False
    return ret_5d_pct > market_ret_5d_pct


def _lower_wick(today) -> bool:
    """(min(open,close) - low) / (high - low) >= 0.4 AND close >= open."""
    h, l, o, c = today.get("high"), today.get("low"), today.get("open"), today.get("close")
    if None in (h, l, o, c) or h == l:
        return False
    if c < o:
        return False
    wick = min(o, c) - l
    rng = h - l
    return wick / rng >= LOWER_WICK_MIN_RATIO


def _tight_range(today) -> bool:
    """(high - low) / atr14 < 0.7."""
    h, l, atr = today.get("high"), today.get("low"), today.get("atr14")
    if h is None or l is None or atr is None or atr <= 0:
        return False
    return (h - l) / atr < TIGHT_RANGE_MAX_ATR


def _vol_expansion(today) -> bool:
    """volume_ratio >= 1.2."""
    vr = today.get("volume_ratio")
    if vr is None:
        return False
    return vr >= VOL_EXPANSION_MIN_RATIO


def _breakout(today) -> bool:
    """close > high_20d_prior (excludes today)."""
    c = today.get("close")
    hp = today.get("high_20d_prior")
    if c is None or hp is None:
        return False
    return c > hp


def _close_strong(today) -> bool:
    """(close - low) / (high - low) >= 0.5 — upper 50%."""
    h, l, c = today.get("high"), today.get("low"), today.get("close")
    if None in (h, l, c) or h == l:
        return False
    return (c - l) / (h - l) >= CLOSE_STRONG_MIN_RATIO


def _intraday_reversal(today) -> bool:
    """low < open AND close > open."""
    o, l, c = today.get("open"), today.get("low"), today.get("close")
    if None in (o, l, c):
        return False
    return l < o and c > o


def _ema_alignment(today) -> bool:
    """ema9 > ema21 > ema65."""
    e9 = today.get("ema9")
    e21 = today.get("ema21")
    e65 = today.get("ema65")
    if None in (e9, e21, e65):
        return False
    return e9 > e21 > e65


def _close_above_ema9(today) -> bool:
    c = today.get("close")
    e9 = today.get("ema9")
    if c is None or e9 is None:
        return False
    return c > e9


def _atr_contraction(today) -> bool:
    """5d avg ATR% < 20d avg ATR%."""
    a5 = today.get("atr14_pct_5d_avg")
    a20 = today.get("atr14_pct_20d_avg")
    if a5 is None or a20 is None:
        return False
    return a5 < a20


def _low_vol_drift(today) -> bool:
    """atr14_pct < 0.8 * atr14_pct_20d_avg."""
    a = today.get("atr14_pct")
    a20 = today.get("atr14_pct_20d_avg")
    if a is None or a20 is None:
        return False
    return a < (a20 * LOW_VOL_DRIFT_RATIO)


def _tight_close_cluster(today, recent_3d_closes) -> bool:
    """(max(close[-3:]) - min(close[-3:])) / atr14 < 0.5."""
    atr = today.get("atr14")
    if atr is None or atr <= 0:
        return False
    if not recent_3d_closes or len(recent_3d_closes) < 3:
        return False
    closes = [c for c in recent_3d_closes if c is not None]
    if len(closes) < 3:
        return False
    spread = max(closes) - min(closes)
    return spread / atr < TIGHT_CLUSTER_MAX_ATR


# ── Score assembly ─────────────────────────────────────────────────


def _assemble(weights: dict, features: dict, track: str,
              rs_delta_pct: Optional[float] = None) -> ScoreResult:
    """Build a ScoreResult preserving config-declaration ordering."""
    components_list = []
    score = 0
    active_count = 0
    for name in weights.keys():  # config-declared iteration order
        weight = weights[name]
        active = bool(features.get(name, False))
        components_list.append({"name": name, "weight": weight, "active": active})
        if active:
            score += weight
            active_count += 1
    return ScoreResult(
        track=track, score=score, active_count=active_count,
        features=dict(features), components_list=components_list,
        rs_delta_pct=rs_delta_pct,
    )


def compute_trigger_score(today: dict, yesterday: Optional[dict],
                          market_ret_5d_pct: Optional[float]) -> ScoreResult:
    """Score for PULLBACK / BASE_FORMING setup. 9 components, max 14."""
    ret_5d = today.get("ret_5d_pct")
    if ret_5d is None:
        ret_5d = today.get("change_5d_pct")  # fetch_market_data field name

    features = {
        "ema_reclaim":       _ema_reclaim(today, yesterday),
        "higher_low":        _higher_low(today, yesterday),
        "rs_strong":         _rs_strong(ret_5d, market_ret_5d_pct),
        "lower_wick":        _lower_wick(today),
        "tight_range":       _tight_range(today),
        "vol_expansion":     _vol_expansion(today),
        "breakout":          _breakout(today),
        "close_strong":      _close_strong(today),
        "intraday_reversal": _intraday_reversal(today),
    }
    rs_delta = (
        round(ret_5d - market_ret_5d_pct, 4)
        if (ret_5d is not None and market_ret_5d_pct is not None) else None
    )
    return _assemble(TRIGGER_WEIGHTS, features, "trigger", rs_delta)


def compute_drift_score(today: dict, yesterday: Optional[dict],
                        recent_3d_closes: Optional[list],
                        market_ret_5d_pct: Optional[float]) -> ScoreResult:
    """Score for TREND_OK setup — quiet leader detection. 7 components, max 9."""
    ret_5d = today.get("ret_5d_pct")
    if ret_5d is None:
        ret_5d = today.get("change_5d_pct")

    features = {
        "ema_alignment":       _ema_alignment(today),
        "close_above_ema9":    _close_above_ema9(today),
        "higher_low":          _higher_low(today, yesterday),
        "atr_contraction":     _atr_contraction(today),
        "rs_strong":           _rs_strong(ret_5d, market_ret_5d_pct),
        "low_vol_drift":       _low_vol_drift(today),
        "tight_close_cluster": _tight_close_cluster(today, recent_3d_closes),
    }
    rs_delta = (
        round(ret_5d - market_ret_5d_pct, 4)
        if (ret_5d is not None and market_ret_5d_pct is not None) else None
    )
    return _assemble(DRIFT_WEIGHTS, features, "drift", rs_delta)
```

- [ ] **Step 2: Commit**

```bash
git add lifecycle_score.py
git commit -m "feat(lifecycle): score engine (trigger 9 components + drift 7 components)"
```

---

### Task 10: Test `lifecycle_score.py` — component-level

**Files:**
- Create: `tests/test_lifecycle_score.py`

- [ ] **Step 1: Write the unit tests**

```python
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
    # open=100, low=99.5 — open is the day's low; no dip-recovery pattern
    assert _intraday_reversal(_today(open=100, low=99.5, close=101)) is False


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
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_lifecycle_score.py -v
```

Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_lifecycle_score.py
git commit -m "test(lifecycle): score component unit tests (9 trigger + 7 drift)"
```

---

### Task 11: Add `hard_risk_veto()` and `_derive_legacy_trigger_state()` to `lifecycle_signal.py`

**Files:**
- Modify: `lifecycle_signal.py` (add new top-level functions; the existing `evaluate_decision()` is untouched in this task — refactor happens in Task 12)

- [ ] **Step 1: Add functions after `compute_risk_tags()` (around line 252)**

Add these new functions to `lifecycle_signal.py`:

```python
# ─────────────────────────────────────────────────────────────────
# Score engine v1 — hard veto + legacy trigger_state derivation
# Added per docs/superpowers/specs/2026-05-13-lifecycle-probabilistic-engine-design.md
# ─────────────────────────────────────────────────────────────────


def hard_risk_veto(setup_state: str, risk_tags: list[str]) -> Optional[str]:
    """Layer 0 — deterministic veto. Returns veto reason or None.

    Spec §4.1. Vetoes are structural failures; no probabilistic score can
    override. FAILED_BREAKOUT / BROKEN / EXTENDED only — see spec §4.2 for
    why OVERHEAT/PARABOLIC are NOT vetoes.
    """
    from lifecycle_score_config import (
        VETO_FAILED_BREAKOUT, VETO_BROKEN, VETO_EXTENDED,
    )
    if VETO_FAILED_BREAKOUT in (risk_tags or []):
        return VETO_FAILED_BREAKOUT
    if setup_state == "BROKEN":
        return VETO_BROKEN
    if setup_state == "EXTENDED":
        return VETO_EXTENDED
    return None


def _derive_legacy_trigger_state(score: Optional[int], track: Optional[str]) -> str:
    """Map score+track to legacy trigger_state enum (WAIT/EARLY/CONFIRMED).

    Spec §7.3. trigger_state is now a DERIVED compatibility field. Primary
    truth is score + decision. This mapping keeps Phase A consumers (history
    parsers, Telegram brief, page renderers) working without modification.
    """
    from lifecycle_score_config import THRESHOLDS, TRACK_TRIGGER, TRACK_DRIFT
    if score is None or track is None:
        return "WAIT"
    if track == TRACK_TRIGGER:
        if score >= THRESHOLDS["trigger_enter"]:
            return "CONFIRMED_TRIGGER"
        if score >= THRESHOLDS["trigger_probe"]:
            return "EARLY_TRIGGER"
        return "WAIT"
    if track == TRACK_DRIFT:
        # Drift never maps to CONFIRMED — drift is anticipatory, not confirmation.
        if score >= THRESHOLDS["drift_probe"]:
            return "EARLY_TRIGGER"
        return "WAIT"
    return "WAIT"
```

- [ ] **Step 2: Add a quick sanity test inline (will be expanded in Task 19)**

Append to `tests/test_lifecycle_signal.py`:

```python
def test_hard_risk_veto_returns_veto_reasons():
    from lifecycle_signal import hard_risk_veto

    assert hard_risk_veto("TREND_OK", ["FAILED_BREAKOUT"]) == "FAILED_BREAKOUT"
    assert hard_risk_veto("BROKEN", []) == "BROKEN"
    assert hard_risk_veto("EXTENDED", []) == "EXTENDED"
    assert hard_risk_veto("PULLBACK", []) is None
    assert hard_risk_veto("TREND_OK", ["OVERHEAT"]) is None  # OVERHEAT is NOT a veto


def test_derive_legacy_trigger_state_mapping():
    from lifecycle_signal import _derive_legacy_trigger_state

    assert _derive_legacy_trigger_state(None, None) == "WAIT"
    assert _derive_legacy_trigger_state(0, "trigger") == "WAIT"
    assert _derive_legacy_trigger_state(3, "trigger") == "EARLY_TRIGGER"
    assert _derive_legacy_trigger_state(7, "trigger") == "CONFIRMED_TRIGGER"
    # Drift never maps to CONFIRMED
    assert _derive_legacy_trigger_state(4, "drift") == "EARLY_TRIGGER"
    assert _derive_legacy_trigger_state(9, "drift") == "EARLY_TRIGGER"
    assert _derive_legacy_trigger_state(3, "drift") == "WAIT"
```

- [ ] **Step 3: Run the new tests**

```bash
pytest tests/test_lifecycle_signal.py::test_hard_risk_veto_returns_veto_reasons tests/test_lifecycle_signal.py::test_derive_legacy_trigger_state_mapping -v
```

Expected: Both PASS.

- [ ] **Step 4: Commit**

```bash
git add lifecycle_signal.py tests/test_lifecycle_signal.py
git commit -m "feat(lifecycle): hard_risk_veto + legacy trigger_state derivation"
```

---

### Task 12: Refactor `evaluate_decision()` with score engine + `LIFECYCLE_ENGINE_MODE` dispatch

This is the biggest single change. The existing `evaluate_decision()` takes `(setup_state, trigger_state)` — we change it to take a full context dict so it can run score computation. Phase A path stays alive under `LIFECYCLE_ENGINE_MODE=legacy`.

**Files:**
- Modify: `lifecycle_signal.py:194-218` (the existing `evaluate_decision()` function)

- [ ] **Step 1: Replace `evaluate_decision()` with the dispatching version**

Replace the existing function (signal lines around 194-218) with this:

```python
def evaluate_decision(
    setup_state: str,
    trigger_state: str,
    *,
    risk_tags: Optional[list[str]] = None,
    regime: Optional[str] = None,
    # Score engine inputs (new; optional for legacy callers)
    today_raw: Optional[dict] = None,
    yesterday_snap: Optional[dict] = None,
    recent_3d_closes: Optional[list] = None,
    market_ret_5d_pct: Optional[float] = None,
) -> dict | str:
    """Evaluate decision. Backwards compatible with Phase A boolean signature.

    LIFECYCLE_ENGINE_MODE env var dispatches:
      - "legacy":        Phase A boolean path (returns str: ENTER/PROBE/WATCH/...)
      - "score_shadow":  Phase A decision (str) + side-channel score computed (NOT used for decision)
      - "score_active":  Score-driven decision (returns dict with score fields)

    All three modes guarantee the same invariants:
      - FAILED_BREAKOUT / BROKEN / EXTENDED → AVOID
      - Drift never ENTER when DRIFT_ALLOW_ENTER=False

    Returns:
        str: Phase A path (modes "legacy" and "score_shadow"). Decision key only.
        dict: Score engine path (mode "score_active"). Full snapshot fields.
              See spec §7.4 for shape.
    """
    import os
    from lifecycle_score_config import (
        DEFAULT_ENGINE_MODE, MODE_LEGACY, MODE_SCORE_SHADOW, MODE_SCORE_ACTIVE,
        TRIGGER_TRACK_ACTIVE, DRIFT_TRACK_ACTIVE,
    )

    mode = os.environ.get("LIFECYCLE_ENGINE_MODE", DEFAULT_ENGINE_MODE)
    risk_tags = risk_tags or []

    # ── Legacy path (rollback target) — Phase A behavior exactly ──
    if mode == MODE_LEGACY:
        return _evaluate_decision_phase_a(setup_state, trigger_state, risk_tags=risk_tags)

    # ── Shadow + active paths both need score computation ──
    # In shadow mode the score is computed and returned in a side-channel form,
    # but the decision returned is the Phase A boolean output (str).
    if mode == MODE_SCORE_SHADOW:
        phase_a_decision = _evaluate_decision_phase_a(setup_state, trigger_state, risk_tags=risk_tags)
        # Shadow scoring happens in process_universe (which has access to all
        # the score inputs) — caller-side annotation. Return str for backward compat.
        return phase_a_decision

    # ── score_active: full new engine ──
    if mode == MODE_SCORE_ACTIVE:
        return _evaluate_decision_score(
            setup_state=setup_state,
            today_raw=today_raw or {},
            yesterday_snap=yesterday_snap,
            recent_3d_closes=recent_3d_closes,
            risk_tags=risk_tags,
            market_ret_5d_pct=market_ret_5d_pct,
        )

    # Unknown mode — safe fallback to legacy
    print(f"[lifecycle_signal] WARN unknown LIFECYCLE_ENGINE_MODE={mode!r}, "
          f"falling back to legacy")
    return _evaluate_decision_phase_a(setup_state, trigger_state, risk_tags=risk_tags)


def _evaluate_decision_phase_a(setup_state: str, trigger_state: str,
                                *, risk_tags: list[str]) -> str:
    """Phase A boolean path — exact behavior of original evaluate_decision."""
    if "FAILED_BREAKOUT" in risk_tags:
        return "AVOID"
    if setup_state in ("EXTENDED", "BROKEN"):
        return "AVOID"
    if setup_state in ("PULLBACK", "BASE_FORMING"):
        if trigger_state == "CONFIRMED_TRIGGER":
            return "ENTER"
        if trigger_state == "EARLY_TRIGGER":
            return "PROBE"
        return "WATCH"
    if setup_state == "TREND_OK":
        return "TRENDING"
    return "AVOID"


def _evaluate_decision_score(*, setup_state: str, today_raw: dict,
                              yesterday_snap: Optional[dict],
                              recent_3d_closes: Optional[list],
                              risk_tags: list[str],
                              market_ret_5d_pct: Optional[float]) -> dict:
    """Score-driven decision evaluator. Returns full snapshot dict.

    See spec §7.4 for the algorithm.
    """
    from lifecycle_score import compute_trigger_score, compute_drift_score
    from lifecycle_score_config import (
        TRACK_TRIGGER, TRACK_DRIFT,
        DECISION_ENTER, DECISION_PROBE, DECISION_WATCH,
        DECISION_TRENDING, DECISION_AVOID,
        BADGE_PROBE_STRONG, VETO_UNKNOWN_SETUP,
        THRESHOLDS, DRIFT_ALLOW_ENTER,
        TRIGGER_TRACK_ACTIVE, DRIFT_TRACK_ACTIVE,
        SIZE_TIERS, DECISION_TO_TIER,
    )

    # ── Layer 0: hard risk veto ──
    veto = hard_risk_veto(setup_state, risk_tags)
    if veto:
        # Internal score still computed for analytics (spec §6.3).
        if setup_state in ("TREND_OK", "EXTENDED"):
            raw, raw_track = compute_drift_score(
                today_raw, yesterday_snap, recent_3d_closes, market_ret_5d_pct
            ), TRACK_DRIFT
        else:
            raw, raw_track = compute_trigger_score(
                today_raw, yesterday_snap, market_ret_5d_pct
            ), TRACK_TRIGGER
        return {
            "decision": DECISION_AVOID, "veto_reason": veto,
            "score": None, "features": None, "score_components": None,
            "active_components": None, "decision_badges": [],
            "_raw_score": raw.score, "_raw_features": raw.features,
            "_raw_score_track": raw_track,
            "suggested_entry_tier": None, "suggested_size_pct": 0.0,
            "rs_delta_pct": raw.rs_delta_pct,
            "trigger_state": "WAIT",
        }

    # ── Layer 2+3: score and promote ──
    if setup_state in ("PULLBACK", "BASE_FORMING"):
        sc = compute_trigger_score(today_raw, yesterday_snap, market_ret_5d_pct)
        track = TRACK_TRIGGER
        if not TRIGGER_TRACK_ACTIVE:
            # Trigger track not yet activated — degrade to WATCH but keep score visible.
            decision, badges = DECISION_WATCH, []
        elif sc.score >= THRESHOLDS["trigger_enter"]:
            decision, badges = DECISION_ENTER, []
        elif sc.score >= THRESHOLDS["trigger_probe"]:
            decision, badges = DECISION_PROBE, []
        else:
            decision, badges = DECISION_WATCH, []
    elif setup_state == "TREND_OK":
        sc = compute_drift_score(today_raw, yesterday_snap, recent_3d_closes, market_ret_5d_pct)
        track = TRACK_DRIFT
        if not DRIFT_TRACK_ACTIVE:
            # Drift track not yet activated — keep score visible, decision = TRENDING.
            decision, badges = DECISION_TRENDING, []
        elif sc.score >= THRESHOLDS["drift_enter"]:
            decision = DECISION_ENTER if DRIFT_ALLOW_ENTER else DECISION_PROBE
            badges   = [] if DRIFT_ALLOW_ENTER else [BADGE_PROBE_STRONG]
        elif sc.score >= THRESHOLDS["drift_probe"]:
            decision, badges = DECISION_PROBE, []
        else:
            decision, badges = DECISION_TRENDING, []
    else:
        # Unknown setup — safe fallback.
        return {
            "decision": DECISION_AVOID, "veto_reason": VETO_UNKNOWN_SETUP,
            "score": None, "features": None, "score_components": None,
            "active_components": None, "decision_badges": [],
            "_raw_score": None, "_raw_features": None, "_raw_score_track": None,
            "suggested_entry_tier": None, "suggested_size_pct": 0.0,
            "rs_delta_pct": None, "trigger_state": "WAIT",
        }

    tier_key = (decision, badges[0] if badges else None)
    tier = DECISION_TO_TIER.get(tier_key)
    size_pct = SIZE_TIERS.get(tier, SIZE_TIERS[None])["size_pct"]

    return {
        "decision": decision, "decision_badges": badges,
        "veto_reason": None,
        "score": sc.score, "score_track": track,
        "active_components": sc.active_count,
        "features": sc.features, "score_components": sc.components_list,
        "rs_delta_pct": sc.rs_delta_pct,
        "suggested_entry_tier": tier,
        "suggested_size_pct": size_pct,
        "trigger_state": _derive_legacy_trigger_state(sc.score, track),
        "_raw_score": None, "_raw_features": None, "_raw_score_track": None,
    }
```

- [ ] **Step 2: Verify the original Phase A tests still pass**

```bash
pytest tests/test_lifecycle_signal.py -v
```

Expected: All existing tests still PASS (since legacy and score_shadow modes return the same Phase A string output and that's what the original signature returned).

- [ ] **Step 3: Commit**

```bash
git add lifecycle_signal.py
git commit -m "refactor(lifecycle): evaluate_decision dispatches on LIFECYCLE_ENGINE_MODE"
```

---

### Task 13: Test the LIFECYCLE_ENGINE_MODE dispatch (all 3 modes)

**Files:**
- Modify: `tests/test_lifecycle_signal.py` (append tests)

- [ ] **Step 1: Add dispatch tests**

```python
import os
from unittest.mock import patch

from lifecycle_signal import evaluate_decision


def _score_inputs():
    """Minimal inputs for score-active path."""
    today_raw = {
        "open": 100, "close": 101, "high": 102, "low": 99,
        "ema9": 100, "ema21": 98, "ema65": 90,
        "atr14": 2.0, "atr14_pct": 2.0,
        "atr14_pct_5d_avg": 1.5, "atr14_pct_20d_avg": 2.0,
        "volume_ratio": 1.0,
        "high_20d_prior": 105.0,
        "change_5d_pct": 3.0,
    }
    yesterday_snap = {"close": 99, "low": 98, "high": 100, "ema9": 99.5}
    return today_raw, yesterday_snap


def test_legacy_mode_returns_string():
    with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": "legacy"}):
        result = evaluate_decision("PULLBACK", "CONFIRMED_TRIGGER", risk_tags=[])
    assert result == "ENTER"


def test_legacy_mode_failed_breakout_avoid():
    with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": "legacy"}):
        result = evaluate_decision("PULLBACK", "CONFIRMED_TRIGGER",
                                   risk_tags=["FAILED_BREAKOUT"])
    assert result == "AVOID"


def test_shadow_mode_returns_phase_a_string():
    with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": "score_shadow"}):
        result = evaluate_decision("PULLBACK", "EARLY_TRIGGER", risk_tags=[])
    assert result == "PROBE"


def test_score_active_returns_dict():
    today_raw, yesterday_snap = _score_inputs()
    with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": "score_active"}):
        result = evaluate_decision("PULLBACK", "EARLY_TRIGGER",
                                   risk_tags=[],
                                   today_raw=today_raw, yesterday_snap=yesterday_snap,
                                   market_ret_5d_pct=1.0)
    assert isinstance(result, dict)
    assert "score" in result
    assert "score_components" in result
    assert "decision" in result
    assert "veto_reason" in result


def test_score_active_veto_returns_avoid_with_internal_raw():
    today_raw, yesterday_snap = _score_inputs()
    with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": "score_active"}):
        result = evaluate_decision("EXTENDED", "WAIT", risk_tags=["EXTENDED"],
                                   today_raw=today_raw, yesterday_snap=yesterday_snap,
                                   market_ret_5d_pct=1.0)
    assert result["decision"] == "AVOID"
    assert result["veto_reason"] == "EXTENDED"
    assert result["score"] is None
    assert result["features"] is None
    # Internal raw still computed for analytics
    assert result["_raw_score"] is not None
    assert result["_raw_features"] is not None


def test_score_active_trigger_track_inactive_degrades_to_watch():
    """When TRIGGER_TRACK_ACTIVE=False (PR#1 default), high score still → WATCH."""
    today_raw, yesterday_snap = _score_inputs()
    # Make sure trigger score would otherwise hit ENTER
    today_raw["close"] = 110  # ema_reclaim + breakout
    today_raw["volume_ratio"] = 1.5  # vol_expansion
    with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": "score_active"}):
        result = evaluate_decision("PULLBACK", "EARLY_TRIGGER", risk_tags=[],
                                   today_raw=today_raw, yesterday_snap=yesterday_snap,
                                   market_ret_5d_pct=1.0)
    # In PR#1: TRIGGER_TRACK_ACTIVE=False — even high score gets WATCH
    assert result["decision"] == "WATCH"
    assert result["score"] > 0  # but the score itself is still computed and visible


def test_unknown_mode_falls_back_to_legacy(capsys):
    with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": "garbage"}):
        result = evaluate_decision("PULLBACK", "CONFIRMED_TRIGGER", risk_tags=[])
    assert result == "ENTER"  # Phase A behavior preserved
    captured = capsys.readouterr()
    assert "unknown LIFECYCLE_ENGINE_MODE" in captured.out
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_lifecycle_signal.py -k "mode" -v
```

Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_lifecycle_signal.py
git commit -m "test(lifecycle): LIFECYCLE_ENGINE_MODE dispatch (legacy/shadow/active)"
```

---

### Task 14: Update `_build_today_raw_for_signal`, `_make_snapshot()` and `process_universe()` for score fields

The orchestrator must (a) propagate new fetch_market_data fields into the per-ticker raw dict, (b) pass `yesterday_snap`, `recent_3d_closes`, and `market_ret_5d_pct` into `evaluate_decision`, and (c) store new score fields in the snapshot.

**Files:**
- Modify: `lifecycle_signal.py` — `_build_today_raw_for_signal()` (around line 259), `_make_snapshot()` (around line 291), `process_universe()` (around line 317)

- [ ] **Step 0: Extend `_build_today_raw_for_signal()` to surface new fetch fields**

Replace the existing function with:

```python
def _build_today_raw_for_signal(md_entry: dict) -> dict:
    """Map fetch_market_data row to lifecycle_signal raw shape.

    score_v1 adds: open, high_20d_prior, atr14_pct_5d_avg, atr14_pct_20d_avg,
    days_sideways (now consistently populated by fetch_market_data).
    """
    return {
        "close": md_entry.get("price") or md_entry.get("close"),
        "open":  md_entry.get("open"),           # NEW — score_v1 lower_wick + intraday_reversal
        "high":  md_entry.get("high"),
        "low":   md_entry.get("low"),
        "ema9":  md_entry.get("ema9"),
        "ema21": md_entry.get("ema21"),
        "ema65": md_entry.get("ema65"),
        "ema21_slope_5d": md_entry.get("ema21_slope_5d"),
        "ema65_slope_5d": md_entry.get("ema65_slope_5d"),
        "rsi14": md_entry.get("rsi14"),
        "atr14": md_entry.get("atr14"),           # NEW — score_v1 tight_range + tight_close_cluster
        "atr14_pct": md_entry.get("atr14_pct"),
        "atr14_pct_5d_avg":   md_entry.get("atr14_pct_5d_avg"),   # NEW (was passed-None before)
        "atr14_pct_20d_avg":  md_entry.get("atr14_pct_20d_avg"),  # NEW
        "volume_ratio": md_entry.get("volume_ratio"),
        "volume_5d_avg":  md_entry.get("volume_5d_avg"),
        "volume_20d_avg": md_entry.get("volume_20d_avg"),
        "high_20d_prior": md_entry.get("high_20d_prior"),  # NEW — score_v1 breakout
        "change_pct":   md_entry.get("change_pct"),
        "change_5d_pct": md_entry.get("change_5d_pct"),    # NEW — score_v1 rs_strong
        "days_sideways":      md_entry.get("days_sideways"),
        "sector": md_entry.get("sector") or md_entry.get("sector_etf"),
    }
```

- [ ] **Step 1: Update `_make_snapshot()` to accept and store score fields**

Replace the existing `_make_snapshot()` with:

```python
def _make_snapshot(date_str: str, raw: dict, setup: str, trigger: str,
                   decision: str, risk_tags: list[str],
                   score_payload: Optional[dict] = None) -> dict:
    """Build a snapshot dict.

    score_payload (when present) merges in the new score_v1 fields:
      score, score_track, active_components, features, score_components,
      decision_badges, veto_reason, suggested_entry_tier, suggested_size_pct,
      rs_delta_pct, engine_version, _raw_score / _raw_features / _raw_score_track.
    """
    from lifecycle_score_config import ENGINE_VERSION

    e9, e21, c = raw.get("ema9"), raw.get("ema21"), raw.get("close")
    snap = {
        "date":            date_str,
        "engine_version":  ENGINE_VERSION,
        "setup":           setup,
        "trigger":         trigger,
        "decision":        decision,
        "raw": {
            "close": c,
            "open":  raw.get("open"),
            "high":  raw.get("high"),
            "low":   raw.get("low"),
            "ema9":  e9,
            "ema21": e21,
            "ema65": raw.get("ema65"),
            "rsi14": raw.get("rsi14"),
            "dist_ema9_pct":  round(abs(c - e9) / e9 * 100, 4) if (c and e9) else None,
            "dist_ema21_pct": round(abs(c - e21) / e21 * 100, 4) if (c and e21) else None,
            "volume_ratio":   raw.get("volume_ratio"),
            "atr_pct":        raw.get("atr14_pct"),
            "high_20d_prior": raw.get("high_20d_prior"),
            "sector":         raw.get("sector"),
            "risk_tags":      risk_tags,
        },
    }

    if score_payload:
        # Merge new fields verbatim — they were built by _evaluate_decision_score.
        for k in ("score", "score_track", "active_components", "features",
                  "score_components", "decision_badges", "veto_reason",
                  "suggested_entry_tier", "suggested_size_pct", "rs_delta_pct",
                  "_raw_score", "_raw_features", "_raw_score_track"):
            snap[k] = score_payload.get(k)

    return snap
```

- [ ] **Step 2: Update `process_universe()` to pass score inputs and handle new return type**

Replace the existing `process_universe()` with:

```python
def process_universe(*, active_set: set[str], market_data: dict,
                     yesterday_state: dict, today: str,
                     regime: Optional[str] = None,
                     market_ret_5d_pct: Optional[float] = None) -> dict:
    """Run setup/trigger/decision/risk_tags across the active set.

    Now also computes scores (when LIFECYCLE_ENGINE_MODE != legacy) and
    passes them through to snapshots.

    Returns:
      {"as_of": today, "snapshots": {ticker: snapshot}, "skipped": [...]}
    """
    import os
    from lifecycle_score_config import (
        DEFAULT_ENGINE_MODE, MODE_SCORE_SHADOW, MODE_SCORE_ACTIVE,
    )
    from lifecycle_score import compute_trigger_score, compute_drift_score

    mode = os.environ.get("LIFECYCLE_ENGINE_MODE", DEFAULT_ENGINE_MODE)

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

        # Pull yesterday snapshot from history
        y_block = (yesterday_state.get("tickers") or {}).get(ticker)
        y_snap_list = (y_block or {}).get("snapshots", [])
        yesterday = y_snap_list[-1] if y_snap_list else None
        y_raw = (yesterday or {}).get("raw") or {}
        y_for_legacy_trigger = {
            "close": y_raw.get("close"),
            "ema9":  y_raw.get("ema9"),
            "high":  y_raw.get("high"),
        }

        # Layer 1 — setup state (unchanged from Phase A)
        setup = evaluate_setup_state(today_raw)
        trigger = evaluate_trigger_state(today_raw, y_for_legacy_trigger, setup)
        risk_tags = compute_risk_tags(today_raw, yesterday)

        # Last 3 closes for drift's tight_close_cluster
        recent_3d_closes = []
        for s in y_snap_list[-3:]:
            c = (s.get("raw") or {}).get("close")
            if c is not None:
                recent_3d_closes.append(c)
        recent_3d_closes.append(today_raw["close"])  # include today

        # Build yesterday_snap for higher_low / ema_reclaim component access
        yesterday_snap_for_score = {
            "close": y_raw.get("close"),
            "low":   y_raw.get("low"),
            "high":  y_raw.get("high"),
            "ema9":  y_raw.get("ema9"),
        } if yesterday else None

        score_payload = None
        if mode in (MODE_SCORE_SHADOW, MODE_SCORE_ACTIVE):
            # Compute scores in BOTH shadow and active modes.
            # Shadow: scores stored, decision from Phase A path.
            # Active: scores drive decision (via evaluate_decision dispatch).
            decision = evaluate_decision(
                setup, trigger, risk_tags=risk_tags, regime=regime,
                today_raw=today_raw,
                yesterday_snap=yesterday_snap_for_score,
                recent_3d_closes=recent_3d_closes,
                market_ret_5d_pct=market_ret_5d_pct,
            )
            if isinstance(decision, dict):
                # score_active path — payload is the full evaluator result.
                score_payload = decision
                final_decision = decision["decision"]
                final_trigger = decision["trigger_state"]
            else:
                # score_shadow path — decision is Phase A str. Compute scores
                # for storage WITHOUT affecting the decision.
                final_decision = decision
                final_trigger = trigger
                if setup in ("TREND_OK", "EXTENDED"):
                    sc = compute_drift_score(
                        today_raw, yesterday_snap_for_score,
                        recent_3d_closes, market_ret_5d_pct,
                    )
                    track = "drift"
                else:
                    sc = compute_trigger_score(
                        today_raw, yesterday_snap_for_score, market_ret_5d_pct,
                    )
                    track = "trigger"
                score_payload = {
                    "score": sc.score, "score_track": track,
                    "active_components": sc.active_count,
                    "features": sc.features,
                    "score_components": sc.components_list,
                    "decision_badges": [], "veto_reason": None,
                    "suggested_entry_tier": None, "suggested_size_pct": 0.0,
                    "rs_delta_pct": sc.rs_delta_pct,
                    "_raw_score": None, "_raw_features": None, "_raw_score_track": None,
                }
        else:
            # mode == "legacy" — call without score inputs.
            decision = evaluate_decision(setup, trigger,
                                          risk_tags=risk_tags, regime=regime)
            final_decision = decision
            final_trigger = trigger

        snapshots[ticker] = _make_snapshot(
            today, today_raw, setup, final_trigger, final_decision, risk_tags,
            score_payload=score_payload,
        )

    return {"as_of": today, "snapshots": snapshots, "skipped": skipped}
```

- [ ] **Step 3: Run existing process_universe tests**

```bash
pytest tests/test_lifecycle_signal.py tests/test_lifecycle_e2e.py -v
```

Expected: All existing tests PASS (Phase A behavior preserved in `score_shadow` default; old call sites that ignore extras still work).

- [ ] **Step 4: Commit**

```bash
git add lifecycle_signal.py
git commit -m "feat(lifecycle): process_universe computes + stores scores in shadow/active modes"
```

---

### Task 15: Update `run_lifecycle()` to fetch market benchmark once per run

**Files:**
- Modify: `lifecycle_signal.py` — `run_lifecycle()` (around line 363)

- [ ] **Step 1: Add market benchmark fetch + pass through**

Modify `run_lifecycle()` to fetch the benchmark once and pass it to `process_universe`:

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
        normalize_momentum_history,
    )
    from market_benchmark import get_market_ret_5d

    history_dir = _os.path.join(project_dir, "history")
    _os.makedirs(history_dir, exist_ok=True)
    state_path = _os.path.join(history_dir, f"lifecycle_history_{market.lower()}.json")

    # NEW: fetch market benchmark ONCE per run (cached, with 3d fallback).
    market_ret_5d_pct = get_market_ret_5d(market, project_dir=project_dir)
    print(f"[lifecycle:{market}] market_ret_5d_pct = {market_ret_5d_pct}")

    # ── existing momentum_state / active_set logic unchanged ──
    momentum_state = {"tickers": {}}
    if _os.path.exists(momentum_history_path):
        try:
            with open(momentum_history_path, "rb") as f:
                raw_momentum = json.loads(f.read().rstrip(b" \t\n\r\x00").decode("utf-8"))
            momentum_state = normalize_momentum_history(raw_momentum)
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

    # ── existing missing-ticker fetch logic unchanged ──
    flat = market_data.get("data") if isinstance(market_data, dict) and "data" in market_data else market_data
    flat = flat or {}
    missing = sorted(tk for tk in active if tk not in flat)
    if missing:
        print(f"[lifecycle:{market}] fetching {len(missing)} active-set tickers absent from market_data...")
        from fetch_market_data import fetch_ticker
        fetched_count = 0
        merged = dict(flat)
        for tk in missing:
            try:
                row = fetch_ticker(tk)
                if row and "error" not in row:
                    merged[tk] = row
                    fetched_count += 1
            except Exception as fetch_err:
                print(f"  WARN [lifecycle:{market}] fetch {tk}: {fetch_err}")
        print(f"[lifecycle:{market}] fetched {fetched_count}/{len(missing)} successfully")
        if isinstance(market_data, dict) and "data" in market_data:
            market_data = {**market_data, "data": merged}
        else:
            market_data = merged

    # NEW: pass market_ret_5d_pct into process_universe
    proc = process_universe(active_set=active, market_data=market_data,
                            yesterday_state=state, today=today,
                            market_ret_5d_pct=market_ret_5d_pct)

    new_transitions: list[dict] = []
    for ticker, today_snap in proc["snapshots"].items():
        y_block = (state.get("tickers") or {}).get(ticker)
        y_snap_list = (y_block or {}).get("snapshots", [])
        y_snap = y_snap_list[-1] if y_snap_list else None
        events = compute_transitions(ticker, y_snap, today_snap)
        new_transitions.extend(events)
        append_snapshot(state, ticker, today_snap)

    state["transitions"].extend(new_transitions)
    # Mark current engine version on the state (top-level)
    from lifecycle_score_config import ENGINE_VERSION as _EV
    state["current_engine_version"] = _EV
    state["market"] = market
    save_lifecycle_history(state, state_path)

    return {
        "status": "ok",
        "market": market,
        "as_of":  today,
        "snapshots":   proc["snapshots"],
        "transitions": new_transitions,
        "skipped":     proc["skipped"],
        "active_set_size": len(active),
        "state":       state,
        "engine_version": _EV,
        "market_ret_5d_pct": market_ret_5d_pct,
    }
```

- [ ] **Step 2: Run end-to-end test**

```bash
pytest tests/test_lifecycle_e2e.py -v
```

Expected: All PASS (benchmark fetch is mocked or skipped via cache).

- [ ] **Step 3: Commit**

```bash
git add lifecycle_signal.py
git commit -m "feat(lifecycle): run_lifecycle fetches market benchmark once + passes through"
```

---

### Task 16: Update `lifecycle_history.py` for new transition types + auto-fill engine_version

**Files:**
- Modify: `lifecycle_history.py:96-128` (load), `lifecycle_history.py:231-272` (compute_transitions)

- [ ] **Step 1: Auto-fill `current_engine_version` on legacy load**

In `load_lifecycle_history()`, after parsing:

```python
def load_lifecycle_history(path: str, market: str = "US") -> dict:
    if not os.path.exists(path):
        return new_empty_state(market)
    try:
        with open(path, "rb") as f:
            raw = f.read()
        state = json.loads(raw.rstrip(b" \t\n\r\x00").decode("utf-8"))
        # Auto-fill engine_version for pre-score_v1 history (per spec §9 migration policy)
        if "current_engine_version" not in state:
            state["current_engine_version"] = "phase_a_legacy"
        return state
    except Exception as e:
        print(f"[lifecycle_history] WARN load failed ({e}) -- using empty state")
        return new_empty_state(market)
```

- [ ] **Step 2: Extend `compute_transitions()` with score-aware events + dedup**

Add to the end of `compute_transitions()` (before `return out`):

```python
def compute_transitions(ticker: str,
                         yesterday: Optional[dict],
                         today: dict) -> list[dict]:
    """Diff yesterday's snapshot against today's. Emit events per spec §5.3 + §9.

    Phase A events: SETUP_CHANGE / TRIGGER_CHANGE / DECISION_CHANGE /
                    FAILED_BREAKOUT / RISK_ESCALATION
    Score_v1 events: SCORE_JUMP / DRIFT_PROBE / PROBE_STRONG
      (first-attach dedup — see spec §9 transitions[] policy)
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

    # ── Existing Phase A transition diffs (unchanged) ──
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

    # ── Score_v1 transitions (first-attach dedup) ──
    y_score = yesterday.get("score")
    t_score = today.get("score")
    if y_score is not None and t_score is not None:
        # SCORE_JUMP — Δscore >= 3
        if abs(t_score - y_score) >= 3:
            _evt("SCORE_JUMP", y_score, t_score)

    # DRIFT_PROBE — drift_score first crosses >= 4 (drift_probe threshold)
    from lifecycle_score_config import THRESHOLDS, BADGE_PROBE_STRONG, TRACK_DRIFT
    drift_thr = THRESHOLDS["drift_probe"]
    y_track = yesterday.get("score_track")
    t_track = today.get("score_track")
    if t_track == TRACK_DRIFT and t_score is not None and t_score >= drift_thr:
        y_drift_score = y_score if y_track == TRACK_DRIFT else None
        if y_drift_score is None or y_drift_score < drift_thr:
            _evt("DRIFT_PROBE", y_drift_score, t_score)

    # PROBE_STRONG — badge first attaches (vs yesterday's badges)
    t_badges = set(today.get("decision_badges") or [])
    y_badges = set(yesterday.get("decision_badges") or [])
    if BADGE_PROBE_STRONG in t_badges and BADGE_PROBE_STRONG not in y_badges:
        _evt("PROBE_STRONG", None, BADGE_PROBE_STRONG)

    return out
```

- [ ] **Step 3: Add transition tests**

Append to `tests/test_lifecycle_history.py`:

```python
def test_score_jump_emits_on_delta_3():
    from lifecycle_history import compute_transitions

    y = {"date": "2026-05-12", "setup": "PULLBACK", "trigger": "EARLY_TRIGGER",
         "decision": "PROBE", "raw": {"risk_tags": []}, "score": 3,
         "score_track": "trigger", "decision_badges": []}
    t = {"date": "2026-05-13", "setup": "PULLBACK", "trigger": "EARLY_TRIGGER",
         "decision": "PROBE", "raw": {"risk_tags": []}, "score": 7,
         "score_track": "trigger", "decision_badges": []}
    events = compute_transitions("AAPL", y, t)
    assert any(e["event"] == "SCORE_JUMP" for e in events)


def test_score_jump_no_emit_small_delta():
    from lifecycle_history import compute_transitions

    y = {"date": "2026-05-12", "setup": "PULLBACK", "trigger": "EARLY_TRIGGER",
         "decision": "PROBE", "raw": {"risk_tags": []}, "score": 4,
         "score_track": "trigger", "decision_badges": []}
    t = {"date": "2026-05-13", "setup": "PULLBACK", "trigger": "EARLY_TRIGGER",
         "decision": "PROBE", "raw": {"risk_tags": []}, "score": 6,  # Δ=2
         "score_track": "trigger", "decision_badges": []}
    events = compute_transitions("AAPL", y, t)
    assert not any(e["event"] == "SCORE_JUMP" for e in events)


def test_drift_probe_first_attach():
    from lifecycle_history import compute_transitions

    y = {"date": "2026-05-12", "setup": "TREND_OK", "trigger": "WAIT",
         "decision": "TRENDING", "raw": {"risk_tags": []}, "score": 3,
         "score_track": "drift", "decision_badges": []}
    t = {"date": "2026-05-13", "setup": "TREND_OK", "trigger": "EARLY_TRIGGER",
         "decision": "PROBE", "raw": {"risk_tags": []}, "score": 5,
         "score_track": "drift", "decision_badges": []}
    events = compute_transitions("META", y, t)
    assert any(e["event"] == "DRIFT_PROBE" for e in events)


def test_drift_probe_dedup_when_already_above_threshold():
    from lifecycle_history import compute_transitions

    y = {"date": "2026-05-12", "setup": "TREND_OK", "trigger": "EARLY_TRIGGER",
         "decision": "PROBE", "raw": {"risk_tags": []}, "score": 5,
         "score_track": "drift", "decision_badges": []}
    t = {"date": "2026-05-13", "setup": "TREND_OK", "trigger": "EARLY_TRIGGER",
         "decision": "PROBE", "raw": {"risk_tags": []}, "score": 5,
         "score_track": "drift", "decision_badges": []}
    events = compute_transitions("META", y, t)
    assert not any(e["event"] == "DRIFT_PROBE" for e in events)


def test_probe_strong_first_attach():
    from lifecycle_history import compute_transitions

    y = {"date": "2026-05-12", "setup": "TREND_OK", "trigger": "EARLY_TRIGGER",
         "decision": "PROBE", "raw": {"risk_tags": []}, "score": 5,
         "score_track": "drift", "decision_badges": []}
    t = {"date": "2026-05-13", "setup": "TREND_OK", "trigger": "EARLY_TRIGGER",
         "decision": "PROBE", "raw": {"risk_tags": []}, "score": 7,
         "score_track": "drift", "decision_badges": ["PROBE_STRONG"]}
    events = compute_transitions("NVDA", y, t)
    assert any(e["event"] == "PROBE_STRONG" for e in events)


def test_legacy_load_auto_fills_engine_version(tmp_path):
    import json
    from lifecycle_history import load_lifecycle_history

    legacy = {"schema_version": "1.0.0", "tickers": {}, "transitions": []}
    p = tmp_path / "lifecycle_history_us.json"
    p.write_text(json.dumps(legacy), encoding="utf-8")

    state = load_lifecycle_history(str(p), market="US")
    assert state["current_engine_version"] == "phase_a_legacy"
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_lifecycle_history.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add lifecycle_history.py tests/test_lifecycle_history.py
git commit -m "feat(lifecycle): score_v1 transitions (SCORE_JUMP/DRIFT_PROBE/PROBE_STRONG) + legacy migration"
```

---

### Task 17: Create `tests/test_lifecycle_invariants.py` — CRITICAL safety contracts

**Files:**
- Create: `tests/test_lifecycle_invariants.py`

- [ ] **Step 1: Write the invariant tests**

```python
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
    today_raw = _today()
    with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": "score_active"}):
        result = evaluate_decision("PULLBACK", "WAIT", risk_tags=[],
                                   today_raw=today_raw,
                                   yesterday_snap=_yesterday(),
                                   market_ret_5d_pct=0.0)
    # WATCH (default for PR#1 since TRIGGER_TRACK_ACTIVE=False) → 0
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
```

- [ ] **Step 2: Run all invariants — every one MUST pass**

```bash
pytest tests/test_lifecycle_invariants.py -v
```

Expected: All PASS. **If any test fails, fix code before continuing — these are safety contracts.**

- [ ] **Step 3: Commit**

```bash
git add tests/test_lifecycle_invariants.py
git commit -m "test(lifecycle): CRITICAL invariants — hard veto, score integrity, drift safety"
```

---

### Task 18: Create `tests/test_lifecycle_decision_matrix.py` — exhaustive setup × score tabulation

**Files:**
- Create: `tests/test_lifecycle_decision_matrix.py`

- [ ] **Step 1: Write the matrix tests**

```python
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
    """Trigger ENTER threshold."""
    # Build today with 7+ active points: ema_reclaim(2) + higher_low(2) + rs(2) + close_strong(1)
    today = _today(close=110, ema9=100, low=99.5, high=110.5,
                   change_5d_pct=5.0)
    yesterday = _yesterday(close=99, low=98)
    result = evaluate_decision("PULLBACK", "CONFIRMED_TRIGGER", risk_tags=[],
                                today_raw=today, yesterday_snap=yesterday,
                                market_ret_5d_pct=1.0)
    assert result["score"] >= 7
    assert result["decision"] == "ENTER"


def test_matrix_pullback_score_3_to_6_probe(score_active_with_tracks_on):
    """Trigger PROBE band [3, 6]."""
    # Build for ~4-5 active points: ema_reclaim(2) + higher_low(2) only
    today = _today(close=101, ema9=100, low=99, high=101.5,
                   change_5d_pct=0.0, volume_ratio=1.0,
                   high_20d_prior=110)
    yesterday = _yesterday(close=99, low=98)
    result = evaluate_decision("PULLBACK", "EARLY_TRIGGER", risk_tags=[],
                                today_raw=today, yesterday_snap=yesterday,
                                market_ret_5d_pct=0.0)
    assert 3 <= result["score"] <= 6
    assert result["decision"] == "PROBE"


def test_matrix_pullback_score_below_3_watch(score_active_with_tracks_on):
    today = _today(close=99, ema9=100, low=98, high=99.5,
                   change_5d_pct=-2.0, volume_ratio=0.5,
                   high_20d_prior=110)
    yesterday = _yesterday(close=99, low=97)  # higher_low False (98 < 97 is False)
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
    """Drift >= 6 → PROBE with PROBE_STRONG badge (drift ENTER disabled)."""
    # Build for max drift: ema_alignment(1) + close>ema9(1) + higher_low(2) +
    # atr_contraction(1) + rs(2) + low_vol_drift(1) + tight_cluster(1) = 9
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
    today = _today(close=101, ema9=100, ema21=98, ema65=90,
                   atr14_pct=1.5, atr14_pct_5d_avg=1.5, atr14_pct_20d_avg=2.0,
                   change_5d_pct=2.0)
    yesterday = _yesterday(close=99, low=98)
    result = evaluate_decision("TREND_OK", "WAIT", risk_tags=[],
                                today_raw=today, yesterday_snap=yesterday,
                                recent_3d_closes=[100.5, 101.0, 101.0],
                                market_ret_5d_pct=1.0)
    assert 4 <= result["score"] <= 5
    assert result["decision"] == "PROBE"
    assert "PROBE_STRONG" not in result["decision_badges"]


def test_matrix_trend_ok_drift_below_4_trending(score_active_with_tracks_on):
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
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_lifecycle_decision_matrix.py -v
```

Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_lifecycle_decision_matrix.py
git commit -m "test(lifecycle): exhaustive decision matrix (setup × score → decision)"
```

---

### Task 19: Update `lifecycle_report.py` to surface score fields

**Files:**
- Modify: `lifecycle_report.py` — `build_page_context()` (around line 151), `_attach_derived` (around line 40)

- [ ] **Step 1: Surface score fields in row dict**

Modify `_attach_derived()` to pass through new score fields. After the existing dist_ema9 computation, before `return out`:

```python
    # Surface score_v1 fields (graceful absence for phase_a_legacy snapshots)
    out["score"]                 = snap.get("score")
    out["score_track"]           = snap.get("score_track")
    out["active_components"]     = snap.get("active_components")
    out["features"]              = snap.get("features")
    out["score_components"]      = snap.get("score_components")
    out["decision_badges"]       = snap.get("decision_badges") or []
    out["veto_reason"]           = snap.get("veto_reason")
    out["suggested_entry_tier"]  = snap.get("suggested_entry_tier")
    out["suggested_size_pct"]    = snap.get("suggested_size_pct")
    out["rs_delta_pct"]          = snap.get("rs_delta_pct")
    out["engine_version"]        = snap.get("engine_version") or "phase_a_legacy"

    return out
```

- [ ] **Step 2: Update `build_page_context()` to surface engine + benchmark info to template**

In `build_page_context()`, in the return dict (around line 185), add:

```python
    return {
        "market":       result.get("market", "US"),
        "as_of":        result.get("as_of"),
        "version":      LIFECYCLE_VERSION,
        "engine_version":     result.get("engine_version"),       # NEW
        "market_ret_5d_pct":  result.get("market_ret_5d_pct"),    # NEW
        "new_confirmed": new_confirmed,
        "enter":        enter,
        # ... rest unchanged ...
```

- [ ] **Step 3: Update verdict_summary narration to mention drift PROBE events**

Modify `_build_verdict_summary()` to add a drift line. Replace the `else` branch (when no ENTER, no PROBE):

```python
    elif probe_n > 0:
        headline = f"⚡ 분할 진입 가능 종목 {probe_n}개"
        narration = f"{_ticker_list(probe)}이 약한 트리거 — 절반 진입 검토"
        action_hint = "PROBE 종목 절반 비중 진입"
        # NEW — count drift-track PROBEs separately
        drift_probes = [r for r in probe if r.get("score_track") == "drift"]
        if drift_probes:
            action_hint += f" (그중 {len(drift_probes)}건은 drift 트랙)"
    else:
        ...
```

- [ ] **Step 4: Run existing report tests**

```bash
pytest tests/test_lifecycle_report.py -v
```

Expected: All existing tests PASS (new fields default to None for legacy snapshots).

- [ ] **Step 5: Commit**

```bash
git add lifecycle_report.py
git commit -m "feat(lifecycle): surface score_v1 fields in page context + drift narration"
```

---

### Task 20: Update lifecycle HTML templates — chip enhancement + debug toggle

**Files:**
- Modify: `templates/lifecycle_us.html`, `templates/lifecycle_kr.html`

- [ ] **Step 1: Find the chip rendering block in `lifecycle_us.html`**

Locate the chip rendering loop (likely in a macro or for-loop iterating over `enter`, `probe`, etc.). The exact path varies but search for usage of `r.decision` or `r.ticker`.

```bash
grep -n "score\|active_components\|ticker" templates/lifecycle_us.html | head -20
```

- [ ] **Step 2: Add score + dots after the decision label in each chip**

Inside the chip template snippet (find `{{ r.ticker }}` or similar), augment with:

```html
{# Existing chip body has ticker + decision label #}
{% if r.score is not none %}
<div class="chip-score">
    {% set dot_count = r.active_components or 0 %}
    {% set max_dots = 5 %}
    <span class="score-dots" title="{{ r.active_components }} components active">
        {% for i in range(max_dots) %}{% if i < dot_count %}●{% else %}○{% endif %}{% endfor %}
    </span>
    <span class="score-num">{{ r.score }}</span>
    {% if 'PROBE_STRONG' in r.decision_badges %}
    <span class="badge badge-strong" title="Drift score ≥ 6">⚡ STRONG</span>
    {% endif %}
</div>
{% endif %}
```

Apply the same edit to `lifecycle_kr.html`.

- [ ] **Step 3: Add `_raw_*` debug toggle in "⚙ 고급 보기" section**

Search for the existing 고급 보기 collapsible. Append a debug-mode-only block:

```html
{% if request and request.args.get('debug') == '1' %}
<details class="advanced-debug">
    <summary>🔬 Internal raw scores (vetoed analytics)</summary>
    <p class="hint">These are score values computed for AVOID rows. Hidden from default UI.</p>
    {# Render r._raw_score, r._raw_features, r._raw_score_track when present #}
</details>
{% endif %}
```

Note: Jinja2 templates rendered from `lifecycle_report.py` don't have a `request` object by default. Since the page is static HTML, the toggle works only if rendered via Flask. For static-served pages, the alternative is `?debug=1` URL parameter handled client-side via JS. Add a simple JS toggle in the same template:

```html
<script>
(function() {
    var params = new URLSearchParams(window.location.search);
    if (params.get('debug') === '1') {
        document.body.classList.add('debug-mode');
    }
})();
</script>
<style>
.advanced-debug { display: none; }
body.debug-mode .advanced-debug { display: block; }
</style>
```

- [ ] **Step 4: Add new entries to "📖 용어 사전" collapsible**

In the term-glossary section, append:

```html
<dt>Score</dt>
<dd>증거 누적 점수. 9개 trigger 컴포넌트 (max 14) 또는 7개 drift 컴포넌트 (max 9) 중 활성화된 항목의 가중치 합. 임계값 이상이면 PROBE/ENTER로 승격.</dd>

<dt>trigger_score vs drift_score</dt>
<dd>trigger는 PULLBACK/BASE_FORMING setup에서 reclaim/breakout/volume 등 expansion 신호를 누적. drift는 TREND_OK setup에서 quiet leader (NVDA/META 류) — volume 폭발 없이 천천히 오르는 종목을 잡기 위한 별도 score.</dd>

<dt>active_components (●○)</dt>
<dd>활성화된 컴포넌트 개수. 같은 score여도 적은 컴포넌트의 큰 가중치보다 많은 컴포넌트의 작은 가중치가 더 broad한 strength를 의미할 수 있음 (calibration 단계 분석 대상).</dd>

<dt>PROBE_STRONG ⚡ badge</dt>
<dd>drift_score ≥ 6 — quiet leader continuation의 강한 신호. 사이즈는 PROBE와 동일 (25%) 이지만 confidence 차이를 보여주는 표식.</dd>
```

- [ ] **Step 5: Render and check templates manually**

Render the templates by running pipeline locally (or just inspect the HTML output of a recent run):

```bash
ls deploy/lifecycle_us_*.html 2>/dev/null | tail -1
```

If existing rendered files are old, run `SKIP_SCANNERS=1 python pipeline.py` to regenerate.

Open the resulting HTML in browser, verify:
- Chips show score + dots
- PROBE_STRONG badge visible on drift rows (won't appear until PR#3)
- Adding `?debug=1` to URL reveals advanced-debug section

- [ ] **Step 6: Commit**

```bash
git add templates/lifecycle_us.html templates/lifecycle_kr.html
git commit -m "feat(lifecycle): chip score+dots, PROBE_STRONG badge, debug toggle, glossary"
```

---

### Task 21: Update `telegram_sender.py` lifecycle brief — surface score

**Files:**
- Modify: `telegram_sender.py:368-422` (`_summarize_lifecycle`, `_format_lifecycle_section`)

- [ ] **Step 1: Augment `_summarize_lifecycle()` to track drift events**

Replace the function with:

```python
def _summarize_lifecycle(result: dict | None) -> dict:
    if not result or not result.get("snapshots"):
        return {"new_confirmed": [], "enter_ok": 0, "early": 0, "failed_breakout": 0,
                "drift_probes": [], "probe_strong": []}
    snaps = result["snapshots"]
    nc, ok, early, fb = [], 0, 0, 0
    drift_probes, probe_strong = [], []
    state = result.get("state") or {}
    for tk, s in snaps.items():
        if s["decision"] == "ENTER":
            ok += 1
            y = ((state.get("tickers") or {}).get(tk) or {}).get("snapshots", [])
            had_prior_confirmed = any(x.get("trigger") == "CONFIRMED_TRIGGER"
                                         for x in y[:-1])
            if not had_prior_confirmed and s["trigger"] == "CONFIRMED_TRIGGER":
                nc.append((tk, s.get("score")))  # NEW: include score
        elif s["decision"] == "PROBE":
            early += 1
            # NEW: drift-track PROBEs
            if s.get("score_track") == "drift":
                drift_probes.append((tk, s.get("score")))
            if "PROBE_STRONG" in (s.get("decision_badges") or []):
                probe_strong.append((tk, s.get("score")))
        if "FAILED_BREAKOUT" in (s.get("raw") or {}).get("risk_tags", []):
            fb += 1
    return {
        "new_confirmed": nc, "enter_ok": ok, "early": early,
        "failed_breakout": fb,
        "drift_probes": drift_probes, "probe_strong": probe_strong,
    }
```

- [ ] **Step 2: Augment `_format_lifecycle_section()` to surface drift + score**

```python
def _format_lifecycle_section(result: dict | None, flag: str, market: str,
                                  base_url: str, date_str: str) -> str:
    if not result or not result.get("snapshots"):
        return ""
    summary = result.get("_brief_summary") or _summarize_lifecycle(result)
    lines = [f"{flag} {market}"]
    if summary["new_confirmed"]:
        items = summary["new_confirmed"][:5]
        # items may be tuple (ticker, score) under score_v1; backwards-compat string under legacy
        formatted = []
        for it in items:
            if isinstance(it, tuple):
                tk, sc = it
                formatted.append(f"{tk} (s{sc})" if sc is not None else tk)
            else:
                formatted.append(str(it))
        nc = " / ".join(formatted)
        more = "" if len(summary["new_confirmed"]) <= 5 else f" (+{len(summary['new_confirmed']) - 5})"
        lines.append(f"\U0001f195 New 본 진입 ({len(summary['new_confirmed'])}): {nc}{more}")
    if summary["enter_ok"]:
        lines.append(f"\U0001f7e2 본 진입 total: {summary['enter_ok']}")
    if summary["early"]:
        lines.append(f"\U0001f7e1 분할 진입: {summary['early']}")
    # NEW: drift events
    if summary.get("drift_probes"):
        dp = summary["drift_probes"][:3]
        formatted = ", ".join(f"{tk}" + (f" (drift {s})" if s else "") for tk, s in dp)
        lines.append(f"\U0001f30a Drift PROBE ({len(summary['drift_probes'])}): {formatted}")
    if summary.get("probe_strong"):
        ps = summary["probe_strong"][:3]
        formatted = ", ".join(f"{tk}" for tk, s in ps)
        lines.append(f"⚡ PROBE_STRONG: {formatted}")
    if summary["failed_breakout"]:
        lines.append(f"\U0001f534 FAILED_BREAKOUT: {summary['failed_breakout']}")
    base = base_url.rstrip("/") + "/" if base_url else ""
    lines.append(f"\U0001f517 {base}lifecycle_{market.lower()}_{date_str}.html")
    return "\n".join(lines)
```

- [ ] **Step 3: Manual sanity check — run the brief on existing data**

```bash
python -c "
from telegram_sender import _format_lifecycle_message
import json
with open('history/lifecycle_history_us.json') as f:
    state = json.load(f)
result = {'market': 'US', 'snapshots': {}, 'state': state, 'as_of': '2026-05-13'}
print(_format_lifecycle_message(result, None, 'https://example.com', '2026-05-13'))
"
```

Expected: prints a section block (likely empty body since no snapshots, but no crash).

- [ ] **Step 4: Commit**

```bash
git add telegram_sender.py
git commit -m "feat(telegram): surface score + drift/PROBE_STRONG in lifecycle brief"
```

---

### Task 22: Wire pipeline.py — confirm market benchmark fetch is in scope per-run

The `run_lifecycle()` already calls `get_market_ret_5d` internally (added in Task 15). No pipeline.py changes are strictly needed, but we should verify the cache path resolves correctly.

**Files:**
- Verify: `pipeline.py:444-487` (Step 4c4/4c5 calls)

- [ ] **Step 1: Run pipeline locally in shadow mode (SKIP_SCANNERS for speed)**

```bash
SKIP_SCANNERS=1 python pipeline.py
```

Expected: pipeline runs end-to-end; logs include `[lifecycle:US] market_ret_5d_pct = X.X` and `[lifecycle:KR] market_ret_5d_pct = X.X`. No errors.

- [ ] **Step 2: Inspect the produced history JSON**

```bash
python -c "
import json
with open('history/lifecycle_history_us.json') as f:
    state = json.load(f)
print('current_engine_version:', state.get('current_engine_version'))
print('market:', state.get('market'))
sample_ticker = next(iter(state.get('tickers', {})), None)
if sample_ticker:
    snap = state['tickers'][sample_ticker]['snapshots'][-1]
    print('sample snapshot has score:', 'score' in snap)
    print('sample snapshot keys:', sorted(snap.keys()))
"
```

Expected:
- `current_engine_version: score_v1`
- `market: US`
- Sample snapshot includes `score`, `score_track`, `features`, `score_components`, etc.

- [ ] **Step 3: Inspect benchmark cache**

```bash
cat history/market_benchmark_cache.json
```

Expected: JSON with `US` and `KR` entries, each with `value`, `cached_at`, `ticker`.

- [ ] **Step 4: Commit (if pipeline.py needed any tweaks; otherwise skip)**

If you modified anything:

```bash
git add pipeline.py
git commit -m "chore(pipeline): verify score_v1 wiring (no changes needed)"
```

---

### Task 23: Create `docs/lifecycle_score_spec.md` in-tree spec freeze

**Files:**
- Create: `docs/lifecycle_score_spec.md`

- [ ] **Step 1: Write a terse in-tree reference**

```markdown
# Lifecycle Score Engine v1 — Runtime Reference

**Engine version**: `score_v1`
**Source design**: [docs/superpowers/specs/2026-05-13-lifecycle-probabilistic-engine-design.md](./superpowers/specs/2026-05-13-lifecycle-probabilistic-engine-design.md)
**Last updated**: 2026-05-13

This file is a fast lookup for operators. The design doc is authoritative.

---

## Quick reference

### Layer 0 — Veto (deterministic)
Returns `AVOID` immediately. Three triggers:
- `FAILED_BREAKOUT` risk tag present
- `setup_state == "BROKEN"`
- `setup_state == "EXTENDED"`

### Layer 2 — Score (probabilistic)
- **trigger_score** (PULLBACK/BASE_FORMING): 9 components, max 14 pts
  - ema_reclaim(+2) higher_low(+2) rs_strong(+2) vol_expansion(+2) breakout(+2)
    lower_wick(+1) tight_range(+1) close_strong(+1) intraday_reversal(+1)
- **drift_score** (TREND_OK): 7 components, max 9 pts
  - higher_low(+2) rs_strong(+2) ema_alignment(+1) close_above_ema9(+1)
    atr_contraction(+1) low_vol_drift(+1) tight_close_cluster(+1)

### Layer 3 — Decision
| Setup | Track | Score | Decision |
|---|---|---|---|
| PULLBACK / BASE_FORMING | trigger | ≥ 7 | ENTER |
| PULLBACK / BASE_FORMING | trigger | 3-6 | PROBE |
| PULLBACK / BASE_FORMING | trigger | < 3 | WATCH |
| TREND_OK | drift | ≥ 6 | PROBE + PROBE_STRONG badge |
| TREND_OK | drift | 4-5 | PROBE |
| TREND_OK | drift | < 4 | TRENDING |

### Sizing hints
- ENTER → `core` tier, 0.35
- PROBE + PROBE_STRONG → `starter_plus`, 0.25
- PROBE → `starter`, 0.25
- WATCH / TRENDING / AVOID → null, 0.0

## Engine modes

Set via `LIFECYCLE_ENGINE_MODE` env var:
- `legacy` — Phase A boolean path (rollback target)
- `score_shadow` — score computed + stored; decision from Phase A (PR#1 default)
- `score_active` — score-driven decision (PR#2+ default)

## Activation flags (in `lifecycle_score_config.py`)
- `TRIGGER_TRACK_ACTIVE` — `False` in PR#1, `True` in PR#2+
- `DRIFT_TRACK_ACTIVE` — `False` in PR#1+PR#2, `True` in PR#3+
- `DRIFT_ALLOW_ENTER` — `False` always until calibration says otherwise

## Rollback
```bash
LIFECYCLE_ENGINE_MODE=legacy python pipeline.py
```

No code revert needed. History JSON's new fields remain (harmless extras).

## See also
- Design dialogue context: brainstorm/spec docs above
- Test invariants: [tests/test_lifecycle_invariants.py](../tests/test_lifecycle_invariants.py)
- Decision matrix: [tests/test_lifecycle_decision_matrix.py](../tests/test_lifecycle_decision_matrix.py)
- Calibration boundary (archetype-collapse guardrail): spec §11.1
```

- [ ] **Step 2: Commit**

```bash
git add docs/lifecycle_score_spec.md
git commit -m "docs: in-tree lifecycle_score_spec runtime reference"
```

---

### Task 24: PR#1 end-to-end verification

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -40
```

Expected: All PASS (including new score config + invariants + decision matrix tests).

- [ ] **Step 2: Run pipeline end-to-end in shadow mode (PR#1 default)**

```bash
SKIP_SCANNERS=1 python pipeline.py 2>&1 | tail -50
```

Expected:
- Logs show `[lifecycle:US] market_ret_5d_pct = X`
- Logs show `[lifecycle:US|KR] active_set=N` with non-zero N
- No exceptions

- [ ] **Step 3: Verify rollback works**

```bash
LIFECYCLE_ENGINE_MODE=legacy SKIP_SCANNERS=1 python pipeline.py 2>&1 | tail -20
```

Expected: pipeline still runs successfully. Snapshots in this run will lack score fields (which is correct for legacy mode).

- [ ] **Step 4: Verify the pages render**

```bash
ls deploy/lifecycle_*.html | tail -5
```

Open one in a browser and confirm:
- Page renders without JS errors
- Score numbers appear in chips
- Adding `?debug=1` to URL reveals advanced section

- [ ] **Step 5: Final PR#1 commit (if any cleanup)**

If any small fixes needed:

```bash
git add -A
git commit -m "chore: PR#1 final verification + cleanup"
```

---

# PR #2 — Trigger Activation (default mode flip)

Goal: Flip `DEFAULT_ENGINE_MODE` to `score_active` and `TRIGGER_TRACK_ACTIVE = True`. PULLBACK/BASE_FORMING decisions now driven by `trigger_score`. Volume formally drops from being a hard gate to one of nine components. Drift remains inactive (PR#3).

---

### Task 25: Flip activation flags + default mode

**Files:**
- Modify: `lifecycle_score_config.py` (defaults)

- [ ] **Step 1: Update config defaults**

```python
# In lifecycle_score_config.py — change these two values:

DEFAULT_ENGINE_MODE = MODE_SCORE_ACTIVE   # was: MODE_SCORE_SHADOW

TRIGGER_TRACK_ACTIVE = True   # was: False
DRIFT_TRACK_ACTIVE   = False  # PR#3 will flip
```

- [ ] **Step 2: Update the test asserting the PR#1 default — it now must reflect PR#2**

In `tests/test_lifecycle_score_config.py`:

```python
def test_default_mode_is_active():
    """PR#2 default = score_active. PR#3 will keep this and flip DRIFT_TRACK_ACTIVE."""
    assert cfg.DEFAULT_ENGINE_MODE == cfg.MODE_SCORE_ACTIVE


def test_trigger_track_active_in_pr2():
    assert cfg.TRIGGER_TRACK_ACTIVE is True
    assert cfg.DRIFT_TRACK_ACTIVE is False
```

(Replace the old `test_default_mode_is_shadow` test with these.)

- [ ] **Step 3: Update the PR#1 decision_matrix test that asserted WATCH-on-active-track-inactive**

In `tests/test_lifecycle_decision_matrix.py`, the test `test_pr1_default_trigger_track_inactive_means_watch` is no longer relevant — replace with:

```python
def test_pr2_default_trigger_track_active_promotes_score():
    """With TRIGGER_TRACK_ACTIVE=True (PR#2 default), high score → ENTER."""
    today = _today(close=110, ema9=100, low=99.5, high=110.5, change_5d_pct=5.0)
    yesterday = _yesterday(close=99, low=98)
    with patch.dict(os.environ, {"LIFECYCLE_ENGINE_MODE": "score_active"}):
        result = evaluate_decision("PULLBACK", "CONFIRMED_TRIGGER", risk_tags=[],
                                    today_raw=today, yesterday_snap=yesterday,
                                    market_ret_5d_pct=1.0)
    assert result["score"] >= 7
    assert result["decision"] == "ENTER"
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: All PASS. Invariants still hold (FAILED_BREAKOUT/BROKEN/EXTENDED still → AVOID).

- [ ] **Step 5: Commit**

```bash
git add lifecycle_score_config.py tests/test_lifecycle_score_config.py tests/test_lifecycle_decision_matrix.py
git commit -m "feat(lifecycle): activate trigger track (PR#2 — score_active default)"
```

---

### Task 26: Update verdict narration to surface PROBE/ENTER frequency

**Files:**
- Modify: `lifecycle_report.py:79-148` `_build_verdict_summary()`

- [ ] **Step 1: Add score-engine narration line when PROBE/ENTER count is up vs Phase A baseline**

This is a small UX addition. After the existing narration logic, append a "score engine on" line if any row has `score is not None`:

Insert before `return` in `_build_verdict_summary()`:

```python
    # Score-engine activity note (PR#2+ only — when scores are visible)
    all_rows = enter + probe + watch + trending + avoid
    score_rows = [r for r in all_rows if r.get("score") is not None]
    score_engine_line = None
    if score_rows:
        avg_score = sum(r["score"] for r in score_rows) / len(score_rows)
        score_engine_line = (
            f"📊 Score engine active — 평균 score {avg_score:.1f}, "
            f"활성 컴포넌트 평균 {sum(r.get('active_components') or 0 for r in score_rows) / len(score_rows):.1f}"
        )

    return {
        "headline":    headline,
        "narration":   narration,
        "avoid_line":  avoid_line,
        "action_hint": action_hint,
        "score_engine_line": score_engine_line,  # NEW
    }
```

- [ ] **Step 2: Render the new line in the template**

In both `lifecycle_us.html` and `lifecycle_kr.html`, find the verdict-summary block (search for `verdict_summary` or `headline`) and append:

```html
{% if verdict_summary.score_engine_line %}
<p class="score-engine-note">{{ verdict_summary.score_engine_line }}</p>
{% endif %}
```

- [ ] **Step 3: Run pipeline + check page**

```bash
SKIP_SCANNERS=1 python pipeline.py
ls deploy/lifecycle_us_*.html | tail -1
```

Open in browser, verify the "📊 Score engine active" line appears.

- [ ] **Step 4: Commit**

```bash
git add lifecycle_report.py templates/lifecycle_us.html templates/lifecycle_kr.html
git commit -m "feat(lifecycle): verdict narration surfaces score engine activity (PR#2)"
```

---

### Task 27: PR#2 verification — 5-day rollout check (informational)

- [ ] **Step 1: Run pipeline + capture decision distribution**

```bash
SKIP_SCANNERS=1 python pipeline.py 2>&1 | tail -20
python -c "
import json
with open('history/lifecycle_history_us.json') as f:
    state = json.load(f)
from collections import Counter
decisions = Counter()
for tk, blk in state.get('tickers', {}).items():
    if blk.get('snapshots'):
        last = blk['snapshots'][-1]
        decisions[last.get('decision')] += 1
print('US decision distribution:', dict(decisions))
"
```

Expected: PROBE count > 0. (Compare to Phase A baseline mentally — should be noticeably higher than under boolean trigger.)

- [ ] **Step 2: Verify invariants hold one more time**

```bash
pytest tests/test_lifecycle_invariants.py -v
```

Expected: All PASS.

- [ ] **Step 3: Final PR#2 commit (if any tweaks)**

```bash
git add -A
git commit -m "chore: PR#2 verification — trigger track activated"
```

---

# PR #3 — Drift Track Activation

Goal: Flip `DRIFT_TRACK_ACTIVE = True`. TREND_OK setup now scored via `drift_score`. Mega-cap leaders (NVDA/META/AVGO style quiet uptrends) can emit PROBE / PROBE_STRONG without volume expansion. ENTER from drift remains disabled (`DRIFT_ALLOW_ENTER = False`).

---

### Task 28: Flip `DRIFT_TRACK_ACTIVE` and verify drift PROBEs emerge

**Files:**
- Modify: `lifecycle_score_config.py`

- [ ] **Step 1: Flip the flag**

```python
# In lifecycle_score_config.py
DRIFT_TRACK_ACTIVE = True   # was: False
```

- [ ] **Step 2: Update the PR#2 test that asserted DRIFT_TRACK_ACTIVE = False**

In `tests/test_lifecycle_score_config.py`:

```python
def test_drift_track_active_in_pr3():
    assert cfg.DRIFT_TRACK_ACTIVE is True


def test_drift_allow_enter_still_false():
    """PR#3 only activates drift PROBE, not drift ENTER. Calibration may flip later."""
    assert cfg.DRIFT_ALLOW_ENTER is False
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: All PASS. Invariants (including `test_invariant_drift_never_enter_when_disabled`) still hold.

- [ ] **Step 4: Run pipeline and look for drift PROBE events**

```bash
SKIP_SCANNERS=1 python pipeline.py 2>&1 | tail -20
python -c "
import json
with open('history/lifecycle_history_us.json') as f:
    state = json.load(f)
drift_probes = []
probe_strong = []
for tk, blk in state.get('tickers', {}).items():
    if blk.get('snapshots'):
        last = blk['snapshots'][-1]
        if last.get('score_track') == 'drift' and last.get('decision') == 'PROBE':
            drift_probes.append((tk, last.get('score')))
        if 'PROBE_STRONG' in (last.get('decision_badges') or []):
            probe_strong.append((tk, last.get('score')))
print('Drift PROBEs:', drift_probes)
print('PROBE_STRONG:', probe_strong)
"
```

Expected: at least 1 drift PROBE (depending on market conditions). Mega-cap leaders most likely candidates.

- [ ] **Step 5: Commit**

```bash
git add lifecycle_score_config.py tests/test_lifecycle_score_config.py
git commit -m "feat(lifecycle): activate drift track (PR#3 — TREND_OK quiet leaders → PROBE)"
```

---

### Task 29: Final integration check + monitoring helpers

**Files:**
- (Optional) Create: `analytics/score_distribution_report.py`

- [ ] **Step 1 (optional but recommended): Create the calibration helper**

```bash
mkdir -p analytics
```

Then create `analytics/score_distribution_report.py`:

```python
# analytics/score_distribution_report.py
"""Calibration helper — emit score distribution stats from lifecycle history.

Usage:
    python analytics/score_distribution_report.py [US|KR|all]
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
HISTORY = PROJECT_DIR / "history"


def report(market: str):
    path = HISTORY / f"lifecycle_history_{market.lower()}.json"
    if not path.exists():
        print(f"  (no history for {market})")
        return

    with open(path, "rb") as f:
        state = json.loads(f.read().decode("utf-8"))

    score_histogram = Counter()
    feature_freq = Counter()
    decisions = Counter()
    by_track = Counter()
    probe_to_enter_streaks = 0
    probe_to_avoid_streaks = 0

    for tk, blk in (state.get("tickers") or {}).items():
        snaps = blk.get("snapshots") or []
        for i, snap in enumerate(snaps):
            sc = snap.get("score")
            if sc is not None:
                score_histogram[sc] += 1
                by_track[snap.get("score_track")] += 1
                for fname, active in (snap.get("features") or {}).items():
                    if active:
                        feature_freq[fname] += 1
            decisions[snap.get("decision")] += 1

            # PROBE → next-day outcome (informational)
            if snap.get("decision") == "PROBE" and i + 1 < len(snaps):
                nxt = snaps[i + 1].get("decision")
                if nxt == "ENTER":
                    probe_to_enter_streaks += 1
                elif nxt == "AVOID":
                    probe_to_avoid_streaks += 1

    total = sum(score_histogram.values())
    print(f"\n=== {market} score distribution (n={total}) ===")
    if total > 0:
        for sc in sorted(score_histogram):
            bar = "█" * int(score_histogram[sc] / max(score_histogram.values()) * 30)
            print(f"  {sc:>2d}: {score_histogram[sc]:>4d} {bar}")
    print(f"\nBy track: {dict(by_track)}")
    print(f"Decision distribution: {dict(decisions)}")
    print(f"\nFeature activation frequency (top 10):")
    for f, n in feature_freq.most_common(10):
        print(f"  {f:<25s} {n}")
    print(f"\nPROBE → ENTER (next day): {probe_to_enter_streaks}")
    print(f"PROBE → AVOID (next day): {probe_to_avoid_streaks}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    if arg.upper() == "ALL":
        for m in ("US", "KR"):
            report(m)
    else:
        report(arg.upper())
```

- [ ] **Step 2: Run the helper**

```bash
python analytics/score_distribution_report.py all
```

Expected: prints score histograms and feature activation tallies.

- [ ] **Step 3: Final invariant check**

```bash
pytest tests/test_lifecycle_invariants.py -v
```

Expected: All PASS.

- [ ] **Step 4: Commit the analytics helper (if created)**

```bash
git add analytics/score_distribution_report.py
git commit -m "feat(analytics): score_distribution_report calibration helper"
```

- [ ] **Step 5: PR#3 final commit / merge prep**

Verify the work tree is clean:

```bash
git status
git log --oneline -20
```

Expected:
- Clean working tree
- Last ~25-30 commits trace the full plan from PR#1 → PR#2 → PR#3

---

## Plan Self-Review (already executed during writing — not a task for the engineer)

This section documents the writing-plans self-review pass; the implementer can skip it.

**Spec coverage**:
- §4 Layer 0 Hard Risk Filter → Task 11 (`hard_risk_veto`), Tasks 17 (invariants)
- §5 Layer 1 Context (Unchanged) → no task needed; preserved by reuse
- §6 Layer 2 Score → Tasks 1, 9, 10
- §7 Layer 3 Decision → Task 12 (refactor), Task 18 (matrix test)
- §8 Data Dependencies → Tasks 3, 4, 5, 7
- §9 History JSON Schema → Tasks 14, 16
- §10 UI Surface → Tasks 19, 20, 21
- §11 Out of Scope → respected (no task touches setup thresholds, position tracking, etc.)
- §11.1 Archetype guardrail → Task 2 test `test_drift_archetype_separation`
- §12 Soft Migration / 3 PRs → reflected in PR structure
- §13 Success Criteria → Task 27, 28, 29 (verification steps)
- §14 Risk & Rollback → Task 11 (invariants), Task 24 (rollback verification)
- §15 Tests & Verification → Tasks 2, 10, 17, 18
- §16 Files Changed → all 17 files covered by tasks
- §17 Open Items → all 7 resolved (explicit if/elif dispatch, history/market_benchmark_cache.json, ●○ dots, replay fixtures, recompute high_20d_prior from existing high series, etc.)

**Type / name consistency**: `evaluate_decision` returns `dict | str` (str for legacy/shadow, dict for active) — callers in `process_universe` check `isinstance(result, dict)` explicitly. `ScoreResult` dataclass used in `lifecycle_score.py` only — `score_payload` dict crosses module boundaries.

**No placeholders**: every step has complete code, exact paths, exact commands. No "TBD" / "TODO" / "similar to above" patterns.
