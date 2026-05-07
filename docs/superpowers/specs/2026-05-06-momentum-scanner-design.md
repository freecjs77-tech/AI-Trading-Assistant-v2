# Market Momentum Scanner v1.0 — Design Spec

**Date**: 2026-05-06
**Status**: Approved (brainstorming complete)
**Owner**: freecjs77@gmail.com

## 0. Summary

기존 저점매수 계단(1st/2nd/3rd_BUY) 스캐너와 **별도로** 동작하는 추세 추종형 모멘텀 스캐너를 추가한다. US와 KR 두 시장에 대해 각각 독립 스캐너를 두고, 시장 → 섹터 → 종목 → 리스크 순서로 좁혀나가 "돈이 몰리는 곳의 리더 종목"을 매일 식별한다.

핵심 원칙:
- **저점 매수와 추세 추종 동시 운영** — 기존 스캐너 영향 없음
- **속도** — Universe 250~400 종목으로 사전 축소, 무거운 지표는 게이트 통과 종목에만
- **연속성** — 캐시 fallback으로 신호 끊김 방지 (streak/MDD 왜곡 방지)
- **장애 격리** — 모멘텀 실패가 기존 파이프라인에 영향 없음
- **검증 가능성** — leg 기반 백테스트로 streak edge 정량 평가

## 1. Goals & Non-goals

### Goals (v1.0)
- 매일 US/KR 모멘텀 시그널(M1/M2/M3) 자동 식별 + 페이지 생성
- Sector momentum → Top 2~3 섹터 → 그 섹터 종목만 평가하는 top-down 흐름
- streak/change(NEW/UPGRADE/HOLD/DOWNGRADE/EXIT) 추적
- leg 기반 모멘텀 전용 백테스트 (+3d/+5d/+10d, MaxRet, MDD, Duration)
- 종목 detail 페이지에 모멘텀 history 섹션 추가
- 텔레그램 간략 알림 (US/KR 별도 링크 + 핵심 Edge 한 줄)

### Non-goals (이번 작업 제외)
- 기존 strategy.md v5.3 시그널 로직 변경 — 영향 없음
- Position-aware leg (M2→M3 추가 매수 분리 추적) — v2 후보
- 외부 거래대금 API (Polygon/Alpaca) 도입 — 비용 검토 후 v2
- 과거 holdings snapshot 기반 생존 편향 보정 — v2

## 2. Architecture Overview

### 2.1 위치 — Pipeline Step 4c2 (신규)

```
Step 4   Signal judgment
Step 4b  Existing scanners (SP100/ETF/KOSPI/Watchlist)
Step 4c  Politician trades
Step 4c2 ★ Momentum scanners (US, KR) — 신규, 독립 실행
Step 4d  YTD benchmark
Step 5   Report generation
```

번호를 4c2로 잡아 기존 4d/5/5a/5b/5c/6/6b/7 번호 변경 없음 (diff 최소화).

### 2.2 모듈 구성 (단방향 의존: config → data → universe → signal → history → backtest)

```
momentum_config.py         # 상수 — RSI 임계값, 가격 비율, 캐시 TTL, 잡주 필터 등
momentum_data.py           # Data access layer (yfinance bulk fetch, 지표 캐시, 캐시 I/O 공통)
momentum_universe.py       # Universe 구축 (IWB/KODEX holdings 의존)
momentum_signal.py         # Sector/Stock momentum 판정, Risk Tag
momentum_history.py        # streak/change/EXIT 이벤트
momentum_backtest.py       # leg 기반 평가 (+3d/+5d/+10d, MDD, Duration)
momentum_scanner.py        # Entry: scan_momentum_us(), scan_momentum_kr() — 위 모듈 조립
```

- `momentum_config.py`: 모든 임계값을 상수로 분리. 추후 튜닝 시 한 곳에서만 수정.
  ```python
  # Sector momentum
  SECTOR_RSI_MIN = 55
  SECTOR_5D_MIN_PCT = 3.0
  SECTOR_HIGH_52W_RATIO = 0.95   # 52주 95% 이내
  SECTOR_HIGH_20D_USE = True     # max(high_20d, high_52w * 0.95)
  SECTOR_RS_SCALE = 5            # rs_score = min(20, max(0, diff * 5))

  # Pre-filter (종목 게이트)
  PREFILTER_3D_MIN_PCT = 4.0     # 5%에서 4%로 완화 (초기 리더 포착)
  PREFILTER_RSI_MIN = 55

  # Stock momentum tiers
  M1_3D_MIN_PCT = 8.0
  M1_RSI_MIN = 60
  M2_VOLUME_RATIO_MIN = 1.2
  M3_HIGH_52W_RATIO = 0.99
  M3_RSI_MIN = 65

  # Risk tags
  RISK_OVERHEAT_RSI = 80
  RISK_PARABOLIC_PCT = 8.0
  RISK_EXTENDED_MA20_PCT = 10.0
  RISK_EARLY_RSI_MIN = 60
  RISK_EARLY_RSI_MAX = 65   # M1 + 60 ≤ RSI < 65

  # Universe
  CACHE_TTL_DAYS = 7
  KR_LIQUIDITY_MIN_KRW = 10_000_000_000   # 100억원
  DAILY_MOVER_1D_PCT = 5.0
  DAILY_MOVER_3D_PCT = 8.0

  # Backtest
  BACKTEST_WINDOW_DAYS = 90
  CONSECUTIVE_LOSS_THRESHOLD = 4   # 최근 5개 leg 중 4개 손실 시 alert
  ```
- `momentum_data.py`가 yfinance 호출과 캐시 I/O 모두 단일 진입점으로 통제 (중복 호출/rate limit/캐시 중복 처리 방지). cache_manager 별도 파일 분리 대신 data 모듈에 함수로 포함:
  ```python
  load_cache(name) -> dict | None
  save_cache(name, data, status="ok", fallback_count=0)
  cache_age_days(name) -> int
  ```

### 2.3 신규 파일 / 캐시 위치

