# tests/test_benchmark_pipeline_integration.py
"""Integration: portfolio_daily.json gains ytd_pct/spy_ytd_pct/alpha_pp after pipeline."""
import json
import os
import sys
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mock_yf_for(symbol_to_close: dict):
    """Build a yf.Ticker mock factory keyed by symbol → close value."""
    def _factory(symbol):
        m = MagicMock()
        if symbol in symbol_to_close:
            df = pd.DataFrame(
                {"Close": [symbol_to_close[symbol]], "Adj Close": [symbol_to_close[symbol]]},
                index=pd.to_datetime(["2026-01-02"]),
            )
        else:
            df = pd.DataFrame()
        m.history.return_value = df
        return m
    return _factory


def test_compute_owner_benchmark_persists_to_baseline_cache(tmp_path):
    """Calling compute_owner_benchmark twice in a row → cache reused (no second build)."""
    from benchmark_ytd import compute_owner_benchmark

    holdings = [{"ticker": "AAPL", "shares": 10}]
    market_data = {"data": {"AAPL": {"price": 157.5}, "SPY": {"price": 482.04}}, "_macro": {"USD_KRW": 1300.0}}

    fake = {"AAPL": 150.0, "KRW=X": 1300.0, "SPY": 468.0}
    call_log = []

    def tracked_fetch(symbol, date_str, use_adj_close=False):
        call_log.append((symbol, date_str))
        if symbol == "SPY" and date_str != "2026-01-02":
            return 482.04  # today
        return fake.get(symbol)

    with patch("benchmark_ytd.fetch_close_on", side_effect=tracked_fetch):
        r1 = compute_owner_benchmark(holdings, "me", str(tmp_path), market_data)
        first_calls = list(call_log)
        r2 = compute_owner_benchmark(holdings, "me", str(tmp_path), market_data)
        second_calls = call_log[len(first_calls):]

    assert r1["status"] == "ok"
    assert r2["status"] == "ok"
    # Second call should fetch only today SPY (Jan 2 prices come from cache)
    second_symbols = [s for s, d in second_calls]
    assert "AAPL" not in second_symbols
    assert "KRW=X" not in second_symbols


def test_save_portfolio_snapshot_with_benchmark_full_round_trip(tmp_path):
    """End-to-end: compute benchmark, save snapshot, reload, ytd fields present."""
    from benchmark_ytd import compute_owner_benchmark
    from history_manager import save_portfolio_snapshot, load_portfolio_daily

    holdings = [{"ticker": "AAPL", "shares": 10}]
    market_data = {"data": {"AAPL": {"price": 157.5}}, "_macro": {"USD_KRW": 1300.0}}

    def fake_fetch(symbol, date_str, use_adj_close=False):
        if symbol == "SPY":
            return 468.0 if date_str == "2026-01-02" else 482.04
        return {"AAPL": 150.0, "KRW=X": 1300.0}.get(symbol)

    with patch("benchmark_ytd.fetch_close_on", side_effect=fake_fetch):
        bm = compute_owner_benchmark(holdings, "me", str(tmp_path), market_data)

    assert bm["status"] == "ok"

    daily_path = str(tmp_path / "history" / "portfolio_daily.json")
    save_portfolio_snapshot(
        path=daily_path, date_str="2026-04-27",
        total_value_krw=bm["v_now_krw"], cost_basis_krw=1_900_000.0,
        cash_value_krw=0, cash_pct=0,
        div_annual_krw=0, div_yield=0, usd_krw=1300.0,
        vix=20.0, yield_30y=4.5, master_switch="GREEN",
        holdings_count=1, weights_by_category={}, weights_by_ticker={},
        ytd_pct=bm["ytd_pct"], spy_ytd_pct=bm["spy_ytd_pct"], alpha_pp=bm["alpha_pp"],
        v0_krw=bm["v0_krw"], spy_v0_krw=bm["spy_v0_krw"],
    )

    daily = load_portfolio_daily(daily_path)
    snap = daily["2026-04-27"]
    assert "ytd_pct" in snap
    assert "spy_ytd_pct" in snap
    assert "alpha_pp" in snap
    assert "v0_krw" in snap
    assert round(snap["ytd_pct"], 2) == 5.0
    assert round(snap["spy_ytd_pct"], 2) == 3.0
    assert round(snap["alpha_pp"], 2) == 2.0
