# 3rd_BUY MACD hist Momentum Reject Filter — Implementation Plan (v5.3e)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a PARAMS-toggleable reject filter to Growth and ETF 3rd_BUY logic that rejects entry when `macd_hist_trend == "decreasing_2d"`. All other `macd_hist_trend` values (`increasing_2d`, `mixed`, `N/A`, `""`) pass through unchanged. 2nd_BUY / 1st_BUY / Exit / history schema all untouched.

**Architecture:** Mirror the existing `[거부] RSI > 75` reject pattern in `_check_entry_growth` and `_check_entry_etf`. Add a parallel display row + extended `gate` field in `_build_entry_sections_growth` and `_build_entry_sections_etf` so the reject is visible in WATCH/HOLD diagnostic output too. New PARAMS keys default to `true`, allowing instant rollback via `strategy_params.json` without code change.

**Tech Stack:** Python 3.10+, pytest, pandas/numpy already in scope (no new deps). All edits in `signal_judge.py`, `strategy_params.json`, `strategy.md`, `CLAUDE.md`, and a new test file.

**Spec:** [docs/superpowers/specs/2026-05-19-3rd-buy-momentum-reject-design.md](../specs/2026-05-19-3rd-buy-momentum-reject-design.md)

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `tests/test_signal_judge_3rd_buy_hist_reject.py` | Create | Decision-layer + display-layer tests for the new filter |
| `strategy_params.json` | Modify | Bump `version` → `"5.3e"`, add `entry_growth.3rd_buy.reject_decreasing_hist: true` and `entry_etf.3rd_buy.reject_decreasing_hist: true` |
| `signal_judge.py` (lines ~274–314) | Modify | Growth `_check_entry_growth` 3rd_BUY decision — add reject clause |
| `signal_judge.py` (lines ~476–502) | Modify | ETF `_check_entry_etf` 3rd_BUY decision — add reject clause |
| `signal_judge.py` (lines ~858–896) | Modify | Growth `_build_entry_sections_growth` 3rd_BUY display — append reject row + extend `gate` field |
| `signal_judge.py` (lines ~993–1022) | Modify | ETF `_build_entry_sections_etf` 3rd_BUY display — append reject row + extend `gate` field |
| `strategy.md` | Modify | Add v5.3e changelog entry + update Growth/ETF 3rd_BUY condition listings to include the new reject |
| `CLAUDE.md` | Modify | One-line v5.3e bullet in the "시그널 판정 규칙" section |

**Decomposition rationale:** Tests first (one file, all behaviors). Then PARAMS (the toggle). Then 4 mirror-image code changes split into two tasks each (decision + display) per track. Then docs. Each task is independently committable and the test suite stays green between tasks.

---

## Cross-task helpers (referenced below)

**Run a single test:** `pytest tests/test_signal_judge_3rd_buy_hist_reject.py::<test_name> -v`

**Run all tests for this feature:** `pytest tests/test_signal_judge_3rd_buy_hist_reject.py -v`

**Run the full test suite affected by signal_judge:** `pytest tests/ -v -k "not e2e"` (e2e tests pull live data and are slow)

**PARAMS patching idiom for tests** (this is the only way to flip the toggle in-process — `signal_judge.PARAMS` is loaded once at import):

```python
import signal_judge

def _patch_param(monkeypatch, dotted_path: str, value):
    """Set signal_judge.PARAMS[a][b][c] = value via monkeypatch (auto-reverts)."""
    keys = dotted_path.split(".")
    # Deep-copy the relevant subtree so other tests are unaffected
    import copy
    new_params = copy.deepcopy(signal_judge.PARAMS)
    obj = new_params
    for k in keys[:-1]:
        obj = obj.setdefault(k, {})
    obj[keys[-1]] = value
    monkeypatch.setattr(signal_judge, "PARAMS", new_params)
```

---

## Task 1: Write failing decision-layer tests (TDD red phase)

**Files:**
- Create: `tests/test_signal_judge_3rd_buy_hist_reject.py`

The test file covers four decision behaviors (toggle-on reject, toggle-on pass for other trend values, toggle-off pass, ETF mirror) and is written *before* implementation so we see them fail correctly first.

- [ ] **Step 1: Create the test file**

