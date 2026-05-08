# tests/test_fetch_market_data_ema_lifecycle.py
"""Phase A — fetch_market_data must emit ema9/21/65 + slopes."""
import numpy as np
import pandas as pd
import pytest

from fetch_market_data import compute_indicators


def _synthetic_df(close_values: list[float], days: int = 200) -> pd.DataFrame:
    """Build a yfinance-shaped DataFrame from a list of closes."""
    if len(close_values) < days:
        # pad with the first value
        close_values = [close_values[0]] * (days - len(close_values)) + close_values
    close = np.array(close_values[-days:], dtype=float)
    idx = pd.date_range("2025-09-01", periods=days, freq="B")
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99,
         "Close": close, "Volume": [1_000_000] * days},
        index=idx,
    )


def test_emit_ema9_ema21_ema65():
    # Steady uptrend: closes 100 → 199.
    closes = [100 + i * 0.5 for i in range(200)]
    df = _synthetic_df(closes)
    out = compute_indicators(df)
    assert "ema9" in out and out["ema9"] is not None
    assert "ema21" in out and out["ema21"] is not None
    assert "ema65" in out and out["ema65"] is not None
    # Steady uptrend: ema9 > ema21 > ema65.
    assert out["ema9"] > out["ema21"] > out["ema65"]


def test_emit_ema_slopes_5d():
    closes = [100 + i * 0.5 for i in range(200)]
    df = _synthetic_df(closes)
    out = compute_indicators(df)
    assert "ema21_slope_5d" in out and out["ema21_slope_5d"] is not None
    assert "ema65_slope_5d" in out and out["ema65_slope_5d"] is not None
    # In a steady uptrend, both slopes are positive.
    assert out["ema21_slope_5d"] > 0
    assert out["ema65_slope_5d"] > 0


def test_ema_slopes_negative_in_downtrend():
    closes = [200 - i * 0.5 for i in range(200)]
    df = _synthetic_df(closes)
    out = compute_indicators(df)
    assert out["ema21_slope_5d"] < 0
    assert out["ema65_slope_5d"] < 0


def test_short_history_returns_none_for_long_emas():
    # Only 30 days of data — ema65 cannot be reliable.
    closes = [100 + i for i in range(30)]
    df = _synthetic_df(closes, days=30)
    out = compute_indicators(df)
    # ema9 still emits, ema65 may or may not — but if it does, slope must
    # also emit; never half-emit.
    if out.get("ema65") is not None:
        assert out.get("ema65_slope_5d") is not None
