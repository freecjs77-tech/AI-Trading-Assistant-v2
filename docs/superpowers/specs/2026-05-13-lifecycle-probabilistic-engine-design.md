# Trade Lifecycle Probabilistic Engine — Design Spec

- **Date**: 2026-05-13
- **Status**: Design (approved through brainstorm, ready for implementation plan)
- **Scope**: Replace the internal evaluation engine of Trade Lifecycle Phase A with a probabilistic, score-based system. **External contracts preserved**: decision keys, history schema (additive only), page structure, Telegram brief format, pipeline integration.
- **Out of scope**: portfolio_stop_signal integration, stage tracking, automated execution, calibration tuning, US/KR weight divergence, setup_state threshold relaxation (see §11).
- **Engine version**: `score_v1` (introduced by this spec). Legacy engine retained as fallback (`phase_a_legacy`, accessible via `LIFECYCLE_ENGINE_MODE=legacy`).
- **Related**:
  - Supersedes the internal logic of [Trade Lifecycle Phase A](2026-05-08-trade-lifecycle-phase-a-design.md) — boolean trigger gate.
  - Preserves UI from [Lifecycle Page Redesign](2026-05-11-lifecycle-redesign-design.md).
  - Independent of [Emerging Momentum + Maturity v1.5](2026-05-09-emerging-momentum-maturity-design.md) (momentum scanner is upstream universe filter; coexists).

---

## 1. Problem Statement

Current Trade Lifecycle Phase A (`lifecycle_signal.py`) is a **good location detector** but its all-AND trigger gate is too strict to convert WATCH into actionable PROBE/ENTER signals.

```
Current CONFIRMED trigger requires ALL of:
  - EMA9 reclaim (yesterday close ≤ ema9 < today close)
  - volume_ratio ≥ 1.2x
  - close in upper 20% of day's range
  - prior-day high break
```

