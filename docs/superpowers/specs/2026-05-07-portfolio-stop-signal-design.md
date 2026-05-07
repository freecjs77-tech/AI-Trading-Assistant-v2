# Portfolio Stop Signal System v1.0 — Design Spec

**Date**: 2026-05-07
**Status**: Approved (brainstorming complete)
**Owner**: freecjs77@gmail.com

## 0. Summary

현재 보유 포트폴리오 종목에 대해 **종가(EOD) 기준 trailing stop**을 매일 자동 계산하고, 4-tier 시그널(HOLD/TIGHT/EXIT_READY/EXIT)과 단계별 부분 청산 가이드를 리포트에 표시한다.

핵심 철학:
- **"언제 팔까?"를 자동 결정하지 않는다.** "현재 추세가 얼마나 위험해졌는가"를 정량화한다.
- **자동 매도 ❌, 매도 판단 보조 ✅** — 사용자가 reference로 활용.
- **부분 청산 중심** — 전량 청산 기본값 금지. trailing stop의 핵심은 "수익 보호".
- **기존 strategy.md 시그널과 공존** — 진입/확대 관점(BUY/TP) + 리스크 축소 관점(Stop)을 동시에 보여줌.

## 1. Goals & Non-goals

### Goals (v1.0)
- 매일 me + wife 포트폴리오의 모든 보유 종목에 대해 trailing stop 시그널 자동 산출
- 종목별 mode 차등 적용 (CORE/DEFENSIVE/MOMENTUM/HIGH_VOL) — `get_ticker_class()` 카테고리 기반 자동 매핑 + keyword 자동 승격 + explicit override
- 4-state signal machine: HOLD → TIGHT → EXIT_READY → EXIT (2일 연속 종가 하회 = EXIT)
- 단계별 청산 가이드: HOLD=Hold / TIGHT=Trim 10~15% / EXIT_READY=Trim 30~50% / EXIT=Exit trading portion
- 전용 페이지 `portfolio_stops_<DATE>.html` (me/wife 별도) + 기존 portfolio 페이지에 Stop Signal 컬럼 추가
- Telegram 합산 1개 알림 (me/wife)
- `signal_history` 영구 보존 (전략 효과 검증용 audit trail)
- 향후 v2 partial trim tracking 가능하도록 schema 여유

### Non-goals (이번 작업 제외)
- 자동 주문 / 실거래 발주
- 실시간(intraday) stop — 종가 기준만
- High-volume breakdown EXIT 트리거 — v1.1 후보
- regime-adaptive / sector-aware stop — v1.1 후보
- core/trading 자동 분리, position-aware stop, partial execution tracking — v2 후보
- `entry_price` 정확성 (실거래 평단 매칭) — v2 정교화 (v1은 trailing stop 목적상 불필요)

## 2. Architecture Overview

### 2.1 위치 — Pipeline Step 4c3 (신규)

```
Step 4    Signal judgment
Step 4b   Existing scanners (SP100/ETF/KOSPI/Watchlist)
Step 4c   Politician trades
Step 4c2  Momentum scanners (US, KR)        ← 별도 스펙 (예정)
Step 4c3  ★ Portfolio Stop Signals          ← 본 스펙
Step 4d   YTD benchmark
Step 5    Report generation
Step 5d   Secondary owner reports (wife stops 페이지도 여기서 함께 생성)
```

번호 4c3로 잡아 기존 4d/5/5a/5b/5c/6/6b/7 번호 변경 없음.

### 2.2 모듈 구성 (단방향 의존: config → history → signal → report)

```
portfolio_stop_config.py     # 상수 — mode 매핑, override, keyword, multiplier, min %
portfolio_stop_history.py    # state I/O — load/save, highest_close 갱신, soft-archive
portfolio_stop_signal.py     # Stop 계산 + 4-state 시그널 판정 (단일 진입점)
portfolio_stop_report.py     # HTML 페이지 생성 (Hero/Cards/Table/Footer)
```

`portfolio_stop_signal.py`가 entry point — `generate_portfolio_stop_signals(project_dir, owner, market_data, portfolio, today)` 함수가 위 4개 모듈을 조립.

**반환 스키마**:
```python
{
    "status": "ok" | "error",
    "owner": "me" | "wife",
    "date": "2026-05-07",
    "summary": {"HOLD": 28, "TIGHT": 7, "EXIT_READY": 3, "EXIT": 1},
    "positions": [  # display_signal severity desc 정렬
        {"ticker": "TSLA", "mode": "MOMENTUM", "highest_close": 410.0,
         "highest_close_date": "2026-02-15", "current_close": 358.5,
         "stop_price": 380.0, "gap_pct": -5.7,
         "raw_signal": "EXIT", "display_signal": "EXIT",
         "display_downgraded": False, "is_new_position": False,
         "below_stop_count": 3, "action": "Exit trading portion"},
        # 신규 진입 + raw EXIT_READY → display TIGHT 다운그레이드 예시
        {"ticker": "CRCL", "mode": "HIGH_VOL", "highest_close": 112.5,
         "highest_close_date": "2026-04-30", "current_close": 95.0,
         "stop_price": 95.30, "gap_pct": -0.31,
         "raw_signal": "EXIT_READY", "display_signal": "TIGHT",
         "display_downgraded": True, "is_new_position": True,
         "below_stop_count": 1, "action": "Trim 10~15% (신규)"},
        ...
    ],
    "changes": [  # 전일 대비 변경 (raw_signal 기준 — 정확성)
        {"ticker": "NVDA", "from": "HOLD", "to": "TIGHT"},
        ...
    ],
    "page_path": "reports/portfolio_stops_2026-05-07.html"  # 또는 wife
}
```

### 2.3 핵심 설계 원칙: Market data vs Position state 분리

| 책임 | 모듈 | 데이터 |
|---|---|---|
| **Market-derived** (가격, ATR, RSI 등) | `fetch_market_data.py` (기존, 일부 확장) | `screenshots/market_data_<DATE>.json` |
| **Position lifecycle state** (entry, highest_close, breach count, signal history) | `portfolio_stop_history.py` (신규) | `history/portfolio_stops.json`, `history/portfolio_stops_wife.json` |

이 분리가 중요한 이유:
- ATR은 종목 자체의 시장 데이터 (언제 샀는지 무관)
- `highest_close`는 포지션 컨텍스트 (보유 시작점에 따라 달라짐)
- 향후 v2에서 position-aware stop / split position(core/trading) 도입 시 상태 모델 깔끔하게 확장 가능

