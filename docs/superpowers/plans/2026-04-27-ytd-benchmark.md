# YTD Benchmark vs S&P (KRW) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display "2026 YTD return / S&P(KRW) YTD / alpha" on My-Portfolio and Wife-Portfolio main report headers and trend page (with a normalized comparison chart), based on a constant-portfolio backtest anchored at 2026-01-02.

**Architecture:** New module `benchmark_ytd.py` computes per-owner v0 (current holdings × Jan 2 prices, KRW) and v_now (current holdings × today prices, KRW), returning `(ytd_pct, spy_ytd_pct, alpha_pp)`. Cache `data/baseline_2026_{owner}.json` stores Jan 2 prices once (incrementally appended when holdings change). Pipeline computes per-owner benchmark before report generation, passes results into templates and into `portfolio_daily.json` for time-series charting.

**Tech Stack:** Python 3.10+, yfinance, pytest, Jinja2, Chart.js (frontend), Tailwind CSS.

**Spec:** [docs/superpowers/specs/2026-04-27-ytd-benchmark-design.md](../specs/2026-04-27-ytd-benchmark-design.md)

---

## File Structure

**Create:**
- `benchmark_ytd.py` — core module (ticker resolution, fetch helpers, baseline cache, v0/v_now/returns computation)
- `tests/test_benchmark_ytd.py` — unit tests with mocked yfinance
- `tests/test_benchmark_pipeline_integration.py` — integration: pipeline writes ytd fields into portfolio_daily

**Modify:**
- `pipeline.py:303-319` and `pipeline.py:544+` — compute benchmark per owner before each `generate_report` call
- `pipeline.py:494-510` — extend `save_portfolio_snapshot` call sites with new ytd fields
- `history_manager.py:194-239` — add optional `ytd_pct`, `spy_ytd_pct`, `alpha_pp`, `v0_krw`, `spy_v0_krw` kwargs to `save_portfolio_snapshot`
- `report_generator.py:280-440` — accept `benchmark_data` arg in `generate_report`, inject into template context
- `report_generator.py:712-844` — extend `generate_trend_page` and `_series_from_daily` to include ytd time series
- `templates/report_template.html:266-282` — add YTD/S&P/α line below "vs Principal"
- `templates/trend_template.html:84-118` — add 3-card YTD summary block + new normalized comparison chart canvas + JS

**Auto-generated (not committed initially):**
- `data/baseline_2026_me.json`
- `data/baseline_2026_wife.json`

---

## Task 1: Create `benchmark_ytd.py` skeleton with constants

**Files:**
- Create: `benchmark_ytd.py`
- Test: `tests/test_benchmark_ytd.py`

- [ ] **Step 1: Create skeleton module**

```python
# benchmark_ytd.py
"""YTD benchmark vs S&P 500 (KRW) — constant-portfolio backtest anchored at 2026-01-02.

See docs/superpowers/specs/2026-04-27-ytd-benchmark-design.md for design.
"""
from __future__ import annotations

import json
import os
from typing import Iterable

ANCHOR_DATE = "2026-01-02"
SPY_SYMBOL = "SPY"
USDKRW_SYMBOL = "KRW=X"
```

- [ ] **Step 2: Create test file with import sanity check**

```python
# tests/test_benchmark_ytd.py
"""Tests for benchmark_ytd module."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import benchmark_ytd


def test_constants_defined():
    assert benchmark_ytd.ANCHOR_DATE == "2026-01-02"
    assert benchmark_ytd.SPY_SYMBOL == "SPY"
    assert benchmark_ytd.USDKRW_SYMBOL == "KRW=X"
```

- [ ] **Step 3: Run test**

Run: `python -m pytest tests/test_benchmark_ytd.py -v`
Expected: PASS (1 test)

- [ ] **Step 4: Commit**

```bash
git add benchmark_ytd.py tests/test_benchmark_ytd.py
git commit -m "feat(benchmark): module skeleton + anchor date constants"
```

---

## Task 2: Ticker → yfinance symbol resolution helper

**Files:**
- Modify: `benchmark_ytd.py`
- Test: `tests/test_benchmark_ytd.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_benchmark_ytd.py`:

```python
from benchmark_ytd import resolve_yf_symbol


def test_resolve_us_ticker():
    assert resolve_yf_symbol("AAPL") == "AAPL"
    assert resolve_yf_symbol("SPY") == "SPY"


def test_resolve_kospi_ticker():
    # 005930 = 삼성전자, KOSPI
    assert resolve_yf_symbol("005930") == "005930.KS"


def test_resolve_kosdaq_ticker():
    # 110990 = 디아이티, KOSDAQ
    assert resolve_yf_symbol("110990") == "110990.KQ"


def test_resolve_ticker_with_existing_suffix():
    # already converted — pass through unchanged
    assert resolve_yf_symbol("005930.KS") == "005930.KS"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_benchmark_ytd.py::test_resolve_us_ticker -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_yf_symbol'`

- [ ] **Step 3: Implement helper**

Add to `benchmark_ytd.py`:

```python
from portfolio_data import to_yfinance_symbol, is_korean_ticker


def resolve_yf_symbol(ticker: str) -> str:
    """Convert portfolio ticker to yfinance symbol.

    - US tickers (AAPL, SPY): unchanged
    - KOSPI 6-digit codes (005930): append .KS
    - KOSDAQ codes (110990): append .KQ
    - Already-suffixed (.KS/.KQ): pass through
    """
    if ticker.endswith(".KS") or ticker.endswith(".KQ"):
        return ticker
    return to_yfinance_symbol(ticker)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/test_benchmark_ytd.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add benchmark_ytd.py tests/test_benchmark_ytd.py
git commit -m "feat(benchmark): ticker → yfinance symbol resolver"
```

---

## Task 3: yfinance close-price fetcher (mocked in tests)

**Files:**
- Modify: `benchmark_ytd.py`
- Test: `tests/test_benchmark_ytd.py`

- [ ] **Step 1: Write failing tests with mocked yfinance**

Add to `tests/test_benchmark_ytd.py`:

```python
from unittest.mock import patch, MagicMock
import pandas as pd


def _mock_yf_history(close_value: float):
    """Build a mock yfinance.Ticker whose .history() returns one row with given close."""
    df = pd.DataFrame(
        {"Close": [close_value], "Adj Close": [close_value]},
        index=pd.to_datetime(["2026-01-02"]),
    )
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = df
    return mock_ticker


def test_fetch_close_on_returns_value():
    from benchmark_ytd import fetch_close_on
    with patch("benchmark_ytd.yf.Ticker", return_value=_mock_yf_history(150.25)):
        assert fetch_close_on("AAPL", "2026-01-02") == 150.25


def test_fetch_close_on_empty_returns_none():
    from benchmark_ytd import fetch_close_on
    empty_df = pd.DataFrame()
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = empty_df
    with patch("benchmark_ytd.yf.Ticker", return_value=mock_ticker):
        assert fetch_close_on("UNKNOWN.XX", "2026-01-02") is None


def test_fetch_close_on_uses_adj_close_for_spy():
    """SPY uses Adj Close (dividend-adjusted) for accurate benchmark return."""
    from benchmark_ytd import fetch_close_on
    df = pd.DataFrame(
        {"Close": [470.0], "Adj Close": [468.5]},
        index=pd.to_datetime(["2026-01-02"]),
    )
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = df
    with patch("benchmark_ytd.yf.Ticker", return_value=mock_ticker):
        # SPY → Adj Close
        assert fetch_close_on("SPY", "2026-01-02", use_adj_close=True) == 468.5
        # AAPL → Close
        assert fetch_close_on("AAPL", "2026-01-02", use_adj_close=False) == 470.0
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_benchmark_ytd.py::test_fetch_close_on_returns_value -v`
Expected: FAIL with import error.

- [ ] **Step 3: Implement fetcher**

Add to `benchmark_ytd.py`:

```python
import yfinance as yf
from datetime import datetime, timedelta


def fetch_close_on(yf_symbol: str, date_str: str, use_adj_close: bool = False) -> float | None:
    """Fetch close price for a yfinance symbol on/after the given date.

    Returns None when no data available (unmappable ticker, IPO not yet listed, etc.).
    The window extends 7 days to handle weekends and holidays.
    """
    start = date_str
    end = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=7)).strftime("%Y-%m-%d")
    try:
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(start=start, end=end, auto_adjust=False)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    col = "Adj Close" if use_adj_close and "Adj Close" in df.columns else "Close"
    if col not in df.columns:
        return None
    val = df[col].iloc[0]
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_benchmark_ytd.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add benchmark_ytd.py tests/test_benchmark_ytd.py
git commit -m "feat(benchmark): yfinance close-price fetcher with date window"
```

---

## Task 4: Build full Jan-2 baseline for a holdings list

**Files:**
- Modify: `benchmark_ytd.py`
- Test: `tests/test_benchmark_ytd.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_benchmark_ytd.py`:

