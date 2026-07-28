"""Scanner ticker/name/sector 데이터 무결성 검증."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from market_scanner import SP100_TICKERS, SP100_NAMES, TICKER_SECTORS, SECTOR_KO_TO_EN

VALID_SECTORS = {
    "Tech", "통신", "소비순환", "필수소비", "헬스케어",
    "금융", "산업재", "에너지", "유틸", "부동산", "원자재",
}

def test_no_duplicates():
    assert len(SP100_TICKERS) == len(set(SP100_TICKERS)), "중복 ticker 존재"

def test_size_in_range():
    n = len(SP100_TICKERS)
    assert n == 50, f"축소 후 종목 수 {n} (예상 50)"

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

def test_every_korean_sector_has_english_mapping():
    """TICKER_SECTORS의 모든 한국어 키가 SECTOR_KO_TO_EN 에 존재해야 함."""
    used = {s for t, s in TICKER_SECTORS.items() if t in SP100_TICKERS}
    missing = used - set(SECTOR_KO_TO_EN.keys())
    assert not missing, f"영문 매핑 누락: {missing}"

def test_english_mapping_is_complete():
    """SECTOR_KO_TO_EN 키 = VALID_SECTORS 와 정확히 일치 (불일치 시 한쪽만 갱신된 사고 방지)."""
    assert set(SECTOR_KO_TO_EN.keys()) == VALID_SECTORS, \
        f"VALID_SECTORS와 SECTOR_KO_TO_EN 키 불일치: {set(SECTOR_KO_TO_EN.keys()) ^ VALID_SECTORS}"

if __name__ == "__main__":
    test_no_duplicates()
    test_size_in_range()
    test_every_ticker_has_name()
    test_every_ticker_has_sector()
    test_sector_values_valid()
    test_every_korean_sector_has_english_mapping()
    test_english_mapping_is_complete()
    print("[OK] All scanner data integrity tests passed.")
