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

if __name__ == "__main__":
    test_load_filter_returns_empty_when_file_missing()
    test_load_filter_returns_names_when_present()
    test_load_filter_handles_malformed()
    test_load_filter_skips_empty_strings()
    test_load_filter_rejects_string_value()
    print("[OK] config 로더 테스트 통과")
