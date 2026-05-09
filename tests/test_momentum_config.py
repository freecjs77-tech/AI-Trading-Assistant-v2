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

def test_universe_caps():
    assert cfg.CACHE_TTL_DAYS == 7
    assert cfg.KR_LIQUIDITY_MIN_KRW == 10_000_000_000  # 100억원
    assert 0 < cfg.DAILY_MOVER_1D_PCT
    assert 0 < cfg.DAILY_MOVER_3D_PCT

def test_backtest_constants():
    assert cfg.BACKTEST_WINDOW_DAYS == 90
    assert 1 <= cfg.CONSECUTIVE_LOSS_THRESHOLD <= 5

def test_version():
    # Updated to v1.5 — kept for backward-compat shape; see test_version_string_v15
    assert cfg.VERSION.startswith("Momentum v")

def test_maturity_constants_present():
    import momentum_config as cfg
    assert cfg.MATURITY_EXT_DIST_PCT == 8.0
    assert cfg.MATURITY_EXT_RSI == 75.0
    assert cfg.MATURITY_EARLY_DIST_PCT == 3.0
    assert cfg.MATURITY_EARLY_RSI == 68.0


def test_em_constants_present():
    import momentum_config as cfg
    assert cfg.EM_RET_5D_MIN_PCT == 4.0
    assert cfg.EM_RET_20D_MIN_PCT == 10.0
    assert cfg.EM_RSI_MAX == 72.0
    assert cfg.EM_DIST_EMA9_MAX == 8.0
    assert cfg.EM_VOL_RATIO_MIN == 1.05
    assert cfg.EM_EMA21_SLOPE_MIN_PCT == 0.0


def test_legacy_risk_tags_set():
    import momentum_config as cfg
    assert cfg.LEGACY_RISK_TAGS == frozenset({"EARLY", "EXTENDED"})


def test_risk_priority_only_two_tags():
    import momentum_config as cfg
    assert cfg.RISK_PRIORITY == ["OVERHEAT", "PARABOLIC"]


def test_history_schema_version_v2():
    import momentum_config as cfg
    assert cfg.HISTORY_SCHEMA_VERSION == 2


def test_version_string_v15():
    import momentum_config as cfg
    assert cfg.VERSION == "Momentum v1.5"


if __name__ == "__main__":
    test_sector_thresholds_in_range()
    test_m1_m2_m3_thresholds_monotonic()
    test_prefilter_relaxed()
    test_risk_thresholds()
    test_universe_caps()
    test_backtest_constants()
    test_version()
    test_maturity_constants_present()
    test_em_constants_present()
    test_legacy_risk_tags_set()
    test_risk_priority_only_two_tags()
    test_history_schema_version_v2()
    test_version_string_v15()
    print("[OK] momentum_config tests passed.")