### 2.4 신규 / 수정 파일 정리

**신규 (8개)**:
- `portfolio_stop_config.py`
- `portfolio_stop_history.py`
- `portfolio_stop_signal.py`
- `portfolio_stop_report.py`
- `templates/portfolio_stops.html`
- `history/portfolio_stops.json` (런타임 자동 생성)
- `history/portfolio_stops_wife.json` (런타임 자동 생성)
- `tests/test_portfolio_stop_signal.py`

**수정 (5개)**:
- `fetch_market_data.py` — `atr14`, `atr14_pct` 필드 추가 (NaN/Zero 안전장치)
- `pipeline.py` — Step 4c3 삽입, Step 5d secondary owner loop에 wife stop 처리 추가
- `report_generator.py` — `generate_portfolio_stops_page()` 호출 통합, portfolio 페이지 컬럼 추가
- `telegram_sender.py` — `send_portfolio_risk_summary()` 추가
- `templates/report_template.html` — 메인 리포트 nav에 `🛡 Portfolio Risk` 링크 + portfolio 테이블 Stop Signal 컬럼

### 2.5 실패 격리

```python
# pipeline.py Step 4c3
try:
    from portfolio_stop_signal import generate_portfolio_stop_signals
    stop_result_me = generate_portfolio_stop_signals(project_dir, owner="me",
                                                      market_data=market_data,
                                                      portfolio=portfolio)
    if stop_result_me and stop_result_me.get("status") == "ok":
        print(f"  OK Stop signals: {stop_result_me['summary']}")
except Exception as e:
    print(f"  WARN [Step 4c3] Portfolio stop (me) failed: {e}")
    stop_result_me = None
```

wife도 같은 패턴, 별도 try. 실패 시 해당 페이지/Telegram 섹션 숨김. 기존 파이프라인 영향 없음.

## 3. Mode System

### 3.1 우선순위 (3-tier)

```python
def get_stop_mode(ticker: str, name: str, category: str) -> str:
    # 1. Explicit override (가장 높은 우선순위)
    if ticker in MODE_OVERRIDES:
        return MODE_OVERRIDES[ticker]

    # 2. Keyword auto-detect (테마/레버리지 ETF 자동 승격)
    if any(kw in (name or "") for kw in HIGH_VOL_KEYWORDS):
        return "HIGH_VOL"

    # 3. Category mapping (가장 일반적)
    return CATEGORY_TO_MODE.get(category, DEFAULT_MODE)
```

### 3.2 상수 정의

```python
# portfolio_stop_config.py

DEFAULT_MODE = "MOMENTUM"

CATEGORY_TO_MODE = {
    "ETF Core":        "CORE",
    "Bond":            "DEFENSIVE",
    "Value/Dividend":  "CORE",
    "Growth":          "MOMENTUM",
    "KOSPI Stock":     "MOMENTUM",
    "KOSPI ETF":       "MOMENTUM",   # ⚠ broad ETF만 OVERRIDES로 CORE 승격
    "Speculative":     "HIGH_VOL",
    "Metal":           "HIGH_VOL",
    "Other":           "MOMENTUM",
}

# 종목명에 포함되면 HIGH_VOL 자동 승격 (테마/레버리지 자동 대응)
HIGH_VOL_KEYWORDS = [
    "반도체", "코스닥", "조선", "레버리지", "2X", "AI", "로봇", "양자",
]

# Explicit override (categry/keyword 룰을 깨고 싶은 종목만)
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
    "SOXX":   "HIGH_VOL",   # 섹터 ETF (반도체 키워드로도 잡히지만 명시)
    "IONQ":   "HIGH_VOL",   # 양자컴 (키워드 보완)
    "CRCL":   "HIGH_VOL",   # 신규 IPO 변동성
}

# Stop multipliers + minimum stop floor + maximum stop ceiling
STOP_PARAMS = {
    "CORE":      {"type": "pct",  "ratio": 0.88,                "min_pct": None, "max_pct": None},  # 12%
    "DEFENSIVE": {"type": "pct",  "ratio": 0.92,                "min_pct": None, "max_pct": None},  # 8%
    "MOMENTUM":  {"type": "atr",  "multiplier": 3, "min_pct": 0.08, "max_pct": 0.20},  # ATR×3, [8%, 20%]
    "HIGH_VOL":  {"type": "atr",  "multiplier": 4, "min_pct": 0.12, "max_pct": 0.30},  # ATR×4, [12%, 30%]
}

# 자동 분류 안 잡히는 카테고리 fallback
FALLBACK_CATEGORY = "Other"

# 매도 감지 — N일 연속 portfolio.md 부재 시 soft-archive
ARCHIVE_AFTER_DAYS_MISSING = 3   # 1일 race condition (Actions 동시성/fetch 실패) 흡수

# Highest close 업데이트 가드 — 데이터 이상치(분할/bad tick/환율) 방어
MAX_DAILY_JUMP_PCT = 0.40        # today_close > prev_close × 1.40 → highest 갱신 스킵 + WARN

# 신규 진입 종목 처리
NEW_POSITION_NOISE_DAYS = 14     # entry_date 후 N **calendar days** (≈ 10 trading days)
                                 # 단순 계산: (today - entry_date).days
                                 # 이 기간은 noise 가능성 마킹 (ⓝ 표시) + display 다운그레이드
NEW_POSITION_DISPLAY_DOWNGRADE = True   # 신규 종목의 EXIT_READY/EXIT는 display만 TIGHT로 표기

# Snapshots retention (영구 보존하되 운영적 cap)
MAX_SNAPSHOT_DAYS = 730          # 2년 rolling. 더 오래된 snapshot은 archive 또는 prune

# Telegram per-category 표시 한계
TELEGRAM_MAX_EXIT_ITEMS       = 5
TELEGRAM_MAX_EXIT_READY_ITEMS = 7
TELEGRAM_MAX_TIGHT_ITEMS      = 12
```

### 3.3 Stop 계산 공식