```python
def test_build_baseline_us_only():
    """Pure US holdings → baseline has ticker_v0_krw + usd_krw + spy_close_usd."""
    from benchmark_ytd import build_baseline
    holdings = [
        {"ticker": "AAPL", "shares": 10},
        {"ticker": "SPY", "shares": 5},
    ]
    fake_prices = {"AAPL": 150.0, "SPY": 470.0}
    fake_usdkrw = 1300.0
    fake_spy_adj = 468.0

    def fake_fetch(symbol, date_str, use_adj_close=False):
        if symbol == "KRW=X":
            return fake_usdkrw
        if symbol == "SPY" and use_adj_close:
            return fake_spy_adj
        return fake_prices.get(symbol)

    with patch("benchmark_ytd.fetch_close_on", side_effect=fake_fetch):
        baseline = build_baseline(holdings)

    assert baseline["anchor_date"] == "2026-01-02"
    assert baseline["usd_krw"] == 1300.0
    assert baseline["spy_close_usd"] == 468.0
    # AAPL: 150 * 1300 = 195000 KRW per share
    assert baseline["ticker_v0_krw"]["AAPL"] == 150.0 * 1300.0
    assert baseline["ticker_v0_krw"]["SPY"] == 470.0 * 1300.0
    assert baseline["unmappable"] == []


def test_build_baseline_mixed_us_and_kr():
    """KOSPI ticker uses native KRW; US uses USD * USD/KRW."""
    from benchmark_ytd import build_baseline
    holdings = [
        {"ticker": "AAPL", "shares": 10},
        {"ticker": "005930", "shares": 100},  # 삼성전자 KOSPI
    ]
    fake_data = {
        "AAPL": 150.0,
        "005930.KS": 80000.0,
        "KRW=X": 1300.0,
        "SPY": 470.0,  # Adj
    }

    def fake_fetch(symbol, date_str, use_adj_close=False):
        return fake_data.get(symbol)

    with patch("benchmark_ytd.fetch_close_on", side_effect=fake_fetch):
        baseline = build_baseline(holdings)

    assert baseline["ticker_v0_krw"]["AAPL"] == 150.0 * 1300.0
    # KOSPI: native KRW, no FX
    assert baseline["ticker_v0_krw"]["005930"] == 80000.0


def test_build_baseline_unmappable_ticker_recorded():
    """Ticker with no Jan 2 data → goes to unmappable list, NOT in ticker_v0_krw."""
    from benchmark_ytd import build_baseline
    holdings = [
        {"ticker": "AAPL", "shares": 10},
        {"ticker": "WEIRD", "shares": 5},
    ]

    def fake_fetch(symbol, date_str, use_adj_close=False):
        if symbol == "WEIRD":
            return None
        return {"AAPL": 150.0, "KRW=X": 1300.0, "SPY": 470.0}.get(symbol)

    with patch("benchmark_ytd.fetch_close_on", side_effect=fake_fetch):
        baseline = build_baseline(holdings)

    assert "AAPL" in baseline["ticker_v0_krw"]
    assert "WEIRD" not in baseline["ticker_v0_krw"]
    assert "WEIRD" in baseline["unmappable"]


def test_build_baseline_failure_on_missing_usdkrw():
    """USD/KRW fetch failure → raises RuntimeError (silent fallback forbidden)."""
    from benchmark_ytd import build_baseline
    holdings = [{"ticker": "AAPL", "shares": 10}]

    def fake_fetch(symbol, date_str, use_adj_close=False):
        if symbol == "KRW=X":
            return None
        return 150.0

    with patch("benchmark_ytd.fetch_close_on", side_effect=fake_fetch):
        import pytest
        with pytest.raises(RuntimeError, match="USD/KRW"):
            build_baseline(holdings)


def test_build_baseline_failure_on_missing_spy():
    """SPY fetch failure → raises RuntimeError."""
    from benchmark_ytd import build_baseline
    holdings = [{"ticker": "AAPL", "shares": 10}]

    def fake_fetch(symbol, date_str, use_adj_close=False):
        if symbol == "SPY":
            return None
        if symbol == "KRW=X":
            return 1300.0
        return 150.0

    with patch("benchmark_ytd.fetch_close_on", side_effect=fake_fetch):
        import pytest
        with pytest.raises(RuntimeError, match="SPY"):
            build_baseline(holdings)
```

- [ ] **Step 2: Implement `build_baseline`**

Add to `benchmark_ytd.py`:

```python
def build_baseline(holdings: list[dict]) -> dict:
    """Build a fresh Jan-2 baseline from a holdings list.

    Returns:
        {
          "anchor_date": "2026-01-02",
          "usd_krw": <float>,
          "spy_close_usd": <float>,
          "ticker_v0_krw": {ticker: jan2_price_in_krw_per_share, ...},
          "unmappable": [ticker, ...]
        }

    Raises:
        RuntimeError: if USD/KRW or SPY fetch fails (no silent fallback).
    """
    usd_krw = fetch_close_on(USDKRW_SYMBOL, ANCHOR_DATE)
    if usd_krw is None or usd_krw <= 0:
        raise RuntimeError(f"Failed to fetch USD/KRW on {ANCHOR_DATE}")

    spy_usd = fetch_close_on(SPY_SYMBOL, ANCHOR_DATE, use_adj_close=True)
    if spy_usd is None or spy_usd <= 0:
        raise RuntimeError(f"Failed to fetch SPY on {ANCHOR_DATE}")

    ticker_v0_krw: dict[str, float] = {}
    unmappable: list[str] = []
    for h in holdings:
        ticker = h["ticker"]
        yf_sym = resolve_yf_symbol(ticker)
        price = fetch_close_on(yf_sym, ANCHOR_DATE)
        if price is None or price <= 0:
            unmappable.append(ticker)
            continue
        if is_korean_ticker(ticker):
            ticker_v0_krw[ticker] = float(price)
        else:
            ticker_v0_krw[ticker] = float(price) * usd_krw

    return {
        "anchor_date": ANCHOR_DATE,
        "usd_krw": float(usd_krw),
        "spy_close_usd": float(spy_usd),
        "ticker_v0_krw": ticker_v0_krw,
        "unmappable": unmappable,
    }
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_benchmark_ytd.py -v`
Expected: PASS (13 tests)

- [ ] **Step 4: Commit**

```bash
git add benchmark_ytd.py tests/test_benchmark_ytd.py
git commit -m "feat(benchmark): build_baseline aggregator for Jan 2 prices"
```

---

## Task 5: Cache I/O — load_or_build_baseline (with incremental ticker append)

**Files:**
- Modify: `benchmark_ytd.py`
- Test: `tests/test_benchmark_ytd.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_benchmark_ytd.py`:

```python
import tempfile
import json as _json


def test_load_or_build_creates_cache_when_missing(tmp_path):
    from benchmark_ytd import load_or_build_baseline
    holdings = [{"ticker": "AAPL", "shares": 10}]
    fake_data = {"AAPL": 150.0, "KRW=X": 1300.0, "SPY": 470.0}

    with patch("benchmark_ytd.fetch_close_on", side_effect=lambda s, d, use_adj_close=False: fake_data.get(s)):
        baseline = load_or_build_baseline(holdings, owner="me", project_dir=str(tmp_path))

    cache_path = tmp_path / "data" / "baseline_2026_me.json"
    assert cache_path.exists()
    saved = _json.loads(cache_path.read_text(encoding="utf-8"))
    assert saved["ticker_v0_krw"]["AAPL"] == 150.0 * 1300.0
    assert baseline == saved


def test_load_or_build_reads_existing_cache_no_fetch(tmp_path):
    """Existing cache + same holdings → no fetch_close_on calls."""
    from benchmark_ytd import load_or_build_baseline
    cache_dir = tmp_path / "data"
    cache_dir.mkdir()
    cached = {
        "anchor_date": "2026-01-02",
        "usd_krw": 1300.0,
        "spy_close_usd": 468.0,
        "ticker_v0_krw": {"AAPL": 195000.0},
        "unmappable": [],
    }
    (cache_dir / "baseline_2026_me.json").write_text(_json.dumps(cached), encoding="utf-8")
    holdings = [{"ticker": "AAPL", "shares": 10}]

    fetch_mock = MagicMock()
    with patch("benchmark_ytd.fetch_close_on", fetch_mock):
        baseline = load_or_build_baseline(holdings, owner="me", project_dir=str(tmp_path))

    assert baseline == cached
    fetch_mock.assert_not_called()


def test_load_or_build_appends_only_new_tickers(tmp_path):
    """Adding a new ticker → only the new ticker is fetched, cache updated."""
    from benchmark_ytd import load_or_build_baseline
    cache_dir = tmp_path / "data"
    cache_dir.mkdir()
    cached = {
        "anchor_date": "2026-01-02",
        "usd_krw": 1300.0,
        "spy_close_usd": 468.0,
        "ticker_v0_krw": {"AAPL": 195000.0},
        "unmappable": [],
    }
    (cache_dir / "baseline_2026_me.json").write_text(_json.dumps(cached), encoding="utf-8")
    holdings = [
        {"ticker": "AAPL", "shares": 10},  # cached
        {"ticker": "TSLA", "shares": 5},   # new
    ]
    calls = []

    def tracked_fetch(symbol, date_str, use_adj_close=False):
        calls.append(symbol)
        return {"TSLA": 200.0}.get(symbol)

    with patch("benchmark_ytd.fetch_close_on", side_effect=tracked_fetch):
        baseline = load_or_build_baseline(holdings, owner="me", project_dir=str(tmp_path))

    # Only TSLA should be fetched (USD/KRW + SPY come from cache)
    assert calls == ["TSLA"]
    assert baseline["ticker_v0_krw"]["AAPL"] == 195000.0  # preserved
    assert baseline["ticker_v0_krw"]["TSLA"] == 200.0 * 1300.0  # new


def test_load_or_build_skips_unmappable_already_recorded(tmp_path):
    """Tickers in cached unmappable list → not retried."""
    from benchmark_ytd import load_or_build_baseline
    cache_dir = tmp_path / "data"
    cache_dir.mkdir()
    cached = {
        "anchor_date": "2026-01-02",
        "usd_krw": 1300.0,
        "spy_close_usd": 468.0,
        "ticker_v0_krw": {"AAPL": 195000.0},
        "unmappable": ["WEIRD"],
    }
    (cache_dir / "baseline_2026_me.json").write_text(_json.dumps(cached), encoding="utf-8")
    holdings = [
        {"ticker": "AAPL", "shares": 10},
        {"ticker": "WEIRD", "shares": 5},  # already unmappable
    ]

    fetch_mock = MagicMock()
    with patch("benchmark_ytd.fetch_close_on", fetch_mock):
        baseline = load_or_build_baseline(holdings, owner="me", project_dir=str(tmp_path))

    fetch_mock.assert_not_called()
    assert "WEIRD" in baseline["unmappable"]
```

