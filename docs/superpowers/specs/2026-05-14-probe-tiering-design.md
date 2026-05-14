# PROBE Tiering (Score Tier + RS Tier) — Design Spec

- **Date**: 2026-05-14
- **Status**: Design (approved through brainstorm, ready for implementation plan)
- **Scope**: Add **display-only** sub-tier badges to PROBE/WATCH/TRENDING rows so operators can rank within tiers. Two independent axes: **Score Tier** (WEAK/MID/STRONG, track-dependent) + **RS Tier** (WEAK/MID/STRONG, based on `rs_delta_pct`). **No decision logic changes.**
- **Out of scope**: decision thresholds, weight tuning, Telegram brief changes, sector diversity, streak/age scoring.
- **Engine version**: `score_v1` (unchanged — additive schema only).
- **Related**:
  - Builds on [Trade Lifecycle Probabilistic Engine](2026-05-13-lifecycle-probabilistic-engine-design.md) shipped 2026-05-13.
  - Addresses calibration-phase observation: 2026-05-13 deployed run produced 43 US PROBEs + 7 KR PROBEs with most clustered at drift score 4–5 — too uniform for at-a-glance selection.

---

## 1. Problem Statement

After shipping the score engine v1, the first day of real data showed:

- **US**: 43 PROBE / 53 WATCH / 7 AVOID / 5 TRENDING / 0 ENTER (108 tickers tracked)
- **KR**: 7 PROBE / 11 WATCH / 9 AVOID / 9 TRENDING / 0 ENTER (36 tickers tracked)

PROBE counts hit the spec's success criterion ("≥ 3× Phase A baseline") — that part works. But operators reported: *"PROBE 종목이 너무 많이 나와서 선별이 어렵다."*

**Diagnosis** (from raw data):

- 22 of 43 US PROBEs are at drift score 5 with identical 4-feature combo (`ema_alignment + close_above_ema9 + rs_strong + tight_close_cluster`). The label `PROBE` is the same for all of them.
- Yet `rs_delta_pct` (raw ticker 5d return − market 5d return) varies dramatically: +0.5% to +16.2%. COLD (+16.2%) and ILMN (+0.5%) are not the same opportunity.
- The differentiating signal exists in the snapshot fields (`score`, `rs_delta_pct`, `active_components`), but the page renders them flat — sorted by `volume_ratio`, no tier visualization.

**Root cause**: PROBE is now a **rank-bucket**, not a binary state. Operators need within-bucket ordering, but the UI presents the bucket as uniform.

**Goal**: Add tier visualization + tier-aware sorting + filter UI to PROBE/WATCH/TRENDING sections so operators can scan strong → weak in seconds. Decision logic stays untouched.

---

## 2. Architectural Principles

This is a calibration-phase addition — small, additive, display-focused.

### Principle 1 — Decision logic is not changed
The score engine, hard veto, sizing, and history schema all stay intact. The same PROBE that fires today still fires tomorrow. Tiers describe; they do not gate.

### Principle 2 — Raw numbers preserved alongside tiers
Per the user memory rule (*"raw 수치 우선, 스코어/별점은 명시적 오버라이드 절차 필요"*), tier badges sit **alongside** raw `score`, `rs_delta_pct`, and `active_components` — never replacing them. Tier is a visual aid, not a new metric.

### Principle 3 — Multi-axis over composite scores
Score and RS are different dimensions of strength. Combining them into a single quality score loses information (a "score 5 + RS +0.5%" ticker is fundamentally different from a "score 5 + RS +16%" ticker, even if their composite is similar). Two axes shown independently keeps both signals visible.

### Principle 4 — Calibration-phase appropriate
We are in the observation phase, not the optimization phase. Tier bands are derived from the first day's actual distribution, not from theoretical expectancy. They are config-externalized and easy to tune as more data accumulates.

---

## 3. Tier Definitions

### 3.1 Score Tier (track-dependent)

`trigger_score` and `drift_score` have different ranges (max 14 vs max 9), so tier bands differ.

| Track | WEAK | MID | STRONG |
|---|---|---|---|
| **trigger** (max 14, ENTER=7+) | score == 3 | score 4–5 | score == 6 |
| **drift** (max 9, ENTER disabled) | score == 4 | score == 5 | score ≥ 6 |

