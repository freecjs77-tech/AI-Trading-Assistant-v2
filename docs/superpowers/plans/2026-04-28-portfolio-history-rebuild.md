# Portfolio History Rebuild (2026-01-02~) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 현재 보유(me/wife) 기준으로 2026-01-02 ~ 최신 거래일까지의 일별 포트폴리오 히스토리(`portfolio_daily.json`, `portfolio_daily_wife.json`)를 실제 시장 데이터로 재계산해 트렌드 페이지(me / wife / 합산 탭)가 1월 2일부터 정확한 자산·PnL·배당 시계열을 보여주게 한다.

**Architecture:** 신규 모듈 `portfolio_history_core.py`가 (1) Yahoo v8 chart 직렬 다운로드, (2) TTM 일별 배당 계산, (3) FX/매크로 조회, (4) me/wife 공통 일일 스냅샷 빌더를 제공한다. 신규 오케스트레이터 `rebuild_portfolio_history.py`가 이 코어로 me·wife 양쪽을 한 번에 재생성한다. 기존 3개의 분기된 백필 경로(`rebuild_trend_data.py`, `rebuild_wife_history.py`, `regenerate_history.py`의 portfolio_daily 블록)에서 하드코딩 배당 / `div=0` / wife skip 문제를 제거하고 모두 신규 코어에 위임한다. 합산 탭은 `report_generator._build_combined_payload()`가 me + wife daily를 date-union 합산하므로 별도 파일이 필요 없다.

**Tech Stack:** Python 3.10+, requests(Yahoo v8 chart API), pandas, yfinance(`Ticker.dividends`만), pytest, Jinja2/Chart.js(트렌드 템플릿).

**참고 분석:** 트렌드 백필 점검 결과 — `rebuild_trend_data.py:243` me 배당 ₩42,218,109 × FX 비례 하드코딩, `rebuild_trend_data.py:53-54,303` wife 배당 ₩16,675,519 × FX 비례 하드코딩, `rebuild_wife_history.py:174-175` `div_annual_krw=0/div_yield=0` 하드코딩, `regenerate_history.py:443` wife는 portfolio_daily 갱신 skip. 한 번에 정리한다.

---

## File Structure

**Create:**
- `portfolio_history_core.py` — Yahoo 다운로드 / TTM 배당 / 일별 me·wife 스냅샷 빌더 (단일 진실의 원천)
- `rebuild_portfolio_history.py` — 최상위 오케스트레이터 (`--start-date`, `--end-date`, `--dry-run`, `--owner` 인자)
- `tests/test_portfolio_history_core.py` — 코어 단위 테스트 (모킹된 가격/배당 시리즈)
- `tests/fixtures/history_rebuild/` — 테스트용 더미 가격/배당 JSON 픽스처

**Modify:**
- `rebuild_trend_data.py:240-262` (me 스냅샷) — 하드코딩 배당 블록 제거, 신규 코어 호출로 위임
- `rebuild_trend_data.py:266-322` (wife 스냅샷) — 하드코딩 base 제거, 신규 코어 호출로 위임
- `rebuild_wife_history.py:160-185` — `div_annual_krw=0/div_yield=0`를 신규 코어 TTM 결과로 대체
- `backfill_dividends.py:35-91` — 헬퍼(`_normalize_dividends`, `compute_ttm_dividend`, `fetch_all_dividends`, `fetch_fx_history`, `get_fx_at`)를 `portfolio_history_core`에서 re-export하도록 정리 (DRY)

**Auto-generated (백업/결과):**
- `history/portfolio_daily.json.bak.20260428-rebuild`
- `history/portfolio_daily_wife.json.bak.20260428-rebuild`
- `history/portfolio_daily.json` (덮어쓰기, 2026-01-02 ~ 최신)
- `history/portfolio_daily_wife.json` (덮어쓰기, 2026-01-02 ~ 최신)

---

## Design Decisions (locked)

1. **Anchor**: `START_DATE = "2026-01-02"`. 종료일은 SPY 일봉의 마지막 인덱스(미국 거래일 기준).
2. **보유 동결**: me는 `portfolios/me.md` 현시점 파싱(`regenerate_history.parse_portfolio_holdings`), wife는 `rebuild_wife_history.HOLDINGS` 상수(KRW 기반 avg_cost). 과거 매매는 무시.
3. **avg_cost 의미**: me는 `avg_cost = (value - pnl) / shares` (네이티브 통화). wife는 `avg_cost_krw` 직접 보유. cost_basis는 시점 무관 상수.
4. **배당**: 모든 일자에 대해 `compute_ttm_dividend(target_ts) = sum(dividends in (target-365d, target])` × shares × FX(US 종목만). 분기 ex-div 통과 시 단계 점프는 회계상 정확하므로 그대로 둠.
5. **yield 분모**: `div_annual_krw / total_value_krw × 100` (현행 유지). cost basis 분모로 바꾸자는 제안은 별도 PR.
6. **거래일**: SPY `Close` 인덱스 기준. KOSPI 종목은 target_ts 이전 마지막 가격을 사용(현행 동일). 비거래일은 자동 skip.
7. **매크로**: VIX(`^VIX`), 30Y(`^TYX`), FX(`USDKRW=X`). master_switch는 QQQ/SPY vs MA200(현행 동일).
8. **합산 탭**: 별도 파일 없음. `report_generator._build_combined_payload`가 me + wife daily date-union 합산.
9. **백업/덮어쓰기**: 실행 시 기존 파일을 `*.bak.20260428-rebuild`로 1회 백업 후 전체 덮어쓰기. 부분 보존 안 함 (현재 보유 기준 일관성 우선).
10. **"오늘" 데이터**: 파이프라인이 매일 추가하는 마지막 줄과 정합성 보장 — rebuild는 SPY 마지막 인덱스가 오늘이면 오늘까지 포함, 어제까지면 어제까지만 채움.

---

## Task 1: 코어 모듈 스켈레톤 + 상수

**Files:**
- Create: `portfolio_history_core.py`
- Create: `tests/test_portfolio_history_core.py`

- [ ] **Step 1: 스켈레톤 작성**

```python
# portfolio_history_core.py
"""포트폴리오 히스토리 재계산 코어.

Yahoo Finance v8 chart API 직접 호출 + 배당 TTM 일별 합산 + me/wife 공통 스냅샷 빌더.
rebuild_portfolio_history.py / rebuild_trend_data.py / rebuild_wife_history.py 모두
이 모듈로 위임한다 (DRY, 단일 진실의 원천).

설계: docs/superpowers/plans/2026-04-28-portfolio-history-rebuild.md
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import pandas as pd
import requests

START_DATE = "2026-01-02"
TICKER_DELAY = 0.7  # rate limit 회피
MAX_RETRIES = 3
MACRO_SYMBOLS = {
    "VIX": "^VIX",
    "yield_30Y": "^TYX",
    "USD_KRW": "USDKRW=X",
}
```

- [ ] **Step 2: 테스트 파일에 import 점검**

```python
# tests/test_portfolio_history_core.py
"""portfolio_history_core 단위 테스트."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import portfolio_history_core as core


def test_constants():
    assert core.START_DATE == "2026-01-02"
    assert core.MACRO_SYMBOLS["USD_KRW"] == "USDKRW=X"
    assert core.MAX_RETRIES == 3
```

- [ ] **Step 3: 테스트 실행**

