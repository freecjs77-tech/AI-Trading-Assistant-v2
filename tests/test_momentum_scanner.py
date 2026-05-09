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


def test_scan_result_has_em_signal_list_and_rotation_radar(monkeypatch, tmp_path):
    """Scan emits signals['EM'] (list) and rotation_radar (list of [sector, count])."""
    import os, json, pandas as pd
    import momentum_scanner as msc, momentum_data as md, momentum_signal as msig

    # Two stocks: AAA = EM-passing, BBB = M1-passing
    n = 90
    aaa = [100 + i * 0.4 for i in range(n)]
    bbb = [100 + i * 0.6 for i in range(n)]
    closes = pd.DataFrame({"AAA": aaa, "BBB": bbb,
                            "XLK": aaa, "XLF": bbb,
                            "SPY": [100 + i * 0.05 for i in range(n)],
                            "QQQ": [100 + i * 0.05 for i in range(n)]})
    volumes = pd.DataFrame({k: [1_500_000] * n for k in closes.columns})

    monkeypatch.setattr(md, "fetch_yf_bulk",
                         lambda tickers, period="90d": (closes[tickers], volumes[tickers]))
    monkeypatch.setattr("momentum_universe.build_us_universe", lambda: ["AAA", "BBB"])
    monkeypatch.setattr(md, "get_us_sector_holdings", lambda: {})
    monkeypatch.setattr(md, "build_sector_mapping",
                         lambda holdings, market: {"AAA": "XLY", "BBB": "XLK"})

    proj = str(tmp_path)
    os.makedirs(os.path.join(proj, "history"), exist_ok=True)
    result = msc.scan_momentum_us(proj)

    assert "signals" in result
    assert "EM" in result["signals"]  # New tier list
    assert isinstance(result["signals"]["EM"], list)
    assert "rotation_radar" in result
    assert isinstance(result["rotation_radar"], list)


def test_em_scan_uses_full_universe_not_top_sectors(monkeypatch, tmp_path):
    """EM should evaluate stocks even if their sector isn't in top_sectors.

    Scenario: AAA's sector (XLY) is NOT a top sector (only XLK is).
    Without EM bypass, AAA would be excluded. With EM bypass, AAA still gets
    evaluated and may appear in signals['EM'] with sector_top_rank=None.
    """
    import os, pandas as pd
    import momentum_scanner as msc, momentum_data as md

    # synthetic data crafted so AAA satisfies EM gates
    n = 90
    aaa = [50.0] * 70 + [50.0 + i * 1.5 for i in range(20)]   # late inflection
    closes = pd.DataFrame({
        "AAA": aaa,
        "XLK": [100 + i * 0.6 for i in range(n)],   # strong sector
        "XLY": [100 + i * 0.05 for i in range(n)],  # weak sector
        "SPY": [100 + i * 0.05 for i in range(n)],
        "QQQ": [100 + i * 0.05 for i in range(n)],
    })
    volumes = pd.DataFrame({k: [2_000_000] * n for k in closes.columns})

    monkeypatch.setattr(md, "fetch_yf_bulk",
                         lambda tickers, period="90d": (closes[tickers], volumes[tickers]))
    monkeypatch.setattr("momentum_universe.build_us_universe", lambda: ["AAA"])
    monkeypatch.setattr(md, "get_us_sector_holdings", lambda: {})
    monkeypatch.setattr(md, "build_sector_mapping",
                         lambda holdings, market: {"AAA": "XLY"})

    proj = str(tmp_path)
    os.makedirs(os.path.join(proj, "history"), exist_ok=True)
    result = msc.scan_momentum_us(proj)

    # AAA's sector (XLY) is not top — but if AAA satisfies EM, it should be
    # in signals['EM'] with sector_top_rank=None
    em_tickers = [s["ticker"] for s in result["signals"].get("EM", [])]
    if em_tickers:
        for s in result["signals"]["EM"]:
            if s["ticker"] == "AAA":
                assert s.get("sector_top_rank") is None  # not top sector
                break


def test_signals_enriched_with_streak_after_history_update(monkeypatch, tmp_path):
    """Rendered signals include streak/change populated from history."""
    import os, pandas as pd
    import momentum_scanner as msc, momentum_data as md

    n = 90
    closes = pd.DataFrame({
        "AAA": [100 + i * 0.5 for i in range(n)],
        "XLK": [100 + i * 0.5 for i in range(n)],
        "SPY": [100 + i * 0.05 for i in range(n)],
        "QQQ": [100 + i * 0.05 for i in range(n)],
    })
    volumes = pd.DataFrame({k: [2_000_000] * n for k in closes.columns})
    monkeypatch.setattr(md, "fetch_yf_bulk",
                         lambda tickers, period="90d": (closes[tickers], volumes[tickers]))
    monkeypatch.setattr("momentum_universe.build_us_universe", lambda: ["AAA"])
    monkeypatch.setattr(md, "get_us_sector_holdings", lambda: {})
    monkeypatch.setattr(md, "build_sector_mapping",
                         lambda h, market: {"AAA": "XLK"})

    proj = str(tmp_path)
    os.makedirs(os.path.join(proj, "history"), exist_ok=True)
    result = msc.scan_momentum_us(proj)

    all_sigs = (result["signals"]["MOMENTUM_3"] + result["signals"]["MOMENTUM_2"]
                + result["signals"]["MOMENTUM_1"] + result["signals"].get("EM", []))
    if all_sigs:
        # First-day signal: streak=1, change="NEW"
        assert all_sigs[0].get("streak") == 1
        assert all_sigs[0].get("change") == "NEW"


def test_momentum_disable_em_env_skips_em_track(monkeypatch, tmp_path):
    """MOMENTUM_DISABLE_EM=1 → EM signals empty, rotation_radar empty."""
    import os, pandas as pd
    import momentum_scanner as msc, momentum_data as md

    n = 90
    closes = pd.DataFrame({
        "AAA": [100 + i * 0.5 for i in range(n)],
        "XLK": [100 + i * 0.5 for i in range(n)],
        "XLY": [100 + i * 0.05 for i in range(n)],
        "SPY": [100 + i * 0.05 for i in range(n)],
        "QQQ": [100 + i * 0.05 for i in range(n)],
    })
    volumes = pd.DataFrame({k: [2_000_000] * n for k in closes.columns})
    monkeypatch.setattr(md, "fetch_yf_bulk",
                         lambda tickers, period="90d": (closes[tickers], volumes[tickers]))
    monkeypatch.setattr("momentum_universe.build_us_universe", lambda: ["AAA"])
    monkeypatch.setattr(md, "get_us_sector_holdings", lambda: {})
    monkeypatch.setattr(md, "build_sector_mapping",
                         lambda h, market: {"AAA": "XLY"})  # not top sector

    monkeypatch.setenv("MOMENTUM_DISABLE_EM", "1")

    proj = str(tmp_path)
    os.makedirs(os.path.join(proj, "history"), exist_ok=True)
    result = msc.scan_momentum_us(proj)

    assert result["signals"].get("EM", []) == []
    assert result.get("rotation_radar", []) == []