Notes:
- **trigger STRONG = 6** = "ENTER 직전" (score 7+ exits PROBE bucket entirely)
- **drift STRONG ≥ 6** = exactly matches the existing `PROBE_STRONG` badge condition → backward compatibility preserved
- Score below the WEAK band (e.g., trigger score 0–2 = WATCH, drift score 0–3 = TRENDING) → `score_tier = null`
- AVOID rows have `score = null` → `score_tier = null`

### 3.2 RS Tier (track-independent)

Based on `rs_delta_pct` (ticker 5-day return − market 5-day return; market = SPY for US, KS200 for KR).

| Tier | rs_delta_pct |
|---|---|
| **STRONG** | ≥ 10% |
| **MID** | 5.0 – 9.99% |
| **WEAK** | 0 – 4.99% |
| `null` | `rs_delta_pct` not computed (market benchmark fetch failed) |

Rationale for thresholds (anchored to 2026-05-13 distribution):
- STRONG 10%: top tier (~3 of 43 US PROBEs)
- MID 5–10%: ~15 of 43 US PROBEs (most leaders fall here)
- WEAK 0–5%: ~25 of 43 US PROBEs (marginally outperforming, less convincing)

→ produces a roughly 1:3:5 STRONG:MID:WEAK split on observed data, which makes filtering meaningful.

### 3.3 Config externalization

Added to `lifecycle_score_config.py`:

```python
# Score tier bands per track. Tunable in calibration phase.
# Format: {tier_name: (low_inclusive, high_inclusive)}.
# Scores outside any band → score_tier = None (e.g., WATCH with score < probe_threshold).
SCORE_TIER_BANDS = {
    "trigger": {"WEAK": (3, 3), "MID": (4, 5), "STRONG": (6, 6)},  # 7+ = ENTER
    "drift":   {"WEAK": (4, 4), "MID": (5, 5), "STRONG": (6, 99)}, # ENTER disabled, 9 is realistic max
}

# RS tier thresholds — track-independent. rs_delta_pct >= threshold → that tier.
# Below WEAK threshold (i.e., rs_delta_pct < 0) → None (underperforming market).
RS_TIER_BANDS = {
    "STRONG": 10.0,
    "MID":     5.0,
    "WEAK":    0.0,
}
```

### 3.4 Existing `PROBE_STRONG` badge preserved

