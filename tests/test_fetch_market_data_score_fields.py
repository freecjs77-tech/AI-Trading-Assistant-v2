# tests/test_fetch_market_data_score_fields.py
"""Score_v1 — new fields emitted by compute_indicators."""
import numpy as np
import pandas as pd

from fetch_market_data import compute_indicators


def _make_df(days: int = 60, seed: int = 42):
    """Synthetic OHLCV with a mild uptrend and reasonable noise."""
    rng = np.random.default_rng(seed)
    base = np.linspace(100, 120, days)
    noise = rng.normal(0, 1.5, days)
    close = base + noise
    open_ = close - rng.normal(0, 0.5, days)
    high = np.maximum(close, open_) + np.abs(rng.normal(0.5, 0.3, days))
    low = np.minimum(close, open_) - np.abs(rng.normal(0.5, 0.3, days))
    volume = rng.integers(800_000, 1_200_000, days)
    dates = pd.date_range("2026-01-01", periods=days, freq="B")
    return pd.DataFrame({
        "Open": open_, "High": high, "Low": low,
        "Close": close, "Volume": volume,
    }, index=dates)


def test_open_field_emitted():
    df = _make_df()
    r = compute_indicators(df)
    assert "open" in r
    assert isinstance(r["open"], float)
    assert r["open"] > 0


def test_high_20d_prior_excludes_today():
    df = _make_df()
    r = compute_indicators(df)
    assert "high_20d_prior" in r
    # high_20d_prior should equal max of high[-21:-1]
    expected = round(float(df["High"].iloc[-21:-1].max()), 2)
    assert r["high_20d_prior"] == expected


def test_high_20d_prior_excludes_today_strictly():
    """If today is a new high, high_20d_prior should be lower than today's high."""
    df = _make_df()
    df.loc[df.index[-1], "High"] = 999.0
    r = compute_indicators(df)
    assert r["high_20d_prior"] is not None
    assert r["high_20d_prior"] < 999.0


def test_atr_5d_20d_avg_emitted():
    df = _make_df()
    r = compute_indicators(df)
    assert r["atr14_pct_5d_avg"] is not None
    assert r["atr14_pct_20d_avg"] is not None
    assert r["atr14_pct_5d_avg"] > 0
    assert r["atr14_pct_20d_avg"] > 0


def test_volume_5d_20d_avg_emitted():
    df = _make_df()
    r = compute_indicators(df)
    assert r["volume_5d_avg"] is not None
    assert r["volume_20d_avg"] is not None
    assert r["volume_5d_avg"] > 0


def test_days_sideways_present_and_non_negative():
    df = _make_df()
    r = compute_indicators(df)
    assert "days_sideways" in r
    assert r["days_sideways"] >= 0


def test_short_history_short_circuits():
    """Less than 20 days of data — averages may be None but no crash."""
    df = _make_df(days=10)
    r = compute_indicators(df)
    # Function should not raise. Some averages will be None.
    assert "open" in r
    assert r.get("atr14_pct_20d_avg") is None or r.get("atr14_pct_20d_avg") > 0
