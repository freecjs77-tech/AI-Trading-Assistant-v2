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
