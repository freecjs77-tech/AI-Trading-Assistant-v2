# Phase A — Trend Structure + Setup/Trigger Lifecycle (Design)

**Date**: 2026-05-08
**Owner**: freecjs77@gmail.com
**Roadmap**: [`2026-05-08-trade-lifecycle-roadmap.md`](2026-05-08-trade-lifecycle-roadmap.md)

## 1. Problem statement

momentum_scanner v1.0 surfaces strong-momentum candidates but treats every day as an isolated snapshot. Two failure modes follow:

1. **Late chase.** A ticker tagged `M1 + OVERHEAT` is presented identically to a ticker tagged `M1` clean — the user has no structural cue that the first one already burned its move.
2. **Lost setups.** When a strong ticker enters a healthy multi-week base, momentum drops below the pre-filter and it disappears from the scanner. The base — often the best entry zone — is invisible.

Phase A fixes both by maintaining a per-ticker daily state machine that lives independently of whether the ticker passes today's momentum filter.

## 2. Scope

### In scope

- A new state machine evaluating every ticker in the *active set* daily.
- A persistent ticker-keyed snapshot history + a separate transition event log.
- A new `lifecycle_us.html` / `lifecycle_kr.html` report page.
- A daily Telegram lifecycle brief.
- Extension of `fetch_market_data.py` with `ema9`, `ema21`, `ema65`, `ema65_slope_5d`.

### Out of scope (explicitly deferred)

- Market regime classification → Phase B.
- Sector heat dashboard → Phase B.
- Position sizing, multi-stage entry, initial stop → Phase C.
- Forward-return / R-multiple / win-rate analysis → Phase D.
- Composite entry-quality scores. Forbidden permanently.
- Auto-trading. Forbidden permanently.

### Integration boundaries

- `signal_judge.py` is **not modified**. Its mean-reversion BUY/EXIT logic on portfolio + SP100/ETF/KOSPI scanners stays as-is.
- `momentum_signal.py` is **not modified**. Phase A only *reads* its M1/M2/M3 output to seed the active set.
- `portfolio.md` is **read-only**. Held tickers are excluded from the active set; lifecycle tracks unheld names only.

## 3. Active set definition

The active set is the universe over which lifecycle states are evaluated each trading day.

```
active_set(today) = {
  ticker  |  ( ticker passed M1/M2/M3 within last 14 calendar days
              OR  ticker.setup_state != BROKEN within last 10 calendar days )
            AND  ticker NOT IN portfolio.md
}
```

The parentheses are part of the spec — the portfolio exclusion applies to *both* recruitment paths.

Two evaluations exist independently — `active_set_us` (sourced from US momentum scanner) and `active_set_kr` (sourced from KR momentum scanner).

**Rationale:** the second clause keeps a ticker in scope after it leaves momentum's pre-filter, because the most actionable transitions (EXTENDED → PULLBACK → CONFIRMED) often happen *after* the discovery flag drops. The first clause re-introduces tickers that climb back into momentum after a long absence.

**First-run bootstrap:** when `lifecycle_history_*.json` does not exist, seed the active set from the most recent N=14 days of `momentum_history_*.json` (M1/M2/M3 hits) and pull a 200-day price window for each via yfinance to bootstrap EMA9/21/65 calculations.

Note on calendar vs trading days: the implementation uses calendar-day
arithmetic (no trading-calendar dependency). Over long weekends this is
slightly tighter than the original spec wording but the active set
recomputes daily and only requires ANY ONE recent qualifying day in the
window — so the practical impact is minimal.

## 4. State machine

### 4.1 setup_state evaluation order (deterministic precedence)

States are evaluated in this strict order; the first matching state wins. This precedence is part of the spec — Golden tests assert it.

```
1. BROKEN          (kill switch — overrides everything)
2. EXTENDED        (still in trend but too far gone for entry)
3. BASE_FORMING    (compression — most-actionable shape)
4. PULLBACK        (textbook EMA9 dip)
5. TREND_OK        (default healthy uptrend)
```

