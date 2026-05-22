# Top 5 Buy Candidates — Universe Expansion (momentum-only tickers)

**Date:** 2026-05-22
**Status:** Design (awaiting user spec review)
**Related:** [Lifecycle Top 5 Buy Candidates plan](../plans/2026-05-22-lifecycle-top5-buy-candidates.md), [Trade Lifecycle Phase A plan](../plans/2026-05-08-trade-lifecycle-phase-a.md)

---

## 1. Problem

오늘 momentum 스캐너 페이지에 잡힌 종목 10개 중 7개(LRCX, ARM, ASML, DXCM, IBM, SNDK, STX)가 Lifecycle US Top 5 후보에 들어올 수 없는 현상이 관찰됨. 원인은 두 가지가 누적된 구조적 결과:

1. **유니버스 불일치** — Top 5의 후보 풀은 `result["snapshots"]`(=lifecycle active_set, 오늘 기준 29종목)에서 시작. Momentum 스캐너는 SP100∪NDX100(~169) 위에서 돌아 결과가 active_set 밖일 수 있음.
2. **하루 지연** — active_set 진입 조건 ([lifecycle_history.py:134-186](../../../lifecycle_history.py)) 중 momentum 경로는 `momentum_history` 파일을 거치므로, 오늘 처음 M+가 잡힌 ticker는 다음 날에야 active_set에 들어옴.

결과: momentum_bonus 가산점이 설계대로 동작하지 않아 hybrid 점수의 의의가 약화됨.

## 2. Goal

Top 5 후보 풀에 **오늘의 momentum 스캐너 결과를 직접** 합치되, lifecycle 5-stage 파이프라인과 lifecycle history 저장 로직은 무영향. 즉 **Top 5에만 국한된 universe 확장**.

### Non-goals

- 5-stage 파이프라인 UI에 momentum-only ticker 노출
- Lifecycle history (`lifecycle_history_us.json`)에 momentum-only ticker 저장
- `active_set` 룰 자체 변경 (다른 진입 경로 추가)
- KR 시장 적용 (US만 — KR은 후속)
- Telegram brief 통합
- 자동매매 / 사이즈 자동 적용

## 3. Architecture

### 3.1 전체 흐름

```
pipeline.py (Step 4c)
├─ Step 4c2: scanner_us_result = run_momentum_scanner("US", market_data, ...)
│              ├─ M+/EM 종목 list (live, 메모리 보관)
│              └─ scanner_momentum_us_history.json 갱신 (기존 동작)
├─ Step 4c4: lifecycle_us_result = run_lifecycle("US", market_data,
│                                                  momentum_history_path, ...)
│              ├─ snapshots: active_set 29종목 (변경 없음)
│              └─ market_ret_5d_pct: float (이미 result 안에 있음)
└─ Lifecycle render step: generate_lifecycle_pages(
                    us_result=lifecycle_us_result,
                    portfolio_tickers=...,
                    momentum_today_us=scanner_us_result,  ← NEW
                    market_data=market_data,              ← NEW
                  )
                    └─ _render
                        └─ select_top5_buy_candidates(...,
                              momentum_today=momentum_today_us,
                              market_data=market_data,
                              market_ret_5d_pct=...)
```

### 3.2 핵심 원칙

- **Stateless 확장**: yesterday snapshot이 필요한 lifecycle state machine과 달리 Top 5는 today 데이터만으로 ranking 가능. on-the-fly 계산이 의미 있음.
- **No persistence**: 합성 snapshot은 메모리에서만 살고 history에 저장하지 않음.
- **Single source of truth for scoring**: base/momentum/RS 보너스 공식은 momentum-only ticker에도 동일하게 적용 (asymmetry 없음).

## 4. Components

### 4.1 `lifecycle_signal.py` — single-ticker helper 추출

**신규 export:**
```python
def compute_single_snapshot(*, ticker: str,
                              market_data_entry: dict,
                              market_ret_5d_pct: float | None,
                              yesterday: dict | None,
                              today: str) -> dict | None:
    """Build a lifecycle snapshot for one ticker without touching history.

    Reuses _build_today_raw_for_signal → evaluate_setup_state →
    evaluate_trigger_state → _evaluate_decision_score. Returns the same
    snapshot dict shape that process_universe produces per ticker.
    Returns None if market_data_entry is missing required fields.
    """
```

**리팩터:** `process_universe`의 per-ticker 본문을 이 함수로 추출. process_universe는 이 함수를 active_set 루프 안에서 호출. 동작 동일 보장은 기존 lifecycle 골든 테스트 통과로 검증.

### 4.2 `lifecycle_buy_candidates.py` — selector 확장

