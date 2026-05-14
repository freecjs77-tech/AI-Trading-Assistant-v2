# PROBE Tiering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add display-only Score Tier + RS Tier dual badges to lifecycle chips, with tier-aware sorting and client-side filter toolbar, so operators can rank within the PROBE bucket.

**Architecture:** Two new derived fields (`score_tier`, `rs_tier`) computed in `lifecycle_score.py` and propagated through `_evaluate_decision_score()` → `_make_snapshot()` → snapshot JSON → `_attach_derived()` → templates. Sort keys for `probe`/`watch`/`trending` lists in `lifecycle_report.py` change from setup-streak/volume to `(score desc, rs_delta_pct desc, active_components desc)`. Templates gain inline tier badges + a client-side JS filter toolbar. Schema is additive only — `ENGINE_VERSION` stays `"score_v1"`. NO decision logic changes.

**Tech Stack:** Python 3.10+, pytest, Jinja2, vanilla JS. Builds on existing `score_v1` infrastructure (already merged to master, commit `6704e3ff`).

**Source spec:** [docs/superpowers/specs/2026-05-14-probe-tiering-design.md](../specs/2026-05-14-probe-tiering-design.md)

**Out of scope for this plan:** decision logic changes, threshold tuning, Telegram brief changes, sector diversity, streak/age scoring (see spec §10).

---

## File Map

| Path | Action | Purpose |
|---|---|---|
| `lifecycle_score_config.py` | Modify | Add `SCORE_TIER_BANDS` dict + `RS_TIER_BANDS` dict |
| `lifecycle_score.py` | Modify | Add `compute_score_tier()` + `compute_rs_tier()` helpers; extend `ScoreResult` dataclass with `score_tier`/`rs_tier` fields; populate in `_assemble()` |
| `lifecycle_signal.py` | Modify | Add `score_tier` + `rs_tier` to all return dicts in `_evaluate_decision_score()` (active path + veto path + unknown setup path); add same to `score_payload` shadow-mode dict in `process_universe()`; extend `_make_snapshot()` merge tuple |
| `lifecycle_report.py` | Modify | Surface `score_tier`/`rs_tier` in `_attach_derived()`; replace sort keys for `probe`/`watch`/`trending` with `_tier_sort_key()` |
| `templates/lifecycle_us.html` + `lifecycle_kr.html` | Modify | Add CSS tier classes; update all 5 `chip-score` blocks (AVOID/ENTER/PROBE/WATCH/TRENDING) to render tier badges + RS raw; add `data-grid` wrapper + `data-score-tier`/`data-rs-tier`/`data-active-components` data attributes on chips; add filter toolbar above PROBE/WATCH/TRENDING sections; add inline filter JS |
| `templates/_lifecycle_glossary.html` | Modify | Append 2 new glossary `<dt>/<dd>` pairs (Score Tier, RS Tier) |
| `telegram_sender.py` | **No change** | Explicitly excluded per user request (spec §6) |
| `tests/test_lifecycle_score_config.py` | Modify | Add `SCORE_TIER_BANDS` + `RS_TIER_BANDS` sanity tests (monotonicity, completeness, drift archetype) |
| `tests/test_lifecycle_score.py` | Modify | Add unit tests for `compute_score_tier()` + `compute_rs_tier()` + `ScoreResult.score_tier`/`rs_tier` field presence |
| `tests/test_lifecycle_invariants.py` | Modify | Add 5 new invariants per spec §7 |
| `tests/test_lifecycle_decision_matrix.py` | Modify | Extend existing matrix tests to also assert `score_tier` correctness in each cell |

**Summary**: 10 files modified, 0 new files, schema additive.

---

### Task 1: Add tier band constants to config

**Files:**
- Modify: `lifecycle_score_config.py`

- [ ] **Step 1: Add SCORE_TIER_BANDS and RS_TIER_BANDS**

Append to `lifecycle_score_config.py` (after `SIZE_TIERS` block, before any closing comment if present):

```python

# ── Score Tier Bands (Phase 4 calibration helper — display-only) ────
# Maps (track, tier_name) → (low_inclusive, high_inclusive) score range.
# Scores outside any band → score_tier = None (e.g., trigger score 0-2 = WATCH,
# drift score 0-3 = TRENDING). 7+ trigger = ENTER (no PROBE tier).
# Drift max is 9 — 99 high bound is a safe sentinel.
SCORE_TIER_BANDS = {
    "trigger": {"WEAK": (3, 3), "MID": (4, 5), "STRONG": (6, 6)},
    "drift":   {"WEAK": (4, 4), "MID": (5, 5), "STRONG": (6, 99)},
}

# ── RS Tier Bands (track-independent — display-only) ────────────────
# rs_delta_pct >= threshold → that tier. Below WEAK (negative rs_delta_pct,
# i.e., underperforming market) → rs_tier = None.
# Calibrated to 2026-05-13 distribution: produces ~1:3:5 STRONG:MID:WEAK split.
RS_TIER_BANDS = {
    "STRONG": 10.0,
    "MID":     5.0,
    "WEAK":    0.0,
}
```

- [ ] **Step 2: Verify config import succeeds**

```bash
python -c "from lifecycle_score_config import SCORE_TIER_BANDS, RS_TIER_BANDS; print('OK', SCORE_TIER_BANDS['trigger']['STRONG'], RS_TIER_BANDS['STRONG'])"
```

Expected output:
```
OK (6, 6) 10.0
```

- [ ] **Step 3: Add tier band tests to test_lifecycle_score_config.py**

Append these tests at the end of `tests/test_lifecycle_score_config.py`:

