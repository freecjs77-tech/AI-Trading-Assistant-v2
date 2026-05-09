"""Phase A — end-to-end smoke through process_universe + render."""
import json
import os
from pathlib import Path

from lifecycle_signal import run_lifecycle


def _market_data():
    """Two synthetic tickers — one TREND_OK, one BROKEN."""
    return {
        "_meta": {"date": "2026-05-08", "is_trading_day": True},
        "data": {
            "FAKE_OK": {
                "price": 100.0, "high": 101, "low": 99, "prev_close": 99,
                "ema9": 99.5, "ema21": 98, "ema65": 90,
                "ema21_slope_5d": 0.5, "ema65_slope_5d": 0.4,
                "rsi14": 60, "atr14_pct": 2.0, "volume_ratio": 1.0,
                "change_pct": 1.0, "sector": "Technology",
            },
            "FAKE_BAD": {
                "price": 80.0, "high": 82, "low": 79, "prev_close": 81,
                "ema9": 90, "ema21": 95, "ema65": 100,
                "ema21_slope_5d": -0.5, "ema65_slope_5d": -0.3,
                "rsi14": 30, "atr14_pct": 4.0, "volume_ratio": 0.5,
                "change_pct": -1.5, "sector": "Energy",
            },
        },
    }


def test_run_lifecycle_round_trip(tmp_path: Path):
    # Build a fake momentum history that puts both tickers in scope.
    momentum_history = {
        "tickers": {
            "FAKE_OK":  {"snapshots": [{"date": "2026-05-08", "stage": "MOMENTUM_2"}]},
            "FAKE_BAD": {"snapshots": [{"date": "2026-05-08", "stage": "MOMENTUM_1"}]},
        }
    }
    (tmp_path / "history").mkdir()
    mom_path = tmp_path / "history" / "scanner_momentum_us_history.json"
    mom_path.write_text(json.dumps(momentum_history), encoding="utf-8")

    md = _market_data()
    result = run_lifecycle("US", project_dir=str(tmp_path),
                             market_data=md,
                             momentum_history_path=str(mom_path),
                             portfolio_tickers=set(), today="2026-05-08")
    assert result["status"] == "ok"
    assert "FAKE_OK" in result["snapshots"]
    # FAKE_OK has close=100, ema9=99.5 — that's 0.5% above ema9, INSIDE the 3% PULLBACK band.
    # So expected setup is PULLBACK, not TREND_OK.
    assert result["snapshots"]["FAKE_OK"]["setup"] == "PULLBACK"
    assert result["snapshots"]["FAKE_BAD"]["setup"] == "BROKEN"
    # State persisted.
    state_file = tmp_path / "history" / "lifecycle_history_us.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert "FAKE_OK" in state["tickers"]


def test_run_lifecycle_two_days_emits_transitions(tmp_path: Path):
    momentum_history = {"tickers": {
        "FAKE": {"snapshots": [{"date": "2026-05-08", "stage": "MOMENTUM_2"}]},
    }}
    (tmp_path / "history").mkdir()
    mom_path = tmp_path / "history" / "scanner_momentum_us_history.json"
    mom_path.write_text(json.dumps(momentum_history), encoding="utf-8")

    # Day 1 — clearly TREND_OK (close 5% above ema9, outside PULLBACK band).
    md1 = {"_meta": {"date": "2026-05-07"}, "data": {"FAKE": {
        "price": 104.5, "high": 105.5, "low": 103.5, "prev_close": 103,
        "ema9": 99.5, "ema21": 98, "ema65": 90,
        "ema21_slope_5d": 0.5, "ema65_slope_5d": 0.4,
        "rsi14": 60, "atr14_pct": 2.0, "volume_ratio": 1.0,
        "change_pct": 1.5, "sector": "Tech",
    }}}
    run_lifecycle("US", project_dir=str(tmp_path),
                    market_data=md1,
                    momentum_history_path=str(mom_path),
                    portfolio_tickers=set(), today="2026-05-07")

    # Day 2 — distance to ema9 grows past 12% AND rsi to 78 → EXTENDED.
    md2 = {"_meta": {"date": "2026-05-08"}, "data": {"FAKE": {
        "price": 120, "high": 121, "low": 118, "prev_close": 100,
        "ema9": 105, "ema21": 98, "ema65": 90,
        "ema21_slope_5d": 0.5, "ema65_slope_5d": 0.4,
        "rsi14": 78, "atr14_pct": 2.0, "volume_ratio": 1.5,
        "change_pct": 20.0, "sector": "Tech",
    }}}
    result = run_lifecycle("US", project_dir=str(tmp_path),
                             market_data=md2,
                             momentum_history_path=str(mom_path),
                             portfolio_tickers=set(), today="2026-05-08")
    types = {e["event"] for e in result["transitions"]}
    assert "SETUP_CHANGE" in types
    assert "DECISION_CHANGE" in types
