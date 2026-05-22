"""Tests for lifecycle_signal.compute_single_snapshot — extracted per-ticker helper."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


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


def test_compute_single_snapshot_parity_with_process_universe():
    """Same input via compute_single_snapshot and process_universe must produce identical snapshot."""
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
    assert process_snap is not None  # sanity

    helper_snap = compute_single_snapshot(
        ticker="AAA",
        market_data_entry=entry,
        market_ret_5d_pct=0.0,
        yesterday=None,
        today="2026-05-22",
    )
    assert helper_snap is not None
    # Core fields must match exactly
    assert helper_snap.get("setup") == process_snap.get("setup")
    assert helper_snap.get("trigger") == process_snap.get("trigger")
    assert helper_snap.get("decision") == process_snap.get("decision")
    assert (helper_snap.get("raw") or {}).get("close") == \
           (process_snap.get("raw") or {}).get("close")
