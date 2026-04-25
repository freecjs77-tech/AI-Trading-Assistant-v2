"""Scanner ticker/name/sector 데이터 무결성 검증."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from market_scanner import SP100_TICKERS, SP100_NAMES, TICKER_SECTORS

VALID_SECTORS = {
    "Tech", "Comm", "경기소비", "필수소비", "헬스케어",
    "금융", "산업", "에너지", "유틸", "부동산", "소재",
}

def test_no_duplicates():
    assert len(SP100_TICKERS) == len(set(SP100_TICKERS)), "중복 ticker 존재"

def test_size_in_range():
    n = len(SP100_TICKERS)
    assert 160 <= n <= 175, f"확장 후 종목 수 {n} (예상 범위 160~175)"

def test_every_ticker_has_name():
    missing = [t for t in SP100_TICKERS if t not in SP100_NAMES]
    assert not missing, f"이름 누락: {missing}"

def test_every_ticker_has_sector():
    missing = [t for t in SP100_TICKERS if t not in TICKER_SECTORS]
    assert not missing, f"섹터 누락: {missing}"

def test_sector_values_valid():
    invalid = {t: s for t, s in TICKER_SECTORS.items()
               if t in SP100_TICKERS and s not in VALID_SECTORS}
    assert not invalid, f"잘못된 섹터값: {invalid}"

if __name__ == "__main__":
    test_no_duplicates()
    test_size_in_range()
    test_every_ticker_has_name()
    test_every_ticker_has_sector()
    test_sector_values_valid()
    print("[OK] All scanner data integrity tests passed.")
