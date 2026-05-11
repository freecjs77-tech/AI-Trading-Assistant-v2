"""Tests for benchmark_ytd.compute_dit_rest_decomposition.

Covers:
- 110990 보유 케이스 (정상 분해)
- 110990 미보유 케이스 (모든 필드 None)
- KOSDAQ 환율 무관성 (USD/KRW 변경해도 dit_ytd_pct 불변)
- 수학적 일관성 (dit_v0_krw + rest_v0_krw == v0_krw)
- 합산 시뮬레이션 (me + wife KRW 합산 후 % 재계산)
"""
from __future__ import annotations

import pytest

from benchmark_ytd import compute_dit_rest_decomposition

DIT = "110990"


def _baseline_with_dit():
    """Baseline snapshot containing 110990, AAPL, and VOO entries.

    VOO is intentionally included in ``ticker_v0_krw`` even though NO test's
    ``holdings`` list contains VOO.  This verifies that
    ``compute_dit_rest_decomposition`` iterates over the caller-supplied
    ``holdings`` list — NOT over ``baseline["ticker_v0_krw"]`` — when
    computing ``rest_v0_krw``.  A Task-2 implementer who writes
    ``rest_v0 = sum(baseline_v0_krw_values) - dit_v0`` will pick up VOO's
    700,000 KRW and fail ``test_dit_held_normal_decomposition``'s
    ``rest_v0_krw == 2_800_000`` assertion.  The failure is the guard.
    """
    return {
        "anchor_date": "2026-01-02",
        "usd_krw": 1400.0,
        "spy_close_usd": 580.0,
        "ticker_v0_krw": {
            DIT: 15690.0,           # KRW native (KOSDAQ)
            "AAPL": 200.0 * 1400,   # 280000 KRW = 200 USD × 1400
            "VOO": 500.0 * 1400,    # 700000 KRW — present in baseline but NOT in any test's holdings
        },
        "unmappable": [],
    }


def test_dit_held_normal_decomposition():
    """디아이티 보유 케이스 → 6 필드 정상 산출."""
    baseline = _baseline_with_dit()
    holdings = [
        {"ticker": DIT, "shares": 1000},
        {"ticker": "AAPL", "shares": 10},
    ]
    today_prices = {DIT: 25000.0, "AAPL": 250.0}
    today_usd_krw = 1500.0

    # v0_krw = 1000*15690 + 10*200*1400 = 15,690,000 + 2,800,000 = 18,490,000
    # v_now_krw = 1000*25000 + 10*250*1500 = 25,000,000 + 3,750,000 = 28,750,000
    v0_krw = 18_490_000.0
    v_now_krw = 28_750_000.0

    result = compute_dit_rest_decomposition(
        holdings, today_prices, today_usd_krw, baseline, v0_krw, v_now_krw
    )

    # 디아이티 단독
    assert result["dit_v0_krw"] == pytest.approx(15_690_000.0)
    assert result["dit_now_krw"] == pytest.approx(25_000_000.0)
    assert result["dit_ytd_pct"] == pytest.approx((25_000_000 / 15_690_000 - 1) * 100, rel=1e-6)

    # 나머지
    assert result["rest_v0_krw"] == pytest.approx(2_800_000.0)
    assert result["rest_now_krw"] == pytest.approx(3_750_000.0)
    assert result["rest_ytd_pct"] == pytest.approx((3_750_000 / 2_800_000 - 1) * 100, rel=1e-6)


def test_dit_not_held_returns_all_none():
    """110990 미보유 → 6 필드 모두 None."""
    baseline = {
        "anchor_date": "2026-01-02",
        "usd_krw": 1400.0,
        "spy_close_usd": 580.0,
        "ticker_v0_krw": {"AAPL": 280000.0, "VOO": 700000.0},
        "unmappable": [],
    }
    holdings = [{"ticker": "AAPL", "shares": 10}]
    today_prices = {"AAPL": 250.0}
    today_usd_krw = 1500.0
    v0_krw = 10 * 280000.0
    v_now_krw = 10 * 250.0 * 1500.0

    result = compute_dit_rest_decomposition(
        holdings, today_prices, today_usd_krw, baseline, v0_krw, v_now_krw
    )

    assert result["dit_ytd_pct"] is None
    assert result["rest_ytd_pct"] is None
    assert result["dit_v0_krw"] is None
    assert result["dit_now_krw"] is None
    assert result["rest_v0_krw"] is None
    assert result["rest_now_krw"] is None


