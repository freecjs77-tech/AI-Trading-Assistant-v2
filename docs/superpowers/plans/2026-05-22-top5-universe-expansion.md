# Top 5 Universe Expansion (momentum-only tickers) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lifecycle US Top 5 후보 풀에 오늘 momentum 스캐너에 잡힌 ticker 중 lifecycle active_set 밖 종목도 포함시킨다. 5-stage 파이프라인 / lifecycle history 무영향.

**Architecture:** `lifecycle_signal.py`의 per-ticker 로직을 `compute_single_snapshot`으로 추출(리팩터). `lifecycle_buy_candidates.py`의 selector가 momentum 스캐너 live 결과를 받아 active_set 밖 ticker에 대해 이 helper로 합성 snapshot을 즉석 계산해 pool에 추가. pipeline이 scanner 반환을 lifecycle render 호출에 직접 연결.

**Tech Stack:** Python 3.10+, pytest, Jinja2 (기존 stack 그대로, 신규 의존성 없음).

**Spec:** [docs/superpowers/specs/2026-05-22-top5-universe-expansion-design.md](../specs/2026-05-22-top5-universe-expansion-design.md)

---

## File Structure

**Create:**
- `tests/test_compute_single_snapshot.py` — `compute_single_snapshot` 단위 + parity 테스트

**Modify:**
- `lifecycle_signal.py` — `compute_single_snapshot` 추출(공개 함수), `process_universe` 본문이 이를 호출하도록 리팩터
- `lifecycle_buy_candidates.py` — `select_top5_buy_candidates` 시그니처 확장, momentum-only pool 합치기
- `lifecycle_report.py` — `_render` / `generate_lifecycle_pages` 시그니처에 신규 kwargs
- `pipeline.py` — momentum scanner 결과를 `generate_lifecycle_pages` 호출에 전달
- `templates/lifecycle_us.html` — `🚀 스캐너 신규` 배지 추가
- `tests/test_lifecycle_buy_candidates.py` — momentum-only 경로 통합 테스트 추가
- `CLAUDE.md` — 진행 중인 계획 리스트에 plan 한 줄 추가

**Out of scope:**
- KR 시장 Top 5
- Telegram brief
- Lifecycle history에 momentum-only 종목 저장
- 5-stage 파이프라인 UI 노출
- `active_set` 룰 변경

---

## Task 1: Verify scanner return shape (read-only investigation)

**Files:** none modified — investigation step only

오늘 momentum 스캐너의 반환 shape이 `{"status": "ok", "signals": {"MOMENTUM_3": [...], "MOMENTUM_2": [...], "MOMENTUM_1": [...], "EM": [...]}, ...}`임을 [pipeline.py:362-368](../../../pipeline.py)에서 확인. 각 list 원소는 `evaluate_stock` 반환 dict (`ticker, stage, rsi, dist_ema9_pct, sector, price, ret_5d_pct, ...`).

- [ ] **Step 1: Verify shape**

```
grep -n "signals\[stage\].append\|signals = {" momentum_scanner.py
```
Expected: line ~244 `signals = {"MOMENTUM_3": [], ...}` 및 line ~275-276 `signals[stage].append(evaluation)` 보임.

- [ ] **Step 2: Decide adapter location**

`lifecycle_buy_candidates.py`에 작은 helper `_flatten_scanner_signals(scanner_result) -> list[dict]` 추가 (Task 5에서 구현). Adapter 1개로 scanner result → flat list of ticker dicts 변환.

- [ ] **Step 3: No commit needed (investigation only).**

---

## Task 2: `compute_single_snapshot` — write failing test for parity

**Files:**
- Create: `tests/test_compute_single_snapshot.py`

`process_universe` 내부 루프와 동등한 단일-ticker helper. 추출 전후 동작 동일 보장이 핵심.

- [ ] **Step 1: Write failing parity test**