```python
# tests/test_signal_judge_3rd_buy_hist_reject.py
"""v5.3e — 3rd_BUY MACD hist deceleration reject filter tests.

Covers both decision layer (_check_entry_growth / _check_entry_etf) and
display layer (_build_entry_sections_growth / _build_entry_sections_etf).
"""
import sys
import os
import copy
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import signal_judge
from signal_judge import (
    _check_entry_growth,
    _check_entry_etf,
    _build_entry_sections_growth,
    _build_entry_sections_etf,
)


def _patch_param(monkeypatch, dotted_path: str, value):
    """Set signal_judge.PARAMS via monkeypatch (auto-reverts after test)."""
    keys = dotted_path.split(".")
    new_params = copy.deepcopy(signal_judge.PARAMS)
    obj = new_params
    for k in keys[:-1]:
        obj = obj.setdefault(k, {})
    obj[keys[-1]] = value
    monkeypatch.setattr(signal_judge, "PARAMS", new_params)


# ─── Growth fixtures: a ticker that otherwise satisfies 3rd_BUY ALL ────────

def _growth_3rd_buy_base():
    """All four 3rd_BUY ALL conditions satisfied; RSI under 75 reject."""
    return {
        "rsi14": 60.0,
        "ma20": 100.0,
        "price": 105.0,
        "price_vs_ma20": "above",
        "macd": 0.50,
        "macd_signal": 0.20,
        "macd_hist": 0.30,
        "macd_hist_3d": [0.10, 0.20, 0.30],
        "macd_hist_trend": "increasing_2d",
        "volume_ratio": 2.0,
        "change_pct": 1.5,
    }


# ─── Growth decision tests ────────────────────────────────────────────────

def test_growth_3rd_buy_fires_on_increasing_2d():
    """Baseline: increasing_2d trend → 3rd_BUY fires (unchanged behavior)."""
    d = _growth_3rd_buy_base()
    signal, _ = _check_entry_growth(d)
    assert signal == "3rd_BUY"


def test_growth_3rd_buy_rejected_on_decreasing_2d(monkeypatch):
    """v5.3e: decreasing_2d → 3rd_BUY rejected (cascades to 2nd/1st/WATCH)."""
    _patch_param(monkeypatch, "entry_growth.3rd_buy.reject_decreasing_hist", True)
    d = _growth_3rd_buy_base()
    d["macd_hist_trend"] = "decreasing_2d"
    d["macd_hist_3d"] = [0.50, 0.40, 0.30]
    signal, _ = _check_entry_growth(d)
    assert signal != "3rd_BUY", \
        f"Expected fallback, got {signal} — decreasing_2d should block 3rd_BUY"


def test_growth_3rd_buy_passes_on_mixed_trend(monkeypatch):
    """mixed → 3rd_BUY still fires (only decreasing_2d rejects)."""
    _patch_param(monkeypatch, "entry_growth.3rd_buy.reject_decreasing_hist", True)
    d = _growth_3rd_buy_base()
    d["macd_hist_trend"] = "mixed"
    d["macd_hist_3d"] = [0.20, 0.30, 0.25]
    signal, _ = _check_entry_growth(d)
    assert signal == "3rd_BUY"


def test_growth_3rd_buy_passes_on_na_trend(monkeypatch):
    """N/A (data insufficient) → 3rd_BUY still fires (no starvation on new listings)."""
    _patch_param(monkeypatch, "entry_growth.3rd_buy.reject_decreasing_hist", True)
    d = _growth_3rd_buy_base()
    d["macd_hist_trend"] = "N/A"
    signal, _ = _check_entry_growth(d)
    assert signal == "3rd_BUY"


def test_growth_3rd_buy_passes_on_empty_trend(monkeypatch):
    """'' (field absent from dict default) → 3rd_BUY still fires."""
    _patch_param(monkeypatch, "entry_growth.3rd_buy.reject_decreasing_hist", True)
    d = _growth_3rd_buy_base()
    d["macd_hist_trend"] = ""
    signal, _ = _check_entry_growth(d)
    assert signal == "3rd_BUY"


def test_growth_3rd_buy_toggle_off_disables_filter(monkeypatch):
    """reject_decreasing_hist=False → decreasing_2d no longer rejects (v5.3d behavior)."""
    _patch_param(monkeypatch, "entry_growth.3rd_buy.reject_decreasing_hist", False)
    d = _growth_3rd_buy_base()
    d["macd_hist_trend"] = "decreasing_2d"
    d["macd_hist_3d"] = [0.50, 0.40, 0.30]
    signal, _ = _check_entry_growth(d)
    assert signal == "3rd_BUY", \
        "With toggle OFF, decreasing_2d should not block 3rd_BUY"


# ─── ETF fixtures + decision tests ────────────────────────────────────────

def _etf_3rd_buy_base():
    """All ETF 3rd_BUY ALL conditions satisfied; RSI under 70 reject."""
    return {
        "rsi14": 60.0,
        "ma20": 400.0,
        "price": 410.0,
        "price_vs_ma20": "above",
        "macd": 0.80,
        "macd_signal": 0.30,
        "macd_hist": 0.50,
        "macd_hist_3d": [0.20, 0.35, 0.50],
        "macd_hist_trend": "increasing_2d",
        "drawdown_52w_pct": -3.0,
    }


def test_etf_3rd_buy_fires_on_increasing_2d():
    """Baseline ETF: increasing_2d → 3rd_BUY (unchanged)."""
    d = _etf_3rd_buy_base()
    signal, _ = _check_entry_etf(d)
    assert signal == "3rd_BUY"


def test_etf_3rd_buy_rejected_on_decreasing_2d(monkeypatch):
    """v5.3e: ETF decreasing_2d → 3rd_BUY rejected."""
    _patch_param(monkeypatch, "entry_etf.3rd_buy.reject_decreasing_hist", True)
    d = _etf_3rd_buy_base()
    d["macd_hist_trend"] = "decreasing_2d"
    d["macd_hist_3d"] = [0.80, 0.65, 0.50]
    signal, _ = _check_entry_etf(d)
    assert signal != "3rd_BUY"


def test_etf_3rd_buy_passes_on_mixed(monkeypatch):
    _patch_param(monkeypatch, "entry_etf.3rd_buy.reject_decreasing_hist", True)
    d = _etf_3rd_buy_base()
    d["macd_hist_trend"] = "mixed"
    signal, _ = _check_entry_etf(d)
    assert signal == "3rd_BUY"


def test_etf_3rd_buy_passes_on_na(monkeypatch):
    _patch_param(monkeypatch, "entry_etf.3rd_buy.reject_decreasing_hist", True)
    d = _etf_3rd_buy_base()
    d["macd_hist_trend"] = "N/A"
    signal, _ = _check_entry_etf(d)
    assert signal == "3rd_BUY"


def test_etf_3rd_buy_toggle_off_disables_filter(monkeypatch):
    _patch_param(monkeypatch, "entry_etf.3rd_buy.reject_decreasing_hist", False)
    d = _etf_3rd_buy_base()
    d["macd_hist_trend"] = "decreasing_2d"
    signal, _ = _check_entry_etf(d)
    assert signal == "3rd_BUY"
```

