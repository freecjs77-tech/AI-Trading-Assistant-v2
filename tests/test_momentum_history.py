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


def test_rank_includes_em_at_zero():
    import momentum_history as mh
    assert mh.RANK["EM"] == 0
    assert mh.RANK["MOMENTUM_1"] == 1
    assert mh.RANK["MOMENTUM_2"] == 2
    assert mh.RANK["MOMENTUM_3"] == 3


def test_em_to_m1_is_upgrade():
    """EM → MOMENTUM_1 should be UPGRADE (RANK 0 < 1) with streak +1."""
    import momentum_history as mh
    history = {"data": {"PLTR": {
        "2026-05-09": {"stage": "EM", "streak": 3, "change": "HOLD",
                        "entry_price": 22.0, "entry_date": "2026-05-07",
                        "time_in_stage": 3, "price": 23.5},
    }}}
    today_signals = [{
        "ticker": "PLTR", "stage": "MOMENTUM_1", "price": 24.0,
        "maturity": "MID", "sector": "Software", "sector_top_rank": None,
        "rsi": 62.0, "ret_1d_pct": 1.5, "ret_3d_pct": 5.0,
        "ret_5d_pct": 7.0, "ret_20d_pct": 12.0, "dist_ema9_pct": 4.5,
        "rs_vs_sector": True, "risk_tags": [], "name": "Palantir",
    }]
    out = mh.update_history(history, today_signals, today="2026-05-10")
    entry = out["data"]["PLTR"]["2026-05-10"]
    assert entry["stage"] == "MOMENTUM_1"
    assert entry["change"] == "UPGRADE"
    assert entry["streak"] == 4
    assert entry["prev_stage"] == "EM"
    assert entry["maturity"] == "MID"
    assert entry["sector_top_rank"] is None
    assert entry["dist_ema9_pct"] == 4.5
    assert entry["ret_20d_pct"] == 12.0


def test_em_new_entry_includes_maturity_and_dist_ema9():
    import momentum_history as mh
    history = {"data": {}}
    today_signals = [{
        "ticker": "DUOL", "stage": "EM", "price": 180.0,
        "maturity": "EARLY", "sector": "Education", "sector_top_rank": None,
        "rsi": 64.0, "ret_1d_pct": 1.2, "ret_3d_pct": 2.0,
        "ret_5d_pct": 4.5, "ret_20d_pct": 11.0, "dist_ema9_pct": 1.8,
        "rs_vs_sector": None, "risk_tags": [], "name": "Duolingo",
    }]
    out = mh.update_history(history, today_signals, today="2026-05-09")
    entry = out["data"]["DUOL"]["2026-05-09"]
    assert entry["change"] == "NEW"
    assert entry["streak"] == 1
    assert entry["stage"] == "EM"
    assert entry["maturity"] == "EARLY"
    assert entry["dist_ema9_pct"] == 1.8
    assert entry["sector_top_rank"] is None


def test_load_history_filters_legacy_risk_tags_on_active_entries():
    """Existing v1.0 entries with EARLY/EXTENDED tags — filtered on read."""
    import json, tempfile, os, momentum_history as mh
    raw = {
        "_meta": {"scanner": "momentum_us", "schema_version": 1,
                  "version": "Momentum v1.0", "last_updated": "2026-05-08"},
        "data": {"NVDA": {"2026-05-08": {
            "stage": "MOMENTUM_3", "streak": 5, "change": "HOLD",
            "risk_tags": ["EXTENDED", "OVERHEAT", "EARLY"],
            "price": 920.0,
        }}},
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(raw, f)
        path = f.name
    try:
        out = mh.load_history(path)
        tags = out["data"]["NVDA"]["2026-05-08"]["risk_tags"]
        assert "EARLY" not in tags
        assert "EXTENDED" not in tags
        assert "OVERHEAT" in tags
    finally:
        os.unlink(path)


def test_save_history_writes_schema_version_2():
    import json, tempfile, os, momentum_history as mh
    history = {"_meta": {}, "data": {}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        path = f.name
    try:
        mh.save_history(path, history)
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["_meta"]["schema_version"] == 2
        assert saved["_meta"]["version"] == "Momentum v1.5"
    finally:
        os.unlink(path)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("[OK] momentum_history tests passed.")
