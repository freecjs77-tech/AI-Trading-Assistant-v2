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