- [ ] **Step 2: Run the tests to verify they all fail at first**

Run: `pytest tests/test_signal_judge_3rd_buy_hist_reject.py -v`

Expected: The two **baseline** tests (`test_growth_3rd_buy_fires_on_increasing_2d`, `test_etf_3rd_buy_fires_on_increasing_2d`) **PASS** (current code already supports them). The two **toggle-off** tests (`..._toggle_off_...`) also **PASS** (current code has no filter, behaves as if toggle is off). All **other** tests (`..._rejected_on_decreasing_2d`, `..._passes_on_mixed_trend`, `..._passes_on_na_trend`, `..._passes_on_empty_trend`, ETF equivalents) currently **FAIL** because the existing code returns `"3rd_BUY"` for the `decreasing_2d` case (no filter exists yet).

Note the per-track failure tally: Growth has 1 expected failure (`rejected_on_decreasing_2d`); the `..._passes_on_mixed_trend` and `..._passes_on_na_trend` cases coincidentally pass under current code because the filter is absent (they will continue to pass after implementation). Same for ETF. So we expect exactly **2 failures** in this initial run: the two `rejected_on_decreasing_2d` tests.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_signal_judge_3rd_buy_hist_reject.py
git commit -m "test(signal_judge): add failing tests for v5.3e 3rd_BUY hist reject

Decision-layer tests for Growth and ETF covering: baseline fire,
decreasing_2d reject, mixed/N/A/empty pass-through, and PARAMS
toggle-off behavior. Two tests fail until v5.3e logic lands."
```

---

## Task 2: Add PARAMS keys + version bump

**Files:**
- Modify: `strategy_params.json`

- [ ] **Step 1: Edit `strategy_params.json`**

Change the `version` field from `"5.3b"` to `"5.3e"`. Add `reject_decreasing_hist: true` to both `entry_growth.3rd_buy` and `entry_etf.3rd_buy`.

Final state of the affected sections:

```json
{
  "version": "5.3e",
  "description": "signal_judge.py 판정 임계값. 백테스트 결과 기반으로 조정 가능.",
  ...
  "entry_growth": {
    "reject_rsi": 55,
    "reject_drop_pct": -5.0,
    "1st_buy": {
      "rsi_max": 45,
      "dd_52w_max": -15.0,
      "hist_increase_days": 2,
      "watch_mandatory_min": 3
    },
    "2nd_buy": {
      "rsi_recovery": 35,
      "volume_ratio": 1.5,
      "double_bottom_diff": 3.0
    },
    "3rd_buy": {
      "rsi_min": 55,
      "volume_ratio": 1.5,
      "rsi_reject": 75,
      "reject_decreasing_hist": true
    }
  },
  ...
  "entry_etf": {
    "reject_rsi": 70,
    "1st_buy": {
      "rsi_max": 45,
      "dd_52w_max": -15.0
    },
    "2nd_buy": {
      "rsi_recovery": 42,
      "min_count": 3
    },
    "3rd_buy": {
      "rsi_min": 55,
      "reject_decreasing_hist": true
    }
  },
  ...
}
```

(All other top-level keys unchanged. Show full file as needed; only the three lines above are added.)

- [ ] **Step 2: Verify JSON is still valid**

Run: `python -c "import json; json.load(open('strategy_params.json', encoding='utf-8'))"`
Expected: No output (silent success). If it errors, fix the syntax.

- [ ] **Step 3: Verify tests still have the same red/green tally**

Run: `pytest tests/test_signal_judge_3rd_buy_hist_reject.py -v`
Expected: Same 2 failures as Task 1 Step 2 (decision code not changed yet, just the toggles exist now).

- [ ] **Step 4: Commit**

```bash
git add strategy_params.json
git commit -m "feat(params): add 3rd_buy.reject_decreasing_hist toggles (v5.3e)

