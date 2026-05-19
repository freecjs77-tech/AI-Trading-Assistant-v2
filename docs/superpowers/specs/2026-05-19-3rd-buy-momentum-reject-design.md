# 3rd_BUY MACD hist Momentum Reject Filter — Design Spec

- **Date**: 2026-05-19
- **Status**: Design (approved through brainstorm, ready for implementation plan)
- **Strategy version**: v5.3e (additive — no schema or history changes)
- **Scope**: Add a **negative momentum filter** to Growth 3rd_BUY and ETF 3rd_BUY. When `macd_hist_trend == "decreasing_2d"`, reject 3rd_BUY (fall through to lower tier). Implemented as a PARAMS-toggleable reject clause matching the existing RSI>75 reject pattern.
- **Out of scope**:
  - Growth 2nd_BUY momentum condition (already `increasing_2d` strict — **untouched**)
  - ETF 2nd_BUY (Pick 3/4) — untouched
  - 1st_BUY logic — untouched
  - Exit / TAKE_PROFIT / TOP_SIGNAL — untouched
  - History schema, cache keys, Telegram brief format — untouched
  - Backtest tuning of the threshold (tracked separately if needed)

---

## 1. Problem Statement

Current Growth 3rd_BUY conditions (signal_judge.py:274–314):
- `price > MA20` AND
- `MACD > 0` AND `MACD > signal` (골든크로스) AND
- `volume_ratio >= 1.5x` AND
- `RSI > 55`
- Reject: `RSI > 75`

Current ETF 3rd_BUY conditions (signal_judge.py:476–502):
- `price > MA20` AND
- `RSI > 55` AND
- `MACD > 0` AND `MACD > signal`
- Reject: `RSI > 70` (entry_etf.reject_rsi)

Both tiers describe the **state** of a trend (above MA20, MACD bullish, RSI strong) but neither asks whether the trend's momentum is **still expanding or already decelerating**. The `macd_hist_trend` field (computed in fetch_market_data.py:249, values: `increasing_2d` / `decreasing_2d` / `mixed` / `N/A`) carries exactly this information but is unused by 3rd_BUY logic.

**Observed failure mode**: Late-stage uptrends where price is still above MA20 and MACD remains positive, but the histogram has been compressing for 2 consecutive days, still fire fresh 3rd_BUY signals. This generates new entry suggestions precisely as the move loses thrust — the opposite of the 3rd_BUY mandate ("추세 확정").

**Goal**: Reject 3rd_BUY only when momentum is **provably decelerating** (`decreasing_2d`), while preserving all other firings. No re-tuning of existing thresholds.

---

## 2. Architectural Principles

### Principle 1 — Negative filter, not positive gate
This is not "buy when momentum is great." It is **"don't buy when momentum has clearly stalled."** Three of four possible `macd_hist_trend` values pass:

| `macd_hist_trend` | 3rd_BUY result | Rationale |
|---|---|---|
| `increasing_2d` | ✅ pass | Strict acceleration — ideal |
| `mixed` | ✅ pass | Noise tolerated — no clear deceleration |
| `N/A` | ✅ pass | Insufficient data ≠ deceleration (new listings, early window) |
| `decreasing_2d` | ❌ reject | Clear 2-day compression — defer entry |

Rejecting only `decreasing_2d` is the minimum-intervention change: it removes a small, identifiable failure mode without re-scoring the rest of the universe.

### Principle 2 — 3rd_BUY shifts from state detector toward momentum quality detector
Prior to this change, 3rd_BUY answers *"is the trend bullish?"*. After this change, 3rd_BUY answers *"is the trend bullish AND not visibly slowing?"*. Documented in strategy.md as:

> 3rd_BUY는 단순 강세 상태가 아니라 momentum persistence / re-acceleration을 요구한다.

### Principle 3 — Pattern consistency with existing reject clauses
Implement as a `_p()`-configurable reject mirroring the existing Growth `rsi_reject: 75` and ETF `reject_rsi: 70`. Same code shape, same display treatment (`[거부] ...` gate label), same trivial rollback path.

### Principle 4 — Future tuning friendliness
PARAMS keys are named so adjacent variants can be added without renaming:
- `reject_decreasing_hist: true` (this spec)
- Future: `reject_mixed_hist`, `require_increasing_hist`, `reject_negative_hist` etc.

### Principle 5 — Display transparency
Operators must be able to see *why* a stock with apparently strong conditions (MA20 위, MACD>0, RSI 60) ended up in WATCH/HOLD instead of 3rd_BUY. The reject must surface in the report's condition table — not just suppress the signal silently. Otherwise the system looks random.