**Observed symptoms** (5 days of Phase A live data + reasoning):
- WATCH accumulates without promotion
- PROBE/ENTER are extremely rare
- Leader stocks already moved by the time CONFIRMED fires
- TREND_OK ("quiet leader" — NVDA/AVGO/MSFT/META style slow continuation without volume expansion) is permanently classified as TRENDING (don't chase), missing the strongest archetypes

**Root cause**: A binary all-AND gate cannot represent "rising probability." The strongest moves often start as quiet recoveries that lack any single dominant signal but accumulate multiple weak ones.

**Goal**: Convert the trigger/decision layer from binary confirmation to **evidence accumulation** while preserving setup state semantics, history continuity, and the safety properties of risk-tag-based AVOID.

---

## 2. Architectural Principles

Four principles emerged from design dialogue. Implementation decisions must trace back to these.

### Principle 1 — Setup provides context, score determines actionability
- Layer 1 (setup_state) classifies market structure. Unchanged.
- Layer 2 (score) evaluates entry probability. New.
- Setup_state is *not* a score input; score is *not* a setup classifier. The two answer different questions.

### Principle 2 — Risk is rule-based, opportunity is probabilistic
- AVOID decisions (FAILED_BREAKOUT / BROKEN / EXTENDED) are **deterministic vetoes**. No score can override.
- PROBE/ENTER promotions are **probabilistic accumulations** of weak signals.
- A high score CANNOT save a vetoed ticker. A weak score CANNOT promote without setup context.

### Principle 3 — Lifecycle is a stateless evaluation engine, not a state machine
- Every day's evaluation is **fresh**. No cycle persistence, no stage aging, no progression tracking.
- Decision is a pure function of today's market data + yesterday's snapshot for cross-day comparisons (higher_low, ema_reclaim).
- Multi-day cycle interpretation belongs to the human reader or a future, explicitly-scoped layer — never inside the lifecycle engine.

### Principle 4 — Now is the observation phase, not the optimization phase
- Default weights are reasonable judgments, not calibrated truths.
- Every component activation is recorded raw (`features{}` map + `score_components[]` array) for future analytics.
- Engine versioning (`engine_version` at file + snapshot level) enables longitudinal comparison.
- Calibration (Phase 4) is an explicit, separate workstream with its own spec.

**Auxiliary design rule** (from user memory): raw 수치 우선, 스코어/별점은 명시적 오버라이드 절차 필요. Scores must always be displayed alongside their raw components. Sizing recommendations are advisory only — never auto-executed.

---

## 3. Four-Layer Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 0 — Hard Risk Filter            [DETERMINISTIC]           │
│   if FAILED_BREAKOUT       → AVOID  + veto_reason               │
│   if setup == BROKEN       → AVOID  + veto_reason               │
│   if setup == EXTENDED     → AVOID  + veto_reason               │
└──────────────────────┬──────────────────────────────────────────┘
                       │ pass
┌──────────────────────▼──────────────────────────────────────────┐
│ Layer 1 — Context: setup_state         [UNCHANGED]              │
│   TREND_OK / PULLBACK / BASE_FORMING / EXTENDED / BROKEN        │
│   Phase A definitions + thresholds + precedence: 100% preserved │
└──────────────────────┬──────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────┐
│ Layer 2 — Opportunity Score            [NEW · PROBABILISTIC]    │
│                                                                 │
│   trigger_score  (PULLBACK / BASE_FORMING)                      │
│     9 components, max 14 points                                 │
│                                                                 │
│   drift_score    (TREND_OK — captures quiet leaders)            │
│     7 components, max 9 points                                  │
│                                                                 │
│   All components → features{} map + score_components[] list     │
│   Weights externalized in lifecycle_score_config.py             │
└──────────────────────┬──────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────┐
│ Layer 3 — Decision Promotion           [NEW · SCORE-DRIVEN]     │
│                                                                 │
│   trigger track (PULLBACK / BASE_FORMING):                      │
│     trigger_score ≥ 7  → ENTER                                  │
│     trigger_score 3-6  → PROBE                                  │
│     trigger_score < 3  → WATCH                                  │
│                                                                 │
│   drift track (TREND_OK):                                       │
│     drift_score ≥ 6    → PROBE + PROBE_STRONG badge             │
│     drift_score 4-5    → PROBE                                  │
│     drift_score < 4    → TRENDING                               │
│                                                                 │
│   + suggested_entry_tier + suggested_size_pct                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Layer 0 — Hard Risk Filter

Deterministic veto. Runs first. No score, no probabilistic logic.

### 4.1 Veto conditions

| Veto | Trigger | Rationale |
|---|---|---|
| `FAILED_BREAKOUT` | Yesterday's snapshot had `trigger == CONFIRMED_TRIGGER` AND today's close < ema9 | Pattern invalidation. Not just overheat — structural failure. Phase A loose form preserved (`FAILED_BREAKOUT_REQUIRE_BELOW_PRIOR_LOW = False`). |
| `BROKEN` | `setup_state == BROKEN` (ema21 < ema65 OR close < ema65) | Structural trend failure. Distribution possible. |
| `EXTENDED` | `setup_state == EXTENDED` (dist_ema9 > 12% AND RSI > 72) | Overheat. RR severely degraded. Phase A definition preserved. |

### 4.2 Risk tags NOT vetoed

`OVERHEAT` (RSI ≥ 80) and `PARABOLIC` (1d +8% AND vol ≥ 2x) remain **informational tags only**. They appear in `risk_tags[]` and may be surfaced in the UI, but they do not force AVOID.

**Rationale**: The strongest leaders frequently exhibit OVERHEAT/PARABOLIC states during major moves (NVDA, SMCI, PLTR). Vetoing them would defeat the purpose of capturing leadership. Phase A behavior preserved.

### 4.3 Output contract

```python
def hard_risk_veto(setup_state: str, risk_tags: list[str]) -> Optional[str]:
    """Return veto reason ("FAILED_BREAKOUT"|"BROKEN"|"EXTENDED") or None."""
    if "FAILED_BREAKOUT" in risk_tags: return "FAILED_BREAKOUT"
    if setup_state == "BROKEN":        return "BROKEN"
    if setup_state == "EXTENDED":      return "EXTENDED"
    return None
```

When veto fires:
- `decision = "AVOID"`, `veto_reason = <reason>`
- Public `score = null`, `features = null`, `score_components = null`
- Internal `_raw_score`, `_raw_features`, `_raw_score_track` ARE computed (analytics use only — see §6)
- `trigger_state = "WAIT"` (legacy compat — `veto_reason` carries the real meaning)

---

## 5. Layer 1 — Context (Unchanged)

Phase A's `evaluate_setup_state()` is reused verbatim. No threshold changes. No predicate changes.

| State | Definition | Source |
|---|---|---|
| `BROKEN` | `ema21 < ema65` OR `close < ema65` | `_is_broken()` |
| `EXTENDED` | `ema9>ema21>ema65` AND `dist_ema9 > 12%` AND `RSI > 72` | `_is_extended()` |
| `BASE_FORMING` | TREND_OK + `days_sideways ∈ [5,15]` + `atr5 < atr20` + `vol5 < vol20×0.85` + `ema21_slope > 0` | `_is_base_forming()` |
| `PULLBACK` | TREND_OK + `dist_ema9 ≤ 3%` + `close ≥ ema21` | `_is_pullback()` |
| `TREND_OK` | `ema9 > ema21 > ema65` AND `ema65_slope > 0` | `_is_trend_ok()` |

Precedence (first match): **BROKEN → EXTENDED → BASE_FORMING → PULLBACK → TREND_OK**. Fallback: BROKEN.

**Rationale**: Setup classification accumulates semantic meaning over time. Changing thresholds now would corrupt regime comparison and calibration baselines. The bottleneck this spec addresses is promotion (Layer 2/3), not classification (Layer 1).

---

## 6. Layer 2 — Opportunity Score

Two parallel score functions. Setup_state decides which one runs.

### 6.1 `trigger_score` — PULLBACK / BASE_FORMING

| # | Component | Weight | Definition | Data source |
|---|---|---|---|---|
| 1 | `ema_reclaim` | +2 | `yesterday.close ≤ ema9 < today.close` | Phase A snapshot raw |
| 2 | `higher_low` | +2 | `today.low > yesterday.low` | Phase A snapshot raw |
| 3 | `rs_strong` | +2 | `ret_5d_pct > market_ret_5d_pct` (SPY for US, KS200 for KR) | NEW: `market_ret_5d` |
| 4 | `lower_wick` | +1 | `(min(open, close) − low) / (high − low) ≥ 0.4` AND `close ≥ open` | NEW: `open` |
| 5 | `tight_range` | +1 | `(high − low) / atr14 < 0.7` | existing |
| 6 | `vol_expansion` | +2 | `volume_ratio ≥ 1.2` | existing |
| 7 | `breakout` | +2 | `today.close > rolling_high_20d_prior` (excludes today) | NEW: `high_20d_prior` |
| 8 | `close_strong` | +1 | `(close − low) / (high − low) ≥ 0.5` (top half) | existing |
| 9 | `intraday_reversal` | +1 | `low < open AND close > open` | NEW: `open` |

**Max points**: 14. **Thresholds**: ENTER ≥ 7, PROBE 3-6, WATCH < 3.

#### Design notes
- `ema_reclaim` matches Phase A arm 1 exactly for cross-engine comparability.
- `rs_strong` uses **market** benchmark (single per-market value), not sector. Sector RS deferred to calibration phase to avoid sector-mapping complexity.
- `lower_wick` requires `close ≥ open` to distinguish strong intraday recovery from a green bar with a long tail.
- `breakout` uses `close > prior 20-day high` (not intraday `high`) — wick-based breakouts are unreliable.
- `close_strong` relaxed from Phase A's 0.8 (top 20%) to 0.5 (top 50%), per design dialogue agreement.
- `vol_expansion` is now ONE component, not a gate. This is the single largest mechanical change driving signal frequency.

### 6.2 `drift_score` — TREND_OK only

Designed to capture "quiet leaders" — slow continuation without volume expansion.

| # | Component | Weight | Definition | Data source |
|---|---|---|---|---|
| 1 | `ema_alignment` | +1 | `ema9 > ema21 > ema65` (already true via TREND_OK, scored explicitly) | existing |
| 2 | `close_above_ema9` | +1 | `close > ema9` | existing |
| 3 | `higher_low` | +2 | `today.low > yesterday.low` (shared with trigger_score) | snapshot |
| 4 | `atr_contraction` | +1 | `atr14_pct_5d_avg < atr14_pct_20d_avg` | existing |
| 5 | `rs_strong` | +2 | `ret_5d_pct > market_ret_5d_pct` (shared with trigger_score) | NEW (shared) |
| 6 | `low_vol_drift` | +1 | `atr14_pct < atr14_pct_20d_avg × 0.8` | existing |
| 7 | `tight_close_cluster` | +1 | `(max(close[-3:]) − min(close[-3:])) / atr14 < 0.5` | snapshots[-3:] |

**Max points**: 9. **Thresholds**: PROBE+PROBE_STRONG ≥ 6, PROBE 4-5, TRENDING < 4. **No ENTER** (default).

#### Design notes
- `vol_expansion` and `breakout` are **intentionally absent**. The whole point of drift is silent continuation. Including either would collapse drift into trigger.
- `tight_close_cluster` requires 3 days of snapshot history. First-time tickers (no history) fail this component naturally.
- `rs_strong` weighted +2 because RS is the strongest predictor of true leader continuation.

### 6.3 Veto-time score handling

When Layer 0 vetoes, score is **still internally computed** but not exposed publicly. This preserves analytics for questions like "which features were active in vetoed tickers?" — critical for calibration of EXTENDED leaders, climax continuations, and failed-breakout recoveries.

```python
# Public output (UI + Telegram + downstream consumers)
{"decision": "AVOID", "veto_reason": "EXTENDED", "score": null, "features": null}

# Internal (history JSON, analytics only)
{"_raw_score": 7, "_raw_features": {...}, "_raw_score_track": "trigger"}
```

UI default: `_raw_*` fields hidden. Visible only with `?debug=1` URL query.

### 6.4 Edge cases

| Case | Behavior |
|---|---|
| First-day ticker (no yesterday snapshot) | `higher_low`, `ema_reclaim`, `tight_close_cluster` = False. Score computed from remaining components. |
| `volume_ratio` missing | `vol_expansion` = False. |
| `market_ret_5d` fetch failed | Use last cached value (max age = 3 calendar days). Beyond 3d → `rs_strong` = False (conservative). Log warning. Pipeline continues. *Rationale: transient SPY/KS200 API failure should not silently disable RS signal market-wide.* |
| `high == low` (zero-range bar) | `lower_wick`, `close_strong`, `intraday_reversal` = False (divide-by-zero avoided). |
| `atr14` = 0 or None | `tight_range`, `low_vol_drift`, `tight_close_cluster` = False. |
| Setup vetoed (EXTENDED/BROKEN) | Score path skipped; `_raw_*` computed for analytics. |

**Invariant**: Missing data = signal absence (False). Never promoted to True.

### 6.5 `lifecycle_score_config.py` shape

```python
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

# IMPORTANT — Component ordering invariant:
# `score_components[]` lists in the history JSON MUST follow the iteration
# order of the dict below. UI rendering, analytics diffs, and snapshot
# comparison all assume this stable order. Renaming or reordering keys
# constitutes a schema-breaking change (bump ENGINE_VERSION).
TRIGGER_WEIGHTS = {
    "ema_reclaim": 2, "higher_low": 2, "rs_strong": 2,
    "lower_wick": 1, "tight_range": 1, "vol_expansion": 2,
    "breakout": 2, "close_strong": 1, "intraday_reversal": 1,
}

DRIFT_WEIGHTS = {
    "ema_alignment": 1, "close_above_ema9": 1, "higher_low": 2,
    "atr_contraction": 1, "rs_strong": 2, "low_vol_drift": 1,
    "tight_close_cluster": 1,
}

THRESHOLDS = {
    "trigger_probe": 3, "trigger_enter": 7,
    "drift_probe": 4, "drift_enter": 6,
}

DRIFT_ALLOW_ENTER = False  # Phase 1 default; calibration may flip

# Component sub-thresholds
LOWER_WICK_MIN_RATIO    = 0.4
CLOSE_STRONG_MIN_RATIO  = 0.5
TIGHT_RANGE_MAX_ATR     = 0.7
VOL_EXPANSION_MIN_RATIO = 1.2
LOW_VOL_DRIFT_RATIO     = 0.8
TIGHT_CLUSTER_MAX_ATR   = 0.5

SIZE_TIERS = {
    "core":         {"size_pct": 0.35, "range": (0.30, 0.40)},
    "starter_plus": {"size_pct": 0.25, "range": (0.25, 0.30)},  # PROBE_STRONG; same size as starter, badge carries meaning
    "starter":      {"size_pct": 0.25, "range": (0.20, 0.30)},
    None:           {"size_pct": 0.0,  "range": (0.0, 0.0)},
}
```

All weights, thresholds, sizes are externalized — Phase 4 calibration can tune without code changes.

---

## 7. Layer 3 — Decision Promotion

### 7.1 Decision matrix

```
┌──────────────────────┬─────────────────┬─────────────┬──────────────────────┐
│ Setup / Veto         │ Score Track     │ Score       │ Decision (+ Badges)  │
├──────────────────────┼─────────────────┼─────────────┼──────────────────────┤
│ Layer 0 veto         │ —               │ —           │ AVOID + veto_reason  │
├──────────────────────┼─────────────────┼─────────────┼──────────────────────┤
│ PULLBACK             │ trigger_score   │ ≥ 7         │ ENTER                │
│ BASE_FORMING         │ (max 14)        │ 3-6         │ PROBE                │
│                      │                 │ < 3         │ WATCH                │
├──────────────────────┼─────────────────┼─────────────┼──────────────────────┤
│ TREND_OK             │ drift_score     │ ≥ 6         │ PROBE [PROBE_STRONG] │
│                      │ (max 9)         │ 4-5         │ PROBE                │
│                      │                 │ < 4         │ TRENDING             │
└──────────────────────┴─────────────────┴─────────────┴──────────────────────┘
```

**Drift ENTER disabled by default** (`DRIFT_ALLOW_ENTER = False`). Drift can emit PROBE with PROBE_STRONG badge, but never ENTER, until calibration validates drift continuation expectancy.

### 7.2 Sizing hints

| Decision | Badge | Tier | size_pct |
|---|---|---|---|
| ENTER | — | `core` | 0.35 |
| PROBE | PROBE_STRONG | `starter_plus` | 0.25 (same as starter; badge carries the conviction) |
| PROBE | — | `starter` | 0.25 |
| WATCH / TRENDING / AVOID | — | null | 0.0 |

Advisory only. Never auto-executed. UI displays alongside raw component scores.

### 7.3 Legacy `trigger_state` mapping

Preserved as a **derived compatibility field**. Primary truth: `score` + `decision`.

| Condition | `trigger_state` |
|---|---|
| Layer 0 veto fires | `"WAIT"` (with `veto_reason` carrying real meaning) |
| Trigger track, score ≥ 7 | `"CONFIRMED_TRIGGER"` |
| Trigger track, score 3-6 | `"EARLY_TRIGGER"` |
| Trigger track, score < 3 | `"WAIT"` |
| Drift track, score ≥ 4 | `"EARLY_TRIGGER"` |
| Drift track, score < 4 | `"WAIT"` |

Rationale: All existing downstream consumers (history parsers, Telegram, page renderers) continue to function. They will see the new score fields if they look, and continue ignoring them if they don't.

### 7.4 Decision evaluator (pseudocode)

```python
def evaluate_decision(setup_state, today_raw, yesterday_snap, recent_3d_closes,
                      risk_tags, market_ret_5d) -> dict:
    veto = hard_risk_veto(setup_state, risk_tags)
    if veto:
        # Even vetoed tickers get internal score for analytics.
        # Track selection: EXTENDED/TREND_OK use drift; PULLBACK/BASE_FORMING/BROKEN use trigger.
        if setup_state in ("TREND_OK", "EXTENDED"):
            raw, raw_track = compute_drift_score(today_raw, yesterday_snap, recent_3d_closes, market_ret_5d), "drift"
        else:
            raw, raw_track = compute_trigger_score(today_raw, yesterday_snap, market_ret_5d), "trigger"
        return {
            "decision": "AVOID", "veto_reason": veto,
            "score": None, "features": None, "score_components": None,
            "active_components": None,
            "_raw_score": raw.score, "_raw_features": raw.features,
            "_raw_score_track": raw_track,
            "decision_badges": [],
            "suggested_entry_tier": None, "suggested_size_pct": 0.0,
            "trigger_state": "WAIT",
        }

    if setup_state in ("PULLBACK", "BASE_FORMING"):
        sc, track = compute_trigger_score(today_raw, yesterday_snap, market_ret_5d), "trigger"
        if sc.score >= THRESHOLDS["trigger_enter"]:
            decision, badges = "ENTER", []
        elif sc.score >= THRESHOLDS["trigger_probe"]:
            decision, badges = "PROBE", []
        else:
            decision, badges = "WATCH", []

    elif setup_state == "TREND_OK":
        sc, track = compute_drift_score(today_raw, yesterday_snap, recent_3d_closes, market_ret_5d), "drift"
        if sc.score >= THRESHOLDS["drift_enter"]:
            decision = "ENTER" if DRIFT_ALLOW_ENTER else "PROBE"
            badges   = [] if DRIFT_ALLOW_ENTER else ["PROBE_STRONG"]
        elif sc.score >= THRESHOLDS["drift_probe"]:
            decision, badges = "PROBE", []
        else:
            decision, badges = "TRENDING", []
    else:
        return {"decision": "AVOID", "veto_reason": "UNKNOWN_SETUP", ...}

    tier = DECISION_TO_TIER.get((decision, badges[0] if badges else None))
    return {
        "decision": decision, "decision_badges": badges,
        "score": sc.score, "score_track": track,
        "active_components": sc.active_count,
        "features": sc.features, "score_components": sc.components_list,
        "rs_delta_pct": sc.rs_delta_pct,
        "suggested_entry_tier": tier,
        "suggested_size_pct": SIZE_TIERS[tier]["size_pct"],
        "trigger_state": _derive_legacy_trigger_state(sc.score, track),
        "veto_reason": None,
    }
```

---

## 8. Data Dependencies

### 8.1 New fields in `fetch_market_data.py`

| Field | Used by | Cost |
|---|---|---|
| `open` | `lower_wick`, `intraday_reversal` | 0 — yfinance row already contains it |
| `high_20d_prior` | `breakout` | 0 — recompute existing `high_20d` excluding today |
| `market_ret_5d` (per-market singleton) | `rs_strong` | 1 additional ticker fetch (SPY for US, KS200 for KR) per pipeline run |

### 8.2 Market benchmark fetch

`market_ret_5d` is **fetched once per pipeline run**, cached, and passed to all tickers in that market. Implementation lives in the lifecycle orchestrator (`run_lifecycle()`) — not in `fetch_market_data.fetch_ticker()`.

```python
# pipeline.py or lifecycle_signal.run_lifecycle()
market_benchmark = {
    "US": fetch_ret_5d("SPY"),
    "KR": fetch_ret_5d("KS200"),  # or "069500.KS" KODEX 200 ETF
}
```

**Cache fallback policy**: write each successful fetch to `history/market_benchmark_cache.json` with timestamp. On fetch failure, reuse last cached value if `now - cached_at ≤ 3 calendar days`; otherwise treat as missing (`rs_strong = False` for all tickers in that market this run). Cache file is small (one float + timestamp per market) and append-safe.

### 8.3 Snapshot history requirements

- `yesterday.close`, `yesterday.low`, `yesterday.high`, `yesterday.ema9` — already saved in Phase A snapshot `raw`.
- Last 3 closes — derive from `snapshots[-3:]` in lifecycle history. Pass into `evaluate_decision` as `recent_3d_closes`. If fewer than 3 available, `tight_close_cluster` = False.

---

## 9. History JSON Schema (Append-Only)

```json
{
  "version": "lifecycle_phase_a/0.1.0",          // existing
  "current_engine_version": "score_v1",           // NEW: top-level current engine
  "market": "US",                                 // NEW: explicit market
  "as_of": "2026-05-14",
  "tickers": {
    "AVGO": {
      "snapshots": [
        {
          "date": "2026-05-14",
          "engine_version": "score_v1",          // NEW: per-snapshot version

          // ── existing Phase A fields (preserved) ──
          "setup":    "PULLBACK",
          "trigger":  "CONFIRMED_TRIGGER",        // derived from score (legacy compat)
          "decision": "ENTER",
          "raw": { /* close, ema9/21/65, rsi14, dist_ema9_pct, volume_ratio, atr_pct, sector, risk_tags */ },

          // ── new score-engine fields ──
          "score": 8,
          "score_track": "trigger",
          "active_components": 5,
          "features": {
            "ema_reclaim": true, "higher_low": true, "rs_strong": true,
            "lower_wick": false, "tight_range": false, "vol_expansion": true,
            "breakout": true, "close_strong": false, "intraday_reversal": true
          },
          "score_components": [
            {"name": "ema_reclaim", "weight": 2, "active": true},
            {"name": "higher_low",  "weight": 2, "active": true},
            {"name": "rs_strong",   "weight": 2, "active": true},
            {"name": "vol_expansion","weight": 2, "active": true},
            {"name": "breakout",    "weight": 2, "active": true}
          ],
          "decision_badges": [],
          "veto_reason": null,
          "suggested_entry_tier": "core",
          "suggested_size_pct": 0.35,
          "rs_delta_pct": 4.2,

          // ── internal analytics (UI hidden by default) ──
          "_raw_score": null,
          "_raw_features": null,
          "_raw_score_track": null
        }
      ]
    }
  },
  "transitions": [
    /* existing types preserved; new types added by this spec: */
    /* "score_jump"    (Δscore ≥ 3 between consecutive snapshots)              */
    /* "drift_probe"   (drift_score first crosses ≥ 4)                          */
    /* "probe_strong"  (PROBE_STRONG badge first attaches in current streak)   */
    /*                                                                          */
    /* Dedup policy (CRITICAL — avoid noisy transitions):                       */
    /*   - "first attach only" — emit when state CHANGES vs yesterday's snapshot */
    /*   - drift_probe: emit only when yesterday drift_score < 4 AND today ≥ 4   */
    /*   - probe_strong: emit only when yesterday lacked badge AND today has it  */
    /*   - score_jump: emit when |today.score - yesterday.score| ≥ 3            */
    /*   - Re-emission only after the state has fallen below threshold for ≥ 1d  */
  ]
}
```

### Migration policy
- Loading legacy history (no `current_engine_version`): auto-fill `"phase_a_legacy"`.
- New score fields absent on old snapshots: UI renders empty cells gracefully.
- Engine version drift across snapshots: explicitly supported. Calibration tools can filter by version.

---

## 10. UI Surface

[Lifecycle Page Redesign](2026-05-11-lifecycle-redesign-design.md) structure preserved entirely. **Additions only.**

### 10.1 Chip enhancement (decision grid)

```
┌─────────────────────────┐
│ AVGO          [PULLBACK]│
│ 본 진입               8│
│ ●●●●○ 5 features active │
└─────────────────────────┘
```

### 10.2 "📖 용어 사전" additions
- `Score` — Layer 2 evidence accumulation
- `trigger_score` vs `drift_score`
- Each of the 9 trigger / 7 drift components, defined in raw-number terms (per user memory: raw 수치 우선)
- `PROBE_STRONG` badge meaning

### 10.3 "⚙ 고급 보기" collapsible additions
- Per-ticker `score_components` table (which components activated)
- `active_components` count
- `rs_delta_pct` raw margin
- `_raw_*` fields visible only with `?debug=1`

### 10.4 "📊 오늘의 결론" narration additions
- "Drift 트랙 PROBE: N건 (META, AVGO, ...)" — surface TREND_OK actionable events
- "PROBE_STRONG: NVDA (drift_score 7)" — highlight strongest drift candidates

### 10.5 Telegram brief additions
- ENTER: `🟢 AVGO 본 진입 (score 8)`
- Drift PROBE: `🌊 META drift PROBE (score 5)`
- PROBE_STRONG: `⚡ NVDA PROBE_STRONG (drift 7)`

---

## 11. Out of Scope

Items explicitly excluded from this spec to preserve focus and rollback safety.

| Item | Reason | Future home |
|---|---|---|
| Setup_state threshold relaxation (BASE_FORMING 5–15 → 3–10, PULLBACK distance) | This spec's hypothesis is "promotion bottleneck"; setup relaxation is a separate hypothesis that must be tested independently | Separate spec post-calibration |
| portfolio_stop_signal integration / live position tracking | Scope explosion; signal/position layers stay decoupled | Phase B+ |
| Stage persistence, cycle IDs, signal aging | Violates "stateless engine" principle | May be permanently out of scope |
| Backtest harness / score weight tuning | Insufficient data pre-launch; live distribution is faster truth | Phase 4 calibration (separate spec) |
| Sector-relative RS | Market RS first for simplicity | Calibration phase |
| US vs KR weight divergence | Same engine first to validate semantics | Calibration phase |
| `EXHAUSTION_WICK` risk tag | Predictive power unverified; strong leaders often continue after exhaustion-shaped bars | Observational-only tag, future review |
| EXTENDED sub-tiers (LIGHT/HARD) | Complexity for marginal benefit; hard veto sufficient | Calibration phase |
| Additional risk vetoes (low liquidity, gap-down) | "Veto = structural failure only" principle; these belong in universe filter | Universe layer |
| `decision_confidence` / `score_pct` derived fields | Score itself is sufficient signal | Future addition if calibration reveals need |
| Automated trade execution | This system is signal-only | Permanent out of scope |

### 11.1 Archetype-collapse guardrail (Phase 4 calibration boundary)

During calibration, a common failure mode is to add `breakout` or `vol_expansion` components to `drift_score` to "boost coverage." This collapses drift into "weak trigger" and destroys the archetype separation that justifies having two tracks.

**Rule for calibration phase**:
- Drift weights may be tuned. **New component types** that overlap trigger's expansion features (breakout, volume spikes, prior-high break) are forbidden in drift.
- If drift coverage is too low, raise individual existing-component weights rather than importing trigger components.
- Adding ANY component that exists in both tracks requires explicit spec amendment with archetype-separation justification.

---

## 12. Soft Migration — 4 Phases / 3 PRs

### Phase 1 — Score infrastructure + shadow mode  *(PR #1)*
- `lifecycle_score.py` (compute_trigger_score, compute_drift_score)
- `lifecycle_score_config.py` (weights, thresholds, sizes)
- `lifecycle_signal.evaluate_decision()` refactored to delegate to score engine
- `LIFECYCLE_ENGINE_MODE` envvar (`legacy` | `score_shadow` | `score_active`)
  - `legacy`: Phase A boolean path (rollback target)
  - `score_shadow`: score computed and stored, decision still from Phase A boolean
  - `score_active`: score-driven decision
- Default mode: `score_shadow` for one observation window, then `score_active`
- History schema extended (append-only)
- Page chips show score + active_components; legacy decision unchanged
- New tests: `test_lifecycle_score.py`, `test_lifecycle_invariants.py`

**Exit criteria**:
- Phase A legacy history loads without errors
- New snapshots emit all new fields
- Under `score_shadow`: store both Phase A decision (actual) AND would-be score-engine decision (shadow). For 5 trading days, every Phase A AVOID matches a score-engine AVOID (zero false-clear); the inverse (score AVOID but Phase A non-AVOID) is logged but allowed.
- Invariant tests pass: FAILED_BREAKOUT/BROKEN/EXTENDED → AVOID always (both engines)

### Phase 2 — Trigger promotion activated  *(PR #2)*
- Switch default mode to `score_active`
- Apply trigger thresholds (PROBE ≥ 3, ENTER ≥ 7)
- Volume requirement formally dropped to one component (was hard gate)
- Page narration surfaces PROBE/ENTER frequency

**Exit criteria**:
- PROBE frequency ≥ 3× Phase A baseline over 5 trading days
- FAILED_BREAKOUT/BROKEN/EXTENDED still 100% AVOID (regression check)
- No score=null leaks to UI for non-veto cases

### Phase 3 — Drift track activated  *(PR #3)*
- Enable `drift_score` evaluation for TREND_OK setup
- Apply drift thresholds (PROBE 4-5, PROBE_STRONG ≥ 6)
- `DRIFT_ALLOW_ENTER = False` enforced
- New transition type: `drift_probe`, `probe_strong`
- Telegram surfaces drift events distinctly

**Exit criteria**:
- TREND_OK → PROBE conversion ≥ 1 ticker/week
- At least one of {NVDA, AVGO, MSFT, META, GOOGL} captured by drift track during observation period
- No regression: trigger track unaffected

### Phase 4 — Calibration  *(separate spec, post-launch)*
- 2-4 weeks accumulated `score_components` data
- Component-level expectancy analysis (forward returns by feature activation)
- Weight tuning, threshold adjustment
- US vs KR divergence analysis
- `DRIFT_ALLOW_ENTER` reconsidered
- → New spec, new brainstorm, not part of this work

---

## 13. Success Criteria

Order reflects priority. Distribution + transition metrics rank above raw counts.

1. **TREND_OK → PROBE conversion rate** (KEY metric for this redesign) — mega-cap leaders (NVDA/AVGO/MSFT/META/GOOGL) emit PROBE via drift track when actually trending.
2. **PROBE → ENTER promotion within 3-5 days** — PROBEs convert at a non-trivial rate (indicates PROBE is meaningful, not noise).
3. **WATCH → PROBE transition rate** — WATCH should not be a permanent destination.
4. **Score distribution smoothness** — no clustering at 0 or at the threshold edges.
5. **Sector diversity** — PROBE/ENTER signals span ≥ 3 sectors at any given week (not single-sector concentration).
6. **AVOID safety regression: zero** — every Phase-A-vetoed case remains AVOID in score engine.
7. **Backward compat: zero history JSON / page-render failures** when loading mixed-version data.
8. **Explainability**: any PROBE/ENTER decision can be explained in ≤ 1 sentence by reading `score_components`.

Raw PROBE count target (~3× Phase A) is a *secondary* check — distribution health matters more than absolute volume.

---

## 14. Risk & Rollback

### Risk #1 — PROBE noise flood
- Symptom: >50 PROBEs/day, low quality
- Mitigation: raise `THRESHOLDS["trigger_probe"]` to 4 or 5 via config (no redeploy)

### Risk #2 — ENTER drought
- Symptom: 0 ENTERs/week
- Mitigation: lower `THRESHOLDS["trigger_enter"]` to 6; revisit `breakout`/`vol_expansion` weights

### Risk #3 — Drift false positives
- Symptom: drift PROBE → BROKEN within 5 days at high rate
- Mitigation: raise `THRESHOLDS["drift_probe"]` to 5; increase weights on `low_vol_drift`/`atr_contraction`

### Risk #4 — AVOID regression
- Symptom: a Phase-A-vetoed ticker emits PROBE/ENTER
- Detection: automated invariant assertions run on every pipeline output (see §15.2)
- Mitigation: this is a code bug — hotfix; flip envvar `LIFECYCLE_ENGINE_MODE=legacy` immediately

### Risk #5 — Hidden upstream coupling breaks
- Symptom: Telegram template / page render fails on new fields
- Mitigation: Phase 1 `score_shadow` mode runs full schema with old decision — exercises all consumers before behavioral change

### Rollback procedure
1. Set environment variable: `LIFECYCLE_ENGINE_MODE=legacy`
2. Pipeline next run uses Phase A boolean path
3. History JSON new fields remain (harmless extras)
4. No code revert required

---

## 15. Tests & Verification

### 15.1 New test files

| File | Purpose |
|---|---|
| `tests/test_lifecycle_score.py` | Component-level unit tests (each of 9 trigger + 7 drift components in isolation) |
| `tests/test_lifecycle_decision_matrix.py` | Exhaustive (setup_state × score) → decision tabulation |
| `tests/test_lifecycle_invariants.py` | Hard contracts (see §15.2) |
| `tests/test_lifecycle_config.py` (existing) | Extended to cover `lifecycle_score_config.py` weight + rationale comment validation |

### 15.2 Invariants (continuously enforced)

```python
# tests/test_lifecycle_invariants.py
def test_failed_breakout_always_avoid(snapshot): ...
def test_broken_setup_always_avoid(snapshot): ...
def test_extended_setup_always_avoid(snapshot): ...
def test_avoid_has_null_public_score(snapshot): ...
def test_avoid_has_internal_raw_score(snapshot): ...
def test_trigger_state_legacy_mapping_consistent(snapshot): ...
def test_drift_track_never_enter_when_disabled(snapshot): ...
def test_score_components_sum_equals_score(snapshot): ...
def test_active_components_matches_features_true_count(snapshot): ...
def test_suggested_size_zero_for_non_actionable(snapshot): ...
```

### 15.3 Optional analytics helper

`analytics/score_distribution_report.py` — reads lifecycle history, emits:
- Score histogram per market
- Per-component activation frequency
- Decision distribution (WATCH/PROBE/ENTER/TRENDING/AVOID counts)
- PROBE → ENTER conversion rate
- Drift PROBE breakdown

Used during Phase 1 shadow window and ongoing in Phase 4 calibration.

---

## 16. Files Changed

| Path | Action |
|---|---|
| `lifecycle_signal.py` | Refactor `evaluate_decision()`; add `hard_risk_veto()`; envvar dispatcher for `LIFECYCLE_ENGINE_MODE` |
| `lifecycle_config.py` | No change (Layer 1 untouched) |
| `lifecycle_score.py` | **NEW** — score computation (trigger + drift) |
| `lifecycle_score_config.py` | **NEW** — weights, thresholds, sizes |
| `lifecycle_history.py` | Extend `append_snapshot` for new fields (forward-compat); add new transition types |
| `lifecycle_report.py` | Chip enhancement; 용어사전/고급보기 extensions; debug toggle |
| `fetch_market_data.py` | Emit `open`, `high_20d_prior` |
| `pipeline.py` | One-time market benchmark fetch (SPY, KS200) per run; pass into lifecycle orchestrator |
| `templates/lifecycle_us.html` / `lifecycle_kr.html` | Chip info, narration additions |
| `history/lifecycle_history_us.json` / `_kr.json` | Schema additions (append-only) |
| `tests/test_lifecycle_score.py` | **NEW** |
| `tests/test_lifecycle_decision_matrix.py` | **NEW** |
| `tests/test_lifecycle_invariants.py` | **NEW** |
| `tests/test_lifecycle_config.py` | Extend to cover score config |
| `analytics/score_distribution_report.py` | **NEW** (optional, recommended) |
| `docs/lifecycle_score_spec.md` | **NEW** — in-tree spec freeze (mirrors this design doc as runtime reference) |

---

## 17. Open Items for Implementation Plan

These are details deferred to the implementation plan (writing-plans skill output). Most have a preferred direction noted (set during design dialogue) — the plan resolves the final approach.

1. **`LIFECYCLE_ENGINE_MODE` dispatch** — preferred: explicit `if/elif/else` branch in `lifecycle_signal.evaluate_decision()`. Not strategy pattern (traceability > polymorphism for business logic).
2. **`transitions[]` event emission** — policy now defined in §9 (first-attach-only, threshold-cross detection). Plan resolves where the diff happens (in `compute_transitions()`) and how it integrates with existing event types.
3. **`lifecycle_report.py` chip rendering** — visual choice for `active_components` (●●●●○ filled-circles, numeric badge, or progress bar). Plan picks one; preference noted in §10.1 as ●●●●○ style.
4. **`market_ret_5d` cache file location/format** — §8.2 specifies `history/market_benchmark_cache.json`. Plan resolves the read/write helpers and lock semantics.
5. **`high_20d_prior` computation** — preferred: recompute from existing `high_20d` rolling window by excluding today's bar (no new yfinance column).
6. **Test fixture strategy for invariants** — preferred: replay from recorded Phase A history + small synthetic cases for edge handling.
7. **`_raw_*` namespace consolidation** (optional future) — current flat fields work; consolidating to `_internal: {raw_score, raw_features, raw_score_track}` is a nice-to-have if more internal fields accumulate. Skip for v1, revisit in calibration phase if surface grows.