- [ ] **Step 2: Implement `load_or_build_baseline`**

Add to `benchmark_ytd.py`:

```python
def _baseline_cache_path(owner: str, project_dir: str) -> str:
    return os.path.join(project_dir, "data", f"baseline_2026_{owner}.json")


def load_or_build_baseline(holdings: list[dict], owner: str, project_dir: str) -> dict:
    """Load cached baseline or build it. Incrementally appends new tickers.

    - First run (no cache): full build via build_baseline().
    - Subsequent runs: read cache. For tickers not in ticker_v0_krw and not in unmappable,
      fetch their Jan-2 price using cached USD/KRW and append.
    """
    path = _baseline_cache_path(owner, project_dir)
    if not os.path.exists(path):
        baseline = build_baseline(holdings)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(baseline, f, ensure_ascii=False, indent=2)
        return baseline

    with open(path, "r", encoding="utf-8") as f:
        baseline = json.load(f)

    cached_tickers = set(baseline["ticker_v0_krw"].keys()) | set(baseline.get("unmappable", []))
    new_tickers = [h["ticker"] for h in holdings if h["ticker"] not in cached_tickers]

    if not new_tickers:
        return baseline

    usd_krw = baseline["usd_krw"]
    changed = False
    for ticker in new_tickers:
        yf_sym = resolve_yf_symbol(ticker)
        price = fetch_close_on(yf_sym, ANCHOR_DATE)
        if price is None or price <= 0:
            baseline.setdefault("unmappable", []).append(ticker)
        elif is_korean_ticker(ticker):
            baseline["ticker_v0_krw"][ticker] = float(price)
        else:
            baseline["ticker_v0_krw"][ticker] = float(price) * usd_krw
        changed = True

    if changed:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(baseline, f, ensure_ascii=False, indent=2)
    return baseline
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_benchmark_ytd.py -v`
Expected: PASS (17 tests)

- [ ] **Step 4: Commit**

```bash
git add benchmark_ytd.py tests/test_benchmark_ytd.py
git commit -m "feat(benchmark): load_or_build_baseline with incremental cache"
```

---

## Task 6: compute_v0_total_krw + compute_v_now_total_krw

**Files:**
- Modify: `benchmark_ytd.py`
- Test: `tests/test_benchmark_ytd.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_benchmark_ytd.py`:

```python
def test_compute_v0_total_krw_basic():
    from benchmark_ytd import compute_v0_total_krw
    holdings = [
        {"ticker": "AAPL", "shares": 10},
        {"ticker": "005930", "shares": 100},
    ]
    baseline = {
        "ticker_v0_krw": {"AAPL": 195000.0, "005930": 80000.0},
        "unmappable": [],
    }
    # 10 * 195000 + 100 * 80000 = 1950000 + 8000000 = 9950000
    v0, excluded = compute_v0_total_krw(holdings, baseline)
    assert v0 == 9_950_000.0
    assert excluded == []


def test_compute_v0_skips_unmappable():
    from benchmark_ytd import compute_v0_total_krw
    holdings = [
        {"ticker": "AAPL", "shares": 10},
        {"ticker": "WEIRD", "shares": 5},
    ]
    baseline = {
        "ticker_v0_krw": {"AAPL": 195000.0},
        "unmappable": ["WEIRD"],
    }
    v0, excluded = compute_v0_total_krw(holdings, baseline)
    assert v0 == 1_950_000.0
    assert excluded == ["WEIRD"]


def test_compute_v_now_total_krw_us_uses_today_fx():
    from benchmark_ytd import compute_v_now_total_krw
    holdings = [
        {"ticker": "AAPL", "shares": 10},
        {"ticker": "005930", "shares": 100},
    ]
    baseline = {"ticker_v0_krw": {"AAPL": 195000.0, "005930": 80000.0}, "unmappable": []}
    today_prices = {"AAPL": 180.0, "005930": 90000.0}  # AAPL=USD, 005930=KRW (KOSPI)
    today_usd_krw = 1400.0
    # AAPL: 10 * 180 * 1400 = 2520000
    # 005930: 100 * 90000 = 9000000
    # total = 11520000
    v_now, excluded = compute_v_now_total_krw(holdings, today_prices, today_usd_krw, baseline)
    assert v_now == 11_520_000.0
    assert excluded == []


def test_compute_v_now_skips_same_unmappable_set_as_v0():
    """v_now must exclude the same tickers as v0 to keep numerator/denominator consistent."""
    from benchmark_ytd import compute_v_now_total_krw
    holdings = [
        {"ticker": "AAPL", "shares": 10},
        {"ticker": "WEIRD", "shares": 5},
    ]
    baseline = {"ticker_v0_krw": {"AAPL": 195000.0}, "unmappable": ["WEIRD"]}
    today_prices = {"AAPL": 180.0, "WEIRD": 100.0}
    v_now, excluded = compute_v_now_total_krw(holdings, today_prices, 1400.0, baseline)
    # WEIRD excluded
    assert v_now == 10 * 180.0 * 1400.0
    assert excluded == ["WEIRD"]


def test_compute_v_now_missing_today_price_excluded():
    """If today_prices lacks a ticker → exclude from BOTH v0 and v_now (handled in caller)."""
    from benchmark_ytd import compute_v_now_total_krw
    holdings = [
        {"ticker": "AAPL", "shares": 10},
        {"ticker": "TSLA", "shares": 5},
    ]
    baseline = {
        "ticker_v0_krw": {"AAPL": 195000.0, "TSLA": 260000.0},
        "unmappable": [],
    }
    today_prices = {"AAPL": 180.0}  # TSLA missing
    v_now, excluded = compute_v_now_total_krw(holdings, today_prices, 1400.0, baseline)
    assert v_now == 10 * 180.0 * 1400.0
    assert "TSLA" in excluded
```

- [ ] **Step 2: Implement v0/v_now**

Add to `benchmark_ytd.py`:

```python
def compute_v0_total_krw(holdings: list[dict], baseline: dict) -> tuple[float, list[str]]:
    """Sum (shares × baseline ticker_v0_krw) over mappable holdings.

    Returns (v0_total_krw, excluded_tickers).
    """
    ticker_v0 = baseline["ticker_v0_krw"]
    unmappable = set(baseline.get("unmappable", []))
    total = 0.0
    excluded: list[str] = []
    for h in holdings:
        t = h["ticker"]
        if t in unmappable or t not in ticker_v0:
            excluded.append(t)
            continue
        total += float(h["shares"]) * float(ticker_v0[t])
    return total, excluded


def compute_v_now_total_krw(
    holdings: list[dict],
    today_prices: dict,
    today_usd_krw: float,
    baseline: dict,
) -> tuple[float, list[str]]:
    """Sum (shares × today_price_in_krw) over the SAME mappable set as v0.

    today_prices: {ticker: today_native_price} (USD for US, KRW for KOSPI/KOSDAQ).
    Excludes tickers that are unmappable in baseline OR missing in today_prices.

    Returns (v_now_total_krw, excluded_tickers).
    """
    unmappable = set(baseline.get("unmappable", []))
    ticker_v0 = baseline["ticker_v0_krw"]
    total = 0.0
    excluded: list[str] = []
    for h in holdings:
        t = h["ticker"]
        if t in unmappable or t not in ticker_v0:
            excluded.append(t)
            continue
        price = today_prices.get(t)
        if price is None or price <= 0:
            excluded.append(t)
            continue
        if is_korean_ticker(t):
            total += float(h["shares"]) * float(price)
        else:
            total += float(h["shares"]) * float(price) * float(today_usd_krw)
    return total, excluded
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_benchmark_ytd.py -v`
Expected: PASS (22 tests)

- [ ] **Step 4: Commit**

```bash
git add benchmark_ytd.py tests/test_benchmark_ytd.py
git commit -m "feat(benchmark): compute_v0_total_krw + compute_v_now_total_krw"
```

---

## Task 7: compute_returns (full benchmark calc with SPY today fetch)

**Files:**
- Modify: `benchmark_ytd.py`
- Test: `tests/test_benchmark_ytd.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_benchmark_ytd.py`:

```python
def test_compute_returns_positive_alpha():
    """Portfolio +5%, S&P (KRW) +3% → alpha = +2.0pp."""
    from benchmark_ytd import compute_returns
    holdings = [{"ticker": "AAPL", "shares": 10}]
    baseline = {
        "anchor_date": "2026-01-02",
        "usd_krw": 1300.0,
        "spy_close_usd": 468.0,
        "ticker_v0_krw": {"AAPL": 195000.0},
        "unmappable": [],
    }
    today_prices = {"AAPL": 157.5}  # +5% of 150
    today_usd_krw = 1300.0  # FX flat
    today_spy_usd = 482.04  # +3% of 468

    result = compute_returns(holdings, today_prices, today_usd_krw, today_spy_usd, baseline)

    assert result["v0_krw"] == 1_950_000.0
    # 10 * 157.5 * 1300 = 2047500
    assert result["v_now_krw"] == 2_047_500.0
    assert round(result["ytd_pct"], 2) == 5.0
    # SPY KRW: v0 = 468 * 1300 = 608400; v_now = 482.04 * 1300 = 626652
    # spy_ytd_pct = (626652/608400 - 1)*100 = 3.0
    assert round(result["spy_ytd_pct"], 2) == 3.0
    assert round(result["alpha_pp"], 2) == 2.0
    assert result["excluded_tickers"] == []


def test_compute_returns_negative_alpha():
    from benchmark_ytd import compute_returns
    holdings = [{"ticker": "AAPL", "shares": 10}]
    baseline = {
        "usd_krw": 1300.0, "spy_close_usd": 468.0,
        "ticker_v0_krw": {"AAPL": 195000.0}, "unmappable": [],
    }
    today_prices = {"AAPL": 147.0}  # -2%
    result = compute_returns(holdings, today_prices, 1300.0, 472.68, baseline)  # SPY +1%
    assert round(result["ytd_pct"], 2) == -2.0
    assert round(result["spy_ytd_pct"], 2) == 1.0
    assert round(result["alpha_pp"], 2) == -3.0


def test_compute_returns_zero_v0_returns_none_pct():
    """All holdings unmappable → v0 = 0 → ytd_pct = None (avoid divide-by-zero)."""
    from benchmark_ytd import compute_returns
    holdings = [{"ticker": "WEIRD", "shares": 10}]
    baseline = {
        "usd_krw": 1300.0, "spy_close_usd": 468.0,
        "ticker_v0_krw": {}, "unmappable": ["WEIRD"],
    }
    result = compute_returns(holdings, {"WEIRD": 100.0}, 1300.0, 482.0, baseline)
    assert result["ytd_pct"] is None
    assert result["alpha_pp"] is None
    # SPY independent → still computed
    assert result["spy_ytd_pct"] is not None


def test_compute_returns_fx_movement_in_spy_krw():
    """SPY KRW return reflects USD/KRW movement, not just SPY USD."""
    from benchmark_ytd import compute_returns
    holdings = [{"ticker": "AAPL", "shares": 10}]
    baseline = {
        "usd_krw": 1000.0, "spy_close_usd": 400.0,
        "ticker_v0_krw": {"AAPL": 150_000.0}, "unmappable": [],
    }
    # SPY USD flat at 400, but FX moved 1000 → 1100 (+10%)
    result = compute_returns(holdings, {"AAPL": 150.0}, 1100.0, 400.0, baseline)
    # SPY KRW: 400*1000=400000 → 400*1100=440000 → +10%
    assert round(result["spy_ytd_pct"], 2) == 10.0
```

- [ ] **Step 2: Implement compute_returns**

Add to `benchmark_ytd.py`:

```python
def compute_returns(
    holdings: list[dict],
    today_prices: dict,
    today_usd_krw: float,
    today_spy_usd: float,
    baseline: dict,
) -> dict:
    """Compute YTD portfolio return, SPY (KRW) return, and alpha.

    Returns:
        {
          "v0_krw": float, "v_now_krw": float,
          "ytd_pct": float | None,
          "spy_v0_krw": float, "spy_now_krw": float,
          "spy_ytd_pct": float | None,
          "alpha_pp": float | None,
          "excluded_tickers": [ticker, ...],
        }

    ytd_pct/alpha_pp are None when v0 == 0 (all holdings unmappable).
    """
    v0_krw, exc1 = compute_v0_total_krw(holdings, baseline)
    v_now_krw, exc2 = compute_v_now_total_krw(holdings, today_prices, today_usd_krw, baseline)
    excluded = sorted(set(exc1) | set(exc2))

    ytd_pct: float | None
    if v0_krw > 0:
        ytd_pct = (v_now_krw / v0_krw - 1.0) * 100.0
    else:
        ytd_pct = None

    spy_v0_krw = float(baseline["spy_close_usd"]) * float(baseline["usd_krw"])
    spy_now_krw = float(today_spy_usd) * float(today_usd_krw)
    spy_ytd_pct: float | None
    if spy_v0_krw > 0:
        spy_ytd_pct = (spy_now_krw / spy_v0_krw - 1.0) * 100.0
    else:
        spy_ytd_pct = None

    alpha_pp: float | None
    if ytd_pct is not None and spy_ytd_pct is not None:
        alpha_pp = ytd_pct - spy_ytd_pct
    else:
        alpha_pp = None

    return {
        "v0_krw": v0_krw,
        "v_now_krw": v_now_krw,
        "ytd_pct": ytd_pct,
        "spy_v0_krw": spy_v0_krw,
        "spy_now_krw": spy_now_krw,
        "spy_ytd_pct": spy_ytd_pct,
        "alpha_pp": alpha_pp,
        "excluded_tickers": excluded,
    }
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_benchmark_ytd.py -v`
Expected: PASS (26 tests)

- [ ] **Step 4: Commit**

```bash
git add benchmark_ytd.py tests/test_benchmark_ytd.py
git commit -m "feat(benchmark): compute_returns with alpha + zero-v0 handling"
```

---

## Task 8: Top-level helper that wires it all together

**Files:**
- Modify: `benchmark_ytd.py`
- Test: `tests/test_benchmark_ytd.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_benchmark_ytd.py`:

```python
def test_compute_owner_benchmark_end_to_end(tmp_path):
    """Top-level entry point: takes holdings + market_data, returns full result dict.

    Builds baseline from scratch on first call, fetches today's SPY separately.
    """
    from benchmark_ytd import compute_owner_benchmark

    holdings = [{"ticker": "AAPL", "shares": 10}]
    market_data = {
        "data": {"AAPL": {"price": 157.5}},
        "_macro": {"USD_KRW": 1300.0},
    }
    fake_data = {
        "AAPL": 150.0,
        "KRW=X": 1300.0,
        "SPY": 482.04,  # used for both Jan2 (Adj) and today
    }

    def fake_fetch(symbol, date_str, use_adj_close=False):
        # First call (Jan 2 baseline): SPY adj 468; today SPY: 482.04
        if symbol == "SPY":
            return 468.0 if date_str == "2026-01-02" else 482.04
        return fake_data.get(symbol)

    with patch("benchmark_ytd.fetch_close_on", side_effect=fake_fetch):
        result = compute_owner_benchmark(
            holdings=holdings,
            owner="me",
            project_dir=str(tmp_path),
            market_data=market_data,
        )

    assert result["status"] == "ok"
    assert round(result["ytd_pct"], 2) == 5.0
    assert round(result["spy_ytd_pct"], 2) == 3.0
    assert round(result["alpha_pp"], 2) == 2.0


def test_compute_owner_benchmark_handles_failure_gracefully(tmp_path):
    """If baseline build fails, return status=error placeholder, do not raise."""
    from benchmark_ytd import compute_owner_benchmark

    holdings = [{"ticker": "AAPL", "shares": 10}]
    market_data = {"data": {"AAPL": {"price": 150.0}}, "_macro": {"USD_KRW": 1300.0}}

    def fake_fetch(symbol, date_str, use_adj_close=False):
        return None  # everything fails

    with patch("benchmark_ytd.fetch_close_on", side_effect=fake_fetch):
        result = compute_owner_benchmark(
            holdings=holdings, owner="me", project_dir=str(tmp_path),
            market_data=market_data,
        )

    assert result["status"] == "error"
    assert "error_message" in result
    assert result["ytd_pct"] is None
```

- [ ] **Step 2: Implement `compute_owner_benchmark`**

Add to `benchmark_ytd.py`:

```python
def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def compute_owner_benchmark(
    holdings: list[dict],
    owner: str,
    project_dir: str,
    market_data: dict,
) -> dict:
    """Top-level entry point used by pipeline.

    Builds/loads baseline cache, fetches today's SPY price (separate from market_data
    for robustness when SPY isn't held), computes returns. Returns dict with `status`
    field — "ok" or "error" — so callers can render placeholder UI on failure.

    today USD/KRW comes from market_data["_macro"]["USD_KRW"].
    today native prices for held tickers come from market_data["data"][ticker]["price"].
    """
    try:
        baseline = load_or_build_baseline(holdings, owner, project_dir)
    except Exception as e:
        return {
            "status": "error",
            "error_message": f"baseline build failed: {e}",
            "ytd_pct": None,
            "spy_ytd_pct": None,
            "alpha_pp": None,
        }

    today_usd_krw = (market_data.get("_macro") or {}).get("USD_KRW") or 0
    if today_usd_krw <= 0:
        return {
            "status": "error",
            "error_message": "today USD/KRW unavailable in market_data",
            "ytd_pct": None,
            "spy_ytd_pct": None,
            "alpha_pp": None,
        }

    data = market_data.get("data", {}) or {}
    today_prices = {t: (data.get(t) or {}).get("price") for t in [h["ticker"] for h in holdings]}

    today_spy_usd = fetch_close_on(SPY_SYMBOL, _today_str(), use_adj_close=True)
    if today_spy_usd is None or today_spy_usd <= 0:
        # fallback to market_data SPY if present
        spy_today = (data.get("SPY") or {}).get("price")
        if spy_today and spy_today > 0:
            today_spy_usd = float(spy_today)
        else:
            return {
                "status": "error",
                "error_message": "today SPY price unavailable",
                "ytd_pct": None,
                "spy_ytd_pct": None,
                "alpha_pp": None,
            }

    result = compute_returns(holdings, today_prices, today_usd_krw, today_spy_usd, baseline)
    result["status"] = "ok"
    result["anchor_date"] = baseline["anchor_date"]
    return result
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_benchmark_ytd.py -v`
Expected: PASS (28 tests)

