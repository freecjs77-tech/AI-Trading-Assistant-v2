"""fetch_market_data.calc_atr smoke test (no yfinance call)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import numpy as np
from fetch_market_data import calc_atr


def test_calc_atr_basic():
    """간단한 OHLC로 ATR 14 계산 — 양수, 마지막 값 not NaN."""
    n = 30
    high = pd.Series([100 + i + (i % 3) for i in range(n)], dtype=float)
    low  = pd.Series([99  + i - (i % 3) for i in range(n)], dtype=float)
    close= pd.Series([100 + i           for i in range(n)], dtype=float)
    atr = calc_atr(high, low, close, period=14)
    last = float(atr.iloc[-1])
    assert last > 0
    assert not np.isnan(last)


def test_calc_atr_short_series_nan_safe():
    """기간보다 짧은 시리즈 — 마지막 값 NaN이어도 raise 없어야 함."""
    high = pd.Series([100, 101, 102], dtype=float)
    low  = pd.Series([99, 100, 101], dtype=float)
    close= pd.Series([100, 101, 102], dtype=float)
    atr = calc_atr(high, low, close, period=14)
    # 14일치 미만이면 마지막 값 NaN — 호출은 성공해야
    assert len(atr) == 3


if __name__ == "__main__":
    test_calc_atr_basic()
    test_calc_atr_short_series_nan_safe()
    print("[OK] calc_atr tests passed.")
