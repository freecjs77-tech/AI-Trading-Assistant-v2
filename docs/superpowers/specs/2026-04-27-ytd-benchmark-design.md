# YTD Benchmark vs S&P (KRW) — 설계 문서

- **작성일**: 2026-04-27
- **대상 페이지**: My Portfolio · Wife Portfolio (메인 리포트 + 트렌드 페이지)
- **상태**: Design (Approved)

---

## 1. 목적

내 포트폴리오의 2026년 누적 수익률을 한눈에 확인하고, 같은 기간 S&P 500(원화 환산) 대비 초과수익(α)을 표시한다. "내 포트가 시장 대비 좋은 상태인가?"를 매일 빠르게 파악하기 위함.

## 2. 방법론

### 2.1 Constant-Portfolio Backtest (Jan 1 anchored)

- **Anchor 날짜**: `2026-01-02` (1/1은 미국·한국 모두 휴장 → 첫 거래일)
- **계산식**:
  - `v0 = Σ(현재 보유수량 × ticker의 2026-01-02 가격(KRW)) + KRW현금 + USD현금 × Jan2_USDKRW`
  - `v_now = Σ(현재 보유수량 × 오늘 가격(KRW)) + KRW현금 + USD현금 × today_USDKRW`
  - `ytd_pct = (v_now / v0 - 1) × 100`
- **중요**: `v_now`는 기존 `total_value_krw`를 재사용하지 않고 **v0와 동일한 종목 집합**으로 새로 계산한다. 매핑 실패 종목(§5.1)이 v0에서 빠지면 v_now에서도 빠져 분모-분자가 일관됨.

### 2.2 v0 업데이트 정책 — 매 파이프라인 실행 시 재계산 (Option B)

- 매일 "오늘의 보유 종목 × 2026-01-02 가격"으로 v0 갱신
- 2026-01-02 가격은 불변이므로 **보유 종목이 변할 때만** v0가 변동
- 신규 매수/매도가 발생해도 분모-분자가 함께 움직여 수익률이 망가지지 않음

### 2.3 알려진 한계 (UI 캐비엇으로 명시)

- 1월 이후 신규 매수한 종목은 1월 가격까지 소급 평가됨 → 1월~매수일 가격 변동분이 수익률에 함께 반영 (편향은 양방향: 오른 종목을 사면 부풀림, 떨어진 종목을 사면 깎임)
- 1월 이후 매도한 종목은 비교에서 제외 (오늘의 보유에 없으므로)
- 능동 거래의 진정한 성과 측정에는 TWR(Time-Weighted Return)이 더 정확하나, 데이터 시작일이 2026-03-05라 Jan 1 비교가 불가능 → 본 방안은 단순성과 Jan 1 비교 가능성을 우선시한 트레이드오프

### 2.4 S&P 벤치마크 — 원화 환산

- `SPY` ETF의 Adj Close 사용 (배당 재투자 반영, 실제 거래 가능 수단)
- `spy_v0_krw = SPY_jan2_usd × USDKRW_jan2`
- `spy_now_krw = SPY_today_usd × USDKRW_today`
- `spy_ytd_pct = (spy_now_krw / spy_v0_krw - 1) × 100`
- **알파**: `alpha_pp = ytd_pct - spy_ytd_pct` (단위: percentage point)

---

## 3. 아키텍처

### 3.1 새 모듈: `benchmark_ytd.py`