- [ ] **Step 4: Commit**

```bash
git add benchmark_ytd.py tests/test_benchmark_ytd.py
git commit -m "feat(benchmark): compute_owner_benchmark top-level entry"
```

---

## Task 9: Extend `save_portfolio_snapshot` with optional ytd fields

**Files:**
- Modify: `history_manager.py:194-239`
- Test: `tests/test_benchmark_ytd.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_benchmark_ytd.py`:

```python
def test_save_portfolio_snapshot_with_ytd_fields(tmp_path):
    """save_portfolio_snapshot accepts ytd_pct/spy_ytd_pct/alpha_pp/v0_krw/spy_v0_krw kwargs."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from history_manager import save_portfolio_snapshot, load_portfolio_daily

    path = str(tmp_path / "portfolio_daily.json")
    daily = save_portfolio_snapshot(
        path=path,
        date_str="2026-04-27",
        total_value_krw=2_000_000_000,
        cost_basis_krw=800_000_000,
        cash_value_krw=100_000_000,
        cash_pct=5.0,
        div_annual_krw=40_000_000,
        div_yield=2.0,
        usd_krw=1300.0,
        vix=20.0,
        yield_30y=4.5,
        master_switch="GREEN",
        holdings_count=18,
        weights_by_category={},
        weights_by_ticker={},
        ytd_pct=5.2,
        spy_ytd_pct=3.1,
        alpha_pp=2.1,
        v0_krw=1_900_000_000,
        spy_v0_krw=608_400.0,
    )

    snapshot = daily["2026-04-27"]
    assert snapshot["ytd_pct"] == 5.2
    assert snapshot["spy_ytd_pct"] == 3.1
    assert snapshot["alpha_pp"] == 2.1
    assert snapshot["v0_krw"] == 1_900_000_000
    assert snapshot["spy_v0_krw"] == 608_400


def test_save_portfolio_snapshot_backward_compatible(tmp_path):
    """Calling without new kwargs still works (no ytd fields in snapshot)."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from history_manager import save_portfolio_snapshot

    path = str(tmp_path / "portfolio_daily.json")
    daily = save_portfolio_snapshot(
        path=path, date_str="2026-04-27",
        total_value_krw=1_000, cost_basis_krw=900, cash_value_krw=0, cash_pct=0,
        div_annual_krw=0, div_yield=0, usd_krw=1300, vix=None, yield_30y=None,
        master_switch="GREEN", holdings_count=1,
        weights_by_category={}, weights_by_ticker={},
    )
    snap = daily["2026-04-27"]
    # New keys absent (not None — actually absent from dict)
    assert "ytd_pct" not in snap
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_benchmark_ytd.py::test_save_portfolio_snapshot_with_ytd_fields -v`
Expected: FAIL with `TypeError: unexpected keyword argument 'ytd_pct'`

- [ ] **Step 3: Modify `history_manager.py:save_portfolio_snapshot`**

Replace the function signature and body:

```python
def save_portfolio_snapshot(
    path: str,
    date_str: str,
    total_value_krw: float,
    cost_basis_krw: float,
    cash_value_krw: float,
    cash_pct: float,
    div_annual_krw: float,
    div_yield: float,
    usd_krw: float,
    vix: float | None,
    yield_30y: float | None,
    master_switch: str,
    holdings_count: int,
    weights_by_category: dict,
    weights_by_ticker: dict,
    ytd_pct: float | None = None,
    spy_ytd_pct: float | None = None,
    alpha_pp: float | None = None,
    v0_krw: float | None = None,
    spy_v0_krw: float | None = None,
):
    """일별 포트폴리오 스냅샷을 portfolio_daily.json에 저장."""
    daily = load_portfolio_daily(path)

    pnl_krw = total_value_krw - cost_basis_krw
    pnl_pct = (pnl_krw / cost_basis_krw * 100) if cost_basis_krw > 0 else 0

    snap = {
        "total_value_krw": round(total_value_krw),
        "cost_basis_krw": round(cost_basis_krw),
        "pnl_krw": round(pnl_krw),
        "pnl_pct": round(pnl_pct, 1),
        "cash_value_krw": round(cash_value_krw),
        "cash_pct": round(cash_pct, 1),
        "div_annual_krw": round(div_annual_krw),
        "div_yield": round(div_yield, 2),
        "usd_krw": round(usd_krw, 2) if usd_krw else 0,
        "vix": round(vix, 2) if vix else None,
        "yield_30y": round(yield_30y, 3) if yield_30y else None,
        "master_switch": master_switch,
        "holdings_count": holdings_count,
        "weights_by_category": weights_by_category,
        "weights_by_ticker": weights_by_ticker,
    }
    if ytd_pct is not None:
        snap["ytd_pct"] = round(ytd_pct, 2)
    if spy_ytd_pct is not None:
        snap["spy_ytd_pct"] = round(spy_ytd_pct, 2)
    if alpha_pp is not None:
        snap["alpha_pp"] = round(alpha_pp, 2)
    if v0_krw is not None:
        snap["v0_krw"] = round(v0_krw)
    if spy_v0_krw is not None:
        snap["spy_v0_krw"] = round(spy_v0_krw, 2)

    daily[date_str] = snap

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(daily, f, ensure_ascii=False, indent=2)

    return daily
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_benchmark_ytd.py -v`
Expected: PASS (30 tests)

- [ ] **Step 5: Commit**

```bash
git add history_manager.py tests/test_benchmark_ytd.py
git commit -m "feat(history): save_portfolio_snapshot accepts optional ytd fields"
```

---

## Task 10: Wire benchmark into pipeline (compute per owner before reports)

**Files:**
- Modify: `pipeline.py:303-319` (insert benchmark step before generate_report)
- Modify: `pipeline.py:494-510` (pass ytd kwargs to save_portfolio_snapshot)
- Modify: `pipeline.py:544+` (compute for each non-me owner before their generate_report)

- [ ] **Step 1: Add benchmark computation block before "Step 5: Report generation"**

In `pipeline.py`, after the politician trades step (line ~302) and before `print("[Step 5] Generating report...")`, insert:

```python
        # Step 4d: YTD benchmark (vs S&P KRW) — per owner
        print("[Step 4d] Computing YTD benchmark vs S&P (KRW)...")
        from benchmark_ytd import compute_owner_benchmark
        from portfolio_paths import discover_portfolios, PRIMARY_OWNER

        benchmark_by_owner: dict[str, dict] = {}
        try:
            me_holdings_for_bench = _parse_portfolio_for_report(portfolio_path)
            benchmark_by_owner["me"] = compute_owner_benchmark(
                holdings=me_holdings_for_bench,
                owner="me",
                project_dir=project_dir,
                market_data=market_data,
            )
            _bm = benchmark_by_owner["me"]
            if _bm.get("status") == "ok":
                print(f"  OK me: YTD={_bm['ytd_pct']:+.2f}%  S&P={_bm['spy_ytd_pct']:+.2f}%  α={_bm['alpha_pp']:+.2f}pp")
            else:
                print(f"  WARN me benchmark: {_bm.get('error_message', 'unknown')}")
        except Exception as _be:
            print(f"  WARN me benchmark exception: {_be}")
            benchmark_by_owner["me"] = {"status": "error", "error_message": str(_be), "ytd_pct": None, "spy_ytd_pct": None, "alpha_pp": None}

        try:
            for _owner, _opath in discover_portfolios(project_dir):
                if _owner == PRIMARY_OWNER:
                    continue
                _oholds = _parse_portfolio_for_report(_opath)
                benchmark_by_owner[_owner] = compute_owner_benchmark(
                    holdings=_oholds, owner=_owner, project_dir=project_dir,
                    market_data=market_data,
                )
                _ob = benchmark_by_owner[_owner]
                if _ob.get("status") == "ok":
                    print(f"  OK {_owner}: YTD={_ob['ytd_pct']:+.2f}%  S&P={_ob['spy_ytd_pct']:+.2f}%  α={_ob['alpha_pp']:+.2f}pp")
                else:
                    print(f"  WARN {_owner} benchmark: {_ob.get('error_message', 'unknown')}")
        except Exception as _be2:
            print(f"  WARN secondary owner benchmarks failed: {_be2}")
```

- [ ] **Step 2: Pass `benchmark_by_owner["me"]` into the me `generate_report` call (line 309-319)**

Modify:

```python
        generate_report(
            market_data=market_data,
            portfolio=portfolio,
            signals=signals,
            history=history,
            prev_signals=prev_signals,
            output_path=report_path,
            scanner_sp100=scanner_sp100_result,
            scanner_etf=scanner_etf_result,
            scanner_kospi=scanner_kospi_result,
            benchmark_data=benchmark_by_owner.get("me"),
        )
```

- [ ] **Step 3: Pass benchmark to save_portfolio_snapshot for me**

Modify the `_save_owner_snapshot` function inside `pipeline.py` (around line 494) — extend the call to include the new kwargs:

Replace the `return save_portfolio_snapshot(...)` block with:

```python
                _bm = benchmark_by_owner.get(owner) or {}
                return save_portfolio_snapshot(
                    path=path,
                    date_str=today,
                    total_value_krw=total_krw,
                    cost_basis_krw=cost_krw,
                    cash_value_krw=cash_k,
                    cash_pct=c_pct,
                    div_annual_krw=_div_ann_krw,
                    div_yield=_div_yield,
                    usd_krw=usd_krw,
                    vix=macro.get("VIX"),
                    yield_30y=macro.get("yield_30Y"),
                    master_switch=macro.get("master_switch", "UNKNOWN"),
                    holdings_count=len(owner_portfolio),
                    weights_by_category=w_cat,
                    weights_by_ticker=w_tick,
                    ytd_pct=_bm.get("ytd_pct"),
                    spy_ytd_pct=_bm.get("spy_ytd_pct"),
                    alpha_pp=_bm.get("alpha_pp"),
                    v0_krw=_bm.get("v0_krw"),
                    spy_v0_krw=_bm.get("spy_v0_krw"),
                )
```

- [ ] **Step 4: Pass benchmark for wife report (Step 5d area, ~line 544+)**

Locate the section that calls `generate_report` for non-primary owners (search for the `for _owner, _opath in discover_portfolios(project_dir):` loop after Step 5d header). Find the line where `generate_report` is invoked for the wife/secondary owner and add `benchmark_data=benchmark_by_owner.get(_owner)` parameter to that call.

If the secondary report uses `app.py`'s `_render_owner_report` instead of pipeline's direct `generate_report`, also propagate the benchmark dict via app.py — but for pipeline.py's own secondary-report block, just add the kwarg.

- [ ] **Step 5: Manual smoke test of pipeline structure (no run yet)**