```
data/
  iwb_holdings.json                       # IWB Russell 1000 holdings (TTL 7일)
  # iwv_holdings.json — V2 후보 (V1.0 미사용)
  kodex200_holdings.json                  # KODEX 200 holdings
  kodex_kosdaq150_holdings.json           # KODEX KOSDAQ 150 holdings
  sector_etf_holdings_us.json             # SPDR/iShares 섹터 ETF holdings (mapping 전용)
  sector_etf_holdings_kr.json
  weekly_liquidity_us.json                # 거래대금 Top100 (TTL 7일)
  weekly_liquidity_kr.json

momentum_cache/
  us_<DATE>.json                          # 당일 universe + 시세 prefetch (US/KR 분리)
  kr_<DATE>.json

history/
  scanner_momentum_us_history.json        # 일별 시그널 + streak + change
  scanner_momentum_kr_history.json
  momentum_backtest_us.json               # leg 기반 평가 결과
  momentum_backtest_kr.json
```

### 2.4 캐시 메타 스키마 (확정)

```json
{
  "last_updated": "2026-05-06T13:42:11+09:00",
  "source": "ishares",
  "etf_ticker": "IWB",
  "fetch_status": "ok",
  "fallback_count": 0,
  "row_count": 1003,
  "data": ["AAPL", "MSFT", "NVDA", "..."]
}
```

- `fetch_status`: `ok` | `stale_fallback` | `failed`
- `fallback_count`: 연속 fallback 사용 횟수 (3 이상이면 경고 로그)
- 모든 캐시 파일이 동일 메타 스키마 사용

### 2.5 실패 격리

```python
# Pipeline Step 4c2
try:
    from momentum_scanner import scan_momentum_us
    momentum_us_result = scan_momentum_us(project_dir)
except Exception as e:
    print(f"[Step 4c2] WARN momentum US failed: {e}")
    momentum_us_result = None

try:
    from momentum_scanner import scan_momentum_kr
    momentum_kr_result = scan_momentum_kr(project_dir)
except Exception as e:
    print(f"[Step 4c2] WARN momentum KR failed: {e}")
    momentum_kr_result = None
```

US/KR 각각 try (하나 실패해도 다른 쪽 정상 진행). 결과 None일 때 리포트/텔레그램은 해당 시장 섹션 자체를 숨김.

## 3. Universe Construction

### 3.1 데이터 소스

| 데이터 | 소스 | URL/방식 | 갱신 |
|---|---|---|---|
| IWB holdings (~1000) | iShares 공개 CSV | `https://www.ishares.com/us/products/239707/ishares-russell-1000-etf/1467271812596.ajax?fileType=csv&fileName=IWB_holdings&dataType=fund` | TTL 7일 |
| ~~IWV holdings (~3000)~~ | V2 후보 — V1.0에서 제외 | — | — |
| US 섹터 ETF holdings | SPDR 또는 iShares | XLK/XLF/XLE/XLV/XLI/XLY/XLP/XLU/XLRE/XLB/XLC | TTL 7일 |
| KODEX 200 (069500) | KRX `data.krx.co.kr` 종목구성내역 API (POST) | 추후 구현 시 정확한 endpoint 확정 | TTL 7일 |
| KODEX KOSDAQ 150 (229200) | KRX 동일 | 동일 | TTL 7일 |
| KR 섹터 ETF holdings | KRX 동일 | KODEX 반도체(091160) / 은행(091170) / 에너지화학(117460) / 200헬스케어(261240) / 자동차 / 미디어통신 / 건설 | TTL 7일 |

**단일 진입점**: `momentum_data.fetch_etf_holdings(etf_ticker, market='us'|'kr') -> List[str]`

**IWB CSV 처리 규칙** (필수):
- 컬럼명 유연 처리 — iShares가 컬럼명을 변경할 수 있음:
  ```python
  TICKER_COLS = ["Ticker", "Ticker Symbol", "Issuer Ticker"]
  ticker_col = next((c for c in df.columns if c in TICKER_COLS), None)
  if ticker_col is None:
      raise ValueError(f"No known ticker column in CSV. Columns: {df.columns.tolist()}")
  ```
- Ticker 컬럼만 추출 (Name/Weight/Market Value 등 폐기)
- 심볼 정규화: `BRK.B → BRK-B`, `BF.B → BF-B` (yfinance 호환)
- 비주식 항목 제외: cash, derivative 행 (보통 ticker가 `-` 또는 빈값) skip

### 3.2 US Universe 구성

```
US_BASE          = IWB holdings (~1000)
US_WEEKLY_TOP100 = IWB 내에서 거래대금 5일 평균 상위 100 (TTL 7일)
US_DAILY_MOVERS  = IWB 내에서 (1d ≥ +5% OR 3d ≥ +8%) AND close > MA20 (당일 계산)

US_UNIVERSE = US_BASE ∪ US_WEEKLY_TOP100 ∪ US_DAILY_MOVERS
            ≈ IWB ∪ (IWB 부분집합)
            = IWB (≈ 1000)

# 핵심 원칙: V1.0 universe는 절대 1000개 넘지 않음
# IWV (~3000) 확장은 V2 — yfinance rate limit / 속도 위험 회피
# US_SECTOR_ETF holdings는 universe에 포함 안 됨
# → ticker → sector 매핑 lookup table 용도로만 사용
```

### 3.3 KR Universe 구성

```
KR_BASE          = KODEX 200 (~200) ∪ KODEX KOSDAQ 150 (~150)  → ~350
KR_SECTOR_ETF    = KR 섹터 ETF holdings 합집합 (universe + 매핑 둘 다)
KR_WEEKLY_TOP100 = KR_BASE에서 거래대금 5일 평균 상위 100
KR_DAILY_MOVERS  = KR_BASE에서 (1d ≥ +5% OR 3d ≥ +8%) AND 거래대금 5일 평균 ≥ 100억원

KR_UNIVERSE = KR_BASE ∪ KR_SECTOR_ETF ∪ KR_WEEKLY_TOP100 ∪ KR_DAILY_MOVERS
            (≈ 250~400)
```

