"""Tests for lifecycle_signal.compute_single_snapshot — extracted per-ticker helper."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


def _minimal_market_entry():
    """Build a market_data entry sufficient for a TREND_OK setup."""
    return {
        "ticker":         "AAA",
        "close":          110.0,
        "high":           111.0,
        "low":            108.0,
        "ema9":           105.0,
        "ema21":          100.0,
        "ema65":          95.0,
        "ema9_slope_3d":  0.5,
        "ema21_slope_5d": 0.3,
        "ema65_slope_20d": 0.2,
        "rsi14":          65.0,
        "atr14":          2.5,
        "atr14_pct":      2.27,
        "volume_ratio":   1.1,
        "macd":           1.0,
        "macd_signal":    0.5,
        "macd_hist":      0.5,
        "ret_5d_pct":     5.0,
        "ret_20d_pct":    10.0,
        "change_pct":     1.2,
        "ret_3d_pct":     3.0,
        "dist_ema9_pct":  4.76,
    }


def test_compute_single_snapshot_returns_snapshot_for_valid_input():
    """Valid market_data → snapshot dict with setup/trigger/decision."""
    from lifecycle_signal import compute_single_snapshot
    snap = compute_single_snapshot(
        ticker="AAA",
        market_data_entry=_minimal_market_entry(),
        market_ret_5d_pct=0.0,
        yesterday=None,
        today="2026-05-22",
    )
    assert snap is not None
    assert "setup" in snap
    assert "trigger" in snap or "trigger_state" in snap
    assert "decision" in snap
    assert snap.get("raw", {}).get("close") == 110.0


def test_compute_single_snapshot_returns_none_for_missing_close():
    """close=None → None (mirrors process_universe skip behavior)."""
    from lifecycle_signal import compute_single_snapshot
    entry = _minimal_market_entry()
    entry["close"] = None
    snap = compute_single_snapshot(
        ticker="AAA",
        market_data_entry=entry,
        market_ret_5d_pct=0.0,
        yesterday=None,
        today="2026-05-22",
    )
    assert snap is None


def test_compute_single_snapshot_returns_none_for_missing_ema9():
    """ema9=None → None."""
    from lifecycle_signal import compute_single_snapshot
    entry = _minimal_market_entry()
    entry["ema9"] = None
    snap = compute_single_snapshot(
        ticker="AAA",
        market_data_entry=entry,
        market_ret_5d_pct=0.0,
        yesterday=None,
        today="2026-05-22",
    )
    assert snap is None


def test_compute_single_snapshot_returns_none_for_error_entry():
    """{'error': ...} → None."""
    from lifecycle_signal import compute_single_snapshot
    snap = compute_single_snapshot(
        ticker="AAA",
        market_data_entry={"error": "fetch failed"},
        market_ret_5d_pct=0.0,
        yesterday=None,
        today="2026-05-22",
    )
    assert snap is None


def test_compute_single_snapshot_yesterday_none_safe():
    """yesterday=None must NOT crash inside _is_early_trigger.

    Previously _is_early_trigger called yesterday.get(...) — would AttributeError on None.
    The helper must pass an empty dict (or None-safe equivalent) internally.
    """
    from lifecycle_signal import compute_single_snapshot
    snap = compute_single_snapshot(
        ticker="AAA",
        market_data_entry=_minimal_market_entry(),
        market_ret_5d_pct=0.0,
        yesterday=None,
        today="2026-05-22",
    )
    assert snap is not None
    # With no yesterday, trigger cannot fire — should be WAIT.
    assert snap.get("trigger") == "WAIT" or snap.get("trigger_state") == "WAIT"


@pytest.mark.parametrize("engine_mode", ["legacy", "score_shadow", "score_active"])
def test_compute_single_snapshot_parity_with_process_universe(monkeypatch, engine_mode):
    """Same input via compute_single_snapshot and process_universe must produce
    identical snapshot — verified across all three LIFECYCLE_ENGINE_MODE values.
    """
    monkeypatch.setenv("LIFECYCLE_ENGINE_MODE", engine_mode)
    from lifecycle_signal import compute_single_snapshot, process_universe

    entry = _minimal_market_entry()
    market_data = {"data": {"AAA": entry}}
    yesterday_state = {"tickers": {}}

    proc_result = process_universe(
        active_set={"AAA"},
        market_data=market_data,
        yesterday_state=yesterday_state,
        today="2026-05-22",
        market_ret_5d_pct=0.0,
    )
    process_snap = proc_result["snapshots"].get("AAA")
    assert process_snap is not None

    helper_snap = compute_single_snapshot(
        ticker="AAA",
        market_data_entry=entry,
        market_ret_5d_pct=0.0,
        yesterday=None,
        today="2026-05-22",
    )
    assert helper_snap is not None
    assert helper_snap == process_snap, (
        f"snapshot diverges (mode={engine_mode}):\n"
        f"  helper={helper_snap}\n"
        f"  process={process_snap}"
    )


@pytest.mark.parametrize("engine_mode", ["legacy", "score_shadow", "score_active"])
def test_compute_single_snapshot_parity_with_3day_yesterday_window(monkeypatch, engine_mode):
    """When yesterday_state has 3+ snapshots, process_universe passes them via
    _y_snap_list_for_drift. The helper must produce identical snapshot when called
    with the same yesterday list — this is the byte-equivalence linchpin for
    drift's tight_close_cluster feature.
    """
    monkeypatch.setenv("LIFECYCLE_ENGINE_MODE", engine_mode)
    from lifecycle_signal import compute_single_snapshot, process_universe

    entry = _minimal_market_entry()
    market_data = {"data": {"AAA": entry}}

    # Build yesterday_state with 3 prior snapshots, each carrying raw.close
    def _snap(date_str, close):
        return {"date": date_str, "setup": "TREND_OK",
                "raw": {"close": close, "ema9": 105, "high": close + 1.0,
                        "low": close - 1.0}}
    y_snap_list = [
        _snap("2026-05-19", 109.0),
        _snap("2026-05-20", 109.5),
        _snap("2026-05-21", 110.0),
    ]
    yesterday_state = {"tickers": {"AAA": {"snapshots": y_snap_list}}}

    proc_result = process_universe(
        active_set={"AAA"},
        market_data=market_data,
        yesterday_state=yesterday_state,
        today="2026-05-22",
        market_ret_5d_pct=0.0,
    )
    process_snap = proc_result["snapshots"]["AAA"]

    helper_snap = compute_single_snapshot(
        ticker="AAA",
        market_data_entry=entry,
        market_ret_5d_pct=0.0,
        yesterday=y_snap_list[-1],
        today="2026-05-22",
        _y_snap_list_for_drift=y_snap_list,
    )
    assert helper_snap == process_snap, (
        f"snapshot diverges (mode={engine_mode}):\n"
        f"  helper={helper_snap}\n"
        f"  process={process_snap}"
    )
