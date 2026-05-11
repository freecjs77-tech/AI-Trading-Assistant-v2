# Trend Page YTD 디아이티/나머지 Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 트렌드 페이지 `포트폴리오 vs S&P 500 (₩) — 2026 YTD` 차트에 디아이티(110990) 단독 YTD와 나머지(110990 제외) YTD 라인 2개를 추가하고, 1월 2일부터 전체 historical 시계열을 backfill한다. me/wife/합산 3 owner 뷰 모두 지원.

**Architecture:** 신규 헬퍼 `compute_dit_rest_decomposition()`을 `benchmark_ytd.py`에 추가해 단일 진실의 원천을 보장한다. `compute_returns()`(파이프라인 going-forward 경로) 와 `backfill_ytd_history.py`(역사 backfill 경로) 양쪽이 이 헬퍼를 호출한다. 6 신규 필드(`dit_ytd_pct`, `rest_ytd_pct`, `dit_v0_krw`, `dit_now_krw`, `rest_v0_krw`, `rest_now_krw`)를 daily snapshot JSON에 저장 — 합산 뷰가 % 가중평균 합산 불가능하므로 KRW 절대값을 저장해야 함. 차트 템플릿에는 datasets 2개 추가 + Y축 수동 토글 라벨 0~50% → 0~80%.

**Tech Stack:** Python 3.10+, yfinance, pytest, Jinja2, Chart.js 4.x.

**참고 디자인 문서:** `docs/superpowers/specs/2026-05-11-trend-dit-decomposition-design.md`

---

## File Structure

**Create:**
- `tests/test_benchmark_dit_decomposition.py` — `compute_dit_rest_decomposition()` 단위 테스트 (보유/미보유/환율무관/수학적 일관성/합산 시뮬레이션)

**Modify:**
- `benchmark_ytd.py` — `compute_dit_rest_decomposition()` 헬퍼 추가 (신규) + `compute_returns()` 반환 dict에 6 필드 추가
- `history_manager.py` — `save_portfolio_snapshot()` 시그너처 확장 (6 신규 kwargs)
- `pipeline.py` — `save_portfolio_snapshot()` 호출부에 6 신규 인자 전달
- `backfill_ytd_history.py` — 110990 가격 시계열 fetch + `compute_dit_rest_decomposition()` 호출 + 6 필드 주입
- `report_generator.py` — `_series_from_daily()` / `_build_owner_payload()` / `_build_combined_payload()` 에 6 필드 pass-through + 합산 뷰 KRW 합산 재계산
- `templates/trend_template.html` — `ytdCompareChart` datasets 2개 추가 + Y축 토글 0~80%로 변경 + `_updateYtdChart()` 신규 datasets 업데이트
- `CLAUDE.md` — "진행 중인 계획" 섹션에 이 plan 등록

**Auto-generated (실행 결과):**
- `history/portfolio_daily.json.bak.YYYYMMDD-rebuild` (rebuild 시 자동 백업)
- `history/portfolio_daily_wife.json.bak.YYYYMMDD-rebuild` (rebuild 시 자동 백업)
- `history/portfolio_daily.json` (1/2~ 최신 덮어쓰기 → 이후 backfill로 6 필드 추가)
- `history/portfolio_daily_wife.json` (동일)

---

## Design Decisions (locked from spec)

1. **분해 대상**: 110990(디아이티)만. 다른 종목 분해 없음.
2. **표시 스코프**: 차트만 (상단 카드 그리드 변경 없음).
3. **Owner 뷰**: me / wife / 합산 3가지 모두.
4. **시계열 시작**: 2026-01-02 anchor부터 전체 backfill (`rebuild_portfolio_history.py` + `backfill_ytd_history.py` 순차 실행).
5. **차트 레이아웃**: 단일 Y축, 4 라인 (디아이티 1/2 YTD ~+61% 수준 outlier 아님 확인됨).
6. **Y축 토글**: Auto / **0~80%** (기존 0~50% 확대).
7. **색상**: Portfolio `#00E5BC`, 디아이티 `#ff716c`, 나머지 `#a78bfa`, S&P 500 `#a3aac4`.
8. **None 처리**: 110990 미보유 owner → 6 필드 모두 `null`. 차트 자동 단절 (Chart.js 기본).
9. **합산 산출**: KRW 절대값 합산 후 % 재계산 (가중평균 합산 불가 회피).
10. **보유 동결**: 현재 holdings × 과거 가격 replay (`rebuild_portfolio_history.py` 패턴 그대로).

---

## Task 1: 분해 헬퍼 테스트 작성 (TDD)

**Files:**
- Create: `tests/test_benchmark_dit_decomposition.py`

- [ ] **Step 1: 테스트 파일 작성**

