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


def test_fetch_indicators_includes_ema_fields(monkeypatch):
    """_fetch_indicators output dict has all EMA fields."""
    import pandas as pd
    import momentum_scanner as msc
    import momentum_data as md

    n = 90
    closes = pd.DataFrame({"AAA": [100 + i * 0.5 for i in range(n)]})
    volumes = pd.DataFrame({"AAA": [1_000_000] * n})

    def _fake_bulk(tickers, period="90d"):
        return closes, volumes
    monkeypatch.setattr(md, "fetch_yf_bulk", _fake_bulk)

    result = msc._fetch_indicators(["AAA"])
    assert "AAA" in result
    for key in ("ema9", "ema21", "ema65",
                "dist_ema9_pct", "dist_ema21_pct",
                "ema21_slope_3d_pct", "ema65_slope_5d_pct"):
        assert key in result["AAA"], f"missing {key}"
        assert result["AAA"][key] is not None  # 90 day series has all
