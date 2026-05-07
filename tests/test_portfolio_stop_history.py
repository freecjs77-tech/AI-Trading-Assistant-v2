"""portfolio_stop_history 라이프사이클 테스트."""
import sys, os, json, tempfile
from datetime import date, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import portfolio_stop_history as ph
from portfolio_stop_history import (
    load_stop_history, save_stop_history,
    update_highest_close_safe, evaluate_lifecycle,
    new_empty_state, get_position,
)


def _tmp_path():
    return os.path.join(tempfile.gettempdir(), f"stops_test_{os.getpid()}.json")


def test_load_returns_empty_when_missing():
    path = _tmp_path()
    if os.path.exists(path):
        os.remove(path)
    state = load_stop_history(path)
    assert state["_meta"]["schema_version"] == 1
    assert state["positions"] == {}
    assert state["snapshots"] == {}


def test_save_load_roundtrip():
    path = _tmp_path()
    state = new_empty_state(owner="me")
    state["positions"]["NVDA"] = {
        "status": "active", "mode": "MOMENTUM",
        "entry_date": "2026-01-02",
        "highest_close": 945.0, "highest_close_date": "2026-05-05",
        "current_stop": 874.0, "below_stop_count": 0,
        "shares": 50.0, "last_size_change": "2026-04-17",
        "missing_since": None, "last_signal": "HOLD",
        "last_action": "Hold", "last_evaluated": "2026-05-07",
    }
    save_stop_history(state, path)
    loaded = load_stop_history(path)
    assert loaded["positions"]["NVDA"]["highest_close"] == 945.0
    assert loaded["positions"]["NVDA"]["below_stop_count"] == 0
    os.remove(path)


def test_update_highest_close_basic_increment():
    pos = {"highest_close": 100.0, "highest_close_date": "2026-01-15", "ticker": "T"}
    update_highest_close_safe(pos, today_close=105.0, prev_close=104.0,
                              today_str="2026-02-01")
    assert pos["highest_close"] == 105.0
    assert pos["highest_close_date"] == "2026-02-01"


def test_update_highest_close_no_change_below():
    pos = {"highest_close": 100.0, "highest_close_date": "2026-01-15", "ticker": "T"}
    update_highest_close_safe(pos, today_close=95.0, prev_close=96.0,
                              today_str="2026-02-01")
    assert pos["highest_close"] == 100.0   # unchanged
    assert pos["highest_close_date"] == "2026-01-15"


def test_update_highest_close_jump_guard_skipped():
    """40% 초과 단일일 점프 -> highest 갱신 스킵."""
    pos = {"highest_close": 100.0, "highest_close_date": "2026-01-15", "ticker": "T"}
    # prev=100, today=145 -> +45% jump -> 가드 발동
    update_highest_close_safe(pos, today_close=145.0, prev_close=100.0,
                              today_str="2026-02-01")
    assert pos["highest_close"] == 100.0   # unchanged due to guard


def test_update_highest_close_normal_jump_within_threshold():
    """30% 점프는 의심스럽지만 정상 범위 (earnings 등)."""
    pos = {"highest_close": 100.0, "highest_close_date": "2026-01-15", "ticker": "T"}
    update_highest_close_safe(pos, today_close=130.0, prev_close=100.0,
                              today_str="2026-02-01")
    assert pos["highest_close"] == 130.0


def test_evaluate_lifecycle_new_position_first_seen():
    """기존 stops에 없는 ticker -> 신규 등록 (entry_date=today)."""
    state = new_empty_state(owner="me")
    evaluate_lifecycle(
        state, portfolio_tickers={"NVDA"}, today_str="2026-05-07",
        new_position_seed={"NVDA": {"close": 920.0, "shares": 50.0,
                                     "mode": "MOMENTUM"}},
    )
    pos = state["positions"]["NVDA"]
    assert pos["status"] == "active"
    assert pos["entry_date"] == "2026-05-07"
    assert pos["highest_close"] == 920.0
    assert pos["highest_close_date"] == "2026-05-07"


