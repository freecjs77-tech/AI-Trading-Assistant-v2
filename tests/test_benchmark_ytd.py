"""Tests for benchmark_ytd module."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import benchmark_ytd
from benchmark_ytd import resolve_yf_symbol


def test_constants_defined():
    assert benchmark_ytd.ANCHOR_DATE == "2026-01-02"
    assert benchmark_ytd.SPY_SYMBOL == "SPY"
    assert benchmark_ytd.USDKRW_SYMBOL == "KRW=X"


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


# ---------------------------------------------------------------------------
# Task 3: yfinance close-price fetcher
# ---------------------------------------------------------------------------
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


def test_fetch_close_on_nan_returns_none():
    """yfinance can return NaN when a session has missing data; treat as None."""
    from benchmark_ytd import fetch_close_on
    import numpy as np
    df = pd.DataFrame(
        {"Close": [np.nan], "Adj Close": [np.nan]},
        index=pd.to_datetime(["2026-01-02"]),
    )
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = df
    with patch("benchmark_ytd.yf.Ticker", return_value=mock_ticker):
        assert fetch_close_on("BROKEN", "2026-01-02") is None
        assert fetch_close_on("BROKEN", "2026-01-02", use_adj_close=True) is None


# ---------------------------------------------------------------------------
# Task 4: build_baseline — Jan-2 anchor prices
# ---------------------------------------------------------------------------

def test_build_baseline_us_only():
    """Pure US holdings -> baseline has ticker_v0_krw + usd_krw + spy_close_usd."""
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
        {"ticker": "005930", "shares": 100},  # Samsung KOSPI
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
    """Ticker with no Jan 2 data -> goes to unmappable list, NOT in ticker_v0_krw."""
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
    """USD/KRW fetch failure -> raises RuntimeError (silent fallback forbidden)."""
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
    """SPY fetch failure -> raises RuntimeError."""
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


# ---------------------------------------------------------------------------
# Task 5: load_or_build_baseline — cache I/O with incremental ticker append
# ---------------------------------------------------------------------------
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
    """Existing cache + same holdings -> no fetch_close_on calls."""
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
    """Adding a new ticker -> only the new ticker is fetched, cache updated."""
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
    """Tickers in cached unmappable list -> not retried."""
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


# ---------------------------------------------------------------------------
# Task 6: compute_v0_total_krw + compute_v_now_total_krw
# ---------------------------------------------------------------------------

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
    """If today_prices lacks a ticker -> exclude from BOTH v0 and v_now (handled in caller)."""
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


# ---------------------------------------------------------------------------
# Task 7: compute_returns — YTD portfolio return, SPY KRW return, alpha
# ---------------------------------------------------------------------------

def test_compute_returns_positive_alpha():
    """Portfolio +5%, S&P (KRW) +3% -> alpha = +2.0pp."""
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
    """All holdings unmappable -> v0 = 0 -> ytd_pct = None (avoid divide-by-zero)."""
    from benchmark_ytd import compute_returns
    holdings = [{"ticker": "WEIRD", "shares": 10}]
    baseline = {
        "usd_krw": 1300.0, "spy_close_usd": 468.0,
        "ticker_v0_krw": {}, "unmappable": ["WEIRD"],
    }
    result = compute_returns(holdings, {"WEIRD": 100.0}, 1300.0, 482.0, baseline)
    assert result["ytd_pct"] is None
    assert result["alpha_pp"] is None
    # SPY independent -> still computed
    assert result["spy_ytd_pct"] is not None


def test_compute_returns_fx_movement_in_spy_krw():
    """SPY KRW return reflects USD/KRW movement, not just SPY USD."""
    from benchmark_ytd import compute_returns
    holdings = [{"ticker": "AAPL", "shares": 10}]
    baseline = {
        "usd_krw": 1000.0, "spy_close_usd": 400.0,
        "ticker_v0_krw": {"AAPL": 150_000.0}, "unmappable": [],
    }
    # SPY USD flat at 400, but FX moved 1000 -> 1100 (+10%)
    result = compute_returns(holdings, {"AAPL": 150.0}, 1100.0, 400.0, baseline)
    # SPY KRW: 400*1000=400000 -> 400*1100=440000 -> +10%
    assert round(result["spy_ytd_pct"], 2) == 10.0


def test_compute_returns_excludes_missing_today_price_from_v0_too():
    """When today_prices is missing a ticker, v0 must also exclude that ticker
    (not just v_now), to keep v_now/v0 ratio mathematically valid.

    Regression test for the v0/v_now exclusion-symmetry contract.
    """
    from benchmark_ytd import compute_returns
    holdings = [
        {"ticker": "AAPL", "shares": 10},   # mappable, has today price
        {"ticker": "TSLA", "shares": 5},    # mappable in baseline, BUT today price missing
    ]
    baseline = {
        "usd_krw": 1300.0,
        "spy_close_usd": 468.0,
        "ticker_v0_krw": {"AAPL": 195000.0, "TSLA": 260000.0},
        "unmappable": [],
    }
    today_prices = {"AAPL": 157.5}  # TSLA missing
    today_usd_krw = 1300.0
    today_spy_usd = 482.04

    result = compute_returns(holdings, today_prices, today_usd_krw, today_spy_usd, baseline)

    # v0 must EXCLUDE TSLA -> only AAPL: 10 * 195000 = 1_950_000
    assert result["v0_krw"] == 1_950_000.0
    # v_now: only AAPL: 10 * 157.5 * 1300 = 2_047_500
    assert result["v_now_krw"] == 2_047_500.0
    # ytd_pct = (2047500/1950000 - 1)*100 = +5.0% (NOT pessimistic-biased)
    assert round(result["ytd_pct"], 2) == 5.0
    assert "TSLA" in result["excluded_tickers"]


# ---------------------------------------------------------------------------
# Task 8: compute_owner_benchmark — top-level entry point
# ---------------------------------------------------------------------------

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


def test_compute_owner_benchmark_market_data_none_returns_error(tmp_path):
    """market_data=None must not raise; should return status=error."""
    from benchmark_ytd import compute_owner_benchmark
    holdings = [{"ticker": "AAPL", "shares": 10}]
    result = compute_owner_benchmark(
        holdings=holdings, owner="me", project_dir=str(tmp_path), market_data=None,
    )
    assert result["status"] == "error"
    assert result["ytd_pct"] is None
    assert "excluded_tickers" in result
    assert "anchor_date" in result


def test_compute_owner_benchmark_missing_usd_krw_returns_error(tmp_path):
    """Missing USD_KRW in market_data._macro -> status=error, no raise."""
    from benchmark_ytd import compute_owner_benchmark
    holdings = [{"ticker": "AAPL", "shares": 10}]
    market_data = {"data": {"AAPL": {"price": 150.0}}, "_macro": {}}  # no USD_KRW

    fake_data = {"AAPL": 150.0, "KRW=X": 1300.0, "SPY": 468.0}

    def fake_fetch(symbol, date_str, use_adj_close=False):
        return fake_data.get(symbol)

    with patch("benchmark_ytd.fetch_close_on", side_effect=fake_fetch):
        result = compute_owner_benchmark(
            holdings=holdings, owner="me", project_dir=str(tmp_path), market_data=market_data,
        )
    assert result["status"] == "error"
    assert "USD/KRW" in result["error_message"]


def test_compute_owner_benchmark_error_returns_have_consistent_shape(tmp_path):
    """All error returns must include excluded_tickers and anchor_date keys (consistent with ok)."""
    from benchmark_ytd import compute_owner_benchmark
    holdings = [{"ticker": "AAPL", "shares": 10}]

    # Trigger baseline-failure error
    def fake_fetch(symbol, date_str, use_adj_close=False):
        return None

    with patch("benchmark_ytd.fetch_close_on", side_effect=fake_fetch):
        result = compute_owner_benchmark(
            holdings=holdings, owner="me", project_dir=str(tmp_path),
            market_data={"data": {}, "_macro": {"USD_KRW": 1300}},
        )

    required_keys = {"status", "error_message", "ytd_pct", "spy_ytd_pct", "alpha_pp",
                     "excluded_tickers", "anchor_date"}
    assert required_keys.issubset(result.keys()), f"missing keys: {required_keys - set(result.keys())}"


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
    assert "ytd_pct" not in snap
