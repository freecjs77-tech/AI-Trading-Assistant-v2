# Trend Page YTD Chart: 디아이티 / 나머지 분해 Design

**작성일:** 2026-05-11
**작성자:** brainstorming session (사용자 요청 기반)
**상태:** Approved, ready for plan

---

## 1. 배경 (Context)

트렌드 페이지의 `포트폴리오 vs S&P 500 (₩) — 2026 YTD` 라인 차트는 현재 두 라인을 표시한다:

- **Portfolio (₩)**: 현재 보유 동결 기준, 모든 종목의 1/2 anchor 대비 KRW 수익률
- **S&P 500 (₩)**: SPY × USD/KRW의 1/2 anchor 대비 KRW 수익률

내 포트(me)는 **디아이티(110990) 단일 종목이 ₩14.96억(전체 weight의 67%)**으로 압도적 비중을 차지한다. 와이프 포트에도 ₩5.19억이 있다. 결과적으로 **Portfolio (₩) 라인의 움직임이 디아이티 가격 변동에 크게 끌려가서**, 시장(S&P 500) 대비 나머지 종목들의 실력을 분리해서 보기 어렵다.

이 디자인은 차트에 라인 2개를 추가하여 그 분리를 가능하게 한다:

- **디아이티 (110990)**: 110990 단독의 1/2 anchor 대비 YTD
- **나머지**: 포트폴리오에서 110990을 차감한 나머지 보유의 1/2 anchor 대비 YTD

## 2. 비목표 (Non-goals)

- 디아이티 외의 다른 종목 분해는 하지 않는다. 향후 outsized position이 새로 생기면 그때 동일 패턴으로 확장한다.
- 상단 YTD 카드 그리드(Portfolio / S&P 500 / Alpha)는 변경하지 않는다. 분해는 **차트 한정**.
- 자동매매 신호 변경 없음. 시그널 로직 무영향.
- baseline_2026_*.json 캐시 재계산 없음. 기존 캐시 값 그대로 사용.

## 3. 사용자 결정 (Locked)

| # | 결정 | 채택안 |
|---|---|---|
| 1 | 표시 스코프 | **차트만** (카드 변경 없음) |
| 2 | Owner 토글 범위 | **3개 뷰 모두** (me / wife / 합산) |
| 3 | 시계열 시작 | **2026-01-02 전체 backfill** (1/2 부터) |
| 4 | 차트 레이아웃 | **단일 Y축, 4 라인** (디아이티 1/2 anchor YTD가 ~+61% 수준으로 outlier 아님이 확인됨) |
| 5 | Y축 수동 토글 라벨 | **0~80%** (기존 0~50%에서 확대, 디아이티 잠재 outlier 여유 확보) |

## 4. 데이터 모델

### 4.1 신규 필드 (6개)

`history/portfolio_daily.json` / `history/portfolio_daily_wife.json` 각 일자 entry에 추가:

```json
{
  "...": "기존 필드들",
  "ytd_pct": 45.21,
  "spy_ytd_pct": 6.85,
  "alpha_pp": 38.36,
  "v0_krw": 1755816979,
  "spy_v0_krw": 983565.41,

  // ▼ NEW (예시 수치: me 2026-04-24 기준 추정, 실제 값은 backfill 산출)
  "dit_ytd_pct": 60.93,
  "rest_ytd_pct": 12.5,
  "dit_v0_krw": 1009792110,
  "dit_now_krw": 1625064750,
  "rest_v0_krw": 746024869,
  "rest_now_krw": 924643417
}
```

**왜 6 필드인가:**

- `dit_ytd_pct`, `rest_ytd_pct`: 차트 라인 데이터
- `dit_v0_krw`, `rest_v0_krw`: 감사용 (1/2 시점 평가)
- `dit_now_krw`, `rest_now_krw`: **합산 뷰 산출에 필수** — me/wife의 % 가중평균을 직접 계산할 수 없으므로 KRW 절대값을 합산 후 `(합 now / 합 v0 - 1) × 100`으로 재계산해야 함

