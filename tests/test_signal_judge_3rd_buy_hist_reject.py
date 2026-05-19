# tests/test_signal_judge_3rd_buy_hist_reject.py
"""v5.3e — 3rd_BUY MACD hist deceleration reject filter tests.

Covers both decision layer (_check_entry_growth / _check_entry_etf) and
display layer (_build_entry_sections_growth / _build_entry_sections_etf).
"""
import sys
import os
import copy
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import signal_judge
from signal_judge import (
    _check_entry_growth,
    _check_entry_etf,
    _build_entry_sections_growth,
    _build_entry_sections_etf,
)


def _patch_param(monkeypatch, dotted_path: str, value):
    """Set signal_judge.PARAMS via monkeypatch (auto-reverts after test)."""
    keys = dotted_path.split(".")
    new_params = copy.deepcopy(signal_judge.PARAMS)
    obj = new_params
    for k in keys[:-1]:
        obj = obj.setdefault(k, {})
    obj[keys[-1]] = value
    monkeypatch.setattr(signal_judge, "PARAMS", new_params)


# ─── Growth fixtures: a ticker that otherwise satisfies 3rd_BUY ALL ────────

def _growth_3rd_buy_base():
    """All four 3rd_BUY ALL conditions satisfied; RSI under 75 reject."""
    return {
        "rsi14": 60.0,
        "ma20": 100.0,
        "price": 105.0,
        "price_vs_ma20": "above",
        "macd": 0.50,
        "macd_signal": 0.20,
        "macd_hist": 0.30,
        "macd_hist_3d": [0.10, 0.20, 0.30],
        "macd_hist_trend": "increasing_2d",
        "volume_ratio": 2.0,
        "change_pct": 1.5,
    }


# ─── Growth decision tests ────────────────────────────────────────────────

def test_growth_3rd_buy_fires_on_increasing_2d():
    """Baseline: increasing_2d trend → 3rd_BUY fires (unchanged behavior)."""
    d = _growth_3rd_buy_base()
    signal, _ = _check_entry_growth(d)
    assert signal == "3rd_BUY"


def test_growth_3rd_buy_rejected_on_decreasing_2d(monkeypatch):
    """v5.3e: decreasing_2d → 3rd_BUY rejected (cascades to 2nd/1st/WATCH)."""
    _patch_param(monkeypatch, "entry_growth.3rd_buy.reject_decreasing_hist", True)
    d = _growth_3rd_buy_base()
    d["macd_hist_trend"] = "decreasing_2d"
    d["macd_hist_3d"] = [0.50, 0.40, 0.30]
    signal, _ = _check_entry_growth(d)
    assert signal != "3rd_BUY", \
        f"Expected fallback, got {signal} — decreasing_2d should block 3rd_BUY"


def test_growth_3rd_buy_passes_on_mixed_trend(monkeypatch):
    """mixed → 3rd_BUY still fires (only decreasing_2d rejects)."""
    _patch_param(monkeypatch, "entry_growth.3rd_buy.reject_decreasing_hist", True)
    d = _growth_3rd_buy_base()
    d["macd_hist_trend"] = "mixed"
    d["macd_hist_3d"] = [0.20, 0.30, 0.25]
    signal, _ = _check_entry_growth(d)
    assert signal == "3rd_BUY"


def test_growth_3rd_buy_passes_on_na_trend(monkeypatch):
    """N/A (data insufficient) → 3rd_BUY still fires (no starvation on new listings)."""
    _patch_param(monkeypatch, "entry_growth.3rd_buy.reject_decreasing_hist", True)
    d = _growth_3rd_buy_base()
    d["macd_hist_trend"] = "N/A"
    signal, _ = _check_entry_growth(d)
    assert signal == "3rd_BUY"


def test_growth_3rd_buy_passes_on_empty_trend(monkeypatch):
    """'' (field absent from dict default) → 3rd_BUY still fires."""
    _patch_param(monkeypatch, "entry_growth.3rd_buy.reject_decreasing_hist", True)
    d = _growth_3rd_buy_base()
    d["macd_hist_trend"] = ""
    signal, _ = _check_entry_growth(d)
    assert signal == "3rd_BUY"


def test_growth_3rd_buy_toggle_off_disables_filter(monkeypatch):
    """reject_decreasing_hist=False → decreasing_2d no longer rejects (v5.3d behavior)."""
    _patch_param(monkeypatch, "entry_growth.3rd_buy.reject_decreasing_hist", False)
    d = _growth_3rd_buy_base()
    d["macd_hist_trend"] = "decreasing_2d"
    d["macd_hist_3d"] = [0.50, 0.40, 0.30]
    signal, _ = _check_entry_growth(d)
    assert signal == "3rd_BUY", \
        "With toggle OFF, decreasing_2d should not block 3rd_BUY"


# ─── ETF fixtures + decision tests ────────────────────────────────────────

def _etf_3rd_buy_base():
    """All ETF 3rd_BUY ALL conditions satisfied; RSI under 70 reject."""
    return {
        "rsi14": 60.0,
        "ma20": 400.0,
        "price": 410.0,
        "price_vs_ma20": "above",
        "macd": 0.80,
        "macd_signal": 0.30,
        "macd_hist": 0.50,
        "macd_hist_3d": [0.20, 0.35, 0.50],
        "macd_hist_trend": "increasing_2d",
        "drawdown_52w_pct": -3.0,
    }