Bumps version 5.3b→5.3e. Defaults to true for both Growth and ETF.
Decision-layer code that consumes these toggles lands in the next commit."
```

---

## Task 3: Implement Growth decision-layer reject

**Files:**
- Modify: `signal_judge.py` — inside `_check_entry_growth`, the Growth 3rd_BUY block (around lines 274–314).

- [ ] **Step 1: Locate the existing 3rd_BUY return condition**

The current block ends with this return (around line 313):

```python
    if all(c[0] == "ok" for c in c3) and not (rsi and rsi > _g3_reject):
        return "3rd_BUY", c3
```

The lines immediately preceding it read `_g3_reject` and conditionally append a `[거부] RSI > {_g3_reject}` row.

- [ ] **Step 2: Insert the hist reject block right before the return**

Add the following lines **between** the existing RSI reject append and the final `if all(...)` return:

```python
    # 3rd BUY 추가 거부: MACD hist 2일 감속 (v5.3e momentum quality)
    _g3_hist_filter = _p("entry_growth.3rd_buy.reject_decreasing_hist", True)
    hist_decel = _g3_hist_filter and macd_hist_trend == "decreasing_2d"
    if hist_decel:
        c3.append(("no", "[거부] MACD hist 2일 감속",
                   "MACD hist 2일 연속 감소 — 추세 둔화로 3차 매수 보류예요"))
```

Then modify the return guard to include `not hist_decel`:

```python
    if all(c[0] == "ok" for c in c3) and not (rsi and rsi > _g3_reject) and not hist_decel:
        return "3rd_BUY", c3
```

The exact `Edit` operation: find the line

```
    if all(c[0] == "ok" for c in c3) and not (rsi and rsi > _g3_reject):
        return "3rd_BUY", c3
```

and replace it with

```
    # 3rd BUY 추가 거부: MACD hist 2일 감속 (v5.3e momentum quality)
    _g3_hist_filter = _p("entry_growth.3rd_buy.reject_decreasing_hist", True)
    hist_decel = _g3_hist_filter and macd_hist_trend == "decreasing_2d"
    if hist_decel:
        c3.append(("no", "[거부] MACD hist 2일 감속",
                   "MACD hist 2일 연속 감소 — 추세 둔화로 3차 매수 보류예요"))

    if all(c[0] == "ok" for c in c3) and not (rsi and rsi > _g3_reject) and not hist_decel:
        return "3rd_BUY", c3
```

- [ ] **Step 3: Run the Growth decision tests**

Run: `pytest tests/test_signal_judge_3rd_buy_hist_reject.py -v -k "growth"`

Expected:
- `test_growth_3rd_buy_fires_on_increasing_2d` PASS
- `test_growth_3rd_buy_rejected_on_decreasing_2d` PASS (was failing)
- `test_growth_3rd_buy_passes_on_mixed_trend` PASS
- `test_growth_3rd_buy_passes_on_na_trend` PASS
- `test_growth_3rd_buy_passes_on_empty_trend` PASS
- `test_growth_3rd_buy_toggle_off_disables_filter` PASS

All 6 Growth tests green. ETF tests still have 1 failure (`test_etf_3rd_buy_rejected_on_decreasing_2d`).

- [ ] **Step 4: Commit**

```bash
git add signal_judge.py
git commit -m "feat(signal_judge): Growth 3rd_BUY reject on macd_hist decreasing_2d

v5.3e momentum quality filter. PARAMS-toggleable
(entry_growth.3rd_buy.reject_decreasing_hist, default true). Only the
exact 'decreasing_2d' value triggers reject; increasing_2d/mixed/N/A
all pass through. ETF mirror in next commit."
```

---

## Task 4: Implement ETF decision-layer reject

**Files:**
- Modify: `signal_judge.py` — inside `_check_entry_etf`, the ETF 3rd_BUY block (around lines 476–502).

- [ ] **Step 1: Locate the existing ETF 3rd_BUY return condition**

The current block ends with (around line 501):

```python
    if all(c[0] == "ok" for c in c3):
        return "3rd_BUY", c3
```

Note: `_check_entry_etf` already pulls `macd_hist_trend = d.get("macd_hist_trend", "")` at line 433, so no additional data fetch is needed.

- [ ] **Step 2: Insert the hist reject block right before the return**

Find the line

```
    if all(c[0] == "ok" for c in c3):
        return "3rd_BUY", c3
```

(inside `_check_entry_etf` only — there are similar lines elsewhere; the surrounding context is the ETF function defined around line 426)

and replace it with:

```
    # 3rd BUY 추가 거부: MACD hist 2일 감속 (v5.3e momentum quality)
    _e3_hist_filter = _p("entry_etf.3rd_buy.reject_decreasing_hist", True)
    hist_decel_etf = _e3_hist_filter and macd_hist_trend == "decreasing_2d"
    if hist_decel_etf:
        c3.append(("no", "[거부] MACD hist 2일 감속",
                   "MACD hist 2일 연속 감소 — 추세 둔화로 3차 매수 보류예요"))

    if all(c[0] == "ok" for c in c3) and not hist_decel_etf:
        return "3rd_BUY", c3
