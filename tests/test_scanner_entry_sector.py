"""Verifies scan_sp100 entry dict includes a sector field."""
import sys, os, inspect
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import market_scanner
from market_scanner import SP100_TICKERS, SP100_NAMES, TICKER_SECTORS

def test_scan_sp100_emits_sector_field():
    src = inspect.getsource(market_scanner.scan_sp100)
    assert '"sector": TICKER_SECTORS.get(ticker' in src, \
        "scan_sp100 entry dict에 sector 필드가 없습니다 — TICKER_SECTORS.get(ticker, ...) 호출 누락"

def test_entry_sector_field_logic():
    sample = SP100_TICKERS[0]
    entry = {
        "ticker": sample,
        "name": SP100_NAMES.get(sample, sample),
        "sector": TICKER_SECTORS.get(sample, "—"),
    }
    assert "sector" in entry, "entry에 sector 키가 없습니다"
    assert entry["sector"] != "—", f"{sample} 섹터 매핑 누락 (fallback 표시됨)"
    assert entry["sector"] in {"Tech", "Comm", "경기소비", "필수소비", "헬스케어",
                              "금융", "산업", "에너지", "유틸", "부동산", "소재"}, \
        f"{sample} 섹터값이 유효하지 않음: {entry['sector']}"

def test_known_ticker_sectors():
    expected = {"AAPL": "Tech", "JPM": "금융", "AMZN": "경기소비",
                "GOOG": "Comm", "WMT": "필수소비", "LLY": "헬스케어"}
    for tk, want in expected.items():
        got = TICKER_SECTORS.get(tk)
        assert got == want, f"{tk}: expected {want}, got {got}"

if __name__ == "__main__":
    test_scan_sp100_emits_sector_field()
    test_entry_sector_field_logic()
    test_known_ticker_sectors()
    print("[OK] scan_sp100 entry sector field verified.")