def test_etf_3rd_buy_fires_on_increasing_2d():
    """Baseline ETF: increasing_2d → 3rd_BUY (unchanged)."""
    d = _etf_3rd_buy_base()
    signal, _ = _check_entry_etf(d)
    assert signal == "3rd_BUY"


def test_etf_3rd_buy_rejected_on_decreasing_2d(monkeypatch):
    """v5.3e: ETF decreasing_2d → 3rd_BUY rejected."""
    _patch_param(monkeypatch, "entry_etf.3rd_buy.reject_decreasing_hist", True)
    d = _etf_3rd_buy_base()
    d["macd_hist_trend"] = "decreasing_2d"
    d["macd_hist_3d"] = [0.80, 0.65, 0.50]
    signal, _ = _check_entry_etf(d)
    assert signal != "3rd_BUY"


def test_etf_3rd_buy_passes_on_mixed(monkeypatch):
    _patch_param(monkeypatch, "entry_etf.3rd_buy.reject_decreasing_hist", True)
    d = _etf_3rd_buy_base()
    d["macd_hist_trend"] = "mixed"
    signal, _ = _check_entry_etf(d)
    assert signal == "3rd_BUY"


def test_etf_3rd_buy_passes_on_na(monkeypatch):
    _patch_param(monkeypatch, "entry_etf.3rd_buy.reject_decreasing_hist", True)
    d = _etf_3rd_buy_base()
    d["macd_hist_trend"] = "N/A"
    signal, _ = _check_entry_etf(d)
    assert signal == "3rd_BUY"


def test_etf_3rd_buy_toggle_off_disables_filter(monkeypatch):
    _patch_param(monkeypatch, "entry_etf.3rd_buy.reject_decreasing_hist", False)
    d = _etf_3rd_buy_base()
    d["macd_hist_trend"] = "decreasing_2d"
    signal, _ = _check_entry_etf(d)
    assert signal == "3rd_BUY"


# ─── Display-layer tests ──────────────────────────────────────────────────

def _find_3rd_buy_section(sections):
    """Pick the 3rd_BUY section out of the list (matches by name prefix)."""
    for s in sections:
        if "3차 매수" in s["name"]:
            return s
    raise AssertionError("3rd_BUY section not found in sections list")


def test_growth_display_3rd_buy_no_reject_row_on_increasing(monkeypatch):
    """Baseline display: increasing_2d → no reject row, gate is None."""
    _patch_param(monkeypatch, "entry_growth.3rd_buy.reject_decreasing_hist", True)
    d = _growth_3rd_buy_base()
    sections = _build_entry_sections_growth(d)
    section = _find_3rd_buy_section(sections)
    labels = [c[1] for c in section["conditions"]]
    assert "[거부] MACD hist 2일 감속" not in labels
    assert section["gate"] != "[거부] MACD hist 2일 감속"


def test_growth_display_3rd_buy_shows_reject_row_on_decreasing(monkeypatch):
    """v5.3e display: decreasing_2d → reject row appears AND gate is set."""
    _patch_param(monkeypatch, "entry_growth.3rd_buy.reject_decreasing_hist", True)
    d = _growth_3rd_buy_base()
    d["macd_hist_trend"] = "decreasing_2d"
    sections = _build_entry_sections_growth(d)
    section = _find_3rd_buy_section(sections)
    labels = [c[1] for c in section["conditions"]]
    assert "[거부] MACD hist 2일 감속" in labels, \
        f"Expected reject row in display; got labels: {labels}"
    assert section["gate"] == "[거부] MACD hist 2일 감속"


def test_growth_display_toggle_off_hides_reject_row(monkeypatch):
    """Toggle off → no reject row even when hist is decreasing_2d."""
    _patch_param(monkeypatch, "entry_growth.3rd_buy.reject_decreasing_hist", False)
    d = _growth_3rd_buy_base()
    d["macd_hist_trend"] = "decreasing_2d"
    sections = _build_entry_sections_growth(d)
    section = _find_3rd_buy_section(sections)
    labels = [c[1] for c in section["conditions"]]
    assert "[거부] MACD hist 2일 감속" not in labels


def test_etf_display_3rd_buy_shows_reject_row_on_decreasing(monkeypatch):
    """v5.3e ETF display: decreasing_2d → reject row AND gate set."""
    _patch_param(monkeypatch, "entry_etf.3rd_buy.reject_decreasing_hist", True)
    d = _etf_3rd_buy_base()
    d["macd_hist_trend"] = "decreasing_2d"
    sections = _build_entry_sections_etf(d)
    section = _find_3rd_buy_section(sections)
    labels = [c[1] for c in section["conditions"]]
    assert "[거부] MACD hist 2일 감속" in labels
    assert section["gate"] == "[거부] MACD hist 2일 감속"


def test_etf_display_toggle_off_hides_reject_row(monkeypatch):
    _patch_param(monkeypatch, "entry_etf.3rd_buy.reject_decreasing_hist", False)
    d = _etf_3rd_buy_base()
    d["macd_hist_trend"] = "decreasing_2d"
    sections = _build_entry_sections_etf(d)
    section = _find_3rd_buy_section(sections)
    labels = [c[1] for c in section["conditions"]]
    assert "[거부] MACD hist 2일 감속" not in labels