```python
# 기존 portfolio_data.py에 정교한 regex 헬퍼 (^[0-9][0-9A-Z]{5}$) 이미 존재 → 재사용
from portfolio_data import is_korean_ticker
# 매칭: 005930, 102110, 0153K0, 000660 등
# 제외: AAPL, 1INCH (5자), 3LTS (4자), 2X (2자) — 안전

def round_stop(price: float, ticker: str) -> float:
    """KR 종목은 정수, US 종목은 소수 둘째 자리."""
    if is_korean_ticker(ticker):
        return float(round(price))
    return round(price, 2)

def calculate_stop(highest_close: float, atr14: float | None,
                   mode: str, ticker: str) -> float:
    p = STOP_PARAMS[mode]
    if p["type"] == "pct":
        # CORE/DEFENSIVE: 단순 percentage stop
        return round_stop(highest_close * p["ratio"], ticker)
    # ATR 기반 (MOMENTUM/HIGH_VOL)
    if atr14 is None or atr14 <= 0:
        # ATR fail-soft → min_pct 강제 적용 (분할/데이터 오류 시)
        return round_stop(highest_close * (1.0 - p["min_pct"]), ticker)
    atr_distance = atr14 * p["multiplier"]
    min_distance = highest_close * p["min_pct"]
    max_distance = highest_close * p["max_pct"]
    # min ≤ distance ≤ max (clamp 양방향)
    distance = max(atr_distance, min_distance)
    distance = min(distance, max_distance)
    return round_stop(highest_close - distance, ticker)
```

**왜 양방향 clamp 필요한가**:
- **min_pct (floor)**: ATR이 비정상적으로 작은 종목(분할 직후/거래 정체)에서 stop이 너무 촘촘하게 잡혀 노이즈성 EXIT 방지
- **max_pct (ceiling)**: earnings 발표/폭락 직후/volatility explosion 상황에서 ATR이 급등해 stop이 너무 멀어지는 것 방지 (의미 없는 stop 회피)

**Rounding 정책**:
- US 종목 (`AAPL`, `NVDA`, ETF 등): 소수 2자리 (`$874.32`)
- KR 종목 (`110990`, `005930`, `0153K0` 등): 정수 (`71,430`)
  - KR은 호가 단위가 큼 (1,000원 이상은 보통 100원/500원 호가)

## 4. Signal Logic

### 4.1 4-State Machine

| State | Trigger | Action 안내 | UI 색상 |
|---|---|---|---|
| 🟢 **HOLD** | `close > stop × 1.05` | Hold | 초록 |
| 🟡 **TIGHT** | `stop < close ≤ stop × 1.05` | Trim 10~15% | 노랑 |
| 🟠 **EXIT_READY** | `close < stop` AND `below_stop_count == 1` | Trim 30~50% | 주황 |
| 🔴 **EXIT** | `close < stop` AND `below_stop_count ≥ 2` | Exit trading portion | 빨강 |

**`below_stop_count` 갱신 규칙** (매일 종가 기준):
```python
# `<=` 사용: 정확히 stop을 찍고 끝난 날도 하회로 인정 (자연스러운 경계)
if today_close <= stop_price:
    below_stop_count += 1
else:
    below_stop_count = 0   # 회복 시 리셋 (비연속 누적 안 함)

if below_stop_count >= 2:
    signal = "EXIT"
elif below_stop_count == 1:
    signal = "EXIT_READY"
elif today_close <= stop_price * 1.05:
    signal = "TIGHT"
else:
    signal = "HOLD"
```

**원칙**: 종가(close) 기준만 인정. intraday low/spike는 무시. stop hunting / shakeout 노이즈 제거.

**v1 EXIT 트리거는 2일 rule만**. high-volume breakdown 같은 추가 트리거는 v1.1 후보로 명시 제외.

### 4.1.1 신규 종목 display downgrade

`is_new_position == True` (entry_date 후 `NEW_POSITION_NOISE_DAYS=14` calendar days 이내)인 종목이 EXIT_READY 또는 EXIT 시그널을 발생시키면 **display 레이어에서만 TIGHT로 다운그레이드**:

```python
def evaluate_signal(stored, today_close, stop_price, today, entry_date):
    # 1) raw signal 계산 (4-state machine)
    raw = compute_raw_signal(today_close, stop_price, stored.below_stop_count)

    # 2) is_new_position 판정 — calendar days 기준 (단순/명확)
    days_since_entry = (today - entry_date).days
    is_new_position = days_since_entry <= NEW_POSITION_NOISE_DAYS

    # 3) display signal 결정
    if NEW_POSITION_DISPLAY_DOWNGRADE and is_new_position \
            and raw in ("EXIT_READY", "EXIT"):
        display = "TIGHT"
        downgraded = True
    else:
        display = raw
        downgraded = False

    return {
        "raw_signal": raw,                # 진실의 원천 — 모든 데이터 저장에 사용
        "display_signal": display,        # UI/Telegram 표시 전용
        "display_downgraded": downgraded, # 분석/디버깅 편의
        "is_new_position": is_new_position,
    }
```

**규칙**:
- **데이터 레이어** (`positions.last_signal`, `snapshots.signal`, `signal_history.signal`)에는 **raw signal** 저장 (audit/analytics/backtest 정확성)
- **HTML 테이블 / Telegram 메시지**에는 **display_signal** 사용
- **표시**: `🟡 TIGHT (new)` — 신규 진입 종목임을 명시. 사용자에게 "위험은 있으나 신뢰도 낮음" 동시 전달

**필드 분리 이유**:
- 향후 분석에서 "신규 종목 false EXIT 빈도" 측정 가능 → threshold calibration
- raw 자체를 다운그레이드하면 데이터 오염 → backtest/연구 왜곡

**Calendar days vs Trading days**:
- v1은 **calendar days** 사용 (`(today - entry_date).days`) — 단순/명확
- 14 calendar days ≈ 10 trading days 근사. 주말 포함이라 약간 더 긴 buffer (안전한 방향)
- v1.1에서 trading days 정밀화 가능 (`snapshots` 키 카운트)

**이유 (UX 관점)**: 신규 진입 직후 며칠은 highest_close 누적 부족으로 stop이 매우 가까움 → 정상 변동도 EXIT_READY/EXIT를 잘못 발동 → 시스템 신뢰도 저하. 진짜 추세 붕괴는 14일 이후에도 지속될 것이므로 noise 기간 동안만 톤 다운.

### 4.2 Suggested Action 매핑

```python
ACTION_MAP = {
    "HOLD":       "Hold",
    "TIGHT":      "Trim 10~15%",
    "EXIT_READY": "Trim 30~50%",
    "EXIT":       "Exit trading portion",
}
```