def test_evaluate_lifecycle_missing_grace_3days():
    """3일 부재 시에만 archive - 1일/2일은 active 유지."""
    state = new_empty_state(owner="me")
    state["positions"]["NVDA"] = {
        "status": "active", "mode": "MOMENTUM",
        "entry_date": "2026-01-02", "highest_close": 1.0,
        "missing_since": None, "shares": 50.0,
    }
    # Day 1 missing
    evaluate_lifecycle(state, portfolio_tickers=set(), today_str="2026-05-08",
                       new_position_seed={})
    assert state["positions"]["NVDA"]["status"] == "active"
    assert state["positions"]["NVDA"]["missing_since"] == "2026-05-08"
    # Day 2 missing
    evaluate_lifecycle(state, portfolio_tickers=set(), today_str="2026-05-09",
                       new_position_seed={})
    assert state["positions"]["NVDA"]["status"] == "active"
    # Day 3 missing
    evaluate_lifecycle(state, portfolio_tickers=set(), today_str="2026-05-10",
                       new_position_seed={})
    assert state["positions"]["NVDA"]["status"] == "closed"
    assert state["positions"]["NVDA"]["closed_date"] == "2026-05-10"


def test_evaluate_lifecycle_missing_recover_resets_counter():
    """1일 부재 후 재등장하면 missing_since 리셋."""
    state = new_empty_state(owner="me")
    state["positions"]["NVDA"] = {
        "status": "active", "mode": "MOMENTUM",
        "entry_date": "2026-01-02", "highest_close": 1.0,
        "missing_since": None, "shares": 50.0,
    }
    evaluate_lifecycle(state, portfolio_tickers=set(), today_str="2026-05-08",
                       new_position_seed={})
    assert state["positions"]["NVDA"]["missing_since"] == "2026-05-08"
    # Re-appears next day
    evaluate_lifecycle(state, portfolio_tickers={"NVDA"}, today_str="2026-05-09",
                       new_position_seed={})
    assert state["positions"]["NVDA"]["status"] == "active"
    assert state["positions"]["NVDA"]["missing_since"] is None


def test_evaluate_lifecycle_reopen_after_archive():
    """Archived 종목이 다시 portfolio에 등장 -> fresh bootstrap."""
    state = new_empty_state(owner="me")
    state["positions"]["TSLA"] = {
        "status": "closed", "mode": "MOMENTUM",
        "entry_date": "2026-01-02", "highest_close": 410.0,
        "highest_close_date": "2026-02-15",
        "closed_date": "2026-04-30", "shares": 0.0,
    }
    evaluate_lifecycle(
        state, portfolio_tickers={"TSLA"}, today_str="2026-05-15",
        new_position_seed={"TSLA": {"close": 250.0, "shares": 30.0,
                                     "mode": "MOMENTUM"}},
    )
    pos = state["positions"]["TSLA"]
    assert pos["status"] == "active"
    assert pos["entry_date"] == "2026-05-15"  # fresh anchor
    assert pos["highest_close"] == 250.0       # reset to today
    assert pos.get("closed_date") is None or pos.get("reopened_date") == "2026-05-15"


if __name__ == "__main__":
    test_load_returns_empty_when_missing()
    test_save_load_roundtrip()
    test_update_highest_close_basic_increment()
    test_update_highest_close_no_change_below()
    test_update_highest_close_jump_guard_skipped()
    test_update_highest_close_normal_jump_within_threshold()
    test_evaluate_lifecycle_new_position_first_seen()
    test_evaluate_lifecycle_missing_grace_3days()
    test_evaluate_lifecycle_missing_recover_resets_counter()
    test_evaluate_lifecycle_reopen_after_archive()
    print("[OK] portfolio_stop_history tests passed.")
