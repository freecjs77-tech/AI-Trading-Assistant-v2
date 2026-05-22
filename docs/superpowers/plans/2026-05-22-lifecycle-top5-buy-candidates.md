# Lifecycle Top 5 Buy Candidates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lifecycle US 페이지 최상단에 "🎯 오늘의 매수 후보 (보유 추가 포함) — Top 5" 섹션을 추가. 기존 lifecycle snapshot + 오늘의 momentum scanner 결과 + RS delta를 합쳐 hybrid 점수로 ranking → 상위 5종목 표시.

**Architecture:** 신규 모듈 `lifecycle_buy_candidates.py`가 ranking 로직을 캡슐화. `lifecycle_report.py::_render`가 portfolio_tickers + momentum_history를 받아 모듈을 호출하고 template ctx에 결과 주입. 글로벌 lifecycle signal/history 로직은 무변경.

**Tech Stack:** Python 3.10+, Jinja2 (기존 사용), pytest (기존 사용), 신규 의존성 없음. 모든 입력은 dict/list (의존성 가볍게).

---

## File Structure

**Create:**
- `lifecycle_buy_candidates.py` — ranking + scoring 로직 모듈 (pure functions)
- `tests/test_lifecycle_buy_candidates.py` — TDD 단위 + 통합 테스트

**Modify:**
- `lifecycle_signal.py:783` — `run_lifecycle` 반환 dict에 `momentum_history` 추가
- `lifecycle_report.py:296` — `_render` 시그니처에 `portfolio_tickers` 추가, 본문에 `select_top5_buy_candidates` 호출 + ctx 주입
- `lifecycle_report.py:349` — `generate_lifecycle_pages` 시그니처에 `portfolio_tickers` 추가
- `pipeline.py:443-462` — `_parse_portfolio_for_report` 결과의 ticker 집합을 `generate_lifecycle_pages` 호출에 전달
- `templates/lifecycle_us.html` — narrative 박스 직후, 5-stage 파이프라인 직전에 새 섹션 삽입
- `tests/test_lifecycle_report.py` (있으면 — 없으면 신규 케이스만 추가) — `_render` 통합 테스트 보강

**Out of scope (이번 PR):**
- `templates/lifecycle_kr.html` (KR 시장)
- Telegram brief 통합
- 자동매매 / size 자동 적용
- Top 5 history JSON 저장

---

## Task 1: lifecycle_buy_candidates.py — `normalize_base_score`

**Files:**
- Create: `lifecycle_buy_candidates.py`
- Test: `tests/test_lifecycle_buy_candidates.py`

각 setup 타입별 lifecycle score를 0~14 스케일로 정규화. PULLBACK/BASE_FORMING은 trigger_score (이미 0~14), TREND_OK는 drift_score × 14/9, EXTENDED는 `_raw_score` × 14/9 (veto된 drift score).

- [ ] **Step 1: Write failing tests**

`tests/test_lifecycle_buy_candidates.py`:
```python
"""Tests for lifecycle_buy_candidates module."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_normalize_base_score_pullback_uses_trigger_score():
    """PULLBACK setup → trigger score 그대로 0~14."""
    from lifecycle_buy_candidates import normalize_base_score
    snap = {"setup": "PULLBACK", "score": 6, "score_track": "trigger"}
    assert normalize_base_score(snap) == 6.0


def test_normalize_base_score_base_forming_uses_trigger_score():
    from lifecycle_buy_candidates import normalize_base_score
    snap = {"setup": "BASE_FORMING", "score": 9, "score_track": "trigger"}
    assert normalize_base_score(snap) == 9.0


def test_normalize_base_score_trend_ok_scales_drift_to_14():
    """TREND_OK drift score 6 → 6 × 14/9 ≈ 9.33."""
    from lifecycle_buy_candidates import normalize_base_score
    snap = {"setup": "TREND_OK", "score": 6, "score_track": "drift"}
    result = normalize_base_score(snap)
    assert abs(result - (6 * 14 / 9)) < 0.01


def test_normalize_base_score_extended_uses_raw_score():
    """EXTENDED veto → _raw_score scaled drift→trigger."""
    from lifecycle_buy_candidates import normalize_base_score
    snap = {"setup": "EXTENDED", "score": None, "_raw_score": 5,
            "_raw_score_track": "drift"}
    result = normalize_base_score(snap)
    assert abs(result - (5 * 14 / 9)) < 0.01


def test_normalize_base_score_missing_returns_zero():
    """No score available → 0."""
    from lifecycle_buy_candidates import normalize_base_score
    assert normalize_base_score({"setup": "TREND_OK", "score": None,
                                   "_raw_score": None}) == 0.0
    assert normalize_base_score({}) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_lifecycle_buy_candidates.py -xvs
```
Expected: FAIL with `ModuleNotFoundError: No module named 'lifecycle_buy_candidates'`.

- [ ] **Step 3: Write minimal implementation**