**잡주 필터**: 거래대금 5일 평균 100억원 미만 종목은 KR_DAILY_MOVERS에서 제외 (테마/뉴스 1일 펌프 무시).

### 3.4 거래대금 Top100 주간 배치

문제: 미국에 "전체 시장 거래대금 랭킹" API 없음. 채택안:
- **IWB universe**에 대해서만 yfinance bulk fetch → 거래대금 평균 계산 → Top100 추출
- 주 1회만 실행 (TTL 7일), bulk 호출이라 5분 이내 (1000 종목)
- KR도 동일 (KR_BASE 대상)

**거래대금 정의 (명시)**:
```python
dollar_volume_today    = volume * close                     # 당일 거래대금
avg_5d_dollar_volume   = mean(dollar_volume[-5:])           # 5일 평균
```
- US Top100 정렬 키: `avg_5d_dollar_volume` 내림차순 → 상위 100
- KR 잡주 필터: `avg_5d_dollar_volume ≥ 100억원 (10_000_000_000 KRW)`

### 3.5 Daily Movers — 계산 비용

매일 universe candidate 약 1350개(IWB 1000 + KR 350) 대상으로 **1d/3d 변화율 + close/MA20 비교만** 계산:
- yfinance `download()` bulk 호출 1번 (~10-30초)
- **RSI/MACD 등 무거운 지표는 절대 계산 금지** (속도 핵심)
- MA20은 close 단순평균 — yfinance bulk 결과로 cheap
- 통과한 종목만 본 스캔 단계로 진입

**Daily Movers 조건 (확정)**:
```
(1d_ret ≥ +5% OR 3d_ret ≥ +8%) AND close > MA20
```
`AND close > MA20` 추가 이유: 갭 상승 1일짜리 펌프 (전체 추세는 하락) 노이즈 제거.

**Universe 1000개 cap 원칙**: V1.0은 IWB만 사용. V2에서 IWV 부분 확장 시에도 universe 총합 1500 이하로 제한 (rate limit + 속도 보장).

### 3.6 갱신 트리거 의사코드

```python
def get_holdings(etf_ticker, market):
    cache = load_cache(etf_ticker)
    if cache and age(cache.last_updated) < 7d and cache.fetch_status == "ok":
        return cache.data
    try:
        data = fetch_from_source(etf_ticker, market)
        save_cache(etf_ticker, data, status="ok", fallback_count=0)
        return data
    except Exception as e:
        if cache:
            save_cache_status_only(etf_ticker, status="stale_fallback",
                                    fallback_count=cache.fallback_count + 1)
            log_warn(f"{etf_ticker}: using stale cache "
                     f"(age={age()}, fallback_count={cache.fallback_count + 1})")
            if cache.fallback_count + 1 >= 3:
                log_critical(f"{etf_ticker}: 3+ consecutive fallbacks — investigate")
            return cache.data
        raise  # 최초 실행 + 첫 fetch 실패 → universe 구성 불가
```

## 4. Signal Logic

### 4.1 Sector Momentum

**필수 조건 (ALL met or 섹터 제외)**:
- ① 5d return ≥ +3%
- ② close > MA20
- ③ RSI(14) ≥ 55

**가속 조건 (2/4 met or 섹터 제외)**:
- ④ 신고가 근접: `close ≥ max(high_20d, high_52w × 0.95)` (혼합 기준)
- ⑤ MACD 히스토그램 증가: `macd_hist_trend == "rising"` (3일 추세)
- ⑥ 거래량 증가: `volume_ratio ≥ 1.2`
- ⑦ 20d return: 평가 대상 섹터 ETF 중 상위 50%

**Relative Strength (필수 게이트)**:
- US: `sector_5d_return > max(SPY_5d, QQQ_5d)`
- KR: `sector_5d_return > max(KOSPI_5d, KOSDAQ_5d)`

**Sector Score (정렬용, 0~100)**:
```python
trend_score    = 40   # 필수 ALL 통과 시 고정 (게이트 통과 자체가 만점)
momentum_score = (가속 4개 중 충족 개수) × 10              # 0~40
rs_score       = min(20, max(0, (sector_5d - market_5d) × 5))  # 연속값
                 # +0.5% → 2.5, +2% → 10, +4% 이상 → 20 cap
total          = trend_score + momentum_score + rs_score   # 60~100
```

RS 점수가 `× 5` 스케일인 이유: `× 10`은 +2%만 우위면 만점이라 섹터 간 변별력 부족. `× 5`로 +4% 이상부터 만점 → Top 2~3 정렬 시 강한 RS와 미미한 RS 구분 명확.

→ Top 2~3 섹터 선택. 동점 시 5d return 큰 순.

### 4.2 섹터 → 종목 매핑

**US**: `data/sector_etf_holdings_us.json`을 ticker→sector 역방향 lookup 테이블로 사용. 한 종목이 여러 섹터 ETF에 포함되면 우선순위 매핑 (예: XLK > IYW). 매핑 없는 종목은 'Other' 섹터로 분류 후 sector momentum 단계 제외.

**KR**: `data/sector_etf_holdings_kr.json` 동일 패턴.

### 4.3 Pre-filter (종목 게이트)

Top 2~3 섹터에 속한 종목만 평가. ALL 통과 시 다음 단계로:
- ① 3d return ≥ +4%   (초기 리더 포착 위해 5% → 4% 완화)
- ② close > MA20
- ③ RSI(14) ≥ 55

→ 통과 결과 30~80개 예상.

**완화 근거**: pre-filter는 "본 스캔 가치 있는가" 게이트. 너무 빡세면 초기 진입 신호(M1 + RSI 60-65) 진입을 미리 잘라버림. 4%로 낮추되 RSI/MA20는 유지해 잡주 차단.

### 4.4 Momentum 단계 판정

| 시그널 | 조건 |
|---|---|
| **MOMENTUM_1 (M1)** | 3d ≥ +8% AND RSI ≥ 60 AND close > MA20 |
| **MOMENTUM_2 (M2)** | M1 충족 AND 다음 3개 중 2개 이상: `volume_ratio ≥ 1.2`, `macd_hist_trend == "rising"`, `close > MA50` |
| **MOMENTUM_3 (M3)** | M2 충족 AND `close ≥ high_52w × 0.99` AND RSI ≥ 65 |