```

To disambiguate from the same line in `_check_entry_growth`, the Edit's `old_string` must include enough surrounding context to be unique. Use the preceding 5 lines (the ETF block's MACD section) as part of the match:

```python
    if macd is not None and macd_signal_val is not None:
        c3.append(("ok" if macd_c3_ok else "no",
                   "MACD > 0 + 골든크로스",
                   f"MACD {macd:.4f} {'>' if macd_above_zero else '<'} 0, {'>' if macd_golden_etf else '<'} signal {macd_signal_val:.4f}"))
    else:
        c3.append(("no", "MACD > 0 + 골든크로스", "MACD 데이터가 없어요"))
    if all(c[0] == "ok" for c in c3):
        return "3rd_BUY", c3
```

— this block is unique to the ETF function (Growth uses different variable names like `macd_golden_c3`).

- [ ] **Step 3: Run all decision tests**

Run: `pytest tests/test_signal_judge_3rd_buy_hist_reject.py -v`

Expected: All 12 decision-layer tests PASS (6 Growth + 6 ETF). No failures.

- [ ] **Step 4: Sanity-check no other tests broke**

Run: `pytest tests/ -v -k "not e2e"` (skip e2e tests that require live data)

Expected: No new failures introduced. If any unrelated test was already red on master, note it but do not fix it here.

- [ ] **Step 5: Commit**

```bash
git add signal_judge.py
git commit -m "feat(signal_judge): ETF 3rd_BUY reject on macd_hist decreasing_2d

Mirrors Growth v5.3e behavior. PARAMS-toggleable
(entry_etf.3rd_buy.reject_decreasing_hist, default true). Decision
layer complete; display surface updates in next commits."
```

---

## Task 5: Add failing display-layer tests

**Files:**
- Modify: `tests/test_signal_judge_3rd_buy_hist_reject.py` (append at end)

The display section helpers return a list of section dicts each carrying `name`, `rule`, `conditions`, `met`, `total`, and `gate`. The reject must appear in BOTH `conditions` (as a row labeled `[거부] MACD hist 2일 감속`) AND `gate` (so the section header renders with gate styling).

- [ ] **Step 1: Append display-layer tests to the existing test file**

Add the following at the bottom of `tests/test_signal_judge_3rd_buy_hist_reject.py`:

```python
# ─── Display-layer tests ──────────────────────────────────────────────────

def _find_3rd_buy_section(sections):
    """Pick the 3rd_BUY section out of the list (matches by name prefix)."""
    for s in sections:
        if "3차 매수" in s["name"]:
            return s
    raise AssertionError("3rd_BUY section not found in sections list")


def test_growth_display_3rd_buy_no_reject_row_on_increasing(monkeypatch):
    """Baseline display: increasing_2d → no reject row, gate is None."""
    _patch_param(monkeypatch, "entry_growth.3rd_buy.reject_decreasing_hist", True)
    d = _growth_3rd_buy_base()
    sections = _build_entry_sections_growth(d)
    section = _find_3rd_buy_section(sections)
    labels = [c[1] for c in section["conditions"]]
    assert "[거부] MACD hist 2일 감속" not in labels
    assert section["gate"] != "[거부] MACD hist 2일 감속"


def test_growth_display_3rd_buy_shows_reject_row_on_decreasing(monkeypatch):
    """v5.3e display: decreasing_2d → reject row appears AND gate is set."""
    _patch_param(monkeypatch, "entry_growth.3rd_buy.reject_decreasing_hist", True)
    d = _growth_3rd_buy_base()
    d["macd_hist_trend"] = "decreasing_2d"
    sections = _build_entry_sections_growth(d)
    section = _find_3rd_buy_section(sections)
    labels = [c[1] for c in section["conditions"]]
    assert "[거부] MACD hist 2일 감속" in labels, \
        f"Expected reject row in display; got labels: {labels}"
    assert section["gate"] == "[거부] MACD hist 2일 감속"


def test_growth_display_toggle_off_hides_reject_row(monkeypatch):
    """Toggle off → no reject row even when hist is decreasing_2d."""
    _patch_param(monkeypatch, "entry_growth.3rd_buy.reject_decreasing_hist", False)
    d = _growth_3rd_buy_base()
    d["macd_hist_trend"] = "decreasing_2d"
    sections = _build_entry_sections_growth(d)
    section = _find_3rd_buy_section(sections)
    labels = [c[1] for c in section["conditions"]]
    assert "[거부] MACD hist 2일 감속" not in labels


def test_etf_display_3rd_buy_shows_reject_row_on_decreasing(monkeypatch):
    """v5.3e ETF display: decreasing_2d → reject row AND gate set."""
    _patch_param(monkeypatch, "entry_etf.3rd_buy.reject_decreasing_hist", True)
    d = _etf_3rd_buy_base()
    d["macd_hist_trend"] = "decreasing_2d"
    sections = _build_entry_sections_etf(d)
    section = _find_3rd_buy_section(sections)
    labels = [c[1] for c in section["conditions"]]
    assert "[거부] MACD hist 2일 감속" in labels
    assert section["gate"] == "[거부] MACD hist 2일 감속"


