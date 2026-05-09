"""
Market Momentum Scanner — 임계값 상수 단일 진입점.

모든 RSI/비율/TTL/필터값은 여기서만 정의. 추후 튜닝 시 한 곳에서만 변경.
"""

VERSION = "Momentum v1.5"
HISTORY_SCHEMA_VERSION = 2

# ── Sector momentum ─────────────────────────────────────
SECTOR_RSI_MIN = 55
SECTOR_5D_MIN_PCT = 3.0
SECTOR_HIGH_52W_RATIO = 0.95
SECTOR_HIGH_20D_USE = True
SECTOR_VOLUME_RATIO_MIN = 1.2
SECTOR_RS_SCALE = 5
SECTOR_TOP_N = 3

# ── Pre-filter (Top-sector 종목 게이트, M+ 평가용) ───────
PREFILTER_3D_MIN_PCT = 4.0
PREFILTER_RSI_MIN = 55

# ── M1/M2/M3 thresholds (v1.0 unchanged) ────────────────
M1_3D_MIN_PCT = 8.0
M1_RSI_MIN = 60
M2_VOLUME_RATIO_MIN = 1.2
M3_HIGH_52W_RATIO = 0.99
M3_RSI_MIN = 65

# ── Maturity classifier (v1.5 신규) ─────────────────────
MATURITY_EXT_DIST_PCT = 8.0     # dist_ema9_pct ≥ 8% → EXTENDED
MATURITY_EXT_RSI = 75.0         # rsi14 ≥ 75 → EXTENDED
MATURITY_EARLY_DIST_PCT = 3.0   # dist_ema9_pct < 3% (AND ...) → EARLY
MATURITY_EARLY_RSI = 68.0       # rsi14 < 68 (AND ...) → EARLY

# ── Emerging Momentum (EM) tier (v1.5 신규) ─────────────
EM_RET_5D_MIN_PCT = 4.0
EM_RET_20D_MIN_PCT = 10.0
EM_RSI_MAX = 72.0
EM_DIST_EMA9_MAX = 8.0
EM_VOL_RATIO_MIN = 1.05
EM_EMA21_SLOPE_MIN_PCT = 0.0    # rising = positive slope

# ── Risk tags (v1.5 정리: EARLY/EXTENDED 삭제) ──────────
RISK_OVERHEAT_RSI = 80
RISK_PARABOLIC_PCT = 8.0
LEGACY_RISK_TAGS = frozenset({"EARLY", "EXTENDED"})  # filtered on history read

# ── Position hint (Maturity + Risk 2-axis) ──────────────
POSITION_HINT = {
    None:           "적극",
    "OVERHEAT":     "신중",
    "PARABOLIC":    "눌림",
    "MAT_EXTENDED": "분할",
    "MAT_EARLY":    "관찰",
    # legacy keys for history read compatibility (never written)
    "EARLY":        "관찰",
    "EXTENDED":     "분할",
}
RISK_PRIORITY = ["OVERHEAT", "PARABOLIC"]

# ── Universe / Daily movers ────────────────────────────
CACHE_TTL_DAYS = 7
KR_LIQUIDITY_MIN_KRW = 10_000_000_000
DAILY_MOVER_1D_PCT = 5.0
DAILY_MOVER_3D_PCT = 8.0

# ── Backtest ──────────────────────────────────────────
BACKTEST_WINDOW_DAYS = 90
CONSECUTIVE_LOSS_THRESHOLD = 4
LEG_RETURN_HORIZONS_DAYS = (3, 5, 10)

# ── ETF 매핑 ──────────────────────────────────────────
US_SECTOR_ETFS = [
    "XLK", "XLF", "XLE", "XLV", "XLI",
    "XLY", "XLP", "XLU", "XLRE", "XLB", "XLC",
]
KR_SECTOR_ETFS = [
    "091160.KS", "091170.KS", "117460.KS", "261240.KS",
    "091180.KS", "229200.KS", "069500.KS",
]
US_MARKET_BENCHMARKS = ["SPY", "QQQ"]
KR_MARKET_BENCHMARKS = ["^KS11", "^KQ11"]