```python
"""Tests for benchmark_ytd.compute_dit_rest_decomposition.

Covers:
- 110990 보유 케이스 (정상 분해)
- 110990 미보유 케이스 (모든 필드 None)
- KOSDAQ 환율 무관성 (USD/KRW 변경해도 dit_ytd_pct 불변)
- 수학적 일관성 (dit_v0_krw + rest_v0_krw == v0_krw)
- 합산 시뮬레이션 (me + wife KRW 합산 후 % 재계산)
"""
from __future__ import annotations

import pytest

from benchmark_ytd import compute_dit_rest_decomposition

DIT = "110990"


def _baseline_with_dit():
    """Baseline with 110990 + AAPL + VOO (KOSDAQ + US tickers)."""
    return {
        "anchor_date": "2026-01-02",
        "usd_krw": 1400.0,
        "spy_close_usd": 580.0,
        "ticker_v0_krw": {
            DIT: 15690.0,           # KRW native (KOSDAQ)
            "AAPL": 200.0 * 1400,   # 280000 KRW = 200 USD × 1400
            "VOO": 500.0 * 1400,    # 700000 KRW
        },
        "unmappable": [],
    }


def test_dit_held_normal_decomposition():
    """디아이티 보유 케이스 → 6 필드 정상 산출."""
    baseline = _baseline_with_dit()
    holdings = [
        {"ticker": DIT, "shares": 1000},
        {"ticker": "AAPL", "shares": 10},
    ]
    today_prices = {DIT: 25000.0, "AAPL": 250.0}
    today_usd_krw = 1500.0

    # v0_krw = 1000*15690 + 10*200*1400 = 15,690,000 + 2,800,000 = 18,490,000
    # v_now_krw = 1000*25000 + 10*250*1500 = 25,000,000 + 3,750,000 = 28,750,000
    v0_krw = 18_490_000.0
    v_now_krw = 28_750_000.0

    result = compute_dit_rest_decomposition(
        holdings, today_prices, today_usd_krw, baseline, v0_krw, v_now_krw
    )

    # 디아이티 단독
    assert result["dit_v0_krw"] == pytest.approx(15_690_000.0)
    assert result["dit_now_krw"] == pytest.approx(25_000_000.0)
    assert result["dit_ytd_pct"] == pytest.approx((25_000_000 / 15_690_000 - 1) * 100, rel=1e-6)

    # 나머지
    assert result["rest_v0_krw"] == pytest.approx(2_800_000.0)
    assert result["rest_now_krw"] == pytest.approx(3_750_000.0)
    assert result["rest_ytd_pct"] == pytest.approx((3_750_000 / 2_800_000 - 1) * 100, rel=1e-6)


def test_dit_not_held_returns_all_none():
    """110990 미보유 → 6 필드 모두 None."""
    baseline = {
        "anchor_date": "2026-01-02",
        "usd_krw": 1400.0,
        "spy_close_usd": 580.0,
        "ticker_v0_krw": {"AAPL": 280000.0, "VOO": 700000.0},
        "unmappable": [],
    }
    holdings = [{"ticker": "AAPL", "shares": 10}]
    today_prices = {"AAPL": 250.0}
    today_usd_krw = 1500.0
    v0_krw = 10 * 280000.0
    v_now_krw = 10 * 250.0 * 1500.0

    result = compute_dit_rest_decomposition(
        holdings, today_prices, today_usd_krw, baseline, v0_krw, v_now_krw
    )

    assert result["dit_ytd_pct"] is None
    assert result["rest_ytd_pct"] is None
    assert result["dit_v0_krw"] is None
    assert result["dit_now_krw"] is None
    assert result["rest_v0_krw"] is None
    assert result["rest_now_krw"] is None


def test_dit_ytd_invariant_under_fx_change():
    """KOSDAQ 종목은 환율 무관 → today_usd_krw 변경해도 dit_ytd_pct 불변."""
    baseline = _baseline_with_dit()
    holdings = [{"ticker": DIT, "shares": 1000}, {"ticker": "AAPL", "shares": 10}]
    today_prices = {DIT: 25000.0, "AAPL": 250.0}

    # FX = 1500
    v0_a = 18_490_000.0
    v_now_a = 1000 * 25000 + 10 * 250 * 1500  # = 28,750,000
    result_a = compute_dit_rest_decomposition(holdings, today_prices, 1500.0, baseline, v0_a, v_now_a)

    # FX = 2000
    v0_b = 18_490_000.0  # baseline은 그대로 — Jan2 시점 KRW 가격 고정
    v_now_b = 1000 * 25000 + 10 * 250 * 2000  # = 30,000,000
    result_b = compute_dit_rest_decomposition(holdings, today_prices, 2000.0, baseline, v0_b, v_now_b)

    # 디아이티는 KOSDAQ → FX 무관
    assert result_a["dit_ytd_pct"] == pytest.approx(result_b["dit_ytd_pct"], rel=1e-9)
    # 나머지는 US 종목이라 FX 변경 시 변화 OK (이 테스트의 단언 대상 아님)


def test_dit_rest_v0_sum_equals_total_v0():
    """수학적 일관성: dit_v0_krw + rest_v0_krw == v0_krw (소수점 오차 1e-3 이내)."""
    baseline = _baseline_with_dit()
    holdings = [{"ticker": DIT, "shares": 1000}, {"ticker": "AAPL", "shares": 10}]
    today_prices = {DIT: 25000.0, "AAPL": 250.0}
    v0_krw = 18_490_000.0
    v_now_krw = 28_750_000.0

    result = compute_dit_rest_decomposition(holdings, today_prices, 1500.0, baseline, v0_krw, v_now_krw)

    assert abs((result["dit_v0_krw"] + result["rest_v0_krw"]) - v0_krw) < 1e-3
    assert abs((result["dit_now_krw"] + result["rest_now_krw"]) - v_now_krw) < 1e-3


def test_combined_simulation_krw_sum_then_recompute():
    """합산 뷰 산출: me + wife KRW 합산 후 % 재계산."""
    # me: dit_v0=1000만, dit_now=1500만, rest_v0=500만, rest_now=600만
    me = {"dit_v0_krw": 10_000_000.0, "dit_now_krw": 15_000_000.0, "rest_v0_krw": 5_000_000.0, "rest_now_krw": 6_000_000.0}
    # wife: dit_v0=300만, dit_now=400만, rest_v0=200만, rest_now=250만
    wife = {"dit_v0_krw": 3_000_000.0, "dit_now_krw": 4_000_000.0, "rest_v0_krw": 2_000_000.0, "rest_now_krw": 2_500_000.0}

    # 합산
    dit_v0 = me["dit_v0_krw"] + wife["dit_v0_krw"]      # 1300만
    dit_now = me["dit_now_krw"] + wife["dit_now_krw"]   # 1900만
    rest_v0 = me["rest_v0_krw"] + wife["rest_v0_krw"]   # 700만
    rest_now = me["rest_now_krw"] + wife["rest_now_krw"]# 850만

    dit_ytd = (dit_now / dit_v0 - 1) * 100
    rest_ytd = (rest_now / rest_v0 - 1) * 100

    assert dit_ytd == pytest.approx(46.1538, abs=1e-3)   # (1900/1300 - 1)*100
    assert rest_ytd == pytest.approx(21.4286, abs=1e-3)  # (850/700 - 1)*100
```

- [ ] **Step 2: 테스트 실행해서 모두 실패 확인**

Run: `pytest tests/test_benchmark_dit_decomposition.py -v`
Expected: 5 FAIL (compute_dit_rest_decomposition 없음 → ImportError)

- [ ] **Step 3: Commit**

```bash
git add tests/test_benchmark_dit_decomposition.py
git commit -m "test(benchmark): add failing tests for compute_dit_rest_decomposition

Covers held/not-held cases, KOSDAQ FX invariance, math consistency,
and combined view KRW sum simulation. All 5 tests fail until helper
is implemented in Task 2."
```

---

## Task 2: `compute_dit_rest_decomposition` 헬퍼 구현

**Files:**
- Modify: `benchmark_ytd.py` (append below `compute_returns()` definition, before `_baseline_cache_path()` at line 227)

- [ ] **Step 1: 헬퍼 함수 추가**

`benchmark_ytd.py` 의 line 224 (compute_returns 종료) 다음, line 227 (`_baseline_cache_path`) 앞에 다음 함수를 추가:

```python
DIT_TICKER = "110990"


def compute_dit_rest_decomposition(
    holdings: list[dict],
    today_prices: dict,
    today_usd_krw: float,
    baseline: dict,
    v0_krw: float,
    v_now_krw: float,
) -> dict:
    """Compute 110990 standalone YTD and 'rest' (portfolio - 110990) YTD.

    Reuses pre-computed v0_krw and v_now_krw from compute_returns to avoid
    redundant summation. Returns 6 fields, all None when 110990 isn't held
    OR is unmappable in baseline OR is missing in today_prices.

    KOSDAQ ticker — USD/KRW conversion not applied to 110990 (is_korean_ticker check).

    Returns:
        {
          "dit_ytd_pct":  float | None,
          "rest_ytd_pct": float | None,
          "dit_v0_krw":   float | None,
          "dit_now_krw":  float | None,
          "rest_v0_krw":  float | None,
          "rest_now_krw": float | None,
        }
    """
    none_result = {
        "dit_ytd_pct": None,
        "rest_ytd_pct": None,
        "dit_v0_krw": None,
        "dit_now_krw": None,
        "rest_v0_krw": None,
        "rest_now_krw": None,
    }

    ticker_v0 = baseline.get("ticker_v0_krw") or {}
    if DIT_TICKER not in ticker_v0:
        return none_result

    dit_today_price = today_prices.get(DIT_TICKER)
    if dit_today_price is None or dit_today_price <= 0:
        return none_result

    dit_shares = next((float(h["shares"]) for h in holdings if h["ticker"] == DIT_TICKER), 0.0)
    if dit_shares <= 0:
        return none_result

    dit_v0_per_share = float(ticker_v0[DIT_TICKER])
    dit_now_per_share = float(dit_today_price)  # KRW native (KOSDAQ — no FX)
    dit_v0_krw_val = dit_shares * dit_v0_per_share
    dit_now_krw_val = dit_shares * dit_now_per_share
    dit_ytd_pct = (dit_now_per_share / dit_v0_per_share - 1.0) * 100.0 if dit_v0_per_share > 0 else None

    rest_v0_krw_val = v0_krw - dit_v0_krw_val
    rest_now_krw_val = v_now_krw - dit_now_krw_val
    rest_ytd_pct = (rest_now_krw_val / rest_v0_krw_val - 1.0) * 100.0 if rest_v0_krw_val > 0 else None

    return {
        "dit_ytd_pct": dit_ytd_pct,
        "rest_ytd_pct": rest_ytd_pct,
        "dit_v0_krw": dit_v0_krw_val,
        "dit_now_krw": dit_now_krw_val,
        "rest_v0_krw": rest_v0_krw_val,
        "rest_now_krw": rest_now_krw_val,
    }
```

