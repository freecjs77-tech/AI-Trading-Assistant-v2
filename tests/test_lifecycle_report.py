# tests/test_lifecycle_report.py
"""Phase A — lifecycle page render."""
import os
from pathlib import Path

import pytest

from lifecycle_report import generate_lifecycle_pages, build_page_context


def _result(market: str, snapshots: dict, transitions=None):
    return {
        "market":   market,
        "as_of":    "2026-05-08",
        "snapshots": snapshots,
        "transitions": transitions or [],
        "skipped":  [],
    }


def test_build_page_context_groups_by_decision():
    snaps = {
        "NVDA": {"date": "2026-05-08", "setup": "PULLBACK", "trigger": "CONFIRMED_TRIGGER",
                  "decision": "ENTER_OK",
                  "raw": {"close": 100, "ema9": 99, "ema21": 95, "ema65": 90,
                           "dist_ema9_pct": 1.0, "dist_ema21_pct": 5.0,
                           "volume_ratio": 1.5, "atr_pct": 2.0,
                           "sector": "Technology", "risk_tags": []}},
        "BAD":  {"date": "2026-05-08", "setup": "BROKEN", "trigger": "WAIT",
                  "decision": "AVOID",
                  "raw": {"close": 50, "ema9": 60, "ema21": 65, "ema65": 70,
                           "dist_ema9_pct": 16.0, "dist_ema21_pct": 23.0,
                           "volume_ratio": 0.5, "atr_pct": 4.0,
                           "sector": "Energy", "risk_tags": []}},
    }
    ctx = build_page_context(_result("US", snaps))
    assert {r["ticker"] for r in ctx["enter_ok"]} == {"NVDA"}
    # BROKEN/AVOID gets routed to broken_table per spec §10.1 [6].
    assert {r["ticker"] for r in ctx["broken_table"]} == {"BAD"}
    assert ctx["new_confirmed"][0]["ticker"] == "NVDA"  # trigger_age 0


def test_build_page_context_sorts_enter_ok_by_trigger_age_then_volume():
    # Two ENTER_OK tickers — newer trigger appears first.
    snaps = {
        "OLD": {"date": "2026-05-08", "setup": "PULLBACK", "trigger": "CONFIRMED_TRIGGER",
                 "decision": "ENTER_OK",
                 "raw": {"close": 100, "ema9": 99, "ema21": 95, "ema65": 90,
                          "dist_ema9_pct": 1.0, "dist_ema21_pct": 5.0,
                          "volume_ratio": 1.3, "atr_pct": 2.0,
                          "sector": "Tech", "risk_tags": []}},
        "NEW": {"date": "2026-05-08", "setup": "PULLBACK", "trigger": "CONFIRMED_TRIGGER",
                 "decision": "ENTER_OK",
                 "raw": {"close": 100, "ema9": 99, "ema21": 95, "ema65": 90,
                          "dist_ema9_pct": 1.0, "dist_ema21_pct": 5.0,
                          "volume_ratio": 2.0, "atr_pct": 2.0,
                          "sector": "Tech", "risk_tags": []}},
    }
    # Inject lifecycle history so OLD has trigger_age=2 and NEW has 0.
    lifecycle_state = {"tickers": {
        "OLD": {"first_seen": "2026-05-06", "last_seen": "2026-05-08",
                 "snapshots": [
                    {"date": "2026-05-06", "setup": "PULLBACK", "trigger": "CONFIRMED_TRIGGER",
                      "decision": "ENTER_OK", "raw": {}},
                    {"date": "2026-05-07", "setup": "PULLBACK", "trigger": "WAIT",
                      "decision": "EARLY", "raw": {}},
                    {"date": "2026-05-08", "setup": "PULLBACK", "trigger": "CONFIRMED_TRIGGER",
                      "decision": "ENTER_OK", "raw": {}},
                 ]},
        "NEW": {"first_seen": "2026-05-08", "last_seen": "2026-05-08",
                 "snapshots": [
                    {"date": "2026-05-08", "setup": "PULLBACK", "trigger": "CONFIRMED_TRIGGER",
                      "decision": "ENTER_OK", "raw": {}},
                 ]},
    }}
    ctx = build_page_context(_result("US", snaps), lifecycle_state=lifecycle_state)
    assert [r["ticker"] for r in ctx["enter_ok"]] == ["NEW", "OLD"]


def test_generate_lifecycle_pages_writes_html(tmp_path: Path):
    snaps = {"NVDA": {"date": "2026-05-08", "setup": "TREND_OK", "trigger": "WAIT",
                       "decision": "STAGING",
                       "raw": {"close": 100, "ema9": 99, "ema21": 95, "ema65": 90,
                                "dist_ema9_pct": 1.0, "dist_ema21_pct": 5.0,
                                "volume_ratio": 1.0, "atr_pct": 2.0,
                                "sector": "Tech", "risk_tags": []}}}
    paths = generate_lifecycle_pages(
        us_result=_result("US", snaps), kr_result=None,
        output_dir=str(tmp_path), template_dir=None)
    assert "us" in paths
    assert os.path.exists(paths["us"])
    html = Path(paths["us"]).read_text(encoding="utf-8")
    assert "NVDA" in html
    assert "STAGING" in html


def test_generate_lifecycle_pages_skips_when_result_none(tmp_path: Path):
    paths = generate_lifecycle_pages(us_result=None, kr_result=None,
                                       output_dir=str(tmp_path), template_dir=None)
    assert paths == {}
