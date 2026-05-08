# tests/test_lifecycle_history.py
"""Phase A — lifecycle_history schema + atomic I/O."""
import json
import os
from pathlib import Path

import pytest

from lifecycle_history import (
    new_empty_state, load_lifecycle_history, save_lifecycle_history,
    append_snapshot, append_transition,
)


def test_new_empty_state_shape():
    s = new_empty_state(market="US")
    assert s["schema_version"] == "1.0.0"
    assert s["generator_version"].startswith("lifecycle_phase_a/")
    assert s["tickers"] == {}
    assert s["transitions"] == []


def test_round_trip(tmp_path: Path):
    s = new_empty_state(market="US")
    p = tmp_path / "lifecycle_history_us.json"
    save_lifecycle_history(s, str(p))
    loaded = load_lifecycle_history(str(p))
    assert loaded["schema_version"] == "1.0.0"
    assert loaded["tickers"] == {}


def test_load_missing_file_returns_empty():
    s = load_lifecycle_history("/nonexistent/path.json", market="US")
    assert s["tickers"] == {}


def test_atomic_write_no_partial_on_failure(tmp_path: Path, monkeypatch):
    """A failed save must leave the existing file intact."""
    p = tmp_path / "lifecycle_history_us.json"
    save_lifecycle_history(new_empty_state(market="US"), str(p))
    original = p.read_text()
    # Force os.replace to fail.
    import lifecycle_history as lh
    monkeypatch.setattr(lh.os, "replace",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("simulated")))
    with pytest.raises(OSError):
        save_lifecycle_history(new_empty_state(market="US"), str(p))
    assert p.read_text() == original  # unchanged.


def test_append_snapshot_creates_ticker_block():
    s = new_empty_state(market="US")
    snap = {"date": "2026-05-08", "setup": "TREND_OK", "trigger": "WAIT",
            "decision": "STAGING", "raw": {"close": 100, "high": 101,
            "low": 99, "ema9": 99, "ema21": 95, "ema65": 90,
            "dist_ema9_pct": 1.0, "dist_ema21_pct": 5.0,
            "volume_ratio": 1.0, "atr_pct": 2.0,
            "sector": "Technology", "risk_tags": []}}
    append_snapshot(s, "NVDA", snap)
    assert s["tickers"]["NVDA"]["first_seen"] == "2026-05-08"
    assert s["tickers"]["NVDA"]["last_seen"] == "2026-05-08"
    assert len(s["tickers"]["NVDA"]["snapshots"]) == 1


def test_append_snapshot_extends_existing_ticker():
    s = new_empty_state(market="US")
    s["tickers"]["NVDA"] = {"first_seen": "2026-05-07", "last_seen": "2026-05-07",
                             "snapshots": [{"date": "2026-05-07", "setup": "TREND_OK",
                                            "trigger": "WAIT", "decision": "STAGING",
                                            "raw": {}}]}
    snap = {"date": "2026-05-08", "setup": "PULLBACK", "trigger": "WAIT",
            "decision": "STAGING", "raw": {}}
    append_snapshot(s, "NVDA", snap)
    assert s["tickers"]["NVDA"]["last_seen"] == "2026-05-08"
    assert len(s["tickers"]["NVDA"]["snapshots"]) == 2


def test_append_transition_event_id_format():
    s = new_empty_state(market="US")
    append_transition(s, ticker="NVDA", date_str="2026-05-08",
                      event="SETUP_CHANGE", from_value="EXTENDED", to_value="PULLBACK")
    t = s["transitions"][0]
    assert t["event_id"] == "NVDA_2026-05-08_SETUP_CHANGE_v1"
    assert t["event"] == "SETUP_CHANGE"
    assert t["from"] == "EXTENDED"
    assert t["to"] == "PULLBACK"