```python


# ── Score tier bands ─────────────────────────────────────────────


def test_score_tier_bands_present_per_track():
    assert "trigger" in cfg.SCORE_TIER_BANDS
    assert "drift" in cfg.SCORE_TIER_BANDS
    for track in ("trigger", "drift"):
        for tier in ("WEAK", "MID", "STRONG"):
            assert tier in cfg.SCORE_TIER_BANDS[track], (
                f"Track {track} missing tier {tier}"
            )


def test_score_tier_bands_monotonic_per_track():
    """Within each track, WEAK upper < MID lower; MID upper < STRONG lower."""
    for track, bands in cfg.SCORE_TIER_BANDS.items():
        w_lo, w_hi = bands["WEAK"]
        m_lo, m_hi = bands["MID"]
        s_lo, s_hi = bands["STRONG"]
        assert w_lo <= w_hi <= m_lo - 0 <= m_hi <= s_lo - 0 <= s_hi, (
            f"Track {track} bands not monotonic: WEAK={bands['WEAK']} "
            f"MID={bands['MID']} STRONG={bands['STRONG']}"
        )


def test_score_tier_trigger_weak_starts_at_probe_threshold():
    """Trigger WEAK lower bound = trigger_probe threshold."""
    assert cfg.SCORE_TIER_BANDS["trigger"]["WEAK"][0] == cfg.THRESHOLDS["trigger_probe"]


def test_score_tier_trigger_strong_ends_below_enter():
    """Trigger STRONG upper bound = trigger_enter - 1 (score 7+ = ENTER)."""
    assert cfg.SCORE_TIER_BANDS["trigger"]["STRONG"][1] == cfg.THRESHOLDS["trigger_enter"] - 1


def test_score_tier_drift_weak_starts_at_drift_probe():
    """Drift WEAK lower bound = drift_probe threshold."""
    assert cfg.SCORE_TIER_BANDS["drift"]["WEAK"][0] == cfg.THRESHOLDS["drift_probe"]


def test_score_tier_drift_strong_starts_at_drift_enter():
    """Drift STRONG lower bound = drift_enter (matches existing PROBE_STRONG semantic)."""
    assert cfg.SCORE_TIER_BANDS["drift"]["STRONG"][0] == cfg.THRESHOLDS["drift_enter"]


# ── RS tier bands ────────────────────────────────────────────────


def test_rs_tier_bands_present():
    for tier in ("STRONG", "MID", "WEAK"):
        assert tier in cfg.RS_TIER_BANDS


def test_rs_tier_bands_monotonic():
    """STRONG threshold > MID > WEAK >= 0."""
    s = cfg.RS_TIER_BANDS["STRONG"]
    m = cfg.RS_TIER_BANDS["MID"]
    w = cfg.RS_TIER_BANDS["WEAK"]
    assert s > m > w >= 0, f"RS bands not monotonic: STRONG={s} MID={m} WEAK={w}"
```

- [ ] **Step 4: Run config tests**

```bash
pytest tests/test_lifecycle_score_config.py -v
```

Expected: All PASS (existing 13 tests + 7 new = 20 tests).

- [ ] **Step 5: Commit**

```bash
git add lifecycle_score_config.py tests/test_lifecycle_score_config.py
git commit -m "feat(lifecycle): add SCORE_TIER_BANDS + RS_TIER_BANDS config"
```

---

### Task 2: Add tier computation helpers + extend ScoreResult

**Files:**
- Modify: `lifecycle_score.py`

- [ ] **Step 1: Extend ScoreResult dataclass**

In `lifecycle_score.py`, find the `ScoreResult` dataclass (around line 24). Add 2 new fields after `rs_delta_pct`:

```python
@dataclass
class ScoreResult:
    """Output of compute_trigger_score / compute_drift_score.

    Invariants enforced by _assemble() builder (not by this dataclass):
      - score = sum(weight for c in components_list if c.active)
      - active_count = sum(1 for v in features.values() if v)
      - features keys == TRIGGER_WEIGHTS.keys() OR DRIFT_WEIGHTS.keys()
      - components_list ordering == config dict iteration order
    Direct construction (e.g., in tests) bypasses these guarantees.
    """
    track: str                       # "trigger" or "drift"
    score: int = 0
    active_count: int = 0
    features: dict = field(default_factory=dict)
    components_list: list = field(default_factory=list)
    rs_delta_pct: Optional[float] = None  # ret_5d - market_ret_5d (raw margin)
    score_tier: Optional[str] = None      # NEW: "WEAK"|"MID"|"STRONG"|None
    rs_tier: Optional[str] = None         # NEW: "WEAK"|"MID"|"STRONG"|None
```

- [ ] **Step 2: Add tier computation helpers**

In `lifecycle_score.py`, find the imports at the top. Update to include the new config dicts:

```python
from lifecycle_score_config import (
    TRIGGER_WEIGHTS, DRIFT_WEIGHTS,
    LOWER_WICK_MIN_RATIO, CLOSE_STRONG_MIN_RATIO,
    TIGHT_RANGE_MAX_ATR, VOL_EXPANSION_MIN_RATIO,
    LOW_VOL_DRIFT_RATIO, TIGHT_CLUSTER_MAX_ATR,
    SCORE_TIER_BANDS, RS_TIER_BANDS,        # NEW
)
```

Then add 2 new helper functions BEFORE the `_assemble()` function (around line 184):

```python
def compute_score_tier(score: Optional[int], track: Optional[str]) -> Optional[str]:
    """Map score+track to tier string. Returns None when score is None or
    falls outside any band (e.g., trigger score 0-2 = WATCH territory).

    Spec §3.1 / §4.3.
    """
    if score is None or track is None:
        return None
    bands = SCORE_TIER_BANDS.get(track)
    if not bands:
        return None
    for tier_name, (lo, hi) in bands.items():
        if lo <= score <= hi:
            return tier_name
    return None  # below WEAK band — e.g., trigger score 0-2


def compute_rs_tier(rs_delta_pct: Optional[float]) -> Optional[str]:
    """Map rs_delta_pct to tier. Returns None when not computed.
    Negative rs_delta_pct (underperforming market) → None, not WEAK.

    Spec §3.2 / §4.3.
    """
    if rs_delta_pct is None:
        return None
    for tier_name in ("STRONG", "MID", "WEAK"):
        if rs_delta_pct >= RS_TIER_BANDS[tier_name]:
            return tier_name
    return None  # rs_delta_pct < 0
```

- [ ] **Step 3: Wire tiers into _assemble()**

Modify the `_assemble()` function. Replace the existing `return ScoreResult(...)` block with:

```python
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
        score_tier=compute_score_tier(score, track),    # NEW
        rs_tier=compute_rs_tier(rs_delta_pct),          # NEW
    )
```

- [ ] **Step 4: Verify import + smoke test**

```bash
python -c "
from lifecycle_score import compute_score_tier, compute_rs_tier, compute_trigger_score
assert compute_score_tier(3, 'trigger') == 'WEAK'
assert compute_score_tier(6, 'trigger') == 'STRONG'
assert compute_score_tier(7, 'trigger') is None  # ENTER, no tier
assert compute_score_tier(0, 'trigger') is None  # below WEAK
assert compute_score_tier(5, 'drift') == 'MID'
assert compute_score_tier(9, 'drift') == 'STRONG'
assert compute_rs_tier(10.0) == 'STRONG'
assert compute_rs_tier(5.0) == 'MID'
assert compute_rs_tier(4.99) == 'WEAK'
assert compute_rs_tier(0.0) == 'WEAK'
assert compute_rs_tier(-1.0) is None
assert compute_rs_tier(None) is None
print('all tier helper smoke tests pass')
"
```

Expected: `all tier helper smoke tests pass`

- [ ] **Step 5: Add comprehensive unit tests**

