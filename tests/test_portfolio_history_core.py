"""portfolio_history_core 단위 테스트."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pytest

import portfolio_history_core as core


def test_constants():
    assert core.START_DATE == "2026-01-02"
    assert core.MACRO_SYMBOLS["USD_KRW"] == "USDKRW=X"
    assert core.MAX_RETRIES == 3


def test_compute_ttm_dividend_full_year():
    # 분기 4회 배당, 1년 윈도우 안에 모두 들어옴
    divs = pd.Series(
        [0.5, 0.5, 0.6, 0.6],
        index=pd.to_datetime(["2025-05-01", "2025-08-01", "2025-11-01", "2026-02-01"]),
    )
    target = pd.Timestamp("2026-04-15")
    assert core.compute_ttm_dividend(divs, target) == pytest.approx(2.2)


def test_compute_ttm_dividend_drops_old():
    # 1년 이전은 윈도우 밖
    divs = pd.Series(
        [1.0, 0.5],
        index=pd.to_datetime(["2025-01-15", "2025-06-01"]),
    )
    target = pd.Timestamp("2026-04-15")
    # 2025-01-15는 (2025-04-15, 2026-04-15] 밖, 0.5만 포함
    assert core.compute_ttm_dividend(divs, target) == pytest.approx(0.5)


def test_compute_ttm_dividend_empty():
    assert core.compute_ttm_dividend(pd.Series(dtype=float), pd.Timestamp("2026-04-15")) == 0.0


def _make_df(dates, prices):
    """Test fixture: dates와 prices로부터 Close 컬럼만 있는 DataFrame 생성."""
    return pd.DataFrame({"Close": prices}, index=pd.to_datetime(dates))


def test_price_at_picks_last_le_target():
    dfs = {"AAPL": _make_df(["2026-01-02", "2026-01-03", "2026-01-06"], [100.0, 101.0, 105.0])}
    assert core.price_at(dfs, "AAPL", pd.Timestamp("2026-01-04")) == 101.0


def test_price_at_returns_none_for_missing():
    assert core.price_at({}, "ZZZ", pd.Timestamp("2026-01-04")) is None


def test_price_at_returns_none_when_target_before_first():
    dfs = {"AAPL": _make_df(["2026-01-05"], [100.0])}
    assert core.price_at(dfs, "AAPL", pd.Timestamp("2026-01-02")) is None


def test_build_me_snapshot_uses_ttm_dividend():
    # 단순 포트폴리오: AAPL 10주 + 005930(KR) 5주
    holdings = [
        {"ticker": "AAPL", "shares": 10.0, "avg_cost": 100.0},
        {"ticker": "005930", "shares": 5.0, "avg_cost": 70000.0},
    ]
    yf_map = {"AAPL": "AAPL", "005930": "005930.KS"}
    target = pd.Timestamp("2026-04-15")
    dfs = {
        "AAPL":      _make_df(["2026-04-15"], [200.0]),
        "005930.KS": _make_df(["2026-04-15"], [80000.0]),
        "USDKRW=X":  _make_df(["2026-04-15"], [1400.0]),
        "^VIX":      _make_df(["2026-04-15"], [18.0]),
        "^TYX":      _make_df(["2026-04-15"], [4.5]),
        "QQQ":       _make_df(["2026-04-15"], [400.0]),
        "SPY":       _make_df(["2026-04-15"], [500.0]),
    }
    # AAPL: 분기 0.25 × 4 = 1.00 / 005930: 1500
    divs_map = {
        "AAPL": pd.Series(
            [0.25, 0.25, 0.25, 0.25],
            index=pd.to_datetime(["2025-05-01", "2025-08-01", "2025-11-01", "2026-02-01"]),
        ),
        "005930": pd.Series([1500.0], index=pd.to_datetime(["2025-12-01"])),
    }
    snap = core.build_me_snapshot(target, holdings, yf_map, dfs, divs_map)
    # AAPL: 1.00 × 10 × 1400 = 14000, 005930: 1500 × 5 = 7500 → 합 21500
    assert snap["div_annual_krw"] == 21500
    # total_value: AAPL 10×200×1400 + 005930 5×80000 = 2,800,000 + 400,000 = 3,200,000
    assert snap["total_value_krw"] == 3_200_000
    assert snap["div_yield"] == round(21500 / 3_200_000 * 100, 2)
    assert snap["usd_krw"] == 1400.0


def test_build_wife_snapshot_uses_ttm_dividend():
    # wife HOLDINGS 형식: (ticker, shares, avg_cost_krw)
    wife_holdings = [
        ("AAPL",   10.0,  150_000.0),  # avg_cost는 KRW 기반 (이미 환산된 매입원가)
        ("005930", 20.0,   75_000.0),
    ]
    usd_tickers = {"AAPL"}
    yf_map = {"AAPL": "AAPL", "005930": "005930.KS"}
    target = pd.Timestamp("2026-04-15")
    dfs = {
        "AAPL":      _make_df(["2026-04-15"], [200.0]),
        "005930.KS": _make_df(["2026-04-15"], [80000.0]),
        "USDKRW=X":  _make_df(["2026-04-15"], [1400.0]),
    }
    divs_map = {
        "AAPL": pd.Series([0.25] * 4, index=pd.to_datetime(
            ["2025-05-01", "2025-08-01", "2025-11-01", "2026-02-01"])),
        "005930": pd.Series([1500.0], index=pd.to_datetime(["2025-12-01"])),
    }
    snap = core.build_wife_snapshot(target, wife_holdings, usd_tickers, yf_map, dfs, divs_map)
    # AAPL value: 10×200×1400 = 2,800,000  / 005930 value: 20×80000 = 1,600,000 → 4,400,000
    assert snap["total_value_krw"] == 4_400_000
    # Dividend: AAPL 1.00×10×1400=14,000 / 005930 1500×20=30,000 → 44,000
    assert snap["div_annual_krw"] == 44_000
    assert snap["div_yield"] == round(44_000 / 4_400_000 * 100, 2)


def test_trading_dates_from_filters_by_start():
    df = _make_df(
        ["2025-12-30", "2026-01-02", "2026-01-03", "2026-01-06"],
        [400, 410, 411, 412],
    )
    idx = core.trading_dates_from(df, "2026-01-02")
    assert len(idx) == 3
    assert idx[0] == pd.Timestamp("2026-01-02")