### 4.2 None 시나리오

110990 미보유 owner는 6 필드 모두 `null`. 향후 가족 포트가 추가되거나 디아이티 매도 후 게신다면 자연스럽게 처리됨.

### 4.3 합산 뷰 (combined)

`report_generator._build_combined_payload()`가 me + wife daily를 date-union 합산하는 기존 패턴을 그대로 사용:

```
combined.dit_v0_krw   = (me.dit_v0_krw  or 0) + (wife.dit_v0_krw  or 0)
combined.dit_now_krw  = (me.dit_now_krw or 0) + (wife.dit_now_krw or 0)
combined.rest_v0_krw  = (me.rest_v0_krw or 0) + (wife.rest_v0_krw or 0)
combined.rest_now_krw = (me.rest_now_krw or 0) + (wife.rest_now_krw or 0)

combined.dit_ytd_pct  = (dit_now_krw  / dit_v0_krw  - 1) × 100  if dit_v0_krw  > 0 else None
combined.rest_ytd_pct = (rest_now_krw / rest_v0_krw - 1) × 100  if rest_v0_krw > 0 else None
```

## 5. 계산 공식

### 5.1 디아이티 단독 YTD

```
dit_v0_per_share  = baseline["ticker_v0_krw"]["110990"]      # 캐시 (₩15,690)
dit_now_per_share = today_prices["110990"]                   # KRW (KOSDAQ → 환율 무관)
dit_ytd_pct       = (dit_now_per_share / dit_v0_per_share - 1) × 100
dit_shares        = holdings에서 110990 shares
dit_v0_krw        = dit_shares × dit_v0_per_share
dit_now_krw       = dit_shares × dit_now_per_share
```

**핵심**: KOSDAQ 종목이므로 USD/KRW 변동에 영향 없음. `is_korean_ticker(110990) == True` 분기로 환율 곱셈 회피.

### 5.2 나머지 YTD

기존 `compute_returns()`가 산출한 `v0_krw`, `v_now_krw`에서 디아이티 기여분 차감:

```
rest_v0_krw   = v0_krw   - dit_v0_krw
rest_now_krw  = v_now_krw - dit_now_krw
rest_ytd_pct  = (rest_now_krw / rest_v0_krw - 1) × 100  if rest_v0_krw > 0 else None
```

**일관성 보장**: `compute_returns()`가 적용하는 excluded_tickers 동기화(unmappable / 가격 누락 종목 v0와 v_now에서 동시 제외) 이후에 분해를 수행하므로, **dit + rest = total**이 항상 성립한다.

### 5.3 110990 미보유 처리

```python
if "110990" not in baseline["ticker_v0_krw"] or "110990" not in today_prices:
    dit_ytd_pct = rest_ytd_pct = None
    dit_v0_krw = dit_now_krw = rest_v0_krw = rest_now_krw = None
```

## 6. 시각화

### 6.1 차트 datasets (4 라인)

| 라인 | 색상 | 스타일 | 출처 필드 |
|---|---|---|---|
| Portfolio (₩) | `#00E5BC` (청록, 기존 secondary) | 실선, fill, tension 0.3, borderWidth 2 | `trend[i].ytd_pct` (기존) |
| 디아이티 (110990) | `#ff716c` (적색, 기존 tertiary) | 실선, no fill, tension 0.3, borderWidth 2 | `trend[i].dit_ytd_pct` (NEW) |
| 나머지 | `#a78bfa` (보라색, 신규 색상) | 실선, no fill, tension 0.3, borderWidth 2 | `trend[i].rest_ytd_pct` (NEW) |
| S&P 500 (₩) | `#a3aac4` (회색) | 점선 `borderDash:[6,4]`, no fill | `trend[i].spy_ytd_pct` (기존) |