범위 그대로 표시 (단일값 변환 안 함). 사용자 판단 보조 시스템 정신 유지.

### 4.3 Visual Escalation (presentation layer only — state는 4개 그대로)

`below_stop_count`가 길어질수록 EXIT 상태 안에서 시각적 강조:
- `count == 2`: 빨강 #dc2626
- `count == 3`: 빨강 #b91c1c (조금 진하게)
- `count >= 4`: 빨강 #991b1b (가장 진하게)

CSS 그라데이션만, 시그널 데이터/로직 동일. 백테스트/통계 분석 단순성 유지.

### 4.4 UI 메타 표시

```
NVDA   🟠 EXIT_READY (1d below stop)
AMD    🔴 EXIT (3d below stop)
```

`(Nd below stop)` 메타를 작게 병기 → state는 같아도 지속 일수 한눈에.

## 5. Bootstrap & Lifecycle

### 5.1 Bootstrap 룰 (요약)

| 상황 | entry_date | highest_close 시작값 |
|---|---|---|
| **A. 첫 실행** (`portfolio_stops.json` 부재) | 모든 종목 = `2026-01-02` | `max(close from 2026-01-02 to today)` (yfinance bulk fetch 1회) |
| **B. 신규 종목** (portfolio에 등장, stops.json엔 active 키 없음) | `today` (포트폴리오 갱신 날짜) | `today_close` |
| **C. 재매수** (소프트-아카이브 항목이 portfolio에 재등장) | `today` (B와 동일 처리) | `today_close`. signal_history엔 `REOPENED` 이벤트 추가 |
| **D. 일상 incremental** | 변경 없음 | `update_highest_close_safe(stored, today_close, prev_close)` (Section 5.1.1 참조) |

#### 5.1.1 `highest_close` 안전 갱신 (데이터 이상치 방어)

```python
def update_highest_close_safe(stored, today_close: float, prev_close: float | None):
    """분할/bad tick/환율 꼬임/액면분할 직후 등 비정상적 jump 방어."""
    # 가드 1: 비정상적 단일일 jump (40% 이상) → 갱신 스킵
    if prev_close and prev_close > 0:
        jump_ratio = today_close / prev_close
        if jump_ratio > (1.0 + MAX_DAILY_JUMP_PCT):
            log_warn(f"{stored.ticker}: suspicious daily jump "
                     f"prev={prev_close} → today={today_close} "
                     f"({(jump_ratio - 1) * 100:.1f}% in 1 day) — skip highest update")
            return  # 변경 없음
    # 정상: highest 갱신
    if today_close > stored.highest_close:
        stored.highest_close = today_close
        stored.highest_close_date = today
```

**40% 임계값 근거**: 일반 종목의 정상 일일 변동은 ±15% 이내. 20-30%는 earnings gap up 정도. 40%+ 단일일 상승은 거의 항상 분할/병합/데이터 오류이므로 highest_close 갱신 보류가 안전.

**수동 복구**: 스킵된 종목은 다음날 정상 데이터 들어오면 자동 갱신 (이미 더 높아진 가격이 그대로 highest_close가 됨).

### 5.2 매도 감지 (soft-archive, 3일 grace)

```python
# 매일 portfolio.md ticker set과 stops.json positions 키 비교
for ticker, stored in stored_positions.items():
    if stored.status == "closed":
        continue
    if ticker in portfolio_tickers:
        # 정상 — missing 카운터 리셋
        stored.missing_since = None
        continue
    # portfolio에서 사라짐
    if stored.missing_since is None:
        stored.missing_since = today
    days_missing = (today - stored.missing_since).days
    if days_missing >= ARCHIVE_AFTER_DAYS_MISSING:
        # 3일 연속 부재 → soft-archive
        stored.status = "closed"
        stored.closed_date = today
        stored.signal_history.append({
            "date": today, "signal": "CLOSED",
            "event": "removed_from_portfolio",
            "missing_since": stored.missing_since,
        })
```

**3일 grace 이유** (1일 → 3일로 보강):
- portfolio.md 저장 타이밍 / wife portfolio 생성 race
- GitHub Actions 동시성 race
- fetch 실패로 일시적 누락
- ticker normalization 일시 오류

이런 단발성 누락이 `active → closed → reopen` 사이클을 만들면 highest_close가 매번 reset되고 signal_history가 오염됨. 3일 grace로 거의 모든 race condition 흡수.

`status: "closed"`는 daily 재계산에서 스킵. 시그널 history 보존. 4일째 portfolio에 다시 등장하면 reopen 처리(Section 5.1 C).

### 5.3 신규 종목 — 첫 며칠 노이즈 안내

신규 종목은 `highest_close = today_close`로 시작 → stop이 매우 가까움 → 다음 -3% 하락만 와도 TIGHT/EXIT_READY 발동 가능. 표식 + 푸터 안내:

- **종목 행에 ⓝ 표시**: `entry_date` 기준 10거래일 이내(`is_new_position = True`)
- **푸터 명시**:
  > ⚠ 신규 진입 종목은 trailing stop 시작 직후 며칠은 시그널 노이즈 가능성이 큽니다 (highest_close 누적 부족).

`NEW_POSITION_NOISE_DAYS = 10` 상수로 `portfolio_stop_config.py`에 분리.

### 5.4 추가매수(position size 증가) 처리

`shares` 변경만 기록, **`highest_close` / `entry_date` 변경 없음**. trailing stop은 가격 기반이므로 share 수와 무관. v2 partial trim tracking 확장 위해 schema에 `last_size_change` 필드 보존.

## 6. Data Schema

### 6.1 `history/portfolio_stops.json` (positions + snapshots 분리)

