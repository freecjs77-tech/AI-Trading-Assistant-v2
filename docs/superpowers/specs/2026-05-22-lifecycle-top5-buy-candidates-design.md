# Lifecycle Top 5 Buy Candidates — Design Spec

**Date**: 2026-05-22
**Status**: Draft (pending user review)
**Target page**: `lifecycle_us.html` (US 우선, KR 차후)

---

## 1. Background & Motivation

### Current observations (2026-05-21 page)
- Lifecycle US 페이지: 추적 29종목 → TRENDING 4 · WATCH 15 · PROBE 8 · **ENTER 0** · AVOID 2 (모두 BROKEN)
- ENTER decision은 사실상 한 번도 fire한 적 없음 (trigger score ≥ 7 임계값이 너무 높아 4개+ 컴포넌트가 동시에 성립해야 함)
- EXTENDED (과열) 종목은 `hard_risk_veto`로 무조건 AVOID 처리 → 강세장에서 NVDA류 강한 종목들이 시야에서 사라짐
- Momentum 페이지가 비어도 lifecycle PROBE에 8종목이 잡혀 있어 UX 혼란 (compute_active_set은 14일 lookback)

### User goal
"매일 액션 가능한 최대 5개 매수 후보를 한눈에 보고 싶다. 모멘텀 강함과 setup 좋음 두 신호를 결합한 ranking. 과열도 포함. 이미 보유한 종목도 포함 (추가 매수 판단용)."

### Design intent
- 기존 lifecycle 5-stage 파이프라인은 **상세 진단용으로 유지**
- 그 위에 **actionable 1-stop 섹션** 추가: 오늘 매수 후보 Top 5
- 자동매매 ❌ / display only · 사용자 최종 판단

### 의도된 chase 성격 (중요)
점수 구조상 **M3 (+4 보너스)** 는 사실상 EXTENDED 조건과 거의 동치 (52주 신고가 + RSI≥65). 반면 **EM (+1 보너스)** 은 명시적 anti-overheat 게이트(RSI<72, dist_ema9<8%) 보유. EXTENDED 페널티도 제거되어, 결과적으로 **"신고가 + 과열 + 강RS"** 종목이 자연스럽게 top 1~2위에 정렬되는 momentum chase 구조. 이는 사용자 의도된 선택 ("강세 종목 우선, setup 좋으면 ENTER로 보너스").

---

## 2. Source Pool

**Inclusion**:
- Lifecycle active_set (BROKEN 제외, EXTENDED 포함)
- Portfolio tickers (BROKEN 제외)
- → 합집합

**Exclusion**:
- setup_state == "BROKEN" (장기 추세 깨진 종목)
- 데이터 결손 (close/ema9 등 핵심 필드 누락)

**Portfolio 종목 lifecycle 평가**:
- [pipeline.py:438](pipeline.py:438) 에서 이미 `_portfolio_tickers = set()` (빈 집합) 으로 `run_lifecycle` 호출 → `compute_active_set`의 portfolio 제외 룰이 작동하지 않음
- **결과적으로 portfolio 종목은 이미 active_set에 포함되어 lifecycle snapshot으로 평가됨** (2026-05-09 사용자 결정)
- 본 feature는 `result['snapshots']` 을 그대로 풀로 사용. 별도 stateless 평가 불필요.
- Portfolio 식별: `portfolio_paths.discover_portfolios()` 의 holdings ticker 집합을 `_render`에 전달하여 "보유 중" 배지 표시 용도로만 사용

---

## 3. Ranking Score

### Formula
```
final_score = base_score
            + momentum_bonus
            + rs_bonus
```

### base_score — 0~14 스케일 정규화
Setup마다 lifecycle 점수 산출 트랙이 다르므로 통일:

| setup_state          | base_score 계산                              |
|----------------------|---------------------------------------------|
| PULLBACK             | `trigger_score` (0~14, 그대로 사용)         |
| BASE_FORMING         | `trigger_score` (0~14, 그대로 사용)         |
| TREND_OK             | `drift_score × 14/9` (0~14, 정규화)         |
| EXTENDED             | `_raw_score × 14/9` (veto 시 drift 저장됨)  |
| 기타 / score 없음    | 0                                           |

(score = None → 0. veto된 EXTENDED의 `_raw_score`는 `_evaluate_decision_score`가 이미 분석용으로 계산하여 snapshot에 저장.)

### momentum_bonus — 0~4
오늘 momentum scanner의 결과 (history JSON `scanner_momentum_us_history.json`의 today entry):

| stage         | bonus |
|---------------|-------|
| MOMENTUM_3    | +4    |
| MOMENTUM_2    | +3    |
| MOMENTUM_1    | +2    |
| EM            | +1    |
| 없음          | 0     |

### rs_bonus — 0~3
Lifecycle snapshot의 `rs_delta_pct` (compute_trigger_score / compute_drift_score 모두 출력):

| rs_delta_pct  | bonus |
|---------------|-------|
| > 10%p        | +3    |
| > 5%p         | +2    |
| > 0%p         | +1    |
| ≤ 0           | 0     |

### Ranking & Cap
- `final_score` desc 정렬, 동점 시 `rs_delta_pct` desc
- **Quality threshold**: `final_score ≥ 5` 인 종목만 후보
- **Cap**: 최대 5개
- 5개 못 채우면 솔직 표시 — "오늘은 N/5"

---

## 4. Display

### 위치
`templates/lifecycle_us.html` — 기존 5-stage 파이프라인 섹션 **상단**에 새 섹션 삽입.
기존 섹션은 그대로 유지 (상세 진단 용도).

### 섹션 구성
**제목**: `🎯 오늘의 매수 후보 (보유 추가 포함)`

**테이블 컬럼**:
| # | Ticker | Decision | Setup | Score | RS | 키 지표 | 사이즈 hint |
|---|--------|----------|-------|-------|------|---------|-------------|

- **#**: 1~N 랭킹
- **Ticker**: 종목 코드 + 한글명
- **Decision**: ENTER / PROBE / WATCH / TRENDING. 보유 종목은 옆에 `🏦 보유 중` 배지
- **Setup**: PULLBACK / TREND_OK / EXTENDED 등. EXTENDED면 `⚠️ 과열` chip
- **Score**: `final_score` (소계 표시: base+momentum+rs)
- **RS**: `rs_delta_pct` (%p, +/- 색상)
- **키 지표**: RSI, dist_ema9_pct, 거래량 비율 압축 표시
- **사이즈 hint**:
  - 신규 (portfolio 외): "신규 50%" 또는 "신규 25%" (EXTENDED)
  - 보유 중: "추가 25%" (EXTENDED), "추가 50%" (정상) — 별도 라벨

### 빈 상태 처리
- 0~4개일 때: "오늘은 N/5 — 시장이 약하거나 강한 setup 부족"
- 0개일 때: "오늘 매수 후보 없음 (모든 종목 score < 5)"

### 안내문
섹션 하단 작은 글씨:
> *⚠️ 자동매매 아님 — display only. 매수 결정은 사용자 판단. 사이즈는 권장치이며 강제 아님.*

---

## 5. Code Organization

### 신규 모듈
**`lifecycle_buy_candidates.py`** — 풀 구성 + ranking
- `build_candidate_pool(active_snapshots, portfolio_tickers, market_data, yesterday_market_data) -> list[dict]`
- `compute_final_score(candidate, momentum_today) -> dict` (final_score, base, momentum_bonus, rs_bonus 분해 반환)
- `rank_top_n(candidates, momentum_history_today, *, threshold=5, cap=5) -> list[dict]`

### 수정
**`lifecycle_report.py::_render`** ([lifecycle_report.py:296](lifecycle_report.py:296))
- buy_candidates 모듈 호출 → template context (`ctx`) 에 `top5_candidates`, `top5_count`, `top5_max=5` 주입
- 호출 시점: `tmpl.render(**ctx)` 직전