`tests/test_compute_single_snapshot.py`:
```python
"""Tests for lifecycle_signal.compute_single_snapshot — extracted per-ticker helper."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _minimal_market_entry():
    """Build a market_data entry sufficient for a TREND_OK setup."""
    return {
        "ticker":         "AAA",
        "close":          110.0,
        "high":           111.0,
        "low":            108.0,
        "ema9":           105.0,
        "ema21":          100.0,
        "ema65":          95.0,
        "ema9_slope_3d":  0.5,
        "ema21_slope_5d": 0.3,
        "ema65_slope_20d": 0.2,
        "rsi14":          65.0,
        "atr14":          2.5,
        "atr14_pct":      2.27,
        "volume_ratio":   1.1,
        "macd":           1.0,
        "macd_signal":    0.5,
        "macd_hist":      0.5,
        "ret_5d_pct":     5.0,
        "ret_20d_pct":    10.0,
        "change_pct":     1.2,
        "ret_3d_pct":     3.0,
        "dist_ema9_pct":  4.76,
    }


def test_compute_single_snapshot_returns_snapshot_for_valid_input():
    """Valid market_data → snapshot dict with setup/trigger/decision."""
    from lifecycle_signal import compute_single_snapshot
    snap = compute_single_snapshot(
        ticker="AAA",
        market_data_entry=_minimal_market_entry(),
        market_ret_5d_pct=0.0,
        yesterday=None,
        today="2026-05-22",
    )
    assert snap is not None
    assert "setup" in snap
    assert "trigger" in snap or "trigger_state" in snap
    assert "decision" in snap
    assert snap.get("raw", {}).get("close") == 110.0


def test_compute_single_snapshot_returns_none_for_missing_close():
    """close=None → None (mirrors process_universe skip behavior)."""
    from lifecycle_signal import compute_single_snapshot
    entry = _minimal_market_entry()
    entry["close"] = None
    snap = compute_single_snapshot(
        ticker="AAA",
        market_data_entry=entry,
        market_ret_5d_pct=0.0,
        yesterday=None,
        today="2026-05-22",
    )
    assert snap is None


def test_compute_single_snapshot_returns_none_for_missing_ema9():
    """ema9=None → None."""
    from lifecycle_signal import compute_single_snapshot
    entry = _minimal_market_entry()
    entry["ema9"] = None
    snap = compute_single_snapshot(
        ticker="AAA",
        market_data_entry=entry,
        market_ret_5d_pct=0.0,
        yesterday=None,
        today="2026-05-22",
    )
    assert snap is None


def test_compute_single_snapshot_returns_none_for_error_entry():
    """{'error': ...} → None."""
    from lifecycle_signal import compute_single_snapshot
    snap = compute_single_snapshot(
        ticker="AAA",
        market_data_entry={"error": "fetch failed"},
        market_ret_5d_pct=0.0,
        yesterday=None,
        today="2026-05-22",
    )
    assert snap is None


def test_compute_single_snapshot_yesterday_none_safe():
    """yesterday=None must NOT crash inside _is_early_trigger.

    Previously _is_early_trigger called yesterday.get(...) — would AttributeError on None.
    The helper must pass an empty dict (or None-safe equivalent) internally.
    """
    from lifecycle_signal import compute_single_snapshot
    snap = compute_single_snapshot(
        ticker="AAA",
        market_data_entry=_minimal_market_entry(),
        market_ret_5d_pct=0.0,
        yesterday=None,
        today="2026-05-22",
    )
    assert snap is not None
    # With no yesterday, trigger cannot fire — should be WAIT.
    assert snap.get("trigger") == "WAIT" or snap.get("trigger_state") == "WAIT"


def test_compute_single_snapshot_parity_with_process_universe():
    """Same input via compute_single_snapshot and process_universe must produce identical snapshot."""
    from lifecycle_signal import compute_single_snapshot, process_universe

    entry = _minimal_market_entry()
    market_data = {"data": {"AAA": entry}}
    yesterday_state = {"tickers": {}}

    proc_result = process_universe(
        active_set={"AAA"},
        market_data=market_data,
        yesterday_state=yesterday_state,
        today="2026-05-22",
        market_ret_5d_pct=0.0,
    )
    process_snap = proc_result["snapshots"].get("AAA")
    assert process_snap is not None  # sanity

    helper_snap = compute_single_snapshot(
        ticker="AAA",
        market_data_entry=entry,
        market_ret_5d_pct=0.0,
        yesterday=None,
        today="2026-05-22",
    )
    assert helper_snap is not None
    # Core fields must match exactly
    assert helper_snap.get("setup") == process_snap.get("setup")
    assert helper_snap.get("trigger") == process_snap.get("trigger")
    assert helper_snap.get("decision") == process_snap.get("decision")
    assert (helper_snap.get("raw") or {}).get("close") == \
           (process_snap.get("raw") or {}).get("close")
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_compute_single_snapshot.py -xvs
```
Expected: FAIL with `ImportError: cannot import name 'compute_single_snapshot' from 'lifecycle_signal'`.

- [ ] **Step 3: No commit yet — test failure is the starting state.**

---

## Task 3: `compute_single_snapshot` — extract from process_universe

**Files:**
- Modify: `lifecycle_signal.py` (extract per-ticker loop body; refactor `process_universe` to call it)

per-ticker 본문 ([lifecycle_signal.py:577-674](../../../lifecycle_signal.py))을 그대로 함수로 빼내고, process_universe는 active_set을 돌며 helper를 호출하는 형태로 단순화.

- [ ] **Step 1: Locate insertion point**

```
grep -n "def process_universe\|def _make_snapshot\|def _build_today_raw_for_signal" lifecycle_signal.py
```
Expected: `_build_today_raw_for_signal` is around L471, `process_universe` is around L553, `_make_snapshot` is defined elsewhere.

- [ ] **Step 2: Add `compute_single_snapshot` directly above `process_universe`**

Insert before the `def process_universe(...)` line:

```python
def compute_single_snapshot(*, ticker: str,
                              market_data_entry: dict,
                              market_ret_5d_pct: Optional[float],
                              yesterday: Optional[dict],
                              today: str,
                              regime: Optional[str] = None) -> Optional[dict]:
    """Build a lifecycle snapshot for one ticker without touching history.

    Mirrors the per-ticker body of process_universe. Returns None for skipped
    tickers (missing close/ema9, or `error` in market_data_entry).

    `yesterday` may be None — internally normalized to an empty raw dict so the
    Phase A trigger helpers (which call yesterday.get(...)) remain None-safe.
    With no yesterday, trigger will resolve to WAIT.
    """
    import os
    from lifecycle_score_config import (
        DEFAULT_ENGINE_MODE, MODE_SCORE_SHADOW, MODE_SCORE_ACTIVE,
    )
    from lifecycle_score import compute_trigger_score, compute_drift_score

    mode = os.environ.get("LIFECYCLE_ENGINE_MODE", DEFAULT_ENGINE_MODE)

    if not market_data_entry or "error" in market_data_entry:
        return None
    today_raw = _build_today_raw_for_signal(market_data_entry)
    if today_raw["close"] is None or today_raw["ema9"] is None:
        return None

    # Normalize yesterday: process_universe builds y_for_legacy_trigger from y_raw
    # (which is {} when no history). Same here — pass {} so .get() is safe.
    y_raw = (yesterday or {}).get("raw") or {}
    y_for_legacy_trigger = {
        "close": y_raw.get("close"),
        "ema9":  y_raw.get("ema9"),
        "high":  y_raw.get("high"),
    }

    setup = evaluate_setup_state(today_raw)
    trigger = evaluate_trigger_state(today_raw, y_for_legacy_trigger, setup)
    risk_tags = compute_risk_tags(today_raw, yesterday)

    # Last-3-day closes for drift scoring. For momentum-only (no yesterday),
    # we have just today.
    recent_3d_closes = []
    if yesterday:
        y_snap_list = [yesterday]  # caller passes the latest yesterday snap, not the list
        # If caller has a list, they should preprocess; here we accept latest only.
        for s in y_snap_list[-3:]:
            c = (s.get("raw") or {}).get("close")
            if c is not None:
                recent_3d_closes.append(c)
    recent_3d_closes.append(today_raw["close"])

    yesterday_snap_for_score = {
        "close": y_raw.get("close"),
        "low":   y_raw.get("low"),
        "high":  y_raw.get("high"),
        "ema9":  y_raw.get("ema9"),
    } if yesterday else None

    score_payload = None
    if mode in (MODE_SCORE_SHADOW, MODE_SCORE_ACTIVE):
        decision = evaluate_decision(
            setup, trigger, risk_tags=risk_tags, regime=regime,
            today_raw=today_raw,
            yesterday_snap=yesterday_snap_for_score,
            recent_3d_closes=recent_3d_closes,
            market_ret_5d_pct=market_ret_5d_pct,
        )
        if isinstance(decision, dict):
            score_payload = decision
            final_decision = decision["decision"]
            final_trigger = decision["trigger_state"]
        else:
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
                "score_tier": sc.score_tier,
                "rs_tier":    sc.rs_tier,
                "active_components": sc.active_count,
                "features": sc.features,
                "score_components": sc.components_list,
                "decision_badges": [], "veto_reason": None,
                "suggested_entry_tier": None, "suggested_size_pct": 0.0,
                "rs_delta_pct": sc.rs_delta_pct,
                "_raw_score": None, "_raw_features": None, "_raw_score_track": None,
            }
    else:
        decision = evaluate_decision(setup, trigger,
                                      risk_tags=risk_tags, regime=regime)
        final_decision = decision
        final_trigger = trigger

    return _make_snapshot(
        today, today_raw, setup, final_trigger, final_decision, risk_tags,
        score_payload=score_payload,
    )
```