```json
{
  "_meta": {
    "schema_version": 1,
    "owner": "me",
    "last_updated": "2026-05-07",
    "anchor_date": "2026-01-02"
  },
  "positions": {
    "NVDA": {
      "status": "active",
      "mode": "MOMENTUM",
      "entry_date": "2026-01-02",
      "highest_close": 945.0,
      "highest_close_date": "2026-05-05",
      "current_stop": 874.0,
      "below_stop_count": 0,
      "shares": 49.878541,
      "last_size_change": "2026-04-17",
      "missing_since": null,
      "last_signal": "HOLD",
      "last_action": "Hold",
      "last_evaluated": "2026-05-07"
    },
    "TSLA": {
      "status": "closed",
      "mode": "MOMENTUM",
      "entry_date": "2026-01-02",
      "highest_close": 410.0,
      "highest_close_date": "2026-02-15",
      "current_stop": 380.0,
      "below_stop_count": 2,
      "last_signal": "EXIT",
      "missing_since": "2026-04-27",
      "closed_date": "2026-04-30"
    }
  },
  "snapshots": {
    "2026-05-07": {
      "NVDA": {
        "signal": "HOLD",
        "close": 920.0,
        "stop": 874.0,
        "gap_pct": 5.26,
        "below_stop_count": 0,
        "is_new_position": false,
        "display_downgraded": false
      },
      "AAPL": {
        "signal": "TIGHT",
        "close": 264.5,
        "stop": 252.0,
        "gap_pct": 4.96,
        "below_stop_count": 0,
        "is_new_position": false,
        "display_downgraded": false
      },
      "CRCL": {
        "signal": "EXIT_READY",
        "close": 95.0,
        "stop": 95.30,
        "gap_pct": -0.31,
        "below_stop_count": 1,
        "is_new_position": true,
        "display_downgraded": true
      }
    },
    "2026-05-06": {"...": "..."}
  }
}
```

**구조 분리 이점**:
- `positions`: 현재 상태 only (조회 빠름, diff 단순)
- `snapshots`: 일자별 audit trail (영구 보존, aggregation 용이)
- 향후 분석 (EXIT 후 회복률, TIGHT 빈도, sector별 stop 효율 등) 시 snapshots만 따로 처리 가능

**Snapshot 보존 정책 (rolling 2년)**:
- `MAX_SNAPSHOT_DAYS = 730` — `positions` 키 (현재 상태)는 영구 보존, `snapshots`만 730일 이전 자동 prune
- 더 오래된 데이터가 필요한 경우: 별도 archive export (`history/portfolio_stops_archive_YYYY.json`) — v1.1 후보
- 39종목 × 730일 = 약 28K 엔트리, 파일 크기 ~3-5MB 예상 (충분히 관리 가능)

### 6.2 `fetch_market_data.py` 출력 확장

기존 종목 처리 라인에 2필드 추가:

```python
# 기존: ADX 계산에서 내부적으로 TR 사용 중. ATR을 별도 노출.
def calc_atr(high, low, close, period=14):
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()

atr14_series = calc_atr(high, low, close, period=14)
atr14 = float(atr14_series.iloc[-1]) if not pd.isna(atr14_series.iloc[-1]) else None

# 출력에 추가
"atr14":     round(atr14, 4) if atr14 else None,
"atr14_pct": round((atr14 / last_close) * 100, 2)
             if atr14 and last_close > 0 else None,
```

**안전장치**: NaN 검사 + ZeroDivision 방어. `atr14 is None`일 때 stop 계산은 `min_pct` fallback으로 자동 처리 (Section 3.3).

기존 `signal_judge.py`는 이 필드를 사용하지 않으므로 부수 효과 없음.

### 6.3 momentum-scanner 스펙과의 필드 중복 조정

`change_5d_pct`, `change_20d_pct`는 momentum-scanner v1.0 spec(2026-05-06)에서도 추가 예정. 본 스펙은 이 필드를 사용하지 않으나, 두 작업이 둘 다 `fetch_market_data.py`를 건드리므로:
- 먼저 머지되는 쪽이 추가 (단순 추가, conflict 없음)
- 둘 다 `atr14`/`atr14_pct`만 본 스펙에서 책임

## 7. Output / UI

### 7.1 신규 페이지 — `reports/portfolio_stops_<DATE>.html` (me) / `portfolio_stops_wife_<DATE>.html` (wife)

```
┌─ Hero ───────────────────────────────────────────────────────────┐
│ 🛡 Portfolio Risk Dashboard — me              2026-05-07         │
│ Anchor: 2026-01-02  ·  Tracked: 39 positions  ·  Mode v1.0       │
└──────────────────────────────────────────────────────────────────┘

┌─ Summary Cards ─────────────────────────────────────────────────┐
│ 🟢 HOLD: 28    🟡 TIGHT: 7    🟠 EXIT_READY: 3    🔴 EXIT: 1     │
└──────────────────────────────────────────────────────────────────┘

┌─ Signal Changes (vs previous trading day) ──────────────────────┐
│ NVDA: HOLD → TIGHT                                               │
│ TSLA: EXIT_READY → EXIT (2d below stop)                          │
│ AMD:  TIGHT → HOLD ✓                                             │
└──────────────────────────────────────────────────────────────────┘

┌─ Main Table (sorted by signal severity desc) ───────────────────┐
│ Ticker | Mode      | Highest    | Current   | Stop    | Stop Gap│
│        |           | (date)     |           |         |         │
│ Signal (Nd)         | Action                                    │
├──────────────────────────────────────────────────────────────────┤
│ TSLA   | MOMENTUM  | $410.00    | $358.50   | $380.00 | -5.7%   │
│        |           | (02-15)    |           |         |  ↓      │
│ 🔴 EXIT (3d)         | Exit trading portion                     │
├──────────────────────────────────────────────────────────────────┤
│ NVDA   | MOMENTUM  | $945.00    | $920.00   | $874.00 | +5.3%   │
│        |           | (05-05)    |           |         |  ✓      │
│ 🟡 TIGHT             | Trim 10~15%                              │
├──────────────────────────────────────────────────────────────────┤
│ 005930 | MOMENTUM  | ₩78,500    | ₩72,100   | ₩71,430 | +0.9%   │
│        |           | (04-22)    |           |         |  ⚠      │
│ 🟡 TIGHT             | Trim 10~15%                              │
├──────────────────────────────────────────────────────────────────┤
│ CRCL   | HIGH_VOL  | $112.50    | $98.20    | $95.30  | +3.0% ⓝ │
│        |           | (04-30)    |           |         |  ⓝ new  │
│ 🟡 TIGHT (new)       | Trim 10~15% (신규 진입 — noise 가능)      │
└──────────────────────────────────────────────────────────────────┘
* KR 종목 stop은 정수 (₩71,430), US 종목은 소수 둘째 자리 ($874.00)
* ⓝ = 신규 진입 종목 (entry_date 후 10거래일 이내)

┌─ Footer ─────────────────────────────────────────────────────────┐
│ Anchor: 2026-01-02 · Bootstrap: yfinance YTD high                │
│ ⚠ 신규 진입 직후 종목은 highest_close 누적 부족으로 시그널 노이즈 │
│   가능. (해당 시 종목 옆 ⓝ 표시)                                  │
│ ⚠ 자동 매도 아님 — 매도 판단 보조 reference 시스템                 │
│ Mode: CORE 12% · DEFENSIVE 8% · MOMENTUM ATR×3+8%min ·            │
│       HIGH_VOL ATR×4+12%min                                       │
└──────────────────────────────────────────────────────────────────┘
```