**한 종목은 가장 높은 단계로 표시** (M3 > M2 > M1).

### 4.5 종목 Relative Strength (참고지표 — 단계 영향 없음)

- `stock_5d_return > sector_5d_return` 여부 → boolean RS 플래그
- 출력에 RS✓ 표시. 시그널 단계 결정에는 영향 없음.

이 결정의 근거: RS를 게이트로 쓰면 "이미 강한 종목"만 살아남아 초기 주도주를 놓침. 표시만 하면 사용자가 직접 판단 가능.

### 4.6 Risk Tags (출력 전용 — 시그널 단계 영향 없음)

| Tag | 조건 | 색상 | Position Hint |
|---|---|---|---|
| 🔴 OVERHEAT | RSI(14) ≥ 80 | 빨강 | 신중 (신규 진입 자제) |
| 🟠 PARABOLIC | 당일 change_pct ≥ +8% | 주황 | 눌림 대기 |
| 🟡 EXTENDED | `(close - ma20) / ma20 ≥ 0.10` | 노랑 | 분할 진입 |
| ⚪ EARLY | M1 AND 60 ≤ RSI < 65 | 회색 | 조기 진입 힌트 |

복수 태그 동시 부여 가능 (예: NVDA M3 🔴🟠).

**해석 규칙**:
| 상태 | Position Hint |
|---|---|
| Risk 없음 | 적극 |
| ⚪ EARLY | 조기 진입 힌트 |
| 🟡 EXTENDED | 분할 |
| 🟠 PARABOLIC | 눌림 |
| 🔴 OVERHEAT | 신중 |

### 4.7 신규 데이터 필드 (`fetch_market_data.py` 확장)

기존 종목 처리 라인에 2필드 추가:
```python
"change_5d_pct":  round((last_close / float(close.iloc[-6]) - 1) * 100, 2)
                  if len(close) >= 6
                     and not pd.isna(close.iloc[-6])
                     and float(close.iloc[-6]) != 0
                  else None,
"change_20d_pct": round((last_close / float(close.iloc[-21]) - 1) * 100, 2)
                  if len(close) >= 21
                     and not pd.isna(close.iloc[-21])
                     and float(close.iloc[-21]) != 0
                  else None,
```

**안전장치**: NaN 검사 + ZeroDivision 방어 (분할/데이터 오류 시 0 반환되는 케이스 대응).

기존 시그널 로직(`signal_judge.py`)은 이 필드 사용 안 함 → 부수 효과 없음. 모멘텀 스캐너만 사용.

## 5. History & Backtest

### 5.1 히스토리 파일 스키마

`history/scanner_momentum_us_history.json` (KR 동일 패턴):

```json
{
  "_meta": {
    "scanner": "momentum_us",
    "schema_version": 1,
    "version": "Momentum v1.0",
    "last_updated": "2026-05-06"
  },
  "data": {
    "NVDA": {
      "2026-05-02": {
        "stage": "MOMENTUM_2",
        "streak": 1,
        "prev_stage": null,
        "change": "NEW",
        "risk_tags": [],
        "price": 850.00,
        "rsi": 62.5,
        "ret_1d_pct": 5.2,
        "ret_3d_pct": 9.1,
        "ret_5d_pct": 11.8,
        "sector": "Tech",
        "rs_vs_sector": false,
        "entry_price": 850.00,
        "entry_date": "2026-05-02",
        "entry_context": {"sector": "Tech", "streak": 1, "risk_tags": []},
        "time_in_stage": 1
      },
      "2026-05-03": {
        "stage": "MOMENTUM_3",
        "streak": 2,
        "prev_stage": "MOMENTUM_2",
        "change": "UPGRADE",
        "risk_tags": ["OVERHEAT"],
        "entry_price": 875.50,
        "entry_date": "2026-05-03",
        "entry_context": {"sector": "Tech", "streak": 2, "risk_tags": ["OVERHEAT"]},
        "time_in_stage": 1,
        "price": 875.50
      },
      "2026-05-04": {
        "stage": "MOMENTUM_3", "streak": 3, "change": "HOLD",
        "entry_price": 875.50, "entry_date": "2026-05-03",
        "time_in_stage": 2,
        "price": 890.00
      },
      "2026-05-07": {
        "stage": null,
        "change": "EXIT",
        "exit_price": 920.00,
        "exit_date": "2026-05-07",
        "exit_reason": "EXIT",
        "prev_stage": "MOMENTUM_3"
      }
    }
  }
}
```

**필드 정의**:
- `entry_price`: **현재 stage**의 최초 진입일 종가 (v1.0 = today_close)
  - ⚠️ **Look-ahead bias 주의**: 종가는 시그널이 확정되는 시점의 가격이라 실거래에서는 다음 날 시초가/시장가에 매수 가능. 백테스트 수익률은 **이론값(낙관적)**이며 실제 실행 시 슬리피지 발생.
  - UI 표시 시 "백테스트는 종가 진입 가정" 푸터 명시 필수
  - V2: `entry_price = next_day_open`으로 변경 (look-ahead 제거)
- `entry_date`: 현재 stage 진입 날짜
- `entry_context`: 진입 시점 컨텍스트 (sector, streak, risk_tags) — 추후 분석용
- `time_in_stage`: 현재 stage 유지 일수 (UPGRADE 시 1로 reset)
- `ret_1d_pct` / `ret_3d_pct` / `ret_5d_pct`: 시점 종가 기준 누적 수익률 (모멘텀 스키마 통일 명명 — 기존 `fetch_market_data.py`의 `change_pct/change_3d_pct/change_5d_pct`를 momentum_data.py에서 매핑)
- EXIT 이벤트는 하루 entry로 저장: `stage: null, change: "EXIT", exit_price, exit_date, exit_reason, prev_stage`
- `exit_reason`: `EXIT` (정상 이탈) | `STOP` (Risk 트리거 — v2) | `TIMEOUT` (기간 초과 — v2)

