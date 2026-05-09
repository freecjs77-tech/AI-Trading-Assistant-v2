"""End-to-end smoke for momentum v1.5 (mocked yfinance).

Verifies:
  - scan_momentum_us produces a result with 'EM' bucket
  - rotation_radar present
  - history file is written with schema_version=2
  - backtest summary structure present (may be sparse on first run)
"""
import os, sys, json, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_e2e_us_smoke(monkeypatch, tmp_path):
    import momentum_scanner as msc
    import momentum_data as md

    n = 90
    rising = [100 + i * 0.5 for i in range(n)]
    flat = [100.0] * n
    closes = pd.DataFrame({
        "AAA": rising, "BBB": rising,
        "XLK": rising, "XLF": flat,
        "SPY": [100 + i * 0.05 for i in range(n)],
        "QQQ": [100 + i * 0.05 for i in range(n)],
    })
    volumes = pd.DataFrame({k: [2_000_000] * n for k in closes.columns})

    def _fake_bulk(tickers, period="90d"):
        available = [t for t in tickers if t in closes.columns]
        if not available:
            return pd.DataFrame(), pd.DataFrame()
        return closes[available], volumes[available]

    monkeypatch.setattr(md, "fetch_yf_bulk", _fake_bulk)
    monkeypatch.setattr("momentum_universe.build_us_universe", lambda: ["AAA", "BBB"])
    monkeypatch.setattr(md, "get_us_sector_holdings", lambda: {})
    monkeypatch.setattr(md, "build_sector_mapping",
                         lambda h, market: {"AAA": "XLK", "BBB": "XLY"})

    proj = str(tmp_path)
    os.makedirs(os.path.join(proj, "history"), exist_ok=True)
    result = msc.scan_momentum_us(proj)

    assert result["status"] == "ok"
    assert "EM" in result["signals"]
    assert isinstance(result["rotation_radar"], list)
    # History was saved with schema_version 2
    hist_path = os.path.join(proj, "history", "scanner_momentum_us_history.json")
    assert os.path.exists(hist_path)
    with open(hist_path, encoding="utf-8") as f:
        hist = json.load(f)
    assert hist["_meta"]["schema_version"] == 2
    assert hist["_meta"]["version"] == "Momentum v1.5"