### 7.2 컬럼 명세

| 컬럼 | 데이터 |
|---|---|
| Ticker | 클릭 시 `/details/<ticker>.html` (ⓝ 신규 진입 종목 표시) |
| Mode | CORE / DEFENSIVE / MOMENTUM / HIGH_VOL (배지) |
| Highest (date) | `highest_close` + `highest_close_date` (KR=정수, US=소수 2자리) |
| Current | 오늘 종가 |
| Stop | `current_stop` (KR=정수, US=소수 2자리) |
| Stop Gap | `(close - stop) / stop × 100`, 부호 + 색상 그라데이션 |
| Signal (Nd) | 4-state 배지 + `(below_stop_count d)` 메타. 신규 진입은 display 다운그레이드 (`TIGHT (new)`) |
| Action | Hold / Trim 10~15% / Trim 30~50% / Exit trading portion |

### 7.3 Stop Gap 컬럼 색상 그라데이션

| Stop Gap 범위 | 색상 | 의미 |
|---|---|---|
| `> +10%` | 초록 (green-600) | 충분히 안전 |
| `+3% ~ +10%` | 연초록 (green-300) | 정상 |
| `0% ~ +3%` | 노랑 (yellow-400) | stop 근접 (TIGHT 영역과 일치) |
| `< 0%` | 빨강 (red-500 → red-700, `below_stop_count`에 따라 진하게) | 하회 |

**컬럼명 "Gap" → "Stop Gap"** (또는 "Dist %") — "Gap"은 갭상승/갭하락으로 해석되기 쉬워 명시적으로 변경.

### 7.4 기존 portfolio 페이지 통합

`templates/report_template.html`의 portfolio 테이블에 컬럼 1개 추가:

```
| Ticker | Strategy Signal | Stop Signal | P/L | ... |
|--------|-----------------|-------------|-----|-----|
| NVDA   | TOP_SIGNAL      | 🟡 TIGHT    | +42% |    |
| AMD    | BUY             | 🟢 HOLD     | +15% |    |
| 디아이티| HOLD            | 🟠 EXIT_READY| +690% |   |
```

두 시그널 공존 — 서로 다른 관점(진입/확대 vs 리스크 축소)을 동시에 보여줌. Stop 컬럼은 클릭 시 `portfolio_stops_<DATE>.html`로 이동.

### 7.5 Nav 통합

`templates/report_template.html` 상단:
```
[📊 Portfolio] [🔥 Momentum] [🛡 Portfolio Risk] [📈 Trend] [🏛 Politicians] [🧪 Backtest]
                                   ↑ 신규 (me 페이지로 링크, wife는 wife 리포트에서 따로)
```

stop 결과 None 시 해당 버튼 hide.

## 8. Telegram

### 8.1 함수 시그니처

```python
# telegram_sender.py
def send_portfolio_risk_summary(stop_result_me: dict, stop_result_wife: dict | None,
                                 report_base_url: str, date_str: str) -> bool:
    """me + wife 합산 1개 메시지. 알림 노이즈 방지."""
```

### 8.2 메시지 포맷 (≤ 3500자 trim, 카테고리별 표시 한계)

**카테고리별 최대 표시 개수** (오버플로우 시 `+N more...` 추가):
- EXIT: 최대 5개
- EXIT_READY: 최대 7개
- TIGHT: 최대 12개 (이름만, 액션 생략)

```
🛡 Portfolio Risk Summary — 2026-05-07

[me]
🟢 HOLD (28)  🟡 TIGHT (7)  🟠 EXIT_READY (3)  🔴 EXIT (1)

🔴 EXIT (1):
  TSLA → Exit trading portion (3d below stop)

🟠 EXIT_READY (3):
  PLTR → Trim 30~50% (1d)
  IONQ → Trim 30~50% (1d)
  005380 → Trim 30~50% (1d)

🟡 TIGHT (7):
  NVDA, AMZN, GOOGL, MSFT, AAPL, 디아이티, 0153K0

[wife]
🟢 HOLD (12)  🟡 TIGHT (1)  🟠 EXIT_READY (0)  🔴 EXIT (0)

🟡 TIGHT (1):
  SCHD

📊 me:   https://freecjs77-tech.github.io/.../portfolio_stops_2026-05-07.html
📊 wife: https://freecjs77-tech.github.io/.../portfolio_stops_wife_2026-05-07.html
```

**오버플로우 예시** (EXIT가 8개일 때):
```
🔴 EXIT (8):
  TSLA → Exit trading portion (3d)
  PLTR → Exit trading portion (2d)
  005380 → Exit trading portion (4d)
  CRCL → Exit trading portion (2d)
  IONQ → Exit trading portion (2d)
  + 3 more — see report
```

**신규 진입 종목 (display downgrade) 처리**: raw signal이 EXIT_READY/EXIT여도 신규 진입(`is_new_position=True`)이면 TIGHT 카테고리에 노출 (Section 4.1.1).

### 8.3 발송 시점

기존 `send_report()` 호출 직후 (Step 5b 직후), 별도 try/except. 메시지 길이 안전장치 `message[:3500]`.

## 9. Operations & Integration

### 9.1 `pipeline.py` 변경

**Step 4c3 신규 삽입** (정치인 거래 / momentum 다음, YTD benchmark 이전):

```python
# Step 4c3: Portfolio Stop Signals (me)
print("[Step 4c3] Portfolio stop signals (me)...")
stop_result_me = None
try:
    from portfolio_stop_signal import generate_portfolio_stop_signals
    stop_result_me = generate_portfolio_stop_signals(
        project_dir=project_dir, owner="me",
        market_data=market_data, portfolio=portfolio, today=today,
    )
    if stop_result_me and stop_result_me.get("status") == "ok":
        s = stop_result_me["summary"]
        print(f"  OK [4c3] me: HOLD={s['HOLD']} TIGHT={s['TIGHT']} "
              f"EXIT_READY={s['EXIT_READY']} EXIT={s['EXIT']}")
except Exception as e:
    print(f"  WARN [4c3] me stop signals failed: {e}")
```

