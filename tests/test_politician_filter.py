"""politician filter config 로딩 + 모드 결정 검증."""
import sys, os, json, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import politician_trades_aggregator as agg

def _with_temp_config(content):
    """임시 config 파일 환경. content=None이면 파일 자체가 없음."""
    tmp = tempfile.mkdtemp()
    cfg_path = os.path.join(tmp, "politician_filter.json")
    if content is not None:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(content, f)
    return tmp, cfg_path

def test_load_filter_returns_empty_when_file_missing():
    tmp, cfg_path = _with_temp_config(None)
    try:
        names = agg._load_politician_filter(cfg_path)
        assert names == [], f"파일 부재 시 빈 리스트 기대, got {names}"
    finally:
        shutil.rmtree(tmp)

def test_load_filter_returns_names_when_present():
    tmp, cfg_path = _with_temp_config({"politicians": ["Michael McCaul"]})
    try:
        names = agg._load_politician_filter(cfg_path)
        assert names == ["Michael McCaul"], f"got {names}"
    finally:
        shutil.rmtree(tmp)

def test_load_filter_handles_malformed():
    tmp, cfg_path = _with_temp_config({"unrelated_key": "x"})
    try:
        names = agg._load_politician_filter(cfg_path)
        assert names == [], "politicians 키 부재 시 빈 리스트"
    finally:
        shutil.rmtree(tmp)

def test_load_filter_skips_empty_strings():
    tmp, cfg_path = _with_temp_config({"politicians": ["Michael McCaul", "", "  ", None]})
    try:
        names = agg._load_politician_filter(cfg_path)
        assert names == ["Michael McCaul"], f"빈 문자열·None 거름, got {names}"
    finally:
        shutil.rmtree(tmp)

def test_load_filter_rejects_string_value():
    """politicians 가 list 가 아닌 string 일 때 빈 리스트 반환 (silent corruption 방지)."""
    tmp, cfg_path = _with_temp_config({"politicians": "Michael McCaul"})
    try:
        names = agg._load_politician_filter(cfg_path)
        assert names == [], f"string 값은 list가 아니므로 거부 기대, got {names}"
    finally:
        shutil.rmtree(tmp)

def test_trade_timeline_sorts_desc_and_keeps_raw_fields():
    """trades[] 가 날짜 desc 정렬되고 핵심 필드를 raw 그대로 포함하는지."""
    fake_trades = [
        {"politician_name": "Michael McCaul", "tx_date": "2026-03-10",
         "ticker": "AAPL", "issuer_name": "Apple Inc",
         "tx_type": "buy", "amount_min": 15001, "amount_max": 50000,
         "politician_id": "M001"},
        {"politician_name": "Michael McCaul", "tx_date": "2026-04-05",
         "ticker": "NVDA", "issuer_name": "NVIDIA Corp",
         "tx_type": "sell", "amount_min": 100001, "amount_max": 250000,
         "politician_id": "M001"},
        {"politician_name": "Michael McCaul", "tx_date": "2026-04-01",
         "ticker": "", "issuer_name": "Empty",  # empty ticker — should be skipped
         "tx_type": "buy", "amount_min": 1000, "amount_max": 2000,
         "politician_id": "M001"},
    ]
    timeline = agg._build_trade_timeline(fake_trades, portfolio_tickers={"AAPL"})
    assert len(timeline) == 2, f"empty-ticker drop, got {len(timeline)}"
    # 날짜 desc
    assert timeline[0]["tx_date"] == "2026-04-05", "최신 거래가 먼저"
    assert timeline[1]["tx_date"] == "2026-03-10"
    # 방향
    assert timeline[0]["direction"] == "sell"
    assert timeline[1]["direction"] == "buy"
    # in_portfolio
    assert timeline[1]["in_portfolio"] == True   # AAPL in portfolio
    assert timeline[0]["in_portfolio"] == False  # NVDA not
    # raw 필드 보존
    assert timeline[1]["amount_min"] == 15001
    assert timeline[0]["issuer_name"] == "NVIDIA Corp"

def test_trade_timeline_drops_unknown_direction():
    """tx_type 인식 못 하는 trade 는 drop."""
    timeline = agg._build_trade_timeline([
        {"ticker": "X", "tx_date": "2026-01-01", "tx_type": "WeirdType"},
    ])
    assert timeline == [], f"got {timeline}"

if __name__ == "__main__":
    test_load_filter_returns_empty_when_file_missing()
    test_load_filter_returns_names_when_present()
    test_load_filter_handles_malformed()
    test_load_filter_skips_empty_strings()
    test_load_filter_rejects_string_value()
    test_trade_timeline_sorts_desc_and_keeps_raw_fields()
    test_trade_timeline_drops_unknown_direction()
    print("[OK] config 로더 테스트 통과")