`lifecycle_buy_candidates.py`:
```python
"""Top 5 Buy Candidates — hybrid ranking module.

Combines lifecycle setup score (normalized to 0~14) + today's momentum
scanner tier bonus + RS vs market bonus. See spec
docs/superpowers/specs/2026-05-22-lifecycle-top5-buy-candidates-design.md.
"""
from __future__ import annotations

import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


_DRIFT_MAX = 9
_TRIGGER_MAX = 14


def normalize_base_score(snapshot: dict) -> float:
    """Return lifecycle score on 0~14 scale, regardless of original track.

    PULLBACK / BASE_FORMING: snapshot.score is on trigger scale (0~14) — return as-is.
    TREND_OK: snapshot.score is on drift scale (0~9) — scale to 14.
    EXTENDED: veto'd; use snapshot._raw_score (drift) and scale to 14.
    Any other / missing: 0.
    """
    if not snapshot:
        return 0.0
    setup = snapshot.get("setup")
    if setup in ("PULLBACK", "BASE_FORMING"):
        s = snapshot.get("score")
        return float(s) if s is not None else 0.0
    if setup == "TREND_OK":
        s = snapshot.get("score")
        if s is None:
            return 0.0
        return float(s) * _TRIGGER_MAX / _DRIFT_MAX
    if setup == "EXTENDED":
        s = snapshot.get("_raw_score")
        if s is None:
            return 0.0
        return float(s) * _TRIGGER_MAX / _DRIFT_MAX
    return 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_lifecycle_buy_candidates.py -xvs
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```
git add lifecycle_buy_candidates.py tests/test_lifecycle_buy_candidates.py
git commit -m "feat(top5): normalize_base_score for hybrid ranking"
```

---

## Task 2: `compute_momentum_bonus` + `compute_rs_bonus`

**Files:**
- Modify: `lifecycle_buy_candidates.py`
- Modify: `tests/test_lifecycle_buy_candidates.py`

오늘의 momentum scanner stage (M3/M2/M1/EM) → bonus +4/+3/+2/+1, 그 외 0. rs_delta_pct → >10:+3, >5:+2, >0:+1, 그 외 0.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_lifecycle_buy_candidates.py`:
```python
def test_momentum_bonus_mapping():
    from lifecycle_buy_candidates import compute_momentum_bonus
    assert compute_momentum_bonus({"stage": "MOMENTUM_3"}) == 4
    assert compute_momentum_bonus({"stage": "MOMENTUM_2"}) == 3
    assert compute_momentum_bonus({"stage": "MOMENTUM_1"}) == 2
    assert compute_momentum_bonus({"stage": "EM"}) == 1
    assert compute_momentum_bonus({"stage": None}) == 0
    assert compute_momentum_bonus({}) == 0
    assert compute_momentum_bonus(None) == 0


def test_rs_bonus_thresholds():
    from lifecycle_buy_candidates import compute_rs_bonus
    assert compute_rs_bonus(15.0) == 3
    assert compute_rs_bonus(10.01) == 3
    assert compute_rs_bonus(10.0) == 2     # boundary — 10.0 is NOT > 10
    assert compute_rs_bonus(7.0) == 2
    assert compute_rs_bonus(5.01) == 2
    assert compute_rs_bonus(5.0) == 1      # boundary — 5.0 is NOT > 5
    assert compute_rs_bonus(2.0) == 1
    assert compute_rs_bonus(0.01) == 1
    assert compute_rs_bonus(0.0) == 0
    assert compute_rs_bonus(-3.0) == 0
    assert compute_rs_bonus(None) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_momentum_bonus_mapping tests/test_lifecycle_buy_candidates.py::test_rs_bonus_thresholds -xvs
```
Expected: FAIL with `ImportError: cannot import name 'compute_momentum_bonus'`.

- [ ] **Step 3: Write minimal implementation**

Append to `lifecycle_buy_candidates.py`:
```python
_MOMENTUM_BONUS = {
    "MOMENTUM_3": 4,
    "MOMENTUM_2": 3,
    "MOMENTUM_1": 2,
    "EM": 1,
}


def compute_momentum_bonus(momentum_today: dict | None) -> int:
    """Map today's momentum scanner stage to bonus points.

    momentum_today is the per-ticker entry from
    scanner_momentum_us_history.json data[<ticker>][<today>] dict,
    or None when the ticker had no momentum entry today.
    """
    if not momentum_today:
        return 0
    return _MOMENTUM_BONUS.get(momentum_today.get("stage"), 0)


def compute_rs_bonus(rs_delta_pct: float | None) -> int:
    """rs_delta_pct (vs market): >10:+3 / >5:+2 / >0:+1 / else 0.

    Boundary semantics: strictly greater than threshold. e.g. 5.0 → +1 (not +2).
    """
    if rs_delta_pct is None:
        return 0
    try:
        v = float(rs_delta_pct)
    except (TypeError, ValueError):
        return 0
    if v > 10:
        return 3
    if v > 5:
        return 2
    if v > 0:
        return 1
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_lifecycle_buy_candidates.py -xvs
```
Expected: 7 passed (cumulative).

- [ ] **Step 5: Commit**

```
git add lifecycle_buy_candidates.py tests/test_lifecycle_buy_candidates.py
git commit -m "feat(top5): momentum_bonus + rs_bonus"
```

---

## Task 3: `compute_final_score` — integrate three components

**Files:**
- Modify: `lifecycle_buy_candidates.py`
- Modify: `tests/test_lifecycle_buy_candidates.py`

Snapshot + 오늘의 momentum entry를 받아 `{final_score, base_score, momentum_bonus, rs_bonus}` 반환. rs_delta_pct는 snapshot 또는 score_payload에서.

- [ ] **Step 1: Write failing tests**

Append:
```python
def test_compute_final_score_pullback_with_momentum():
    """PULLBACK score 5 + EM bonus 1 + RS 7%p (+2) = 8."""
    from lifecycle_buy_candidates import compute_final_score
    snap = {"setup": "PULLBACK", "score": 5, "score_track": "trigger",
            "rs_delta_pct": 7.0}
    momentum = {"stage": "EM"}
    result = compute_final_score(snap, momentum)
    assert result["base_score"] == 5.0
    assert result["momentum_bonus"] == 1
    assert result["rs_bonus"] == 2
    assert result["final_score"] == 8.0


def test_compute_final_score_extended_no_penalty():
    """EXTENDED + M3 + strong RS → very high score (no penalty per spec §3)."""
    from lifecycle_buy_candidates import compute_final_score
    snap = {"setup": "EXTENDED", "score": None, "_raw_score": 6,
            "_raw_score_track": "drift", "rs_delta_pct": 12.5}
    momentum = {"stage": "MOMENTUM_3"}
    result = compute_final_score(snap, momentum)
    # base = 6 * 14/9 ≈ 9.33; +4 (M3); +3 (RS>10) = 16.33
    assert abs(result["base_score"] - (6 * 14 / 9)) < 0.01
    assert result["momentum_bonus"] == 4
    assert result["rs_bonus"] == 3
    assert abs(result["final_score"] - (6 * 14 / 9 + 7)) < 0.01


def test_compute_final_score_no_momentum_entry():
    """ticker not in today's momentum → momentum_bonus 0."""
    from lifecycle_buy_candidates import compute_final_score
    snap = {"setup": "TREND_OK", "score": 4, "score_track": "drift",
            "rs_delta_pct": 3.0}
    result = compute_final_score(snap, None)
    assert result["momentum_bonus"] == 0
    assert result["rs_bonus"] == 1
    assert abs(result["base_score"] - (4 * 14 / 9)) < 0.01
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_compute_final_score_pullback_with_momentum -xvs
```
Expected: FAIL with `ImportError: cannot import name 'compute_final_score'`.