Run: `python -c "import pipeline; print('imports OK')"`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add pipeline.py
git commit -m "feat(pipeline): compute YTD benchmark per owner + thread to reports/snapshots"
```

---

## Task 11: `report_generator.generate_report` accepts `benchmark_data`, injects to template context

**Files:**
- Modify: `report_generator.py:280-440` (function signature + context dict)

- [ ] **Step 1: Locate `generate_report` signature**

Open `report_generator.py`. Find `def generate_report(` (around line 240-280). Add a new keyword-only param:

```python
def generate_report(
    market_data,
    portfolio,
    signals,
    history,
    prev_signals,
    output_path,
    *,
    scanner_sp100=None,
    scanner_etf=None,
    scanner_kospi=None,
    nav_portfolio=None,
    active_nav="me",
    benchmark_data=None,  # NEW
):
```

(Adjust `*,` placement to match existing kwargs.) If the function does not currently use `*,` separator, just add `benchmark_data=None` at the end of the signature.

- [ ] **Step 2: Inject benchmark fields into context dict**

In the same function, find the `context = {` block (around line 371). Just before `html = template.render(**context)`, add:

```python
    # Benchmark data (YTD vs S&P KRW)
    if benchmark_data and benchmark_data.get("status") == "ok":
        context["benchmark_status"] = "ok"
        context["ytd_pct"] = benchmark_data.get("ytd_pct")
        context["spy_ytd_pct"] = benchmark_data.get("spy_ytd_pct")
        context["alpha_pp"] = benchmark_data.get("alpha_pp")
        context["benchmark_anchor_date"] = benchmark_data.get("anchor_date", "2026-01-02")
        context["benchmark_excluded"] = benchmark_data.get("excluded_tickers", [])
    else:
        context["benchmark_status"] = "error"
        context["ytd_pct"] = None
        context["spy_ytd_pct"] = None
        context["alpha_pp"] = None
        context["benchmark_anchor_date"] = "2026-01-02"
        context["benchmark_excluded"] = []
        if benchmark_data:
            context["benchmark_error"] = benchmark_data.get("error_message", "unknown")
```

- [ ] **Step 3: Verify import works**

Run: `python -c "from report_generator import generate_report; import inspect; print('benchmark_data' in inspect.signature(generate_report).parameters)"`
Expected: `True`

- [ ] **Step 4: Commit**

```bash
git add report_generator.py
git commit -m "feat(report): generate_report accepts benchmark_data + injects to template ctx"
```

---

## Task 12: Add YTD/S&P/α line to main report header template

**Files:**
- Modify: `templates/report_template.html:266-282`

- [ ] **Step 1: Locate header block**

Open `templates/report_template.html`. Find the `<p>...vs Principal</p>` line (around line 272) inside the "Total Equity Value" card.

- [ ] **Step 2: Insert benchmark line directly after the "vs Principal" `<p>` element**

Add this immediately after line 272 (the `vs Principal` paragraph):

```html
              {% if benchmark_status == "ok" and ytd_pct is not none and spy_ytd_pct is not none %}
              <div class="mt-2 pt-2 border-t border-outline-variant/10 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-label">
                <span class="text-on-surface-variant uppercase tracking-widest">2026 YTD</span>
                <span class="font-bold {{ 'text-secondary' if ytd_pct >= 0 else 'text-tertiary' }}">{{ '+' if ytd_pct >= 0 else '' }}{{ '%.2f'|format(ytd_pct) }}%</span>
                <span class="text-outline">·</span>
                <span class="text-on-surface-variant">S&amp;P (₩)</span>
                <span class="font-bold {{ 'text-secondary' if spy_ytd_pct >= 0 else 'text-tertiary' }}">{{ '+' if spy_ytd_pct >= 0 else '' }}{{ '%.2f'|format(spy_ytd_pct) }}%</span>
                <span class="text-outline">·</span>
                <span class="text-on-surface-variant">α</span>
                <span class="font-bold {{ 'text-secondary' if alpha_pp >= 0 else 'text-tertiary' }}">{{ '+' if alpha_pp >= 0 else '' }}{{ '%.2f'|format(alpha_pp) }}pp</span>
                <span class="ml-1 cursor-help text-outline" title="2026-01-02 기준 baseline. 보유 종목/수량이 변경되면 baseline도 자동 재계산됩니다. 1월 이후 신규 매수 종목은 1월~매수일 가격 변동분이 함께 반영되어 실제 거래 성과와 차이가 있을 수 있습니다.{% if benchmark_excluded %} 제외된 종목: {{ benchmark_excluded|join(', ') }}{% endif %}">ⓘ</span>
              </div>
              {% elif benchmark_status == "error" %}
              <p class="mt-2 text-xs font-label text-outline">2026 YTD: 데이터 준비 중...</p>
              {% endif %}
```

- [ ] **Step 3: Verify template renders without error**

Run: `python -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('templates'))
t = env.get_template('report_template.html')
# Minimal context just to parse; provide all required keys as None/empty
print('template loaded OK')
"`
Expected: prints "template loaded OK" without exception.

- [ ] **Step 4: Commit**

```bash
git add templates/report_template.html
git commit -m "feat(template): add 2026 YTD / S&P(₩) / α line to main report header"
```

---

## Task 13: Generate trend page passes benchmark series + latest values

**Files:**
- Modify: `report_generator.py:601-645` (`_series_from_daily`)
- Modify: `report_generator.py:618-649` (`_build_owner_payload`)
- Modify: `report_generator.py:712-844` (`generate_trend_page`)

- [ ] **Step 1: Locate `_series_from_daily` (around line 601)**

Read existing implementation. It returns a list of dicts with date/total_eok/pnl_eok/pnl_pct etc.

- [ ] **Step 2: Extend `_series_from_daily` to include ytd fields**

Find the `trend_data.append({...})` block inside `_series_from_daily` (around line 605-615). Add three keys to each appended dict:

```python
            "ytd_pct": snap.get("ytd_pct"),
            "spy_ytd_pct": snap.get("spy_ytd_pct"),
            "alpha_pp": snap.get("alpha_pp"),
```

- [ ] **Step 3: Extend `_build_owner_payload` "latest" dict**

Find `_build_owner_payload` (around line 618-649). The `latest` dict assignment near the end (around line 625-635). Add:

```python
        "ytd_pct": latest_snap.get("ytd_pct"),
        "spy_ytd_pct": latest_snap.get("spy_ytd_pct"),
        "alpha_pp": latest_snap.get("alpha_pp"),
```

- [ ] **Step 4: Extend `generate_trend_page` "latest" context (around line 760-770)**

Find the `latest_snap = portfolio_daily.get(...)` block. The dict that becomes part of context. Add the same three keys:

```python
        "ytd_pct": latest_snap.get("ytd_pct"),
        "spy_ytd_pct": latest_snap.get("spy_ytd_pct"),
        "alpha_pp": latest_snap.get("alpha_pp"),
```

- [ ] **Step 5: Verify report_generator imports/parses**

Run: `python -c "import report_generator; print('OK')"`
Expected: prints "OK" without error.

- [ ] **Step 6: Commit**

```bash
git add report_generator.py
git commit -m "feat(report): trend payload includes ytd_pct/spy_ytd_pct/alpha_pp series"
```

---

## Task 14: Add YTD summary card block to trend template

**Files:**
- Modify: `templates/trend_template.html:84-118` (insert before existing summary cards or as new row)

- [ ] **Step 1: Insert new YTD card row after existing summary cards (line ~118)**

Open `templates/trend_template.html`. After the closing `</div>` of the existing 4-card summary row (line ~118), insert:

```html
    <!-- YTD Benchmark Cards -->
    {% if latest.ytd_pct is not none and latest.spy_ytd_pct is not none %}
    <div class="grid grid-cols-2 lg:grid-cols-3 gap-4">
      <div class="rounded-xl bg-surface-container p-5 border border-outline-variant/10 border-l-4 {{ 'border-l-secondary' if latest.ytd_pct >= 0 else 'border-l-tertiary' }} flex items-center gap-4">
        <span class="material-symbols-outlined {{ 'text-secondary/60' if latest.ytd_pct >= 0 else 'text-tertiary/60' }} flex-shrink-0" style="font-size:44px;font-variation-settings:'FILL' 1;">flag</span>
        <div class="min-w-0 flex-1">
          <span class="block text-[10px] font-label text-on-surface-variant uppercase tracking-widest mb-2">2026 YTD (Portfolio)</span>
          <div class="text-2xl font-headline font-bold {{ 'text-secondary' if latest.ytd_pct >= 0 else 'text-tertiary' }}" id="sumYtd">{{ '+' if latest.ytd_pct >= 0 else '' }}{{ '%.2f'|format(latest.ytd_pct) }}%</div>
          <div class="text-xs mt-2 text-outline">기준: 2026-01-02</div>
        </div>
      </div>
      <div class="rounded-xl bg-surface-container p-5 border border-outline-variant/10 border-l-4 {{ 'border-l-secondary' if latest.spy_ytd_pct >= 0 else 'border-l-tertiary' }} flex items-center gap-4">
        <span class="material-symbols-outlined {{ 'text-secondary/60' if latest.spy_ytd_pct >= 0 else 'text-tertiary/60' }} flex-shrink-0" style="font-size:44px;font-variation-settings:'FILL' 1;">show_chart</span>
        <div class="min-w-0 flex-1">
          <span class="block text-[10px] font-label text-on-surface-variant uppercase tracking-widest mb-2">S&amp;P 500 YTD (₩)</span>
          <div class="text-2xl font-headline font-bold {{ 'text-secondary' if latest.spy_ytd_pct >= 0 else 'text-tertiary' }}" id="sumSpy">{{ '+' if latest.spy_ytd_pct >= 0 else '' }}{{ '%.2f'|format(latest.spy_ytd_pct) }}%</div>
          <div class="text-xs mt-2 text-outline">SPY × USD/KRW</div>
        </div>
      </div>
      <div class="rounded-xl bg-surface-container p-5 border border-outline-variant/10 border-l-4 {{ 'border-l-secondary' if latest.alpha_pp >= 0 else 'border-l-tertiary' }} flex items-center gap-4">
        <span class="material-symbols-outlined {{ 'text-secondary/60' if latest.alpha_pp >= 0 else 'text-tertiary/60' }} flex-shrink-0" style="font-size:44px;font-variation-settings:'FILL' 1;">trending_up</span>
        <div class="min-w-0 flex-1">
          <span class="block text-[10px] font-label text-on-surface-variant uppercase tracking-widest mb-2">Alpha vs S&amp;P</span>
          <div class="text-2xl font-headline font-bold {{ 'text-secondary' if latest.alpha_pp >= 0 else 'text-tertiary' }}" id="sumAlpha">{{ '+' if latest.alpha_pp >= 0 else '' }}{{ '%.2f'|format(latest.alpha_pp) }}pp</div>
          <div class="text-xs mt-2 text-outline">초과수익</div>
        </div>
      </div>
    </div>
    {% endif %}
```

- [ ] **Step 2: Verify template parses**

Run: `python -c "from jinja2 import Environment, FileSystemLoader; env = Environment(loader=FileSystemLoader('templates')); env.get_template('trend_template.html'); print('OK')"`
Expected: "OK".

- [ ] **Step 3: Commit**

```bash
git add templates/trend_template.html
git commit -m "feat(trend): add YTD/S&P/α summary cards row"
```

---

## Task 15: Add normalized comparison chart to trend template

**Files:**
- Modify: `templates/trend_template.html` (add new canvas + JS render block)

- [ ] **Step 1: Locate existing trend chart block**

Open `templates/trend_template.html`. Search for `<canvas id="trendChart"` or similar. Identify the section containing the existing KRW trend chart.

- [ ] **Step 2: Insert new canvas after the existing trend chart's parent block**

After the closing `</div>` of the existing trend chart card, insert:

```html
    <!-- YTD Comparison Chart (Portfolio vs S&P, normalized) -->
    {% if latest.ytd_pct is not none and latest.spy_ytd_pct is not none %}
    <div class="rounded-xl bg-surface-container p-6 border border-outline-variant/10">
      <div class="flex items-center justify-between mb-4">
        <h3 class="font-headline font-bold text-lg flex items-center gap-2">
          <span class="material-symbols-outlined text-primary">compare_arrows</span>
          포트폴리오 vs S&amp;P 500 (₩) — 2026 YTD
        </h3>
        <span class="text-xs text-outline font-label">기준: 2026-01-02 = 0%</span>
      </div>
      <div class="relative" style="height:340px;">
        <canvas id="ytdCompareChart"></canvas>
      </div>
    </div>
    {% endif %}
```

- [ ] **Step 3: Add chart rendering JS**

Find the existing trend chart's `new Chart(...)` invocation in the template's `<script>` block. Below it (still inside the same script tag), add:

```javascript
    // YTD Comparison Chart
    (function renderYtdChart() {
      const trendArr = {{ trend_json|safe }};
      if (!trendArr || trendArr.length === 0) return;
      const labels = trendArr.map(d => d.date);
      const portSeries = trendArr.map(d => d.ytd_pct);
      const spySeries = trendArr.map(d => d.spy_ytd_pct);
      // skip render if any series is fully null
      if (portSeries.every(v => v == null) || spySeries.every(v => v == null)) return;

      const ctxYtd = document.getElementById('ytdCompareChart');
      if (!ctxYtd) return;

      new Chart(ctxYtd, {
        type: 'line',
        data: {
          labels,
          datasets: [
            {
              label: 'Portfolio (₩)',
              data: portSeries,
              borderColor: 'rgb(109, 221, 255)',
              backgroundColor: 'rgba(109, 221, 255, 0.1)',
              borderWidth: 2.5,
              tension: 0.25,
              pointRadius: 2,
              fill: false,
            },
            {
              label: 'S&P 500 (₩)',
              data: spySeries,
              borderColor: 'rgba(163, 170, 196, 0.9)',
              borderDash: [6, 4],
              borderWidth: 2,
              tension: 0.25,
              pointRadius: 2,
              fill: false,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: 'bottom', labels: { font: { size: 12 } } },
            tooltip: {
              callbacks: {
                label: function(c) {
                  const v = c.parsed.y;
                  return `${c.dataset.label}: ${v == null ? 'n/a' : (v >= 0 ? '+' : '') + v.toFixed(2) + '%'}`;
                },
              },
            },
          },
          scales: {
            y: {
              ticks: {
                callback: function(v) { return (v >= 0 ? '+' : '') + v.toFixed(1) + '%'; },
              },
              grid: { color: 'rgba(163, 170, 196, 0.1)' },
            },
            x: { grid: { display: false } },
          },
        },
      });
    })();
```

- [ ] **Step 4: Verify template parses**

Run: `python -c "from jinja2 import Environment, FileSystemLoader; env = Environment(loader=FileSystemLoader('templates')); env.get_template('trend_template.html'); print('OK')"`
Expected: "OK".

- [ ] **Step 5: Commit**

```bash
git add templates/trend_template.html
git commit -m "feat(trend): normalized portfolio vs S&P (KRW) comparison chart"
```

---

## Task 16: Integration test — pipeline writes ytd fields into portfolio_daily.json

**Files:**
- Create: `tests/test_benchmark_pipeline_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_benchmark_pipeline_integration.py
"""Integration: portfolio_daily.json gains ytd_pct/spy_ytd_pct/alpha_pp after pipeline."""
import json
import os
import sys
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mock_yf_for(symbol_to_close: dict):
    """Build a yf.Ticker mock factory keyed by symbol → close value."""
    def _factory(symbol):
        m = MagicMock()
        if symbol in symbol_to_close:
            df = pd.DataFrame(
                {"Close": [symbol_to_close[symbol]], "Adj Close": [symbol_to_close[symbol]]},
                index=pd.to_datetime(["2026-01-02"]),
            )
        else:
            df = pd.DataFrame()
        m.history.return_value = df
        return m
    return _factory


def test_compute_owner_benchmark_persists_to_baseline_cache(tmp_path):
    """Calling compute_owner_benchmark twice in a row → cache reused (no second build)."""
    from benchmark_ytd import compute_owner_benchmark

    holdings = [{"ticker": "AAPL", "shares": 10}]
    market_data = {"data": {"AAPL": {"price": 157.5}, "SPY": {"price": 482.04}}, "_macro": {"USD_KRW": 1300.0}}

    fake = {"AAPL": 150.0, "KRW=X": 1300.0, "SPY": 468.0}
    call_log = []

    def tracked_fetch(symbol, date_str, use_adj_close=False):
        call_log.append((symbol, date_str))
        if symbol == "SPY" and date_str != "2026-01-02":
            return 482.04  # today
        return fake.get(symbol)

    with patch("benchmark_ytd.fetch_close_on", side_effect=tracked_fetch):
        r1 = compute_owner_benchmark(holdings, "me", str(tmp_path), market_data)
        first_calls = list(call_log)
        r2 = compute_owner_benchmark(holdings, "me", str(tmp_path), market_data)
        second_calls = call_log[len(first_calls):]

    assert r1["status"] == "ok"
    assert r2["status"] == "ok"
    # Second call should fetch only today SPY (Jan 2 prices come from cache)
    second_symbols = [s for s, d in second_calls]
    assert "AAPL" not in second_symbols
    assert "KRW=X" not in second_symbols


def test_save_portfolio_snapshot_with_benchmark_full_round_trip(tmp_path):
    """End-to-end: compute benchmark, save snapshot, reload, ytd fields present."""
    from benchmark_ytd import compute_owner_benchmark
    from history_manager import save_portfolio_snapshot, load_portfolio_daily

    holdings = [{"ticker": "AAPL", "shares": 10}]
    market_data = {"data": {"AAPL": {"price": 157.5}}, "_macro": {"USD_KRW": 1300.0}}

    def fake_fetch(symbol, date_str, use_adj_close=False):
        if symbol == "SPY":
            return 468.0 if date_str == "2026-01-02" else 482.04
        return {"AAPL": 150.0, "KRW=X": 1300.0}.get(symbol)

    with patch("benchmark_ytd.fetch_close_on", side_effect=fake_fetch):
        bm = compute_owner_benchmark(holdings, "me", str(tmp_path), market_data)

    assert bm["status"] == "ok"

    daily_path = str(tmp_path / "history" / "portfolio_daily.json")
    save_portfolio_snapshot(
        path=daily_path, date_str="2026-04-27",
        total_value_krw=bm["v_now_krw"], cost_basis_krw=1_900_000.0,
        cash_value_krw=0, cash_pct=0,
        div_annual_krw=0, div_yield=0, usd_krw=1300.0,
        vix=20.0, yield_30y=4.5, master_switch="GREEN",
        holdings_count=1, weights_by_category={}, weights_by_ticker={},
        ytd_pct=bm["ytd_pct"], spy_ytd_pct=bm["spy_ytd_pct"], alpha_pp=bm["alpha_pp"],
        v0_krw=bm["v0_krw"], spy_v0_krw=bm["spy_v0_krw"],
    )

    daily = load_portfolio_daily(daily_path)
    snap = daily["2026-04-27"]
    assert "ytd_pct" in snap
    assert "spy_ytd_pct" in snap
    assert "alpha_pp" in snap
    assert "v0_krw" in snap
    assert round(snap["ytd_pct"], 2) == 5.0
    assert round(snap["spy_ytd_pct"], 2) == 3.0
    assert round(snap["alpha_pp"], 2) == 2.0
```

- [ ] **Step 2: Run integration tests**

Run: `python -m pytest tests/test_benchmark_pipeline_integration.py -v`
Expected: PASS (2 tests)

- [ ] **Step 3: Run full test suite — verify no regression**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS (32+ tests, no regressions in scanner_data/politician_filter/scanner_entry_sector tests)

- [ ] **Step 4: Commit**

```bash
git add tests/test_benchmark_pipeline_integration.py
git commit -m "test(benchmark): pipeline integration — cache reuse + full snapshot round-trip"
```

---

## Task 17: End-to-end manual smoke test

**Files:**
- None (manual verification)

- [ ] **Step 1: Backup current data/ directory**

```bash
cp -r data data.bak.before-ytd 2>/dev/null || true
```

- [ ] **Step 2: Run pipeline once**

```bash
python pipeline.py --skip-ocr
```

Expected console output includes:
- `[Step 4d] Computing YTD benchmark vs S&P (KRW)...`
- `OK me: YTD=+X.XX%  S&P=+Y.YY%  α=+Z.ZZpp`
- `OK wife: YTD=...` (if wife portfolio exists)

- [ ] **Step 3: Verify cache files were created**

```bash
ls -la data/baseline_2026_*.json
```

Expected: `data/baseline_2026_me.json` and `data/baseline_2026_wife.json` exist.

Inspect contents:
```bash
python -c "import json; d=json.load(open('data/baseline_2026_me.json',encoding='utf-8')); print('keys:', list(d.keys())); print('tickers:', len(d['ticker_v0_krw'])); print('unmappable:', d['unmappable']); print('USD/KRW:', d['usd_krw']); print('SPY:', d['spy_close_usd'])"
```

Expected: keys = anchor_date/usd_krw/spy_close_usd/ticker_v0_krw/unmappable; tickers count > 0.

- [ ] **Step 4: Verify portfolio_daily.json has new fields for today**

```bash
python -c "
import json
from datetime import date
d = json.load(open('history/portfolio_daily.json', encoding='utf-8'))
today = date.today().strftime('%Y-%m-%d')
snap = d.get(today, {})
print('ytd_pct:', snap.get('ytd_pct'))
print('spy_ytd_pct:', snap.get('spy_ytd_pct'))
print('alpha_pp:', snap.get('alpha_pp'))
print('v0_krw:', snap.get('v0_krw'))
"
```

Expected: All four values are non-None numbers.

- [ ] **Step 5: Open generated reports in a browser**

```bash
python -c "import os, glob; files = sorted(glob.glob('reports/report_*.html')); print(files[-1])"
```

Open the latest report in a browser. Verify:
- Header shows "2026 YTD: +X.XX% · S&P (₩): +Y.YY% · α: +Z.ZZpp ⓘ"
- Hover over ⓘ shows the caveat tooltip
- Color: positive values green (text-secondary), negative red (text-tertiary)

Open `reports/trend_<today>.html`. Verify:
- 3-card row showing Portfolio YTD / S&P (₩) / Alpha appears
- New comparison chart "포트폴리오 vs S&P 500 (₩) — 2026 YTD" renders with two lines
- Toggle between owners (me / wife) updates all three cards and the chart

- [ ] **Step 6: Hand-calculation sanity check**

Pick the largest US holding (e.g., VOO 185 shares). Manually compute:
- v0_per_share_krw = VOO_jan2_close × Jan2_USD_KRW
- v_now_per_share_krw = VOO_today_close × today_USD_KRW
- expected_ytd_per_share_pct = (v_now - v0) / v0 × 100

Compare with `data/baseline_2026_me.json`'s `ticker_v0_krw["VOO"]` (should equal v0_per_share_krw within 0.01).

- [ ] **Step 7: External cross-check**

Look up SPY YTD return on a public source (e.g., Yahoo Finance: "SPY YTD" or Naver "원화 환산 SPY"). Compare with `spy_ytd_pct` from the report. Tolerance: ±0.5pp.

- [ ] **Step 8: Document any anomalies**

If any value seems wrong, note it and investigate. Common issues:
- yfinance returned wrong day (weekend/holiday) → check anchor_date in cache
- KOSDAQ ticker .KQ vs .KS confusion → check `to_yfinance_symbol` mapping
- Currency double-conversion → check `is_korean_ticker` branch in `compute_v0_total_krw`

If everything looks reasonable, commit any small fixes and a verification note:

```bash
git commit --allow-empty -m "verify: YTD benchmark numbers cross-checked against external sources"
```

---

## Self-Review Notes

After writing this plan, fresh-eyes check:

**Spec coverage:**
- ✅ §2.1 Constant-portfolio backtest formula → Task 4 (build_baseline) + Task 6 (compute_v0/v_now)
- ✅ §2.2 v0 매 실행 재계산 → Task 5 (load_or_build_baseline incremental append)
- ✅ §2.3 Limitation caveat → Task 12 (tooltip text)
- ✅ §2.4 SPY KRW 환산 + alpha → Task 7 (compute_returns)
- ✅ §3.1 benchmark_ytd module structure → Tasks 1–8
- ✅ §3.2 Pipeline integration → Task 10
- ✅ §3.3 Cache policy → Task 5
- ✅ §3.4 Data flow (portfolio_daily save) → Tasks 9, 10
- ✅ §4.1 Main header line → Task 12
- ✅ §4.2(a) Trend summary cards → Task 14
- ✅ §4.2(b) Normalized comparison chart → Task 15
- ✅ §4.3 Caveat tooltip text → Task 12
- ✅ §5.1 Ticker fetch / unmappable → Tasks 2, 3, 4
- ✅ §5.2 Cash treatment → covered implicitly (BIL is a regular ticker; no separate cash field exists in portfolio model)
- ✅ §5.3 USD/KRW failure → Task 4 (RuntimeError on None)
- ✅ §5.4 SPY Adj Close + today separate fetch → Tasks 3, 8
- ✅ §5.5 Holiday boundary → Task 3 (7-day window)
- ✅ §5.6 Holdings change detection → Task 5
- ✅ §5.7 Owner separation → Tasks 5, 10
- ✅ §5.8 Failure fallback "데이터 준비 중" → Tasks 8, 11, 12
- ✅ §6 Tests → Tasks 1–9 (unit), Task 16 (integration), Task 17 (manual)

**Type consistency check:**
- `compute_v0_total_krw`, `compute_v_now_total_krw`: both return `tuple[float, list[str]]` — consistent.
- `compute_returns`: returns dict with `ytd_pct: float | None`, `alpha_pp: float | None` — Task 11 template handles both.
- `compute_owner_benchmark`: returns dict with `status: "ok"|"error"`, ytd_pct/spy_ytd_pct/alpha_pp — Task 11 reads these.
- `save_portfolio_snapshot`: optional kwargs `ytd_pct/spy_ytd_pct/alpha_pp/v0_krw/spy_v0_krw` — Task 10 passes them by name.

**Placeholder scan:** None.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-27-ytd-benchmark.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — Fresh subagent per task with two-stage review between tasks. Good for catching cross-task drift.

**2. Inline Execution** — Execute tasks directly in this session with checkpoints for review. Faster, single context.

Which approach?