If none match, the ticker fails out of the active set's "in-trend" branch (BROKEN catches the rest).

### 4.2 setup_state definitions

```python
TREND_OK:
    ema9 > ema21 > ema65
    AND ema65_slope_5d > 0

    Note: an earlier draft also required `close > ema21`. That gate was
    dropped during implementation — a healthy uptrend with a brief
    intra-day dip below ema21 (but above ema65) still belongs in
    TREND_OK. The PULLBACK predicate's separate `close >= ema21` guard
    naturally rejects such tickers from being misclassified as PULLBACK.

PULLBACK:
    TREND_OK conditions hold
    AND abs(close - ema9) / ema9 <= 0.03    # within 3% of EMA9
    AND close >= ema21                        # but holding above EMA21

BASE_FORMING:
    TREND_OK conditions hold
    AND days_sideways in [5, 15]              # consolidation window
    AND atr14_pct_5d_avg < atr14_pct_20d_avg  # volatility contraction
    AND volume_5d_avg < volume_20d_avg * 0.85 # volume dry-up
    AND ema21_slope_5d > 0                    # medium-term trend still rising
                                              # — distinguishes healthy compression from dead sideways

EXTENDED:
    ema9 > ema21 > ema65                      # alignment intact
    AND distance_from_ema9_pct > 0.12         # >12% above EMA9
    AND rsi14 > 72                            # AND overbought (combo, not single condition)

BROKEN:
    ema21 < ema65
    OR close < ema65
```

**Notes on definitions:**

- BROKEN does NOT include `ema9 < ema21` — that condition fires on every healthy pullback and would falsely kill good setups. Demotion only happens when the *medium-term* structure breaks (ema21<ema65) or when price loses the long-term filter (close<ema65).
- EXTENDED requires *both* distance and overbought RSI. High-volatility names (SOXL, IONQ, CRCL) have natural 12% EMA9 distance and would be wrongly tagged otherwise.
- `days_sideways` is computed as: max consecutive trading days where `(high - low) / median_price <= 0.08` for the rolling window.

### 4.3 trigger_state evaluation

trigger_state has exactly three values: `WAIT / EARLY_TRIGGER / CONFIRMED_TRIGGER`. It is only evaluated when `setup_state ∈ {PULLBACK, BASE_FORMING}`. For `TREND_OK / EXTENDED / BROKEN`, trigger_state is forced to `WAIT`.

```python
WAIT:
    default — no trigger event detected

EARLY_TRIGGER:
    (yesterday_close <= ema9 AND today_close > ema9)   # EMA9 reclaim
    OR today_high > yesterday_high                      # prior-day-high break

CONFIRMED_TRIGGER:
    EARLY_TRIGGER conditions hold
    AND volume_ratio_20d >= 1.2
    AND today_close >= today_high * 0.8 + today_low * 0.2   # closed in upper 20% of day's range
```

**Trigger failure is NOT a trigger_state.** A failed CONFIRMED is detected and surfaced as a `FAILED_BREAKOUT` risk_tag (§4.5) and a `FAILED_BREAKOUT` transition event (§5.3) — both derived independently from yesterday's snapshot. This keeps trigger_state monotonic in the entry direction (WAIT → EARLY → CONFIRMED) and avoids ambiguity in `trigger_age_days` and expectancy queries.

The next day's trigger_state always re-evaluates from scratch — usually returning to WAIT, sometimes back to EARLY if the ticker recovers. There is no cooldown that blocks future triggers.

### 4.4 entry_decision

Decision is the user-facing layer derived from setup + trigger:

```python
ENTER_OK:  setup ∈ {PULLBACK, BASE_FORMING} AND trigger == CONFIRMED_TRIGGER
EARLY:     setup ∈ {PULLBACK, BASE_FORMING} AND trigger == EARLY_TRIGGER
STAGING:   setup == TREND_OK AND trigger == WAIT
AVOID:     setup ∈ {EXTENDED, BROKEN}
           OR FAILED_BREAKOUT in risk_tags
```

`evaluate_decision()` accepts `regime=None` parameter. In Phase A this is unused. Phase B will populate it; the function signature is the integration hook.

### 4.5 risk_tags

Risk tags are derived metadata, not state. Multiple tags can attach simultaneously.

| Tag | Condition |
|---|---|
| `OVERHEAT` | `rsi14 >= 80` |
| `PARABOLIC` | 1-day return ≥ 8% AND volume_ratio ≥ 2.0 |
| `EXTENDED` | matches setup_state EXTENDED criteria (mirrored, redundant by design — easier to query) |
| `FAILED_BREAKOUT` | yesterday's trigger_state == CONFIRMED_TRIGGER AND today_close < ema9 |

`FAILED_BREAKOUT` is computed independently each day by inspecting yesterday's snapshot — it is **not** a derivation of any current trigger_state value (since trigger_state has only 3 values, all forward-looking). When fired, it both attaches to today's risk_tags array and emits a `FAILED_BREAKOUT` transition event (§5.3). It naturally lasts only one day — yesterday's CONFIRMED is gone after that.

An optional strict variant (`AND today_close < yesterday_low`) is gated by `FAILED_BREAKOUT_REQUIRE_BELOW_PRIOR_LOW` in lifecycle_config.py, defaulting to `False` for Phase A. Phase D measures whether the strict form gives better expectancy.

### 4.6 Derived fields (not stored — recomputed on read)

These three appear in the UI but are NOT in the snapshot schema. They are computed by walking the ticker's snapshot history at read time:

- `setup_streak`: consecutive days with same `setup_state`
- `days_in_pullback`: consecutive days with `setup_state ∈ {PULLBACK, BASE_FORMING}`
- `trigger_age_days`: days since `trigger_state` last became EARLY or CONFIRMED (0 = today)

**Future split (deferred — not implemented in Phase A):** Phase D may need to distinguish `confirmed_age_days` (days since last CONFIRMED only) from `early_age_days` (days since last EARLY only) for finer expectancy queries — e.g., "Is freshness more important for CONFIRMED than EARLY?". Both are derivable from the same snapshot history; the split happens in derived-field code, not in the schema. Phase A ships only `trigger_age_days`; the others are added later if expectancy data justifies the split.

Storing these would create denormalized data that drifts during backfills. Computing on read is cheap and stays correct.

## 5. Data model

### 5.1 Snapshot schema (per ticker per day)

```json
{
  "date": "2026-05-08",
  "setup": "PULLBACK",
  "trigger": "WAIT",
  "decision": "STAGING",
  "raw": {
    "close": 181.22,
    "high": 183.50,
    "low":  179.10,
    "ema9":  180.00,
    "ema21": 175.00,
    "ema65": 160.00,
    "dist_ema9_pct":  0.68,
    "dist_ema21_pct": 3.55,
    "volume_ratio":   0.85,
    "atr_pct":        3.20,
    "sector": "Technology",
    "risk_tags": []
  }
}
```

**Why these and not more:**

- `close/high/low` enable post-hoc forward returns + MAE/MFE for Phase D.
- `ema9/21/65` allow re-deriving `dist_*` if the formula ever changes (defense against silent breakage).
- `dist_ema9_pct / dist_ema21_pct` are stored even though derivable from EMAs — saves CPU on reads, and lets Phase D compare expectancy across distance bands without reloading raw EMAs.
- `volume_ratio / atr_pct` are needed for compression analysis without re-fetching.
- No EMA50, EMA200, MACD, RSI in raw — they're available in `screenshots/market_data_<DATE>.json` if needed; redundant storage is avoided.

### 5.2 Lifecycle history file structure

