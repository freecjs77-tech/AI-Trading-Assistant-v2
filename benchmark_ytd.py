"""YTD benchmark vs S&P 500 (KRW) — constant-portfolio backtest anchored at 2026-01-02.

See docs/superpowers/specs/2026-04-27-ytd-benchmark-design.md for design.
"""
from __future__ import annotations

import json
import math
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
        f = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return f


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