- [ ] **Step 3: Write implementation**

Append:
```python
def compute_final_score(snapshot: dict, momentum_today: dict | None) -> dict:
    """Compute hybrid ranking score breakdown.

    Returns dict with keys: base_score, momentum_bonus, rs_bonus, final_score.
    """
    base = normalize_base_score(snapshot)
    m_bonus = compute_momentum_bonus(momentum_today)
    rs_bonus = compute_rs_bonus((snapshot or {}).get("rs_delta_pct"))
    return {
        "base_score":     base,
        "momentum_bonus": m_bonus,
        "rs_bonus":       rs_bonus,
        "final_score":    base + m_bonus + rs_bonus,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_lifecycle_buy_candidates.py -xvs
```
Expected: 10 passed.

- [ ] **Step 5: Commit**

```
git add lifecycle_buy_candidates.py tests/test_lifecycle_buy_candidates.py
git commit -m "feat(top5): compute_final_score combining base/momentum/RS"
```

---

## Task 4: `build_candidate_pool` — exclude BROKEN, mark portfolio

**Files:**
- Modify: `lifecycle_buy_candidates.py`
- Modify: `tests/test_lifecycle_buy_candidates.py`

`result['snapshots']` 입력 → BROKEN 제외 → portfolio_tickers에 해당하면 `is_portfolio=True` 마킹 → list of candidate dicts 반환.

- [ ] **Step 1: Write failing tests**

Append:
```python
def test_build_candidate_pool_excludes_broken():
    from lifecycle_buy_candidates import build_candidate_pool
    snapshots = {
        "AAA": {"setup": "PULLBACK", "score": 5},
        "BBB": {"setup": "BROKEN", "score": None},
        "CCC": {"setup": "TREND_OK", "score": 6, "score_track": "drift"},
        "DDD": {"setup": "EXTENDED", "score": None, "_raw_score": 5},
    }
    pool = build_candidate_pool(snapshots, portfolio_tickers=set())
    tickers = {c["ticker"] for c in pool}
    assert tickers == {"AAA", "CCC", "DDD"}  # BBB excluded


def test_build_candidate_pool_marks_portfolio():
    from lifecycle_buy_candidates import build_candidate_pool
    snapshots = {
        "AAPL": {"setup": "TREND_OK", "score": 5, "score_track": "drift"},
        "INTC": {"setup": "PULLBACK", "score": 4, "score_track": "trigger"},
    }
    pool = build_candidate_pool(snapshots, portfolio_tickers={"AAPL"})
    by_ticker = {c["ticker"]: c for c in pool}
    assert by_ticker["AAPL"]["is_portfolio"] is True
    assert by_ticker["INTC"]["is_portfolio"] is False


def test_build_candidate_pool_attaches_snapshot():
    """Each candidate carries the full snapshot dict (so downstream can read raw)."""
    from lifecycle_buy_candidates import build_candidate_pool
    snapshots = {"AAA": {"setup": "PULLBACK", "score": 5,
                          "raw": {"close": 100.0, "rsi14": 65}}}
    pool = build_candidate_pool(snapshots, portfolio_tickers=set())
    assert pool[0]["snapshot"]["raw"]["close"] == 100.0
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_build_candidate_pool_excludes_broken -xvs
```
Expected: FAIL with `ImportError: cannot import name 'build_candidate_pool'`.

- [ ] **Step 3: Write implementation**

Append:
```python
def build_candidate_pool(snapshots: dict, portfolio_tickers: set) -> list[dict]:
    """Pool = snapshots minus BROKEN, with portfolio membership marked.

    Returns list of dicts: {ticker, snapshot, is_portfolio}.
    """
    portfolio_tickers = portfolio_tickers or set()
    pool: list[dict] = []
    for ticker, snap in (snapshots or {}).items():
        if not snap:
            continue
        if snap.get("setup") == "BROKEN":
            continue
        pool.append({
            "ticker":       ticker,
            "snapshot":     snap,
            "is_portfolio": ticker in portfolio_tickers,
        })
    return pool
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_lifecycle_buy_candidates.py -xvs
```
Expected: 13 passed.

- [ ] **Step 5: Commit**

```
git add lifecycle_buy_candidates.py tests/test_lifecycle_buy_candidates.py
git commit -m "feat(top5): build_candidate_pool excluding BROKEN"
```

---

## Task 5: `rank_top_n` — sort, threshold, cap

**Files:**
- Modify: `lifecycle_buy_candidates.py`
- Modify: `tests/test_lifecycle_buy_candidates.py`

Candidates list + per-ticker momentum entries → score 계산 후 final_score desc + rs_delta_pct desc tiebreak → score ≥ 5 필터 → 상위 N (default 5).

- [ ] **Step 1: Write failing tests**