The `decision_badges = ["PROBE_STRONG"]` array (added for drift score ≥ 6 in PR#3) is **not** removed. Both representations co-exist:
- New: `score_tier == "STRONG"` + `score_track == "drift"` — generic field
- Existing: `"PROBE_STRONG" in decision_badges` — legacy badge

Implementation derives `PROBE_STRONG` from `score_tier == "STRONG" AND track == "drift"`, so the two never disagree. Backward consumers (history readers, future analytics scripts referencing `decision_badges`) continue to function.

---

## 4. Data Model

### 4.1 New snapshot fields

```json
{
  "decision": "PROBE",
  "score": 5,
  "score_track": "drift",
  "score_tier": "MID",        // NEW: WEAK / MID / STRONG / null
  "rs_delta_pct": 9.3,
  "rs_tier": "MID",           // NEW: WEAK / MID / STRONG / null
  "active_components": 4,
  "features": { ... },
  "score_components": [ ... ],
  "decision_badges": [],       // PROBE_STRONG when drift score >= 6
  "engine_version": "score_v1",
  ...
}
```

Both new fields are **append-only**. Legacy history JSON files load with `score_tier = null` and `rs_tier = null` for old snapshots — UI renders them gracefully (no badge).

### 4.2 `ScoreResult` dataclass extension

In `lifecycle_score.py`:

```python
@dataclass
class ScoreResult:
    track: str
    score: int = 0
    active_count: int = 0
    features: dict = field(default_factory=dict)
    components_list: list = field(default_factory=list)
    rs_delta_pct: Optional[float] = None
    score_tier: Optional[str] = None    # NEW
    rs_tier: Optional[str] = None        # NEW
```

### 4.3 Tier computation helpers

```python
def compute_score_tier(score: Optional[int], track: Optional[str]) -> Optional[str]:
    """Map score+track to tier string. Returns None when score is None or
    falls outside any band (e.g., trigger score 0-2 = WATCH territory).
    """
    if score is None or track is None:
        return None
    bands = SCORE_TIER_BANDS.get(track)
    if not bands:
        return None
    for tier_name, (lo, hi) in bands.items():
        if lo <= score <= hi:
            return tier_name
    return None  # below WEAK band


def compute_rs_tier(rs_delta_pct: Optional[float]) -> Optional[str]:
    """Map rs_delta_pct to tier. Returns None when not computed.
    Negative rs_delta_pct (underperforming market) → None, not WEAK.
    """
    if rs_delta_pct is None:
        return None
    # Iterate in descending threshold order to find first match
    for tier_name in ("STRONG", "MID", "WEAK"):
        if rs_delta_pct >= RS_TIER_BANDS[tier_name]:
            return tier_name
    return None
```

### 4.4 Wiring into `_assemble()`

In `lifecycle_score.py:_assemble()`, after `rs_delta_pct` is computed:

```python
return ScoreResult(
    track=track, score=score, active_count=active_count,
    features=dict(features), components_list=components_list,
    rs_delta_pct=rs_delta_pct,
    score_tier=compute_score_tier(score, track),   # NEW
    rs_tier=compute_rs_tier(rs_delta_pct),         # NEW
)
```

### 4.5 Snapshot merge

In `lifecycle_signal.py:_make_snapshot()`, extend the score_payload merge list:

```python
for k in ("score", "score_track", "score_tier", "rs_tier",   # +score_tier, +rs_tier
          "active_components", "features", "score_components",
          "decision_badges", "veto_reason",
          "suggested_entry_tier", "suggested_size_pct", "rs_delta_pct",
          "_raw_score", "_raw_features", "_raw_score_track"):
    snap[k] = score_payload.get(k)
```

And in `_evaluate_decision_score()`, both the veto path and the active-path returns include the two new keys (mirror of how `rs_delta_pct` propagates today). Shadow path in `process_universe()` also populates them from `compute_*_score()` output.

---

## 5. UI Surface

### 5.1 Chip rendering

Current chip (e.g., 017670.KS SK텔레콤 PROBE, drift score 5, RS +2.5%):
```
017670.KS SK텔레콤
9일선 +6.8% · vol 1.2×
EARLY · 9일 압축
●●●●○ 5
```

New chip:
```
017670.KS SK텔레콤
9일선 +6.8% · vol 1.2×
EARLY · 9일 압축
●●●●○ 5  S·MID    RS +2.5%  R·WEAK
```

Markup (Jinja):
```html
{% if r.score is not none %}
<div class="chip-score">
  <span class="score-dots" title="{{ r.active_components }} components active">
    {% for i in range(5) %}{% if i < (r.active_components or 0) %}●{% else %}○{% endif %}{% endfor %}
  </span>
  <span class="score-num tier-{{ (r.score_tier or 'null')|lower }}">{{ r.score }}</span>
  {% if r.score_tier %}
    <span class="tier-badge tier-{{ r.score_tier|lower }}">S·{{ r.score_tier }}</span>
  {% endif %}
  {% if r.rs_delta_pct is not none %}
    <span class="rs-num tier-{{ (r.rs_tier or 'null')|lower }}">RS {{ '%+.1f'|format(r.rs_delta_pct) }}%</span>
    {% if r.rs_tier %}
      <span class="tier-badge tier-{{ r.rs_tier|lower }}">R·{{ r.rs_tier }}</span>
    {% endif %}
  {% endif %}
  {% if 'PROBE_STRONG' in (r.decision_badges or []) %}
    <span class="badge badge-strong">⚡ PROBE_STRONG</span>
  {% endif %}
</div>
{% endif %}
```

Chip wrapper gets data attributes for filter JS:
```html
<div class="stock-chip"
     data-score-tier="{{ r.score_tier|default('null') }}"
     data-rs-tier="{{ r.rs_tier|default('null') }}"
     data-active-components="{{ r.active_components or 0 }}">
```

### 5.2 CSS color palette

Tier colors (works on the existing dark theme):

```css
.tier-strong  { background: #d4a017; color: #000; padding: 1px 6px; border-radius: 3px; }
.tier-mid     { background: #4a9eff; color: #fff; padding: 1px 6px; border-radius: 3px; }
.tier-weak    { background: #555;    color: #ccc; padding: 1px 6px; border-radius: 3px; }
.tier-null    { background: transparent; color: var(--muted); }

.tier-badge { font-size: 0.75em; margin: 0 4px; font-weight: 600; }
.score-num.tier-strong,
.rs-num.tier-strong   { color: #d4a017; font-weight: 600; }
.score-num.tier-mid,
.rs-num.tier-mid      { color: #4a9eff; font-weight: 600; }
.score-num.tier-weak,
.rs-num.tier-weak     { color: #aaa; }
```

### 5.3 Sort order

In `lifecycle_report.py:build_page_context()`, replace existing sort keys for `probe`, `watch`, `trending`:

```python
def _tier_sort_key(row):
    """Tier-aware sort: score desc, rs_delta_pct desc, active_components desc.
    Nulls sort last via sentinel -999 / -9999.
    """
    return (
        -(row.get("score") if row.get("score") is not None else -999),
        -(row.get("rs_delta_pct") if row.get("rs_delta_pct") is not None else -9999),
        -(row.get("active_components") or 0),
    )

probe.sort(key=_tier_sort_key)
watch.sort(key=_tier_sort_key)
trending.sort(key=_tier_sort_key)
# enter — keep existing (trigger_age_days then volume_ratio)
# avoid — keep existing (dist_ema9_pct desc)
# broken_table — keep existing
```

Result: STRONG-tier tickers first within each section, with RS magnitude as tiebreaker. WEAK / null score rows fall to the bottom.

### 5.4 Filter toolbar

Added above each section that gets tier-sorted (PROBE, WATCH, TRENDING). Client-side JS only — no server changes.

```html
<div class="filter-toolbar" data-section="probe">
  <button class="filter-btn active" data-filter="all">전체</button>
  <button class="filter-btn" data-filter="s-strong">Score STRONG</button>
  <button class="filter-btn" data-filter="rs-strong-mid">RS STRONG+MID</button>
  <button class="filter-btn" data-filter="active-4plus">활성 ≥ 4</button>
</div>
```

JS (single inline script per page, shared):

```html
<script>
(function() {
  document.querySelectorAll('.filter-toolbar').forEach(toolbar => {
    const section = toolbar.dataset.section;
    const grid = document.querySelector(`[data-grid="${section}"]`);
    if (!grid) return;

    toolbar.addEventListener('click', e => {
      if (!e.target.classList.contains('filter-btn')) return;
      toolbar.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      e.target.classList.add('active');
      const filter = e.target.dataset.filter;
      grid.querySelectorAll('.stock-chip').forEach(chip => {
        const st = chip.dataset.scoreTier;
        const rt = chip.dataset.rsTier;
        const ac = parseInt(chip.dataset.activeComponents || '0', 10);
        let show = true;
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

The section grid wrapper needs a `data-grid` attribute to be selectable:
```html
<div class="chip-grid" data-grid="probe">
  {% for r in probe %}
  <div class="stock-chip" ...>...</div>
  {% endfor %}
</div>
```

### 5.5 Glossary entries

In `templates/_lifecycle_glossary.html`, add 2 new `<dt>/<dd>` pairs:

```html
<dt>Score Tier (S·WEAK / S·MID / S·STRONG)</dt>
<dd>점수의 상대적 강도. trigger 트랙: WEAK=3, MID=4–5, STRONG=6. drift 트랙: WEAK=4, MID=5, STRONG=6+. drift STRONG은 기존 PROBE_STRONG ⚡ badge와 동일.</dd>

<dt>RS Tier (R·WEAK / R·MID / R·STRONG)</dt>
<dd>시장 대비 5일 outperform 정도 (rs_delta_pct). STRONG ≥ 10%, MID 5–9.99%, WEAK 0–4.99%. 같은 점수여도 RS가 높을수록 진짜 leader. SPY (US) / KS200 (KR) 대비.</dd>
```

---

## 6. Telegram Brief

**No changes.** User explicitly requested Telegram brief untouched in this iteration. The fields `score_tier` and `rs_tier` will be available in the result dict for future Telegram enhancements, but `_format_lifecycle_section()` and `_summarize_lifecycle()` in `telegram_sender.py` are not modified.

---

## 7. Invariants

Added to `tests/test_lifecycle_invariants.py`:

```python
def test_invariant_score_tier_exhaustive():
    """score_tier must be in {WEAK, MID, STRONG, None}."""
    # Build cases: ENTER, PROBE-trigger, PROBE-drift, WATCH, TRENDING, AVOID
    # Assert score_tier in valid set always

def test_invariant_score_tier_band_membership():
    """When score_tier is non-null, the score must fall within that band."""
    # For each (track, tier) combo:
    # band = SCORE_TIER_BANDS[track][tier]
    # assert band[0] <= score <= band[1]

def test_invariant_drift_strong_implies_probe_strong_badge():
    """score_tier=STRONG AND track=drift → PROBE_STRONG in decision_badges."""
    # build inputs producing drift score >= 6
    # assert result["score_tier"] == "STRONG"
    # assert "PROBE_STRONG" in result["decision_badges"]

def test_invariant_rs_tier_threshold_consistency():
    """rs_tier == STRONG ⟺ rs_delta_pct >= 10; MID ⟺ 5 <= rs < 10; WEAK ⟺ 0 <= rs < 5."""

def test_invariant_rs_tier_null_when_no_market_data():
    """rs_delta_pct=None → rs_tier=None."""
```

---

## 8. Files Changed

| Path | Action | Purpose |
|---|---|---|
| `lifecycle_score_config.py` | Modify | Add `SCORE_TIER_BANDS`, `RS_TIER_BANDS` constants |
| `lifecycle_score.py` | Modify | Add `compute_score_tier()`, `compute_rs_tier()`; extend `ScoreResult` dataclass; populate tiers in `_assemble()` |
| `lifecycle_signal.py` | Modify | Propagate `score_tier`/`rs_tier` in `_evaluate_decision_score()` (active + veto paths); same in `process_universe()` shadow path; merge fields in `_make_snapshot()` |
| `lifecycle_report.py` | Modify | Surface `score_tier`/`rs_tier` in `_attach_derived()`; replace sort keys for `probe`/`watch`/`trending` to use `_tier_sort_key` |
| `templates/lifecycle_us.html` + `lifecycle_kr.html` | Modify | Chip tier badges + data attributes; CSS tier classes; filter toolbar + JS |
| `templates/_lifecycle_glossary.html` | Modify | 2 new glossary entries |
| `telegram_sender.py` | **No change** | Per user request |
| `tests/test_lifecycle_score_config.py` | Modify | Band sanity tests (monotonic, complete coverage) |
| `tests/test_lifecycle_score.py` | Modify | Unit tests for `compute_score_tier()` + `compute_rs_tier()` + `ScoreResult` field presence |
| `tests/test_lifecycle_invariants.py` | Modify | 5 new invariants (§7) |
| `tests/test_lifecycle_decision_matrix.py` | Modify | Existing matrix tests now also assert correct `score_tier` |

**Summary**: 10 files modified, 0 new files, schema additive only.

---

## 9. Migration & Rollback

- **Schema**: append-only (`score_tier`, `rs_tier` two new fields). Legacy snapshots load with both = null.
- **UI rendering**: tier-related markup gated by `{% if r.score_tier %}` — no badge rendered for legacy snapshots.
- **Sort**: `_tier_sort_key` handles None gracefully (sentinel `-999`). Legacy snapshots sort to bottom but still render.
- **Rollback**: setting `LIFECYCLE_ENGINE_MODE=legacy` already disables score path; tiers also won't emit. No new envvar needed.
- **Engine version**: `score_v1` unchanged. Not a breaking schema change.

---

## 10. Out of Scope (explicit)

| Item | Reason |
|---|---|
| Decision logic changes | (B) decision in Q1 — display-only design |
| Threshold raise (drift_probe 4 → 5) | Selected (B), not (A) — keep current PROBE volume |
| Weight tuning | Phase 4 calibration — separate spec |
| Telegram brief tier markers | Explicit user request to skip |
| Sector diversity tier | Not the reported pain point — future |
| Streak/age scoring | Violates "stateless engine" principle |
| `decision_confidence` field | Score itself + tier suffices |
| Composite quality score | (D-2) over (B)/(C) — multi-axis preserves raw info |

---

## 11. Success Criteria

1. **Operator can identify top-tier PROBE candidates in < 5 seconds** — STRONG-tier badge + RS-STRONG color visible at top of sorted list.
2. **Sort + filter reduces effective scan list by ≥ 70%** — clicking `[Score STRONG]` on US data drops 43 → ~3 candidates.
3. **Zero decision-logic regression** — all 540 existing tests pass; invariants hold.
4. **PROBE_STRONG badge backward compat** — every existing PROBE_STRONG case still produces the badge.
5. **Calibration-ready** — `SCORE_TIER_BANDS` and `RS_TIER_BANDS` are externalized; tuning is config-only, no code change.

---

## 12. Estimated Effort

- Code: ~150–200 lines (config + helpers + sort + template chunks + CSS + filter JS)
- Tests: ~80–100 lines (unit + invariants + matrix extension)
- Migration: 0 lines (additive)
- Single PR, ~10 implementation tasks (much smaller than score_v1's 29).