**Step 5d (secondary owner loop) 안에 wife stop 추가**:
```python
# 기존 wife report 생성 다음에
try:
    stop_result_wife = generate_portfolio_stop_signals(
        project_dir=project_dir, owner=_owner,
        market_data=_owner_market, portfolio=_owner_portfolio, today=today,
    )
    # 페이지 생성도 같은 자리에서
except Exception as e:
    print(f"  WARN [4c3] {_owner} stop signals failed: {e}")
```

**Step 5 인자 추가**:
```python
generate_report(..., portfolio_stop_result=stop_result_me, ...)
```

`generate_report`는 stop_result가 있으면 portfolio 테이블에 Stop Signal 컬럼 추가, 없으면 컬럼 자체 hide.

**Step 5b (Telegram)**: `send_report` 직후 `send_portfolio_risk_summary` 별도 호출.

### 9.2 환경변수

기존 `SKIP_SCANNERS=1`처럼 추가:
- `SKIP_STOPS=1`: Step 4c3 스킵 (회귀 테스트용)

### 9.3 GitHub Actions 워크플로우

`.github/workflows/daily-report.yml`:

**복원 패턴 확장**:
```yaml
git checkout gh-pages -- history/portfolio_stops.json \
                         history/portfolio_stops_wife.json \
                         || true
```

**푸시 단계**: 기존 `history/` 디렉토리 add에 자동 포함됨 (별도 작업 불필요).

**Pre-commit 가드**: `.githooks/`의 history shrink 가드는 기존 dict-form JSON에 적용. `portfolio_stops.json`도 dict-form이므로 자동 보호 대상. `positions` 키 개수가 줄면 abort → soft-archive(키 보존 + status만 변경) 정책과 자연 일치.

### 9.4 신규 패키지 의존성

**없음** — `pandas`, `yfinance`, `jinja2` 모두 기존 사용 중.

## 10. Tests

### 10.1 단위 테스트 (`tests/test_portfolio_stop_signal.py`)

- `test_get_stop_mode_priority`: override > keyword > category 순서 검증
- `test_calculate_stop_per_mode`: CORE/DEFENSIVE/MOMENTUM/HIGH_VOL 각 공식
- `test_minimum_stop_floor`: ATR 비정상 작을 때 min_pct floor 동작
- `test_atr_none_fallback`: `atr14 is None` 시 min_pct로 fallback
- `test_signal_state_transitions`:
  - HOLD → TIGHT (close = stop × 1.04)
  - TIGHT → EXIT_READY (close = stop × 0.99, count=1)
  - EXIT_READY → EXIT (count 2 누적)
  - EXIT → HOLD (회복 시 count reset)
- `test_below_stop_count_reset`: 1일 하회 후 회복 시 count=0 확인

### 10.2 Bootstrap / Lifecycle 테스트

- `test_first_run_bootstrap`: stops.json 없을 때 모든 종목 entry_date=2026-01-02
- `test_new_position_today_anchor`: 기존 stops.json 있고 신규 ticker 등장 시 entry_date=today, highest=today_close
- `test_soft_archive_on_removal`: portfolio에서 사라지면 status=closed, history 보존
- `test_reopen_after_archive`: archived ticker 재등장 시 fresh bootstrap + REOPENED 이벤트
- `test_position_size_change_no_highest_reset`: shares 변경 시 highest_close 변동 없음

### 10.3 Golden sample (회귀 방지)

- `tests/fixtures/golden_stops_2026-05-07.json`: NVDA/AMD/디아이티 고정 입력 → 항상 같은 시그널 결과
- 시그널 로직 리팩토링 시 깨짐 즉시 감지

### 10.4 통합 테스트

- `SKIP_SCANNERS=1` 모드로 빠른 회귀 (~1분)
- 페이지 생성 / Telegram 메시지 포맷 smoke test
- yfinance 실패 → 이전 stop 유지 + WARN 로그 확인
- ATR fail → percentage fallback 동작 확인

## 11. Risks & Mitigations

| 항목 | 리스크 | 완화책 |
|---|---|---|
| 첫 bootstrap yfinance 호출 (~45종목 ~85일치) | rate limit, 시간 | bulk download 사용. 실패 시 portfolio 단위 재시도 + 다음 실행 retry |
| ATR 계산 실패 (분할, 데이터 부족) | stop 계산 불가 | `min_pct` percentage fallback (Section 3.3) |
| ATR explosion (earnings/폭락 직후 변동성 급증) | stop 거리가 너무 멀어짐 (의미 없는 stop) | `max_pct` ceiling clamp — MOMENTUM 20%, HIGH_VOL 30% |
| portfolio.md 일시적 누락 (1일 race) | 종목 사라짐 → false archive → highest reset 사이클 | `ARCHIVE_AFTER_DAYS_MISSING=3` grace + `missing_since` 추적 |
| 데이터 이상치 (분할/bad tick/환율 꼬임) | highest_close가 비정상값으로 갱신 | `MAX_DAILY_JUMP_PCT=0.40` 가드 — 단일일 +40% 초과 시 highest 갱신 스킵 + WARN |
| 신규 종목 첫 며칠 노이즈 | 즉시 EXIT_READY/EXIT 발동 → 시스템 신뢰도 저하 | (1) 종목 옆 ⓝ 표시 (2) display 레이어에서 EXIT/EXIT_READY → TIGHT 다운그레이드 (raw signal은 보존) |
| stops.json 손실 | 전체 history 사라짐 | gh-pages 백업 + pre-commit shrink 가드 자동 적용 |
| Stop과 strategy 시그널 충돌 (TOP_SIGNAL + EXIT_READY 등) | 사용자 혼란 | 두 시그널 모두 표시 — "강하지만 과열" 같은 의미 있는 정보로 노출 |
| Mode 매핑 누락 (신규 ETF) | DEFAULT_MODE=MOMENTUM 자동 적용 | keyword auto-detect로 대부분 흡수. 누락 발견 시 OVERRIDES에 추가 |
| KR 종목 stop rounding (소수점) | 호가 단위 mismatch | `round_stop()` market-aware: KR=정수, US=소수 2자리 |
| Telegram 메시지 길이 폭증 (EXIT 종목 多) | 3500자 trim에서 잘림 | 카테고리별 표시 한계 (EXIT≤5, EXIT_READY≤7, TIGHT≤12) + `+N more...` |
| snapshots 파일 크기 무한 증가 | 장기 운영 시 GB 단위 부담 | `MAX_SNAPSHOT_DAYS=730` 2년 rolling prune. 더 오래된 데이터는 archive export (v1.1) |