```json
{
  "schema_version": "1.0.0",
  "generator_version": "lifecycle_phase_a/0.1.0",
  "last_updated": "2026-05-08T16:30:00-05:00",
  "tickers": {
    "NVDA": {
      "first_seen": "2026-04-15",
      "last_seen":  "2026-05-08",
      "snapshots": [
        { "date": "2026-04-15", "setup": "TREND_OK", ...},
        { "date": "2026-04-16", "setup": "EXTENDED", ...},
        ...
      ]
    },
    "PLTR": { ... }
  },
  "transitions": [
    {
      "event_id": "NVDA_2026-05-08_SETUP_CHANGE_v1",
      "date": "2026-05-08",
      "ticker": "NVDA",
      "event": "SETUP_CHANGE",
      "from": "EXTENDED",
      "to": "PULLBACK"
    }
  ]
}
```

**Versioning:**
- `schema_version` follows semver. Breaking changes to the snapshot or transition shape bump the major version.
- `generator_version` records which `lifecycle_signal.py` revision wrote the file. Useful when rules change and we want to know whether a snapshot was produced under the new or old logic.

**Two files, never one:**
- `history/lifecycle_history_us.json` — sourced from US momentum + price feed
- `history/lifecycle_history_kr.json` — sourced from KR momentum + price feed
- They never share state. KR tickers go only into the KR file.

### 5.3 Transition events

Five event types are written to the `transitions` array. **Only meaningful regime changes** — raw value drift is never a transition.

| Event | Triggered when |
|---|---|
| `SETUP_CHANGE` | today's setup_state differs from yesterday's |
| `TRIGGER_CHANGE` | today's trigger_state differs from yesterday's |
| `DECISION_CHANGE` | today's entry_decision differs from yesterday's |
| `FAILED_BREAKOUT` | independent detection (§4.5 condition) — yesterday's CONFIRMED + today's close below EMA9. Emitted as its own event for direct Phase D queries; not derived from TRIGGER_CHANGE. |
| `RISK_ESCALATION` | risk_tags newly contains EXTENDED (i.e., not present yesterday) |

Risk_tag changes other than EXTENDED entry (e.g., OVERHEAT toggle) are **not** transitions. They're descriptive, not lifecycle.

`event_id` format: `{ticker}_{date}_{event}_v1`. The `_v1` suffix is for future schema evolution (e.g., if we split events differently, old IDs remain unique).

### 5.4 Retention

- Both files are **never truncated** during normal operation.
- Once per year (manual operation), an offline script can move snapshots older than 1 year into `history/archived/lifecycle_history_us_<YEAR>.json`. The active file keeps the most recent year for fast read.
- Phase D queries can read both active + archived files transparently.

Estimated size: ~200 active tickers × 250 trading days × ~250 bytes/snapshot ≈ 12 MB/year. GitHub-friendly.

## 6. File structure

### 6.1 New files

| File | Responsibility |
|---|---|
| `lifecycle_config.py` | All thresholds with rationale comments. Single source of truth. |
| `lifecycle_signal.py` | `evaluate_setup_state()` / `evaluate_trigger_state()` / `evaluate_decision()` / `compute_risk_tags()` / `process_universe()` entry point |
| `lifecycle_history.py` | JSON I/O, bootstrap from yfinance on first run, soft-archive, active_set computation |
| `lifecycle_report.py` | `generate_lifecycle_pages(us_result, kr_result)` Jinja2 rendering |
| `templates/lifecycle_us.html` | US lifecycle page |
| `templates/lifecycle_kr.html` | KR lifecycle page (same template, different data) |
| `tests/test_lifecycle_config.py` | Threshold sanity + rationale-comment-present test |
| `tests/test_lifecycle_signal.py` | State machine unit tests + precedence tests |
| `tests/test_lifecycle_history.py` | Bootstrap, archival, derived-field reconstruction tests |
| `tests/test_lifecycle_golden.py` | 6 named scenarios (see §9) — regression contract |
| `tests/test_lifecycle_e2e.py` | Smoke test wiring through pipeline |

