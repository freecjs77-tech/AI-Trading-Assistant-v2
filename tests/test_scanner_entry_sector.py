"""Verifies scan_sp100 entry dict includes an English sector field."""
import sys, os, inspect
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import market_scanner
from market_scanner import SP100_TICKERS, SP100_NAMES, TICKER_SECTORS, SECTOR_KO_TO_EN

VALID_ENGLISH_SECTORS = set(SECTOR_KO_TO_EN.values())

def test_scan_sp100_emits_translated_sector_field():
    src = inspect.getsource(market_scanner.scan_sp100)
    assert "SECTOR_KO_TO_EN.get(TICKER_SECTORS.get(ticker" in src, \
        "scan_sp100 entry는 SECTOR_KO_TO_EN으로 영문 변환된 sector를 emit해야 함"

def test_entry_sector_is_english():
    """entry["sector"]는 영문 표시명 (Yahoo Finance 분류)."""
    sample = SP100_TICKERS[0]
    sector_en = SECTOR_KO_TO_EN.get(TICKER_SECTORS.get(sample, ""), "—")
    assert sector_en != "—", f"{sample} 섹터 매핑 누락"
    assert sector_en in VALID_ENGLISH_SECTORS, \
        f"{sample} 섹터값이 유효한 영문이 아님: {sector_en}"

def test_known_ticker_sectors_english():
    """주요 ticker의 영문 섹터가 yfinance 분류와 일치."""
    expected = {
        "AAPL": "Technology",
        "JPM":  "Financial Services",
        "AMZN": "Consumer Cyclical",
        "GOOG": "Communication Services",
        "WMT":  "Consumer Defensive",
        "LLY":  "Healthcare",
        "XOM":  "Energy",
        "LIN":  "Basic Materials",
        "CAT":  "Industrials",
    }
    for tk, want in expected.items():
        got = SECTOR_KO_TO_EN.get(TICKER_SECTORS.get(tk, ""), "—")
        assert got == want, f"{tk}: expected {want}, got {got}"

if __name__ == "__main__":
    test_scan_sp100_emits_translated_sector_field()
    test_entry_sector_is_english()
    test_known_ticker_sectors_english()
    print("[OK] scan_sp100 entry sector field (English) verified.")