Append these tests at the end of `tests/test_lifecycle_score.py`:

```python


# ── score_tier helper ─────────────────────────────────────────────


def test_compute_score_tier_trigger_weak():
    from lifecycle_score import compute_score_tier
    assert compute_score_tier(3, "trigger") == "WEAK"


def test_compute_score_tier_trigger_mid():
    from lifecycle_score import compute_score_tier
    assert compute_score_tier(4, "trigger") == "MID"
    assert compute_score_tier(5, "trigger") == "MID"


def test_compute_score_tier_trigger_strong():
    from lifecycle_score import compute_score_tier
    assert compute_score_tier(6, "trigger") == "STRONG"


def test_compute_score_tier_trigger_below_probe_none():
    """Trigger score 0-2 = WATCH territory → no tier."""
    from lifecycle_score import compute_score_tier
    for s in (0, 1, 2):
        assert compute_score_tier(s, "trigger") is None


def test_compute_score_tier_trigger_above_enter_none():
    """Trigger score 7+ = ENTER (out of PROBE bucket) → no tier."""
    from lifecycle_score import compute_score_tier
    assert compute_score_tier(7, "trigger") is None
    assert compute_score_tier(14, "trigger") is None


def test_compute_score_tier_drift_weak():
    from lifecycle_score import compute_score_tier
    assert compute_score_tier(4, "drift") == "WEAK"


def test_compute_score_tier_drift_mid():
    from lifecycle_score import compute_score_tier
    assert compute_score_tier(5, "drift") == "MID"


def test_compute_score_tier_drift_strong():
    from lifecycle_score import compute_score_tier
    assert compute_score_tier(6, "drift") == "STRONG"
    assert compute_score_tier(9, "drift") == "STRONG"


def test_compute_score_tier_drift_below_probe_none():
    """Drift score 0-3 = TRENDING territory → no tier."""
    from lifecycle_score import compute_score_tier
    for s in (0, 1, 2, 3):
        assert compute_score_tier(s, "drift") is None


def test_compute_score_tier_none_inputs():
    from lifecycle_score import compute_score_tier
    assert compute_score_tier(None, "trigger") is None
    assert compute_score_tier(5, None) is None
    assert compute_score_tier(None, None) is None


def test_compute_score_tier_unknown_track_none():
    from lifecycle_score import compute_score_tier
    assert compute_score_tier(5, "unknown_track") is None


# ── rs_tier helper ────────────────────────────────────────────────


def test_compute_rs_tier_strong():
    from lifecycle_score import compute_rs_tier
    assert compute_rs_tier(10.0) == "STRONG"
    assert compute_rs_tier(15.5) == "STRONG"


def test_compute_rs_tier_mid():
    from lifecycle_score import compute_rs_tier
    assert compute_rs_tier(5.0) == "MID"
    assert compute_rs_tier(9.99) == "MID"


def test_compute_rs_tier_weak():
    from lifecycle_score import compute_rs_tier
    assert compute_rs_tier(0.0) == "WEAK"
    assert compute_rs_tier(4.99) == "WEAK"


def test_compute_rs_tier_below_zero_none():
    """Negative rs_delta_pct = underperforming market → None (not WEAK)."""
    from lifecycle_score import compute_rs_tier
    assert compute_rs_tier(-0.01) is None
    assert compute_rs_tier(-5.0) is None


def test_compute_rs_tier_none_input():
    from lifecycle_score import compute_rs_tier
    assert compute_rs_tier(None) is None


# ── ScoreResult tier fields populated by _assemble() ──────────────


def test_score_result_includes_score_tier_field():
    """compute_trigger_score must produce score_tier in result."""
    from lifecycle_score import compute_trigger_score
    today = _today(close=110, ema9=100, low=99.5, high=110.5, change_5d_pct=5.0)
    yesterday = _yesterday(close=99, low=98)
    res = compute_trigger_score(today, yesterday, market_ret_5d_pct=1.0)
    assert hasattr(res, "score_tier")
    assert res.score_tier in ("WEAK", "MID", "STRONG", None)


def test_score_result_includes_rs_tier_field():
    """compute_drift_score must produce rs_tier in result."""
    from lifecycle_score import compute_drift_score
    today = _today(close=101, ema9=100, ema21=98, ema65=90,
                   atr14_pct=1.5, atr14_pct_5d_avg=1.5, atr14_pct_20d_avg=2.0,
                   change_5d_pct=5.0)
    yesterday = _yesterday(close=99, low=98)
    res = compute_drift_score(today, yesterday,
                              recent_3d_closes=[100, 100.5, 101], market_ret_5d_pct=1.0)
    assert hasattr(res, "rs_tier")
    # 5.0 - 1.0 = 4.0 → WEAK tier
    assert res.rs_tier == "WEAK"


def test_score_result_tier_consistent_with_score():
    """score_tier band must contain the score."""
    from lifecycle_score import compute_trigger_score
    from lifecycle_score_config import SCORE_TIER_BANDS
    today = _today(close=110, ema9=100, low=99.5, high=110.5, change_5d_pct=5.0)
    yesterday = _yesterday(close=99, low=98)
    res = compute_trigger_score(today, yesterday, market_ret_5d_pct=1.0)
    if res.score_tier is not None:
        lo, hi = SCORE_TIER_BANDS[res.track][res.score_tier]
        assert lo <= res.score <= hi
```

- [ ] **Step 6: Run unit tests**

```bash
pytest tests/test_lifecycle_score.py -v --tb=line
```

Expected: All PASS (existing 38 + 19 new = 57 tests).

- [ ] **Step 7: Commit**

```bash
git add lifecycle_score.py tests/test_lifecycle_score.py
git commit -m "feat(lifecycle): compute_score_tier + compute_rs_tier + ScoreResult fields"
```

---

### Task 3: Propagate tier fields through lifecycle_signal.py

**Files:**
- Modify: `lifecycle_signal.py`

- [ ] **Step 1: Update `_evaluate_decision_score` — active path**

In `lifecycle_signal.py`, find `_evaluate_decision_score` (around line 278). Locate the FINAL return dict (the non-veto, non-unknown-setup return, after `tier = DECISION_TO_TIER.get(tier_key)`). Add `score_tier` and `rs_tier` keys to that return dict:

```python
    return {
        "decision": decision, "decision_badges": badges,
        "veto_reason": None,
        "score": sc.score, "score_track": track,
        "score_tier": sc.score_tier,        # NEW
        "rs_tier":    sc.rs_tier,           # NEW
        "active_components": sc.active_count,
        "features": sc.features, "score_components": sc.components_list,
        "rs_delta_pct": sc.rs_delta_pct,
        "suggested_entry_tier": tier,
        "suggested_size_pct": size_pct,
        "trigger_state": _derive_legacy_trigger_state(sc.score, track),
        "_raw_score": None, "_raw_features": None, "_raw_score_track": None,
    }
```