```bash
pytest tests/test_portfolio_history_core.py::test_constants -v
```
Expected: PASS

- [ ] **Step 4: 커밋**

```bash
git add portfolio_history_core.py tests/test_portfolio_history_core.py
git commit -m "feat(history): scaffold portfolio_history_core module"
```

---

## Task 2: TTM 배당 계산 함수 (순수 로직)

**Files:**
- Modify: `portfolio_history_core.py` (append)
- Modify: `tests/test_portfolio_history_core.py` (append)

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_portfolio_history_core.py 에 추가
import pandas as pd


def test_compute_ttm_dividend_full_year():
    # 분기 4회 배당, 1년 윈도우 안에 모두 들어옴
    divs = pd.Series(
        [0.5, 0.5, 0.6, 0.6],
        index=pd.to_datetime(["2025-05-01", "2025-08-01", "2025-11-01", "2026-02-01"]),
    )
    target = pd.Timestamp("2026-04-15")
    assert core.compute_ttm_dividend(divs, target) == pytest.approx(2.2)


def test_compute_ttm_dividend_drops_old():
    # 1년 이전은 윈도우 밖
    divs = pd.Series(
        [1.0, 0.5],
        index=pd.to_datetime(["2025-01-15", "2025-06-01"]),
    )
    target = pd.Timestamp("2026-04-15")
    # 2025-01-15는 (2025-04-15, 2026-04-15] 밖, 0.5만 포함
    assert core.compute_ttm_dividend(divs, target) == pytest.approx(0.5)


def test_compute_ttm_dividend_empty():
    assert core.compute_ttm_dividend(pd.Series(dtype=float), pd.Timestamp("2026-04-15")) == 0.0
```

`tests/test_portfolio_history_core.py` 상단에 `import pytest` 추가.

- [ ] **Step 2: 실패 확인**

```bash
pytest tests/test_portfolio_history_core.py -v
```
Expected: 3 FAILs (`AttributeError: module ... has no attribute 'compute_ttm_dividend'`)

- [ ] **Step 3: 구현**

`portfolio_history_core.py`에 추가:
```python
def compute_ttm_dividend(divs: pd.Series, target: pd.Timestamp) -> float:
    """target 이전 365일 윈도우의 배당 합계 (주당)."""
    if divs is None or len(divs) == 0:
        return 0.0
    cutoff = target - pd.DateOffset(years=1)
    mask = (divs.index > cutoff) & (divs.index <= target)
    return float(divs[mask].sum())


def normalize_dividends(divs) -> pd.Series:
    """yfinance Ticker.dividends 반환을 Series로 정규화 (Series/DataFrame 양 대응)."""
    if divs is None:
        return pd.Series(dtype=float)
    if hasattr(divs, "columns"):
        col = "Dividends" if "Dividends" in divs.columns else divs.columns[0]
        divs = divs[col]
    if len(divs) == 0:
        return pd.Series(dtype=float)
    if divs.index.tz is not None:
        divs.index = divs.index.tz_localize(None)
    return divs.astype(float)
```

- [ ] **Step 4: 통과 확인**

```bash
pytest tests/test_portfolio_history_core.py -v
```
Expected: 4 PASS

- [ ] **Step 5: 커밋**

```bash
git add portfolio_history_core.py tests/test_portfolio_history_core.py
git commit -m "feat(history): TTM dividend computation"
```

---

## Task 3: Yahoo v8 chart 다운로더 (모킹 가능 인터페이스)

**Files:**
- Modify: `portfolio_history_core.py`
- Modify: `tests/test_portfolio_history_core.py`

- [ ] **Step 1: 다운로더 구현**

`portfolio_history_core.py`에 추가:
```python
def make_yahoo_session() -> tuple[requests.Session, str]:
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    })
    crumb = ""
    try:
        r = sess.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=10)
        if r.status_code == 200:
            crumb = r.text.strip()
    except Exception:
        pass
    return sess, crumb


