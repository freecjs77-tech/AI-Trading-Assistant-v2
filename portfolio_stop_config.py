# portfolio_stop_config.py
"""
Portfolio Stop Signal — 상수 단일 진입점.

모든 mode/임계값/그레이스/한계는 여기서만 정의. 추후 튜닝 시 한 곳에서만 변경.
"""

VERSION = "PortfolioStop v1.0"

# YTD 앵커 — 첫 실행 시 모든 종목 highest_close 계산 시작점
ANCHOR_DATE = "2026-01-02"

# ── Mode 매핑 ──────────────────────────────────────────────
DEFAULT_MODE = "MOMENTUM"

CATEGORY_TO_MODE = {
    "ETF Core":        "CORE",
    "Bond":            "DEFENSIVE",
    "Value/Dividend":  "CORE",
    "Growth":          "MOMENTUM",
    "KOSPI Stock":     "MOMENTUM",
    "KOSPI ETF":       "MOMENTUM",   # broad ETF만 OVERRIDES로 CORE 승격
    "Speculative":     "HIGH_VOL",
    "Metal":           "HIGH_VOL",
    "Other":           "MOMENTUM",
}

# 종목명에 포함되면 HIGH_VOL 자동 승격 (테마/레버리지 자동 대응)
HIGH_VOL_KEYWORDS = [
    "반도체", "코스닥", "조선", "레버리지", "2X", "AI", "로봇", "양자",
]

# Explicit overrides (categry/keyword 룰을 깨고 싶은 종목만)
MODE_OVERRIDES = {
    # KR broad ETFs → CORE (KOSPI ETF 기본 MOMENTUM 깨고 CORE)
    "102110": "CORE",   # TIGER 200
    "458730": "CORE",   # TIGER 미국배당다우존스
    "379800": "CORE",   # KODEX 미국S&P500
    "379810": "CORE",   # KODEX 미국나스닥100
    # Individual overrides
    "110990": "HIGH_VOL",   # 디아이티 (소형주 변동성)
    "QLD":    "HIGH_VOL",   # 2x 레버리지
    "ETHU":   "HIGH_VOL",   # crypto leverage
    "SOXX":   "HIGH_VOL",   # 섹터 ETF
    "IONQ":   "HIGH_VOL",   # 양자컴 변동성
    "CRCL":   "HIGH_VOL",   # 신규 IPO 변동성
}

# ── Stop 계산 파라미터 ──────────────────────────────────────
# pct: 단순 percentage stop (CORE/DEFENSIVE)
# atr: ATR 기반 + min/max% 양방향 clamp (MOMENTUM/HIGH_VOL)
STOP_PARAMS = {
    "CORE":      {"type": "pct",  "ratio": 0.88, "min_pct": None, "max_pct": None},  # 12%
    "DEFENSIVE": {"type": "pct",  "ratio": 0.92, "min_pct": None, "max_pct": None},  # 8%
    "MOMENTUM":  {"type": "atr",  "multiplier": 3, "min_pct": 0.08, "max_pct": 0.20},
    "HIGH_VOL":  {"type": "atr",  "multiplier": 4, "min_pct": 0.12, "max_pct": 0.30},
}

# ── 시그널 임계값 ───────────────────────────────────────────
TIGHT_RATIO = 1.05   # close <= stop * 1.05 → TIGHT
EXIT_BELOW_STOP_DAYS = 2   # below_stop_count >= 2 → EXIT (이전은 EXIT_READY)

# ── 매도 감지 / 라이프사이클 ───────────────────────────────
ARCHIVE_AFTER_DAYS_MISSING = 3   # 1일 race condition 흡수 (Actions 동시성/fetch 실패)

# Highest close 업데이트 가드 — 데이터 이상치(분할/bad tick/환율) 방어
MAX_DAILY_JUMP_PCT = 0.40        # today_close > prev_close × 1.40 → 갱신 스킵 + WARN

# 신규 진입 종목 처리
NEW_POSITION_NOISE_DAYS = 14     # **calendar days** (≈ 10 trading days)
                                 # (today - entry_date).days 기준
NEW_POSITION_DISPLAY_DOWNGRADE = True  # 신규 종목의 EXIT_READY/EXIT는 display만 TIGHT로

# Snapshot 보존 (영구 보존하되 운영적 cap)
MAX_SNAPSHOT_DAYS = 730          # 2년 rolling

# ── Telegram 표시 한계 ──────────────────────────────────────
TELEGRAM_MAX_EXIT_ITEMS       = 5
TELEGRAM_MAX_EXIT_READY_ITEMS = 7
TELEGRAM_MAX_TIGHT_ITEMS      = 12

# ── Bootstrap (yfinance YTD fetch) ─────────────────────────
BOOTSTRAP_TIMEOUT_SEC = 600      # 첫 실행 yfinance bulk fetch 최대 시간