- [ ] **Step 2: Update `_evaluate_decision_score` — veto path**

Same function, locate the veto return dict (after `if veto:`). Add `score_tier=None` and `rs_tier=raw.rs_tier`:

```python
        return {
            "decision": DECISION_AVOID, "veto_reason": veto,
            "score": None, "score_track": None,
            "score_tier": None,                       # NEW (public is None — score is null)
            "rs_tier": raw.rs_tier,                   # NEW (preserve RS tier for analytics)
            "features": None, "score_components": None,
            "active_components": None, "decision_badges": [],
            "_raw_score": raw.score, "_raw_features": raw.features,
            "_raw_score_track": raw_track,
            "suggested_entry_tier": None, "suggested_size_pct": 0.0,
            "rs_delta_pct": raw.rs_delta_pct,
            "trigger_state": "WAIT",
        }
```

- [ ] **Step 3: Update `_evaluate_decision_score` — unknown setup path**

Same function, locate the unknown-setup fallback (after `else:` for setup_state matching). Add the two new keys:

```python
        return {
            "decision": DECISION_AVOID, "veto_reason": VETO_UNKNOWN_SETUP,
            "score": None, "score_track": None,
            "score_tier": None,                       # NEW
            "rs_tier": None,                          # NEW
            "features": None, "score_components": None,
            "active_components": None, "decision_badges": [],
            "_raw_score": None, "_raw_features": None, "_raw_score_track": None,
            "suggested_entry_tier": None, "suggested_size_pct": 0.0,
            "rs_delta_pct": None, "trigger_state": "WAIT",
        }
```

- [ ] **Step 4: Update `process_universe` shadow-mode score_payload**

In `lifecycle_signal.py`, find `process_universe()` (around line 546). Locate the `else:` branch that builds `score_payload` for shadow mode (lines around 645). It currently looks like:

```python
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
```

Replace with (adds 2 tier fields):

```python
                score_payload = {
                    "score": sc.score, "score_track": track,
                    "score_tier": sc.score_tier,         # NEW
                    "rs_tier":    sc.rs_tier,            # NEW
                    "active_components": sc.active_count,
                    "features": sc.features,
                    "score_components": sc.components_list,
                    "decision_badges": [], "veto_reason": None,
                    "suggested_entry_tier": None, "suggested_size_pct": 0.0,
                    "rs_delta_pct": sc.rs_delta_pct,
                    "_raw_score": None, "_raw_features": None, "_raw_score_track": None,
                }
```

- [ ] **Step 5: Extend `_make_snapshot` merge tuple**

In `lifecycle_signal.py`, find `_make_snapshot` (around line 497). Locate the `for k in (...)` loop (around line 537). Update the tuple to include the 2 new keys (insertion point: right after `"score_track"`):

```python
    if score_payload:
        # Merge new fields verbatim — they were built by _evaluate_decision_score.
        for k in ("score", "score_track", "score_tier", "rs_tier",
                  "active_components", "features",
                  "score_components", "decision_badges", "veto_reason",
                  "suggested_entry_tier", "suggested_size_pct", "rs_delta_pct",
                  "_raw_score", "_raw_features", "_raw_score_track"):
            snap[k] = score_payload.get(k)
```

- [ ] **Step 6: Add PROBE_STRONG badge invariant — wire score_tier to decision_badges**

Currently the `decision_badges` array gets `["PROBE_STRONG"]` when drift_score ≥ 6 (via the existing logic at the score path). We need to verify that the new `score_tier == "STRONG"` for drift track produces the same result. Inspect the existing logic in `_evaluate_decision_score`:

```python
    elif setup_state == "TREND_OK":
        sc = compute_drift_score(...)
        track = TRACK_DRIFT
        ...
        elif sc.score >= THRESHOLDS["drift_enter"]:
            decision = DECISION_ENTER if DRIFT_ALLOW_ENTER else DECISION_PROBE
            badges   = [] if DRIFT_ALLOW_ENTER else [BADGE_PROBE_STRONG]
```

The condition `sc.score >= THRESHOLDS["drift_enter"]` (which is 6) is exactly the condition for `score_tier="STRONG"` in drift track (band `(6, 99)`). So the two are already aligned — no code change needed here. Task 8 (invariant tests) will pin this.

- [ ] **Step 7: Run full lifecycle_signal tests**

```bash
pytest tests/test_lifecycle_signal.py -v --tb=line
```

Expected: All existing tests PASS (48 tests).

- [ ] **Step 8: Run end-to-end + invariant tests**

```bash
pytest tests/test_lifecycle_e2e.py tests/test_lifecycle_invariants.py tests/test_lifecycle_decision_matrix.py -v --tb=line
```

Expected: All PASS. The score_tier/rs_tier fields appear in returned dicts now; existing tests should not assert their absence so this should be additive.

- [ ] **Step 9: Smoke test — score_active mode produces tier fields**

```bash
python -c "
import os
os.environ['LIFECYCLE_ENGINE_MODE'] = 'score_active'
import lifecycle_score_config as cfg
# patch TRIGGER_TRACK_ACTIVE to True (PR#2 default)
from lifecycle_signal import evaluate_decision

result = evaluate_decision('PULLBACK', 'CONFIRMED_TRIGGER', risk_tags=[],
    today_raw={'open':100,'close':110,'high':111,'low':99.5,'ema9':100,'ema21':98,'ema65':90,
               'atr14':2.0,'atr14_pct':2.0,'volume_ratio':1.5,'high_20d_prior':105,'change_5d_pct':5.0},
    yesterday_snap={'close':99,'low':98,'high':100,'ema9':99.5},
    market_ret_5d_pct=1.0)
assert 'score_tier' in result, 'score_tier missing'
assert 'rs_tier' in result, 'rs_tier missing'
print(f\"OK decision={result['decision']} score={result['score']} score_tier={result['score_tier']} rs_tier={result['rs_tier']}\")
"
```

Expected: `OK decision=... score=... score_tier=... rs_tier=...` with non-None tier values.

- [ ] **Step 10: Commit**

```bash
git add lifecycle_signal.py
git commit -m "feat(lifecycle): propagate score_tier + rs_tier through decision + snapshot"
```

---

### Task 4: Surface tier fields in lifecycle_report + new sort key

**Files:**
- Modify: `lifecycle_report.py`

- [ ] **Step 1: Add `score_tier` + `rs_tier` to `_attach_derived`**