### 6.2 Modified files

| File | Change |
|---|---|
| `fetch_market_data.py` | Add `ema9`, `ema21`, `ema65`, `ema21_slope_5d`, `ema65_slope_5d` per ticker. Compute from existing 200d price window. |
| `pipeline.py` | New Step 4c4 (US lifecycle), Step 4c5 (KR lifecycle) — independent failure isolation |
| `report_generator.py` | `generate_report()` accepts `lifecycle_result` arg; main report nav gets `→ Lifecycle US/KR` link |
| `telegram_sender.py` | `send_lifecycle_brief(us, kr, base_url, date_str)` |
| `generate_site.py` | Copy `lifecycle_*.html` into `deploy/` (mirror existing `portfolio_stops_*.html` pattern) |
| `.github/workflows/daily-report.yml` | Restore `history/lifecycle_history_*.json` from gh-pages branch on workflow start |
| `CLAUDE.md` | Register the plan under "진행 중인 계획" |

### 6.3 New runtime artifacts

```
history/lifecycle_history_us.json
history/lifecycle_history_kr.json
reports/lifecycle_us_<DATE>.html
reports/lifecycle_kr_<DATE>.html
```

## 7. Pipeline integration

```
... (existing steps) ...

Step 4c2  (existing) — momentum_scanner US/KR
Step 4c3  (existing) — portfolio stop signal me
Step 4c4  (NEW)     — lifecycle US:
    1. Compute active_set_us from momentum_history_us + last 10d lifecycle setups
    2. For each ticker: fetch_market_data already produced today's indicators
    3. evaluate_setup_state → evaluate_trigger_state → evaluate_decision → risk_tags
    4. Append snapshot to lifecycle_history_us.json
    5. Compute transitions vs yesterday's snapshots; append to transitions log
Step 4c5  (NEW)     — lifecycle KR (same shape, KR data)
Step 5d   (existing) — portfolio stop signal wife
Step 5    (existing) — telegram + reports
                         + send_lifecycle_brief(us, kr, ...)
                         + generate_lifecycle_pages(us, kr)
```

**Failure isolation:** Step 4c4 / 4c5 failures must not block Step 5 (existing portfolio reports). Wrap in try/except logging at pipeline level, same pattern as Step 4c3.

## 8. Configuration with rationale

All thresholds live in `lifecycle_config.py`. Every value carries a rationale comment. Sample:

```python
# lifecycle_config.py

LIFECYCLE_VERSION = "lifecycle_phase_a/0.1.0"

# ── EMA structure ──────────────────────────────────────
EMA_FAST   = 9   # short-term momentum; matches existing momentum_scanner conventions
EMA_MEDIUM = 21  # medium-term swing support; standard institutional reference
EMA_LONG   = 65  # long-term trend filter
                 # 65 chosen over 50 (too common, less differentiation) and 75 (too slow for growth names)
                 # Roughly 13 weeks — aligns with quarterly earnings rhythm
EMA_LONG_SLOPE_WINDOW = 5   # ema65 must have positive slope over 5 trading days for TREND_OK
EMA_MEDIUM_SLOPE_WINDOW = 5 # ema21 slope window for BASE_FORMING — same length, different EMA

# ── PULLBACK ───────────────────────────────────────────
PULLBACK_MAX_DIST_FROM_EMA9 = 0.03
# 3% chosen because:
#   - typical strong-trend pullback range in US large-cap growth (NVDA/PLTR/MSFT)
#   - tighter (1-2%) misses healthy intraday wicks
#   - looser (5%+) starts admitting weak structures
#   - validated against representative pullback samples; revisit in Phase D

# ── BASE_FORMING ───────────────────────────────────────
BASE_FORMING_DAYS_MIN = 5
BASE_FORMING_DAYS_MAX = 15
# 5-15 day window covers VCP-style bases without admitting multi-month dead zones.
# Anything <5d is just noise; >15d usually means trend has aged out.

BASE_RANGE_MAX_PCT = 0.08
# (high-low)/median_price ≤ 8% over the sideways window
# Picked as roughly 1.5x typical large-cap ATR — admits slow consolidations,
# rejects choppy ranges where price actually went somewhere.

BASE_VOL_CONTRACTION_RATIO = 0.85
# 5d avg volume must be < 85% of 20d avg
# Tighter (e.g. 0.7) is rare and too restrictive; looser (0.95) admits non-contractions.

# ── EXTENDED ───────────────────────────────────────────
EXTENDED_DIST_FROM_EMA9 = 0.12  # >12% above EMA9
EXTENDED_RSI_MIN = 72            # AND RSI14 > 72 — both required (AND, not OR)
# 12% alone wrongly tags high-vol names (SOXL/IONQ/CRCL) where 12% extension is normal.
# RSI 72 chosen below traditional 80 overbought — by 80 the move is nearly over;
# 72 catches earlier exhaustion characteristic of growth-name climaxes.

# ── BROKEN ─────────────────────────────────────────────
# Definition: ema21 < ema65 OR close < ema65
# Note: ema9 < ema21 is intentionally NOT included — it triggers on every healthy
# pullback. BROKEN should require medium-term structure failure, not normal noise.

# ── Trigger ────────────────────────────────────────────
TRIGGER_CONFIRM_VOL_RATIO_MIN = 1.2
# 1.2x avg20 — modest threshold to avoid false positives without being so strict
# that most legitimate triggers fail. Higher (1.5x) misses many real CONFIRMED entries
# in normal-volume regimes.

TRIGGER_CONFIRM_CLOSE_HIGH_RATIO = 0.8
# Close must be in upper 20% of day's range:
# close >= today_high * 0.8 + today_low * 0.2
# Rejects gap-up-then-fade patterns (the classic exhaustion shape).

FAILED_BREAKOUT_REQUIRE_BELOW_PRIOR_LOW = False
# Controls the FAILED_BREAKOUT risk_tag detection (§4.5).
# False = loose form (close < ema9 only) — Phase A default.
# True  = strict form (also requires close < yesterday_low).
# Phase D measures whether the strict form gives better expectancy. Toggle there, not here.

# ── Active set ─────────────────────────────────────────
ACTIVE_M123_LOOKBACK_DAYS = 14
ACTIVE_NONBROKEN_LOOKBACK_DAYS = 10
# 14d momentum lookback covers the typical EXTENDED→PULLBACK→TRIGGER cycle.
# 10d non-broken lookback ensures recently-faded names stay in scope long enough
# to capture a base, but drop out before zombie tickers accumulate.

# ── Risk tags ──────────────────────────────────────────
RISK_OVERHEAT_RSI = 80
RISK_PARABOLIC_RET_1D = 0.08
RISK_PARABOLIC_VOL_RATIO = 2.0
```

The test `test_lifecycle_config.py` includes a check that every threshold has at least one comment line within 5 lines above its definition. This forces rationale to stay attached as values evolve.

## 9. Golden test scenarios

`tests/test_lifecycle_golden.py` defines the following named scenarios. Each is a synthetic price history that drives a specific transition path. They are the regression contract — any rule change that breaks a Golden test must be deliberate and the test file updated in the same commit.

