"""momentum_config.py 상수 정합성 테스트."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import momentum_config as cfg

def test_sector_thresholds_in_range():
    assert 50 <= cfg.SECTOR_RSI_MIN <= 70
    assert 0 < cfg.SECTOR_5D_MIN_PCT <= 10
    assert 0.8 <= cfg.SECTOR_HIGH_52W_RATIO <= 1.0

def test_m1_m2_m3_thresholds_monotonic():
    """M1 < M2 < M3 임계값 단조성 검증."""
    assert cfg.M1_RSI_MIN < cfg.M3_RSI_MIN
    assert cfg.M3_HIGH_52W_RATIO > cfg.SECTOR_HIGH_52W_RATIO  # M3가 더 빡셈

def test_prefilter_relaxed():
    """Pre-filter는 M1보다 완화되어야 함."""
    assert cfg.PREFILTER_3D_MIN_PCT < cfg.M1_3D_MIN_PCT

def test_risk_thresholds():
    assert cfg.RISK_OVERHEAT_RSI > cfg.M3_RSI_MIN
    assert cfg.RISK_PARABOLIC_PCT > 0
    assert cfg.RISK_EARLY_RSI_MIN < cfg.RISK_EARLY_RSI_MAX <= cfg.M3_RSI_MIN

def test_universe_caps():
    assert cfg.CACHE_TTL_DAYS == 7
    assert cfg.KR_LIQUIDITY_MIN_KRW == 10_000_000_000  # 100억원
    assert 0 < cfg.DAILY_MOVER_1D_PCT
    assert 0 < cfg.DAILY_MOVER_3D_PCT

def test_backtest_constants():
    assert cfg.BACKTEST_WINDOW_DAYS == 90
    assert 1 <= cfg.CONSECUTIVE_LOSS_THRESHOLD <= 5

def test_version():
    assert cfg.VERSION == "Momentum v1.0"

if __name__ == "__main__":
    test_sector_thresholds_in_range()
    test_m1_m2_m3_thresholds_monotonic()
    test_prefilter_relaxed()
    test_risk_thresholds()
    test_universe_caps()
    test_backtest_constants()
    test_version()
    print("[OK] momentum_config tests passed.")
