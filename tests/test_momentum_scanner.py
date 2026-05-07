"""Scanner entry point — heavily mocked smoke tests."""
import sys, os, tempfile, shutil
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def setup():
    return tempfile.mkdtemp(prefix="scanner_test_")


def teardown(d):
    shutil.rmtree(d, ignore_errors=True)


def test_scan_momentum_us_returns_skeleton_when_universe_empty():
    """Universe 비면 status='ok', signals 빈 dict."""
    import momentum_scanner as ms_scan
    tmp = setup()
    try:
        with patch("momentum_scanner.build_us_universe", return_value=[]):
            result = ms_scan.scan_momentum_us(tmp)
        assert result["status"] == "ok"
        assert result["market"] == "US"
        assert result["signals"]["MOMENTUM_3"] == []
        assert result["signals"]["MOMENTUM_2"] == []
        assert result["signals"]["MOMENTUM_1"] == []
    finally:
        teardown(tmp)


def test_scan_momentum_us_status_failed_on_critical_error():
    """fetch가 raise → status='failed'."""
    import momentum_scanner as ms_scan
    tmp = setup()
    try:
        with patch("momentum_scanner.build_us_universe",
                   side_effect=RuntimeError("network")):
            result = ms_scan.scan_momentum_us(tmp)
        assert result["status"] == "failed"
        assert "network" in result.get("error_message", "")
    finally:
        teardown(tmp)


def test_scan_momentum_includes_meta_fields():
    """결과 dict에 필요한 메타: market, version, scanned_count, top_sectors, signals, backtest_summary."""
    import momentum_scanner as ms_scan
    tmp = setup()
    try:
        with patch("momentum_scanner.build_us_universe", return_value=[]):
            result = ms_scan.scan_momentum_us(tmp)
        for key in ("market", "version", "scanned_count", "top_sectors",
                    "signals", "backtest_summary", "as_of"):
            assert key in result, f"missing key: {key}"
    finally:
        teardown(tmp)


def test_scan_momentum_kr_uses_kr_universe():
    """KR scanner는 build_kr_universe 사용."""
    import momentum_scanner as ms_scan
    tmp = setup()
    try:
        called = []
        def stub():
            called.append("kr")
            return []
        with patch("momentum_scanner.build_kr_universe", side_effect=stub):
            result = ms_scan.scan_momentum_kr(tmp)
        assert called == ["kr"]
        assert result["market"] == "KR"
    finally:
        teardown(tmp)