**필드명 통일 정책**:
- 기존 `fetch_market_data.py`가 생성하는 시장 데이터는 `change_*_pct` 유지 (signal_judge 등 기존 코드 사용 중)
- 모멘텀 스키마(`scanner_momentum_*_history.json`, `momentum_backtest_*.json`)는 `ret_*_pct`로 통일
- 매핑은 `momentum_data.py`가 단일 진입점으로 담당 (`change_5d_pct → ret_5d_pct`)

**JSON 키 순서 보장**:
- Python `json.dump()`는 dict 삽입 순서를 그대로 직렬화 (Python 3.7+).
- 다만 외부 도구가 재정렬할 수 있으므로 **읽을 때는 항상 `sorted(dates)` 적용**.
- 디스플레이/계산 로직에서는 명시적 정렬을 보장한다.

### 5.2 Streak / Change 계산 규칙

```python
RANK = {"MOMENTUM_1": 1, "MOMENTUM_2": 2, "MOMENTUM_3": 3}

def compute_streak_change(today_stage, prev_day):
    if prev_day is None:
        return ("NEW", 1)
    prev_stage = prev_day["stage"]
    if today_stage is None:
        return ("EXIT", 0)
    if today_stage == prev_stage:
        return ("HOLD", prev_day["streak"] + 1)
    if RANK[today_stage] > RANK[prev_stage]:
        return ("UPGRADE", prev_day["streak"] + 1)  # streak 유지 +1
    return ("DOWNGRADE", 1)  # 하락 시 streak 1로 reset
```

EXIT 시: 하루 EXIT entry 저장 후, 다음 거래일부터 ticker key에 일자 추가 안 함 (다시 시그널 발동 시 NEW로 재시작).

`time_in_stage`: NEW/UPGRADE/DOWNGRADE 시 1, HOLD 시 prev + 1.

### 5.3 모멘텀 전용 백테스트 (`momentum_backtest.py`)

**Leg 정의**: 각 (ticker, stage) 진입 이벤트 = 1 leg.
- NEW M1 → leg start
- UPGRADE → 새 leg start (이전 leg는 종료)
- DOWNGRADE → 새 stage의 새 leg 시작 (이전 stage leg는 종료)
- EXIT → 현 leg 종료

**Leg 결과 스키마** (`history/momentum_backtest_us.json`):

```json
{
  "ticker": "NVDA",
  "leg_id": "NVDA_M3_2026-05-03",
  "stage": "MOMENTUM_3",
  "entry_date": "2026-05-03",
  "entry_price": 875.50,
  "entry_context": {"sector": "Tech", "streak": 2, "risk_tags": ["OVERHEAT"]},
  "exit_date": "2026-05-08",
  "exit_price": 905.00,
  "exit_reason": "DOWNGRADE",
  "duration_days": 5,
  "ret_3d_pct": 4.5,
  "ret_5d_pct": 7.8,
  "ret_10d_pct": null,
  "max_ret_pct": 9.2,
  "min_ret_pct": -1.1,
  "mdd_pct": -2.3
}
```

**계산 방법**:
- max/min/MDD: 가능하면 **intraday OHLCV의 high/low** 사용 (정확도 우선). 데이터 없으면 close fallback.
  - `max_ret_pct = (max(high_since_entry) / entry_price - 1) * 100`
  - `min_ret_pct = (min(low_since_entry) / entry_price - 1) * 100`
  - `mdd_pct = (min(low) - max(high))/max(high) * 100` — peak-to-trough 가장 큰 낙폭
- `ret_3d/5d/10d`: 진입 후 N거래일 시점 종가 기준 누적 수익률. 미경과 시 null.
- 진행 중 leg는 `exit_date: null`, `exit_price: null` → 매일 스냅샷 갱신.

### 5.4 집계 분석 (UI 표시용)

```json
{
  "as_of": "2026-05-06",
  "version": "Momentum v1.0",
  "by_stage": {
    "MOMENTUM_3": {
      "leg_count": 47,
      "win_rate_5d_pct": 68.1,
      "avg_ret_3d_pct": 2.1,
      "avg_ret_5d_pct": 4.8,
      "avg_ret_10d_pct": 7.2,
      "avg_max_ret_pct": 9.5,
      "avg_min_ret_pct": -1.5,
      "avg_mdd_pct": -3.1,
      "avg_duration_days": 5.2
    },
    "MOMENTUM_2": {"...": "..."},
    "MOMENTUM_1": {"...": "..."}
  },
  "by_streak": {
    "1":  {"avg_ret_5d": 1.2, "win_rate_pct": 51},
    "2":  {"avg_ret_5d": 3.4, "win_rate_pct": 62},
    "3+": {"avg_ret_5d": 5.7, "win_rate_pct": 73}
  },
  "alerts": {
    "consecutive_loss_warning": false,
    "recent_5_legs_loss_count": 1
  }
}
```

**연속 손실 감지**: 최근 5개 leg 중 4개 이상이 음수 ret_5d → `alerts.consecutive_loss_warning: true` 표시 (UI에 경고 배지).

### 5.5 기존 backtest_evaluator와의 분리

- 기존 `backtest_evaluator.py`: 30일 평가창, mean-reversion 전제 (1st/2nd/3rd_BUY 대상)
- 신규 `momentum_backtest.py`: 10일 leg, trend-following 전제 (M1/M2/M3 대상)
- **코드 재사용 안 함**, 별도 모듈
- 리포트에는 두 백테스트 모두 표시 (기존: 메인 backtest 페이지, 신규: 모멘텀 페이지 내)

## 6. Output / UI

### 6.1 페이지 구조 — `reports/momentum_us_<DATE>.html`, `momentum_kr_<DATE>.html`