- [ ] **Step 2: 테스트 실행해서 5개 모두 통과 확인**

Run: `pytest tests/test_benchmark_dit_decomposition.py -v`
Expected: 5 PASS

- [ ] **Step 3: Commit**

```bash
git add benchmark_ytd.py
git commit -m "feat(benchmark): add compute_dit_rest_decomposition helper

110990 single-stock YTD and 'rest' (portfolio - 110990) YTD computation.
KOSDAQ FX-invariant. Returns 6 fields, all None for non-holders.
Single source of truth — to be called by both compute_returns (pipeline)
and backfill_ytd_history (historical backfill)."
```

---

## Task 3: `compute_returns()` 확장 — 6 필드 추가

**Files:**
- Modify: `benchmark_ytd.py:215-224` (compute_returns return dict)

- [ ] **Step 1: compute_returns 함수 수정**

`benchmark_ytd.py:215-224` 를 다음과 같이 교체:

```python
    decomp = compute_dit_rest_decomposition(
        holdings, today_prices, today_usd_krw, baseline, v0_krw, v_now_krw
    )

    return {
        "v0_krw": v0_krw,
        "v_now_krw": v_now_krw,
        "ytd_pct": ytd_pct,
        "spy_v0_krw": spy_v0_krw,
        "spy_now_krw": spy_now_krw,
        "spy_ytd_pct": spy_ytd_pct,
        "alpha_pp": alpha_pp,
        "excluded_tickers": excluded,
        "dit_ytd_pct": decomp["dit_ytd_pct"],
        "rest_ytd_pct": decomp["rest_ytd_pct"],
        "dit_v0_krw": decomp["dit_v0_krw"],
        "dit_now_krw": decomp["dit_now_krw"],
        "rest_v0_krw": decomp["rest_v0_krw"],
        "rest_now_krw": decomp["rest_now_krw"],
    }
```

- [ ] **Step 2: 기존 compute_returns 테스트들이 회귀 없음을 확인**

Run: `pytest tests/test_benchmark_ytd.py tests/test_benchmark_dit_decomposition.py -v`
Expected: 기존 + 신규 모두 PASS

- [ ] **Step 3: Commit**

```bash
git add benchmark_ytd.py
git commit -m "feat(benchmark): compute_returns now includes DIT/rest decomposition

Adds 6 new fields to the result dict by calling compute_dit_rest_decomposition.
Non-holders get None for all 6 fields. Existing fields unchanged."
```

---

## Task 4: `save_portfolio_snapshot()` 시그너처 확장

**Files:**
- Modify: `history_manager.py:209-248`

- [ ] **Step 1: 시그너처 + 본문 수정**

`history_manager.py:210-214` 의 keyword args를 다음으로 교체:

```python
    ytd_pct: float | None = None,
    spy_ytd_pct: float | None = None,
    alpha_pp: float | None = None,
    v0_krw: float | None = None,
    spy_v0_krw: float | None = None,
    dit_ytd_pct: float | None = None,
    rest_ytd_pct: float | None = None,
    dit_v0_krw: float | None = None,
    dit_now_krw: float | None = None,
    rest_v0_krw: float | None = None,
    rest_now_krw: float | None = None,
```

그리고 `history_manager.py:239-248` (기존 if blocks)의 끝(line 248 `if spy_v0_krw is not None: ...` 직후, line 250 `daily[date_str] = snap` 직전)에 다음 추가:

```python
    if dit_ytd_pct is not None:
        snap["dit_ytd_pct"] = round(dit_ytd_pct, 2)
    if rest_ytd_pct is not None:
        snap["rest_ytd_pct"] = round(rest_ytd_pct, 2)
    if dit_v0_krw is not None:
        snap["dit_v0_krw"] = round(dit_v0_krw)
    if dit_now_krw is not None:
        snap["dit_now_krw"] = round(dit_now_krw)
    if rest_v0_krw is not None:
        snap["rest_v0_krw"] = round(rest_v0_krw)
    if rest_now_krw is not None:
        snap["rest_now_krw"] = round(rest_now_krw)
```

- [ ] **Step 2: 시그너처 확장 확인 (간단한 import + 호출)**

Run:
```bash
python -c "from history_manager import save_portfolio_snapshot; import inspect; sig = inspect.signature(save_portfolio_snapshot); assert 'dit_ytd_pct' in sig.parameters; assert 'rest_now_krw' in sig.parameters; print('OK 6 new kwargs present')"
```
Expected: `OK 6 new kwargs present`

- [ ] **Step 3: Commit**

```bash
git add history_manager.py
git commit -m "feat(history): save_portfolio_snapshot accepts 6 DIT/rest kwargs

dit_ytd_pct, rest_ytd_pct, dit_v0_krw, dit_now_krw, rest_v0_krw, rest_now_krw.
All default to None; only written to snapshot when not None."
```

---

## Task 5: `pipeline.py` 호출부 확장

**Files:**
- Modify: `pipeline.py:730-742` (save_portfolio_snapshot 호출부 블록)

- [ ] **Step 1: 호출부 수정**

`pipeline.py:735-737` 의 ytd 인자 전달부에 6 개 추가. 기존 코드:

```python
                    ytd_pct=_bm.get("ytd_pct"),
                    spy_ytd_pct=_bm.get("spy_ytd_pct"),
                    alpha_pp=_bm.get("alpha_pp"),
```

을 다음으로 교체:

```python
                    ytd_pct=_bm.get("ytd_pct"),
                    spy_ytd_pct=_bm.get("spy_ytd_pct"),
                    alpha_pp=_bm.get("alpha_pp"),
                    v0_krw=_bm.get("v0_krw"),
                    spy_v0_krw=_bm.get("spy_v0_krw"),
                    dit_ytd_pct=_bm.get("dit_ytd_pct"),
                    rest_ytd_pct=_bm.get("rest_ytd_pct"),
                    dit_v0_krw=_bm.get("dit_v0_krw"),
                    dit_now_krw=_bm.get("dit_now_krw"),
                    rest_v0_krw=_bm.get("rest_v0_krw"),
                    rest_now_krw=_bm.get("rest_now_krw"),
```

(`v0_krw`/`spy_v0_krw`는 기존에 전달 안 하던 것을 함께 추가 — 합산 뷰에 필요)

- [ ] **Step 2: 다른 save_portfolio_snapshot 호출부 확인**

Run:
```bash
grep -n "save_portfolio_snapshot" pipeline.py
```
Expected: 단일 호출부 (line 730 근처). 다른 곳에서 호출하지 않음을 확인.

만약 추가 호출부가 있으면 동일하게 6 인자 전달 추가.

- [ ] **Step 3: Commit**

```bash
git add pipeline.py
git commit -m "feat(pipeline): pass 6 DIT/rest fields to save_portfolio_snapshot

Wires compute_owner_benchmark output through to daily snapshot writer.
Going-forward, pipeline runs automatically save dit_ytd_pct / rest_ytd_pct
plus 4 KRW absolute fields needed for combined view recomputation."
```

---

## Task 6: `backfill_ytd_history.py` 확장 — 110990 가격 시계열 fetch

**Files:**
- Modify: `backfill_ytd_history.py`

- [ ] **Step 1: 110990 가격 fetch 헬퍼 함수 추가**

`backfill_ytd_history.py` 의 `fetch_spy_history()` 함수 (line 32-68) 바로 아래에 다음 함수 추가:

```python
def fetch_dit_history(start_date: str, end_date: str) -> dict:
    """Fetch 110990.KQ Close prices for date range. Returns {date_str: close_krw}.

    Same retry pattern as fetch_spy_history. Returns empty dict on failure.
    """
    import time
    end = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=2)).strftime("%Y-%m-%d")
    print(f"Fetching 110990.KQ history {start_date} → {end} ...")
    delays = [0, 1, 3, 9]
    last_exc = None
    for attempt, delay in enumerate(delays):
        if delay > 0:
            print(f"  ⏳ retry after {delay}s (attempt {attempt}/{len(delays)-1})")
            time.sleep(delay)
        try:
            t = yf.Ticker("110990.KQ")
            df = t.history(start=start_date, end=end, auto_adjust=False)
            if df is None or df.empty:
                return {}
            out = {}
            for idx, row in df.iterrows():
                date_str = idx.strftime("%Y-%m-%d")
                close = row.get("Close")
                if pd.notna(close) and close > 0:
                    out[date_str] = float(close)
            return out
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            if "rate limit" in msg or "too many requests" in msg or "429" in msg:
                continue
            if "no data" in msg or "delisted" in msg:
                return {}
            continue
    print(f"  WARN 110990.KQ history fetch failed after {len(delays)} attempts: {last_exc}")
    return {}


def find_nearest_dit(dit_history: dict, target_date: str) -> float | None:
    """Find 110990 close on target_date, or fall back to most recent prior trading day."""
    if target_date in dit_history:
        return dit_history[target_date]
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    for back in range(1, 8):
        d = (dt - timedelta(days=back)).strftime("%Y-%m-%d")
        if d in dit_history:
            return dit_history[d]
    return None
```

- [ ] **Step 2: import 확장**

`backfill_ytd_history.py:21-24` 의 import block에 `compute_dit_rest_decomposition`을 추가:

기존:
```python
from benchmark_ytd import (
    ANCHOR_DATE, SPY_SYMBOL, load_or_build_baseline,
    compute_v0_total_krw, fetch_close_on,
)
```

수정:
```python
from benchmark_ytd import (
    ANCHOR_DATE, SPY_SYMBOL, DIT_TICKER, load_or_build_baseline,
    compute_v0_total_krw, fetch_close_on, compute_dit_rest_decomposition,
)
```

- [ ] **Step 3: 함수 import 확인**

Run:
```bash
python -c "from backfill_ytd_history import fetch_dit_history, find_nearest_dit; from benchmark_ytd import compute_dit_rest_decomposition, DIT_TICKER; print('OK imports')"
```
Expected: `OK imports`

- [ ] **Step 4: Commit**

```bash
git add backfill_ytd_history.py
git commit -m "feat(backfill): add 110990.KQ price history fetcher

fetch_dit_history + find_nearest_dit helpers mirror SPY equivalents.
Same retry pattern (1s/3s/9s) on 429 rate limit. Imports
compute_dit_rest_decomposition for next step."
```

---

## Task 7: `backfill_ytd_history.py` — DIT/rest 필드 주입

**Files:**
- Modify: `backfill_ytd_history.py:105-210` (main loop)

- [ ] **Step 1: main loop에 holdings 캐시 + DIT 가격 fetch 추가**

`backfill_ytd_history.py:117` (`print()` 직후, line 119 `# Step 2` 주석 직전)에 다음 추가:

```python
    # Cache per-owner holdings for DIT/rest decomposition
    owner_holdings = {}
    for owner, ppath in discover_portfolios(PROJECT_DIR):
        owner_holdings[owner] = _parse_portfolio_for_report(ppath)
```

그리고 `backfill_ytd_history.py:142` (SPY history fetch) 다음 라인에 DIT history fetch 추가:

기존:
```python
    spy_history = fetch_spy_history(ANCHOR_DATE, sorted_dates[-1])
    print(f"  Fetched {len(spy_history)} SPY trading days\n")
    if not spy_history:
        print("  WARN SPY history empty — skipping backfill (will retry on next run)")
        return  # graceful exit, exit code 0
```

수정 후:
```python
    spy_history = fetch_spy_history(ANCHOR_DATE, sorted_dates[-1])
    print(f"  Fetched {len(spy_history)} SPY trading days\n")
    if not spy_history:
        print("  WARN SPY history empty — skipping backfill (will retry on next run)")
        return  # graceful exit, exit code 0

    dit_history = fetch_dit_history(ANCHOR_DATE, sorted_dates[-1])
    print(f"  Fetched {len(dit_history)} 110990.KQ trading days\n")
    # Note: DIT history may be empty for owners not holding 110990 — that's OK,
    # decomposition will return None fields for those owners.
```

- [ ] **Step 2: Per-owner 루프에 DIT/rest 계산 + 주입 추가**

`backfill_ytd_history.py:153-208` 의 per-owner backfill loop를 수정. 다음 부분에 DIT/rest 로직을 끼워 넣는다:

`backfill_ytd_history.py:198` (`if snap.get("spy_v0_krw") is None: snap["spy_v0_krw"] = round(spy_v0_krw, 2)`) 다음, line 199 (`if is_update: updated += 1`) 직전에 DIT/rest 계산 블록 추가:

```python
            # DIT/rest decomposition (110990 보유 owner만)
            holdings_for_owner = owner_holdings.get(owner, [])
            dit_close_d = find_nearest_dit(dit_history, date_str)
            if dit_close_d is not None and holdings_for_owner:
                # 백필 컨텍스트에서 today_prices는 dit_close_d만 있으면 충분
                # (compute_dit_rest_decomposition은 110990만 today_prices에서 읽음)
                today_prices_d = {DIT_TICKER: dit_close_d}
                decomp = compute_dit_rest_decomposition(
                    holdings_for_owner,
                    today_prices_d,
                    usd_krw_d,
                    baseline,
                    float(current_v0),
                    float(total_krw_d),
                )
                if decomp["dit_ytd_pct"] is not None:
                    snap["dit_ytd_pct"] = round(decomp["dit_ytd_pct"], 2)
                if decomp["rest_ytd_pct"] is not None:
                    snap["rest_ytd_pct"] = round(decomp["rest_ytd_pct"], 2)
                if decomp["dit_v0_krw"] is not None:
                    snap["dit_v0_krw"] = round(decomp["dit_v0_krw"])
                if decomp["dit_now_krw"] is not None:
                    snap["dit_now_krw"] = round(decomp["dit_now_krw"])
                if decomp["rest_v0_krw"] is not None:
                    snap["rest_v0_krw"] = round(decomp["rest_v0_krw"])
                if decomp["rest_now_krw"] is not None:
                    snap["rest_now_krw"] = round(decomp["rest_now_krw"])
```

- [ ] **Step 3: 구문 검증 — script가 ImportError/SyntaxError 없이 import되는지 확인**

Run:
```bash
python -c "import backfill_ytd_history; print('OK module loads')"
```
Expected: `OK module loads`

- [ ] **Step 4: Commit**

```bash
git add backfill_ytd_history.py
git commit -m "feat(backfill): inject DIT/rest decomposition fields per snapshot

Uses fetch_dit_history (one bulk yfinance call) + compute_dit_rest_decomposition.
For each historical date, computes 6 new fields and writes them to the snapshot.
Owners not holding 110990 get no fields (None propagation)."
```

---

## Task 8: `rebuild_portfolio_history.py` 실행 — 1/2~ 전체 daily 재생성

**Files:**
- 실행만, 코드 변경 없음
- 영향: `history/portfolio_daily.json` / `history/portfolio_daily_wife.json` 덮어쓰기

- [ ] **Step 1: 현재 상태 백업 확인 + dry-run**

```bash
python rebuild_portfolio_history.py --dry-run
```
Expected: me/wife 거래일 수(약 90+ 일), first/last 날짜 출력. "[DRY-RUN] 저장 생략"

- [ ] **Step 2: 실제 실행**

