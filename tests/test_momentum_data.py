"""momentum_data.py 캐시 I/O 테스트."""
import sys, os, json, tempfile, shutil
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import momentum_data as md

def setup_temp_data_dir():
    tmp = tempfile.mkdtemp(prefix="momentum_test_")
    md.set_data_dir(tmp)
    return tmp

def teardown(tmp):
    shutil.rmtree(tmp, ignore_errors=True)

def test_save_and_load_cache():
    tmp = setup_temp_data_dir()
    try:
        md.save_cache("test_etf", ["AAPL", "MSFT"], source="ishares", status="ok")
        loaded = md.load_cache("test_etf")
        assert loaded is not None
        assert loaded["data"] == ["AAPL", "MSFT"]
        assert loaded["fetch_status"] == "ok"
        assert loaded["fallback_count"] == 0
        assert loaded["row_count"] == 2
        assert loaded["source"] == "ishares"
    finally:
        teardown(tmp)

def test_load_cache_missing_returns_none():
    tmp = setup_temp_data_dir()
    try:
        assert md.load_cache("does_not_exist") is None
    finally:
        teardown(tmp)

def test_cache_age_days_fresh():
    tmp = setup_temp_data_dir()
    try:
        md.save_cache("x", ["A"])
        age = md.cache_age_days("x")
        assert 0 <= age <= 1
    finally:
        teardown(tmp)

def test_cache_age_days_missing_returns_inf():
    tmp = setup_temp_data_dir()
    try:
        assert md.cache_age_days("missing") == float("inf")
    finally:
        teardown(tmp)

def test_save_cache_with_fallback_count():
    tmp = setup_temp_data_dir()
    try:
        md.save_cache("x", ["A"], status="stale_fallback", fallback_count=2)
        loaded = md.load_cache("x")
        assert loaded["fetch_status"] == "stale_fallback"
        assert loaded["fallback_count"] == 2
    finally:
        teardown(tmp)

def test_with_fallback_helper_uses_cached_on_failure():
    """fetch_with_fallback: 실패 시 직전 캐시 반환 + fallback_count++."""
    tmp = setup_temp_data_dir()
    try:
        md.save_cache("x", ["OLD"], status="ok")
        def failing_fetch():
            raise RuntimeError("network down")
        result = md.fetch_with_fallback("x", failing_fetch, source="test")
        assert result == ["OLD"]
        cache = md.load_cache("x")
        assert cache["fetch_status"] == "stale_fallback"
        assert cache["fallback_count"] == 1
    finally:
        teardown(tmp)

def test_with_fallback_helper_resets_count_on_success():
    tmp = setup_temp_data_dir()
    try:
        md.save_cache("x", ["OLD"], status="stale_fallback", fallback_count=2)
        result = md.fetch_with_fallback("x", lambda: ["NEW"], source="test")
        assert result == ["NEW"]
        cache = md.load_cache("x")
        assert cache["fetch_status"] == "ok"
        assert cache["fallback_count"] == 0
    finally:
        teardown(tmp)

def test_normalize_symbol():
    """normalize_symbol — 심볼 정규화 및 캐시/빈값 필터링."""
    assert md.normalize_symbol("AAPL") == "AAPL"
    assert md.normalize_symbol("BRK.B") == "BRK-B"
    assert md.normalize_symbol("BF.B") == "BF-B"
    assert md.normalize_symbol("-") is None    # cash row
    assert md.normalize_symbol("") is None
    assert md.normalize_symbol("   ") is None


def test_parse_iwb_csv_with_known_column():
    """parse_ishares_csv — 알려진 컬럼명 'Ticker'."""
    fixture = os.path.join(os.path.dirname(__file__), "fixtures", "iwb_sample.csv")
    with open(fixture, "rb") as f:
        csv_bytes = f.read()
    tickers = md.parse_ishares_csv(csv_bytes)
    # AAPL, MSFT, BRK-B (정규화), BF-B (정규화). USD CASH / 빈줄 제외.
    assert tickers == ["AAPL", "MSFT", "BRK-B", "BF-B"]


def test_parse_iwb_csv_with_alternative_column():
    """parse_ishares_csv — 컬럼명이 'Ticker Symbol'이어도 인식."""
    csv = (b"\n\nTicker Symbol,Name\n"
           b"NVDA,NVIDIA\n"
           b"AMD,AMD INC\n")
    assert md.parse_ishares_csv(csv) == ["NVDA", "AMD"]


def test_parse_iwb_csv_unknown_column_raises():
    """parse_ishares_csv — 알려진 컬럼명 없으면 ValueError."""
    csv = b"\n\nWeirdCol,Name\nFOO,Foo Inc\n"
    try:
        md.parse_ishares_csv(csv)
        assert False, "Should have raised"
    except ValueError as e:
        assert "ticker column" in str(e).lower()


if __name__ == "__main__":
    test_save_and_load_cache()
    test_load_cache_missing_returns_none()
    test_cache_age_days_fresh()
    test_cache_age_days_missing_returns_inf()
    test_save_cache_with_fallback_count()
    test_with_fallback_helper_uses_cached_on_failure()
    test_with_fallback_helper_resets_count_on_success()
    test_normalize_symbol()
    test_parse_iwb_csv_with_known_column()
    test_parse_iwb_csv_with_alternative_column()
    test_parse_iwb_csv_unknown_column_raises()
    print("[OK] momentum_data tests passed.")