```
┌─ Hero Summary ─────────────────────────────────────────┐
│ 🔥 Today's Momentum Leaders — US     2026-05-06       │
│ Scanned: 312 tickers · ⏱ 47s · Momentum v1.0          │
│ Detected: M3=3 / M2=5 / M1=12                         │
└────────────────────────────────────────────────────────┘

┌─ Sector Leaders ───────────────────────────────────────┐
│ ① Tech              🔥🔥🔥  Score 98   5d +5.2%   RS +2.1pp │
│ ② Communication     🔥🔥    Score 87   5d +4.1%   RS +1.0pp │
│ ③ Semiconductor     🔥🔥    Score 82   5d +3.7%   RS +0.6pp │
└────────────────────────────────────────────────────────┘

┌─ [Tech] ──────────────────────────────────────────────┐
│ Ticker  Name     Signal Streak Change   Price 1d/3d/5d RSI Sec_RS Risk Hint  │
│ NVDA    NVIDIA   M3     4d     HOLD     $920  ...     78  ✓     🔴🟠 신중   │
│ AMD     AMD      M3     2d     UPGRADE  $168  ...     71  ✓     🟠 눌림     │
│ MU      Micron   M2     1d     NEW      $138  ...     63  —     🟡 분할     │
└────────────────────────────────────────────────────────┘

┌─ Backtest Summary (직전 90일 누적) ────────────────────┐
│ Stage   #legs  Win 5d  Avg 3d   Avg 5d   Avg 10d  MDD  │
│ M3      47     68%     +2.1%    +4.8%    +7.2%   -3.1%│
│ M2      83     54%     +1.4%    +2.9%    +4.1%   -3.8%│
│ M1      129    46%     +0.6%    +1.2%    +1.8%   -4.2%│
│                                                       │
│ 🔥 Edge: M3 streak 3+일 → 5d 평균 +5.7% (vs 1일 +1.2%) │
│ ⚠ 최근 5개 leg 중 4개 손실 (있을 때만 표시)            │
└────────────────────────────────────────────────────────┘

┌─ Footer (Universe / Cache Status) ─────────────────────┐
│ IWB 1003종목 (cached 5d ago, fallback_count=0)         │
│ Daily movers: 38 (1d≥5%:22, 3d≥8%:24)                  │
│ ⚠ 백테스트는 종가 진입 가정 — 실거래 시 슬리피지 발생  │
│ KR pages → /momentum_kr_<DATE>.html                    │
│ ⚠ Momentum KR: unavailable (fetch failed)  ← 실패 시   │
└────────────────────────────────────────────────────────┘
```

### 6.2 종목 행 컬럼 명세

| 컬럼 | 데이터 |
|---|---|
| Ticker | 클릭 시 `/details/<ticker>.html` |
| Name | 종목명 |
| Signal | M1/M2/M3 (색상 배지) |
| Streak | "4d" |
| Change | NEW(파랑) / UPGRADE(녹색) / HOLD(회색) / DOWNGRADE(주황) — EXIT은 표시 안 됨 |
| Price | 종가 |
| 1d / 3d / 5d | change_pct, change_3d_pct, change_5d_pct |
| RSI | rsi14 |
| Sec_RS | 섹터 대비 ✓ / — |
| Risk | 🔴 / 🟠 / 🟡 / ⚪ EARLY |
| Hint | "적극" / "조기" / "분할" / "눌림" / "신중" |

### 6.3 메인 리포트 nav 통합

`templates/report_template.html` 상단 nav:
```
[📊 Portfolio] [👀 SP100] [💼 ETF] [🇰🇷 KOSPI] [👁 Watchlist]
[🔥 Momentum US] [🔥 Momentum KR]   ← 신규
[📈 Trend] [🏛 Politicians] [🧪 Backtest]
```

기존 스캐너 페이지 nav도 동일 패턴 적용. 모멘텀 결과 None 시 해당 버튼 hide.

### 6.4 Detail 페이지 보강

`details/<ticker>.html` 레이아웃 (모멘텀 시그널 종목만 새 섹션 추가):

```
[차트]

🔥 CURRENT STATUS  ← 신규 (최상단, 차트 바로 아래)
  Stage: M3 (5일째)
  Entry: $875 → Now $920 (+5.1%, MDD -1.8%)
  Risk: 🔴 OVERHEAT
  Hint: 신규 진입 신중

🔥 Momentum History (last 30 days)  ← 신규
  2026-05-02  M2  NEW       streak 1   $850
  2026-05-03  M3  UPGRADE   streak 2   $875  ← entry
  2026-05-04  M3  HOLD      streak 3   $890
  2026-05-05  M3  HOLD      streak 4   $905
  2026-05-06  M3  HOLD      streak 5   $920  🔴 OVERHEAT

[기존 시그널 분석]
[기타 지표]
```

기존 detail 페이지의 다른 섹션은 유지. 모멘텀 시그널 없는 종목은 신규 섹션 노출 안 함.

`generate_detail_pages()`에 `momentum_us_history`, `momentum_kr_history` 인자 추가 (선택적).

### 6.5 차트 생성

`chart_generator.generate_all_charts(tickers, charts_dir)` 재사용. `pipeline.py` Step 5a:
```python
all_chart_tickers = portfolio + scanner_buy + watchlist + momentum_signal_tickers
                    # 모멘텀 universe 전체가 아닌 M1/M2/M3 발동 종목만
```

### 6.6 Telegram 알림

`telegram_sender.py`에 `send_momentum_brief(momentum_us, momentum_kr, backtest_summary)` 추가.

**메시지 포맷** (≤ 3500자 안전 trim):
```
🔥 Momentum Scanner — 2026-05-06

🇺🇸 US  Top: Tech, Comm Svcs
M3 (3): NVDA 🔴 (4d), AMD 🟠 (2d), AVGO (1d)
M2 (5): MU 🟡, QCOM, KLAC, GOOGL, ...
M1 (12): see report

🇰🇷 KR  Top: 반도체, 2차전지
M3 (2): SK하이닉스 (3d), 한미반도체 🟠 (1d)
M2 (4): 에코프로 🟡, 삼성SDI, ...

🔥 Edge: M3 streak 3+일 → 5d 평균 +5.7%

📊 US: https://freecjs77-tech.github.io/.../momentum_us_2026-05-06.html
📊 KR: https://freecjs77-tech.github.io/.../momentum_kr_2026-05-06.html
```