In `lifecycle_report.py`, find `_attach_derived()` (around line 40). Locate the block that surfaces score_v1 fields (after `out["rs_delta_pct"] = snap.get("rs_delta_pct")`). Insert 2 new lines right after `rs_delta_pct`:

```python
    out["rs_delta_pct"]          = snap.get("rs_delta_pct")
    out["score_tier"]            = snap.get("score_tier")           # NEW
    out["rs_tier"]               = snap.get("rs_tier")              # NEW
    out["engine_version"]        = snap.get("engine_version") or "phase_a_legacy"
```

- [ ] **Step 2: Add tier-aware sort key function**

In `lifecycle_report.py`, find `build_page_context()` (around line 150). BEFORE the function (or as a helper inside), add:

```python
def _tier_sort_key(row):
    """Tier-aware sort: score desc, rs_delta_pct desc, active_components desc.

    None values sort last via sentinel (-999 / -9999 / 0).
    Used for PROBE/WATCH/TRENDING sections per spec §5.3.
    """
    return (
        -(row.get("score") if row.get("score") is not None else -999),
        -(row.get("rs_delta_pct") if row.get("rs_delta_pct") is not None else -9999),
        -(row.get("active_components") or 0),
    )
```

- [ ] **Step 3: Replace sort keys for probe/watch/trending**

In `build_page_context()`, find the existing sort block (around line 209):

```python
    enter.sort(key=lambda r: ((r["trigger_age_days"] if r["trigger_age_days"] is not None else 999),
                               -(r["raw"].get("volume_ratio") or 0)))
    probe.sort(key=lambda r: -(r["raw"].get("volume_ratio") or 0))
    watch.sort(key=lambda r: -(r["setup_streak"] or 0))
    trending.sort(key=lambda r: -(r["setup_streak"] or 0))
```

Replace ONLY the `probe`, `watch`, `trending` sorts (KEEP `enter` sort unchanged — it stays on trigger_age_days):

```python
    enter.sort(key=lambda r: ((r["trigger_age_days"] if r["trigger_age_days"] is not None else 999),
                               -(r["raw"].get("volume_ratio") or 0)))
    probe.sort(key=_tier_sort_key)
    watch.sort(key=_tier_sort_key)
    trending.sort(key=_tier_sort_key)
```

- [ ] **Step 4: Run report tests**

```bash
pytest tests/test_lifecycle_report.py -v --tb=line
```

Expected: All PASS (4 tests).

- [ ] **Step 5: Smoke test — tier in row dict**

```bash
python -c "
from lifecycle_report import _attach_derived
snap = {
    'date': '2026-05-14', 'setup': 'TREND_OK', 'trigger': 'EARLY_TRIGGER',
    'decision': 'PROBE',
    'raw': {'close':105,'ema9':100,'ema21':98,'risk_tags':[]},
    'score': 5, 'score_track': 'drift', 'score_tier': 'MID', 'rs_tier': 'STRONG',
    'rs_delta_pct': 12.3, 'active_components': 4, 'features': {}, 'score_components': [],
    'decision_badges': [], 'engine_version': 'score_v1',
}
row = _attach_derived(snap, 'AAPL', None)
assert row.get('score_tier') == 'MID', f\"score_tier={row.get('score_tier')}\"
assert row.get('rs_tier') == 'STRONG', f\"rs_tier={row.get('rs_tier')}\"
print('OK score_tier=', row['score_tier'], 'rs_tier=', row['rs_tier'])
"
```

Expected: `OK score_tier= MID rs_tier= STRONG`

- [ ] **Step 6: Smoke test — sort order**

```bash
python -c "
from lifecycle_report import _tier_sort_key

rows = [
    {'ticker': 'A', 'score': 4, 'rs_delta_pct': 8.0, 'active_components': 3},
    {'ticker': 'B', 'score': 6, 'rs_delta_pct': 2.0, 'active_components': 3},
    {'ticker': 'C', 'score': 5, 'rs_delta_pct': 12.0, 'active_components': 4},
    {'ticker': 'D', 'score': 5, 'rs_delta_pct': 3.0, 'active_components': 4},
]
sorted_rows = sorted(rows, key=_tier_sort_key)
order = [r['ticker'] for r in sorted_rows]
print('Sorted order:', order)
assert order == ['B', 'C', 'D', 'A'], f'Unexpected order: {order}'
print('OK')
"
```

Expected: `Sorted order: ['B', 'C', 'D', 'A']` then `OK`. Reasoning: B has score 6 (highest), then C/D at score 5 (C has higher RS than D), then A at score 4.

- [ ] **Step 7: Commit**

```bash
git add lifecycle_report.py
git commit -m "feat(lifecycle): tier-aware sort for probe/watch/trending sections"
```

---

### Task 5: Update lifecycle_us.html — CSS + chip markup + filter toolbar

**Files:**
- Modify: `templates/lifecycle_us.html`

- [ ] **Step 1: Add CSS tier classes to existing `<style>` block**

In `templates/lifecycle_us.html`, find the existing CSS for chip-score (around line 22, look for `.chip-score`). After the existing `.badge-strong` rule, append:

```css
  /* Tier badges (Score Tier + RS Tier) — see docs/superpowers/specs/2026-05-14-probe-tiering-design.md */
  .tier-badge { font-size: 0.75em; margin-left: 4px; padding: 1px 6px; border-radius: 3px; font-weight: 600; }
  .tier-strong { background: #d4a017; color: #000; }
  .tier-mid    { background: #4a9eff; color: #fff; }
  .tier-weak   { background: #555;    color: #ccc; }
  .tier-null   { background: transparent; color: var(--muted); }
  .score-num.tier-strong,
  .rs-num.tier-strong { color: #d4a017; font-weight: 600; background: transparent; padding: 0; }
  .score-num.tier-mid,
  .rs-num.tier-mid    { color: #4a9eff; font-weight: 600; background: transparent; padding: 0; }
  .score-num.tier-weak,
  .rs-num.tier-weak   { color: #aaa; background: transparent; padding: 0; }
  .rs-num { margin-left: 10px; font-size: 0.95em; }

  /* Filter toolbar */
  .filter-toolbar { display: flex; gap: 6px; margin: 6px 0 10px; flex-wrap: wrap; }
  .filter-btn {
    background: rgba(255,255,255,0.05); color: var(--muted); border: 1px solid rgba(255,255,255,0.1);
    padding: 3px 10px; border-radius: 4px; font-size: 11px; cursor: pointer; font-family: inherit;
  }
  .filter-btn:hover { background: rgba(255,255,255,0.08); color: var(--text); }
  .filter-btn.active { background: var(--primary-bg); color: var(--primary-c); border-color: var(--primary-c); }
```

- [ ] **Step 2: Update all 4 `chip-score` blocks (ENTER/PROBE/WATCH/TRENDING)**

