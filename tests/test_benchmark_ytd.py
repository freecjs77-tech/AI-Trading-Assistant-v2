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