Append:
```python
def test_rank_top_n_sorts_desc_caps_at_5():
    from lifecycle_buy_candidates import rank_top_n
    pool = [
        {"ticker": "A", "snapshot": {"setup": "PULLBACK", "score": 10, "rs_delta_pct": 5.0}, "is_portfolio": False},
        {"ticker": "B", "snapshot": {"setup": "PULLBACK", "score": 8,  "rs_delta_pct": 12.0}, "is_portfolio": False},
        {"ticker": "C", "snapshot": {"setup": "PULLBACK", "score": 6,  "rs_delta_pct": 7.0}, "is_portfolio": False},
        {"ticker": "D", "snapshot": {"setup": "PULLBACK", "score": 5,  "rs_delta_pct": 3.0}, "is_portfolio": False},
        {"ticker": "E", "snapshot": {"setup": "PULLBACK", "score": 4,  "rs_delta_pct": 1.0}, "is_portfolio": False},
        {"ticker": "F", "snapshot": {"setup": "PULLBACK", "score": 3,  "rs_delta_pct": 0.5}, "is_portfolio": False},
    ]
    momentum_data = {}  # no momentum bonuses for any
    ranked = rank_top_n(pool, momentum_data, threshold=5, cap=5)
    assert [c["ticker"] for c in ranked] == ["B", "A", "C", "D", "E"]
    # B: 8 + 0 + 3 (RS>10) = 11
    # A: 10 + 0 + 1 (RS>0) = 11 -- tied with B
    # → B wins tiebreak (higher rs_delta_pct)
    # C: 6 + 0 + 2 = 8
    # D: 5 + 0 + 1 = 6
    # E: 4 + 0 + 1 = 5
    # F: 3 + 0 + 1 = 4 → below threshold


def test_rank_top_n_threshold_excludes_low_scores():
    from lifecycle_buy_candidates import rank_top_n
    pool = [
        {"ticker": "X", "snapshot": {"setup": "PULLBACK", "score": 2, "rs_delta_pct": 1.0}, "is_portfolio": False},
        {"ticker": "Y", "snapshot": {"setup": "PULLBACK", "score": 3, "rs_delta_pct": 0.0}, "is_portfolio": False},
    ]
    # X: 2+0+1=3 ; Y: 3+0+0=3 → both below threshold 5
    ranked = rank_top_n(pool, {}, threshold=5, cap=5)
    assert ranked == []


def test_rank_top_n_attaches_score_breakdown():
    """Each ranked entry includes final_score + breakdown for display."""
    from lifecycle_buy_candidates import rank_top_n
    pool = [{"ticker": "AAA",
             "snapshot": {"setup": "PULLBACK", "score": 6, "rs_delta_pct": 7.0},
             "is_portfolio": True}]
    momentum_data = {"AAA": {"stage": "MOMENTUM_2"}}
    ranked = rank_top_n(pool, momentum_data, threshold=5, cap=5)
    assert len(ranked) == 1
    entry = ranked[0]
    assert entry["final_score"] == 11.0  # 6 + 3 (M2) + 2 (RS>5)
    assert entry["base_score"] == 6.0
    assert entry["momentum_bonus"] == 3
    assert entry["rs_bonus"] == 2
    assert entry["is_portfolio"] is True
    assert entry["ticker"] == "AAA"
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_rank_top_n_sorts_desc_caps_at_5 -xvs
```
Expected: FAIL with `ImportError: cannot import name 'rank_top_n'`.

- [ ] **Step 3: Write implementation**

Append:
```python
def rank_top_n(pool: list[dict], momentum_data: dict, *,
                threshold: float = 5.0, cap: int = 5) -> list[dict]:
    """Rank candidates, filter by threshold, cap at top N.

    Args:
        pool: list of {ticker, snapshot, is_portfolio} from build_candidate_pool.
        momentum_data: {ticker: today_entry_dict} from
            scanner_momentum_us_history.json data → today section.
            Pass {} if no momentum data available.
        threshold: minimum final_score to include (default 5.0).
        cap: maximum number of candidates returned (default 5).

    Returns: list of dicts with keys: ticker, snapshot, is_portfolio,
        base_score, momentum_bonus, rs_bonus, final_score.
        Sorted by final_score desc, then rs_delta_pct desc.
    """
    scored: list[dict] = []
    for entry in pool:
        snap = entry["snapshot"]
        m_today = momentum_data.get(entry["ticker"])
        breakdown = compute_final_score(snap, m_today)
        if breakdown["final_score"] < threshold:
            continue
        scored.append({
            "ticker":         entry["ticker"],
            "snapshot":       snap,
            "is_portfolio":   entry["is_portfolio"],
            "base_score":     breakdown["base_score"],
            "momentum_bonus": breakdown["momentum_bonus"],
            "rs_bonus":       breakdown["rs_bonus"],
            "final_score":    breakdown["final_score"],
        })
    scored.sort(key=lambda c: (-c["final_score"],
                                 -(c["snapshot"].get("rs_delta_pct") or 0)))
    return scored[:cap]
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_lifecycle_buy_candidates.py -xvs
```
Expected: 16 passed.

- [ ] **Step 5: Commit**

```
git add lifecycle_buy_candidates.py tests/test_lifecycle_buy_candidates.py
git commit -m "feat(top5): rank_top_n with threshold + cap"
```

---

## Task 6: `select_top5_buy_candidates` — orchestrator + display formatting

**Files:**
- Modify: `lifecycle_buy_candidates.py`
- Modify: `tests/test_lifecycle_buy_candidates.py`

엔트리 포인트. snapshots + portfolio_tickers + momentum_history + today를 받아 ranked list와 메타정보를 반환. 사이즈 hint 라벨 ("신규 50%" / "추가 25%" 등) 도 여기서 결정.

- [ ] **Step 1: Write failing tests**

Append:
```python
def test_select_top5_orchestrator_end_to_end():
    """E2E mini scenario: 3 candidates, only 2 pass threshold."""
    from lifecycle_buy_candidates import select_top5_buy_candidates
    snapshots = {
        "AAPL": {"setup": "TREND_OK", "score": 6, "score_track": "drift",
                  "rs_delta_pct": 8.0},
        "INTC": {"setup": "PULLBACK", "score": 5, "score_track": "trigger",
                  "rs_delta_pct": 6.0},
        "WEAK": {"setup": "PULLBACK", "score": 1, "rs_delta_pct": 0.0},
    }
    momentum_history = {"data": {"AAPL": {"2026-05-21": {"stage": "MOMENTUM_2"}}}}
    result = select_top5_buy_candidates(
        snapshots=snapshots,
        portfolio_tickers={"AAPL"},
        momentum_history=momentum_history,
        today="2026-05-21",
    )
    assert result["max"] == 5
    assert result["count"] == 2  # AAPL + INTC; WEAK below threshold
    tickers = [c["ticker"] for c in result["candidates"]]
    assert "AAPL" in tickers
    assert "INTC" in tickers
    assert "WEAK" not in tickers


def test_select_top5_size_hint_labels_extended_portfolio():
    """size_hint string varies by EXTENDED + portfolio state."""
    from lifecycle_buy_candidates import select_top5_buy_candidates
    snapshots = {
        "EXT_NEW":  {"setup": "EXTENDED", "score": None, "_raw_score": 6,
                       "_raw_score_track": "drift", "rs_delta_pct": 12.0},
        "EXT_HOLD": {"setup": "EXTENDED", "score": None, "_raw_score": 6,
                       "_raw_score_track": "drift", "rs_delta_pct": 12.0},
        "NORM_NEW":  {"setup": "PULLBACK", "score": 8, "rs_delta_pct": 7.0},
        "NORM_HOLD": {"setup": "PULLBACK", "score": 8, "rs_delta_pct": 7.0},
    }
    result = select_top5_buy_candidates(
        snapshots=snapshots,
        portfolio_tickers={"EXT_HOLD", "NORM_HOLD"},
        momentum_history={"data": {}}, today="2026-05-21",
    )
    by_ticker = {c["ticker"]: c for c in result["candidates"]}
    assert by_ticker["EXT_NEW"]["size_hint_label"] == "신규 25%"
    assert by_ticker["EXT_HOLD"]["size_hint_label"] == "추가 25%"
    assert by_ticker["NORM_NEW"]["size_hint_label"] == "신규 50%"
    assert by_ticker["NORM_HOLD"]["size_hint_label"] == "추가 50%"


def test_select_top5_empty_snapshots():
    """No snapshots → count=0, candidates=[]."""
    from lifecycle_buy_candidates import select_top5_buy_candidates
    result = select_top5_buy_candidates(
        snapshots={}, portfolio_tickers=set(),
        momentum_history={"data": {}}, today="2026-05-21",
    )
    assert result["count"] == 0
    assert result["candidates"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_select_top5_orchestrator_end_to_end -xvs
```
Expected: FAIL with `ImportError: cannot import name 'select_top5_buy_candidates'`.

