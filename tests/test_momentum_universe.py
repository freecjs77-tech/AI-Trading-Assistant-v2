"""Universe 조립 테스트 — 합집합 + 1500개 cap 검증."""
import sys, os, tempfile, shutil
from unittest.mock import patch
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import momentum_data as md
import momentum_universe as mu


def setup():
    tmp = tempfile.mkdtemp(prefix="universe_test_")
    md.set_data_dir(tmp)
    return tmp


def teardown(tmp):
    shutil.rmtree(tmp, ignore_errors=True)


def test_build_us_universe_unions_sources():
    """US universe = IWB ∪ weekly_top100 ∪ daily_movers."""
    tmp = setup()
    try:
        md.save_cache("iwb_holdings", ["AAPL", "MSFT", "NVDA"], status="ok")
        md.save_cache("weekly_liquidity_us", ["TSLA"], status="ok")
        with patch("momentum_universe.fetch_daily_movers_for", return_value=["AMD"]):
            uni = mu.build_us_universe()
        assert set(uni) == {"AAPL", "MSFT", "NVDA", "TSLA", "AMD"}
    finally:
        teardown(tmp)


def test_build_us_universe_caps_at_1500():
    """V1.0 안전장치 — universe 1500개 초과 절대 금지."""
    tmp = setup()
    try:
        big = [f"T{i}" for i in range(2000)]
        md.save_cache("iwb_holdings", big, status="ok")
        md.save_cache("weekly_liquidity_us", [], status="ok")
        with patch("momentum_universe.fetch_daily_movers_for", return_value=[]):
            uni = mu.build_us_universe()
        assert len(uni) <= 1500
    finally:
        teardown(tmp)


def test_build_kr_universe_uses_kospi_tickers():
    """KR universe = KOSPI_TICKERS (from market_scanner) + movers.
    KRX public API requires auth since 2025 — static list is the base."""
    tmp = setup()
    try:
        fake_kospi = ["005930.KS", "000660.KS", "035720.KS"]
        with patch("market_scanner.KOSPI_TICKERS", fake_kospi), \
             patch("momentum_universe.fetch_daily_movers_for", return_value=[]):
            md.save_cache("weekly_liquidity_kr", [], status="ok")
            uni = mu.build_kr_universe()
        assert "005930.KS" in uni
        assert "000660.KS" in uni
        assert "035720.KS" in uni
    finally:
        teardown(tmp)


def test_build_us_universe_dedup_preserves_order():
    """중복 제거되지만 IWB가 먼저 등장한 순서를 유지."""
    tmp = setup()
    try:
        md.save_cache("iwb_holdings", ["AAPL", "MSFT"], status="ok")
        md.save_cache("weekly_liquidity_us", ["MSFT", "TSLA"], status="ok")
        with patch("momentum_universe.fetch_daily_movers_for", return_value=["AAPL"]):
            uni = mu.build_us_universe()
        assert uni.index("AAPL") < uni.index("MSFT") < uni.index("TSLA")
        assert uni.count("AAPL") == 1
        assert uni.count("MSFT") == 1
    finally:
        teardown(tmp)


def test_kr_movers_drops_all_when_volumes_empty():
    """KR daily movers — volumes.empty 시 잡주 leak 방지 위해 모두 제외."""
    import pandas as pd
    tmp = setup()
    try:
        closes = pd.DataFrame({
            "005930.KS": [100] * 25 + [110],  # 1d +10% → 통과 후보
        })
        empty_vol = pd.DataFrame()
        with patch("momentum_universe.md.fetch_yf_bulk",
                   return_value=(closes, empty_vol)):
            result = mu.fetch_daily_movers_for(["005930.KS"], market="kr")
        assert result == [], f"KR with empty volumes should drop all, got {result}"
    finally:
        teardown(tmp)


def test_build_kr_universe_no_krx_api_calls():
    """KRX API (get_krx_etf_holdings, get_kr_sector_holdings) must NOT be called.
    KR universe is built entirely from the static KOSPI_TICKERS list."""
    tmp = setup()
    try:
        fake_kospi = ["005930.KS", "000660.KS"]
        with patch("market_scanner.KOSPI_TICKERS", fake_kospi), \
             patch("momentum_universe.fetch_daily_movers_for", return_value=[]), \
             patch("momentum_universe.md.get_krx_etf_holdings",
                   side_effect=AssertionError("KRX API must not be called")) as mock_krx, \
             patch("momentum_universe.md.get_kr_sector_holdings",
                   side_effect=AssertionError("KRX sector API must not be called")) as mock_sec:
            md.save_cache("weekly_liquidity_kr", [], status="ok")
            uni = mu.build_kr_universe()
        assert not mock_krx.called, "get_krx_etf_holdings must not be called"
        assert not mock_sec.called, "get_kr_sector_holdings must not be called"
        assert set(uni) == {"005930.KS", "000660.KS"}
    finally:
        teardown(tmp)


if __name__ == "__main__":
    test_build_us_universe_unions_sources()
    test_build_us_universe_caps_at_1500()
    test_build_kr_universe_uses_kospi_tickers()
    test_build_us_universe_dedup_preserves_order()
    test_kr_movers_drops_all_when_volumes_empty()
    test_build_kr_universe_no_krx_api_calls()
    print("[OK] momentum_universe tests passed.")