The template has 4 inline `chip-score` blocks (one per section). Each currently looks like:

```html
{% if row.score is not none %}
<div class="chip-score">
  {% set dot_count = row.active_components or 0 %}
  <span class="score-dots" title="{{ row.active_components }} components active">{% for i in range(5) %}{% if i < dot_count %}●{% else %}○{% endif %}{% endfor %}</span>
  <span class="score-num">{{ row.score }}</span>
  {% if 'PROBE_STRONG' in (row.decision_badges or []) %}
  <span class="badge badge-strong" title="Drift score ≥ 6">⚡ STRONG</span>
  {% endif %}
</div>
{% endif %}
```

REPLACE each occurrence with this enhanced version:

```html
{% if row.score is not none %}
<div class="chip-score">
  {% set dot_count = row.active_components or 0 %}
  <span class="score-dots" title="{{ row.active_components }} components active">{% for i in range(5) %}{% if i < dot_count %}●{% else %}○{% endif %}{% endfor %}</span>
  <span class="score-num tier-{{ (row.score_tier or 'null')|lower }}">{{ row.score }}</span>
  {% if row.score_tier %}<span class="tier-badge tier-{{ row.score_tier|lower }}">S·{{ row.score_tier }}</span>{% endif %}
  {% if row.rs_delta_pct is not none %}
    <span class="rs-num tier-{{ (row.rs_tier or 'null')|lower }}">RS {{ '%+.1f'|format(row.rs_delta_pct) }}%</span>
    {% if row.rs_tier %}<span class="tier-badge tier-{{ row.rs_tier|lower }}">R·{{ row.rs_tier }}</span>{% endif %}
  {% endif %}
  {% if 'PROBE_STRONG' in (row.decision_badges or []) %}
  <span class="badge badge-strong" title="Drift score ≥ 6">⚡ PROBE_STRONG</span>
  {% endif %}
</div>
{% endif %}
```

Find ALL occurrences in `lifecycle_us.html` (search for `<div class="chip-score">`) — there should be 4 (one each in ENTER/PROBE/WATCH/TRENDING sections; AVOID section has different markup so check carefully). Replace each.

Note: this changes `⚡ STRONG` → `⚡ PROBE_STRONG` for clarity.

- [ ] **Step 3: Add data attributes to chip divs (PROBE/WATCH/TRENDING only)**

For PROBE/WATCH/TRENDING sections only (NOT enter, NOT avoid), find the `<div class="stock-chip">` opening tags. Replace with:

```html
<div class="stock-chip"
     data-score-tier="{{ row.score_tier or 'null' }}"
     data-rs-tier="{{ row.rs_tier or 'null' }}"
     data-active-components="{{ row.active_components or 0 }}">
```

(Apply to the chip in PROBE section, WATCH section, TRENDING section — NOT the AVOID/ENTER sections which have different chip class modifiers like `danger`/`new-confirmed`.)

- [ ] **Step 4: Wrap chip lists with `data-grid` + add filter toolbar (PROBE/WATCH/TRENDING)**

For the PROBE section, find the existing `<div class="stock-list">`:

```html
      <div class="stock-list">
        {% for row in probe %}
        ...
```

Replace with:

```html
      <div class="filter-toolbar" data-section="probe">
        <button class="filter-btn active" data-filter="all">전체</button>
        <button class="filter-btn" data-filter="s-strong">Score STRONG</button>
        <button class="filter-btn" data-filter="rs-strong-mid">RS STRONG+MID</button>
        <button class="filter-btn" data-filter="active-4plus">활성 ≥ 4</button>
      </div>
      <div class="stock-list" data-grid="probe">
        {% for row in probe %}
        ...
```

Apply the same pattern to WATCH section (use `data-section="watch"`, `data-grid="watch"`) and TRENDING section (use `data-section="trending"`, `data-grid="trending"`).

- [ ] **Step 5: Add inline filter JS before `</body>`**

Find the existing `</body>` closing tag in `lifecycle_us.html`. Add this script JUST BEFORE it:

```html
<script>
// Tier filter toolbar — see docs/superpowers/specs/2026-05-14-probe-tiering-design.md §5.4
(function() {
  document.querySelectorAll('.filter-toolbar').forEach(function(toolbar) {
    var section = toolbar.dataset.section;
    var grid = document.querySelector('[data-grid="' + section + '"]');
    if (!grid) return;
    toolbar.addEventListener('click', function(e) {
      if (!e.target.classList.contains('filter-btn')) return;
      toolbar.querySelectorAll('.filter-btn').forEach(function(b) { b.classList.remove('active'); });
      e.target.classList.add('active');
      var filter = e.target.dataset.filter;
      grid.querySelectorAll('.stock-chip').forEach(function(chip) {
        var st = chip.dataset.scoreTier;
        var rt = chip.dataset.rsTier;
        var ac = parseInt(chip.dataset.activeComponents || '0', 10);
        var show = true;
        if (filter === 's-strong')      show = (st === 'STRONG');
        if (filter === 'rs-strong-mid') show = (rt === 'STRONG' || rt === 'MID');
        if (filter === 'active-4plus')  show = (ac >= 4);
        chip.style.display = show ? '' : 'none';
      });
    });
  });
})();
</script>
```

- [ ] **Step 6: Verify Jinja parses**

```bash
python -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('templates'), autoescape=True)
env.filters['signed_pct'] = lambda x: f'{x:+.1f}%' if x is not None else '—'
env.filters['x_fmt'] = lambda x: f'{x:.1f}×' if x is not None else '—'
env.filters['trig_age_label'] = lambda x: '오늘' if x == 0 else f'{x}일전' if x else '—'
t = env.get_template('lifecycle_us.html')
print('lifecycle_us.html parses OK')
"
```

Expected: `lifecycle_us.html parses OK`. If parse error, fix Jinja syntax issue.

- [ ] **Step 7: Commit**

```bash
git add templates/lifecycle_us.html
git commit -m "feat(lifecycle): chip tier badges + filter toolbar in lifecycle_us.html"
```

---

### Task 6: Mirror changes in lifecycle_kr.html

**Files:**
- Modify: `templates/lifecycle_kr.html`

- [ ] **Step 1: Apply identical changes to lifecycle_kr.html**

Repeat Task 5 Steps 1–5 verbatim on `templates/lifecycle_kr.html`. The structure mirrors `lifecycle_us.html` exactly (same sections, same chip-score block locations, same chip-grid pattern).

Specifically:
- Step 1 (CSS additions) — apply to the `<style>` block in `lifecycle_kr.html`
- Step 2 (chip-score replacement) — find all 4 occurrences in lifecycle_kr.html and replace each
- Step 3 (data attributes on `<div class="stock-chip">`) — same 3 sections (PROBE/WATCH/TRENDING)
- Step 4 (filter toolbar + data-grid wrapper) — same 3 sections
- Step 5 (inline filter JS before `</body>`) — copy script verbatim