- [ ] **Step 3: Write implementation**

Append:
```python
def _extract_today_momentum(momentum_history: dict, today: str) -> dict:
    """Pull {ticker: today_entry_dict} from scanner_momentum_*_history.json.

    History shape (from momentum_history.py):
        {"_meta": {...}, "data": {ticker: {date_str: entry, ...}}}
    """
    data = (momentum_history or {}).get("data") or {}
    out: dict = {}
    for ticker, by_date in data.items():
        if not isinstance(by_date, dict):
            continue
        entry = by_date.get(today)
        if entry:
            out[ticker] = entry
    return out


def _size_hint_label(setup: str, is_portfolio: bool) -> str:
    """Display label: 신규/추가 + percent based on EXTENDED override."""
    prefix = "추가" if is_portfolio else "신규"
    pct = "25%" if setup == "EXTENDED" else "50%"
    return f"{prefix} {pct}"


def select_top5_buy_candidates(*, snapshots: dict, portfolio_tickers: set,
                                  momentum_history: dict, today: str,
                                  threshold: float = 5.0, cap: int = 5) -> dict:
    """One-call entry. Returns dict ready for template ctx injection.

    Returns:
        {
            "candidates": list of ranked dicts (with size_hint_label, snapshot, scores),
            "count":      len(candidates),
            "max":        cap,
            "threshold":  threshold,
        }
    """
    pool = build_candidate_pool(snapshots, portfolio_tickers)
    momentum_today = _extract_today_momentum(momentum_history, today)
    ranked = rank_top_n(pool, momentum_today, threshold=threshold, cap=cap)

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

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_lifecycle_buy_candidates.py -xvs
```
Expected: 19 passed.

- [ ] **Step 5: Commit**

```
git add lifecycle_buy_candidates.py tests/test_lifecycle_buy_candidates.py
git commit -m "feat(top5): select_top5_buy_candidates orchestrator + size_hint_label"
```

---

## Task 7: `run_lifecycle` returns `momentum_history`; `_render` injects ctx

**Files:**
- Modify: `lifecycle_signal.py:774-785` (`run_lifecycle` return dict)
- Modify: `lifecycle_report.py:296-298` (`_render` signature) + body (lines 339-345)
- Modify: `lifecycle_report.py:349-373` (`generate_lifecycle_pages` signature) + body
- Modify: `tests/test_lifecycle_buy_candidates.py` — integration test

`run_lifecycle`가 `momentum_state` 를 result에 포함. `generate_lifecycle_pages`/`_render`가 `portfolio_tickers` 인자를 받아 `select_top5_buy_candidates` 호출 → ctx에 `top5_*` 주입.

- [ ] **Step 1: Write failing integration test**

Append to `tests/test_lifecycle_buy_candidates.py`:
```python
def test_render_injects_top5_into_ctx(monkeypatch, tmp_path):
    """_render must call select_top5 and inject ctx vars."""
    import os, json
    import lifecycle_report as lr

    captured_ctx = {}

    def fake_render(self, **ctx):
        captured_ctx.update(ctx)
        return "<html></html>"

    # Monkeypatch the Jinja2 template.render
    from jinja2 import Template
    monkeypatch.setattr(Template, "render", fake_render)

    # Minimal result fixture
    result = {
        "as_of": "2026-05-21", "market": "US",
        "snapshots": {
            "AAA": {"setup": "PULLBACK", "score": 8, "score_track": "trigger",
                     "rs_delta_pct": 6.0,
                     "raw": {"close": 100, "rsi14": 65, "dist_ema9_pct": 1.0,
                             "volume_ratio": 1.1, "risk_tags": []}},
        },
        "transitions": [], "skipped": [], "active_set_size": 1,
        "market_ret_5d_pct": 0.0,
        "momentum_history": {"data": {}},
        "engine_version": "score_v1",
    }

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    lr._render("US", result, str(out_dir), template_dir=None,
                lifecycle_state={"tickers": {}, "transitions": []},
                portfolio_tickers={"AAA"})

    assert "top5_candidates" in captured_ctx
    assert "top5_count" in captured_ctx
    assert "top5_max" in captured_ctx
    assert captured_ctx["top5_max"] == 5
    assert captured_ctx["top5_count"] == 1
    assert captured_ctx["top5_candidates"][0]["ticker"] == "AAA"
    assert captured_ctx["top5_candidates"][0]["is_portfolio"] is True
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_render_injects_top5_into_ctx -xvs
```
Expected: FAIL — TypeError (`portfolio_tickers` arg unknown) or assertion on missing ctx keys.

- [ ] **Step 3: Modify `lifecycle_signal.py` — extend `run_lifecycle` return**

In `lifecycle_signal.py`, locate the final return dict (`return {... "market_ret_5d_pct": ...}`) and add `momentum_history`:

```python
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
        "momentum_history": momentum_state,   # NEW — for top5 selector
    }
```

- [ ] **Step 4: Modify `lifecycle_report.py::_render`**

Change signature to accept `portfolio_tickers`:

```python
def _render(market: str, result: dict, output_dir: str,
              template_dir: Optional[str], lifecycle_state: Optional[dict],
              nav_ctx: Optional[dict] = None,
              portfolio_tickers: Optional[set] = None) -> str:
```