```
benchmark_ytd.py
├─ ANCHOR_DATE = "2026-01-02"
│
├─ load_or_build_baseline(holdings, owner) → dict
│    캐시: data/baseline_2026_{owner}.json
│    {
│      "anchor_date": "2026-01-02",
│      "usd_krw": <float>,
│      "spy_close_usd": <float>,
│      "ticker_v0_krw": { "AAPL": <KRW가격>, "삼성전자": <KRW가격>, ... },
│      "unmappable": [<ticker>, ...]   # 매핑 실패 종목 기록
│    }
│
├─ compute_v0_total_krw(holdings, baseline) → float
│    Σ(보유수량 × ticker_v0_krw[ticker])
│    + KRW 현금 그대로 합산
│    + USD 현금 × baseline.usd_krw
│    매핑 실패 종목은 v_now 계산 시에도 동일하게 제외
│
├─ compute_v_now_total_krw(holdings, today_prices, today_usd_krw, baseline) → float
│    v0와 동일한 구성으로 오늘 가격 기준 평가액 계산
│    today_prices는 fetch_market_data 결과 dict (ticker → 현재가)
│    SPY가 포함되어 있지 않으면 별도 fetch
│
├─ compute_returns(holdings, today_prices, today_usd_krw, today_spy_usd, baseline) → dict
│    {
│      "v0_krw": ..., "v_now_krw": ...,
│      "ytd_pct": (v_now/v0 - 1)*100,
│      "spy_v0_krw": ..., "spy_now_krw": ...,
│      "spy_ytd_pct": ...,
│      "alpha_pp": ytd_pct - spy_ytd_pct,
│      "excluded_tickers": [...]   # unmappable로 제외된 종목 리스트 (UI 캐비엇용)
│    }
│
└─ refresh_baseline_for_new_tickers(holdings, baseline)
     기존 캐시에 없는 신규 ticker만 yfinance fetch 후 캐시 갱신
```

### 3.2 파이프라인 통합

```
pipeline.py
  └─ fetch_market_data → signal_judge → report_generator
                                          │
                                          ├─ 기존: portfolio_daily 갱신
                                          └─ 신규: benchmark_ytd.compute_returns() 호출
                                                    → 결과를 템플릿에 전달
                                                    → portfolio_daily에 ytd_pct/spy_ytd_pct/alpha_pp 저장
```

### 3.3 캐시 정책

- **첫 실행**: `data/baseline_2026_me.json`, `data/baseline_2026_wife.json` 생성. yfinance에서 1/2 가격 + USD/KRW + SPY 1회 fetch
- **이후 실행**: 보유 종목 리스트 비교 → 신규 ticker만 추가 fetch. 기존 ticker는 재fetch 안 함 (1/2 가격 불변)
- **제거된 종목**은 캐시에 남겨둠 (재매수 가능성, 용량 부담 미미)

### 3.4 데이터 흐름

```
[portfolio.md] ─→ holdings dict ─┐
                                   ├─→ benchmark_ytd ─→ (ytd_pct, spy_ytd_pct, alpha_pp)
[data/baseline_2026_*.json] ──────┘            │
                                                ├─→ report_template.html 헤더
                                                └─→ portfolio_daily.json 저장
                                                        └─→ trend_template.html 차트
```

---

## 4. 표시 형식

### 4.1 메인 리포트 헤더 (`templates/report_template.html`)

기존 헤더(264~272줄) 아래 한 줄 추가:

```
$X,XXX,XXX  ($XXX,XXX 평가손익)
▲ +XX.X% vs Principal
─────────────────────────────────
2026 YTD: +X.X% · S&P(₩): +Y.Y% · α: +Z.Zpp ⓘ
```

- 포트 YTD: 양수=초록(`text-secondary`), 음수=빨강(`text-tertiary`)
- S&P(₩): 동일 색상 규칙
- α: 양수=초록(시장 outperform), 음수=빨강(underperform)
- ⓘ 호버 툴팁: 한계 캐비엇 (§2.3)

### 4.2 트렌드 페이지 (`templates/trend_template.html`)

**(a) 상단 요약 카드** — 메인과 동일 3개 수치를 큼직한 카드로

```
┌────────────┬────────────┬────────────┐
│ 2026 YTD   │ S&P (₩)    │ Alpha      │
│  +5.2%     │  +3.1%     │  +2.1pp    │
└────────────┴────────────┴────────────┘
```

**(b) 별도 정규화 비교 차트** — 기존 KRW 시계열 차트는 그대로 유지, 그 아래에 신설

- y축: v0 대비 % 변화 (포트 v0=0, S&P v0=0 기준)
- x축: 일자 (기존 트렌드 차트와 동일)
- 포트 라인: 실선(파란색)
- S&P 라인: 점선(회색)
- 두 라인 사이 음영: 알파가 양수면 파란 음영, 음수면 빨강 음영
- 데이터 소스: `portfolio_daily.json`의 `ytd_pct`, `spy_ytd_pct` 시계열

### 4.3 캐비엇 툴팁 텍스트