---

## 3. Design

### 3.1 Decision logic — Growth 3rd_BUY

File: `signal_judge.py`, function `_check_entry_growth` (around line 274–314).

Add reject check **inside** the 3rd_BUY block, before the ALL-pass return:

```python
# 3rd BUY 추가 거부: MACD hist 2일 감속 (v5.3e momentum quality)
_g3_hist_reject = _p("entry_growth.3rd_buy.reject_decreasing_hist", True)
hist_decel = _g3_hist_reject and macd_hist_trend == "decreasing_2d"
if hist_decel:
    c3.append(("no", "[거부] MACD hist 2일 감속",
               f"MACD hist 2일 연속 감소 — 추세 둔화로 3차 매수 보류예요"))

# 통과 조건에 hist_decel 추가
if all(c[0] == "ok" for c in c3) and not (rsi and rsi > _g3_reject) and not hist_decel:
    return "3rd_BUY", c3
```

Existing 2nd_BUY block (already requires `increasing_2d`) will also reject this stock, so it cascades naturally to 1st_BUY → WATCH/HOLD per the existing fallback chain.

### 3.2 Decision logic — ETF 3rd_BUY

File: `signal_judge.py`, function `_check_entry_etf` (around line 476–502).

Identical pattern, mirrored:

```python
# ETF 3rd BUY 추가 거부: MACD hist 2일 감속
_e3_hist_reject = _p("entry_etf.3rd_buy.reject_decreasing_hist", True)
hist_decel_etf = _e3_hist_reject and macd_hist_trend == "decreasing_2d"
if hist_decel_etf:
    c3.append(("no", "[거부] MACD hist 2일 감속",
               f"MACD hist 2일 연속 감소 — 추세 둔화로 3차 매수 보류예요"))

if all(c[0] == "ok" for c in c3) and not hist_decel_etf:
    return "3rd_BUY", c3
```

(`macd_hist_trend` is already pulled at `_check_entry_etf` entry — line 433, default `""` — and at the Growth entry path. No data-fetch wiring needed.)

### 3.3 Display sections

The report's "3차 매수 조건" sections (`signal_judge.py` lines ~858–896 Growth, ~993–1022 ETF) build a `c3` list shown to the user even when the signal doesn't fire. Both display blocks must mirror the decision-logic change:

- Append the same `[거부] MACD hist 2일 감속` row when `macd_hist_trend == "decreasing_2d"` AND the PARAMS toggle is on.
- Update the section's `gate` field so the reject is rendered with gate styling (matching the existing `[거부] RSI > 75` / `[거부] RSI 75 > 70` patterns):

```python
sections.append({
    "name": f"3차 매수 조건 - {group_label} v2.3",   # bump version label
    "rule": "4개 모두 충족",
    "conditions": c3,
    "met": _count_ok(c3),
    "total": len(c3),
    "gate": _resolve_gate(c3_reject, reject_drop, hist_decel),
})
```