```bash
python rebuild_portfolio_history.py
```
Expected:
- backup: `history/portfolio_daily.json.bak.YYYYMMDD-rebuild` 와 `_wife.json.bak.YYYYMMDD-rebuild`
- saved: 두 파일 모두 1/2 ~ 최신 거래일까지 (약 90+ entries) 저장됨

- [ ] **Step 3: 결과 검증**

```bash
python -c "
import json
me = json.load(open('history/portfolio_daily.json', encoding='utf-8'))
wife = json.load(open('history/portfolio_daily_wife.json', encoding='utf-8'))
print(f'me: {len(me)} days, first={min(me.keys())}, last={max(me.keys())}')
print(f'wife: {len(wife)} days, first={min(wife.keys())}, last={max(wife.keys())}')
assert min(me.keys()) == '2026-01-02', f'me first date should be 2026-01-02, got {min(me.keys())}'
assert min(wife.keys()) == '2026-01-02', f'wife first date should be 2026-01-02, got {min(wife.keys())}'
print('OK 2026-01-02 시작 확인')
"
```
Expected: 두 파일 모두 1/2 시작, 60+ entries.

- [ ] **Step 4: 데이터 commit (별도 코드 변경 없이 데이터만)**

```bash
git add history/portfolio_daily.json history/portfolio_daily_wife.json
git commit -m "data(history): rebuild me+wife portfolio_daily from 2026-01-02

Re-run of rebuild_portfolio_history.py (existing code). Restores the
1/2 anchor that was lost when the feature/portfolio-history-rebuild
branch never merged. Required prerequisite for DIT/rest YTD backfill.

Backups: history/portfolio_daily*.bak.YYYYMMDD-rebuild"
```

---

## Task 9: `backfill_ytd_history.py` 실행 — YTD + DIT/rest 전체 backfill

**Files:**
- 실행만, 코드 변경 없음
- 영향: 두 daily JSON에 6+5=11 필드 채워짐 (ytd/spy/alpha + v0/spy_v0 + dit/rest 6개)

- [ ] **Step 1: 실행**

```bash
python backfill_ytd_history.py
```
Expected output:
- `me: current v0_krw=..., spy_v0_krw=...`
- `wife: current v0_krw=..., spy_v0_krw=...`
- `Historical dates: 2026-01-02 → 2026-05-XX (XX dates)`
- `Fetched XX SPY trading days`
- `Fetched XX 110990.KQ trading days`
- 각 owner 별: `added=XX, updated=YY, skipped_existing=ZZ, skipped_no_data=WW`

- [ ] **Step 2: 6 필드 spot-check**

```bash
python -c "
import json
me = json.load(open('history/portfolio_daily.json', encoding='utf-8'))
# 1/2 entry: dit_ytd_pct, rest_ytd_pct == 0.0
jan2 = me.get('2026-01-02')
assert jan2 is not None, '2026-01-02 missing'
assert jan2.get('dit_ytd_pct') == 0.0, f'1/2 dit_ytd_pct should be 0.0, got {jan2.get(\"dit_ytd_pct\")}'
assert jan2.get('rest_ytd_pct') == 0.0, f'1/2 rest_ytd_pct should be 0.0, got {jan2.get(\"rest_ytd_pct\")}'
print(f'OK 1/2: dit_ytd={jan2[\"dit_ytd_pct\"]}, rest_ytd={jan2[\"rest_ytd_pct\"]}')

# 최신 entry: 6 필드 모두 존재
last_date = max(me.keys())
last = me[last_date]
required = ['dit_ytd_pct', 'rest_ytd_pct', 'dit_v0_krw', 'dit_now_krw', 'rest_v0_krw', 'rest_now_krw']
for k in required:
    assert k in last, f'last entry missing {k}'
    assert last[k] is not None, f'last entry {k} is None'
print(f'OK {last_date}: dit_ytd={last[\"dit_ytd_pct\"]}, rest_ytd={last[\"rest_ytd_pct\"]}')

# 수학적 일관성: dit_v0 + rest_v0 ~= v0_krw (rounding tolerance ±2 KRW per side)
assert abs((last['dit_v0_krw'] + last['rest_v0_krw']) - last['v0_krw']) <= 5, \
    f'sum mismatch: dit_v0+rest_v0={last[\"dit_v0_krw\"]+last[\"rest_v0_krw\"]}, v0={last[\"v0_krw\"]}'
print('OK 수학적 일관성 (dit_v0 + rest_v0 == v0_krw)')
"
```
Expected: 3개 OK 라인. 1/2은 0.0, 최신 entry는 non-null, 합산 일관성 OK.

- [ ] **Step 3: 디아이티 단독 YTD를 yfinance 직접 fetch와 비교**

```bash
python -c "
import json
import yfinance as yf
me = json.load(open('history/portfolio_daily.json', encoding='utf-8'))
last_date = max(me.keys())
last = me[last_date]

# 캐시된 baseline 1/2 가격
baseline = json.load(open('data/baseline_2026_me.json', encoding='utf-8'))
v0 = baseline['ticker_v0_krw']['110990']

# yfinance 직접 fetch (last_date)
t = yf.Ticker('110990.KQ')
df = t.history(start=last_date, end=last_date, auto_adjust=False)
if df.empty:
    # 비거래일이면 최근 거래일
    from datetime import datetime, timedelta
    end = (datetime.strptime(last_date, '%Y-%m-%d') + timedelta(days=2)).strftime('%Y-%m-%d')
    df = t.history(start=last_date, end=end, auto_adjust=False)
close = df.iloc[0]['Close']
expected_ytd = (close / v0 - 1) * 100
actual_ytd = last['dit_ytd_pct']
print(f'  expected dit_ytd ({last_date}): {expected_ytd:+.2f}%')
print(f'  actual   dit_ytd ({last_date}): {actual_ytd:+.2f}%')
assert abs(expected_ytd - actual_ytd) < 0.5, f'mismatch: expected={expected_ytd}, actual={actual_ytd}'
print('OK 디아이티 단독 YTD yfinance 일치')
"
```
Expected: 두 값이 0.5%p 이내 일치.

- [ ] **Step 4: 데이터 commit**

```bash
git add history/portfolio_daily.json history/portfolio_daily_wife.json
git commit -m "data(history): backfill YTD + DIT/rest fields for all snapshots

Adds ytd_pct/spy_ytd_pct/alpha_pp/v0_krw/spy_v0_krw plus 6 new DIT/rest
fields to every daily snapshot from 2026-01-02 onwards. Verified:
1/2 entries have dit_ytd_pct=0.0, latest entry matches yfinance direct
fetch, dit_v0 + rest_v0 == v0_krw consistency holds."
```

---

## Task 10: `report_generator.py` — owner payload pass-through

**Files:**
- Modify: `report_generator.py:730-745` (_series_from_daily)
- Modify: `report_generator.py:748-783` (_build_owner_payload)

- [ ] **Step 1: `_series_from_daily()`에 6 필드 추가**

`report_generator.py:733-744` 의 append dict를 다음으로 교체:

```python
        out.append({
            "date": d,
            "total_eok": round(snap.get("total_value_krw", 0) / 1e8, 2),
            "cost_eok": round(snap.get("cost_basis_krw", 0) / 1e8, 2),
            "pnl_eok": round(snap.get("pnl_krw", 0) / 1e8, 2),
            "pnl_pct": snap.get("pnl_pct", 0),
            "div_annual_man": round(snap.get("div_annual_krw", 0) / 1e4),
            "div_yield": snap.get("div_yield", 0),
            "ytd_pct": snap.get("ytd_pct"),
            "spy_ytd_pct": snap.get("spy_ytd_pct"),
            "alpha_pp": snap.get("alpha_pp"),
            "dit_ytd_pct": snap.get("dit_ytd_pct"),
            "rest_ytd_pct": snap.get("rest_ytd_pct"),
        })
```

- [ ] **Step 2: `_build_owner_payload()` latest dict 확장**