After the `ctx = build_page_context(result, lifecycle_state=lifecycle_state)` line (around line 331), inject top5:

```python
    # Top 5 Buy Candidates section
    from lifecycle_buy_candidates import select_top5_buy_candidates
    top5 = select_top5_buy_candidates(
        snapshots=result.get("snapshots") or {},
        portfolio_tickers=portfolio_tickers or set(),
        momentum_history=result.get("momentum_history") or {"data": {}},
        today=result["as_of"],
    )
    ctx["top5_candidates"] = top5["candidates"]
    ctx["top5_count"]      = top5["count"]
    ctx["top5_max"]        = top5["max"]
    ctx["top5_threshold"]  = top5["threshold"]
```

- [ ] **Step 5: Modify `lifecycle_report.py::generate_lifecycle_pages`**

Add `portfolio_tickers` arg and pass it through to `_render`:

```python
def generate_lifecycle_pages(*, us_result: Optional[dict],
                                kr_result: Optional[dict],
                                output_dir: str,
                                template_dir: Optional[str] = None,
                                us_state: Optional[dict] = None,
                                kr_state: Optional[dict] = None,
                                nav_ctx: Optional[dict] = None,
                                portfolio_tickers: Optional[set] = None,
                                ) -> dict[str, str]:
    """... [docstring unchanged] ..."""
    out: dict[str, str] = {}
    if us_result and us_result.get("snapshots"):
        out["us"] = _render("US", us_result, output_dir, template_dir,
                              us_state, nav_ctx,
                              portfolio_tickers=portfolio_tickers)
    if kr_result and kr_result.get("snapshots"):
        out["kr"] = _render("KR", kr_result, output_dir, template_dir,
                              kr_state, nav_ctx,
                              portfolio_tickers=portfolio_tickers)
    return out
```

