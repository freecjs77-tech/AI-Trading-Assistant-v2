"""portfolio_stop_signal calculate_stop / evaluate_signal 테스트."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import portfolio_stop_signal as ps
from portfolio_stop_signal import (
    get_stop_mode, calculate_stop, round_stop,
    evaluate_signal, ACTION_MAP,
)


# ─── get_stop_mode 우선순위 ────────────────────────────────

def test_mode_explicit_override_wins():
    """OVERRIDES > keyword > category."""
    # 110990 디아이티는 KOSPI Stock 카테고리지만 HIGH_VOL override
    assert get_stop_mode("110990", "디아이티", "KOSPI Stock") == "HIGH_VOL"
    # 102110 TIGER 200 은 KOSPI ETF 기본 MOMENTUM이지만 CORE override
    assert get_stop_mode("102110", "TIGER 200", "KOSPI ETF") == "CORE"


def test_mode_keyword_auto():
    """KOSPI ETF 기본 MOMENTUM, '반도체'/'코스닥' 키워드 → HIGH_VOL."""
    assert get_stop_mode("396500", "TIGER 반도체TOP10", "KOSPI ETF") == "HIGH_VOL"
    assert get_stop_mode("232080", "TIGER 코스닥150", "KOSPI ETF") == "HIGH_VOL"
    assert get_stop_mode("466920", "SOL 조선TOP3플러스", "KOSPI ETF") == "HIGH_VOL"


def test_mode_category_default():
    assert get_stop_mode("VOO", "Vanguard S&P 500 ETF", "ETF Core") == "CORE"
    assert get_stop_mode("BIL", "SPDR 1-3M T-bill", "Bond") == "DEFENSIVE"
    assert get_stop_mode("AAPL", "Apple Inc", "Growth") == "MOMENTUM"
    assert get_stop_mode("SLV", "iShares Silver", "Metal") == "HIGH_VOL"


def test_mode_unknown_category_default():
    assert get_stop_mode("XYZ", "Unknown Co", "MadeUpCategory") == "MOMENTUM"


# ─── round_stop (시장별 호가) ───────────────────────────────

def test_round_stop_us_two_decimals():
    assert round_stop(874.32156, "NVDA") == 874.32


def test_round_stop_kr_integer():
    assert round_stop(71432.2831, "005930") == 71432.0
    assert round_stop(15000.7, "0153K0") == 15001.0


# ─── calculate_stop (모드별) ────────────────────────────────

def test_calculate_stop_core_pct():
    """CORE: highest × 0.88."""
    assert calculate_stop(100.0, atr14=2.0, mode="CORE", ticker="VOO") == 88.0


def test_calculate_stop_defensive_pct():
    """DEFENSIVE: highest × 0.92."""
    assert calculate_stop(100.0, atr14=0.5, mode="DEFENSIVE", ticker="BIL") == 92.0


def test_calculate_stop_momentum_atr_floor_applied():
    """ATR×3 < 8% min → min_pct floor 적용."""
    # ATR×3 = 6, min_pct=8 → distance = max(6, 8) = 8 → stop = 92
    assert calculate_stop(100.0, atr14=2.0, mode="MOMENTUM", ticker="AAPL") == 92.0


def test_calculate_stop_momentum_atr_in_range():
    """8% ≤ ATR×3 ≤ 20% → 그대로 적용."""
    # ATR×3 = 12 → distance = 12 → stop = 88
    assert calculate_stop(100.0, atr14=4.0, mode="MOMENTUM", ticker="NVDA") == 88.0


def test_calculate_stop_momentum_atr_ceiling_applied():
    """ATR×3 > 20% max → max_pct ceiling 적용."""
    # ATR×3 = 30 → distance = min(30, 20) = 20 → stop = 80
    assert calculate_stop(100.0, atr14=10.0, mode="MOMENTUM", ticker="TSLA") == 80.0


def test_calculate_stop_high_vol_atr_clamps():
    """HIGH_VOL: ATR×4, [12%, 30%]."""
    # ATR×4 = 8 < 12 min → 12 → stop = 88
    assert calculate_stop(100.0, atr14=2.0, mode="HIGH_VOL", ticker="QLD") == 88.0
    # ATR×4 = 80 > 30 max → 30 → stop = 70
    assert calculate_stop(100.0, atr14=20.0, mode="HIGH_VOL", ticker="QLD") == 70.0


def test_calculate_stop_atr_none_fallback():
    """ATR 없으면 min_pct로 fallback."""
    assert calculate_stop(100.0, atr14=None, mode="MOMENTUM", ticker="NVDA") == 92.0
    assert calculate_stop(100.0, atr14=None, mode="HIGH_VOL", ticker="QLD") == 88.0


def test_calculate_stop_kr_integer_rounding():
    """KR ticker → stop은 정수."""
    # 삼성전자 highest 78500, ATR 800 → MOMENTUM
    # ATR×3 = 2400 (3.06%), min 8% → 6280 → distance = 6280 → 72220
    assert calculate_stop(78500.0, atr14=800.0, mode="MOMENTUM", ticker="005930") == 72220.0


# ─── evaluate_signal 4-state machine ────────────────────────

def test_signal_hold():
    """close > stop × 1.05 → HOLD."""
    r = evaluate_signal(today_close=100.0, stop_price=90.0, prev_below_count=0,
                        is_new_position=False)
    assert r["raw_signal"] == "HOLD"
    assert r["display_signal"] == "HOLD"
    assert r["below_stop_count"] == 0


def test_signal_tight():
    """stop < close ≤ stop × 1.05 → TIGHT."""
    r = evaluate_signal(today_close=92.0, stop_price=90.0, prev_below_count=0,
                        is_new_position=False)
    assert r["raw_signal"] == "TIGHT"
    assert r["below_stop_count"] == 0


def test_signal_exit_ready_first_breach():
    """close ≤ stop AND below_count was 0 → EXIT_READY (count=1)."""
    r = evaluate_signal(today_close=89.0, stop_price=90.0, prev_below_count=0,
                        is_new_position=False)
    assert r["raw_signal"] == "EXIT_READY"
    assert r["below_stop_count"] == 1


def test_signal_exit_two_consecutive():
    """count was 1 + still below → EXIT (count=2)."""
    r = evaluate_signal(today_close=88.0, stop_price=90.0, prev_below_count=1,
                        is_new_position=False)
    assert r["raw_signal"] == "EXIT"
    assert r["below_stop_count"] == 2


def test_signal_recovery_resets_count():
    """count=1, recovery → HOLD/TIGHT, count=0."""
    r = evaluate_signal(today_close=100.0, stop_price=90.0, prev_below_count=1,
                        is_new_position=False)
    assert r["raw_signal"] == "HOLD"
    assert r["below_stop_count"] == 0


def test_signal_close_equals_stop_counted():
    """close == stop → 하회로 인정 (`<=` 사용)."""
    r = evaluate_signal(today_close=90.0, stop_price=90.0, prev_below_count=0,
                        is_new_position=False)
    assert r["raw_signal"] == "EXIT_READY"
    assert r["below_stop_count"] == 1


# ─── Display downgrade (신규 종목) ───────────────────────────

def test_display_downgrade_new_position_exit_ready():
    """신규 종목 + raw EXIT_READY → display TIGHT."""
    r = evaluate_signal(today_close=89.0, stop_price=90.0, prev_below_count=0,
                        is_new_position=True)
    assert r["raw_signal"] == "EXIT_READY"   # raw 보존
    assert r["display_signal"] == "TIGHT"   # display 다운그레이드
    assert r["display_downgraded"] is True


def test_display_downgrade_new_position_exit():
    r = evaluate_signal(today_close=88.0, stop_price=90.0, prev_below_count=1,
                        is_new_position=True)
    assert r["raw_signal"] == "EXIT"
    assert r["display_signal"] == "TIGHT"
    assert r["display_downgraded"] is True


def test_no_downgrade_for_old_position():
    r = evaluate_signal(today_close=89.0, stop_price=90.0, prev_below_count=0,
                        is_new_position=False)
    assert r["display_signal"] == "EXIT_READY"
    assert r["display_downgraded"] is False


# ─── Action 매핑 ────────────────────────────────────────────

def test_action_map_complete():
    for s in ("HOLD", "TIGHT", "EXIT_READY", "EXIT"):
        assert s in ACTION_MAP


if __name__ == "__main__":
    import inspect
    fns = [f for n, f in globals().items()
           if n.startswith("test_") and inspect.isfunction(f)]
    for f in fns:
        f()
    print(f"[OK] {len(fns)} portfolio_stop_signal tests passed.")