**발송 시점**: 메인 리포트 텔레그램 발송 직후 (Step 5b 직후), 별도 try/except. 길이 안전장치 `message[:3500]`.

### 6.7 실패 시 UI 처리

| 시나리오 | 처리 |
|---|---|
| Momentum US 결과 None | nav US 버튼 hide, US 페이지 생성 skip, KR은 정상 |
| Momentum KR 결과 None | 동일 KR만 skip |
| 둘 다 None | nav 버튼 모두 hide, 텔레그램 모멘텀 메시지 발송 안 함 |
| Backtest 데이터 부족 (90일 미만) | "데이터 누적 중 (X/90일)" 메시지 표시 |
| 캐시 stale_fallback | Footer에 "cached Xd ago, fallback_count=N" 표시 |
| 캐시 fallback_count ≥ 3 | Footer에 ⚠ 경고 배지 추가 |

### 6.8 신규 템플릿 파일

```
templates/
  base_momentum.html           # 공통 base (Hero/Sector/Stock list/Backtest/Footer 블록)
  momentum_us.html             # extends base_momentum.html (US 색상/레이블)
  momentum_kr.html             # extends base_momentum.html (KR 색상/레이블)
```

## 7. Operations & Integration

### 7.1 `pipeline.py` 수정 포인트

**Step 4c2 신규 삽입** (정치인 거래 다음, YTD benchmark 이전, 번호 안 밀림):

```python
# Step 4c2: Momentum Scanner (US + KR, 독립 실행)
print("[Step 4c2] Momentum scanners...")
momentum_us_result = momentum_kr_result = None
try:
    from momentum_scanner import scan_momentum_us
    momentum_us_result = scan_momentum_us(project_dir)
    if momentum_us_result and momentum_us_result.get("status") == "ok":
        print(f"  OK [Step 4c2] Momentum US: M3={...} M2={...} M1={...}")
except Exception as e:
    print(f"  WARN [Step 4c2] Momentum US failed: {e}")

try:
    from momentum_scanner import scan_momentum_kr
    momentum_kr_result = scan_momentum_kr(project_dir)
    if momentum_kr_result and momentum_kr_result.get("status") == "ok":
        print(f"  OK [Step 4c2] Momentum KR: M3={...} M2={...} M1={...}")
except Exception as e:
    print(f"  WARN [Step 4c2] Momentum KR failed: {e}")
```

**Step 5 인자 추가**:
```python
generate_report(..., momentum_us=momentum_us_result, momentum_kr=momentum_kr_result, ...)
generate_scanner_pages(..., momentum_us=..., momentum_kr=..., output_dir=reports_dir)
```

**Step 5a (charts/details)**: 모멘텀 시그널 종목 → `extra_tickers`에 합산. `generate_detail_pages()`에 모멘텀 history 인자 전달.

**Step 5b (Telegram)**: 메인 직후 `send_momentum_brief()` 별도 호출.

### 7.2 환경변수 / 모드

기존 `SKIP_SCANNERS=1`처럼 다음 추가:
- `MODE=momentum_only`: 4c2만 실행 (~30초 회귀 테스트)
- `MODE=scanner_only`: 4b만 실행
- `MODE=full`: 전체 (기본)

미지정 시 `full`. 모드별 충돌 방지(예: `momentum_only`는 fetch_market_data, signal judgment 등 전 단계 결과 필요 → 모멘텀 모드는 입력 데이터 캐시 사용 가정).

### 7.3 GitHub Actions 워크플로우

`.github/workflows/daily-report.yml` 변경:

**워크플로우 시작 시 gh-pages 복원 패턴 확장**:
```yaml
git checkout gh-pages -- history/scanner_momentum_us_history.json \
                          history/scanner_momentum_kr_history.json \
                          history/momentum_backtest_us.json \
                          history/momentum_backtest_kr.json \
                          data/  || true
```

**워크플로우 종료 시 gh-pages 푸시 — 동시성 보호** (필수):
```bash
git pull --rebase origin gh-pages || git rebase --abort
git add history/ data/ momentum_cache/ deploy/
git commit -m "..."
git push origin gh-pages
```

`git pull --rebase` 누락 시 동시 실행 race condition으로 데이터 손실 가능 (1a320422류 사고 재발 방지).

**파일 단위 분리**: `history/` / `data/` / `momentum_cache/`를 별도 add — 충돌 영역 최소화.

### 7.4 신규 패키지 의존성

**없음** — `requests`, `pandas`, `yfinance` 모두 이미 사용 중. iShares CSV는 `requests.get()` + `csv.DictReader`, KRX API는 `requests.post()` (form data) + JSON.

### 7.5 신규 / 수정 파일 정리

**신규 (10개)**:
- `momentum_config.py`        — 상수 (RSI 임계값, 비율, TTL 등 한 곳)
- `momentum_data.py`          — yfinance + 캐시 I/O 단일 진입점
- `momentum_universe.py`      — IWB/KODEX holdings 처리
- `momentum_signal.py`        — Sector/M1/M2/M3 판정
- `momentum_history.py`       — streak/change/EXIT
- `momentum_backtest.py`      — leg 기반 평가
- `momentum_scanner.py`       — Entry point
- `templates/base_momentum.html`
- `templates/momentum_us.html`
- `templates/momentum_kr.html`

**수정 (7개)**:
- `fetch_market_data.py` — change_5d_pct, change_20d_pct 추가 (NaN/Zero 안전장치 포함)
- `history_manager.py` — 신규 필드 보존
- `pipeline.py` — Step 4c2 삽입 + report 인자 추가 + MODE 환경변수 처리
- `report_generator.py` — generate_scanner_pages, generate_detail_pages 인자
- `telegram_sender.py` — send_momentum_brief() 추가
- `templates/report_template.html` — nav 링크 2개 추가
- `.github/workflows/daily-report.yml` — gh-pages 동시성 보호 + 신규 파일 복원

**계획 문서**:
- `docs/plans/momentum-scanner.md` — implementation plan (writing-plans skill에서 생성)
- CLAUDE.md "진행 중인 계획" 섹션에 추가