- [ ] **Step 6: Run integration test to verify it passes**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_render_injects_top5_into_ctx -xvs
```
Expected: PASS.

- [ ] **Step 7: Run lifecycle test suite for regression**

```
python -m pytest tests/test_lifecycle_report.py tests/test_lifecycle_buy_candidates.py tests/test_lifecycle_history.py tests/test_lifecycle_signal.py -x
```
Expected: All pass.

- [ ] **Step 8: Commit**

```
git add lifecycle_signal.py lifecycle_report.py tests/test_lifecycle_buy_candidates.py
git commit -m "feat(top5): wire select_top5 into lifecycle _render via momentum_history + portfolio_tickers"
```

---

## Task 8: Template section in `templates/lifecycle_us.html`

**Files:**
- Modify: `templates/lifecycle_us.html`
- Modify: `tests/test_lifecycle_buy_candidates.py` — template rendering test

기존 narrative 박스 직후 / 5-stage 파이프라인 직전에 `<section id="top5-buy-candidates">` 추가. ctx 변수 `top5_candidates`, `top5_count`, `top5_max` 사용.

- [ ] **Step 1: Locate insertion point in template**

`templates/lifecycle_us.html` 구조 (확인된 라인):
- L233-238: `{# 컨셉 박스 #}` (concept-box)
- L240-252: `{# 오늘의 결론 #}` (summary-box) — `<div class="summary-box">...</div>` 종료
- L254: `{% include "_lifecycle_pipeline.html" %}` — 5-stage 파이프라인

**삽입 지점: L252 (summary-box `</div>`) 와 L254 (pipeline include) 사이** — concept-box / 오늘의 결론 다음, 파이프라인 직전.

검증용 grep:
```
grep -n "오늘의 결론\|_lifecycle_pipeline" templates/lifecycle_us.html
```

- [ ] **Step 2: Write failing template rendering test**

Append to `tests/test_lifecycle_buy_candidates.py`:
```python
def test_template_renders_top5_section(tmp_path):
    """Rendered HTML contains the top5 section with expected text + tickers."""
    import os
    from jinja2 import Environment, FileSystemLoader

    project_dir = os.path.join(os.path.dirname(__file__), "..")
    env = Environment(loader=FileSystemLoader(
        os.path.join(project_dir, "templates")), autoescape=True)
    # Custom filters mimicking lifecycle_report._render
    env.filters["signed_pct"] = lambda x: "—" if x is None else f"{x:+.1f}%"
    env.filters["x_fmt"]      = lambda x: "—" if x is None else f"{x:.1f}×"
    env.filters["trig_age_label"] = lambda d: "—" if d is None else (
        "오늘" if d == 0 else "어제" if d == 1 else f"{d}일전")

    tmpl = env.get_template("lifecycle_us.html")
    ctx = {
        "market": "US", "as_of": "2026-05-21", "engine_version": "score_v1",
        "active_nav": "lifecycle_us",
        "snapshots_list": [], "transitions": [], "skipped": [],
        "active_set_size": 1, "summary": {"counts": {}}, "score_tier_bands": {},
        "lifecycle_thresholds": {},
        "top5_candidates": [{
            "ticker": "NVDA", "is_portfolio": True,
            "snapshot": {"setup": "EXTENDED", "decision": "AVOID",
                          "raw": {"close": 1200, "rsi14": 76,
                                  "dist_ema9_pct": 11.5, "volume_ratio": 1.5,
                                  "risk_tags": ["EXTENDED"]},
                          "rs_delta_pct": 12.0},
            "base_score": 9.33, "momentum_bonus": 4, "rs_bonus": 3,
            "final_score": 16.33, "size_hint_label": "추가 25%",
        }],
        "top5_count": 1, "top5_max": 5, "top5_threshold": 5.0,
    }
    html = tmpl.render(**ctx)
    assert "오늘의 매수 후보" in html
    assert "NVDA" in html
    assert "1/5" in html or "(1/5)" in html
    # EXTENDED 종목엔 과열 표시 + 사이즈 25%
    assert "과열" in html or "EXTENDED" in html
    assert "추가 25%" in html
    # Portfolio 종목엔 보유 표시
    assert "보유 중" in html or "🏦" in html
```

- [ ] **Step 3: Run test to verify it fails**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_template_renders_top5_section -xvs
```
Expected: FAIL — "오늘의 매수 후보" or "NVDA" not in rendered HTML.

- [ ] **Step 4: Add template section**

In `templates/lifecycle_us.html`, find the line just BEFORE the first stage section (e.g., `<section class="stage" id="trending">` or similar). Insert this Jinja2 block immediately before it:

```html
{# ── Top 5 Buy Candidates (2026-05-22 spec) ─────────────────── #}
<section id="top5-buy-candidates" class="top5-section">
  <h2>🎯 오늘의 매수 후보 (보유 추가 포함) — Top {{ top5_count }}/{{ top5_max }}</h2>

  {% if top5_count == 0 %}
    <p class="empty-state">
      오늘 매수 후보 없음 — 모든 종목 score &lt; {{ top5_threshold }}
      (시장이 약하거나 강한 setup 부족)
    </p>
  {% else %}
    {% if top5_count < top5_max %}
      <p class="partial-notice">
        오늘은 {{ top5_count }}/{{ top5_max }} — 시장이 약하거나 강한 setup 부족
      </p>
    {% endif %}

    <table class="top5-table">
      <thead>
        <tr>
          <th>#</th><th>Ticker</th><th>Decision</th><th>Setup</th>
          <th>Score</th><th>RS</th><th>키 지표</th><th>사이즈 hint</th>
        </tr>
      </thead>
      <tbody>
      {% for c in top5_candidates %}
        <tr class="top5-row{% if c.snapshot.setup == 'EXTENDED' %} extended-row{% endif %}">
          <td>{{ loop.index }}</td>
          <td>
            <strong>{{ c.ticker }}</strong>
            {% if c.is_portfolio %}<span class="badge portfolio-badge">🏦 보유 중</span>{% endif %}
          </td>
          <td>{{ c.snapshot.decision }}</td>
          <td>
            {{ c.snapshot.setup }}
            {% if c.snapshot.setup == 'EXTENDED' %}<span class="chip overheat-chip">⚠️ 과열</span>{% endif %}
          </td>
          <td>
            <strong>{{ '%.1f' % c.final_score }}</strong>
            <small>= {{ '%.1f' % c.base_score }} + {{ c.momentum_bonus }} + {{ c.rs_bonus }}</small>
          </td>
          <td>{{ c.snapshot.rs_delta_pct | signed_pct }}</td>
          <td>
            RSI {{ '%.0f' % c.snapshot.raw.rsi14 }} ·
            EMA9 {{ c.snapshot.raw.dist_ema9_pct | signed_pct }} ·
            Vol {{ c.snapshot.raw.volume_ratio | x_fmt }}
          </td>
          <td>{{ c.size_hint_label }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    <p class="disclaimer">
      <small>⚠️ 자동매매 아님 — display only. 매수 결정은 사용자 판단. 사이즈는 권장치이며 강제 아님.</small>
    </p>
  {% endif %}
</section>
```

Style guidance: use minimal inline-friendly classes; existing CSS in lifecycle_us.html already covers chip/badge styling. If specific classes (`top5-section`, `top5-row`, `extended-row`, `overheat-chip`, `portfolio-badge`, `partial-notice`, `disclaimer`) need styling, add a small `<style>` block at the top of the new section:

```html
<style>
  .top5-section { margin: 1.5rem 0; padding: 1rem; border-radius: 8px;
                   background: rgba(60, 130, 200, 0.08); }
  .top5-section h2 { margin-top: 0; }
  .top5-table { width: 100%; border-collapse: collapse; }
  .top5-table th, .top5-table td { padding: 0.4rem 0.6rem; text-align: left;
                                     border-bottom: 1px solid rgba(0,0,0,0.08); }
  .top5-row.extended-row { background: rgba(255, 165, 0, 0.06); }
  .chip.overheat-chip { display: inline-block; padding: 0.1rem 0.4rem;
                         margin-left: 0.3rem; border-radius: 4px;
                         background: #fff3cd; color: #856404; font-size: 0.85em; }
  .badge.portfolio-badge { display: inline-block; padding: 0.1rem 0.4rem;
                            margin-left: 0.3rem; border-radius: 4px;
                            background: #d4edda; color: #155724; font-size: 0.85em; }
  .empty-state, .partial-notice { font-style: italic; color: #666; }
  .disclaimer { color: #888; margin-top: 0.5rem; }
</style>
```

- [ ] **Step 5: Run test to verify it passes**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_template_renders_top5_section -xvs
```
Expected: PASS.

- [ ] **Step 6: Run lifecycle template/golden tests for regression**

```
python -m pytest tests/test_lifecycle_report.py tests/test_lifecycle_golden.py tests/test_generate_site_lifecycle.py tests/test_lifecycle_report_nav.py -x
```
Expected: All pass. If `test_lifecycle_golden.py` produces a snapshot diff due to the new section, update the golden fixture by reading the test and regenerating per the project's golden update convention (likely `pytest --golden-update` or manual fixture edit — check the test source for the pattern).

- [ ] **Step 7: Commit**

```
git add templates/lifecycle_us.html tests/test_lifecycle_buy_candidates.py
git commit -m "feat(top5): add Top 5 Buy Candidates section to lifecycle_us.html"
```

---

## Task 9: pipeline.py — pass portfolio_tickers into `generate_lifecycle_pages`

**Files:**
- Modify: `pipeline.py` — find the `generate_lifecycle_pages(...)` call site
- Modify: `tests/test_lifecycle_buy_candidates.py` — pipeline integration smoke

지금 lifecycle 페이지 렌더 호출은 `generate_lifecycle_pages(us_result=..., ...)` 형태. 여기에 `portfolio_tickers={t["ticker"] for t in _parse_portfolio_for_report(portfolio_path)}` 추가.

- [ ] **Step 1: Verify the existing `generate_lifecycle_pages` call**

확인된 위치: `pipeline.py:662-669`:
```python
from lifecycle_report import generate_lifecycle_pages
_lc_paths = generate_lifecycle_pages(
    us_result=lifecycle_us_result, kr_result=lifecycle_kr_result,
    output_dir=os.path.join(project_dir, "reports"),
    us_state=(lifecycle_us_result or {}).get("state"),
    kr_state=(lifecycle_kr_result or {}).get("state"),
    nav_ctx=_shared_nav,
)
```

검증용 grep (라인 번호 변경 시):
```
grep -n "generate_lifecycle_pages" pipeline.py
```

- [ ] **Step 2: Write failing test for portfolio_tickers wiring**

Append to `tests/test_lifecycle_buy_candidates.py`:
```python
def test_pipeline_passes_portfolio_tickers_to_generate(monkeypatch):
    """generate_lifecycle_pages should receive portfolio_tickers=set of all holdings."""
    captured_kwargs = {}

    def fake_generate(**kwargs):
        captured_kwargs.update(kwargs)
        return {}

    import lifecycle_report
    monkeypatch.setattr(lifecycle_report, "generate_lifecycle_pages", fake_generate)

    # Construct a minimal portfolio markdown
    import tempfile, textwrap
    md = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False,
                                       encoding="utf-8")
    md.write(textwrap.dedent("""
        | Ticker | 종목명 | 보유수량 | 평가금액 | 수익금액 | 수익률 |
        |--------|--------|---------|---------|---------|--------|
        | AAPL | 애플 | 100주 | $20,000.00 | +$5,000.00 | +33.33% |
        | NVDA | 엔비디아 | 50주 | $50,000.00 | +$10,000.00 | +25.00% |
    """).strip() + "\n")
    md.close()

    import pipeline
    holdings = pipeline._parse_portfolio_for_report(md.name)
    tickers = {h["ticker"] for h in holdings}
    assert tickers == {"AAPL", "NVDA"}
```

This test only validates the parse — the pipeline.py edit ensures the same set is passed downstream.

- [ ] **Step 3: Run test (should pass — verifies existing parser behavior)**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_pipeline_passes_portfolio_tickers_to_generate -xvs
```
Expected: PASS (just parses).

- [ ] **Step 4: Modify `pipeline.py:662-669` call site**

Replace the existing 8-line block with the augmented version. `portfolio_path` 변수는 같은 함수 스코프에서 이미 사용 중 (예: L496의 `me_holdings_for_bench = _parse_portfolio_for_report(portfolio_path)`).

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
    portfolio_tickers=_lifecycle_portfolio_tickers,   # NEW
)
```

- [ ] **Step 5: Run full lifecycle + buy_candidates suite**

```
python -m pytest tests/test_lifecycle_buy_candidates.py tests/test_lifecycle_report.py tests/test_lifecycle_signal.py tests/test_lifecycle_history.py tests/test_lifecycle_golden.py tests/test_pipeline_momentum_step.py tests/test_pipeline_momentum_wiring.py -x
```
Expected: All pass.

- [ ] **Step 6: Smoke test — local pipeline run with skip_scanners**

```
SKIP_SCANNERS=1 python pipeline.py 2>&1 | grep -i "lifecycle\|top5\|매수 후보"
```
Expected: lifecycle steps log successfully; no errors mentioning top5/buy_candidates.

Then inspect generated `deploy/lifecycle_us_<today>.html`:
```
grep "오늘의 매수 후보\|top5-buy-candidates" deploy/lifecycle_us_*.html | head -3
```
Expected: section is rendered (at least the heading is present).

- [ ] **Step 7: Commit**

```
git add pipeline.py tests/test_lifecycle_buy_candidates.py
git commit -m "feat(top5): pipeline passes portfolio_tickers into lifecycle page render"
```

---

## Task 10: Documentation — CLAUDE.md plans list update

**Files:**
- Modify: `CLAUDE.md` (project root) — "진행 중인 계획" section

기존 plans 리스트 패턴을 따라 새 plan 한 줄 추가.

- [ ] **Step 1: Read current plans list**

```
grep -n "진행 중인 계획" CLAUDE.md
```

- [ ] **Step 2: Add one-line entry to "진행 중인 계획" section**

Add (preserving existing markdown bullet style):

```markdown
- [Lifecycle Top 5 Buy Candidates](docs/superpowers/plans/2026-05-22-lifecycle-top5-buy-candidates.md) — Lifecycle US 페이지 최상단 "🎯 오늘의 매수 후보 (보유 추가 포함) — Top 5" 섹션 · hybrid 점수(base normalized 0~14 + momentum bonus M3:+4~EM:+1 + RS bonus >10:+3~>0:+1) · EXTENDED 포함 · portfolio 종목은 🏦 보유 중 배지 · 기존 5-stage 파이프라인 무영향 · score_active 모드 유지 · KR/Telegram 후속
```

- [ ] **Step 3: Commit**

```
git add CLAUDE.md
git commit -m "docs(claude): add top 5 buy candidates plan to in-progress list"
```

---

## Final verification

- [ ] **Run full momentum + lifecycle regression suite**

```
python -m pytest tests/test_momentum_scanner.py tests/test_momentum_signal.py tests/test_momentum_history.py tests/test_lifecycle_buy_candidates.py tests/test_lifecycle_signal.py tests/test_lifecycle_history.py tests/test_lifecycle_report.py tests/test_lifecycle_golden.py tests/test_lifecycle_e2e.py tests/test_pipeline_momentum_step.py tests/test_pipeline_momentum_wiring.py -x
```
Expected: all pass (≥ 130 tests).

- [ ] **Smoke run the pipeline**

```
SKIP_SCANNERS=1 python pipeline.py
```
Expected: clean exit, no exceptions. Check `deploy/lifecycle_us_<today>.html` contains the new section.

- [ ] **PR / merge to master**

Standard PR flow per project convention (see recent commit history for merge style).

---

## Self-review notes (for the executing engineer)

- **No autotrading**: this is display only. Never wire `size_hint_label` to order placement.
- **Score threshold 5.0**: hardcoded in `select_top5_buy_candidates` default arg. If calibration data later suggests tuning, expose via `lifecycle_buy_candidates.py` module-level constant (do not introduce env vars yet — keeps the surface small).
- **KR market deferred**: `lifecycle_kr.html` intentionally not modified; `generate_lifecycle_pages` already calls `_render` for KR with the same `portfolio_tickers` kwarg, which is harmless (KR template doesn't reference top5 vars).
- **EXTENDED score path**: the `_raw_score` field exists in snapshots for vetoed (EXTENDED/BROKEN) tickers because `_evaluate_decision_score` stores it for analytics (see [lifecycle_signal.py:301-322](lifecycle_signal.py:301)). BROKEN is filtered out at pool stage so its `_raw_score` is never used here.
- **Backward compat**: `_render` and `generate_lifecycle_pages` add `portfolio_tickers` as a keyword arg with default `None`. Existing callers that don't pass it get an empty set internally (no "보유 중" badges on any ticker — degraded but functional). Only `pipeline.py` is updated in this PR.