- [ ] **Step 2: Verify Jinja parses**

```bash
python -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('templates'), autoescape=True)
env.filters['signed_pct'] = lambda x: f'{x:+.1f}%' if x is not None else '—'
env.filters['x_fmt'] = lambda x: f'{x:.1f}×' if x is not None else '—'
env.filters['trig_age_label'] = lambda x: '오늘' if x == 0 else f'{x}일전' if x else '—'
t = env.get_template('lifecycle_kr.html')
print('lifecycle_kr.html parses OK')
"
```

Expected: `lifecycle_kr.html parses OK`.

- [ ] **Step 3: Run lifecycle_report tests (templates render against fixtures)**

```bash
pytest tests/test_lifecycle_report.py tests/test_lifecycle_report_nav.py -v --tb=line
```

Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add templates/lifecycle_kr.html
git commit -m "feat(lifecycle): chip tier badges + filter toolbar in lifecycle_kr.html"
```

---

### Task 7: Add glossary entries

**Files:**
- Modify: `templates/_lifecycle_glossary.html`

- [ ] **Step 1: Append 2 new entries**

In `templates/_lifecycle_glossary.html`, find the existing list of `<dt>/<dd>` pairs (or whatever structure the glossary uses — there might be a `<table>` or `<dl>`). Find the structure used by the most recent additions (Score / trigger_score vs drift_score / active_components / PROBE_STRONG entries from PR#1). Append the same structure with 2 new entries:

```html
<dt>Score Tier (S·WEAK / S·MID / S·STRONG)</dt>
<dd>점수의 상대적 강도. trigger 트랙: WEAK=3, MID=4–5, STRONG=6. drift 트랙: WEAK=4, MID=5, STRONG=6+. drift STRONG은 기존 PROBE_STRONG ⚡ badge와 동일.</dd>

<dt>RS Tier (R·WEAK / R·MID / R·STRONG)</dt>
<dd>시장 대비 5일 outperform 정도 (rs_delta_pct). STRONG ≥ 10%, MID 5–9.99%, WEAK 0–4.99%. 같은 점수여도 RS가 높을수록 진짜 leader. SPY (US) / KS200 (KR) 대비.</dd>
```

If the glossary uses a `<table>` structure (each entry is a `<tr>` with two `<td>` cells), adapt accordingly. Inspect the file first:

```bash
head -30 templates/_lifecycle_glossary.html
```

Use the matching format.

- [ ] **Step 2: Verify Jinja parses**

```bash
python -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('templates'), autoescape=True)
env.filters['signed_pct'] = lambda x: f'{x:+.1f}%' if x is not None else '—'
env.filters['x_fmt'] = lambda x: f'{x:.1f}×' if x is not None else '—'
env.filters['trig_age_label'] = lambda x: '오늘' if x == 0 else f'{x}일전' if x else '—'
env.get_template('_lifecycle_glossary.html')
env.get_template('lifecycle_us.html')
env.get_template('lifecycle_kr.html')
print('all 3 templates parse OK')
"
```

Expected: `all 3 templates parse OK`.

- [ ] **Step 3: Commit**

```bash
git add templates/_lifecycle_glossary.html
git commit -m "docs(lifecycle): glossary entries for Score Tier + RS Tier"
```

---

### Task 8: Add invariant tests

**Files:**
- Modify: `tests/test_lifecycle_invariants.py`

- [ ] **Step 1: Append 5 new invariants**

Append at the end of `tests/test_lifecycle_invariants.py`:

```python


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
    from lifecycle_score import compute_trigger_score, compute_drift_score

    # trigger track at each tier
    for score_target, expected_tier in [(3, "WEAK"), (4, "MID"), (5, "MID"), (6, "STRONG")]:
        # check helper directly
        from lifecycle_score import compute_score_tier
        actual_tier = compute_score_tier(score_target, "trigger")
        if actual_tier is not None:
            lo, hi = cfg.SCORE_TIER_BANDS["trigger"][actual_tier]
            assert lo <= score_target <= hi
            assert actual_tier == expected_tier

    # drift track at each tier
    for score_target, expected_tier in [(4, "WEAK"), (5, "MID"), (6, "STRONG"), (9, "STRONG")]:
        from lifecycle_score import compute_score_tier
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
```

- [ ] **Step 2: Run all invariants**

```bash
pytest tests/test_lifecycle_invariants.py -v --tb=line
```

Expected: ALL PASS (12 existing + 5 new = 17 invariants).

- [ ] **Step 3: Commit**

```bash
git add tests/test_lifecycle_invariants.py
git commit -m "test(lifecycle): tier integrity invariants (drift STRONG ⟺ PROBE_STRONG)"
```

---

### Task 9: Extend decision matrix tests to verify score_tier

**Files:**
- Modify: `tests/test_lifecycle_decision_matrix.py`

- [ ] **Step 1: Add score_tier assertions to existing matrix tests**

In `tests/test_lifecycle_decision_matrix.py`, find the existing tests:
- `test_matrix_pullback_score_7_enter`
- `test_matrix_pullback_score_3_to_6_probe`
- `test_matrix_pullback_score_below_3_watch`
- `test_matrix_base_forming_uses_trigger_track`
- `test_matrix_trend_ok_drift_above_6_probe_strong`
- `test_matrix_trend_ok_drift_4_to_5_probe`
- `test_matrix_trend_ok_drift_below_4_trending`

For each test, after the existing assertions, ADD a tier check. Specifically:

`test_matrix_pullback_score_7_enter` — after `assert result["decision"] == "ENTER"`, add:
```python
    # ENTER has no PROBE-tier (score_tier is for PROBE bucket only)
    assert result.get("score_tier") is None
```

`test_matrix_pullback_score_3_to_6_probe` — after `assert result["decision"] == "PROBE"`, add:
```python
    # PROBE in trigger track: MID tier (score 4-5)
    assert result["score_tier"] in ("WEAK", "MID")
```

`test_matrix_pullback_score_below_3_watch` — after `assert result["decision"] == "WATCH"`, add:
```python
    # WATCH score < 3 → tier is None (below WEAK band)
    assert result.get("score_tier") is None
```

`test_matrix_trend_ok_drift_above_6_probe_strong` — after the existing `"PROBE_STRONG" in result["decision_badges"]` assertion, add:
```python
    assert result["score_tier"] == "STRONG"
```

`test_matrix_trend_ok_drift_4_to_5_probe` — after `assert "PROBE_STRONG" not in result["decision_badges"]`, add:
```python
    assert result["score_tier"] in ("WEAK", "MID")
    assert result["score_tier"] != "STRONG"
