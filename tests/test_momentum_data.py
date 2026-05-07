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


def _make_krx_response(items):
    """Mock KRX API response builder."""
    from unittest.mock import MagicMock
    mock = MagicMock()
    mock.json.return_value = {"output": items}
    mock.raise_for_status = MagicMock()
    return mock


def test_fetch_kodex_holdings_parses_response():
    """fetch_krx_etf_holdings — KRX JSON 응답 파싱."""
    from unittest.mock import patch
    fake = _make_krx_response([
        {"ISU_SRT_CD": "005930", "ISU_ABBRV": "삼성전자"},
        {"ISU_SRT_CD": "000660", "ISU_ABBRV": "SK하이닉스"},
        {"ISU_SRT_CD": "035720", "ISU_ABBRV": "카카오"},
    ])
    with patch("momentum_data.requests.post", return_value=fake):
        tickers = md.fetch_krx_etf_holdings("069500")  # KODEX 200
    # KRX 6자리 코드 → yfinance .KS 부착
    assert tickers == ["005930.KS", "000660.KS", "035720.KS"]


def test_fetch_kodex_holdings_skips_invalid_rows():
    """fetch_krx_etf_holdings — 빈 코드/형식 오류 행 스킵."""
    from unittest.mock import patch
    fake = _make_krx_response([
        {"ISU_SRT_CD": "005930", "ISU_ABBRV": "삼성전자"},
        {"ISU_SRT_CD": "", "ISU_ABBRV": "현금"},
        {"ISU_SRT_CD": "12", "ISU_ABBRV": "잘못된 코드"},
    ])
    with patch("momentum_data.requests.post", return_value=fake):
        tickers = md.fetch_krx_etf_holdings("069500")
    assert tickers == ["005930.KS"]


def test_fetch_kosdaq_holdings_uses_kq_suffix():
    """KOSDAQ 150 holdings should use .KQ for KOSDAQ-listed codes."""
    from unittest.mock import patch
    fake = _make_krx_response([
        {"ISU_SRT_CD": "005930", "ISU_ABBRV": "삼성전자"},   # KOSPI → .KS
        {"ISU_SRT_CD": "110990", "ISU_ABBRV": "디아이티"},  # KOSDAQ → .KQ
    ])
    with patch("momentum_data.requests.post", return_value=fake):
        tickers = md.fetch_krx_etf_holdings("229200")
    assert "005930.KS" in tickers, f"KOSPI suffix wrong: {tickers}"
    assert "110990.KQ" in tickers, f"KOSDAQ suffix wrong: {tickers}"


def test_build_sector_mapping_us():
    """SPDR 섹터 ETF holdings → ticker → sector dict."""
    import momentum_data as md
    fake_holdings = {
        "XLK": ["AAPL", "MSFT", "NVDA"],
        "XLF": ["JPM", "BAC", "WFC"],
        "XLE": ["XOM", "CVX"],
    }
    mapping = md.build_sector_mapping(fake_holdings, market="us")
    assert mapping["AAPL"] == "XLK"
    assert mapping["JPM"] == "XLF"
    assert mapping["XOM"] == "XLE"


def test_build_sector_mapping_with_overlap_uses_priority():
    """한 종목이 여러 섹터에 → 우선순위 ETF (먼저 등장한 것)."""
    import momentum_data as md
    holdings = {
        "XLK": ["NVDA"],
        "SOXX": ["NVDA"],          # NVDA가 둘 다에 있음
    }
    mapping = md.build_sector_mapping(holdings, market="us")
    assert mapping["NVDA"] == "XLK"   # 첫 키 우선


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
    test_fetch_kodex_holdings_parses_response()
    test_fetch_kodex_holdings_skips_invalid_rows()
    test_fetch_kosdaq_holdings_uses_kq_suffix()
    test_build_sector_mapping_us()
    test_build_sector_mapping_with_overlap_uses_priority()
    print("[OK] momentum_data tests passed.")