**색상 충돌 검토**:
- `#fbbf24`(앰버)는 같은 페이지의 fxChart에서 사용 중 → 회피.
- `#ff716c`(tertiary)는 같은 페이지의 vixChart/divChart에서도 사용되지만, 별도 차트라 혼동 위험 낮음. 디아이티 단독 (단일 종목 강조)에 의미상 적합.
- `#a78bfa`(violet)는 트렌드 페이지에서 미사용 → "나머지"(복합)에 신규 배정.

Datasets 배열 순서가 곧 legend 순서. 위 표 순서대로 배열에 push.

### 6.2 Y축 토글

기존 `ytdRangeToggle`의 manual 모드 범위 `{ min: 0, max: 50 }` → `{ min: 0, max: 80 }`. 라벨 텍스트도 `0~50%` → `0~80%`.

### 6.3 None 처리

Chart.js 기본 동작(`spanGaps: false`)으로 null 구간은 라인 단절. 110990 미보유 owner는 디아이티/나머지 라인 자체가 전 구간 null → 자동으로 안 그려짐.

### 6.4 Owner 토글 인터랙션

기존 `_updateYtdChart(trendArr)` 함수에 datasets[2], datasets[3] 업데이트 로직 추가. owner 전환 시 4 라인 모두 해당 owner의 trend 데이터로 재바인딩.

## 7. 시스템 통합

### 7.1 단일 진실의 원천

`benchmark_ytd.compute_returns()` 단 한 곳에서 분해 계산. 호출자:

- `benchmark_ytd.compute_owner_benchmark()` — pipeline 매일 호출
- `rebuild_portfolio_history.py` — 1회 backfill

→ 양쪽 경로가 동일한 값 산출 (Tests에서 검증).

### 7.2 Backfill

기존 `rebuild_portfolio_history.py`는 SPY 마지막 인덱스까지 일자별 가격을 replay하여 me/wife daily JSON을 재생성한다. 이 루프 안에서 `compute_returns()`가 호출되도록 hook 추가 → 6 신규 필드도 함께 채워짐.

**실행**: `python rebuild_portfolio_history.py`
- 백업: `history/portfolio_daily.json.bak.20260511-rebuild`, `history/portfolio_daily_wife.json.bak.20260511-rebuild`
- 결과: 2026-01-02 ~ 최신 거래일까지 me/wife 양쪽 모두 갱신

### 7.3 Going-forward

매일 `pipeline.py:735`에서 `history_manager.save_portfolio_snapshot()`에 YTD 필드들을 전달한다 (owner마다 1회). 이 path에 6 신규 필드도 함께 전달:

- `history_manager.save_portfolio_snapshot()` (현 line 210~242) — 함수 시그니처 확장: `dit_ytd_pct`, `rest_ytd_pct`, `dit_v0_krw`, `dit_now_krw`, `rest_v0_krw`, `rest_now_krw` 추가 (모두 `float | None = None`)
- `pipeline.py:735-737` 호출부 — `_bm.get("dit_ytd_pct")` 등 추가 전달

`compute_owner_benchmark()`가 반환 dict에 신규 6 키를 추가하면 호출자(pipeline, rebuild) 양쪽에 자동 반영됨.

## 8. 테스트 전략

### 8.1 단위 테스트 (`tests/test_benchmark_dit_decomposition.py`)

1. **보유 케이스**: 110990 포함 holdings + 캐시된 baseline + 합리적 today_prices → 6 필드 모두 산출, 값 검증
2. **미보유 케이스**: holdings에 110990 없음 → 6 필드 모두 None
3. **환율 무관성**: today_usd_krw를 2배로 늘려도 `dit_ytd_pct` 불변 (KOSDAQ 환율 무관 검증)
4. **수학적 일관성**: `dit_v0_krw + rest_v0_krw == v0_krw` (excluded_tickers 동기화 후)
5. **합산 시뮬레이션**: me, wife 가상 결과 → date-union 합산 후 % 재계산 검증

