"""Sector momentum 판정 테스트 — 필수/가속/RS/Score."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import momentum_signal as ms


def _sector(ret_5d, rsi, ret_20d=2.0, vol_ratio=1.0,
            close=110, ma20=100, high_20d=110, high_52w=115,
            macd_hist_trend="flat"):
    return {
        "ticker": "XLK",
        "ret_5d_pct": ret_5d, "rsi14": rsi,
        "ret_20d_pct": ret_20d, "volume_ratio": vol_ratio,
        "close": close, "ma20": ma20,
        "high_20d": high_20d, "high_52w": high_52w,
        "macd_hist_trend": macd_hist_trend,
    }


def test_sector_passes_all_required_gates():
    s = _sector(ret_5d=4.0, rsi=58)
    market = {"ret_5d_pct": 1.0}   # SPY 5d +1%
    result = ms.evaluate_sector(s, market_5d=1.0, peer_20d_returns=[2.0, 1.0])
    assert result["passes_required"] is True
    assert result["score"] >= 60  # trend(40) + 0 acc + rs


def test_sector_fails_required_low_5d_return():
    s = _sector(ret_5d=2.0, rsi=58)   # 3% 미달
    result = ms.evaluate_sector(s, market_5d=0.0, peer_20d_returns=[1.0])
    assert result["passes_required"] is False


def test_sector_fails_required_low_rsi():
    s = _sector(ret_5d=4.0, rsi=50)
    result = ms.evaluate_sector(s, market_5d=0.0, peer_20d_returns=[1.0])
    assert result["passes_required"] is False


def test_sector_fails_rs_against_market():
    """sector 5d ≤ market 5d → RS 게이트 실패."""
    s = _sector(ret_5d=4.0, rsi=58)
    result = ms.evaluate_sector(s, market_5d=5.0, peer_20d_returns=[1.0])
    assert result["passes_required"] is False
    assert result["fail_reason"] == "rs_below_market"


def test_sector_score_with_full_acceleration():
    """필수 + 가속 4/4 + RS 만점 → 100."""
    s = _sector(
        ret_5d=4.0, rsi=70,
        close=120, high_20d=110, high_52w=120,   # 신고가
        macd_hist_trend="rising",
        vol_ratio=1.5,
        ret_20d=8.0,                              # 상위 50%
    )
    result = ms.evaluate_sector(s, market_5d=0.0, peer_20d_returns=[3.0, 5.0])
    assert result["score"] == 100
    assert result["accel_count"] == 4


def test_sector_score_rs_scale():
    """RS 점수 = min(20, max(0, diff*5))."""
    s = _sector(ret_5d=5.0, rsi=58)
    # diff = +4 → rs = 20 (cap)
    r1 = ms.evaluate_sector(s, market_5d=1.0, peer_20d_returns=[1.0])
    assert r1["rs_score"] == 20

    # diff = +1 → rs = 5
    s2 = _sector(ret_5d=5.0, rsi=58)
    r2 = ms.evaluate_sector(s2, market_5d=4.0, peer_20d_returns=[1.0])
    assert r2["rs_score"] == 5


def test_select_top_sectors():
    sectors = [
        {"ticker": "XLK", "score": 95, "ret_5d_pct": 5.0, "passes_required": True},
        {"ticker": "XLF", "score": 80, "ret_5d_pct": 3.5, "passes_required": True},
        {"ticker": "XLE", "score": 80, "ret_5d_pct": 4.0, "passes_required": True},
        {"ticker": "XLV", "score": 30, "ret_5d_pct": 1.0, "passes_required": False},
    ]
    top = ms.select_top_sectors(sectors, n=3)
    assert [t["ticker"] for t in top] == ["XLK", "XLE", "XLF"]   # XLE 우선 (5d tiebreak)
    assert all(t["passes_required"] for t in top)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("[OK] momentum_signal sector tests passed.")