`report_generator.py:755-768` 의 latest dict 다음 line 769 `ticker_weights = ...` 직전에 6 신규 필드 (latest 차원에는 % 2개만 — KRW 절대값은 합산용으로만):

`latest = { ..., "alpha_pp": ..., }` 마지막 라인에 추가:

기존:
```python
        "alpha_pp": latest_snap.get("alpha_pp"),
    }
```

수정:
```python
        "alpha_pp": latest_snap.get("alpha_pp"),
        "dit_ytd_pct": latest_snap.get("dit_ytd_pct"),
        "rest_ytd_pct": latest_snap.get("rest_ytd_pct"),
    }
```

- [ ] **Step 3: import 후 호출 검증 (no-op test)**

Run:
```bash
python -c "
from report_generator import _series_from_daily, _build_owner_payload
import json
me = json.load(open('history/portfolio_daily.json', encoding='utf-8'))
series = _series_from_daily(me)
assert 'dit_ytd_pct' in series[-1], 'dit_ytd_pct missing in series'
assert 'rest_ytd_pct' in series[-1], 'rest_ytd_pct missing in series'
print(f'OK series last: dit_ytd={series[-1][\"dit_ytd_pct\"]}, rest_ytd={series[-1][\"rest_ytd_pct\"]}')
payload = _build_owner_payload(me)
assert 'dit_ytd_pct' in payload['latest']
print(f'OK latest: dit_ytd={payload[\"latest\"][\"dit_ytd_pct\"]}')
"
```
Expected: 2개 OK 라인.

- [ ] **Step 4: Commit**

```bash
git add report_generator.py
git commit -m "feat(report): owner payload includes DIT/rest YTD fields

_series_from_daily and _build_owner_payload pass-through 6 new fields
to template. Latest dict gets 2 % fields (KRW absolute values used only
by _build_combined_payload aggregation)."
```

---

## Task 11: `report_generator._build_combined_payload()` — KRW 합산 후 % 재계산

**Files:**
- Modify: `report_generator.py:786-852`

- [ ] **Step 1: 합산 로직에 DIT/rest KRW 누적 추가**

`report_generator.py:786-852` 의 `_build_combined_payload()` 를 수정. 4 부분에 변경:

**(a)** Line 801 (`v0_complete = True`) 다음, line 802 (`spy_ytd_pct = None`) 직전에 DIT/rest 합산 변수 추가:

```python
        v0_complete = True  # v0_krw가 모든 owner에 있어야 합산 ytd 계산 가능
        spy_ytd_pct = None
        # DIT/rest 합산용 (모든 owner에 있어야 합산 가능)
        dit_v0_sum = 0.0
        dit_now_sum = 0.0
        rest_v0_sum = 0.0
        rest_now_sum = 0.0
        dit_complete = True
```

**(b)** Per-owner 루프 본문 (line 806-825) 끝에 DIT/rest 누적 추가. Line 825 (`if spy_ytd_pct is None and snap.get("spy_ytd_pct") is not None: ...`) 다음에:

```python
            if spy_ytd_pct is None and snap.get("spy_ytd_pct") is not None:
                spy_ytd_pct = snap.get("spy_ytd_pct")  # 모든 owner 동일하므로 첫 값 사용
            # DIT/rest 합산: 모든 owner에 4 KRW 필드 있어야 의미 있음
            dit_v0 = snap.get("dit_v0_krw")
            dit_now = snap.get("dit_now_krw")
            rest_v0 = snap.get("rest_v0_krw")
            rest_now = snap.get("rest_now_krw")
            if dit_v0 is None or dit_now is None or rest_v0 is None or rest_now is None:
                # 한 owner만 미보유여도 합산 의미 없으면 None; 다만 둘 다 보유 시 합산
                # 보수적으로: 4개 모두 있을 때만 누적 (한쪽이 미보유면 0으로 처리)
                # 실제로는 me·wife 둘 다 110990 보유 중 — 이 분기는 향후 가족 추가 대비
                if dit_v0 is None and dit_now is None and rest_v0 is None and rest_now is None:
                    # 완전 미보유 owner — 단순 skip (0 합산), dit_complete 유지
                    pass
                else:
                    dit_complete = False
            else:
                dit_v0_sum += dit_v0
                dit_now_sum += dit_now
                rest_v0_sum += rest_v0
                rest_now_sum += rest_now
```

**(c)** Line 831-836 (`ytd_pct_combined / alpha_pp_combined` 계산) 다음, line 837 (`combined_daily[date] = { ... }`) 직전에 DIT/rest combined 계산 추가:

```python
        # 합산 YTD: v0_krw 합산이 완전할 때만 계산
        ytd_pct_combined = None
        alpha_pp_combined = None
        if v0_complete and v0_sum > 0:
            ytd_pct_combined = round((tot / v0_sum - 1) * 100, 2)
            if spy_ytd_pct is not None:
                alpha_pp_combined = round(ytd_pct_combined - spy_ytd_pct, 2)
        # 합산 DIT/rest YTD: KRW 절대값 합산 후 % 재계산
        dit_ytd_combined = None
        rest_ytd_combined = None
        if dit_complete:
            if dit_v0_sum > 0:
                dit_ytd_combined = round((dit_now_sum / dit_v0_sum - 1) * 100, 2)
            if rest_v0_sum > 0:
                rest_ytd_combined = round((rest_now_sum / rest_v0_sum - 1) * 100, 2)
```

**(d)** Line 837-851 (`combined_daily[date] = { ... }`) 의 dict 안에 DIT/rest 필드 추가. 기존:

```python
        combined_daily[date] = {
            "total_value_krw": tot,
            ...
            "v0_krw": v0_sum if v0_complete else None,
            "ytd_pct": ytd_pct_combined,
            "spy_ytd_pct": spy_ytd_pct,
            "alpha_pp": alpha_pp_combined,
        }
```

수정:
```python
        combined_daily[date] = {
            "total_value_krw": tot,
            "cost_basis_krw": cost,
            "pnl_krw": pnl,
            "pnl_pct": pnl_pct,
            "cash_value_krw": cash,
            "cash_pct": cash_pct,
            "div_annual_krw": div_annual,
            "div_yield": div_yield,
            "weights_by_ticker": weights_by_ticker,
            "v0_krw": v0_sum if v0_complete else None,
            "ytd_pct": ytd_pct_combined,
            "spy_ytd_pct": spy_ytd_pct,
            "alpha_pp": alpha_pp_combined,
            "dit_ytd_pct": dit_ytd_combined,
            "rest_ytd_pct": rest_ytd_combined,
            "dit_v0_krw": dit_v0_sum if dit_complete else None,
            "dit_now_krw": dit_now_sum if dit_complete else None,
            "rest_v0_krw": rest_v0_sum if dit_complete else None,
            "rest_now_krw": rest_now_sum if dit_complete else None,
        }
```

- [ ] **Step 2: 합산 페이로드 검증**

```bash
python -c "
import json
from report_generator import _build_combined_payload
me = json.load(open('history/portfolio_daily.json', encoding='utf-8'))
wife = json.load(open('history/portfolio_daily_wife.json', encoding='utf-8'))
combined = _build_combined_payload(me, {'wife': wife})
last = combined['trend'][-1]
print(f'combined last date: {last[\"date\"]}')
print(f'  ytd_pct:      {last[\"ytd_pct\"]}')
print(f'  spy_ytd_pct:  {last[\"spy_ytd_pct\"]}')
print(f'  dit_ytd_pct:  {last[\"dit_ytd_pct\"]}')
print(f'  rest_ytd_pct: {last[\"rest_ytd_pct\"]}')
assert last['dit_ytd_pct'] is not None, 'dit_ytd_pct should not be None (both owners hold 110990)'
assert last['rest_ytd_pct'] is not None, 'rest_ytd_pct should not be None'
print('OK 합산 뷰 DIT/rest 산출')
"
```
Expected: 4 필드 출력 + OK 라인.

