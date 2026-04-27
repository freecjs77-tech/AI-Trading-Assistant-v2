"""YTD benchmark vs S&P 500 (KRW) — constant-portfolio backtest anchored at 2026-01-02.

See docs/superpowers/specs/2026-04-27-ytd-benchmark-design.md for design.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Iterable

import yfinance as yf

from portfolio_data import to_yfinance_symbol, is_korean_ticker

ANCHOR_DATE = "2026-01-02"
SPY_SYMBOL = "SPY"
USDKRW_SYMBOL = "KRW=X"


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
