# tests/test_market_benchmark.py
"""market_benchmark — cache hit/miss/staleness/fallback behaviour."""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

import market_benchmark as mb


@pytest.fixture
def tmp_cache_path(tmp_path):
    return str(tmp_path / "market_benchmark_cache.json")


def _write_cache(path: str, market: str, value: float, age_days: int):
    cached_at = (datetime.now() - timedelta(days=age_days)).strftime("%Y-%m-%dT%H:%M:%S")
    data = {market: {"value": value, "cached_at": cached_at, "ticker": "SPY"}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def test_live_fetch_success_writes_cache(tmp_cache_path, tmp_path):
    with patch.object(mb, "_fetch_live_ret_5d", return_value=2.5):
        ret = mb.get_market_ret_5d("US", project_dir=str(tmp_path), cache_path=tmp_cache_path)
    assert ret == 2.5
    assert os.path.exists(tmp_cache_path)
    with open(tmp_cache_path) as f:
        cache = json.load(f)
    assert cache["US"]["value"] == 2.5


def test_live_fetch_failure_uses_fresh_cache(tmp_cache_path, tmp_path):
    _write_cache(tmp_cache_path, "US", value=1.8, age_days=1)
    with patch.object(mb, "_fetch_live_ret_5d", return_value=None):
        ret = mb.get_market_ret_5d("US", project_dir=str(tmp_path), cache_path=tmp_cache_path)
    assert ret == 1.8


def test_live_fetch_failure_rejects_stale_cache(tmp_cache_path, tmp_path):
    _write_cache(tmp_cache_path, "US", value=1.8, age_days=5)  # > 3 day max age
    with patch.object(mb, "_fetch_live_ret_5d", return_value=None):
        ret = mb.get_market_ret_5d("US", project_dir=str(tmp_path), cache_path=tmp_cache_path)
    assert ret is None


def test_unknown_market_raises(tmp_cache_path, tmp_path):
    with pytest.raises(ValueError, match="Unknown market"):
        mb.get_market_ret_5d("JP", project_dir=str(tmp_path), cache_path=tmp_cache_path)


def test_no_cache_no_live_returns_none(tmp_cache_path, tmp_path):
    with patch.object(mb, "_fetch_live_ret_5d", return_value=None):
        ret = mb.get_market_ret_5d("US", project_dir=str(tmp_path), cache_path=tmp_cache_path)
    assert ret is None


def test_kr_uses_kospi_etf_ticker():
    """KR benchmark should target KS200 ETF, not SPY."""
    assert mb._market_to_ticker("KR") == "069500.KS"
    assert mb._market_to_ticker("US") == "SPY"
