"""fetch_market_data의 change_5d_pct / change_20d_pct 안전장치 검증."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pandas as pd
import numpy as np


def test_close_series_with_5_and_20_day_returns_present():
    """충분한 데이터(>= 21일) → change_5d_pct, change_20d_pct 둘 다 산출."""
    from fetch_market_data import _compute_returns
    close = pd.Series([100.0] * 25 + [110.0])  # 26일, 마지막 110
    out = _compute_returns(close)
    assert out["change_5d_pct"] is not None
    assert out["change_20d_pct"] is not None
    # 모두 100→110이므로 +10%
    assert abs(out["change_5d_pct"] - 10.0) < 0.01
    assert abs(out["change_20d_pct"] - 10.0) < 0.01


def test_short_series_returns_none():
    """짧은 데이터 → None."""
    from fetch_market_data import _compute_returns
    close = pd.Series([100.0, 105.0])  # 2일
    out = _compute_returns(close)
    assert out["change_5d_pct"] is None
    assert out["change_20d_pct"] is None


def test_zero_denominator_returns_none():
    """20일 전 종가가 0이면 None (ZeroDivision 방어)."""
    from fetch_market_data import _compute_returns
    close = pd.Series([100.0] * 5 + [0.0] + [100.0] * 20)  # index -21이 0
    out = _compute_returns(close)
    assert out["change_20d_pct"] is None


def test_nan_denominator_returns_none():
    """6일 전 종가가 NaN이면 None."""
    from fetch_market_data import _compute_returns
    vals = [100.0] * 26
    vals[-6] = float("nan")
    close = pd.Series(vals)
    out = _compute_returns(close)
    assert out["change_5d_pct"] is None


if __name__ == "__main__":
    test_close_series_with_5_and_20_day_returns_present()
    test_short_series_returns_none()
    test_zero_denominator_returns_none()
    test_nan_denominator_returns_none()
    print("[OK] change field safety tests passed.")