| # | Name | Setup | Expected sequence |
|---|---|---|---|
| 1 | `cooling_off` | Strong uptrend that runs to EMA9 distance >12% with RSI>72, then pulls back into 3% band | `EXTENDED → TREND_OK → PULLBACK` |
| 2 | `clean_entry` | Healthy trend → 3-day pullback → EMA9 reclaim with 1.5x volume + close in top 20% | `TREND_OK → PULLBACK → EARLY_TRIGGER → CONFIRMED_TRIGGER` |
| 3 | `failed_breakout` | Same as #2 through CONFIRMED, then next day close drops below EMA9 | yesterday CONFIRMED, today trigger_state back to WAIT, FAILED_BREAKOUT risk_tag set, FAILED_BREAKOUT transition event emitted |
| 4 | `structure_break` | Trend fades; ema21 crosses below ema65 | `TREND_OK → BROKEN` (skips intermediate states — BROKEN takes precedence) |
| 5 | `weak_volume` | PULLBACK + EMA9 reclaim but volume_ratio = 0.9 (below 1.2 threshold) | `PULLBACK → EARLY_TRIGGER` (does NOT advance to CONFIRMED) — verifies volume gate is enforced |
| 6 | `gap_up_exhaustion` | Big gap up, today_high > yesterday_high, but close in lower half of day's range | trigger stays at `WAIT` despite price-action criteria — verifies close-in-upper-20% gate |

Additional non-Golden unit tests cover:
- `setup_state` precedence (BROKEN beats EXTENDED beats BASE_FORMING etc.)
- Derived field reconstruction (setup_streak / days_in_pullback / trigger_age_days from synthetic history)
- Active set computation with the ex-portfolio rule
- Schema versioning round-trip (read v1.0.0, write v1.0.0)

## 10. UI specification

### 10.1 Page sections (in render order)

```
[1] MARKET STATE   — Phase A placeholder
    "Market regime classifier coming in Phase B."
    Static block. No live data this phase.

[2] ACTION PANEL   — colored decision cards
    🟢 ENTER_OK   (count, list of tickers)
    🟡 EARLY      (count, list)
    ⚪ STAGING    (count, list — collapsed by default)
    🔴 AVOID      (count, list — collapsed by default)

[3] 🆕 NEW CONFIRMED TODAY
    Subset of ENTER_OK where trigger_age_days == 0.
    Most actionable section. Always visible at top of body.

[4] STATE TRANSITIONS (last 5 trading days)
    Chronological log of SETUP_CHANGE / TRIGGER_CHANGE / FAILED_BREAKOUT events
    Format: "2026-05-08  NVDA  EXTENDED → PULLBACK"
    Limit ~50 entries; older accessible via JSON history.

[5] MAIN TABLE  (active set, sorted by ENTRY MATURITY)
    Sort order: ENTER_OK → EARLY → STAGING → EXTENDED → BROKEN
    Within ENTER_OK: by trigger_age_days ascending (newest first)
    Within EARLY:    by volume_ratio descending
    Within STAGING:  by setup_streak descending (longest healthy first)

    Columns:
      Ticker | Sector | Setup | Trigger | Decision | trigger_age
            | dist_ema9% | dist_ema21% | vol_ratio | atr% | days_in_pullback | setup_streak | risk_tags

    BROKEN rows in this table are *hidden*. They appear in section [6].

[6] FAILED / BROKEN  (collapsed by default; toggle to expand)
    Purpose: failure data is preserved for Phase D expectancy analysis.
    Same columns as [5]. Sorted by date BROKEN was first entered.
```

### 10.2 Phase B/C placeholders in UI

- Section [1] explicitly labels itself "Phase B placeholder" so the user knows new info is coming.
- Inside each ENTER_OK card, a small footer: `Recommended size: TBD — Phase C`. Italic/grey.

### 10.3 Layout mirroring portfolio_stops.html

The lifecycle page reuses the visual pattern of `portfolio_stops.html` (Hero → Summary cards → Detail sections → Footer) so the user navigates consistently between risk and entry pages.

## 11. Telegram brief

`send_lifecycle_brief(us_result, kr_result, base_url, date_str)` produces a single message:

```
[Lifecycle Brief — 2026-05-08]

🇺🇸 US
🆕 New CONFIRMED (3): NVDA / PLTR / HOOD
🟢 ENTER_OK total: 7
🟡 EARLY: 12
🔴 FAILED_BREAKOUT: 2 (TSLA, SMCI)
🔗 https://.../lifecycle_us_2026-05-08.html

🇰🇷 KR
🆕 New CONFIRMED (1): 005930.KS
🟢 ENTER_OK total: 4
🟡 EARLY: 6
🔴 FAILED_BREAKOUT: 0
🔗 https://.../lifecycle_kr_2026-05-08.html
```

Sent once per day after the pipeline completes, alongside (not replacing) the existing portfolio risk summary.

**Empty-section handling:** if a category has zero tickers, the line is omitted (not "🟢 ENTER_OK total: 0"). If both US and KR are empty, the brief itself is suppressed — the user already knows from the existing portfolio brief that the pipeline ran.

## 12. Risk and rollback

### 12.1 Risk: lifecycle history file corruption

Mitigation: every write goes to `lifecycle_history_us.json.tmp` first, then atomic rename. On read failure, the pipeline logs and continues with an empty history (no daily blocker), but a non-zero exit code surfaces in the workflow.

### 12.2 Risk: yfinance bootstrap on first run is slow

Mitigation: bootstrap only runs once. Subsequent days append a single snapshot per ticker. Rate-limit retries reuse the existing `_download_with_retry` helper from `fetch_market_data.py`.

### 12.3 Risk: active set explodes

Mitigation: a hard ceiling of 500 active tickers. If exceeded, log a warning and truncate to the 500 most recently-active (last setup_state evaluation date). This protects against a runaway state where lifecycle keeps tracking dead tickers.

### 12.4 Rollback procedure

If Phase A is broken in production:
1. Comment out Step 4c4 / 4c5 in `pipeline.py`.
2. Skip `send_lifecycle_brief()` in Step 5.
3. The lifecycle page disappears; everything else unaffected.
4. `lifecycle_history_*.json` files are preserved for later debugging.

No data migration is required to roll back.

## 13. Acceptance criteria

The phase is "done" when ALL of the following hold:

1. `pytest tests/test_lifecycle_*.py` — green.
2. Pipeline runs end-to-end on a real trading day producing `lifecycle_us_<DATE>.html` and `lifecycle_kr_<DATE>.html` without errors.
3. `lifecycle_history_us.json` accumulates ≥ 5 days of snapshots for ≥ 50 tickers.
4. At least one transition of each major event type (SETUP_CHANGE, TRIGGER_CHANGE, FAILED_BREAKOUT) appears in the transitions log.
5. Telegram brief delivers correctly with the "🆕 New CONFIRMED" section populated on at least one day.
6. The 6 Golden scenarios pass deterministically.
7. signal_judge and momentum_scanner outputs are byte-identical to pre-Phase-A baselines on the same input data.

Criterion #7 is the safety net: lifecycle is purely additive. If it changes the existing systems' output, the integration is wrong.

## 14. Open questions (deferred to plan or implementation)

- **Bootstrap edge case:** what happens if a ticker is in momentum_history_us but yfinance returns an error during bootstrap? Provisional answer: skip and log; ticker re-enters next day if still relevant.
- **First-run UX:** the very first lifecycle page will have empty `setup_streak` and `days_in_pullback` for all tickers. Acceptable? Provisional answer: yes — derived fields show "—" until enough history accumulates (≥ 2 days).
- **Time zone for date stamps:** snapshots use US Eastern date for both US and KR pages? Or KR uses Asia/Seoul date? Provisional answer: each market uses its own local close date; this means US and KR pages can show different "today" stamps when one is mid-session — document this in the page footer.
- **Holiday handling:** if no US trading day occurred today (holiday), Step 4c4 should write nothing rather than duplicate yesterday's snapshot. The pipeline already detects market-closed days via existing `is_market_open_us()`; reuse it.