### 7.6 테스트 / 검증 전략

**단위 테스트** (`tests/test_momentum_*.py`):
- `momentum_signal.py`: M1/M2/M3 임계값 boundary 테스트 (RSI 59.9 → 60, 64.9 → 65 등)
- `momentum_history.py`: streak/change 계산 (NEW → UPGRADE → HOLD → DOWNGRADE → EXIT 시나리오)
- `momentum_backtest.py`: leg 시작/종료 + return 계산 (high/low fallback 포함)
- `momentum_universe.py`: IWB CSV 파싱 + 심볼 정규화 (BRK.B → BRK-B)

**Golden sample 테스트** (회귀 방지):
- 고정된 NVDA/AMD/SK하이닉스 가짜 데이터 fixture → 항상 같은 시그널 결과
- `tests/fixtures/golden_<date>.json` 형태로 보관
- 시그널 로직 리팩토링 시 깨짐 즉시 감지

**통합 테스트**:
- `MODE=momentum_only` 환경변수로 모멘텀 단독 실행 (~30s)
- 페이지 생성 / Telegram 메시지 포맷 smoke test
- IWB CSV 다운로드 강제 실패 → 캐시 fallback 동작 확인
- 캐시 자체 없을 때 → "Insufficient data" 페이지 표시

### 7.7 배포 체크리스트

- [ ] `requirements.txt` 변경 없음 확인 (의존성 없음)
- [ ] gh-pages 워크플로우의 history/data 복원 패턴에 신규 파일 추가
- [ ] gh-pages 푸시 단계에 `git pull --rebase` 안전장치 적용
- [ ] 첫 배포 시 `data/*.json` 캐시 초기 fetch (수동 1회 또는 자동 시작)
- [ ] 메인 리포트 nav에 모멘텀 링크 표시 검증 (deploy/index.html)
- [ ] Telegram 메시지 길이 ≤ 3500 trim 검증
- [ ] 백테스트 데이터 부족 페이지(누적 중) 표시 확인 — 첫 90일은 누적 안내
- [ ] 페이지 푸터에 "Momentum v1.0" 버전 표기
- [ ] CLAUDE.md "진행 중인 계획" 섹션에 momentum-scanner 등재

### 7.8 리스크 / 완화책

| 항목 | 리스크 | 완화책 |
|---|---|---|
| iShares CSV 엔드포인트 변경 | URL/포맷 깨질 시 universe 빔 | TTL 캐시 fallback + fallback_count ≥ 3 시 critical 로그 |
| KRX API 응답 구조 변화 | KR universe 영향 | 동일 — 캐시 fallback |
| yfinance rate limit (1350 종목 daily fetch — IWB 1000 + KR 350) | 실패율 상승 | bulk download() + 청크 분할 + 재시도. IWV 확장은 V2까지 보류 (1000개 cap) |
| 신규 IPO / delisted | 데이터 누락 | yfinance 에러 graceful skip |
| 모멘텀 false positive (휩쏠림 장세) | 진입 후 즉시 손실 | Risk Tag + Backtest + 연속 손실 감지 alert |
| gh-pages 동시 push race | 데이터 손실 | `git pull --rebase` 안전장치 (필수) |
| 분할/데이터 오류로 close.iloc 0 또는 NaN | ZeroDivisionError | NaN/Zero 검사 후 None 반환 |

## 8. v1.0 Scope vs Future

### v1.0 (이번 작업 범위)

**필수 포함**:
- US + KR 모멘텀 스캐너 (별도 2개 페이지)
- IWB / KODEX 200 / KODEX KOSDAQ 150 holdings 캐시 (IWV는 V2)
- M1/M2/M3 + Sector momentum + Risk Tags + Streak/Change
- ⚪ EARLY 태그 (M1 + RSI 60-65)
- 거래대금 5일 평균 100억원 KR 잡주 필터
- leg 기반 모멘텀 백테스트 + streak 별 통계 + 연속 손실 감지
- Detail 페이지 CURRENT STATUS + Momentum History 섹션
- Telegram 간략 알림 (US/KR 링크 + Edge 한 줄)
- gh-pages 동시성 보호
- Golden sample 테스트

### v1.1 (후속 별도 작업, 우선순위 순)

1. **IWV 부분 확장** — `IWB ∪ (IWV에서 weekly liquidity 상위 200)`로 universe 확장. 단 1500개 cap 유지. yfinance rate limit 검증 후 진행.
2. 텔레그램 메시지에 종목별 차트 썸네일 첨부 (이미지 전송)
3. KRX endpoint 자동 갱신 (URL 변경 감지 시 알림)

### v2 (장기)

- Position-aware leg (M2→M3 추가 매수 분리)
- 과거 holdings snapshot (생존 편향 보정)
- 외부 거래대금 API (Polygon/Alpaca) — 비용 검토 후
- `entry_price = next_day_open` (look-ahead bias 제거 — v2 정교화)
- `exit_reason` 세분화 (STOP/TIMEOUT 자동 트리거)

## 9. 결정 요약 (Q&A 기록)

| # | 질문 | 결정 |
|---|---|---|
| Q1 | 기존 SP100과의 관계 | A — 별도 신규 스캐너로 추가 |
| Q2 | Universe 범위 | B — US + KR 별도 두 모멘텀 스캐너 |
| Q3 | 거래대금 처리 | B' Hybrid (ETF + 주간 Top100 + Daily movers) |
| Q4 | 미국 base 데이터 소스 | A — IWB holdings (V1.0). IWV 보완은 V2로 이전 (rate limit 회피) |
| Q5 | KR 구조 | A — US와 동일 B' 적용 (KODEX 200 + KOSDAQ 150 base) |
| Q6 | 출력 / 통합 | A — 별도 2개 페이지 + detail 페이지 + Telegram brief |
| Q7 | 히스토리 / 백테스트 | A — 풀 편입 + streak + change + 모멘텀 전용 백테스트 |
| Q8 | 운영 통합 | B + C + E + G — 독립 Step / 트리거 캐시 / KOSPI+KOSDAQ both / 캐시 fallback |