def test_dit_ytd_invariant_under_fx_change():
    """KOSDAQ 종목은 환율 무관 → today_usd_krw 변경해도 dit_ytd_pct 불변."""
    baseline = _baseline_with_dit()
    holdings = [{"ticker": DIT, "shares": 1000}, {"ticker": "AAPL", "shares": 10}]
    today_prices = {DIT: 25000.0, "AAPL": 250.0}

    # FX = 1500
    v0_a = 18_490_000.0
    v_now_a = 1000 * 25000 + 10 * 250 * 1500  # = 28,750,000
    result_a = compute_dit_rest_decomposition(holdings, today_prices, 1500.0, baseline, v0_a, v_now_a)

    # FX = 2000
    v0_b = 18_490_000.0  # baseline은 그대로 — Jan2 시점 KRW 가격 고정
    v_now_b = 1000 * 25000 + 10 * 250 * 2000  # = 30,000,000
    result_b = compute_dit_rest_decomposition(holdings, today_prices, 2000.0, baseline, v0_b, v_now_b)

    # 디아이티는 KOSDAQ → FX 무관
    assert result_a["dit_ytd_pct"] == pytest.approx(result_b["dit_ytd_pct"], rel=1e-9)
    # 나머지는 US 종목이라 FX 변경 시 변화 OK (이 테스트의 단언 대상 아님)


def test_dit_rest_v0_sum_equals_total_v0():
    """수학적 일관성: dit_v0_krw + rest_v0_krw == v0_krw (소수점 오차 1e-3 이내)."""
    baseline = _baseline_with_dit()
    holdings = [{"ticker": DIT, "shares": 1000}, {"ticker": "AAPL", "shares": 10}]
    today_prices = {DIT: 25000.0, "AAPL": 250.0}
    v0_krw = 18_490_000.0
    v_now_krw = 28_750_000.0

    result = compute_dit_rest_decomposition(holdings, today_prices, 1500.0, baseline, v0_krw, v_now_krw)

    assert abs((result["dit_v0_krw"] + result["rest_v0_krw"]) - v0_krw) < 1e-3
    assert abs((result["dit_now_krw"] + result["rest_now_krw"]) - v_now_krw) < 1e-3


def test_combined_simulation_krw_sum_then_recompute():
    """합산 뷰 산출: me + wife KRW 합산 후 % 재계산 — aggregation math contract.

    SCOPE: This test does NOT call ``compute_dit_rest_decomposition``.
    It validates the pure-arithmetic aggregation formula that will be used
    in ``report_generator._build_combined_payload`` (Task 11):

        combined_pct = (sum_now / sum_v0 - 1) * 100

    where KRW values from the me-result and wife-result are summed first,
    and then the percentage is recomputed from the combined totals (NOT by
    averaging the two individual percentages).  This serves as a regression
    guard for the aggregation formula itself, independent of the helper.
    """
    # me: dit_v0=1000만, dit_now=1500만, rest_v0=500만, rest_now=600만
    me = {"dit_v0_krw": 10_000_000.0, "dit_now_krw": 15_000_000.0, "rest_v0_krw": 5_000_000.0, "rest_now_krw": 6_000_000.0}
    # wife: dit_v0=300만, dit_now=400만, rest_v0=200만, rest_now=250만
    wife = {"dit_v0_krw": 3_000_000.0, "dit_now_krw": 4_000_000.0, "rest_v0_krw": 2_000_000.0, "rest_now_krw": 2_500_000.0}

    # 합산
    dit_v0 = me["dit_v0_krw"] + wife["dit_v0_krw"]      # 1300만
    dit_now = me["dit_now_krw"] + wife["dit_now_krw"]   # 1900만
    rest_v0 = me["rest_v0_krw"] + wife["rest_v0_krw"]   # 700만
    rest_now = me["rest_now_krw"] + wife["rest_now_krw"]# 850만

    dit_ytd = (dit_now / dit_v0 - 1) * 100
    rest_ytd = (rest_now / rest_v0 - 1) * 100

    assert dit_ytd == pytest.approx(46.1538, abs=1e-3)   # (1900/1300 - 1)*100
    assert rest_ytd == pytest.approx(21.4286, abs=1e-3)  # (850/700 - 1)*100
