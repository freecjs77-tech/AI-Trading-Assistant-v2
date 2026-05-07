"""
Market Momentum Scanner — 임계값 상수 단일 진입점.

모든 RSI/비율/TTL/필터값은 여기서만 정의. 추후 튜닝 시 한 곳에서만 변경.
"""

VERSION = "Momentum v1.0"

# ── Sector momentum ─────────────────────────────────────
SECTOR_RSI_MIN = 55
SECTOR_5D_MIN_PCT = 3.0
SECTOR_HIGH_52W_RATIO = 0.95            # 52주 고가 95% 이내
SECTOR_HIGH_20D_USE = True              # max(high_20d, high_52w * 0.95) 혼합
SECTOR_VOLUME_RATIO_MIN = 1.2
SECTOR_RS_SCALE = 5                     # rs_score = min(20, max(0, diff_pct * 5))
SECTOR_TOP_N = 3                        # Top 2~3 섹터 (3까지 표시)

# ── Pre-filter (종목 게이트) ───────────────────────────
PREFILTER_3D_MIN_PCT = 4.0              # 5%에서 4%로 완화 (초기 리더 포착)
PREFILTER_RSI_MIN = 55

# ── Stock momentum tiers ───────────────────────────────
M1_3D_MIN_PCT = 8.0
M1_RSI_MIN = 60
M2_VOLUME_RATIO_MIN = 1.2
M3_HIGH_52W_RATIO = 0.99
M3_RSI_MIN = 65

# ── Risk tags ──────────────────────────────────────────
RISK_OVERHEAT_RSI = 80
RISK_PARABOLIC_PCT = 8.0
RISK_EXTENDED_MA20_PCT = 10.0
RISK_EARLY_RSI_MIN = 60
RISK_EARLY_RSI_MAX = 65                 # M1 + 60 ≤ RSI < 65

# ── Universe / Daily movers ────────────────────────────
CACHE_TTL_DAYS = 7
KR_LIQUIDITY_MIN_KRW = 10_000_000_000   # 100억원 (5일 평균)
DAILY_MOVER_1D_PCT = 5.0
DAILY_MOVER_3D_PCT = 8.0

# ── Backtest ──────────────────────────────────────────
BACKTEST_WINDOW_DAYS = 90
CONSECUTIVE_LOSS_THRESHOLD = 4          # 최근 5개 leg 중 4개 손실 시 alert
LEG_RETURN_HORIZONS_DAYS = (3, 5, 10)

# ── Position hint (Risk → Action) ──────────────────────
POSITION_HINT = {
    None: "적극",
    "EARLY": "조기",
    "EXTENDED": "분할",
    "PARABOLIC": "눌림",
    "OVERHEAT": "신중",
}
# 복수 태그: priority 가장 높은 것 적용 (OVERHEAT > PARABOLIC > EXTENDED > EARLY)
RISK_PRIORITY = ["OVERHEAT", "PARABOLIC", "EXTENDED", "EARLY"]

# ── ETF 매핑 ──────────────────────────────────────────
US_SECTOR_ETFS = [
    "XLK", "XLF", "XLE", "XLV", "XLI",
    "XLY", "XLP", "XLU", "XLRE", "XLB", "XLC",
]
KR_SECTOR_ETFS = [
    "091160.KS",  # 반도체
    "091170.KS",  # 은행
    "117460.KS",  # 에너지화학
    "261240.KS",  # 200헬스케어
    "091180.KS",  # 자동차
    "229200.KS",  # KOSDAQ 150
    "069500.KS",  # KODEX 200
]
US_MARKET_BENCHMARKS = ["SPY", "QQQ"]
KR_MARKET_BENCHMARKS = ["^KS11", "^KQ11"]