### 8.2 통합 검증

- `python rebuild_portfolio_history.py` 실행 후 spot-check:
  - 1/2 entry: `dit_ytd_pct == 0.0` (baseline v0 = 1/2 close, today_price@1/2 = 1/2 close → 비율 정확히 1.0). `rest_ytd_pct` 도 마찬가지로 0.0.
  - 최신 entry: 110990 단독 yfinance fetch한 `(today_close / 15690 - 1) × 100`과 `dit_ytd_pct` 일치 검증.
  - 임의 중간 일자: `dit_v0_krw + rest_v0_krw == v0_krw` (소수점 오차 1e-3 이내) 검증.
- `SKIP_SCANNERS=1 python pipeline.py` 실행 후 trend 페이지 시각 검증:
  - me/wife/합산 토글 → 4 라인 정상 표시
  - Auto/0~80% 토글 → 디아이티 라인이 0~80% 박스 안에 들어가는지

## 9. 위험 & 완화

| 위험 | 영향 | 완화 |
|---|---|---|
| baseline 캐시의 v0 값 부정확 | YTD 절대값 오차 | 현재 `data/baseline_2026_me.json["ticker_v0_krw"]["110990"]==15690`은 yfinance와 일치 — 검증 완료 |
| Yahoo API rate limit (backfill 중) | 백필 실패/부분 데이터 | `portfolio_history_core`의 기존 sequential + delay 패턴 그대로 사용. 캐시 활용. |
| 합산 뷰 한쪽만 미보유 | 합산 결과 왜곡 | 현재 me·wife 둘 다 보유. one-side None은 0 합산이라 자동 처리. 양쪽 모두 None일 때만 합산도 None. |
| 향후 디아이티 매도 → 보유 동결 충돌 | 시계열 불연속 | rebuild 패턴의 "현재 보유 동결" 원칙 그대로 — 매도 시점 이후 going-forward는 None, 과거는 동결 시점 holdings 기준. 매도 결정 시 별도 결정. |
| 기존 daily JSON 백업 누락 | 데이터 손실 위험 | `rebuild_portfolio_history.py`가 `*.bak.YYYYMMDD-rebuild` 자동 백업 (기존 동작) + pre-commit 가드(`.githooks/`)가 dict 키 감소 detect |

## 10. 파일 변경 요약

**Create:**
- `tests/test_benchmark_dit_decomposition.py`
- `docs/superpowers/specs/2026-05-11-trend-dit-decomposition-design.md` (이 문서)
- `docs/superpowers/plans/2026-05-11-trend-dit-decomposition.md` (writing-plans 단계에서 생성)

**Modify:**
- `benchmark_ytd.py` — `compute_returns()` 6 필드 추가
- `pipeline.py` — daily snapshot 작성 시 6 필드 포함
- `rebuild_portfolio_history.py` — replay 루프에서 6 필드 backfill
- `report_generator.py` — `_build_owner_payload()` / `_build_combined_payload()` 6 필드 pass-through + 합산 재계산
- `templates/trend_template.html` — datasets 2개 추가, Y축 토글 0~80%
- `CLAUDE.md` — "진행 중인 계획" 섹션에 신규 plan 등록

**Auto-generated:**
- `history/portfolio_daily.json.bak.20260511-rebuild`
- `history/portfolio_daily_wife.json.bak.20260511-rebuild`
- `history/portfolio_daily.json` (덮어쓰기, 1/2~ 최신)
- `history/portfolio_daily_wife.json` (덮어쓰기, 1/2~ 최신)

## 11. 시그널 / 자동매매 영향

**없음.** 본 변경은 트렌드 페이지 시각화 한정. `signal_judge.py`, `strategy.md`, `pipeline`의 시그널 생성 path는 무영향. 새 필드는 모두 reporting/audit용.
