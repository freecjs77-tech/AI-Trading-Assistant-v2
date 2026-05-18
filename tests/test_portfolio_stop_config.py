"""portfolio_stop_config 상수 정합성 테스트."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import portfolio_stop_config as cfg


def test_version_and_anchor():
    assert cfg.VERSION == "PortfolioStop v1.0"
    assert cfg.ANCHOR_DATE == "2026-01-02"


def test_modes_complete():
    """STOP_PARAMS는 4개 모드 모두 정의되어야."""
    for mode in ("CORE", "DEFENSIVE", "MOMENTUM", "HIGH_VOL"):
        assert mode in cfg.STOP_PARAMS


def test_pct_modes_no_atr_keys():
    """CORE/DEFENSIVE는 type='pct' + ratio 정의."""
    for mode in ("CORE", "DEFENSIVE"):
        p = cfg.STOP_PARAMS[mode]
        assert p["type"] == "pct"
        assert 0.85 <= p["ratio"] <= 0.95


def test_atr_modes_have_clamps():
    """MOMENTUM/HIGH_VOL은 multiplier + min_pct + max_pct 모두 정의.

    자산보호 cap 12% 적용 후 HIGH_VOL은 min==max (degenerate 12% fix) 허용.
    """
    for mode in ("MOMENTUM", "HIGH_VOL"):
        p = cfg.STOP_PARAMS[mode]
        assert p["type"] == "atr"
        assert p["multiplier"] >= 1
        assert 0 < p["min_pct"] <= p["max_pct"] <= 0.5


def test_max_pct_capped_at_12_percent():
    """자산보호 정책: ATR 모드의 max_pct는 12% 이내."""
    for mode in ("MOMENTUM", "HIGH_VOL"):
        assert cfg.STOP_PARAMS[mode]["max_pct"] <= 0.12 + 1e-9


def test_high_vol_min_floor_at_least_momentum():
    """HIGH_VOL의 노이즈 흡수 하한은 MOMENTUM 이상 (multiplier도 더 큼)."""
    m = cfg.STOP_PARAMS["MOMENTUM"]
    h = cfg.STOP_PARAMS["HIGH_VOL"]
    assert h["multiplier"] > m["multiplier"]
    assert h["min_pct"] >= m["min_pct"]


def test_category_to_mode_complete():
    """포트폴리오에 등장할 수 있는 모든 카테고리 매핑."""
    expected = {"ETF Core", "Bond", "Value/Dividend", "Growth",
                "KOSPI Stock", "KOSPI ETF", "Speculative", "Metal", "Other"}
    assert expected.issubset(set(cfg.CATEGORY_TO_MODE.keys()))


def test_kospi_etf_default_momentum():
    """KOSPI ETF 기본은 MOMENTUM. broad는 OVERRIDES로 CORE 승격."""
    assert cfg.CATEGORY_TO_MODE["KOSPI ETF"] == "MOMENTUM"


def test_overrides_broad_kr_etfs():
    for tk in ("102110", "458730", "379800", "379810"):
        assert cfg.MODE_OVERRIDES.get(tk) == "CORE", f"{tk} should be CORE"


def test_overrides_high_vol_individual():
    for tk in ("110990", "QLD", "ETHU", "SOXX", "IONQ", "CRCL"):
        assert cfg.MODE_OVERRIDES.get(tk) == "HIGH_VOL", f"{tk} should be HIGH_VOL"


def test_high_vol_keywords():
    assert "반도체" in cfg.HIGH_VOL_KEYWORDS
    assert "코스닥" in cfg.HIGH_VOL_KEYWORDS
    assert "조선" in cfg.HIGH_VOL_KEYWORDS
    assert "레버리지" in cfg.HIGH_VOL_KEYWORDS


def test_archive_grace_three_days():
    assert cfg.ARCHIVE_AFTER_DAYS_MISSING == 3


def test_max_daily_jump_pct():
    """40% 단일일 점프는 의심 (분할/bad tick 등)."""
    assert 0.30 <= cfg.MAX_DAILY_JUMP_PCT <= 0.50


def test_new_position_noise_calendar_days():
    """v1은 calendar days 기준."""
    assert cfg.NEW_POSITION_NOISE_DAYS == 14
    assert cfg.NEW_POSITION_DISPLAY_DOWNGRADE is True


def test_telegram_limits_descending():
    """심각도 높을수록 적게 (EXIT는 더 알리고 디테일 길어지므로 제한)."""
    assert cfg.TELEGRAM_MAX_EXIT_ITEMS <= cfg.TELEGRAM_MAX_EXIT_READY_ITEMS
    assert cfg.TELEGRAM_MAX_EXIT_READY_ITEMS <= cfg.TELEGRAM_MAX_TIGHT_ITEMS


def test_snapshot_retention_two_years():
    assert cfg.MAX_SNAPSHOT_DAYS == 730


if __name__ == "__main__":
    test_version_and_anchor()
    test_modes_complete()
    test_pct_modes_no_atr_keys()
    test_atr_modes_have_clamps()
    test_max_pct_capped_at_12_percent()
    test_high_vol_min_floor_at_least_momentum()
    test_category_to_mode_complete()
    test_kospi_etf_default_momentum()
    test_overrides_broad_kr_etfs()
    test_overrides_high_vol_individual()
    test_high_vol_keywords()
    test_archive_grace_three_days()
    test_max_daily_jump_pct()
    test_new_position_noise_calendar_days()
    test_telegram_limits_descending()
    test_snapshot_retention_two_years()
    print("[OK] portfolio_stop_config tests passed.")