**시그니처 변경:**
```python
def select_top5_buy_candidates(*,
        snapshots: dict,
        portfolio_tickers: set,
        momentum_history: dict,        # 기존 — fallback 용도로 유지
        today: str,
        # NEW
        momentum_today: list[dict] | None = None,  # 오늘 스캐너 live 결과
        market_data: dict | None = None,
        market_ret_5d_pct: float | None = None,
        threshold: float = 5.0, cap: int = 5) -> dict:
```

**로직 추가:** `build_candidate_pool` 다음 단계에서 momentum-only 풀 합치기:
1. 기존: `snapshots`에서 BROKEN 제외해 pool 생성 (~27)
2. **신규**: `momentum_today` 안에서 `snapshots`에 없는 ticker 추출
   → 각각 `compute_single_snapshot` 호출 (`yesterday=None`, market_data_entry는 `market_data["data"][ticker]` 또는 `market_data[ticker]`)
   → 반환 snapshot이 None이거나 setup이 BROKEN이면 skip
   → `_scanner_only: True` 마킹 후 pool에 append
3. 합쳐진 pool → 기존 `rank_top_n` 로직 그대로 적용

**호환성**: `momentum_today=None` 일 때는 기존 동작 그대로 (테스트 fixture 보호).

### 4.3 `lifecycle_report.py` — _render / generate 시그니처 확장

`generate_lifecycle_pages`, `_render` 양쪽에 `momentum_today_us`, `momentum_today_kr`, `market_data` kwargs 추가. `_render`는 받은 값을 그대로 `select_top5_buy_candidates`로 전달. `market_ret_5d_pct`는 이미 `result`에 있으므로 `result.get("market_ret_5d_pct")`로 꺼냄.

### 4.4 `pipeline.py` — scanner result → lifecycle render 연결

Step 4c2의 `run_momentum_scanner` 반환을 변수에 보관 (현재는 history 갱신만 하고 반환값을 미사용 가능성 있음 — plan 단계에서 검증). 그 결과를 `generate_lifecycle_pages` 호출에 추가 kwarg로 전달.

### 4.5 `templates/lifecycle_us.html` — 배지 추가

Top 5 row에서 `c.snapshot._scanner_only`이면 ticker 옆에 `🚀 스캐너 신규` 칩 표시 (`is_portfolio` 배지와 동일 패턴, 색상은 구분). 둘 다 해당하면 두 배지 나란히.

## 5. Data shapes

### 5.1 momentum scanner per-ticker output (현재)

[momentum_signal.py:355-372](../../../momentum_signal.py)의 `evaluate_stock` 반환:
```python
{
    "ticker": "LRCX", "stage": "MOMENTUM_2", "tier": "MOMENTUM_2",
    "maturity": "MID", "risk_tags": [], "hint": "...",
    "rs_vs_sector": True, "sector": "Tech",
    "price": 1050.0, "rsi": 64.0,
    "ret_1d_pct": 2.5, "ret_3d_pct": 5.0, "ret_5d_pct": 8.2,
    "dist_ema9_pct": 3.1, ...
}
```

이 dict가 `momentum_today` 리스트 원소.

### 5.2 합성 snapshot (compute_single_snapshot 반환)

기존 process_universe per-ticker snapshot과 동일 shape. 새 필드:
- `_scanner_only: True` — UI에서 배지용 (compute_single_snapshot 호출처에서 마킹)
- `rs_delta_pct`: ticker의 `ret_5d_pct - market_ret_5d_pct`. 계산은 `_build_today_raw_for_signal` 또는 process_universe 본문에 이미 있음 → 추출된 helper에서 동일하게 동작.

### 5.3 Yesterday snapshot

momentum-only ticker는 lifecycle_state에 없으므로 `yesterday=None`. `evaluate_trigger_state(today, None, setup)` 의 None 처리 동작은 기존 코드 그대로 사용. (Plan 작성 시 확인하여 None safe 보장 필요 — 만약 None unsafe면 `evaluate_trigger_state`에 None guard 추가가 작은 부수작업이 됨.)

## 6. Edge cases

| 케이스 | 처리 |
|---|---|
| momentum 스캐너 ticker가 market_data에 없음 | skip — 같은 universe이므로 이론상 발생 X. 발생 시 print warn 후 pool 미포함 |
| compute_single_snapshot 반환 None (close/ema9 결측) | skip — process_universe와 동일 정책 |
| 합성 snapshot의 setup이 BROKEN | pool 미포함 — 기존 BROKEN 제외 룰과 일관 |
| 합성 snapshot의 setup이 EXTENDED | 기존과 동일하게 포함 + size_hint_label = "신규 25%" |
| 점수 동률 | 기존 tiebreak (rs_delta_pct desc) 유지 |
| momentum_today=None (호환성) | 기존 동작 — momentum_only 풀 비어있음 |
| KR 시장 | `momentum_today_kr` kwarg는 받지만 lifecycle_kr.html 템플릿이 top5 변수를 참조 안 하므로 무영향 (현재 KR Top 5 미구현 상태와 동일) |