- [ ] **Step 3: Refactor process_universe to call the helper**

Replace lines 577-674 of `process_universe` (the per-ticker for loop body) with:

```python
    for ticker in sorted(active_set):
        entry = (flat or {}).get(ticker)
        if not entry or "error" in entry:
            skipped.append(ticker)
            continue

        # Resolve yesterday from history
        y_block = (yesterday_state.get("tickers") or {}).get(ticker)
        y_snap_list = (y_block or {}).get("snapshots", [])
        yesterday = y_snap_list[-1] if y_snap_list else None

        # For drift's tight_close_cluster we need up to 3 recent closes.
        # compute_single_snapshot uses just `yesterday`; for full parity with
        # the previous in-line loop, we pass the latest yesterday and let the
        # helper rebuild recent_3d_closes with only that data — for active_set
        # tickers this is the same behavior as before (drift used full 3d).
        # To preserve EXACT parity, pass the full y_snap_list via an internal
        # parameter (see note below).
        snap = compute_single_snapshot(
            ticker=ticker,
            market_data_entry=entry,
            market_ret_5d_pct=market_ret_5d_pct,
            yesterday=yesterday,
            today=today,
            regime=regime,
            _y_snap_list_for_drift=y_snap_list,  # internal — preserves parity
        )
        if snap is None:
            skipped.append(ticker)
            continue
        snapshots[ticker] = snap
```

Then update `compute_single_snapshot` signature to accept the internal `_y_snap_list_for_drift` kwarg:

```python
def compute_single_snapshot(*, ticker: str,
                              market_data_entry: dict,
                              market_ret_5d_pct: Optional[float],
                              yesterday: Optional[dict],
                              today: str,
                              regime: Optional[str] = None,
                              _y_snap_list_for_drift: Optional[list] = None,
                              ) -> Optional[dict]:
```

And inside, replace the `recent_3d_closes` block with:

```python
    recent_3d_closes = []
    src_list = _y_snap_list_for_drift if _y_snap_list_for_drift is not None else (
        [yesterday] if yesterday else []
    )
    for s in src_list[-3:]:
        c = (s.get("raw") or {}).get("close")
        if c is not None:
            recent_3d_closes.append(c)
    recent_3d_closes.append(today_raw["close"])
```

This keeps the original 3-day-close window for active_set tickers (via `_y_snap_list_for_drift=y_snap_list`) while degrading gracefully for momentum-only callers who only have one yesterday snap (or None).

- [ ] **Step 4: Run the parity tests + full lifecycle suite**

```
python -m pytest tests/test_compute_single_snapshot.py tests/test_lifecycle_signal.py tests/test_lifecycle_history.py tests/test_lifecycle_report.py tests/test_lifecycle_golden.py tests/test_lifecycle_e2e.py -x
```
Expected: all pass. Critical: golden tests must NOT diff — this validates the refactor is byte-equivalent.

- [ ] **Step 5: Commit**

```
git add lifecycle_signal.py tests/test_compute_single_snapshot.py
git commit -m "refactor(lifecycle): extract compute_single_snapshot from process_universe"
```

---

## Task 4: `select_top5_buy_candidates` — accept momentum_today + market_data kwargs (failing test first)

**Files:**
- Modify: `tests/test_lifecycle_buy_candidates.py`

Selector 시그니처 확장: `momentum_today`, `market_data`, `market_ret_5d_pct` kwargs를 받아 momentum-only ticker를 합성 snapshot으로 pool에 추가.

- [ ] **Step 1: Append failing tests**

Append to `tests/test_lifecycle_buy_candidates.py`:

```python
def _scanner_signal_entry(ticker: str, stage: str = "MOMENTUM_2",
                           rsi: float = 65.0, dist_ema9_pct: float = 4.0,
                           ret_5d_pct: float = 8.0) -> dict:
    """Mock momentum_scanner per-ticker output (subset of evaluate_stock result)."""
    return {
        "ticker": ticker, "stage": stage, "tier": stage,
        "maturity": "MID", "risk_tags": [], "hint": "",
        "rs_vs_sector": True, "sector": "Tech",
        "price": 100.0, "rsi": rsi,
        "ret_1d_pct": 1.0, "ret_3d_pct": 3.0, "ret_5d_pct": ret_5d_pct,
        "ret_20d_pct": 12.0, "dist_ema9_pct": dist_ema9_pct,
    }


def _market_data_entry_for_trend_ok(ticker: str) -> dict:
    """Build market_data entry that classifies as TREND_OK in lifecycle setup state."""
    return {
        "ticker": ticker,
        "close": 110.0, "high": 111.0, "low": 108.0,
        "ema9": 105.0, "ema21": 100.0, "ema65": 95.0,
        "ema9_slope_3d": 0.5, "ema21_slope_5d": 0.3, "ema65_slope_20d": 0.2,
        "rsi14": 65.0, "atr14": 2.5, "atr14_pct": 2.27,
        "volume_ratio": 1.1, "macd": 1.0, "macd_signal": 0.5, "macd_hist": 0.5,
        "ret_5d_pct": 8.0, "ret_20d_pct": 12.0, "change_pct": 1.2,
        "ret_3d_pct": 3.0, "dist_ema9_pct": 4.76,
    }


def test_select_top5_includes_momentum_only_ticker():
    """LRCX is in today's scanner but NOT in lifecycle snapshots → must enter Top 5."""
    from lifecycle_buy_candidates import select_top5_buy_candidates
    snapshots = {
        # Lifecycle universe — 1 ticker only
        "AAPL": {"setup": "TREND_OK", "score": 5, "score_track": "drift",
                  "rs_delta_pct": 3.0,
                  "raw": {"close": 200, "rsi14": 60, "dist_ema9_pct": 1.0,
                          "volume_ratio": 1.0, "risk_tags": []}},
    }
    # LRCX is in scanner today, but NOT in snapshots
    momentum_today = [_scanner_signal_entry("LRCX", stage="MOMENTUM_2")]
    market_data = {"data": {"LRCX": _market_data_entry_for_trend_ok("LRCX")}}

    result = select_top5_buy_candidates(
        snapshots=snapshots,
        portfolio_tickers={"AAPL"},
        momentum_history={"data": {}},
        today="2026-05-22",
        momentum_today=momentum_today,
        market_data=market_data,
        market_ret_5d_pct=0.0,
    )
    tickers = [c["ticker"] for c in result["candidates"]]
    assert "LRCX" in tickers, f"LRCX should be in candidates, got {tickers}"


def test_select_top5_momentum_only_marked_scanner_only():
    """momentum-only ticker's snapshot must carry _scanner_only=True for badge."""
    from lifecycle_buy_candidates import select_top5_buy_candidates
    momentum_today = [_scanner_signal_entry("LRCX", stage="MOMENTUM_3")]
    market_data = {"data": {"LRCX": _market_data_entry_for_trend_ok("LRCX")}}

    result = select_top5_buy_candidates(
        snapshots={},
        portfolio_tickers=set(),
        momentum_history={"data": {}},
        today="2026-05-22",
        momentum_today=momentum_today,
        market_data=market_data,
        market_ret_5d_pct=0.0,
    )
    lrcx = next((c for c in result["candidates"] if c["ticker"] == "LRCX"), None)
    assert lrcx is not None
    assert lrcx["snapshot"].get("_scanner_only") is True


def test_select_top5_momentum_only_gets_base_score():
    """momentum-only ticker uses compute_single_snapshot → real base_score, not 0."""
    from lifecycle_buy_candidates import select_top5_buy_candidates
    momentum_today = [_scanner_signal_entry("LRCX", stage="MOMENTUM_3")]
    market_data = {"data": {"LRCX": _market_data_entry_for_trend_ok("LRCX")}}

    result = select_top5_buy_candidates(
        snapshots={},
        portfolio_tickers=set(),
        momentum_history={"data": {}},
        today="2026-05-22",
        momentum_today=momentum_today,
        market_data=market_data,
        market_ret_5d_pct=0.0,
    )
    lrcx = next((c for c in result["candidates"] if c["ticker"] == "LRCX"), None)
    assert lrcx is not None
    # base_score should be > 0 (TREND_OK setup with positive drift score)
    assert lrcx["base_score"] > 0
    # momentum_bonus = 4 (M3)
    assert lrcx["momentum_bonus"] == 4


def test_select_top5_momentum_today_none_unchanged():
    """momentum_today=None (or absent) → existing behavior, no momentum-only pool."""
    from lifecycle_buy_candidates import select_top5_buy_candidates
    snapshots = {
        "AAPL": {"setup": "TREND_OK", "score": 5, "score_track": "drift",
                  "rs_delta_pct": 3.0,
                  "raw": {"close": 200, "rsi14": 60, "dist_ema9_pct": 1.0,
                          "volume_ratio": 1.0, "risk_tags": []}},
    }
    # Call WITHOUT momentum_today / market_data — must work as before
    result = select_top5_buy_candidates(
        snapshots=snapshots,
        portfolio_tickers=set(),
        momentum_history={"data": {}},
        today="2026-05-22",
    )
    tickers = [c["ticker"] for c in result["candidates"]]
    assert tickers == ["AAPL"]


def test_select_top5_momentum_only_skipped_when_market_data_missing():
    """Scanner ticker not in market_data → silently skipped, others unaffected."""
    from lifecycle_buy_candidates import select_top5_buy_candidates
    momentum_today = [
        _scanner_signal_entry("LRCX", stage="MOMENTUM_3"),
        _scanner_signal_entry("GHOST", stage="MOMENTUM_3"),  # no market_data
    ]
    market_data = {"data": {"LRCX": _market_data_entry_for_trend_ok("LRCX")}}

    result = select_top5_buy_candidates(
        snapshots={},
        portfolio_tickers=set(),
        momentum_history={"data": {}},
        today="2026-05-22",
        momentum_today=momentum_today,
        market_data=market_data,
        market_ret_5d_pct=0.0,
    )
    tickers = [c["ticker"] for c in result["candidates"]]
    assert "LRCX" in tickers
    assert "GHOST" not in tickers


def test_select_top5_momentum_only_skipped_when_already_in_snapshots():
    """Scanner ticker that's also in snapshots → use snapshot path, no double-add."""
    from lifecycle_buy_candidates import select_top5_buy_candidates
    # NVDA is in lifecycle snapshots AND in today's scanner
    snapshots = {
        "NVDA": {"setup": "PULLBACK", "score": 8, "score_track": "trigger",
                  "rs_delta_pct": 7.0,
                  "raw": {"close": 1200, "rsi14": 65, "dist_ema9_pct": 1.5,
                          "volume_ratio": 1.1, "risk_tags": []}},
    }
    momentum_today = [_scanner_signal_entry("NVDA", stage="MOMENTUM_3")]
    market_data = {"data": {"NVDA": _market_data_entry_for_trend_ok("NVDA")}}

    result = select_top5_buy_candidates(
        snapshots=snapshots,
        portfolio_tickers=set(),
        momentum_history={"data": {}},
        today="2026-05-22",
        momentum_today=momentum_today,
        market_data=market_data,
        market_ret_5d_pct=0.0,
    )
    # Count: exactly 1 NVDA entry (snapshot path), not 2
    nvda_entries = [c for c in result["candidates"] if c["ticker"] == "NVDA"]
    assert len(nvda_entries) == 1
    # Should use the lifecycle snapshot, not the scanner one
    assert nvda_entries[0]["snapshot"].get("_scanner_only") is not True
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_select_top5_includes_momentum_only_ticker -xvs
```
Expected: FAIL — either `TypeError: select_top5_buy_candidates() got an unexpected keyword argument 'momentum_today'` or AssertionError on missing LRCX.

