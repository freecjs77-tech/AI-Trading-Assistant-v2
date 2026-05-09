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


def _stock(ret_3d=10, rsi=65, close=110, ma20=100, ma50=95,
           vol_ratio=1.3, macd_hist_trend="rising", high_52w=120,
           ret_5d=12.0):
    return {
        "ticker": "NVDA",
        "ret_3d_pct": ret_3d, "rsi14": rsi,
        "close": close, "ma20": ma20, "ma50": ma50,
        "volume_ratio": vol_ratio,
        "macd_hist_trend": macd_hist_trend,
        "high_52w": high_52w,
        "ret_5d_pct": ret_5d,
    }


def test_prefilter_passes():
    s = _stock(ret_3d=5.0, rsi=58, close=110, ma20=100)
    assert ms.passes_prefilter(s) is True


def test_prefilter_fails_low_ret_3d():
    s = _stock(ret_3d=2.0, rsi=58, close=110, ma20=100)
    assert ms.passes_prefilter(s) is False


def test_prefilter_fails_low_rsi():
    s = _stock(ret_3d=5.0, rsi=50, close=110, ma20=100)
    assert ms.passes_prefilter(s) is False


def test_prefilter_fails_below_ma20():
    s = _stock(ret_3d=5.0, rsi=58, close=98, ma20=100)
    assert ms.passes_prefilter(s) is False


def test_classify_m1_basic():
    """M1 = 3d≥8% AND RSI≥60 AND close>MA20 (그러나 M2 가속 미달)."""
    s = _stock(ret_3d=8.0, rsi=60, close=110, ma20=100,
               vol_ratio=1.0, macd_hist_trend="flat", ma50=120,  # M2 가속 0/3
               high_52w=200)                                    # M3 미달
    assert ms.classify_stage(s) == "MOMENTUM_1"


def test_classify_m2_with_2_of_3_acceleration():
    """M2 = M1 + 가속 3개 중 2개 이상 (volume_ratio≥1.2, macd rising, close>MA50)."""
    s = _stock(ret_3d=8.0, rsi=60, close=110, ma20=100,
               vol_ratio=1.3, macd_hist_trend="rising", ma50=95,
               high_52w=200)   # M3 미달
    assert ms.classify_stage(s) == "MOMENTUM_2"


def test_classify_m3_at_52w_high():
    """M3 = M2 + close ≥ high_52w × 0.99 + RSI ≥ 65."""
    s = _stock(ret_3d=10.0, rsi=70, close=120, ma20=100,
               vol_ratio=1.3, macd_hist_trend="rising", ma50=110,
               high_52w=120)
    assert ms.classify_stage(s) == "MOMENTUM_3"


def test_classify_m3_requires_rsi_65():
    """M2 조건 충족 + 52주 고가 도달, 그러나 RSI < 65 → M2."""
    s = _stock(ret_3d=10.0, rsi=63, close=120, ma20=100,
               vol_ratio=1.3, macd_hist_trend="rising", ma50=110,
               high_52w=120)
    assert ms.classify_stage(s) == "MOMENTUM_2"


def test_classify_returns_none_when_m1_fails():
    s = _stock(ret_3d=5.0, rsi=55, close=110, ma20=100)
    assert ms.classify_stage(s) is None


def test_risk_tags_overheat():
    s = _stock(rsi=82)
    tags = ms.compute_risk_tags(s, stage="MOMENTUM_2")
    assert "OVERHEAT" in tags


def test_risk_tags_parabolic():
    s = _stock()
    s["change_pct"] = 9.0   # 1d +9% > 8% threshold
    tags = ms.compute_risk_tags(s, stage="MOMENTUM_2")
    assert "PARABOLIC" in tags


def test_risk_tags_extended():
    """close가 MA20 대비 +12% → EXTENDED."""
    s = _stock(close=112, ma20=100)
    tags = ms.compute_risk_tags(s, stage="MOMENTUM_2")
    assert "EXTENDED" in tags


def test_risk_tags_early():
    """M1 + 60 ≤ RSI < 65 → EARLY."""
    s = _stock(rsi=62)
    tags = ms.compute_risk_tags(s, stage="MOMENTUM_1")
    assert "EARLY" in tags


def test_risk_tags_early_only_for_m1():
    """M2 / M3는 EARLY 부여 안 됨."""
    s = _stock(rsi=62)
    assert "EARLY" not in ms.compute_risk_tags(s, stage="MOMENTUM_2")


