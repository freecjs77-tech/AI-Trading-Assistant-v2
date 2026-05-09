"""Leg 검출 + return 계산 테스트."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import momentum_backtest as mb


def _hist(events: list[tuple]) -> dict:
    """events: [(date, stage, change, price, ...)] → ticker_data dict."""
    out = {}
    for tup in events:
        date, stage, change, price = tup[:4]
        e = {"stage": stage, "change": change, "price": price}
        if change == "EXIT":
            e["exit_price"] = price
            e["exit_date"] = date
            e["exit_reason"] = "EXIT"
            e["prev_stage"] = tup[4] if len(tup) > 4 else None
        out[date] = e
    return out


def test_extract_legs_single_new_then_exit():
    history = {"data": {"NVDA": _hist([
        ("2026-05-01", "MOMENTUM_2", "NEW", 100.0),
        ("2026-05-02", "MOMENTUM_2", "HOLD", 105.0),
        ("2026-05-03", None, "EXIT", 110.0, "MOMENTUM_2"),
    ])}}
    legs = mb.extract_legs(history)
    assert len(legs) == 1
    L = legs[0]
    assert L["ticker"] == "NVDA"
    assert L["stage"] == "MOMENTUM_2"
    assert L["entry_date"] == "2026-05-01"
    assert L["entry_price"] == 100.0
    assert L["exit_date"] == "2026-05-03"
    assert L["exit_price"] == 110.0
    assert L["exit_reason"] == "EXIT"


def test_extract_legs_upgrade_creates_new_leg():
    history = {"data": {"NVDA": _hist([
        ("2026-05-01", "MOMENTUM_2", "NEW", 100.0),
        ("2026-05-02", "MOMENTUM_3", "UPGRADE", 105.0),
        ("2026-05-03", None, "EXIT", 110.0, "MOMENTUM_3"),
    ])}}
    legs = mb.extract_legs(history)
    assert len(legs) == 2
    # 첫 leg: M2, 05-01 → 05-02 (UPGRADE 직전)
    assert legs[0]["stage"] == "MOMENTUM_2"
    assert legs[0]["entry_date"] == "2026-05-01"
    assert legs[0]["exit_date"] == "2026-05-02"
    assert legs[0]["exit_reason"] == "UPGRADE"
    # 두 번째 leg: M3, 05-02 → 05-03 EXIT
    assert legs[1]["stage"] == "MOMENTUM_3"
    assert legs[1]["entry_date"] == "2026-05-02"
    assert legs[1]["exit_date"] == "2026-05-03"


def test_extract_legs_in_progress_has_null_exit():
    history = {"data": {"NVDA": _hist([
        ("2026-05-01", "MOMENTUM_2", "NEW", 100.0),
        ("2026-05-02", "MOMENTUM_2", "HOLD", 105.0),
    ])}}
    legs = mb.extract_legs(history)
    assert len(legs) == 1
    L = legs[0]
    assert L["exit_date"] is None
    assert L["exit_price"] is None
    assert L["duration_days"] >= 1


def test_compute_leg_returns_basic():
    """leg에 entry_price=100, ohlc 시퀀스로 +5d/+10d/MaxRet/MDD 계산."""
    leg = {
        "ticker": "AAPL", "stage": "MOMENTUM_2",
        "entry_date": "2026-05-01", "entry_price": 100.0,
        "exit_date": None, "exit_price": None,
    }
    # 종가 시퀀스 (entry +1d, +2d, ..., +10d)
    closes = [100.0, 105.0, 108.0, 110.0, 112.0,
              115.0, 113.0, 109.0, 108.0, 105.0, 102.0]
    highs = [c * 1.02 for c in closes]   # 최대 117.3
    lows = [c * 0.98 for c in closes]    # 최소 99.96
    enriched = mb.compute_leg_returns(leg, closes=closes, highs=highs, lows=lows)
    # +3d 종가: 110 → +10%
    assert abs(enriched["ret_3d_pct"] - 10.0) < 0.01
    # +5d 종가: 115 → +15%
    assert abs(enriched["ret_5d_pct"] - 15.0) < 0.01
    # +10d 종가: 102 → +2%
    assert abs(enriched["ret_10d_pct"] - 2.0) < 0.01
    # max high since entry ≈ 117.3
    assert enriched["max_ret_pct"] > 16
    # mdd: peak ~117.3 → trough lowest low ≈ 99.96 → about -14.8%
    assert enriched["mdd_pct"] < -10


def test_compute_leg_returns_short_window():
    """진입 후 데이터가 3일밖에 없으면 5d/10d는 None."""
    leg = {"ticker": "X", "stage": "MOMENTUM_1",
           "entry_date": "2026-05-01", "entry_price": 100.0,
           "exit_date": None, "exit_price": None}
    closes = [100.0, 102.0, 103.0, 104.0]
    enriched = mb.compute_leg_returns(leg, closes=closes, highs=closes, lows=closes)
    assert enriched["ret_3d_pct"] is not None
    assert enriched["ret_5d_pct"] is None
    assert enriched["ret_10d_pct"] is None


def test_aggregate_legs_by_stage_and_streak():
    legs = [
        {"stage": "MOMENTUM_3", "ret_3d_pct": 2.0, "ret_5d_pct": 5.0,
         "ret_10d_pct": 8.0, "max_ret_pct": 10.0, "min_ret_pct": -1.0,
         "mdd_pct": -2.0, "duration_days": 6,
         "entry_context": {"streak": 3}},
        {"stage": "MOMENTUM_3", "ret_3d_pct": 1.0, "ret_5d_pct": 3.0,
         "ret_10d_pct": 5.0, "max_ret_pct": 7.0, "min_ret_pct": -2.0,
         "mdd_pct": -3.0, "duration_days": 5,
         "entry_context": {"streak": 1}},
        {"stage": "MOMENTUM_2", "ret_3d_pct": 0.5, "ret_5d_pct": 1.0,
         "ret_10d_pct": 2.0, "max_ret_pct": 4.0, "min_ret_pct": -3.0,
         "mdd_pct": -3.5, "duration_days": 4,
         "entry_context": {"streak": 2}},
    ]
    agg = mb.aggregate(legs, as_of="2026-05-06")
    assert agg["as_of"] == "2026-05-06"
    assert agg["by_stage"]["MOMENTUM_3"]["leg_count"] == 2
    # 두 leg ret_5d=5,3 → win_rate 100%, avg 4.0
    assert abs(agg["by_stage"]["MOMENTUM_3"]["avg_ret_5d_pct"] - 4.0) < 0.01
    assert agg["by_stage"]["MOMENTUM_3"]["win_rate_5d_pct"] == 100.0


def test_aggregate_consecutive_loss_alert_triggered():
    """최근 5개 leg 중 4개 이상 ret_5d < 0 → alert."""
    legs = [
        {"stage": "MOMENTUM_2", "ret_5d_pct": -3.0, "exit_date": "2026-05-01",
         "ret_3d_pct": 0, "ret_10d_pct": 0, "max_ret_pct": 0, "min_ret_pct": 0,
         "mdd_pct": 0, "duration_days": 1, "entry_context": {"streak": 1}},
        {"stage": "MOMENTUM_2", "ret_5d_pct": -2.0, "exit_date": "2026-05-02",
         "ret_3d_pct": 0, "ret_10d_pct": 0, "max_ret_pct": 0, "min_ret_pct": 0,
         "mdd_pct": 0, "duration_days": 1, "entry_context": {"streak": 1}},
        {"stage": "MOMENTUM_2", "ret_5d_pct": -1.0, "exit_date": "2026-05-03",
         "ret_3d_pct": 0, "ret_10d_pct": 0, "max_ret_pct": 0, "min_ret_pct": 0,
         "mdd_pct": 0, "duration_days": 1, "entry_context": {"streak": 1}},
        {"stage": "MOMENTUM_2", "ret_5d_pct": 1.0, "exit_date": "2026-05-04",
         "ret_3d_pct": 0, "ret_10d_pct": 0, "max_ret_pct": 0, "min_ret_pct": 0,
         "mdd_pct": 0, "duration_days": 1, "entry_context": {"streak": 1}},
        {"stage": "MOMENTUM_2", "ret_5d_pct": -4.0, "exit_date": "2026-05-05",
         "ret_3d_pct": 0, "ret_10d_pct": 0, "max_ret_pct": 0, "min_ret_pct": 0,
         "mdd_pct": 0, "duration_days": 1, "entry_context": {"streak": 1}},
    ]
    agg = mb.aggregate(legs, as_of="2026-05-06")
    assert agg["alerts"]["consecutive_loss_warning"] is True
    assert agg["alerts"]["recent_5_legs_loss_count"] >= 4


def test_aggregate_streak_buckets():
    legs = [
        {"stage": "MOMENTUM_3", "ret_5d_pct": 1.2, "entry_context": {"streak": 1},
         "ret_3d_pct": 0, "ret_10d_pct": 0, "max_ret_pct": 0, "min_ret_pct": 0,
         "mdd_pct": 0, "duration_days": 1},
        {"stage": "MOMENTUM_3", "ret_5d_pct": 3.4, "entry_context": {"streak": 2},
         "ret_3d_pct": 0, "ret_10d_pct": 0, "max_ret_pct": 0, "min_ret_pct": 0,
         "mdd_pct": 0, "duration_days": 1},
        {"stage": "MOMENTUM_3", "ret_5d_pct": 5.7, "entry_context": {"streak": 3},
         "ret_3d_pct": 0, "ret_10d_pct": 0, "max_ret_pct": 0, "min_ret_pct": 0,
         "mdd_pct": 0, "duration_days": 1},
    ]
    agg = mb.aggregate(legs, as_of="2026-05-06")
    assert "1" in agg["by_streak"]
    assert "3+" in agg["by_streak"]
    assert abs(agg["by_streak"]["3+"]["avg_ret_5d"] - 5.7) < 0.01


def test_aggregate_includes_em_in_by_stage():
    import momentum_backtest as mb
    legs = [
        {"ticker": "X", "stage": "EM", "ret_3d_pct": 1.0, "ret_5d_pct": 2.0,
         "ret_10d_pct": 4.0, "max_ret_pct": 5.0, "min_ret_pct": -1.0,
         "mdd_pct": -1.5, "duration_days": 5, "exit_reason": "UPGRADE"},
        {"ticker": "Y", "stage": "EM", "ret_3d_pct": -0.5, "ret_5d_pct": -1.0,
         "ret_10d_pct": 0.0, "max_ret_pct": 1.0, "min_ret_pct": -2.0,
         "mdd_pct": -2.5, "duration_days": 7, "exit_reason": "EXIT"},
    ]
    agg = mb.aggregate(legs, as_of="2026-05-09")
    assert "EM" in agg["by_stage"]
    em = agg["by_stage"]["EM"]
    assert em["leg_count"] == 2
    # win rate 5d: 1 of 2 positive (2.0 > 0)
    assert em["win_rate_5d_pct"] == 50.0


def test_em_transition_to_m1_pct_calculated():
    """transition_to_M1_pct = % of EM legs whose exit_reason == UPGRADE."""
    import momentum_backtest as mb
    legs = [
        {"ticker": "A", "stage": "EM", "exit_reason": "UPGRADE",
         "ret_5d_pct": 3.0, "ret_3d_pct": 1.0, "ret_10d_pct": None,
         "max_ret_pct": None, "min_ret_pct": None, "mdd_pct": None,
         "duration_days": 4},
        {"ticker": "B", "stage": "EM", "exit_reason": "UPGRADE",
         "ret_5d_pct": 5.0, "ret_3d_pct": 2.0, "ret_10d_pct": None,
         "max_ret_pct": None, "min_ret_pct": None, "mdd_pct": None,
         "duration_days": 5},
        {"ticker": "C", "stage": "EM", "exit_reason": "EXIT",
         "ret_5d_pct": -1.0, "ret_3d_pct": 0.0, "ret_10d_pct": None,
         "max_ret_pct": None, "min_ret_pct": None, "mdd_pct": None,
         "duration_days": 6},
        {"ticker": "D", "stage": "EM", "exit_reason": "DOWNGRADE",
         "ret_5d_pct": -2.0, "ret_3d_pct": -1.0, "ret_10d_pct": None,
         "max_ret_pct": None, "min_ret_pct": None, "mdd_pct": None,
         "duration_days": 7},
    ]
    agg = mb.aggregate(legs, as_of="2026-05-09")
    em = agg["by_stage"]["EM"]
    # 2 of 4 UPGRADE → 50.0%
    assert em["transition_to_M1_pct"] == 50.0


def test_transition_pct_excludes_in_progress_legs():
    """In-progress legs (exit_reason None) shouldn't count in denominator."""
    import momentum_backtest as mb
    legs = [
        {"ticker": "A", "stage": "EM", "exit_reason": "UPGRADE",
         "ret_5d_pct": 3.0, "ret_3d_pct": 1.0, "ret_10d_pct": None,
         "max_ret_pct": None, "min_ret_pct": None, "mdd_pct": None,
         "duration_days": 4},
        {"ticker": "B", "stage": "EM", "exit_reason": None,
         "ret_5d_pct": None, "ret_3d_pct": None, "ret_10d_pct": None,
         "max_ret_pct": None, "min_ret_pct": None, "mdd_pct": None,
         "duration_days": 1},
    ]
    agg = mb.aggregate(legs, as_of="2026-05-09")
    em = agg["by_stage"]["EM"]
    # Only 1 closed leg, 1 UPGRADE → 100.0%
    assert em["transition_to_M1_pct"] == 100.0


def test_transition_pct_none_when_no_closed_em_legs():
    import momentum_backtest as mb
    legs = [
        {"ticker": "A", "stage": "EM", "exit_reason": None,
         "ret_5d_pct": None, "ret_3d_pct": None, "ret_10d_pct": None,
         "max_ret_pct": None, "min_ret_pct": None, "mdd_pct": None,
         "duration_days": 1},
    ]
    agg = mb.aggregate(legs, as_of="2026-05-09")
    em = agg["by_stage"]["EM"]
    assert em["transition_to_M1_pct"] is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("[OK] momentum_backtest tests passed.")
