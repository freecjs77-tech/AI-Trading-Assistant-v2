"""Streak/change/EXIT 시나리오 테스트."""
import sys, os, json, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import momentum_history as mh


def test_first_signal_is_new_streak_1():
    history = {"_meta": {"scanner": "momentum_us"}, "data": {}}
    today_signals = [
        {"ticker": "NVDA", "stage": "MOMENTUM_2", "price": 850.0,
         "rsi": 62.5, "ret_1d_pct": 5.2, "ret_3d_pct": 9.1, "ret_5d_pct": 11.8,
         "sector": "Tech", "rs_vs_sector": False, "risk_tags": []},
    ]
    new_history = mh.update_history(history, today_signals, today="2026-05-02")
    e = new_history["data"]["NVDA"]["2026-05-02"]
    assert e["change"] == "NEW"
    assert e["streak"] == 1
    assert e["entry_date"] == "2026-05-02"
    assert e["entry_price"] == 850.0
    assert e["time_in_stage"] == 1


def test_hold_increments_streak():
    history = {"_meta": {}, "data": {"NVDA": {
        "2026-05-02": {"stage": "MOMENTUM_2", "streak": 1, "change": "NEW",
                       "entry_price": 850.0, "entry_date": "2026-05-02",
                       "time_in_stage": 1, "price": 850.0}
    }}}
    new = mh.update_history(history, [
        {"ticker": "NVDA", "stage": "MOMENTUM_2", "price": 855.0, "risk_tags": []},
    ], today="2026-05-03")
    e = new["data"]["NVDA"]["2026-05-03"]
    assert e["change"] == "HOLD"
    assert e["streak"] == 2
    assert e["entry_price"] == 850.0    # 동일 stage 유지
    assert e["time_in_stage"] == 2


def test_upgrade_resets_entry_keeps_streak_increment():
    history = {"_meta": {}, "data": {"NVDA": {
        "2026-05-02": {"stage": "MOMENTUM_2", "streak": 1, "change": "NEW",
                       "entry_price": 850.0, "entry_date": "2026-05-02",
                       "time_in_stage": 1, "price": 850.0}
    }}}
    new = mh.update_history(history, [
        {"ticker": "NVDA", "stage": "MOMENTUM_3", "price": 875.0, "risk_tags": []},
    ], today="2026-05-03")
    e = new["data"]["NVDA"]["2026-05-03"]
    assert e["change"] == "UPGRADE"
    assert e["streak"] == 2          # streak +1
    assert e["entry_price"] == 875.0 # 새 stage 진입가
    assert e["entry_date"] == "2026-05-03"
    assert e["time_in_stage"] == 1


def test_downgrade_resets_streak_to_1():
    history = {"_meta": {}, "data": {"NVDA": {
        "2026-05-02": {"stage": "MOMENTUM_3", "streak": 5, "change": "HOLD",
                       "entry_price": 875.0, "entry_date": "2026-05-02",
                       "time_in_stage": 1, "price": 920.0}
    }}}
    new = mh.update_history(history, [
        {"ticker": "NVDA", "stage": "MOMENTUM_2", "price": 905.0, "risk_tags": []},
    ], today="2026-05-03")
    e = new["data"]["NVDA"]["2026-05-03"]
    assert e["change"] == "DOWNGRADE"
    assert e["streak"] == 1
    assert e["entry_price"] == 905.0


def test_exit_event_when_signal_disappears():
    history = {"_meta": {}, "data": {"NVDA": {
        "2026-05-06": {"stage": "MOMENTUM_3", "streak": 4, "change": "HOLD",
                       "entry_price": 875.0, "entry_date": "2026-05-03",
                       "time_in_stage": 4, "price": 920.0}
    }}}
    # NVDA가 today 시그널에 없음 → EXIT 이벤트
    new = mh.update_history(history, [], today="2026-05-07")
    e = new["data"]["NVDA"]["2026-05-07"]
    assert e["change"] == "EXIT"
    assert e["stage"] is None
    assert e["prev_stage"] == "MOMENTUM_3"
    assert e["exit_date"] == "2026-05-07"
    assert e["exit_reason"] == "EXIT"


def test_re_entry_after_exit_starts_new():
    """EXIT 후 다음 시그널 → NEW 재시작 (streak 1)."""
    history = {"_meta": {}, "data": {"NVDA": {
        "2026-05-06": {"stage": "MOMENTUM_3", "streak": 4, "change": "HOLD",
                       "entry_price": 875.0, "entry_date": "2026-05-03",
                       "time_in_stage": 4, "price": 920.0},
        "2026-05-07": {"stage": None, "change": "EXIT", "prev_stage": "MOMENTUM_3",
                       "exit_date": "2026-05-07", "exit_price": 920.0,
                       "exit_reason": "EXIT"},
    }}}
    new = mh.update_history(history, [
        {"ticker": "NVDA", "stage": "MOMENTUM_1", "price": 940.0, "risk_tags": []},
    ], today="2026-05-08")
    e = new["data"]["NVDA"]["2026-05-08"]
    assert e["change"] == "NEW"
    assert e["streak"] == 1
    assert e["entry_price"] == 940.0


def test_save_load_roundtrip():
    tmp = tempfile.mkdtemp(prefix="mh_test_")
    try:
        path = os.path.join(tmp, "history.json")
        history = {"_meta": {"scanner": "momentum_us", "schema_version": 1},
                   "data": {"AAPL": {"2026-05-01": {"stage": "MOMENTUM_1"}}}}
        mh.save_history(path, history)
        loaded = mh.load_history(path)
        assert loaded["data"]["AAPL"]["2026-05-01"]["stage"] == "MOMENTUM_1"
        assert loaded["_meta"]["scanner"] == "momentum_us"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_load_history_creates_skeleton_if_missing():
    tmp = tempfile.mkdtemp(prefix="mh_test_")
    try:
        path = os.path.join(tmp, "missing.json")
        loaded = mh.load_history(path, scanner_name="momentum_us")
        assert loaded["_meta"]["scanner"] == "momentum_us"
        assert loaded["data"] == {}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("[OK] momentum_history tests passed.")