- [ ] **Step 3: Commit**

```bash
git add report_generator.py
git commit -m "feat(report): combined view aggregates DIT/rest via KRW sum + recompute

Sums dit_v0_krw / dit_now_krw / rest_v0_krw / rest_now_krw across owners,
then recomputes dit_ytd_pct / rest_ytd_pct from the totals. Avoids the
percentage-weighted-average aggregation problem. Stays None if any owner
has partial DIT/rest data (defensive — both owners currently hold 110990)."
```

---

## Task 12: `templates/trend_template.html` — datasets 2 라인 추가

**Files:**
- Modify: `templates/trend_template.html:344-353` (YTD chart Chart.js datasets)
- Modify: `templates/trend_template.html:355-365` (_updateYtdChart)
- Modify: `templates/trend_template.html:178-180` (Y축 토글 라벨)
- Modify: `templates/trend_template.html:353` (`_wireRangeToggle` cfg)

- [ ] **Step 1: 신규 라인 datasets 추가**

`templates/trend_template.html:344-353` 의 ytdCompareChart 정의 블록을 수정. 기존:

```html
{% if latest.ytd_pct is not none and latest.spy_ytd_pct is not none %}
const ytdPortData = trend.map(d => d.ytd_pct);
const ytdSpyData  = trend.map(d => d.spy_ytd_pct);
const _ytdYTickFn = function(v){ return (v>=0?'+':'') + v.toFixed(1) + '%'; };
const _ytdTooltipFn = function(c){ const v=c.parsed.y; return c.dataset.label+': '+(v==null?'n/a':(v>=0?'+':'')+v.toFixed(2)+'%'); };
ytdChart = new Chart(document.getElementById('ytdCompareChart'), { type:'line', data:{ labels:dates, datasets:[
  { label:'Portfolio (₩)', data:ytdPortData, borderColor:'#00E5BC', backgroundColor:'rgba(0,229,188,0.08)', fill:true, tension:0.3, pointRadius:2, borderWidth:2 },
  { label:'S&P 500 (₩)', data:ytdSpyData, borderColor:'#a3aac4', backgroundColor:'rgba(163,170,196,0.05)', borderDash:[6,4], fill:false, tension:0.3, pointRadius:2, borderWidth:2 }
]}, options:{ responsive:true, plugins:{ legend:{ position:'top' }, tooltip:{ callbacks:{ label:_ytdTooltipFn }}}, scales:{ y:{ ...dso, ticks:{ ...dso.ticks, callback:_ytdYTickFn }, title:{ display:true, text:'%', color:'#a3aac4' }}}}});
_wireRangeToggle('ytdRangeToggle', ytdChart, { min: 0, max: 50 });
{% endif %}
```

수정 후:

```html
{% if latest.ytd_pct is not none and latest.spy_ytd_pct is not none %}
const ytdPortData = trend.map(d => d.ytd_pct);
const ytdSpyData  = trend.map(d => d.spy_ytd_pct);
const ytdDitData  = trend.map(d => d.dit_ytd_pct);
const ytdRestData = trend.map(d => d.rest_ytd_pct);
const _ytdYTickFn = function(v){ return (v>=0?'+':'') + v.toFixed(1) + '%'; };
const _ytdTooltipFn = function(c){ const v=c.parsed.y; return c.dataset.label+': '+(v==null?'n/a':(v>=0?'+':'')+v.toFixed(2)+'%'); };
ytdChart = new Chart(document.getElementById('ytdCompareChart'), { type:'line', data:{ labels:dates, datasets:[
  { label:'Portfolio (₩)', data:ytdPortData, borderColor:'#00E5BC', backgroundColor:'rgba(0,229,188,0.08)', fill:true, tension:0.3, pointRadius:2, borderWidth:2 },
  { label:'디아이티 (110990)', data:ytdDitData, borderColor:'#ff716c', backgroundColor:'rgba(255,113,102,0.04)', fill:false, tension:0.3, pointRadius:2, borderWidth:2 },
  { label:'나머지', data:ytdRestData, borderColor:'#a78bfa', backgroundColor:'rgba(167,139,250,0.04)', fill:false, tension:0.3, pointRadius:2, borderWidth:2 },
  { label:'S&P 500 (₩)', data:ytdSpyData, borderColor:'#a3aac4', backgroundColor:'rgba(163,170,196,0.05)', borderDash:[6,4], fill:false, tension:0.3, pointRadius:2, borderWidth:2 }
]}, options:{ responsive:true, plugins:{ legend:{ position:'top' }, tooltip:{ callbacks:{ label:_ytdTooltipFn }}}, scales:{ y:{ ...dso, ticks:{ ...dso.ticks, callback:_ytdYTickFn }, title:{ display:true, text:'%', color:'#a3aac4' }}}}});
_wireRangeToggle('ytdRangeToggle', ytdChart, { min: 0, max: 80 });
{% endif %}
```

- [ ] **Step 2: Y축 토글 manual 라벨 텍스트 변경**

`templates/trend_template.html:179` 의 `<button data-mode="manual" ...>0~50%</button>` 를 다음으로 교체:

기존:
```html
        <button data-mode="manual" class="range-btn px-3 py-1 rounded-md text-[11px] font-bold bg-surface-container-high text-on-surface-variant border border-outline-variant/20">0~50%</button>
```

수정:
```html
        <button data-mode="manual" class="range-btn px-3 py-1 rounded-md text-[11px] font-bold bg-surface-container-high text-on-surface-variant border border-outline-variant/20">0~80%</button>
```

- [ ] **Step 3: `_updateYtdChart()` 에 datasets[2,3] 업데이트 추가**

`templates/trend_template.html:355-365` 의 `_updateYtdChart` 함수를 수정. 기존:

```javascript
function _updateYtdChart(trendArr){
  if(!ytdChart) return;
  if(!trendArr || trendArr.length === 0) return;
  const portSeries = trendArr.map(d => d.ytd_pct);
  const spySeries  = trendArr.map(d => d.spy_ytd_pct);
  if(portSeries.every(v => v == null) || spySeries.every(v => v == null)) return;
  ytdChart.data.labels = trendArr.map(d => d.date.slice(5));
  ytdChart.data.datasets[0].data = portSeries;
  ytdChart.data.datasets[1].data = spySeries;
  ytdChart.update();
}
```

수정:

```javascript
function _updateYtdChart(trendArr){
  if(!ytdChart) return;
  if(!trendArr || trendArr.length === 0) return;
  const portSeries = trendArr.map(d => d.ytd_pct);
  const spySeries  = trendArr.map(d => d.spy_ytd_pct);
  const ditSeries  = trendArr.map(d => d.dit_ytd_pct);
  const restSeries = trendArr.map(d => d.rest_ytd_pct);
  if(portSeries.every(v => v == null) || spySeries.every(v => v == null)) return;
  ytdChart.data.labels = trendArr.map(d => d.date.slice(5));
  // datasets 배열 순서: Portfolio(0) → 디아이티(1) → 나머지(2) → S&P(3)
  ytdChart.data.datasets[0].data = portSeries;
  ytdChart.data.datasets[1].data = ditSeries;
  ytdChart.data.datasets[2].data = restSeries;
  ytdChart.data.datasets[3].data = spySeries;
  ytdChart.update();
}
```

- [ ] **Step 4: Commit**

```bash
git add templates/trend_template.html
git commit -m "feat(trend): add DIT (110990) and rest YTD lines to comparison chart

4 datasets total: Portfolio (#00E5BC), 디아이티 (#ff716c), 나머지 (#a78bfa),
S&P 500 (#a3aac4 dashed). Y axis manual toggle: 0~50% → 0~80% to accommodate
DIT's typical YTD range. _updateYtdChart wires owner toggle to all 4 lines."
```

