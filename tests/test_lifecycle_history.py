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


# ---------------------------------------------------------------------------
# Task 8: compute_active_set
# ---------------------------------------------------------------------------
from lifecycle_history import compute_active_set


def test_active_set_includes_recent_m1_m2_m3():
    momentum_history = {
        "tickers": {
            "NVDA": {"snapshots": [{"date": "2026-05-08", "stage": "MOMENTUM_2"}]},
            "OLD":  {"snapshots": [{"date": "2026-04-01", "stage": "MOMENTUM_1"}]},  # >14d ago
        }
    }
    lifecycle_state = {"tickers": {}}
    portfolio = []
    s = compute_active_set(momentum_history=momentum_history,
                           lifecycle_state=lifecycle_state,
                           portfolio_tickers=set(portfolio),
                           today="2026-05-08")
    assert "NVDA" in s
    assert "OLD" not in s


def test_active_set_keeps_recent_nonbroken_lifecycle_tickers():
    momentum_history = {"tickers": {}}
    lifecycle_state = {
        "tickers": {
            "PLTR": {"last_seen": "2026-05-05",
                     "snapshots": [{"date": "2026-05-05", "setup": "PULLBACK"}]},
            "DEAD": {"last_seen": "2026-04-01",
                     "snapshots": [{"date": "2026-04-01", "setup": "TREND_OK"}]},
            "BRKN": {"last_seen": "2026-05-07",
                     "snapshots": [{"date": "2026-05-07", "setup": "BROKEN"}]},
        }
    }
    s = compute_active_set(momentum_history=momentum_history,
                           lifecycle_state=lifecycle_state,
                           portfolio_tickers=set(),
                           today="2026-05-08")
    assert "PLTR" in s    # recent + non-broken
    assert "DEAD" not in s   # >10d stale
    assert "BRKN" not in s   # most-recent state was BROKEN — drops out


def test_active_set_excludes_portfolio_tickers():
    momentum_history = {"tickers": {
        "AAPL": {"snapshots": [{"date": "2026-05-08", "stage": "MOMENTUM_3"}]},
    }}
    s = compute_active_set(momentum_history=momentum_history,
                           lifecycle_state={"tickers": {}},
                           portfolio_tickers={"AAPL"},
                           today="2026-05-08")
    assert "AAPL" not in s


def test_active_set_truncates_to_max_size():
    # Build 600 momentum-recent tickers; expect <=500 in active set.
    momentum_history = {"tickers": {
        f"T{i:04d}": {"snapshots": [{"date": "2026-05-08", "stage": "MOMENTUM_1"}]}
        for i in range(600)
    }}
    s = compute_active_set(momentum_history=momentum_history,
                           lifecycle_state={"tickers": {}},
                           portfolio_tickers=set(),
                           today="2026-05-08")
    from lifecycle_config import ACTIVE_SET_MAX_SIZE
    assert len(s) <= ACTIVE_SET_MAX_SIZE


# ---------------------------------------------------------------------------
# Task 9: derive_fields
# ---------------------------------------------------------------------------
from lifecycle_history import derive_fields


def _ticker_history(*items):
    """items: list of (date, setup, trigger). Returns block in storage shape."""
    return {
        "first_seen": items[0][0],
        "last_seen": items[-1][0],
        "snapshots": [
            {"date": d, "setup": s, "trigger": t, "decision": "X", "raw": {}}
            for d, s, t in items
        ],
    }


def test_derive_setup_streak():
    block = _ticker_history(
        ("2026-05-04", "TREND_OK", "WAIT"),
        ("2026-05-05", "PULLBACK", "WAIT"),
        ("2026-05-06", "PULLBACK", "WAIT"),
        ("2026-05-07", "PULLBACK", "EARLY_TRIGGER"),
        ("2026-05-08", "PULLBACK", "CONFIRMED_TRIGGER"),
    )
    out = derive_fields(block)
    assert out["setup_streak"] == 4  # 4 consecutive PULLBACK days