def fetch_chart(sess: requests.Session, crumb: str, symbol: str, range_str: str = "1y") -> pd.DataFrame | None:
    """Yahoo v8 chart API → 일봉 OHLCV DataFrame."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": range_str, "interval": "1d", "includeAdjustedClose": "true"}
    if crumb:
        params["crumb"] = crumb
    try:
        r = sess.get(url, params=params, timeout=15)
        if r.status_code != 200:
            return None
        result = r.json().get("chart", {}).get("result", [])
        if not result:
            return None
        ts = result[0].get("timestamp", [])
        q = result[0].get("indicators", {}).get("quote", [{}])[0]
        if not ts or not q:
            return None
        df = pd.DataFrame({
            "Open": q.get("open", []),
            "High": q.get("high", []),
            "Low": q.get("low", []),
            "Close": q.get("close", []),
            "Volume": q.get("volume", []),
        }, index=pd.to_datetime(ts, unit="s", utc=True))
        df.index = df.index.tz_localize(None)
        return df.dropna(subset=["Close"])
    except Exception:
        return None


def download_all(symbols: list[str], range_str: str = "1y", logger=print) -> dict[str, pd.DataFrame]:
    """모든 심볼 직렬 다운로드 + 재시도. (rate limit 회피)"""
    sess, crumb = make_yahoo_session()
    logger(f"  세션: crumb={'OK' if crumb else 'EMPTY'} / 심볼 {len(symbols)}개")
    out: dict[str, pd.DataFrame] = {}
    for idx, sym in enumerate(symbols):
        df = None
        for attempt in range(MAX_RETRIES):
            df = fetch_chart(sess, crumb, sym, range_str=range_str)
            if df is not None and len(df) >= 10:
                break
            time.sleep(2 * (attempt + 1))
        if df is not None:
            out[sym] = df
            logger(f"  [{idx+1:2d}/{len(symbols)}] {sym:<12} OK ({len(df)}일)")
        else:
            logger(f"  [{idx+1:2d}/{len(symbols)}] {sym:<12} SKIP")
        time.sleep(TICKER_DELAY)
    return out


def price_at(dfs: dict[str, pd.DataFrame], sym: str, target_ts: pd.Timestamp) -> float | None:
    """target_ts 이전 마지막 종가."""
    df = dfs.get(sym)
    if df is None or df.empty:
        return None
    sub = df["Close"][df["Close"].index <= target_ts]
    return float(sub.iloc[-1]) if not sub.empty else None
```

- [ ] **Step 2: price_at 단위 테스트 추가**

```python
# tests/test_portfolio_history_core.py 에 추가
def _make_df(dates, prices):
    return pd.DataFrame({"Close": prices}, index=pd.to_datetime(dates))


def test_price_at_picks_last_le_target():
    dfs = {"AAPL": _make_df(["2026-01-02", "2026-01-03", "2026-01-06"], [100.0, 101.0, 105.0])}
    assert core.price_at(dfs, "AAPL", pd.Timestamp("2026-01-04")) == 101.0


def test_price_at_returns_none_for_missing():
    assert core.price_at({}, "ZZZ", pd.Timestamp("2026-01-04")) is None


def test_price_at_returns_none_when_target_before_first():
    dfs = {"AAPL": _make_df(["2026-01-05"], [100.0])}
    assert core.price_at(dfs, "AAPL", pd.Timestamp("2026-01-02")) is None
```

- [ ] **Step 3: 테스트 통과 확인**

```bash
pytest tests/test_portfolio_history_core.py -v
```
Expected: 7 PASS

- [ ] **Step 4: 커밋**

```bash
git add portfolio_history_core.py tests/test_portfolio_history_core.py
git commit -m "feat(history): Yahoo v8 chart downloader + price_at helper"
```

---

## Task 4: me 일별 스냅샷 빌더 (TTM 배당 사용)

**Files:**
- Modify: `portfolio_history_core.py`
- Modify: `tests/test_portfolio_history_core.py`

- [ ] **Step 1: 실패 테스트 작성 — me 스냅샷이 div_annual_krw를 TTM에서 계산하는지**

```python
# tests/test_portfolio_history_core.py 에 추가
def test_build_me_snapshot_uses_ttm_dividend():
    # 단순 포트폴리오: AAPL 10주 + 005930(KR) 5주
    holdings = [
        {"ticker": "AAPL", "shares": 10.0, "avg_cost": 100.0},
        {"ticker": "005930", "shares": 5.0, "avg_cost": 70000.0},
    ]
    yf_map = {"AAPL": "AAPL", "005930": "005930.KS"}
    target = pd.Timestamp("2026-04-15")
    dfs = {
        "AAPL":      _make_df(["2026-04-15"], [200.0]),
        "005930.KS": _make_df(["2026-04-15"], [80000.0]),
        "USDKRW=X":  _make_df(["2026-04-15"], [1400.0]),
        "^VIX":      _make_df(["2026-04-15"], [18.0]),
        "^TYX":      _make_df(["2026-04-15"], [4.5]),
        "QQQ":       _make_df(["2026-04-15"], [400.0]),
        "SPY":       _make_df(["2026-04-15"], [500.0]),
    }
    # AAPL: 분기 0.25 × 4 = 1.00 / 005930: 1500
    divs_map = {
        "AAPL": pd.Series(
            [0.25, 0.25, 0.25, 0.25],
            index=pd.to_datetime(["2025-05-01", "2025-08-01", "2025-11-01", "2026-02-01"]),
        ),
        "005930": pd.Series([1500.0], index=pd.to_datetime(["2025-12-01"])),
    }
    snap = core.build_me_snapshot(target, holdings, yf_map, dfs, divs_map)
    # AAPL: 1.00 × 10 × 1400 = 14000, 005930: 1500 × 5 = 7500 → 합 21500
    assert snap["div_annual_krw"] == 21500
    # total_value: AAPL 10×200×1400 + 005930 5×80000 = 2,800,000 + 400,000 = 3,200,000
    assert snap["total_value_krw"] == 3_200_000
    assert snap["div_yield"] == round(21500 / 3_200_000 * 100, 2)
    assert snap["usd_krw"] == 1400.0
```

- [ ] **Step 2: 실패 확인**

```bash
pytest tests/test_portfolio_history_core.py::test_build_me_snapshot_uses_ttm_dividend -v
```
Expected: FAIL (`AttributeError: ... 'build_me_snapshot'`)

- [ ] **Step 3: 빌더 구현 — `portfolio_history_core.py`에 추가**

```python
from portfolio_data import is_kospi_ticker, get_ticker_name, get_ticker_class


def _macro_at(dfs: dict[str, pd.DataFrame], target_ts: pd.Timestamp) -> dict:
    out = {}
    for key, sym in MACRO_SYMBOLS.items():
        v = price_at(dfs, sym, target_ts)
        out[key] = round(v, 4) if v is not None else None
    return out


def _master_switch_at(dfs: dict[str, pd.DataFrame], yf_map: dict, target_ts: pd.Timestamp) -> str:
    qqq_below = spy_below = False
    for bench in ("QQQ", "SPY"):
        df = dfs.get(yf_map.get(bench, bench))
        if df is None:
            continue
        s = df["Close"][df["Close"].index <= target_ts]
        if len(s) >= 200:
            ma200_val = float(s.rolling(200).mean().iloc[-1])
            cur = float(s.iloc[-1])
            if bench == "QQQ":
                qqq_below = cur < ma200_val
            else:
                spy_below = cur < ma200_val
    if qqq_below and spy_below:
        return "RED"
    if qqq_below or spy_below:
        return "YELLOW"
    return "GREEN"


def build_me_snapshot(
    target_ts: pd.Timestamp,
    holdings: list[dict],
    yf_map: dict[str, str],
    dfs: dict[str, pd.DataFrame],
    divs_map: dict[str, pd.Series],
) -> dict | None:
    """me 포트폴리오 1일 스냅샷.

    holdings: [{ticker, shares, avg_cost}] (avg_cost는 네이티브 통화)
    yf_map:   {ticker -> yfinance symbol}
    dfs:      {symbol -> Close DataFrame}
    divs_map: {ticker -> 배당 Series (주당, 네이티브 통화)}
    """
    macro = _macro_at(dfs, target_ts)
    usd_krw = macro.get("USD_KRW") or 0
    rate = usd_krw if usd_krw and usd_krw > 1 else None
    if rate is None:
        return None  # FX 누락 일자 skip

    us_value = us_cost = 0.0
    kospi_value = kospi_cost = 0.0
    for p in holdings:
        t = p["ticker"]
        px = price_at(dfs, yf_map.get(t, t), target_ts)
        if px is None:
            continue
        val = p["shares"] * px
        cost = p["shares"] * p["avg_cost"]
        if is_kospi_ticker(t):
            kospi_value += val; kospi_cost += cost
        else:
            us_value += val;    us_cost += cost

    total_value_krw = us_value * rate + kospi_value
    cost_basis_krw = us_cost * rate + kospi_cost
    if total_value_krw <= 0:
        return None
    pnl_krw = total_value_krw - cost_basis_krw
    pnl_pct = (pnl_krw / cost_basis_krw * 100) if cost_basis_krw > 0 else 0

    # Cash (BIL)
    bil = next((p for p in holdings if p["ticker"] == "BIL"), None)
    cash_val = 0.0
    if bil:
        bp = price_at(dfs, "BIL", target_ts)
        if bp is not None:
            cash_val = bil["shares"] * bp
    cash_krw = cash_val * rate
    denom_usd = us_value + (kospi_value / rate)
    cash_pct = (cash_val / denom_usd * 100) if denom_usd > 0 else 0

    # 비중
    weights_cat: dict[str, float] = {}
    weights_ticker: dict[str, float] = {}
    for p in holdings:
        t = p["ticker"]
        px = price_at(dfs, yf_map.get(t, t), target_ts)
        if px is None:
            continue
        val = p["shares"] * px
        val_krw = val if is_kospi_ticker(t) else val * rate
        w = (val_krw / total_value_krw * 100) if total_value_krw > 0 else 0
        nm = (get_ticker_name(t) or t) if is_kospi_ticker(t) else t
        weights_ticker[nm] = round(w, 1)
        cls = get_ticker_class(t) or "Other"
        weights_cat[cls] = weights_cat.get(cls, 0) + w
    weights_cat = {k: round(v, 1) for k, v in weights_cat.items()}

    # TTM 배당
    total_div_krw = 0.0
    for p in holdings:
        shares = p.get("shares", 0) or 0
        if shares <= 0:
            continue
        ttm = compute_ttm_dividend(divs_map.get(p["ticker"], pd.Series(dtype=float)), target_ts)
        if ttm <= 0:
            continue
        annual = ttm * shares
        total_div_krw += annual if is_kospi_ticker(p["ticker"]) else annual * rate
    div_annual_krw = round(total_div_krw)
    div_yield = round(total_div_krw / total_value_krw * 100, 2) if total_value_krw > 0 else 0.0

    return {
        "total_value_krw": round(total_value_krw),
        "cost_basis_krw": round(cost_basis_krw),
        "pnl_krw": round(pnl_krw),
        "pnl_pct": round(pnl_pct, 1),
        "cash_value_krw": round(cash_krw),
        "cash_pct": round(cash_pct, 1),
        "div_annual_krw": div_annual_krw,
        "div_yield": div_yield,
        "usd_krw": round(usd_krw, 2),
        "vix": round(macro["VIX"], 2) if macro.get("VIX") else None,
        "yield_30y": round(macro["yield_30Y"], 3) if macro.get("yield_30Y") else None,
        "master_switch": _master_switch_at(dfs, yf_map, target_ts),
        "holdings_count": len(holdings),
        "weights_by_category": weights_cat,
        "weights_by_ticker": weights_ticker,
    }
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
pytest tests/test_portfolio_history_core.py::test_build_me_snapshot_uses_ttm_dividend -v
```
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add portfolio_history_core.py tests/test_portfolio_history_core.py
git commit -m "feat(history): build_me_snapshot with TTM-based dividends"
```

---

## Task 5: wife 일별 스냅샷 빌더 (TTM 배당 사용)

**Files:**
- Modify: `portfolio_history_core.py`
- Modify: `tests/test_portfolio_history_core.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_portfolio_history_core.py 에 추가
def test_build_wife_snapshot_uses_ttm_dividend():
    # wife HOLDINGS 형식: (ticker, shares, avg_cost_krw)
    wife_holdings = [
        ("AAPL",   10.0,  150_000.0),  # avg_cost는 KRW 기반 (이미 환산된 매입원가)
        ("005930", 20.0,   75_000.0),
    ]
    usd_tickers = {"AAPL"}
    yf_map = {"AAPL": "AAPL", "005930": "005930.KS"}
    target = pd.Timestamp("2026-04-15")
    dfs = {
        "AAPL":      _make_df(["2026-04-15"], [200.0]),
        "005930.KS": _make_df(["2026-04-15"], [80000.0]),
        "USDKRW=X":  _make_df(["2026-04-15"], [1400.0]),
    }
    divs_map = {
        "AAPL": pd.Series([0.25] * 4, index=pd.to_datetime(
            ["2025-05-01", "2025-08-01", "2025-11-01", "2026-02-01"])),
        "005930": pd.Series([1500.0], index=pd.to_datetime(["2025-12-01"])),
    }
    snap = core.build_wife_snapshot(target, wife_holdings, usd_tickers, yf_map, dfs, divs_map)
    # AAPL value: 10×200×1400 = 2,800,000  / 005930 value: 20×80000 = 1,600,000 → 4,400,000
    assert snap["total_value_krw"] == 4_400_000
    # Dividend: AAPL 1.00×10×1400=14,000 / 005930 1500×20=30,000 → 44,000
    assert snap["div_annual_krw"] == 44_000
    assert snap["div_yield"] == round(44_000 / 4_400_000 * 100, 2)
```

- [ ] **Step 2: 실패 확인**

```bash
pytest tests/test_portfolio_history_core.py::test_build_wife_snapshot_uses_ttm_dividend -v
```
Expected: FAIL

- [ ] **Step 3: 구현 — `portfolio_history_core.py`에 추가**

```python
def build_wife_snapshot(
    target_ts: pd.Timestamp,
    wife_holdings: list[tuple[str, float, float]],
    usd_tickers: set[str],
    yf_map: dict[str, str],
    dfs: dict[str, pd.DataFrame],
    divs_map: dict[str, pd.Series],
) -> dict | None:
    """wife 포트폴리오 1일 스냅샷.

    wife_holdings: [(ticker, shares, avg_cost_krw)] — avg_cost는 이미 KRW 환산된 매입원가
    usd_tickers: 가격이 USD인 티커 집합 (가치 계산 시 FX 곱)
    """
    fx = price_at(dfs, "USDKRW=X", target_ts)
    if fx is None or fx <= 0:
        return None

    total_krw = 0.0
    cost_krw = 0.0
    weights_krw: dict[str, float] = {}
    miss = 0
    for ticker, shares, avg_cost_krw in wife_holdings:
        sym = yf_map.get(ticker, ticker)
        px = price_at(dfs, sym, target_ts)
        if px is None:
            miss += 1
            continue
        val_krw = px * shares * fx if ticker in usd_tickers else px * shares
        total_krw += val_krw
        cost_krw += avg_cost_krw * shares
        weights_krw[ticker] = val_krw

    if total_krw <= 0:
        return None
    pnl_krw = total_krw - cost_krw
    pnl_pct = round(pnl_krw / cost_krw * 100, 2) if cost_krw > 0 else 0
    weights_by_ticker = {t: round(v / total_krw * 100, 2) for t, v in weights_krw.items()}

    # TTM 배당 — wife는 BIL 외 USD/KR 모두 동일하게 계산
    total_div_krw = 0.0
    for ticker, shares, _ in wife_holdings:
        if shares <= 0:
            continue
        ttm = compute_ttm_dividend(divs_map.get(ticker, pd.Series(dtype=float)), target_ts)
        if ttm <= 0:
            continue
        annual = ttm * shares
        total_div_krw += annual * fx if ticker in usd_tickers else annual
    div_annual_krw = round(total_div_krw)
    div_yield = round(total_div_krw / total_krw * 100, 2) if total_krw > 0 else 0.0

    macro = _macro_at(dfs, target_ts)

    return {
        "total_value_krw": int(total_krw),
        "cost_basis_krw": int(cost_krw),
        "pnl_krw": int(pnl_krw),
        "pnl_pct": pnl_pct,
        "cash_value_krw": 0,
        "cash_pct": 0.0,
        "div_annual_krw": div_annual_krw,
        "div_yield": div_yield,
        "usd_krw": round(fx, 2),
        "vix": round(macro["VIX"], 2) if macro.get("VIX") else None,
        "yield_30y": round(macro["yield_30Y"], 3) if macro.get("yield_30Y") else None,
        "master_switch": "UNKNOWN",
        "holdings_count": len(wife_holdings) - miss,
        "weights_by_category": {},
        "weights_by_ticker": weights_by_ticker,
    }
```

- [ ] **Step 4: 통과 확인**

```bash
pytest tests/test_portfolio_history_core.py -v
```
Expected: 9 PASS

- [ ] **Step 5: 커밋**

```bash
git add portfolio_history_core.py tests/test_portfolio_history_core.py
git commit -m "feat(history): build_wife_snapshot with TTM-based dividends"
```

---

## Task 6: 배당 시리즈 일괄 fetch + 거래일 필터

**Files:**
- Modify: `portfolio_history_core.py`
- Modify: `tests/test_portfolio_history_core.py`

- [ ] **Step 1: 배당/거래일 헬퍼 추가 — `portfolio_history_core.py`**

```python
import yfinance as yf
from portfolio_data import is_korean_ticker, to_yfinance_symbol


def yf_symbol(ticker: str) -> str:
    return to_yfinance_symbol(ticker) if is_korean_ticker(ticker) else ticker


def fetch_all_dividends(tickers: list[str], delay: float = 0.4, logger=print) -> dict[str, pd.Series]:
    """티커별 전체 배당 시리즈."""
    out: dict[str, pd.Series] = {}
    for i, t in enumerate(tickers, 1):
        sym = yf_symbol(t)
        s = pd.Series(dtype=float)
        for attempt in range(MAX_RETRIES):
            try:
                s = normalize_dividends(yf.Ticker(sym).dividends)
                break
            except Exception:
                time.sleep(2 ** attempt)
        logger(f"  [{i:2}/{len(tickers)}] {sym}: {len(s)} events")
        out[t] = s
        time.sleep(delay)
    return out


def trading_dates_from(spy_df: pd.DataFrame, start: str) -> pd.DatetimeIndex:
    """SPY 일봉에서 start (YYYY-MM-DD) 이후 거래일 인덱스 추출."""
    s = spy_df["Close"].dropna()
    s = s[s.index >= pd.Timestamp(start)]
    return s.index
```

- [ ] **Step 2: trading_dates_from 테스트**

```python
def test_trading_dates_from_filters_by_start():
    df = _make_df(
        ["2025-12-30", "2026-01-02", "2026-01-03", "2026-01-06"],
        [400, 410, 411, 412],
    )
    idx = core.trading_dates_from(df, "2026-01-02")
    assert len(idx) == 3
    assert idx[0] == pd.Timestamp("2026-01-02")
```

- [ ] **Step 3: 통과 확인**

```bash
pytest tests/test_portfolio_history_core.py -v
```
Expected: 10 PASS

- [ ] **Step 4: 커밋**

```bash
git add portfolio_history_core.py tests/test_portfolio_history_core.py
git commit -m "feat(history): dividend fetcher + trading_dates helper"
```

---

## Task 7: 최상위 오케스트레이터 `rebuild_portfolio_history.py`

**Files:**
- Create: `rebuild_portfolio_history.py`

- [ ] **Step 1: 오케스트레이터 작성**

```python
#!/usr/bin/env python3
"""rebuild_portfolio_history.py — me + wife portfolio_daily 재생성 (2026-01-02~).