- [ ] **Step 3: No commit yet — implementation comes in Task 5.**

---

## Task 5: `select_top5_buy_candidates` — implementation

**Files:**
- Modify: `lifecycle_buy_candidates.py`

신규 kwargs 추가 + momentum-only pool 합치기.

- [ ] **Step 1: Add `_flatten_scanner_signals` helper**

Insert above `_extract_today_momentum` in `lifecycle_buy_candidates.py`:

```python
def _flatten_scanner_signals(momentum_today: list[dict] | dict | None) -> list[dict]:
    """Accept either:
      - flat list of evaluate_stock dicts: [{ticker, stage, ...}, ...]
      - scanner_*_result dict: {"signals": {"MOMENTUM_3": [...], ...}, ...}
    Returns a flat list of per-ticker dicts.
    """
    if momentum_today is None:
        return []
    if isinstance(momentum_today, list):
        return list(momentum_today)
    if isinstance(momentum_today, dict) and "signals" in momentum_today:
        flat: list[dict] = []
        for tier in ("MOMENTUM_3", "MOMENTUM_2", "MOMENTUM_1", "EM"):
            flat.extend(momentum_today["signals"].get(tier, []) or [])
        return flat
    return []
```

- [ ] **Step 2: Modify `select_top5_buy_candidates` signature + body**

Replace the existing `select_top5_buy_candidates` function with:

```python
def select_top5_buy_candidates(*, snapshots: dict, portfolio_tickers: set,
                                  momentum_history: dict, today: str,
                                  threshold: float = 5.0, cap: int = 5,
                                  momentum_today: list[dict] | dict | None = None,
                                  market_data: dict | None = None,
                                  market_ret_5d_pct: float | None = None) -> dict:
    """One-call entry. Returns dict ready for template ctx injection.

    Args:
        snapshots: lifecycle process_universe result snapshots (active_set 종목).
        portfolio_tickers: 보유 종목 set — is_portfolio 마킹용.
        momentum_history: scanner_momentum_*_history.json raw dict (fallback path,
            기존 기능 유지 — momentum_bonus 산정 시 활용).
        today: "YYYY-MM-DD".
        threshold / cap: ranking 임계 / 상한 (기본 5.0 / 5).
        momentum_today: (선택) 오늘 momentum 스캐너 라이브 결과. flat list 또는
            scanner_*_result dict. snapshots에 없는 ticker를 즉석 합성 snapshot
            으로 pool에 추가 — universe 확장 경로.
        market_data: (선택) momentum-only ticker의 합성 snapshot 계산 source.
            pipeline의 market_data dict (`{"data": {ticker: entry, ...}}` 또는
            `{ticker: entry, ...}`).
        market_ret_5d_pct: (선택) RS bonus 계산을 위한 시장 5일 수익률.

    Returns:
        {
            "candidates": list of ranked dicts (with size_hint_label, snapshot, scores),
            "count":      len(candidates),
            "max":        cap,
            "threshold":  threshold,
        }
    """
    pool = build_candidate_pool(snapshots, portfolio_tickers)

    # --- Universe expansion: momentum-only tickers (NEW) ---
    if momentum_today is not None and market_data is not None:
        from lifecycle_signal import compute_single_snapshot
        scanner_list = _flatten_scanner_signals(momentum_today)
        existing_tickers = {entry["ticker"] for entry in pool}
        market_data_flat = (market_data.get("data")
                             if isinstance(market_data, dict) and "data" in market_data
                             else market_data) or {}
        seen_extra: set[str] = set()
        for sig in scanner_list:
            tk = sig.get("ticker")
            if not tk or tk in existing_tickers or tk in seen_extra:
                continue
            md_entry = market_data_flat.get(tk)
            if not md_entry:
                continue
            synthetic = compute_single_snapshot(
                ticker=tk,
                market_data_entry=md_entry,
                market_ret_5d_pct=market_ret_5d_pct,
                yesterday=None,
                today=today,
            )
            if synthetic is None:
                continue
            if synthetic.get("setup") == "BROKEN":
                continue
            synthetic["_scanner_only"] = True
            pool.append({
                "ticker":       tk,
                "snapshot":     synthetic,
                "is_portfolio": tk in (portfolio_tickers or set()),
            })
            seen_extra.add(tk)

    momentum_today_for_bonus = _extract_today_momentum(momentum_history, today)
    # Also include live scanner stages so momentum-only tickers get momentum_bonus
    if momentum_today is not None:
        for sig in _flatten_scanner_signals(momentum_today):
            tk = sig.get("ticker")
            if tk and tk not in momentum_today_for_bonus:
                momentum_today_for_bonus[tk] = {"stage": sig.get("stage")}

    ranked = rank_top_n(pool, momentum_today_for_bonus,
                          threshold=threshold, cap=cap)

    for c in ranked:
        setup = (c["snapshot"] or {}).get("setup")
        c["size_hint_label"] = _size_hint_label(setup, c["is_portfolio"])

    return {
        "candidates": ranked,
        "count":      len(ranked),
        "max":        cap,
        "threshold":  threshold,
    }
```

- [ ] **Step 3: Run failing tests to verify they now pass**

```
python -m pytest tests/test_lifecycle_buy_candidates.py -xvs
```
Expected: all pass (existing + 6 new).

- [ ] **Step 4: Commit**