**`templates/lifecycle_us.html`** (US 우선; KR은 후속 PR)
- 새 섹션 `<section id="top5-buy-candidates">` 추가 (기존 narrative 박스와 5-stage 파이프라인 사이)

### 변경 없음
- `lifecycle_signal.py` — 글로벌 lifecycle 로직 무수정
- `lifecycle_history.py` — `compute_active_set`의 portfolio 제외 그대로
- `lifecycle_config.py`, `lifecycle_score_config.py` — 임계값 무수정
- `momentum_*` 모듈 — 무수정 (출력만 읽음)

---

## 6. Data Flow

```
[market_data_YYYY-MM-DD.json]
       ↓
[lifecycle_history.json] ── active_set (29종목, portfolio 제외)
       ↓                                                     ↓
[snapshots] ──────────────────────┐                          │
                                  │                          │
                                  ▼                          ▼
                  ┌────── lifecycle_buy_candidates ──────────┐
                  │  1. pool = active + portfolio (BROKEN 제외)│
                  │  2. portfolio: stateless lifecycle eval   │
                  │  3. score: base + momentum + rs           │
                  │  4. rank, threshold≥5, cap 5              │
                  └──────────────────┬───────────────────────┘
                                     ↓
                  [scanner_momentum_us_history.json] (read)
                                     ↓
                       top5_candidates (list of dicts)
                                     ↓
                           lifecycle.html (template)
```

---

## 7. Error Handling

- `compute_active_set` 결과 비어있음 → portfolio만으로 진행. 그것도 비면 "0/5" 표시
- Portfolio 종목 market_data 없음 → skip (warn log)
- momentum_history 파일 없음 → momentum_bonus = 0 (degraded)
- 점수 계산 중 예외 → 해당 종목 제외 (warn log, 페이지는 정상 렌더)

---

## 8. Testing Strategy (TDD)

`tests/test_lifecycle_buy_candidates.py`:

1. **build_candidate_pool**
   - active_set + portfolio union 정상
   - BROKEN 제외 (active든 portfolio든)
   - EXTENDED 포함
   - 결손 데이터 skip

2. **compute_final_score**
   - PULLBACK setup: trigger_score 그대로 base
   - TREND_OK setup: drift_score × 14/9 정규화
   - EXTENDED: _raw_score × 14/9
   - momentum_bonus 매핑 정확 (M3→4, M2→3, M1→2, EM→1, none→0)
   - rs_bonus 매핑 (>10:+3, >5:+2, >0:+1)
   - score None → 0

3. **rank_top_n**
   - score desc + rs_delta_pct desc tiebreak
   - threshold ≥ 5 미달 제거
   - cap 5
   - 빈 결과 정상 반환

4. **Integration**
   - 실제 lifecycle snapshot fixture로 end-to-end
   - 오늘 5/21 데이터 (8 PROBE, 0 ENTER) 입력 시 적절한 5개 반환

---

## 9. Open Questions / Future Work

- **KR 시장**: 동일 패턴 복제 (lifecycle_kr.html). 별도 PR.
- **Telegram brief**: Top 5를 일일 알림에 포함? (별도 결정)
- **History tracking**: 매일의 top 5 기록을 별도 JSON으로 저장? (현재 design엔 미포함)
- **Trigger 연속성**: portfolio 종목은 yesterday snapshot 없음 → trigger_state가 항상 fresh. Phase 2에서 portfolio 자체 lifecycle history 도입 검토.
- **Sizing 자동 적용**: 현재 display only. 미래에 portfolio_stop_signal과 연계해서 실제 size 추천 가능.

---

## 10. Out of Scope (이번 PR에서 제외)

- 자동매매 / order 발생
- KR 시장 적용
- Telegram brief 통합
- Top 5 history 저장
- 임계값 calibration (5 vs 6 등) — 운영 후 데이터 보고 튜닝