def test_etf_display_toggle_off_hides_reject_row(monkeypatch):
    _patch_param(monkeypatch, "entry_etf.3rd_buy.reject_decreasing_hist", False)
    d = _etf_3rd_buy_base()
    d["macd_hist_trend"] = "decreasing_2d"
    sections = _build_entry_sections_etf(d)
    section = _find_3rd_buy_section(sections)
    labels = [c[1] for c in section["conditions"]]
    assert "[거부] MACD hist 2일 감속" not in labels
```

- [ ] **Step 2: Run the display tests and verify they fail correctly**

Run: `pytest tests/test_signal_judge_3rd_buy_hist_reject.py -v -k "display"`

Expected:
- `test_growth_display_3rd_buy_no_reject_row_on_increasing` PASS (no change in baseline)
- `test_growth_display_3rd_buy_shows_reject_row_on_decreasing` **FAIL** (display not implemented yet)
- `test_growth_display_toggle_off_hides_reject_row` PASS (display doesn't append reject row in any case yet)
- `test_etf_display_3rd_buy_shows_reject_row_on_decreasing` **FAIL** (display not implemented yet)
- `test_etf_display_toggle_off_hides_reject_row` PASS (same reason)

Two expected failures (Growth + ETF "shows reject row" tests).

- [ ] **Step 3: Commit**

```bash
git add tests/test_signal_judge_3rd_buy_hist_reject.py
git commit -m "test(signal_judge): add failing display-layer tests for v5.3e reject

Asserts that 3rd_BUY display section appends a [거부] MACD hist 2일 감속
row AND sets the section's gate field when decreasing_2d is detected.
Implementation lands in subsequent commits."
```

---

## Task 6: Implement Growth display reject row + gate

**Files:**
- Modify: `signal_judge.py` — inside `_build_entry_sections_growth`, the 3rd BUY display block (around lines 858–896).

- [ ] **Step 1: Locate the existing Growth 3rd_BUY display block**

The current block ends with this `sections.append(...)` at around line 889:

```python
    c3_reject = rsi is not None and rsi > 75
    sections.append({
        "name": f"3차 매수 조건 - {group_label} v2.2",
        "rule": "4개 모두 충족",
        "conditions": c3,
        "met": _count_ok(c3),
        "total": len(c3),
        "gate": "[거부] RSI > 75" if c3_reject else ("[거부] 당일 급락" if reject_drop else None),
    })
```

- [ ] **Step 2: Insert the hist reject computation and conditionally append the row before the section is built**

Replace the block above with:

```python
    c3_reject = rsi is not None and rsi > 75
    _g3_hist_filter_display = _p("entry_growth.3rd_buy.reject_decreasing_hist", True)
    c3_hist_reject = _g3_hist_filter_display and macd_hist_trend == "decreasing_2d"
    if c3_hist_reject:
        c3.append(("no", "[거부] MACD hist 2일 감속",
                   "MACD hist 2일 연속 감소 — 추세 둔화로 3차 매수 보류예요"))
    # gate priority: RSI overheat > daily drop > hist deceleration
    if c3_reject:
        c3_gate = "[거부] RSI > 75"
    elif reject_drop:
        c3_gate = "[거부] 당일 급락"
    elif c3_hist_reject:
        c3_gate = "[거부] MACD hist 2일 감속"
    else:
        c3_gate = None
    sections.append({
        "name": f"3차 매수 조건 - {group_label} v2.3",
        "rule": "4개 모두 충족",
        "conditions": c3,
        "met": _count_ok(c3),
        "total": len(c3),
        "gate": c3_gate,
    })
```

Notes:
- Section name version bumped `v2.2` → `v2.3` to reflect the structural addition (the section now carries a 5th conditional row).
- Gate priority places `RSI > 75` and `당일 급락` ahead of the new hist reject because those are hard vetos that apply to all entry tiers, whereas hist reject is tier-specific.

- [ ] **Step 3: Run Growth display tests**

Run: `pytest tests/test_signal_judge_3rd_buy_hist_reject.py -v -k "growth and display"`

Expected: All 3 Growth display tests PASS:
- `test_growth_display_3rd_buy_no_reject_row_on_increasing` PASS
- `test_growth_display_3rd_buy_shows_reject_row_on_decreasing` PASS (was failing)
- `test_growth_display_toggle_off_hides_reject_row` PASS

- [ ] **Step 4: Commit**

```bash
git add signal_judge.py
git commit -m "feat(signal_judge): Growth display surfaces 3rd_BUY hist reject

When macd_hist_trend == 'decreasing_2d' and the v5.3e toggle is on,
the Growth 3rd_BUY display section appends a [거부] MACD hist 2일 감속
row and sets section.gate accordingly. Section name bumped v2.2→v2.3.
ETF mirror in next commit."
```

---

## Task 7: Implement ETF display reject row + gate

**Files:**
- Modify: `signal_judge.py` — inside `_build_entry_sections_etf`, the 3rd BUY display block (around lines 993–1022).

- [ ] **Step 1: Locate the existing ETF 3rd_BUY display block**

The current block ends with this `sections.append(...)` at around line 1015:

```python
    sections.append({
        "name": "3차 매수 조건 - ETF v2.4",
        "rule": "3개 ALL 충족",
        "conditions": c3,
        "met": _count_ok(c3),
        "total": len(c3),
        "gate": f"[거부] RSI {rsi:.1f} > 70" if reject_rsi else None,
    })