> "2026-01-02 기준 baseline. 보유 종목/수량이 변경되면 baseline도 자동 재계산됩니다. 1월 이후 신규 매수 종목은 1월~매수일 가격 변동분이 함께 반영되어 실제 거래 성과와 차이가 있을 수 있습니다."

---

## 5. 엣지 케이스 & 에러 처리

### 5.1 종목별 가격 fetch

| 케이스 | 처리 |
|---|---|
| 미국 종목 | yfinance `Ticker.history(start='2026-01-02', end='2026-01-03')` Close |
| KOSPI 종목 (`삼성전자`, `현대차`) | `005930.KS`, `005380.KS` 등 `.KS` suffix. `portfolio_data.to_yfinance_symbol()` 헬퍼 그대로 활용 |
| KOSDAQ 종목 (`디아이티`) | `.KQ` suffix. `portfolio_data.KOSDAQ_TICKERS` 셋 + `to_yfinance_symbol()` 활용 |
| 한글명 → 종목코드 변환 | `portfolio_data.KR_TO_TICKER` (이미 한글명→6자리 코드 매핑 존재) 활용 |
| 2026년 신규 상장 (CRCL, ETHU 등) | yfinance 첫 거래일 가격 사용. 효과적으로 "보유 시작일~오늘"이 되어 편향 자연 감소 |
| 매핑 실패 종목 | 캐시 `unmappable` 리스트에 기록, 경고 로그, v0/v_now 모두에서 제외 (분모-분자 동시 제거 → 비율 왜곡 방지) |

### 5.2 현금 처리

| 자산 | v0 처리 |
|---|---|
| KRW 현금 | v0_krw = 현재 KRW 잔액 그대로 (가격 변동 없음). 현금 비중만큼 수익률 희석 |
| USD 현금 | v0_krw = USD 잔액 × 2026-01-02 USD/KRW. v_now_krw = USD 잔액 × 현재 USD/KRW. FX 변동분만 수익률에 반영 |
| BIL 등 단기채 ETF | 일반 종목과 동일 처리 (yfinance 가격 있음) |

### 5.3 USD/KRW 환율

- 2026-01-02: yfinance `KRW=X` 또는 `USDKRW=X` 심볼
- 캐시 파일에 1회 저장 후 재사용
- fetch 실패 시: 1회 retry → 실패면 작업 중단 + 명시적 에러 (silent fallback 금지)

### 5.4 SPY 가격 데이터

- **Jan 2 가격** (baseline): yfinance `Ticker("SPY").history(start='2026-01-02')` Adj Close. 캐시에 저장
- **오늘 가격**: 매 실행마다 yfinance 별도 fetch (`fetch_market_data` 결과에 SPY가 있더라도 명시성을 위해 분리). 사용자 포트에 SPY가 없을 때도 동작 보장
- `SPY` Adj Close 사용 이유: 배당 재투자 반영, 실거래 가능 ETF. `^GSPC`는 배당 미반영이라 한국 KOSPI200처럼 비교 시 편차 발생

### 5.5 휴장일 보정

- 2026-01-02가 토/일이면 yfinance가 다음 거래일 자동 사용. anchor_date를 캐시에 명시 저장해 추적 가능
- 2026-01-02 실제: 금요일 → US/KR 모두 정상 거래일

### 5.6 보유 종목 변경 감지

```python
current_tickers = set(holdings.keys())
cached_tickers = set(baseline["ticker_v0_krw"].keys()) | set(baseline["unmappable"])
new_tickers = current_tickers - cached_tickers
if new_tickers:
    # yfinance에서 신규 종목들의 1/2 가격만 fetch → 캐시에 추가
# 제거된 종목은 캐시에 남겨둠
```

### 5.7 Wife 포트 분리

- `data/baseline_2026_me.json` / `data/baseline_2026_wife.json` 별도 파일
- 각자 자기 portfolio.md 기준으로 v0 계산
- USD/KRW, SPY 가격은 단순함을 위해 각 파일에 중복 저장

### 5.8 실패 시 Fallback

- 최초 baseline 빌드 실패 → 파이프라인은 계속 진행, YTD/S&P 표시는 "데이터 준비 중" placeholder. 다음 실행 시 재시도
- 일부 종목만 fetch 실패 → 그 종목만 제외하고 진행, 콘솔 경고

---

## 6. 테스트 전략

