# market_benchmark.py
"""Market benchmark fetch + cache for score_v1 rs_strong component.

Per spec §8.2:
  - Fetched ONCE per pipeline run per market (not per ticker)
  - Cached to history/market_benchmark_cache.json
  - On fetch failure: reuse last cached value if age <= 3 calendar days
  - Beyond cache: rs_strong = False for all tickers in that market this run
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Optional

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from lifecycle_score_config import (
    MARKET_BENCHMARK_CACHE_MAX_AGE_DAYS,
    US_BENCHMARK_TICKER, KR_BENCHMARK_TICKER,
)

CACHE_FILE = "market_benchmark_cache.json"


def _market_to_ticker(market: str) -> str:
    if market == "US":
        return US_BENCHMARK_TICKER
    if market == "KR":
        return KR_BENCHMARK_TICKER
    raise ValueError(f"Unknown market: {market!r}")


def _load_cache(cache_path: str) -> dict:
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, "rb") as f:
            return json.loads(f.read().decode("utf-8"))
    except Exception as e:
        print(f"[market_benchmark] WARN cache load failed ({e}); ignoring cache")
        return {}


def _save_cache(cache_path: str, cache: dict) -> None:
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
    tmp = cache_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    os.replace(tmp, cache_path)


def _fetch_live_ret_5d(ticker: str) -> Optional[float]:
    """Fetch 5-day percent return via existing fetch_ticker. Returns None on failure."""
    try:
        from fetch_market_data import fetch_ticker
        row = fetch_ticker(ticker)
        if not row or "error" in row:
            return None
        # fetch_market_data emits change_5d_pct (not ret_5d_pct).
        ret = row.get("change_5d_pct")
        if ret is None:
            return None
        return float(ret)
    except Exception as e:
        print(f"[market_benchmark] WARN live fetch failed for {ticker}: {e}")
        return None


def _is_fresh(cached_at_str: str, max_age_days: int) -> bool:
    try:
        cached_at = datetime.strptime(cached_at_str, "%Y-%m-%dT%H:%M:%S")
        age = (datetime.now() - cached_at).days
        return age <= max_age_days
    except (ValueError, TypeError):
        return False


def get_market_ret_5d(market: str, *, project_dir: str,
                      cache_path: Optional[str] = None) -> Optional[float]:
    """Return market 5d % return. Live fetch with cache fallback.

    Args:
        market: "US" or "KR"
        project_dir: project root (used to find history/market_benchmark_cache.json)
        cache_path: explicit override (used by tests)

    Returns:
        float | None: 5-day % return, or None if both live and cache fail.
    """
    if cache_path is None:
        cache_path = os.path.join(project_dir, "history", CACHE_FILE)

    cache = _load_cache(cache_path)
    ticker = _market_to_ticker(market)

    live = _fetch_live_ret_5d(ticker)
    if live is not None:
        cache[market] = {
            "value":     live,
            "cached_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "ticker":    ticker,
        }
        _save_cache(cache_path, cache)
        return live

    # Live fetch failed — try cache fallback
    cached = cache.get(market)
    if cached and _is_fresh(cached.get("cached_at", ""),
                            MARKET_BENCHMARK_CACHE_MAX_AGE_DAYS):
        print(f"[market_benchmark] live fetch failed for {ticker}; "
              f"using cached value from {cached['cached_at']}")
        return float(cached["value"])

    print(f"[market_benchmark] WARN no fresh benchmark for {market}; "
          f"rs_strong will be False for all tickers in this market")
    return None
