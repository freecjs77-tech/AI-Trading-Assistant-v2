"""Tests for lifecycle_report._build_verdict_summary.

Covers 4 branches + AVOID dynamic line insertion:
- ENTER ≥ 1 → "✅ 오늘 신규 진입 가능 종목 N개"
- PROBE ≥ 1, ENTER = 0 → "⚡ 분할 진입 가능 종목 N개"
- ENTER = 0 & PROBE = 0 (with WATCH/TRENDING) → "⏸ 오늘은 신규 진입할 종목이 없습니다"
- All groups empty (total = 0) → "⚠ 추적 종목 없음 — 시그널 부재"
- AVOID > 0 → avoid_line populated with max dist + max RSI
"""
from __future__ import annotations

import pytest

from lifecycle_report import _build_verdict_summary


def _row(ticker, dist_ema9=None, rsi=None):
    """Minimal row dict for verdict tests. dist_ema9_pct attached at top-level
    (derived), rsi14 nested under raw (matches _attach_derived structure)."""
    return {
        "ticker": ticker,
        "dist_ema9_pct": dist_ema9,
        "raw": {"rsi14": rsi},
    }


def test_verdict_enter_present():
    """ENTER ≥ 1 → '✅ 신규 진입 가능 종목 N개' headline."""
    enter = [_row("AAPL"), _row("NVDA"), _row("MSFT")]
    result = _build_verdict_summary(enter, probe=[], watch=[], trending=[], avoid=[])

    assert "✅" in result["headline"]
    assert "3" in result["headline"]
    assert "신규 진입" in result["headline"]
    assert "AAPL" in result["narration"]
    assert "NVDA" in result["narration"]
    assert "확정 트리거" in result["narration"]
    assert result["avoid_line"] is None
    assert "ENTER 종목" in result["action_hint"]


def test_verdict_probe_only():
    """ENTER=0, PROBE≥1 → '⚡ 분할 진입 가능 종목 N개'."""
    probe = [_row("TSLA"), _row("AMZN")]
    result = _build_verdict_summary(enter=[], probe=probe, watch=[], trending=[], avoid=[])

    assert "⚡" in result["headline"]
    assert "2" in result["headline"]
    assert "분할 진입" in result["headline"]
    assert "TSLA" in result["narration"]
    assert "약한 트리거" in result["narration"]
    assert "PROBE 종목" in result["action_hint"]


def test_verdict_watch_trending_only():
    """ENTER=0 & PROBE=0 with WATCH/TRENDING → '⏸ 신규 진입할 종목 없음'."""
    watch = [_row("AFRM"), _row("ALGM"), _row("AVGO")]
    trending = [_row("NVDA"), _row("AAPL")]
    result = _build_verdict_summary(enter=[], probe=[], watch=watch,
                                     trending=trending, avoid=[])

    assert "⏸" in result["headline"]
    assert "신규 진입할 종목이 없습니다" in result["headline"]
    assert "WATCH 3개" in result["narration"]
    assert "TRENDING 2개" in result["narration"]
    assert "WATCH 트리거 발화 대기" in result["action_hint"]


def test_verdict_all_empty():
    """5 그룹 모두 빈 list (total=0) → '⚠ 추적 종목 없음'."""
    result = _build_verdict_summary(enter=[], probe=[], watch=[],
                                     trending=[], avoid=[])

    assert "⚠" in result["headline"]
    assert "추적 종목 없음" in result["headline"]
    assert "pipeline 로그" in result["action_hint"]


def test_verdict_avoid_dynamic_line():
    """AVOID > 0 → avoid_line에 max dist + max RSI 실측치 정확히 삽입."""
    avoid = [
        _row("AMD", dist_ema9=19.1, rsi=81.2),
        _row("INTC", dist_ema9=20.3, rsi=84.5),  # max RSI
        _row("MU", dist_ema9=21.2, rsi=80.0),    # max dist
    ]
    result = _build_verdict_summary(enter=[], probe=[], watch=[],
                                     trending=[], avoid=avoid)

    assert result["avoid_line"] is not None
    assert "🔴" in result["avoid_line"]
    assert "AMD" in result["avoid_line"]
    assert "INTC" in result["avoid_line"]
    assert "MU" in result["avoid_line"]
    assert "3종목" in result["avoid_line"]
    # max dist (MU's 21.2) and max RSI (INTC's 84.5 → 85 when rounded)
    assert "21.2" in result["avoid_line"]
    assert "84" in result["avoid_line"] or "85" in result["avoid_line"]


def test_make_snapshot_exposes_rsi14_in_raw():
    """Regression guard: production snap.raw must include rsi14 for verdict avoid_line.

    Without this, the dynamic AVOID line displays 'RSI 0+로 과확장 상태'
    instead of the actual RSI value. The synthetic _row() helper in the
    verdict tests injects rsi14 manually, so they pass even when the
    production data path is broken — this test closes that gap.
    """
    from lifecycle_signal import _make_snapshot
    snap = _make_snapshot(
        "2026-05-11",
        raw={"close": 100, "ema9": 95, "ema21": 90, "ema65": 85,
             "rsi14": 78.5, "high": 102, "low": 98, "volume_ratio": 1.5},
        setup="EXTENDED", trigger="WAIT", decision="AVOID", risk_tags=["OVERHEAT"]
    )
    assert "rsi14" in snap["raw"], "_make_snapshot raw dict must include rsi14"
    assert snap["raw"]["rsi14"] == 78.5