```

- [ ] **Step 2: Insert hist reject computation and gate extension**

Replace the block above with:

```python
    _e3_hist_filter_display = _p("entry_etf.3rd_buy.reject_decreasing_hist", True)
    c3_hist_reject_etf = _e3_hist_filter_display and macd_hist_trend == "decreasing_2d"
    if c3_hist_reject_etf:
        c3.append(("no", "[거부] MACD hist 2일 감속",
                   "MACD hist 2일 연속 감소 — 추세 둔화로 3차 매수 보류예요"))
    # gate priority: RSI overheat > hist deceleration
    if reject_rsi:
        etf_c3_gate = f"[거부] RSI {rsi:.1f} > 70"
    elif c3_hist_reject_etf:
        etf_c3_gate = "[거부] MACD hist 2일 감속"
    else:
        etf_c3_gate = None
    sections.append({
        "name": "3차 매수 조건 - ETF v2.5",
        "rule": "3개 ALL 충족",
        "conditions": c3,
        "met": _count_ok(c3),
        "total": len(c3),
        "gate": etf_c3_gate,
    })
```

Notes:
- Section name version bumped `v2.4` → `v2.5`.
- ETF gate priority: RSI overheat is the only pre-existing veto, so hist comes second.

- [ ] **Step 3: Run all tests for this feature**

Run: `pytest tests/test_signal_judge_3rd_buy_hist_reject.py -v`

Expected: All 17 tests PASS (12 decision + 5 display).

- [ ] **Step 4: Sanity-check no other tests broke**

Run: `pytest tests/ -v -k "not e2e"`

Expected: No new failures relative to the master baseline.

- [ ] **Step 5: Commit**

```bash
git add signal_judge.py
git commit -m "feat(signal_judge): ETF display surfaces 3rd_BUY hist reject

Mirrors Growth v5.3e display behavior. Section name bumped v2.4→v2.5.
Code change complete; docs updates in subsequent commits."
```

---

## Task 8: Update `strategy.md` with v5.3e notes

**Files:**
- Modify: `strategy.md`

- [ ] **Step 1: Update the Growth 3rd BUY section condition listing (around line 221)**

Find this block:

```
### 3rd BUY (50%) — 추세 확정
```
[ALL 4개 충족]
  ① 가격 > MA20       (추세 복귀)
  ② MACD > 0 + 골든크로스 (MACD > signal)  (완전 양전환)
  ③ 거래량 ≥ 1.5x     (강한 매수세)
  ④ RSI > 55          (상승 모멘텀 확인)

[추가 거부] RSI > 75 → 과열 구간 진입 금지
```

Replace with:

```
### 3rd BUY (50%) — 추세 확정
```
[ALL 4개 충족]
  ① 가격 > MA20       (추세 복귀)
  ② MACD > 0 + 골든크로스 (MACD > signal)  (완전 양전환)
  ③ 거래량 ≥ 1.5x     (강한 매수세)
  ④ RSI > 55          (상승 모멘텀 확인)

[추가 거부] RSI > 75 → 과열 구간 진입 금지
[추가 거부] MACD hist 2일 연속 감속 (decreasing_2d) → 추세 둔화 보류 (v5.3e)
```

- [ ] **Step 2: Update the ETF 3rd BUY section condition listing (around line 271)**

Find this block:

```
### 3rd BUY (50%) — ALL 충족
```
  ① 종가 > MA20       (추세 복귀)
  ② RSI > 55          (상승 모멘텀)
  ③ MACD > 0 + 골든크로스 (MACD > signal)  (완전 양전환)
```

Replace with:

```
### 3rd BUY (50%) — ALL 충족
```
  ① 종가 > MA20       (추세 복귀)
  ② RSI > 55          (상승 모멘텀)
  ③ MACD > 0 + 골든크로스 (MACD > signal)  (완전 양전환)

[추가 거부] MACD hist 2일 연속 감속 (decreasing_2d) → 추세 둔화 보류 (v5.3e)
```

- [ ] **Step 3: Add the v5.3e entry to the 변경 이력 section**

Find the line `### v5.3b` (around line 368) and insert a new section **immediately before** it:

```markdown
### v5.3e
- **3rd_BUY momentum quality reject** (Growth + ETF): `macd_hist_trend == "decreasing_2d"` 시 3차 매수 거부 (cascade → 2nd/1st/WATCH).
- `increasing_2d`, `mixed`, `N/A`, `""` 모두 통과 — 오직 명확한 2일 감속만 reject.
- PARAMS toggle: `entry_growth.3rd_buy.reject_decreasing_hist`, `entry_etf.3rd_buy.reject_decreasing_hist` (default `true`). False 설정 시 v5.3d 동작과 bit-identical.
- 디스플레이: 3차 매수 섹션에 `[거부] MACD hist 2일 감속` 행 + gate 라벨 표시 → WATCH/HOLD 진단에서도 이유 노출.
- **철학**: 3rd_BUY는 단순 강세 상태가 아니라 momentum persistence / re-acceleration을 요구한다.
- 2nd_BUY / 1st_BUY / Exit / 히스토리 스키마 무변경.

```