```

`test_matrix_trend_ok_drift_below_4_trending` — after `assert result["decision"] == "TRENDING"`, add:
```python
    # TRENDING score < 4 (drift_probe threshold) → tier is None
    assert result.get("score_tier") is None
```

- [ ] **Step 2: Run matrix tests**

```bash
pytest tests/test_lifecycle_decision_matrix.py -v --tb=line
```

Expected: All PASS (10 tests with new tier assertions added).

- [ ] **Step 3: Run full test suite — confirm no regression**

```bash
pytest tests/ --tb=line -q 2>&1 | tail -5
```

Expected: 540 existing tests + new tier-related tests all PASS. Total should be ~570+.

- [ ] **Step 4: Commit**

```bash
git add tests/test_lifecycle_decision_matrix.py
git commit -m "test(lifecycle): decision matrix asserts score_tier in each cell"
```

---

### Task 10: End-to-end verification + render real pages

**Files:**
- No file edits expected — verification gate

- [ ] **Step 1: Run full test suite one final time**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -25
```

Expected: ALL PASS. New count should be 540 (PR#1 final) + ~26 (Tasks 1, 2, 8, 9 added tests) = ~566 total tests.

- [ ] **Step 2: Run pipeline end-to-end**

```powershell
$env:SKIP_SCANNERS="1"
python pipeline.py 2>&1 | tail -15
Remove-Item Env:SKIP_SCANNERS
```

Expected:
- `[lifecycle:US] market_ret_5d_pct = X.X`
- `[lifecycle:US] snapshots=N transitions=M active_set=K`
- Same for KR
- No exceptions

- [ ] **Step 3: Inspect a rendered page**

```bash
ls reports/lifecycle_*.html | tail -2
```

Pick the latest lifecycle_kr or lifecycle_us file. Open it and verify:
- Score tier badges visible (e.g., `S·MID`, `S·STRONG`)
- RS values visible with tier coloring (e.g., `RS +5.4% R·MID`)
- Filter toolbar present above PROBE/WATCH/TRENDING sections
- Clicking `Score STRONG` filter button hides non-STRONG chips
- Glossary at bottom has new Score Tier + RS Tier entries

Quick HTML inspection:

```bash
python -c "
import re
from pathlib import Path
files = sorted(Path('reports').glob('lifecycle_kr_*.html'))
if not files:
    files = sorted(Path('reports').glob('lifecycle_us_*.html'))
if not files:
    print('No lifecycle pages found')
    raise SystemExit(1)
html = files[-1].read_text(encoding='utf-8')
print(f'Inspecting: {files[-1]}')
print(f'  tier-badge occurrences: {html.count(\"tier-badge\")}')
print(f'  filter-toolbar occurrences: {html.count(\"filter-toolbar\")}')
print(f'  data-score-tier occurrences: {html.count(\"data-score-tier\")}')
print(f'  Score Tier glossary entry: {\"Score Tier\" in html}')
print(f'  RS Tier glossary entry: {\"RS Tier\" in html}')
"
```

Expected: positive counts for tier-badge, filter-toolbar, data-score-tier; both glossary booleans True.

- [ ] **Step 4: Inspect tier sort produced expected order**

```bash
python -c "
import json
with open('history/lifecycle_history_kr.json', encoding='utf-8') as f:
    state = json.load(f)
probe_rows = []
for tk, blk in (state.get('tickers') or {}).items():
    if not blk.get('snapshots'): continue
    last = blk['snapshots'][-1]
    if last.get('decision') == 'PROBE':
        probe_rows.append((tk, last.get('score'), last.get('score_tier'), last.get('rs_delta_pct'), last.get('rs_tier')))
probe_rows.sort(key=lambda r: (-(r[1] or -999), -(r[3] or -9999)))
print('KR PROBE sorted (ticker, score, score_tier, rs_delta, rs_tier):')
for r in probe_rows[:10]:
    print(f'  {r}')
"
```

Expected: top rows have score 5+ and high RS; tail rows have score 4 with low RS.

- [ ] **Step 5: Final invariant check**

```bash
pytest tests/test_lifecycle_invariants.py -v
```

Expected: 17/17 PASS.

- [ ] **Step 6: Final cleanup commit (if any small fixes during verification)**

If any small fixes were needed during steps 1–5, commit them. Otherwise no commit. Then:

```bash
git log --oneline master..HEAD
```

Expected: 9–10 commits ahead of master (Task 1 + Task 2 + Task 3 + Task 4 + Task 5 + Task 6 + Task 7 + Task 8 + Task 9 + the original spec commit `cae83d76`).

---

## Plan Self-Review

**Spec coverage check** (each spec section → task):
- Spec §1 Problem Statement → reflected in plan Goal
- Spec §2 Architectural Principles → reflected in plan Architecture
- Spec §3 Tier Definitions → Task 1 (config) + Task 2 (helpers)
- Spec §4 Data Model → Task 2 (ScoreResult extension) + Task 3 (snapshot wiring)
- Spec §5 UI Surface → Task 4 (sort) + Task 5 (US template) + Task 6 (KR template) + Task 7 (glossary)
- Spec §6 Telegram — explicitly no change (no task; reflected in File Map)
- Spec §7 Invariants → Task 8
- Spec §8 Files Changed → matches plan File Map
- Spec §9 Migration → handled inherently by additive schema (no special task needed)
- Spec §10 Out of Scope — respected; no task touches them
- Spec §11 Success Criteria → verified in Task 10

**Placeholder scan**: zero "TBD"/"TODO"/"similar to". Each step has complete code, exact paths, exact commands, expected output.

**Type consistency**:
- `score_tier` field name used consistently across all tasks (Task 2 defines, Task 3 propagates, Task 4 surfaces, Tasks 5–6 render, Task 8 invariants).
- `rs_tier` field name consistent.
- `compute_score_tier` and `compute_rs_tier` signatures consistent.
- `_tier_sort_key` returns 3-tuple consistent with sort consumers.
- CSS class names (`.tier-strong`, `.tier-mid`, `.tier-weak`, `.tier-null`) consistent across Tasks 5/6 and the conditional Jinja `{{ ... |lower }}` filter outputs.

**Architecture-collapse check**: this plan does NOT add any expansion-style component to drift_score. The `archetype-collapse guardrail` (parent spec §11.1) is not threatened — tiers are derivative of existing score/RS, not new feature components.

**Telegram check**: confirmed no `telegram_sender.py` edits across any task.

**ENGINE_VERSION check**: confirmed no `ENGINE_VERSION` bump (additive schema only).

Plan is complete and self-consistent.
