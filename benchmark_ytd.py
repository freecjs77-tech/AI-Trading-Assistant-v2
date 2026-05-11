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
          "dit_ytd_pct": float | None,
          "rest_ytd_pct": float | None,
          "dit_v0_krw": float | None,
          "dit_now_krw": float | None,
          "rest_v0_krw": float | None,
          "rest_now_krw": float | None,
        }

    ytd_pct/alpha_pp are None when v0 == 0 (all holdings unmappable).

    Exclusion symmetry: any ticker excluded from v_now (e.g., missing today price)
    is ALSO excluded from v0, so the v_now/v0 ratio is mathematically valid.
    """
    # First pass: compute v_now to discover the full exclusion set
    v_now_krw, exc_now = compute_v_now_total_krw(holdings, today_prices, today_usd_krw, baseline)

    # Re-derive baseline with v_now's exclusions added to unmappable, then compute v0.
    # This guarantees v0 uses the same ticker set as v_now.
    sym_baseline = dict(baseline)
    sym_baseline["unmappable"] = list(set(baseline.get("unmappable", [])) | set(exc_now))
    v0_krw, exc_v0 = compute_v0_total_krw(holdings, sym_baseline)

    excluded = sorted(set(exc_now) | set(exc_v0))

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

    decomp = compute_dit_rest_decomposition(
        holdings, today_prices, today_usd_krw, sym_baseline, v0_krw, v_now_krw
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

    110990 is statically KOSDAQ → KRW native, so no USD/KRW multiplication
    is applied to its prices.

    Args:
        holdings: list of {ticker, shares, ...} dicts. Used to find DIT shares.
        today_prices: {ticker: price} dict. Used to fetch today's DIT price (KRW).
        today_usd_krw: Unused in this function (110990 is KOSDAQ → KRW native).
            Kept in signature for call-site symmetry with compute_returns()
            so both callers pass the same argument set.
        baseline: anchor baseline dict with "ticker_v0_krw" key.
        v0_krw: pre-computed portfolio v0 (total) from compute_v0_total_krw.
        v_now_krw: pre-computed portfolio v_now (total).

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
    if dit_v0_per_share <= 0:
        return none_result  # corrupted baseline — bail

    dit_now_per_share = float(dit_today_price)  # KRW native (KOSDAQ — no FX)
    dit_v0_krw_val = dit_shares * dit_v0_per_share
    dit_now_krw_val = dit_shares * dit_now_per_share
    dit_ytd_pct = (dit_now_per_share / dit_v0_per_share - 1.0) * 100.0

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
    if not isinstance(market_data, dict):
        return {
            "status": "error",
            "error_message": f"market_data must be a dict, got {type(market_data).__name__}",
            "ytd_pct": None,
            "spy_ytd_pct": None,
            "alpha_pp": None,
            "excluded_tickers": [],
            "anchor_date": None,
        }

    try:
        baseline = load_or_build_baseline(holdings, owner, project_dir)
    except Exception as e:
        return {
            "status": "error",
            "error_message": f"baseline build failed: {e}",
            "ytd_pct": None,
            "spy_ytd_pct": None,
            "alpha_pp": None,
            "excluded_tickers": [],
            "anchor_date": None,
        }

    today_usd_krw = (market_data.get("_macro") or {}).get("USD_KRW") or 0
    if today_usd_krw <= 0:
        return {
            "status": "error",
            "error_message": "today USD/KRW unavailable in market_data",
            "ytd_pct": None,
            "spy_ytd_pct": None,
            "alpha_pp": None,
            "excluded_tickers": [],
            "anchor_date": None,
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
                "excluded_tickers": [],
                "anchor_date": None,
            }

    try:
        result = compute_returns(holdings, today_prices, today_usd_krw, today_spy_usd, baseline)
    except Exception as e:
        return {
            "status": "error",
            "error_message": f"compute_returns failed: {e}",
            "ytd_pct": None,
            "spy_ytd_pct": None,
            "alpha_pp": None,
            "excluded_tickers": [],
            "anchor_date": None,
        }
    result["status"] = "ok"
    result["anchor_date"] = baseline["anchor_date"]
    return result