```
git add lifecycle_buy_candidates.py tests/test_lifecycle_buy_candidates.py
git commit -m "feat(top5): expand universe via on-the-fly momentum-only synthesis"
```

---

## Task 6: `lifecycle_report.py` — plumbing kwargs through _render + generate_lifecycle_pages

**Files:**
- Modify: `lifecycle_report.py`
- Modify: `tests/test_lifecycle_buy_candidates.py`

`_render` 와 `generate_lifecycle_pages` 시그니처에 `momentum_today_us`, `momentum_today_kr`, `market_data` kwargs 추가. `_render`는 받은 값을 `select_top5_buy_candidates` 호출에 전달. `market_ret_5d_pct`는 `result.get("market_ret_5d_pct")`로 추출.

- [ ] **Step 1: Write failing integration test**

Append to `tests/test_lifecycle_buy_candidates.py`:

```python
def test_render_passes_momentum_today_and_market_data(monkeypatch, tmp_path):
    """_render must forward momentum_today + market_data to select_top5."""
    import lifecycle_report as lr

    captured: dict = {}

    def fake_select(**kwargs):
        captured.update(kwargs)
        return {"candidates": [], "count": 0, "max": 5, "threshold": 5.0}

    monkeypatch.setattr(lr, "select_top5_buy_candidates", fake_select)

    # Also stub the Jinja render to avoid pulling full template
    from jinja2 import Template
    monkeypatch.setattr(Template, "render", lambda self, **ctx: "<html></html>")

    result = {
        "as_of": "2026-05-22", "market": "US",
        "snapshots": {},
        "transitions": [], "skipped": [], "active_set_size": 0,
        "market_ret_5d_pct": 0.42,
        "momentum_history": {"data": {}},
        "engine_version": "score_v1",
    }
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    lr._render("US", result, str(out_dir), template_dir=None,
                lifecycle_state={"tickers": {}, "transitions": []},
                portfolio_tickers={"AAA"},
                momentum_today=[{"ticker": "LRCX", "stage": "MOMENTUM_3"}],
                market_data={"data": {"LRCX": {"close": 100, "ema9": 95}}})

    assert captured.get("momentum_today") == [{"ticker": "LRCX", "stage": "MOMENTUM_3"}]
    assert "LRCX" in (captured.get("market_data", {}).get("data", {}) or {})
    assert captured.get("market_ret_5d_pct") == 0.42


def test_generate_lifecycle_pages_dispatches_us_momentum(monkeypatch, tmp_path):
    """generate_lifecycle_pages must pass us-scoped kwargs to _render('US', ...)."""
    import lifecycle_report as lr

    captured_calls: list[dict] = []

    def fake_render(market, result, output_dir, template_dir, lifecycle_state,
                     nav_ctx=None, portfolio_tickers=None,
                     momentum_today=None, market_data=None):
        captured_calls.append({
            "market": market,
            "momentum_today": momentum_today,
            "has_market_data": market_data is not None,
        })
        return str(tmp_path / f"{market.lower()}.html")

    monkeypatch.setattr(lr, "_render", fake_render)

    us_result = {"snapshots": {"AAA": {"setup": "TREND_OK"}}, "as_of": "2026-05-22"}
    kr_result = {"snapshots": {"005930": {"setup": "PULLBACK"}}, "as_of": "2026-05-22"}

    lr.generate_lifecycle_pages(
        us_result=us_result, kr_result=kr_result,
        output_dir=str(tmp_path),
        portfolio_tickers={"AAA"},
        momentum_today_us=[{"ticker": "LRCX", "stage": "MOMENTUM_3"}],
        momentum_today_kr=None,
        market_data={"data": {"LRCX": {"close": 100}}},
    )

    us_call = next(c for c in captured_calls if c["market"] == "US")
    kr_call = next(c for c in captured_calls if c["market"] == "KR")
    assert us_call["momentum_today"] == [{"ticker": "LRCX", "stage": "MOMENTUM_3"}]
    assert us_call["has_market_data"] is True
    assert kr_call["momentum_today"] is None  # KR not provided
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_render_passes_momentum_today_and_market_data tests/test_lifecycle_buy_candidates.py::test_generate_lifecycle_pages_dispatches_us_momentum -xvs
```
Expected: FAIL with `TypeError: _render() got an unexpected keyword argument 'momentum_today'` (and similar for generate).

- [ ] **Step 3: Modify `_render` signature + select_top5 call**

In `lifecycle_report.py`, locate `def _render(market: str, result: dict, ...)` and update:

```python
def _render(market: str, result: dict, output_dir: str,
              template_dir: Optional[str], lifecycle_state: Optional[dict],
              nav_ctx: Optional[dict] = None,
              portfolio_tickers: Optional[set] = None,
              momentum_today: list | dict | None = None,
              market_data: Optional[dict] = None) -> str:
```

Inside the body, locate the existing `select_top5_buy_candidates(...)` call and update it to:

```python
    from lifecycle_buy_candidates import select_top5_buy_candidates
    top5 = select_top5_buy_candidates(
        snapshots=result.get("snapshots") or {},
        portfolio_tickers=portfolio_tickers or set(),
        momentum_history=result.get("momentum_history") or {"data": {}},
        today=result["as_of"],
        momentum_today=momentum_today,
        market_data=market_data,
        market_ret_5d_pct=result.get("market_ret_5d_pct"),
    )
```

- [ ] **Step 4: Modify `generate_lifecycle_pages` signature**

Locate `def generate_lifecycle_pages(...)` and update:

```python
def generate_lifecycle_pages(*, us_result: Optional[dict],
                                kr_result: Optional[dict],
                                output_dir: str,
                                template_dir: Optional[str] = None,
                                us_state: Optional[dict] = None,
                                kr_state: Optional[dict] = None,
                                nav_ctx: Optional[dict] = None,
                                portfolio_tickers: Optional[set] = None,
                                momentum_today_us: list | dict | None = None,
                                momentum_today_kr: list | dict | None = None,
                                market_data: Optional[dict] = None,
                                ) -> dict[str, str]:
```

And in the body, pass the per-market values to `_render`:

```python
    out: dict[str, str] = {}
    if us_result and us_result.get("snapshots"):
        out["us"] = _render("US", us_result, output_dir, template_dir,
                              us_state, nav_ctx,
                              portfolio_tickers=portfolio_tickers,
                              momentum_today=momentum_today_us,
                              market_data=market_data)
    if kr_result and kr_result.get("snapshots"):
        out["kr"] = _render("KR", kr_result, output_dir, template_dir,
                              kr_state, nav_ctx,
                              portfolio_tickers=portfolio_tickers,
                              momentum_today=momentum_today_kr,
                              market_data=market_data)
    return out
```

- [ ] **Step 5: Run the two new tests + full lifecycle/buy_candidates suite**

```
python -m pytest tests/test_lifecycle_buy_candidates.py tests/test_lifecycle_report.py tests/test_lifecycle_golden.py -x
```
Expected: all pass.

- [ ] **Step 6: Commit**

```
git add lifecycle_report.py tests/test_lifecycle_buy_candidates.py
git commit -m "feat(top5): plumb momentum_today + market_data through lifecycle render"
```

---

## Task 7: `pipeline.py` — wire scanner result into generate_lifecycle_pages

**Files:**
- Modify: `pipeline.py`

Step 4c2의 `momentum_us_result` / `momentum_kr_result` (이미 존재) 를 `generate_lifecycle_pages` 호출에 추가 kwarg로 전달. `market_data`도 함께 전달.

- [ ] **Step 1: Locate the generate_lifecycle_pages call**

```
grep -n "generate_lifecycle_pages" pipeline.py
```
Expected: call site around line 662-669.

- [ ] **Step 2: Read the call site to confirm shape**

Read [pipeline.py:660-680](../../../pipeline.py) — verify `momentum_us_result` and `momentum_kr_result` variables are in scope at the call site (they should be from Step 4c2 above).

- [ ] **Step 3: Augment the call**

Replace the existing `generate_lifecycle_pages(...)` call with:

```python
from lifecycle_report import generate_lifecycle_pages
_lifecycle_portfolio_tickers = {
    h["ticker"] for h in _parse_portfolio_for_report(portfolio_path)
    if h.get("ticker")
}
_lc_paths = generate_lifecycle_pages(
    us_result=lifecycle_us_result, kr_result=lifecycle_kr_result,
    output_dir=os.path.join(project_dir, "reports"),
    us_state=(lifecycle_us_result or {}).get("state"),
    kr_state=(lifecycle_kr_result or {}).get("state"),
    nav_ctx=_shared_nav,
    portfolio_tickers=_lifecycle_portfolio_tickers,
    momentum_today_us=momentum_us_result,   # NEW — full scanner result dict
    momentum_today_kr=momentum_kr_result,   # NEW
    market_data=market_data,                 # NEW
)
```

`select_top5_buy_candidates`의 `_flatten_scanner_signals`가 scanner_*_result dict 형식을 list로 변환하므로 `momentum_us_result`를 그대로 넘겨도 됨.

- [ ] **Step 4: Run full lifecycle + pipeline tests**

```
python -m pytest tests/test_lifecycle_buy_candidates.py tests/test_lifecycle_report.py tests/test_lifecycle_signal.py tests/test_lifecycle_history.py tests/test_lifecycle_golden.py tests/test_pipeline_momentum_step.py tests/test_pipeline_momentum_wiring.py -x
```
Expected: all pass.

- [ ] **Step 5: Smoke test — local pipeline run**

```
python pipeline.py 2>&1 | tail -40
```
Expected: clean exit, lifecycle US step logs success. (Can NOT use `SKIP_SCANNERS=1` — that skips the momentum scanner whose result we need.)

Then inspect:
```
grep -c "🚀 스캐너 신규\|scanner-only\|_scanner_only" deploy/lifecycle_us_*.html
```
Expected: 0 yet — badge template change comes in Task 8. But the section should render without errors.

- [ ] **Step 6: Commit**

```
git add pipeline.py
git commit -m "feat(top5): pipeline passes scanner result + market_data into lifecycle render"
```

---

## Task 8: Template — `🚀 스캐너 신규` badge

**Files:**
- Modify: `templates/lifecycle_us.html`
- Modify: `tests/test_lifecycle_buy_candidates.py`

Top 5 row의 ticker 셀에서 `c.snapshot._scanner_only`가 true이면 `🚀 스캐너 신규` 칩 표시.

- [ ] **Step 1: Write failing template test**

Append to `tests/test_lifecycle_buy_candidates.py`:

```python
def test_template_renders_scanner_only_badge(tmp_path):
    """Rendered HTML contains the '🚀 스캐너 신규' chip for _scanner_only candidates."""
    import os
    from jinja2 import Environment, FileSystemLoader

    project_dir = os.path.join(os.path.dirname(__file__), "..")
    env = Environment(loader=FileSystemLoader(
        os.path.join(project_dir, "templates")), autoescape=True)
    env.filters["signed_pct"] = lambda x: "—" if x is None else f"{x:+.1f}%"
    env.filters["x_fmt"]      = lambda x: "—" if x is None else f"{x:.1f}×"
    env.filters["trig_age_label"] = lambda d: "—" if d is None else (
        "오늘" if d == 0 else "어제" if d == 1 else f"{d}일전")

    tmpl = env.get_template("lifecycle_us.html")
    ctx = {
        "market": "US", "as_of": "2026-05-22", "engine_version": "score_v1",
        "active_nav": "lifecycle_us",
        "snapshots_list": [], "transitions": [], "skipped": [],
        "active_set_size": 1, "summary": {"counts": {}}, "score_tier_bands": {},
        "lifecycle_thresholds": {},
        "top5_candidates": [{
            "ticker": "LRCX", "is_portfolio": False,
            "snapshot": {"setup": "TREND_OK", "decision": "ENTER",
                          "_scanner_only": True,
                          "raw": {"close": 1050, "rsi14": 64,
                                  "dist_ema9_pct": 3.1, "volume_ratio": 1.2,
                                  "risk_tags": []},
                          "rs_delta_pct": 8.0},
            "base_score": 9.33, "momentum_bonus": 4, "rs_bonus": 2,
            "final_score": 15.33, "size_hint_label": "신규 50%",
        }],
        "top5_count": 1, "top5_max": 5, "top5_threshold": 5.0,
    }
    html = tmpl.render(**ctx)
    assert "LRCX" in html
    assert "🚀 스캐너 신규" in html or "scanner-only" in html
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_template_renders_scanner_only_badge -xvs
```
Expected: FAIL — "🚀 스캐너 신규" or "scanner-only" not in HTML.