### 6.1 단위 테스트 (`tests/test_benchmark_ytd.py`)

| 테스트 | 목적 |
|---|---|
| `test_compute_v0_total_krw_basic` | 미국+한국 종목 혼합 보유 시 v0 합산 정확성 |
| `test_compute_v0_with_krw_cash` | KRW 현금이 v0에 그대로 반영되는지 |
| `test_compute_v0_with_usd_cash` | USD 현금이 1/2 환율로 환산되는지 |
| `test_compute_returns_alpha_calculation` | 포트 +5%, S&P +3% → α=+2.0pp |
| `test_compute_returns_negative_alpha` | 포트 -2%, S&P +1% → α=-3.0pp |
| `test_baseline_cache_skip_existing_tickers` | 신규 ticker만 fetch (yfinance mock으로 호출 횟수 검증) |
| `test_baseline_excludes_unmappable_ticker` | 매핑 실패 시 v0/v_now에서 모두 제외 |
| `test_baseline_post_2026_listing` | 1/2 이후 상장 종목은 첫 거래일 가격을 baseline으로 사용 |

### 6.2 통합 테스트

- `tests/test_pipeline_with_benchmark.py`: 파이프라인 끝까지 실행 → `portfolio_daily.json`에 `ytd_pct`, `spy_ytd_pct`, `alpha_pp` 키 추가 검증
- mock yfinance로 결정론적 가격 데이터 사용
- 기존 테스트 회귀 확인: `test_scanner_data.py`, `test_politician_filter.py` 등

### 6.3 수동 검증 체크리스트

1. 첫 파이프라인 실행 후 `data/baseline_2026_me.json` / `..._wife.json` 생성 확인
2. 메인 리포트 헤더에 "2026 YTD: +X.X% · S&P(₩): +Y.Y% · α: +Z.Zpp" 표시 확인
3. 트렌드 페이지에 정규화 비교 차트(포트 vs S&P) 표시 확인
4. 손계산 검증: 보유 1종목(예: AAPL 100주)만 두고 v0_krw = 100 × Jan2_close × Jan2_FX 일치 확인
5. 보유 종목 변경 시뮬레이션: portfolio.md에 종목 1개 추가 → 다음 실행 후 캐시에 신규 ticker만 추가됐는지

### 6.4 정확도 검증 (post-deploy)

- 첫 1주일간 매일 수치 모니터링: yfinance 종가 갱신 시 YTD가 합리적 범위에서 변동하는지
- 외부 소스(Naver Finance SPY 환산 가격)와 ±0.5%pp 이내 일치 확인

---

## 7. 작업 범위 (Out of Scope)

다음은 본 spec에서 다루지 않음:

- TWR(Time-Weighted Return) 도입 — 별도 spec 필요 (Mar 5 ~ 한정)
- 이전 연도(2025) 비교 — 2026 한정
- 종목별 기여도 분해 (어떤 종목이 알파에 얼마나 기여했나) — 후속 작업 후보
- 다중 벤치마크 (NASDAQ, KOSPI 등) — SPY만 우선
- 모바일 차트 인터랙션 최적화 — 기존 차트 동작 패턴 따름

---

## 8. 결정 기록 (Decisions)

| # | 결정 | 근거 |
|---|---|---|
| D1 | Constant-portfolio backtest (Jan 1 anchored) | 단순성, Jan 1 비교 가능, 사용자 명시적 선택 |
| D2 | v0 매 실행 재계산 (B안) | 신규 매수 시 분모-분자 함께 움직여 비율 안정 |
| D3 | KRW 환산 벤치마크 | 포트가 KRW 표시이므로 같은 기준 비교 |
| D4 | SPY (Adj Close) 사용 | 배당 재투자 반영, 실거래 가능 수단 |
| D5 | 표시: 메인 헤더 + 트렌드 페이지 둘 다 (옵션 C) | 빠른 확인(헤더) + 시계열 추이(트렌드) 상호 보완 |
| D6 | 트렌드 페이지: 별도 정규화 차트 신설 (옵션 A) | 기존 KRW 차트 정보 보존, 비교 차트는 목적 분명 |
| D7 | 한계는 UI 캐비엇 툴팁으로 명시 | 사용자가 수치 해석 시 오해 방지 |