사용:
  python rebuild_portfolio_history.py                         # me + wife 모두
  python rebuild_portfolio_history.py --owner me --dry-run    # me만 검증
  python rebuild_portfolio_history.py --start-date 2026-01-02 --end-date 2026-04-28

원칙:
  - 현재 보유 동결 → 과거로 가격 replay
  - 배당은 TTM (compute_ttm_dividend), 하드코딩 없음
  - 기존 파일은 *.bak.<today>-rebuild로 백업 후 덮어쓰기
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))

import pandas as pd

import portfolio_history_core as core
from fetch_market_data import parse_portfolio_md
from portfolio_data import is_kospi_ticker, to_yfinance_symbol
from portfolio_paths import primary_portfolio_path
from regenerate_history import parse_portfolio_holdings
from rebuild_wife_history import HOLDINGS as WIFE_HOLDINGS, USD_TICKERS as WIFE_USD_TICKERS

ME_DAILY = PROJECT_DIR / "history" / "portfolio_daily.json"
WIFE_DAILY = PROJECT_DIR / "history" / "portfolio_daily_wife.json"


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d")
    bak = path.with_suffix(path.suffix + f".bak.{stamp}-rebuild")
    shutil.copy2(path, bak)
    return bak


def _collect_symbols(me_holdings, wife_holdings) -> tuple[list[str], dict[str, str]]:
    """me + wife + 매크로 + SPY 심볼 집합."""
    yf_map: dict[str, str] = {}
    for p in me_holdings:
        yf_map[p["ticker"]] = to_yfinance_symbol(p["ticker"])
    for t, _, _ in wife_holdings:
        yf_map.setdefault(t, to_yfinance_symbol(t) if not is_kospi_ticker(t) else to_yfinance_symbol(t))
        # is_kospi_ticker 분기는 to_yfinance_symbol 내부에서 처리됨

    syms = set(yf_map.values())
    syms.update(core.MACRO_SYMBOLS.values())
    syms.add("SPY")
    syms.add("QQQ")
    yf_map.setdefault("SPY", "SPY")
    yf_map.setdefault("QQQ", "QQQ")
    return sorted(syms), yf_map