- [ ] **Step 3: Add CSS + badge to template**

In `templates/lifecycle_us.html`, locate the `<style>` block (around L255-271) and inside, before the closing `</style>`, append:

```css
  .badge.scanner-only-badge { display: inline-block; padding: 0.1rem 0.4rem;
                                margin-left: 0.3rem; border-radius: 4px;
                                background: #cce5ff; color: #004085; font-size: 0.85em; }
```

Then locate the ticker cell (around L298-301):

```html
          <td>
            <strong>{{ c.ticker }}</strong>
            {% if c.is_portfolio %}<span class="badge portfolio-badge">🏦 보유 중</span>{% endif %}
          </td>
```

Replace with:

```html
          <td>
            <strong>{{ c.ticker }}</strong>
            {% if c.is_portfolio %}<span class="badge portfolio-badge">🏦 보유 중</span>{% endif %}
            {% if c.snapshot._scanner_only %}<span class="badge scanner-only-badge">🚀 스캐너 신규</span>{% endif %}
          </td>
```

- [ ] **Step 4: Run test to verify it passes**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_template_renders_scanner_only_badge -xvs
```
Expected: PASS.

- [ ] **Step 5: Run lifecycle template/golden tests for regression**

```
python -m pytest tests/test_lifecycle_buy_candidates.py tests/test_lifecycle_report.py tests/test_lifecycle_golden.py tests/test_generate_site_lifecycle.py tests/test_lifecycle_report_nav.py -x
```
Expected: all pass. If `test_lifecycle_golden.py` produces a snapshot diff (only if golden fixtures embed a top5 row), update per project convention (likely manual fixture edit since the change is additive).

- [ ] **Step 6: Commit**

```
git add templates/lifecycle_us.html tests/test_lifecycle_buy_candidates.py
git commit -m "feat(top5): add scanner-only badge to Top 5 row"
```

---

## Task 9: CLAUDE.md — plans list update

**Files:**
- Modify: `CLAUDE.md`

진행 중인 계획 리스트에 한 줄 추가.

- [ ] **Step 1: Locate the plans list**

```
grep -n "진행 중인 계획" CLAUDE.md
```

- [ ] **Step 2: Append new line in the plans list section**

Add (preserving existing markdown bullet style — insert after the existing "Lifecycle Top 5 Buy Candidates" line):

```markdown
- [Lifecycle Top 5 Universe Expansion](docs/superpowers/plans/2026-05-22-top5-universe-expansion.md) — Top 5 후보 풀에 오늘 momentum 스캐너 결과 직접 합치기 (active_set 밖 ticker 포함) · `lifecycle_signal.compute_single_snapshot` 헬퍼 추출 후 selector가 momentum-only ticker를 즉석 합성 snapshot으로 pool에 추가 · `🚀 스캐너 신규` 배지 · 5-stage 파이프라인 / lifecycle history 무영향 · KR/Telegram 후속
```

- [ ] **Step 3: Commit**

```
git add CLAUDE.md
git commit -m "docs(claude): add top5 universe expansion plan to in-progress list"
```

---

## Final verification

- [ ] **Run full lifecycle + momentum + pipeline regression suite**

```
python -m pytest tests/test_compute_single_snapshot.py tests/test_lifecycle_buy_candidates.py tests/test_lifecycle_signal.py tests/test_lifecycle_history.py tests/test_lifecycle_report.py tests/test_lifecycle_golden.py tests/test_lifecycle_e2e.py tests/test_momentum_scanner.py tests/test_momentum_signal.py tests/test_momentum_history.py tests/test_pipeline_momentum_step.py tests/test_pipeline_momentum_wiring.py -x
```
Expected: all pass.

- [ ] **Smoke run the pipeline (full, with momentum scanner)**

```
python pipeline.py
```
Expected: clean exit, no exceptions. Inspect:

```
grep "🚀 스캐너 신규\|scanner-only" deploy/lifecycle_us_*.html
```
Expected: at least one match if today's scanner has any M+/EM tickers outside active_set. If zero matches, that's also acceptable (it just means today every scanner ticker is already in active_set or none scored above threshold).

Check Top 5 section ticker list against `deploy/momentum_us_*.html` scanner page — momentum scanner M+/EM tickers should appear in Top 5 (with badge) unless filtered by threshold/BROKEN.

- [ ] **PR / merge to master**

Standard PR flow per project convention.

---

## Self-review notes (for the executing engineer)

- **No autotrading**: this is display-only. Never wire `size_hint_label` to order placement.
- **History persistence**: `_scanner_only` snapshots NEVER reach `save_lifecycle_history`. They live only inside the Top 5 selector's pool. Don't add them to `result["snapshots"]`.
- **Yesterday None-safety**: Task 3 normalizes `yesterday=None` to an empty raw dict so Phase A trigger helpers (`_is_early_trigger`, `_is_confirmed_trigger`) which call `yesterday.get(...)` remain safe. Trigger resolves to WAIT — by design, since momentum-only tickers have no prior context.
- **Drift score parity**: Active_set tickers preserve the 3-day-close window via `_y_snap_list_for_drift`. Momentum-only callers pass None → just today's close. Drift score may be slightly lower for momentum-only tickers; that's expected (less history = less confidence).
- **KR scope**: `momentum_today_kr` kwarg is plumbed but `lifecycle_kr.html` doesn't reference `_scanner_only` yet. Harmless — KR template ignores the badge. KR Top 5 itself is out of scope per existing plan.
- **Threshold 5.0**: unchanged. Momentum-only ticker max realistic score ≈ TREND_OK drift_score×14/9 (~9-14) + M3(+4) + RS>10(+3) = 16-21. Well above threshold.
- **Pipeline call site `market_data`**: passed as the same `market_data` dict already used by lifecycle steps; no re-fetch.