def test_risk_tags_multiple():
    """복수 태그 — OVERHEAT + PARABOLIC."""
    s = _stock(rsi=82)
    s["change_pct"] = 10.0
    tags = ms.compute_risk_tags(s, stage="MOMENTUM_3")
    assert "OVERHEAT" in tags and "PARABOLIC" in tags


def test_position_hint_priority():
    """OVERHEAT > PARABOLIC > EXTENDED > EARLY."""
    assert ms.position_hint(["EXTENDED", "PARABOLIC"]) == "눌림"
    assert ms.position_hint(["EXTENDED", "EARLY", "OVERHEAT"]) == "신중"
    assert ms.position_hint([]) == "적극"
    assert ms.position_hint(["EARLY"]) == "조기"


def test_evaluate_stock_returns_full_dict():
    s = _stock(ret_3d=10.0, rsi=70, close=109, ma20=100,
               vol_ratio=1.3, macd_hist_trend="rising", ma50=110,
               high_52w=110, ret_5d=12.0)
    s["change_pct"] = 2.0
    s["sector"] = "Technology"
    result = ms.evaluate_stock(s, sector_5d_return=4.0)
    assert result["stage"] == "MOMENTUM_3"
    assert result["risk_tags"] == []
    assert result["rs_vs_sector"] is True   # 12% > 4%
    assert result["hint"] == "적극"
    assert result["sector"] == "Technology"


def test_evaluate_stock_no_signal_when_below_m1():
    s = _stock(ret_3d=5.0, rsi=55)
    result = ms.evaluate_stock(s, sector_5d_return=2.0)
    assert result is None


def _stock_basic(dist_ema9=4.0, rsi=65, ema9=110, ema21=108):
    return {
        "ticker": "TEST",
        "dist_ema9_pct": dist_ema9, "rsi14": rsi,
        "ema9": ema9, "ema21": ema21,
    }


# EXTENDED — dist OR rsi
def test_maturity_extended_by_dist():
    s = _stock_basic(dist_ema9=8.0, rsi=60)  # at boundary
    assert ms.classify_maturity(s) == "EXTENDED"


def test_maturity_not_extended_just_below_dist():
    s = _stock_basic(dist_ema9=7.99, rsi=60)
    assert ms.classify_maturity(s) != "EXTENDED"


def test_maturity_extended_by_rsi():
    s = _stock_basic(dist_ema9=4.0, rsi=75.0)  # at boundary
    assert ms.classify_maturity(s) == "EXTENDED"


def test_maturity_not_extended_just_below_rsi():
    s = _stock_basic(dist_ema9=4.0, rsi=74.99)
    assert ms.classify_maturity(s) != "EXTENDED"


# EARLY — dist AND rsi AND ema9>ema21
def test_maturity_early_all_three_satisfied():
    s = _stock_basic(dist_ema9=2.0, rsi=64, ema9=110, ema21=108)
    assert ms.classify_maturity(s) == "EARLY"


def test_maturity_not_early_dist_at_boundary():
    s = _stock_basic(dist_ema9=3.0, rsi=64, ema9=110, ema21=108)  # < 3 strict
    assert ms.classify_maturity(s) != "EARLY"


def test_maturity_not_early_rsi_at_boundary():
    s = _stock_basic(dist_ema9=2.0, rsi=68.0, ema9=110, ema21=108)  # < 68 strict
    assert ms.classify_maturity(s) != "EARLY"


def test_maturity_not_early_when_ema9_below_ema21():
    s = _stock_basic(dist_ema9=2.0, rsi=64, ema9=108, ema21=110)
    assert ms.classify_maturity(s) != "EARLY"


# MID — fallback
def test_maturity_mid_fallback():
    s = _stock_basic(dist_ema9=5.0, rsi=70, ema9=110, ema21=108)
    assert ms.classify_maturity(s) == "MID"


def test_maturity_mid_when_ema9_below_ema21_but_not_extended():
    s = _stock_basic(dist_ema9=2.0, rsi=64, ema9=108, ema21=110)
    assert ms.classify_maturity(s) == "MID"


def test_maturity_none_when_required_fields_missing():
    s = {"ticker": "TEST", "rsi14": 65}  # no dist_ema9_pct
    assert ms.classify_maturity(s) is None


def test_maturity_extended_takes_precedence_over_early():
    """if both EXTENDED conditions true, EXTENDED wins (eval order)."""
    s = _stock_basic(dist_ema9=8.0, rsi=64, ema9=110, ema21=108)
    assert ms.classify_maturity(s) == "EXTENDED"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("[OK] momentum_signal sector tests passed.")