def test_derive_days_in_pullback_counts_base_forming_too():
    block = _ticker_history(
        ("2026-05-05", "TREND_OK",     "WAIT"),
        ("2026-05-06", "PULLBACK",     "WAIT"),
        ("2026-05-07", "BASE_FORMING", "WAIT"),
        ("2026-05-08", "PULLBACK",     "CONFIRMED_TRIGGER"),
    )
    out = derive_fields(block)
    assert out["days_in_pullback"] == 3


def test_derive_trigger_age_days_zero_today():
    block = _ticker_history(
        ("2026-05-05", "PULLBACK", "WAIT"),
        ("2026-05-06", "PULLBACK", "WAIT"),
        ("2026-05-08", "PULLBACK", "CONFIRMED_TRIGGER"),
    )
    out = derive_fields(block)
    assert out["trigger_age_days"] == 0


def test_derive_trigger_age_counts_back_to_last_early_or_confirmed():
    block = _ticker_history(
        ("2026-05-04", "PULLBACK", "WAIT"),
        ("2026-05-05", "PULLBACK", "EARLY_TRIGGER"),
        ("2026-05-06", "PULLBACK", "WAIT"),
        ("2026-05-07", "PULLBACK", "WAIT"),
        ("2026-05-08", "PULLBACK", "WAIT"),
    )
    out = derive_fields(block)
    # Today is 2026-05-08; last EARLY_TRIGGER was 2026-05-05 -> 3 days ago.
    assert out["trigger_age_days"] == 3


def test_derive_trigger_age_none_when_never_triggered():
    block = _ticker_history(
        ("2026-05-07", "PULLBACK", "WAIT"),
        ("2026-05-08", "PULLBACK", "WAIT"),
    )
    out = derive_fields(block)
    assert out["trigger_age_days"] is None


# ---------------------------------------------------------------------------
# Task 10: compute_transitions
# ---------------------------------------------------------------------------
from lifecycle_history import compute_transitions


def test_transition_setup_change():
    yesterday = {"setup": "EXTENDED", "trigger": "WAIT", "decision": "AVOID",
                  "raw": {"risk_tags": []}}
    today =     {"date": "2026-05-08",
                  "setup": "PULLBACK", "trigger": "WAIT", "decision": "STAGING",
                  "raw": {"risk_tags": []}}
    events = compute_transitions("NVDA", yesterday, today)
    types = {e["event"] for e in events}
    assert "SETUP_CHANGE" in types
    assert "DECISION_CHANGE" in types  # AVOID -> STAGING


def test_transition_no_change_no_event():
    same = {"date": "2026-05-08", "setup": "TREND_OK", "trigger": "WAIT",
             "decision": "STAGING", "raw": {"risk_tags": []}}
    events = compute_transitions("NVDA", same, same)
    assert events == []


def test_transition_failed_breakout_emitted_independently():
    yesterday = {"setup": "PULLBACK", "trigger": "CONFIRMED_TRIGGER",
                  "decision": "ENTER_OK", "raw": {"risk_tags": []}}
    today =     {"date": "2026-05-08",
                  "setup": "PULLBACK", "trigger": "WAIT", "decision": "AVOID",
                  "raw": {"risk_tags": ["FAILED_BREAKOUT"]}}
    events = compute_transitions("NVDA", yesterday, today)
    assert any(e["event"] == "FAILED_BREAKOUT" for e in events)
    assert any(e["event"] == "TRIGGER_CHANGE" for e in events)


def test_transition_risk_escalation_when_extended_first_appears():
    yesterday = {"setup": "TREND_OK", "trigger": "WAIT",
                  "decision": "STAGING", "raw": {"risk_tags": []}}
    today =     {"date": "2026-05-08",
                  "setup": "EXTENDED", "trigger": "WAIT",
                  "decision": "AVOID", "raw": {"risk_tags": ["EXTENDED"]}}
    events = compute_transitions("NVDA", yesterday, today)
    assert any(e["event"] == "RISK_ESCALATION" for e in events)