## 7. Backward compatibility

- `select_top5_buy_candidates`의 신규 kwargs는 모두 default 있음 (`None`). 기존 테스트 호출 그대로 통과.
- `_render`, `generate_lifecycle_pages`의 신규 kwargs도 default `None`. 다른 호출처 영향 없음 (`pipeline.py` 외에는 호출 없음 — Grep 확인됨).
- Pre-existing lifecycle behavior: process_universe / save_lifecycle_history / history JSON shape 모두 동일.

## 8. Testing strategy

### 8.1 Unit tests

`tests/test_lifecycle_buy_candidates.py` 확장:
- `test_select_top5_includes_momentum_only_ticker` — snapshots에 없지만 momentum_today에 있는 ticker가 Top 5에 들어옴
- `test_select_top5_momentum_only_marked_scanner_only` — 합성 snapshot의 `_scanner_only` 플래그 검증
- `test_select_top5_momentum_only_uses_compute_single_snapshot` — base_score 계산이 lifecycle 정상 종목과 같은 0~14 스케일
- `test_select_top5_momentum_today_none_unchanged_behavior` — 후방 호환 (None 입력 시 기존 결과)
- `test_select_top5_template_renders_scanner_only_badge` — 템플릿 렌더링 검증

`tests/test_lifecycle_signal.py` 또는 신규 `tests/test_compute_single_snapshot.py`:
- `test_compute_single_snapshot_matches_process_universe` — 같은 입력에서 두 경로 결과 동일
- `test_compute_single_snapshot_no_yesterday` — yesterday=None에서 정상 동작
- `test_compute_single_snapshot_missing_data_returns_none`

### 8.2 Regression

기존 lifecycle 골든/시그널/히스토리 테스트 모두 통과 (process_universe 리팩터 후에도 출력 동일).

### 8.3 Smoke

`SKIP_SCANNERS=1`은 momentum scanner를 스킵하므로 사용 불가. 일반 pipeline 실행 후:
- `deploy/lifecycle_us_<today>.html` 에 LRCX/ARM 등이 Top 5에 등장하는지 (오늘 시장 상황에 따라 다름)
- 배지가 렌더되는지

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| `compute_single_snapshot` 추출이 process_universe 동작을 미세하게 바꿀 수 있음 | 골든 테스트 + 추출 전후 1회 회귀 비교 |
| `evaluate_trigger_state(yesterday=None)` 동작이 정의되지 않았을 가능성 | Plan Step 1에서 확인. None unsafe면 guard 추가 |
| Top 5 후보가 너무 많이 늘어 ranking이 노이즈화 | threshold=5.0 기존 유지 + 후보 풀에서 BROKEN/setup 결측 자동 필터. 측정 후 필요시 momentum-only 종목에 score 패널티 (현재는 추가 X) |
| Pipeline `run_momentum_scanner` 반환값이 직접 사용 가능한 list of dict가 아닐 수 있음 | Plan 작성 시 반환 형태 확인. 필요시 adapter 1개 추가 |

## 10. Affected files

| File | Change type |
|---|---|
| `lifecycle_signal.py` | Refactor — extract `compute_single_snapshot`, process_universe inner loop calls it |
| `lifecycle_buy_candidates.py` | Extend — new kwargs, momentum-only pool merge |
| `lifecycle_report.py` | Plumbing — _render / generate_lifecycle_pages kwargs |
| `pipeline.py` | Plumbing — capture scanner result, pass to generate_lifecycle_pages |
| `templates/lifecycle_us.html` | Add `🚀 스캐너 신규` chip in Top 5 row |
| `tests/test_lifecycle_buy_candidates.py` | New cases for momentum-only path + badge |
| `tests/test_lifecycle_signal.py` (or new file) | `compute_single_snapshot` parity tests |
| `CLAUDE.md` | Add plan one-liner to "진행 중인 계획" |

## 11. Open questions for plan stage

이 spec은 high-level 결정 확정. 다음 사항은 plan 단계에서 확정:

1. `run_momentum_scanner`의 실제 반환 shape — list of dict인지 dict-of-list인지 (pipeline.py에서 검증)
2. `evaluate_trigger_state(yesterday=None)`의 현재 동작과 None safe 여부
3. Template 변경 시 기존 골든 테스트의 snapshot diff 처리 패턴
4. `compute_single_snapshot` 호출 시 추가 fetch 필요 여부 — momentum 스캐너의 universe (SP100∪NDX100)는 `fetch_market_data`가 이미 모두 가져오므로 추가 fetch 없음을 검증