Where `_resolve_gate` picks the first active gate in priority order: `당일 급락` → `RSI > 75` → `MACD hist 2일 감속`. (Implementation may inline the chain — exact form is the plan's call.)

### 3.4 PARAMS additions

File: `strategy_params.json`. Bump `version` to `"5.3e"`. Add toggles:

```json
"entry_growth": {
  ...
  "3rd_buy": {
    "rsi_min": 55,
    "volume_ratio": 1.5,
    "rsi_reject": 75,
    "reject_decreasing_hist": true       // NEW
  }
},
"entry_etf": {
  ...
  "3rd_buy": {
    "rsi_min": 55,
    "reject_decreasing_hist": true       // NEW
  }
}
```

Defaults match the design intent (filter ON). Operators can disable per-track for A/B testing by setting to `false` without touching code.

### 3.5 N/A / data-missing handling

`macd_hist_trend` returns `"N/A"` when fewer than 2 valid hist diffs are available (typically: new listings, post-split data gaps, first days of fetch window). Per Principle 1 and user direction:

- `"N/A"` → **pass** (do not reject). Reason: absence of evidence ≠ evidence of deceleration. Rejecting on `N/A` would cause signal starvation on legitimate new entries.
- `"mixed"` → **pass**. Reason: noisy hist (e.g., up-down-up) is not a clear deceleration signal.
- `""` (empty string — the dict-default if field absent) → **pass**. Treated as data-missing.
- Only the exact string `"decreasing_2d"` triggers reject.

This is enforced by the `== "decreasing_2d"` equality check (not `"decreasing" in ...`).

---

## 4. Documentation updates

### 4.1 `strategy.md`

Add a v5.3e section near the existing v5.3d notes. Include the principle line:

> **v5.3e 3rd_BUY momentum quality reject**: `macd_hist_trend == "decreasing_2d"` 시 Growth/ETF 3rd_BUY 거부. 1일 노이즈에 둔감하고 (increasing_2d/mixed/N/A 모두 통과), `decreasing_2d`만 명확한 deceleration으로 간주. PARAMS `entry_growth.3rd_buy.reject_decreasing_hist` / `entry_etf.3rd_buy.reject_decreasing_hist` (default `true`)로 토글. **철학**: 3rd_BUY는 단순 강세 상태가 아니라 momentum persistence / re-acceleration을 요구한다.

Update the Growth 3rd BUY section (line ~221) and ETF 3rd BUY section (line ~271) condition lists to include the new reject row.

### 4.2 `CLAUDE.md`

Add one line to the "시그널 판정 규칙 (strategy.md v5.3 주요 변경사항)" section:

> - **v5.3e 3rd_BUY momentum reject**: Growth/ETF 3rd_BUY에 `macd_hist_trend == "decreasing_2d"` 거부 필터 추가 · increasing_2d/mixed/N/A 통과 · PARAMS toggle로 롤백 가능 · 2nd_BUY/1st_BUY/Exit 무변경

---

## 5. What does NOT change

Explicit non-changes (to anchor the implementation plan's scope):

| Area | Change? |
|---|---|
| Growth 2nd_BUY (`increasing_2d` strict requirement) | ❌ untouched |
| Growth 1st_BUY (필수 4 ALL: RSI≤45 + 가격<MA20 + hist 2일증가 + DD_52w≤-15%) | ❌ untouched |
| ETF 2nd_BUY (Pick 3/4) | ❌ untouched |
| ETF 1st_BUY | ❌ untouched |
| TOP_SIGNAL / TAKE_PROFIT_1 / TAKE_PROFIT_2 / HOLD | ❌ untouched |
| `signals_history.json` schema | ❌ untouched (signal name unchanged, fields unchanged) |
| `fetch_market_data.py` (data layer) | ❌ untouched (`macd_hist_trend` already computed) |
| Telegram brief format | ❌ untouched (signal string unchanged) |
| Market scanner (SP100, ETF, KOSPI) Entry-only logic | ❌ untouched (scanner already runs the same `_check_entry_*` and would inherit the filter — this is intentional and consistent) |
| Lifecycle / Momentum Scanner / Portfolio Stop signals | ❌ untouched (independent subsystems) |
| Cache invalidation keys | ❌ untouched |

---

## 6. Acceptance criteria

Implementation is complete when:

1. With default PARAMS (`reject_decreasing_hist: true`), a Growth or ETF ticker that previously fired 3rd_BUY and whose `macd_hist_trend == "decreasing_2d"` no longer fires 3rd_BUY (cascades to lower tier via existing logic).
2. With `reject_decreasing_hist: false`, behavior is bit-identical to v5.3d for the affected tickers.
3. The report's "3차 매수 조건" section displays the `[거부] MACD hist 2일 감속` row when the reject is active, even when the section is rendered as part of WATCH/HOLD diagnostic output.
4. Tickers with `macd_hist_trend` of `increasing_2d`, `mixed`, or `N/A` are unaffected.
5. No other signal (1st_BUY, 2nd_BUY, Exit, TOP_SIGNAL, TP1/TP2) changes for any ticker.
6. `strategy_params.json` version bumped to `"5.3e"`.
7. `strategy.md` and `CLAUDE.md` carry the v5.3e note.
8. No history file rows are deleted or schema-changed.

---

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Filter is too aggressive in practice (kills useful 3rd_BUYs at minor pullbacks) | PARAMS toggle off without code change; spec calls this out explicitly |
| `macd_hist_trend` not populated in some code path | Add `d.get("macd_hist_trend", "N/A")` fallback — `"N/A"` passes the filter anyway |
| Display section not updated → operator confusion | Acceptance criterion #3 covers this; reviewer should look at both decision and display blocks |
| Scanner output noticeably thinner (fewer 3rd_BUY candidates surface) | Expected behavior — this is the goal. Note in v5.3e CLAUDE.md line so it's not mistaken for a bug. |

---

## 8. Open questions

None. All decision points (scope, threshold, N/A handling, PARAMS naming, display surface, documentation) were settled during brainstorm.