def test_transition_no_yesterday_emits_nothing():
    today =     {"date": "2026-05-08",
                  "setup": "PULLBACK", "trigger": "WAIT", "decision": "STAGING",
                  "raw": {"risk_tags": []}}
    assert compute_transitions("NVDA", None, today) == []


# ---------------------------------------------------------------------------
# Task 11: bootstrap_active_set
# ---------------------------------------------------------------------------
from lifecycle_history import bootstrap_active_set


def test_bootstrap_uses_supplied_fetcher_returns_seed_state():
    """When lifecycle_history is missing on first run, bootstrap_active_set
    builds seed state from a momentum-history-style input."""
    momentum_history = {
        "tickers": {
            "NVDA": {"snapshots": [{"date": "2026-05-08", "stage": "MOMENTUM_2"}]},
            "PLTR": {"snapshots": [{"date": "2026-05-07", "stage": "MOMENTUM_1"}]},
        }
    }
    seed = bootstrap_active_set(market="US", momentum_history=momentum_history,
                                  portfolio_tickers=set(), today="2026-05-08")
    # Seed is a state dict ready to receive snapshots — empty tickers map but
    # marker fields populated so subsequent process_universe knows it bootstrapped.
    assert seed["schema_version"] == "1.0.0"
    assert "_bootstrap_meta" in seed
    assert set(seed["_bootstrap_meta"]["seed_tickers"]) == {"NVDA", "PLTR"}


# ---------------------------------------------------------------------------
# Schema adapter: momentum_scanner shape → active_set shape
# ---------------------------------------------------------------------------

from lifecycle_history import normalize_momentum_history


def test_normalize_momentum_history_converts_data_keyed():
    raw = {
        "_meta": {"scanner": "momentum_us"},
        "data": {
            "NVDA": {
                "2026-05-07": {"stage": "MOMENTUM_2", "streak": 1},
                "2026-05-08": {"stage": "MOMENTUM_3", "streak": 2},
            },
            "PLTR": {
                "2026-05-08": {"stage": "MOMENTUM_1"},
            },
        },
    }
    out = normalize_momentum_history(raw)
    assert "tickers" in out
    nvda_snaps = out["tickers"]["NVDA"]["snapshots"]
    assert [s["date"] for s in nvda_snaps] == ["2026-05-07", "2026-05-08"]
    assert nvda_snaps[1]["stage"] == "MOMENTUM_3"
    assert out["tickers"]["PLTR"]["snapshots"][0]["date"] == "2026-05-08"


def test_normalize_passthrough_when_already_tickers_shape():
    raw = {"tickers": {"NVDA": {"snapshots": [{"date": "2026-05-08", "stage": "MOMENTUM_2"}]}}}
    out = normalize_momentum_history(raw)
    assert out is raw  # passthrough


def test_normalize_handles_empty_or_garbage():
    assert normalize_momentum_history({}) == {"tickers": {}}
    assert normalize_momentum_history({"data": {}}) == {"tickers": {}}
    assert normalize_momentum_history(None) == {"tickers": {}}
    # Non-dict ticker entry skipped, not crashed.
    assert normalize_momentum_history({"data": {"NVDA": "garbage"}}) == {"tickers": {}}


def test_active_set_uses_normalized_momentum_history():
    raw = {
        "data": {
            "NVDA": {"2026-05-08": {"stage": "MOMENTUM_2"}},
            "OLD":  {"2026-04-01": {"stage": "MOMENTUM_1"}},  # >14d ago
        }
    }
    normalized = normalize_momentum_history(raw)
    s = compute_active_set(momentum_history=normalized,
                            lifecycle_state={"tickers": {}},
                            portfolio_tickers=set(),
                            today="2026-05-08")
    assert "NVDA" in s
    assert "OLD" not in s