## 12. v1.0 Scope vs Future

### v1.0 (이번 작업)

**필수 포함**:
- 4-state signal machine (HOLD/TIGHT/EXIT_READY/EXIT)
- Mode 시스템 (3-tier: override > keyword > category) + minimum stop floor
- Bootstrap (2026-01-02 앵커) + 신규 종목 감지 + soft-archive
- me + wife 양쪽 owner 적용 (별도 JSON/HTML, Telegram 합산 1개)
- `portfolio_stops.json` 영구 audit trail (positions + snapshots 분리)
- 전용 페이지 + 기존 portfolio 페이지 컬럼 통합
- `fetch_market_data.py`에 `atr14`/`atr14_pct` 추가
- Telegram 합산 알림
- Golden sample 테스트

### v1.1 (후속, 우선순위 순)

1. **High-volume breakdown EXIT 트리거** — 거래량 급증 + close < stop 동시 시 즉시 EXIT (1일 confirm 단축)
2. **Position-size grace** — `ARCHIVE_AFTER_DAYS_MISSING=N` 가변 (스캔 중 일시적 누락 흡수)
3. **EXIT 후 회복 통계** — snapshots 누적 활용 (회복률, MaxDD)

### v2 (장기)

- **Position-aware stop** — core/trading 자동 분리, 각각 별도 trailing stop
- **Partial trim tracking** — `last_size_change` 활용해 실거래 trim 추적
- **Regime-adaptive stop** — VIX/master_switch에 따른 multiplier 동적 조정
- **Sector-aware stop** — 섹터 momentum 약화 시 stop 강화
- **Volatility-adaptive stop** — `atr14_pct` 기반 동적 mode 승격

## 13. 결정 요약 (Q&A 기록)

| # | 질문 | 결정 |
|---|---|---|
| Q1 | 기존 보유 종목 highest_close 부트스트랩 | 전 종목 **2026-01-02 YTD 앵커** (yfinance bulk 1회 fetch) |
| Q2 | Stop signal 적용 범위 | 전 종목 적용 (참고용 — BIL 등 제외 없음) |
| Q3 | Mode 매핑 | category auto + keyword auto + explicit override (3-tier 우선순위), KOSPI ETF 기본 MOMENTUM, broad ETF만 CORE override |
| Q4 | ATR 데이터 소스 | A+A2 — `fetch_market_data.py`에 `atr14`/`atr14_pct` 추가, `highest_close`는 `portfolio_stops.json`이 자체 관리 (incremental) |
| Q5 | Wife 포트폴리오 적용 | 양쪽 모두 (B 패턴) — owner별 JSON/HTML, Telegram은 합산 1개 |
| Q6 | 매도/재매수 lifecycle | Soft-archive (status=closed). 재매수 = 신규 종목 처리 (today anchor). 첫 실행은 2026-01-02 앵커 |
| Q7-1 | Gap 컬럼 형식 | `(close - stop) / stop × 100`, 색상 그라데이션 (>10%/3-10%/0-3%/<0%) |
| Q7-2 | Suggested Action | 범위 그대로 (`Trim 10~15%`) |
| Q7-3 | History 보존 | 영구 보존 + positions/snapshots 구조 분리 |
| Q7-4 | 추가매수 처리 | highest 변경 없음. `shares`/`last_size_change` 기록만 (v2 확장 여유) |
| Q7-5 | EXIT 트리거 | v1은 2-consecutive-close-breach only. high-volume breakdown은 v1.1 |
| Q7-6 | 기존 strategy 시그널 관계 | 공존 — Strategy + Stop 두 컬럼 동시 표시 |
| Q8 | 5-state 확장 (EXIT_CONFIRMED) | v1은 4-state 유지. 시각 강조만 CSS 그라데이션 (presentation layer only) |
| Q9 | `ARCHIVE_AFTER_DAYS_MISSING` | 1일 → **3일 grace** + `missing_since` 필드 (race condition 흡수) |
| Q10 | `highest_close` 갱신 가드 | `MAX_DAILY_JUMP_PCT=0.40` — 단일일 +40% 초과 시 갱신 스킵 + WARN |
| Q11 | "Gap" 컬럼명 | "Stop Gap" (또는 "Dist %") — "Gap"은 갭상승/하락으로 해석되기 쉬움 |
| Q12 | 신규 종목 노이즈 처리 | display 레이어에서 EXIT_READY/EXIT → TIGHT 다운그레이드 (raw signal 보존) |
| Q13 | `below_stop_count` 계산 기준 | `today_close <= stop_price` (정확히 stop 찍은 날 포함) |
| Q14 | Telegram 표시 한계 | 카테고리별 한계 (EXIT≤5, EXIT_READY≤7, TIGHT≤12) + `+N more...` |
| Q15 | Stop rounding | market-aware: KR=정수, US=소수 2자리 |
| Q16 | `snapshots` 보존 | 영구 → **2년 rolling** (`MAX_SNAPSHOT_DAYS=730`). archive export는 v1.1 |
| Q17 | Stop 거리 ceiling | `MAX_STOP_DISTANCE_PCT` — MOMENTUM 20%, HIGH_VOL 30% (ATR explosion 방어) |
| Q18 | KR ticker 검출 헬퍼 | 기존 `portfolio_data.is_korean_ticker()` 재사용 (regex `^[0-9][0-9A-Z]{5}$`, `.KS`/`.KQ` 접미사 지원) |
| Q19 | Display downgrade 필드 분리 | `raw_signal`/`display_signal`/`display_downgraded` 별도 저장 — analytics/디버깅 정확성 |
| Q20 | NEW_POSITION_NOISE_DAYS 기준 | **calendar days** (`(today - entry_date).days`), 14일 (≈ 10 trading days). v1.1에서 trading days 정밀화 가능 |