- [ ] **Step 4: Update the document title from `v5.3b` to `v5.3e`**

Find the first line:

```markdown
# Signal Decision Rules v5.3b — 익절 전용 판정 로직
```

Replace with:

```markdown
# Signal Decision Rules v5.3e — 익절 전용 판정 로직
```

- [ ] **Step 5: Verify tests still pass (docs-only change, but be safe)**

Run: `pytest tests/test_signal_judge_3rd_buy_hist_reject.py -v`

Expected: All 17 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add strategy.md
git commit -m "docs(strategy): record v5.3e 3rd_BUY hist reject filter

Updates Growth/ETF 3rd_BUY condition lists with the new [추가 거부]
row, adds v5.3e to 변경 이력, bumps document version header."
```

---

## Task 9: Update `CLAUDE.md` with v5.3e bullet

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Find the v5.3 bullet list section**

Locate the section titled `## 시그널 판정 규칙 (strategy.md v5.3 주요 변경사항)`. Find the existing `**v5.3d 2nd BUY 재설계**: ...` bullet.

- [ ] **Step 2: Insert a v5.3e bullet immediately after the v5.3d bullet**

Add this new line:

```markdown
- **v5.3e 3rd_BUY momentum reject**: Growth/ETF 3rd_BUY에 `macd_hist_trend == "decreasing_2d"` 거부 필터 추가 · increasing_2d/mixed/N/A 통과 · PARAMS toggle (`entry_*.3rd_buy.reject_decreasing_hist`, default `true`)로 즉시 롤백 가능 · 2nd_BUY/1st_BUY/Exit 무변경
```

- [ ] **Step 3: Final sanity test run**

Run: `pytest tests/test_signal_judge_3rd_buy_hist_reject.py -v`
Expected: All 17 tests PASS.

Then: `pytest tests/ -v -k "not e2e"`
Expected: No regressions versus the master baseline.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): add v5.3e 3rd_BUY hist reject bullet

One-line summary in the strategy changelog section pointing at the
PARAMS toggle and the unchanged downstream surface."
```

---

## Self-Review

### Spec coverage check

| Spec section | Implementing task(s) |
|---|---|
| §3.1 Growth decision reject clause | Task 1 (test), Task 3 (impl) |
| §3.2 ETF decision reject clause | Task 1 (test), Task 4 (impl) |
| §3.3 Display sections (Growth + ETF, gate + row) | Task 5 (test), Task 6 (Growth impl), Task 7 (ETF impl) |
| §3.4 PARAMS additions + version bump | Task 2 |
| §3.5 N/A / "" / mixed handling | Task 1 tests `..._passes_on_na_trend`, `..._passes_on_empty_trend`, `..._passes_on_mixed_trend` (Growth) and the equivalent ETF tests |
| §4.1 strategy.md update | Task 8 |
| §4.2 CLAUDE.md update | Task 9 |
| §5 What does NOT change | Verified by Task 4 Step 4 (`pytest tests/ -v -k "not e2e"` for no regressions) |
| §6 Acceptance criteria 1–8 | All covered: (1) Task 3+4 decision impl, (2) Task 1 toggle-off tests, (3) Tasks 6+7 display impl, (4) Task 1 mixed/N/A/empty tests, (5) Task 4 regression sanity run, (6) Task 2 version bump, (7) Tasks 8+9 docs, (8) no history file touched anywhere in the plan |
| §7 Risks | Mitigations are operational (PARAMS toggle visible to operator); plan does not need a code-level mitigation task |

No gaps.

### Placeholder scan
No "TBD", "TODO", "implement later", or vague instructions. Every code step shows the exact code to insert/replace.

### Type/name consistency
- PARAMS keys consistent across spec and all tasks: `entry_growth.3rd_buy.reject_decreasing_hist` and `entry_etf.3rd_buy.reject_decreasing_hist`.
- Local variable names: `hist_decel` (Growth decision), `hist_decel_etf` (ETF decision), `c3_hist_reject` (Growth display), `c3_hist_reject_etf` (ETF display) — distinct, no collision risk.
- Display label uniform: `"[거부] MACD hist 2일 감속"` everywhere.
- Display description uniform: `"MACD hist 2일 연속 감소 — 추세 둔화로 3차 매수 보류예요"` — same string across all four insertion sites (Growth decision, ETF decision, Growth display, ETF display).

### Section version bumps
- Growth display: `v2.2` → `v2.3` (Task 6)
- ETF display: `v2.4` → `v2.5` (Task 7)
- strategy.md header: `v5.3b` → `v5.3e` (Task 8)
- strategy_params.json: `5.3b` → `5.3e` (Task 2)

All consistent.

---

## Execution Notes

- Tasks are intentionally ordered so the test suite is **always green at every commit boundary** except the explicit "failing test" commits (Task 1 Step 3, Task 5 Step 3), which are documented as known-red and resolved by the immediately following implementation tasks.
- No history files (`history/*.json`) are touched. The pre-commit hook described in CLAUDE.md should not trigger.
- All code edits live in already-tracked files. No new directories needed beyond the existing `tests/`.