---

## Task 13: 로컬 검증 — pipeline + 트렌드 페이지 시각 확인

**Files:**
- 실행만, 코드 변경 없음

- [ ] **Step 1: 빠른 회귀 실행 (스캐너 스킵)**

```bash
SKIP_SCANNERS=1 python pipeline.py
```
PowerShell:
```powershell
$env:SKIP_SCANNERS=1; python pipeline.py
```

Expected:
- 에러 없이 완료
- `reports/trend_YYYY-MM-DD.html` 생성됨
- 콘솔 로그에 `me: YTD=...`, `wife: YTD=...` 출력

- [ ] **Step 2: 생성된 트렌드 페이지 열어서 시각 확인**

```bash
python -c "import webbrowser; import os; from datetime import datetime; today = datetime.now().strftime('%Y-%m-%d'); p = os.path.abspath(f'reports/trend_{today}.html'); webbrowser.open(f'file:///{p}')"
```

브라우저에서 확인:
- [ ] `포트폴리오 vs S&P 500 (₩) — 2026 YTD` 차트에 4 라인 표시
- [ ] Legend 순서: Portfolio → 디아이티 → 나머지 → S&P 500
- [ ] 색상: 청록 / 적색 / 보라 / 회색(점선)
- [ ] Y축 토글 클릭 `Auto` ↔ `0~80%` 작동
- [ ] Owner 토글 `내 포트 / 와이프 / 합산` 전환 시 4 라인 모두 데이터 변경
- [ ] 차트 시작점 = 2026-01-02 (1/2 anchor)
- [ ] 차트 종료점 = 오늘 (또는 마지막 거래일)
- [ ] 1/2 시점의 4 라인이 모두 0%에서 출발

- [ ] **Step 3: 콘솔 에러 확인**

브라우저 DevTools (F12) → Console 탭. Chart.js 관련 에러 없음을 확인.

- [ ] **Step 4: 데이터 commit (pipeline이 생성한 리포트)**

```bash
git add reports/
git commit -m "data(report): regenerate trend page with DIT/rest decomposition

Pipeline run after Task 12 confirms 4 YTD lines render correctly across
me / wife / combined owner toggle and Auto / 0~80% Y-axis toggle."
```

---

## Task 14: CLAUDE.md "진행 중인 계획" 등록

**Files:**
- Modify: `CLAUDE.md` ("## 진행 중인 계획" 섹션)

- [ ] **Step 1: CLAUDE.md 수정**

`CLAUDE.md` 의 "## 진행 중인 계획" 섹션 아래 (Portfolio Stop Signal System v1.0 항목 직후)에 신규 항목 추가:

```markdown
- [Trend Page YTD 디아이티/나머지 Decomposition](docs/superpowers/plans/2026-05-11-trend-dit-decomposition.md) — 트렌드 페이지 `포트폴리오 vs S&P 500 (₩) — 2026 YTD` 차트에 디아이티(110990) 단독 + 나머지(110990 제외) 라인 2개 추가 · me/wife/합산 3 owner 뷰 모두 지원 · 1/2 anchor 전체 backfill · 단일 Y축 4 라인 · Y토글 0~80% · 신규 6 필드 (`dit_ytd_pct`, `rest_ytd_pct`, `dit_v0_krw`, `dit_now_krw`, `rest_v0_krw`, `rest_now_krw`) 합산 뷰 KRW 합산 후 % 재계산
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: register trend DIT/rest decomposition plan in CLAUDE.md"
```

---

## Self-Review Checklist

(이 섹션은 plan 실행 후 reviewer가 점검하는 항목)

### 1. Spec coverage
- [x] §3 결정 1 (차트만) → Task 12
- [x] §3 결정 2 (3 owner 뷰) → Task 11 (combined), Task 12 (owner toggle)
- [x] §3 결정 3 (1/2 backfill) → Task 8, 9
- [x] §3 결정 4 (단일 Y축 4 라인) → Task 12
- [x] §3 결정 5 (Y토글 0~80%) → Task 12 Step 1, 2
- [x] §4 데이터 모델 6 필드 → Task 3, 4, 5, 7
- [x] §4 None 시나리오 → Task 2 (`compute_dit_rest_decomposition` early returns)
- [x] §4 합산 KRW 합산 후 % 재계산 → Task 11
- [x] §5 KOSDAQ 환율 무관 → Task 2 (`dit_now_per_share = float(dit_today_price)` no FX multiply) + Task 1 test
- [x] §5 dit + rest == total 일관성 → Task 1 test + Task 9 Step 2 검증
- [x] §6 색상 (#00E5BC / #ff716c / #a78bfa / #a3aac4) → Task 12 Step 1
- [x] §6 datasets 순서 = legend 순서 → Task 12 Step 1, 3
- [x] §7 단일 진실의 원천 → Task 2 (헬퍼 추가) + Task 3 (compute_returns 호출) + Task 7 (backfill 호출)
- [x] §7 going-forward (`pipeline.py` 호출) → Task 5
- [x] §8 테스트 5개 (보유/미보유/환율무관/일관성/합산) → Task 1
- [x] §8 통합 spot-check → Task 9 (3 검증 단계)
- [x] §10 파일 변경 전체 → Tasks 1-13 망라

### 2. Placeholder scan
- "TBD" / "implement later" / "fill in details": 없음 ✓
- "Add appropriate error handling" / "handle edge cases": 모두 구체적 분기 명시됨 ✓
- "Similar to Task N" 없음 (각 task 자체완결) ✓

### 3. Type consistency
- 헬퍼 이름: `compute_dit_rest_decomposition` (Task 1, 2, 3, 7 일관) ✓
- 반환 dict 키 (6개): `dit_ytd_pct`, `rest_ytd_pct`, `dit_v0_krw`, `dit_now_krw`, `rest_v0_krw`, `rest_now_krw` — Task 1, 2, 3, 4, 5, 7, 10, 11, 12 일관 ✓
- 상수: `DIT_TICKER = "110990"` (Task 2 정의, Task 6 import) ✓
- 색상 HEX: `#ff716c` (디아이티), `#a78bfa` (나머지) — spec / plan 일치 ✓

### 4. 실행 순서 의존성
- Task 2 → Task 3 (헬퍼 정의 → compute_returns에서 호출)
- Task 4 → Task 5 (시그너처 확장 → 호출부 인자 추가)
- Task 6 → Task 7 (헬퍼 + fetch 추가 → main loop 사용)
- Task 8 → Task 9 (rebuild로 base snapshots 생성 → backfill로 YTD 필드 채움) **중요**
- Task 9 → Task 10, 11 (데이터 있어야 report_generator 출력 검증 가능)
- Task 10, 11 → Task 12 (백엔드 payload 있어야 차트 작동)
- Task 12 → Task 13 (차트 변경 → 시각 검증)

---

## Execution Notes

- **Task 8 + 9 는 실행 결과 데이터를 commit**한다. `.githooks/check_history_shrink.py` pre-commit 가드가 daily JSON top-level 키 개수 감소 시 abort하므로, rebuild 결과가 기존보다 키가 적으면 우회 필요:
  ```bash
  ALLOW_HISTORY_SHRINK=1 git commit -m "..."
  ```
  단, 1/2~ 전체 backfill은 키 개수가 *늘어나는* 방향이므로 가드 트리거 안 됨 (현 me=32, wife=35 → rebuild 후 90+).
- **commit 전 git status 확인**: rebuild + backfill 후 `data/baseline_2026_*.json` 도 자동 갱신될 수 있다 (incremental append). 함께 commit.
- **Windows 인코딩**: pipeline.py 실행 시 PowerShell에서 한글 출력 cp949 에러 시 `$env:PYTHONIOENCODING="utf-8"` 설정 후 재실행.
