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


def test_build_kr_universe_unions_with_sector_etfs():
    """KR universe = KODEX 200 ∪ KOSDAQ 150 ∪ 섹터 ETF holdings ∪ daily_movers."""
    tmp = setup()
    try:
        md.save_cache("krx_etf_069500_holdings", ["005930.KS", "000660.KS"], status="ok")
        md.save_cache("krx_etf_229200_holdings", ["196170.KQ"], status="ok")
        md.save_cache("weekly_liquidity_kr", [], status="ok")
        with patch("momentum_universe.md.get_kr_sector_holdings",
                   return_value={"091160.KS": ["042700.KS"]}), \
             patch("momentum_universe.fetch_daily_movers_for", return_value=[]):
            uni = mu.build_kr_universe()
        assert "005930.KS" in uni
        assert "000660.KS" in uni
        assert "196170.KQ" in uni
        assert "042700.KS" in uni
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


def test_kr_universe_auto_fetches_sector_holdings_on_cache_miss():
    """sector_etf_holdings_kr cache 없을 때 get_kr_sector_holdings 호출."""
    tmp = setup()
    try:
        md.save_cache("krx_etf_069500_holdings", ["005930.KS"], status="ok")
        md.save_cache("krx_etf_229200_holdings", [], status="ok")
        md.save_cache("weekly_liquidity_kr", [], status="ok")
        # NO sector_etf_holdings_kr cache pre-saved
        with patch("momentum_universe.md.get_kr_sector_holdings",
                   return_value={"091160.KS": ["042700.KS"]}) as mock_sec, \
             patch("momentum_universe.fetch_daily_movers_for", return_value=[]):
            uni = mu.build_kr_universe()
        assert mock_sec.called, "should fetch sector holdings"
        assert "042700.KS" in uni
    finally:
        teardown(tmp)


if __name__ == "__main__":
    test_build_us_universe_unions_sources()
    test_build_us_universe_caps_at_1500()
    test_build_kr_universe_unions_with_sector_etfs()
    test_build_us_universe_dedup_preserves_order()
    test_kr_movers_drops_all_when_volumes_empty()
    test_kr_universe_auto_fetches_sector_holdings_on_cache_miss()
    print("[OK] momentum_universe tests passed.")