def _div_tickers(me_holdings, wife_holdings) -> list[str]:
    s = {p["ticker"] for p in me_holdings}
    s.update(t for t, _, _ in wife_holdings)
    return sorted(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", choices=["me", "wife", "both"], default="both")
    ap.add_argument("--start-date", default=core.START_DATE)
    ap.add_argument("--end-date", default=None, help="기본: SPY 마지막 인덱스")
    ap.add_argument("--dry-run", action="store_true", help="저장 없이 결과만 출력")
    args = ap.parse_args()

    print(f"\n{'='*64}")
    print(f"  Portfolio history rebuild (start={args.start_date}, owner={args.owner})")
    print(f"{'='*64}")

    me_path = primary_portfolio_path(str(PROJECT_DIR))
    me_holdings = parse_portfolio_holdings(me_path)
    print(f"  me holdings: {len(me_holdings)} (from {me_path})")
    print(f"  wife holdings: {len(WIFE_HOLDINGS)} (from rebuild_wife_history.HOLDINGS)")

    syms, yf_map = _collect_symbols(me_holdings, WIFE_HOLDINGS)
    print(f"  unique symbols: {len(syms)}")

    print(f"\n  ── 1) Yahoo v8 chart 다운로드 ──")
    dfs = core.download_all(syms, range_str="1y")
    if "SPY" not in dfs:
        print("  ERROR: SPY 데이터 없음 — 거래일 판별 불가")
        sys.exit(1)

    trading = core.trading_dates_from(dfs["SPY"], args.start_date)
    if args.end_date:
        trading = trading[trading <= pd.Timestamp(args.end_date)]
    if len(trading) == 0:
        print(f"  ERROR: 거래일 0일 (start={args.start_date})")
        sys.exit(1)
    print(f"  거래일 {len(trading)}일: {trading[0].date()} ~ {trading[-1].date()}")

    print(f"\n  ── 2) 배당 히스토리 다운로드 ──")
    div_tickers = _div_tickers(me_holdings, WIFE_HOLDINGS)
    divs_map = core.fetch_all_dividends(div_tickers)

    me_daily: dict[str, dict] = {}
    wife_daily: dict[str, dict] = {}

    print(f"\n  ── 3) 일별 스냅샷 생성 ──")
    for ts in trading:
        ds = ts.strftime("%Y-%m-%d")
        if args.owner in ("me", "both"):
            snap = core.build_me_snapshot(ts, me_holdings, yf_map, dfs, divs_map)
            if snap is not None:
                me_daily[ds] = snap
        if args.owner in ("wife", "both"):
            snap_w = core.build_wife_snapshot(
                ts, WIFE_HOLDINGS, WIFE_USD_TICKERS, yf_map, dfs, divs_map
            )
            if snap_w is not None:
                wife_daily[ds] = snap_w

    # 출력 요약
    if me_daily:
        first, last = min(me_daily), max(me_daily)
        print(f"  me  : {len(me_daily)}일 ({first} ~ {last}) "
              f"first total ₩{me_daily[first]['total_value_krw']:,} → "
              f"last ₩{me_daily[last]['total_value_krw']:,}")
    if wife_daily:
        first, last = min(wife_daily), max(wife_daily)
        print(f"  wife: {len(wife_daily)}일 ({first} ~ {last}) "
              f"first total ₩{wife_daily[first]['total_value_krw']:,} → "
              f"last ₩{wife_daily[last]['total_value_krw']:,}")

    if args.dry_run:
        print("\n  [DRY-RUN] 저장 생략")
        return

    print(f"\n  ── 4) 백업 + 저장 ──")
    if args.owner in ("me", "both") and me_daily:
        bak = _backup(ME_DAILY)
        if bak:
            print(f"  backup: {bak}")
        with open(ME_DAILY, "w", encoding="utf-8") as f:
            json.dump(me_daily, f, ensure_ascii=False, indent=2)
        print(f"  saved : {ME_DAILY} ({len(me_daily)}일)")
    if args.owner in ("wife", "both") and wife_daily:
        bak = _backup(WIFE_DAILY)
        if bak:
            print(f"  backup: {bak}")
        with open(WIFE_DAILY, "w", encoding="utf-8") as f:
            json.dump(wife_daily, f, ensure_ascii=False, indent=2)
        print(f"  saved : {WIFE_DAILY} ({len(wife_daily)}일)")

    print(f"\n{'='*64}\n  완료\n{'='*64}\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 도움말 표시 확인 (네트워크 호출 없음)**

```bash
python rebuild_portfolio_history.py --help
```
Expected: argparse 도움말 출력, `--owner {me,wife,both}` `--start-date` `--end-date` `--dry-run` 4개 옵션 노출.

- [ ] **Step 3: 커밋**

```bash
git add rebuild_portfolio_history.py
git commit -m "feat(history): top-level rebuild orchestrator (me+wife, 2026-01-02~)"
```

---

## Task 8: 드라이런 실행 — 1주일치로 정합성 확인

**Files:** (실행만, 코드 변경 없음)

- [ ] **Step 1: 짧은 윈도우로 드라이런**

```bash
python rebuild_portfolio_history.py --start-date 2026-04-20 --dry-run
```
Expected:
- 거래일 5~7일
- me/wife 양쪽 first/last total 출력
- 마지막 일자(`2026-04-24` 또는 그 이후)의 me total이 현재 `history/portfolio_daily.json`의 동일 일자 ±1% 이내
- div_annual_krw가 0이 아니고 me는 40,000,000~45,000,000 KRW 범위

- [ ] **Step 2: 정합성 검증 스크립트**

```bash
python -c "
import json
import subprocess
# 새로 계산: dry-run으로는 저장 안 되므로 임시 파일에 직접 계산
# 대신 기존 파일 vs rebuild 결과 비교는 Step 3에서 실제 실행 후 수행
with open('history/portfolio_daily.json', encoding='utf-8') as f:
    cur = json.load(f)
last = max(k for k in cur if not k.startswith('_'))
print(f'현재 {last}: total ₩{cur[last][\"total_value_krw\"]:,}, div ₩{cur[last][\"div_annual_krw\"]:,}, yield {cur[last][\"div_yield\"]}%')
"
```
Expected: 비교 기준선 출력 (예: `2026-04-24: total ₩2,549,708,167, div ₩42,445,749, yield 1.66%`)

- [ ] **Step 3: 커밋 없음 (실행만)** — 결과를 기록하고 다음 task로

---

## Task 9: 본 실행 — 2026-01-02부터 전체 재생성

**Files:** (실행)
- Backup: `history/portfolio_daily.json.bak.20260428-rebuild`
- Backup: `history/portfolio_daily_wife.json.bak.20260428-rebuild`
- Overwrite: `history/portfolio_daily.json`
- Overwrite: `history/portfolio_daily_wife.json`

- [ ] **Step 1: 본 실행**

```bash
python rebuild_portfolio_history.py --start-date 2026-01-02
```
Expected:
- 거래일 ~80일 (1월 2일 ~ 4월 28일)
- me/wife 양쪽 saved 메시지
- 백업 파일 생성

- [ ] **Step 2: 결과 검증 — me**

```bash
python -c "
import json
with open('history/portfolio_daily.json', encoding='utf-8') as f:
    d = json.load(f)
ks = sorted(k for k in d if not k.startswith('_'))
print(f'me: {len(ks)}일 {ks[0]}~{ks[-1]}')
# 1월 2일 데이터 존재 확인
assert ks[0] == '2026-01-02', f'시작일 불일치: {ks[0]}'
# div_annual_krw 가 모든 일자에서 0이 아님
zero_div = [k for k in ks if d[k]['div_annual_krw'] == 0]
print(f'div=0 일자: {len(zero_div)}/{len(ks)}')
assert len(zero_div) == 0, f'배당 0인 일자 존재: {zero_div[:3]}'
# 배당이 환율 비례 직선이 아닌지 — 같은 환율 1480 ± 5인 두 날짜 비교 시 div 차이가 1% 이내가 아닌 경우가 있어야 함 (ex-div 점프)
# (가벼운 점검)
print(f'first: total ₩{d[ks[0]][\"total_value_krw\"]:,} div ₩{d[ks[0]][\"div_annual_krw\"]:,}')
print(f'last:  total ₩{d[ks[-1]][\"total_value_krw\"]:,} div ₩{d[ks[-1]][\"div_annual_krw\"]:,}')
"
```
Expected:
- me: 80일 전후, 시작 2026-01-02, 마지막은 SPY 마지막 거래일
- div=0 일자 0개
- first/last total 출력

- [ ] **Step 3: 결과 검증 — wife**

```bash
python -c "
import json
with open('history/portfolio_daily_wife.json', encoding='utf-8') as f:
    d = json.load(f)
ks = sorted(k for k in d if not k.startswith('_'))
print(f'wife: {len(ks)}일 {ks[0]}~{ks[-1]}')
assert ks[0] == '2026-01-02'
zero_div = [k for k in ks if d[k]['div_annual_krw'] == 0]
assert len(zero_div) == 0, f'wife 배당 0 일자: {zero_div[:3]}'
print(f'first: total ₩{d[ks[0]][\"total_value_krw\"]:,} div ₩{d[ks[0]][\"div_annual_krw\"]:,}')
print(f'last:  total ₩{d[ks[-1]][\"total_value_krw\"]:,} div ₩{d[ks[-1]][\"div_annual_krw\"]:,}')
"
```
Expected: wife도 80일 전후, 1월 2일 시작, 모든 일자에 배당 > 0.

- [ ] **Step 4: 커밋 (데이터 갱신)**

```bash
git add history/portfolio_daily.json history/portfolio_daily_wife.json
git commit -m "data(history): rebuild me+wife portfolio_daily from 2026-01-02"
```

(백업 파일 `*.bak.*`은 .gitignore에 따라 처리. 추적되면 별도 커밋.)

---

## Task 10: 트렌드 페이지 렌더링 검증

**Files:** (실행만)

- [ ] **Step 1: 트렌드 페이지 재생성**

```bash
python -c "
import json
from report_generator import generate_trend_page
with open('history/portfolio_daily.json', encoding='utf-8') as f:
    me = json.load(f)
with open('history/portfolio_daily_wife.json', encoding='utf-8') as f:
    wife = json.load(f)
out = generate_trend_page(
    portfolio_daily=me,
    output_dir='reports',
    owner_daily={'wife': wife},
)
print(f'trend page: {out}')
"
```
Expected: `reports/trend_<날짜>.html` 생성 메시지.

- [ ] **Step 2: 시각 점검**

브라우저 또는 미리보기에서 `reports/trend_<날짜>.html` 열기:
- me 탭: 자산/PnL/배당 차트가 2026-01-02부터 시작
- wife 탭: 동일 시작일, 배당 차트가 0 직선이 아닌 의미있는 값
- 합산 탭: me + wife 합계가 두 탭의 합과 일치

`TREND_START_DATE = "2026-03-05"` 필터에 걸려 1월 2일이 안 보이는 경우:

- [ ] **Step 3: TREND_START_DATE 갱신**

`report_generator.py:699`:
```python
TREND_START_DATE = "2026-01-02"  # 트렌드 차트 시작일 (이전 데이터는 표시 안 함)
```

- [ ] **Step 4: 다시 렌더링 후 확인** (Step 1 재실행)

- [ ] **Step 5: 커밋**

```bash
git add report_generator.py
git commit -m "feat(trend): extend chart start date to 2026-01-02"
```

---

## Task 11: `rebuild_trend_data.py` 위임 리팩터

**Files:**
- Modify: `rebuild_trend_data.py:240-262` (me 스냅샷)
- Modify: `rebuild_trend_data.py:266-322` (wife 스냅샷)
- Modify: `rebuild_trend_data.py:51-54` (하드코딩 상수 삭제)

- [ ] **Step 1: me 스냅샷 함수를 코어 위임으로 교체**

`rebuild_trend_data.py`의 `build_me_snapshot` 본문을 다음으로 교체 (시그니처 호환성 유지하되 내부에서 `core.build_me_snapshot` 호출):

```python
def build_me_snapshot(target_ts, me_holdings, yf_map, dfs):
    """deprecated wrapper — portfolio_history_core.build_me_snapshot로 위임."""
    import portfolio_history_core as core
    # divs_map은 build_me_snapshot 호출자(main)에서 주입해야 정확.
    # 호환성을 위해 빈 dict 사용 시 배당 0 — 호출자는 main()을 통해 fetch 후 직접 core 호출 권장.
    divs_map = getattr(build_me_snapshot, "_divs_map", {})
    return core.build_me_snapshot(target_ts, me_holdings, yf_map, dfs, divs_map)
```

- [ ] **Step 2: wife 스냅샷도 동일 위임**

```python
def build_wife_snapshot(target_ts, dfs):
    """deprecated wrapper — portfolio_history_core.build_wife_snapshot로 위임."""
    import portfolio_history_core as core
    from rebuild_wife_history import HOLDINGS as WIFE_HOLDINGS, USD_TICKERS as WIFE_USD_TICKERS
    divs_map = getattr(build_wife_snapshot, "_divs_map", {})
    yf_map = {t: core.yf_symbol(t) for t, _, _ in WIFE_HOLDINGS}
    return core.build_wife_snapshot(target_ts, WIFE_HOLDINGS, WIFE_USD_TICKERS, yf_map, dfs, divs_map)
```

- [ ] **Step 3: 하드코딩 상수 제거**

`rebuild_trend_data.py:51-55`의 `WIFE_DIV_BASE_KRW`, `WIFE_DIV_BASE_FX` 상수 삭제 또는 주석 처리:
```python
# REMOVED 2026-04-28: 하드코딩 배당 base 폐기. portfolio_history_core.compute_ttm_dividend 사용.
# WIFE_DIV_BASE_KRW = 16675519
# WIFE_DIV_BASE_FX = 1481.24
```

`rebuild_trend_data.py:243` me 배당 블록도 동일하게:
```python
# REMOVED 2026-04-28: 하드코딩 ₩42,218,109 × FX 비례 폐기. core.compute_ttm_dividend 위임.
```

- [ ] **Step 4: main() 본문에 divs_map fetch 추가 후 wrapper에 주입**

`rebuild_trend_data.py:331` (main 함수)에 추가:
```python
# 배당 시리즈 미리 fetch
import portfolio_history_core as core
all_div_tickers = (
    [p["ticker"] for p in me_holdings] +
    [t for t, _, _ in WIFE_HOLDINGS]
)
divs_map = core.fetch_all_dividends(sorted(set(all_div_tickers)))
build_me_snapshot._divs_map = divs_map
build_wife_snapshot._divs_map = divs_map
```

- [ ] **Step 5: 회귀 테스트 — 짧은 범위 실행**

```bash
python rebuild_trend_data.py
python -c "
import json
with open('history/portfolio_daily.json', encoding='utf-8') as f:
    d = json.load(f)
last = max(k for k in d if not k.startswith('_'))
# div_annual_krw 가 환율 비례 곡선이 아닌지 확인
print(f'{last}: div ₩{d[last][\"div_annual_krw\"]:,} yield {d[last][\"div_yield\"]}%')
assert d[last]['div_yield'] != 2.08, '배당수익률이 여전히 2.08% 고정'
"
```
Expected: yield가 2.08이 아니고 일별로 다양한 값.

- [ ] **Step 6: 커밋**

```bash
git add rebuild_trend_data.py
git commit -m "refactor(history): rebuild_trend_data delegates to portfolio_history_core (no more hardcoded dividends)"
```

---

## Task 12: `rebuild_wife_history.py` 배당 0 제거

**Files:**
- Modify: `rebuild_wife_history.py:160-185`

- [ ] **Step 1: 배당 계산을 코어로 위임**

`rebuild_wife_history.py`의 main 함수 내, 일별 루프에 진입하기 전 배당 시리즈 fetch:
```python
import portfolio_history_core as core
divs_map = core.fetch_all_dividends([t for t, _, _ in HOLDINGS])
```

일별 스냅샷 dict 생성 부분(L167-183) 교체:
```python
wife_daily[date_str] = {
    "total_value_krw": int(total_krw),
    "cost_basis_krw": int(cost_krw),
    "pnl_krw": int(pnl_krw),
    "pnl_pct": pnl_pct,
    "cash_value_krw": 0,
    "cash_pct": 0.0,
    # ─── 배당: TTM 기반으로 계산 (2026-04-28 하드코딩 0 제거) ───
    **_compute_wife_div_fields(pd.Timestamp(date_str), HOLDINGS, USD_TICKERS, fx, divs_map, total_krw),
    "usd_krw": round(fx, 2),
    "vix": None,
    "yield_30y": None,
    "master_switch": "UNKNOWN",
    "holdings_count": len(HOLDINGS) - len(missing_syms),
    "weights_by_category": {},
    "weights_by_ticker": weights_by_ticker,
}
```

- [ ] **Step 2: 헬퍼 함수 추가**

`rebuild_wife_history.py` 상단에:
```python
def _compute_wife_div_fields(target_ts, holdings, usd_tickers, fx, divs_map, total_krw):
    import portfolio_history_core as core
    total_div_krw = 0.0
    for ticker, shares, _ in holdings:
        if shares <= 0:
            continue
        ttm = core.compute_ttm_dividend(divs_map.get(ticker, pd.Series(dtype=float)), target_ts)
        if ttm <= 0:
            continue
        annual = ttm * shares
        total_div_krw += annual * fx if ticker in usd_tickers else annual
    return {
        "div_annual_krw": round(total_div_krw),
        "div_yield": round(total_div_krw / total_krw * 100, 2) if total_krw > 0 else 0.0,
    }
```

- [ ] **Step 3: 회귀 테스트**

```bash
python rebuild_wife_history.py
python -c "
import json
with open('history/portfolio_daily_wife.json', encoding='utf-8') as f:
    d = json.load(f)
zero = [k for k in d if not k.startswith('_') and d[k]['div_annual_krw'] == 0]
assert not zero, f'wife 배당 0 일자 잔존: {zero[:3]}'
print('OK — wife 배당 모두 > 0')
"
```
Expected: `OK — wife 배당 모두 > 0`

- [ ] **Step 4: 커밋**

```bash
git add rebuild_wife_history.py
git commit -m "fix(history): rebuild_wife_history computes TTM dividends instead of 0"
```

---

## Task 13: 회귀 — 파이프라인 전체 실행 1회 (스캐너 스킵 옵션 포함)

**Files:**
- Modify: `pipeline.py:177-256` — `SKIP_SCANNERS=1` 환경변수 가드 추가

- [ ] **Step 1: pipeline.py에 SKIP_SCANNERS 가드 추가**

`pipeline.py:177` 근처(Step 4b 시작) 직전에 분기 추가:

```python
        # Step 4b: Scanner (S&P 100 + ETF + KOSPI + Watchlist)
        skip_scanners = os.environ.get("SKIP_SCANNERS", "").lower() in ("1", "true", "yes")
        scanner_sp100_result = None
        scanner_etf_result = None
        scanner_kospi_result = None
        scanner_watchlist_result = None
        if skip_scanners:
            print("[Step 4b] SKIP_SCANNERS=1 — 스캐너 스킵 (로컬 테스트 모드)")
        else:
            # union 티커를 한 번에 수집 → scanner_shared_{date}.json 으로 공유.
            # (각 스캐너의 _fetch_scanner_data가 이 파일을 우선 활용)
            print("[Step 4b] Prefetching scanner universe (shared cache)...")
            ... (기존 prefetch + scan_sp100/etf/kospi/watchlist 블록 전체를 이 else 안으로 들여쓰기)
```

기존 라인 181~256을 `else:` 블록으로 들여쓰기. `scanner_*_result` 변수 4개의 초기화는 if-skip 분기와 else 분기 둘 다에 노출되도록 위치 조정.

- [ ] **Step 2: 가드 동작 확인 (드라이런)**

```bash
SKIP_SCANNERS=1 python -c "import os; os.environ['SKIP_SCANNERS']='1'; print(os.environ['SKIP_SCANNERS'])"
```
Expected: `1`

- [ ] **Step 3: 파이프라인 실행 (스캐너 스킵)**

```bash
SKIP_SCANNERS=1 python pipeline.py
```
(Windows PowerShell: `$env:SKIP_SCANNERS=1; python pipeline.py`)

Expected: 무오류 종료. `[Step 4b] SKIP_SCANNERS=1 — 스캐너 스킵` 메시지 출력. `portfolio_daily.json` 마지막 줄이 오늘 날짜로 갱신되되, 1월 2일~어제 데이터는 보존(`save_portfolio_snapshot`은 단일 일자만 갱신).

- [ ] **Step 4: 보존 확인**

```bash
python -c "
import json
with open('history/portfolio_daily.json', encoding='utf-8') as f:
    d = json.load(f)
ks = sorted(k for k in d if not k.startswith('_'))
print(f'me: {len(ks)}일 {ks[0]}~{ks[-1]}')
assert ks[0] == '2026-01-02', f'1월 2일 데이터 사라짐: {ks[0]}'
"
```
Expected: 1월 2일 시작일 보존.

- [ ] **Step 5: 커밋**

```bash
git add pipeline.py
git commit -m "feat(pipeline): SKIP_SCANNERS env var for fast local regression"
# data 변경(오늘 줄 추가)이 있으면 별도 커밋:
git add history/portfolio_daily.json history/portfolio_daily_wife.json
git commit -m "data: pipeline regular update"
```

---

## Task 14: 문서 업데이트

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: "진행 중인 계획" 섹션에 항목 추가**

`CLAUDE.md`의 "## 진행 중인 계획" 블록에:
```markdown
- [Portfolio history rebuild 2026-01-02~](docs/superpowers/plans/2026-04-28-portfolio-history-rebuild.md) — me/wife/합산 트렌드 1월 2일까지 확장 · TTM 배당 단일 진실의 원천(`portfolio_history_core.py`) · 하드코딩 배당(₩42M base, ₩16M base, div=0) 제거
```

- [ ] **Step 2: 핵심 파일 구조 섹션에 새 모듈 등록**

```markdown
├── portfolio_history_core.py       # 히스토리 재계산 코어 (다운로드+TTM 배당+스냅샷)
├── rebuild_portfolio_history.py    # me+wife daily 일괄 재생성 (2026-01-02~)
```

- [ ] **Step 3: 커밋**

```bash
git add CLAUDE.md
git commit -m "docs: register portfolio history rebuild plan"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** me/wife/합산 모두 → me는 Task 4, wife는 Task 5, 합산은 Task 10(`_build_combined_payload` 자동). 1월 2일 시작일 → Task 9 + 10. 트렌드 차트 표시 → Task 10.
- [x] **하드코딩 제거:** Task 11 (rebuild_trend_data), Task 12 (rebuild_wife_history) 양쪽 다룸.
- [x] **Placeholder 없음:** 모든 코드 블록 완전. 테스트 코드 동봉. 명령어 expected 표기.
- [x] **타입 일관성:** `holdings = list[dict{ticker, shares, avg_cost}]` (me) vs `wife_holdings = list[tuple[ticker, shares, avg_cost_krw]]` (wife) — 의도적 분리, 각 빌더 독립 시그니처.
- [x] **외부 시그니처 호환:** `save_portfolio_snapshot` 인자 변경 없음 → pipeline.py 수정 불필요.
- [x] **TREND_START_DATE 차트 필터:** Task 10 Step 3에서 명시적으로 `2026-01-02`로 갱신.
- [x] **백업 안전성:** Task 9가 본 실행 전 자동 백업 생성.
- [x] **합산 탭:** 별도 파일 없음 — `_build_combined_payload`가 me+wife daily로 즉석 합산. me/wife 양쪽이 동일 날짜 범위로 갱신되므로 자동 정합.

---

## Risks & Mitigations

| 리스크 | 완화 |
|---|---|
| Yahoo rate limit으로 1년치 다운로드 실패 | `download_all`이 0.7s 간격 + 지수 백오프 3회. 실패 심볼은 SKIP되고 main이 SPY 누락 시 abort. |
| 1년 이전 배당 데이터 누락(yfinance 한계) | 분기 4회 배당이 1년 안에 모두 들어와야 정확 — 1월 2일은 이미 365일 후 → OK. 단 신규 상장 종목(<1년)은 자동으로 부분 TTM. |
| ex-div 통과로 인한 배당 단계 점프 | 회계상 정확. 시각적 부드러움이 필요하면 별도 PR(forward annualized = 직전 분기 × 4)로 분리. |
| wife HOLDINGS와 portfolios/wife.md 불일치 | 본 계획은 `rebuild_wife_history.HOLDINGS`를 단일 진실로 사용. wife.md 파싱 통합은 별도 작업. |
| 기존 백업 파일이 `.gitignore`에 없으면 추적됨 | `.gitignore`에 `history/*.bak.*` 추가는 별도 PR. 본 계획은 백업 자체만 보장. |

---

## Execution Handoff

Plan complete. 다음 실행 옵션:

1. **Subagent-Driven (권장)** — Task별 fresh subagent + review checkpoint
2. **Inline Execution** — 현재 세션에서 batch 실행

선택해주세요.
