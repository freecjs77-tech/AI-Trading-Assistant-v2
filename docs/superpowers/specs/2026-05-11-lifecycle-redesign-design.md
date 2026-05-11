# Lifecycle Page Redesign Design

**작성일:** 2026-05-11
**작성자:** brainstorming session (사용자 요청 + mockup 기반)
**상태:** Approved, ready for plan

---

## 1. 배경 (Context)

현재 Lifecycle US/KR 페이지(`templates/lifecycle_us.html` 441줄, `lifecycle_kr.html` 동등)는 테이블 위주 디자인으로, 결정(decision) 분류 결과를 그룹별 표로 나열한다. 정보는 충실하지만, 일반 사용자가 "오늘 어떤 종목이 진입 임박이고 어떤 종목을 피해야 하는지"를 한눈에 파악하기 어렵다.

사용자가 첨부한 mockup HTML이 시각적 재설계의 방향을 명확히 정의한다:

- **종목 흐름 파이프라인**: TRENDING → WATCH → PROBE → ENTER 5-stage 가로 flow로 "진입 임박" 정도를 즉시 가시화
- **컨셉 박스**: 페이지의 목적과 한계를 1단락으로 설명
- **오늘의 결론 (verdict box)**: 동적 narration으로 "오늘 할 일" 직접 전달
- **칩 그리드**: 테이블 대신 카드형 칩으로 종목 가독성 강화
- **용어 사전**: collapsible `<details>`로 입문자도 페이지 해석 가능

본 디자인은 mockup의 시각 패턴을 채택하면서, 기존 정보(transitions, BROKEN 종목, 상세 컬럼)를 collapsible "고급 보기" 섹션으로 보존한다.

## 2. 비목표 (Non-goals)

- **시그널 / 자동매매 path 무수정**: `lifecycle_signal.py`, `lifecycle_history.py`, `lifecycle_config.py` 손대지 않음. setup/trigger/decision 판정 로직 그대로.
- **데이터 모델 무변경**: `build_page_context()`가 이미 생성하는 `enter/probe/watch/trending/avoid/broken_table/new_confirmed/transitions` 그대로 사용. 신규 derived 필드는 `verdict_summary` 한 개만.
- **pipeline.py 무수정**: lifecycle 단계 (Step 4c4 US, 4c5 KR) 호출부 동일.
- **모바일 nav / 사이드바 / 테마 토글 회귀 없음**: 최근 commit `2972c592 feat(ui): unify momentum + lifecycle theme with main report + sidebar`의 통합 작업 보존.
- **공통 base 템플릿 추출 (`_lifecycle_base.html`)은 별도 PR**: 본 PR은 디자인 변경 + partial 2개(파이프라인, 용어 사전) 추출까지만.

## 3. 사용자 결정 (Locked)

| # | 결정 | 채택안 |
|---|---|---|
| 1 | 스코프 | **A: US + KR 둘 다** 동시 재설계 |
| 2 | mockup에 없는 기존 요소 처리 | **B: collapsible `<details>` "고급 보기"로 보존** (transitions / BROKEN / 상세 테이블) |
| 3 | 사이드바 처리 | **C: 사이드바 유지 + 모바일 nav bar 패턴** |
| 4 | 5-stage 아이콘 통일 | **색깔 원 통일**: 🔴 AVOID / 🟢 ENTER / 🟡 PROBE / 🔵 WATCH / ⚪ TRENDING |

## 4. 아키텍처

```
┌──────────────────────────────────────────────────────────────┐
│  lifecycle_signal.py / lifecycle_history.py / config.py      │
│  ✗ 무변경                                                    │
└──────────────────┬───────────────────────────────────────────┘
                   ↓
┌──────────────────────────────────────────────────────────────┐
│  lifecycle_report.py                                         │
│   • _build_verdict_summary(enter, probe, watch, trending,   │
│       avoid) -> dict  ← 신규 헬퍼                           │
│   • build_page_context() 반환 dict에 추가:                  │
│       - verdict_summary: {headline, narration, action_hint} │
│       - lifecycle_thresholds: {EXTENDED_DIST, RSI_MIN, ...} │
└──────────────────┬───────────────────────────────────────────┘
                   ↓
┌──────────────────────────────────────────────────────────────┐
│  templates/                                                  │
│   ├─ lifecycle_us.html (전면 재작성)                         │
│   ├─ lifecycle_kr.html (전면 재작성)                         │
│   ├─ _lifecycle_pipeline.html  ← 신규 partial (5 stages)    │
│   ├─ _lifecycle_glossary.html  ← 신규 partial (용어 사전)   │
│   └─ _sidebar.html (변경 없음, include 그대로)              │
└──────────────────────────────────────────────────────────────┘
```

**핵심 원칙**:
1. **백엔드 minimal 변경**: 헬퍼 함수 1개 + context 키 2개 추가
2. **DRY**: 파이프라인 + 용어 사전을 partial로 추출 → US/KR 공유
3. **점진적 disclosure**: mockup 콘텐츠 = primary, 기존 정보 = collapsible
4. **테마/사이드바/모바일 보존**: 기존 chrome 그대로

## 5. UI 컴포넌트

페이지 구조 (위에서 아래로):

### 5.1 사이드바 + 모바일 nav
- `{% include "_sidebar.html" %}` — 변경 없음. `active_nav` 설정 보존.
- 모바일 하단 nav bar (`<nav class="md:hidden fixed bottom-0">`) — 기존 패턴 복사.

### 5.2 헤더
- `🔄 Lifecycle US` (또는 `🔄 Lifecycle KR`)
- 부제목: `{as_of} 기준 · lifecycle_phase_a / {version} · 추적 {N} 종목`
- 우측: 테마 토글 (☀/🌙).

### 5.3 컨셉 박스 (📌)
정적 콘텐츠 (i18n 변수 없음, mockup 그대로):

> Momentum 스캐너가 추세 후보로 뽑은 종목들이 지금 어느 단계에 있는지 매일 추적하는 페이지입니다. 각 종목을 "사도 되는가 / 기다려야 하는가 / 피해야 하는가" 5단계로 분류합니다.
>
> ⚠️ 매수 판단 보조용이지 자동 매매가 아닙니다. 또한 보유 종목 매도는 Portfolio Risk 페이지에서 별도로 봅니다.

### 5.4 오늘의 결론 (Summary box)

`verdict_summary` 컨텍스트 사용:

```
{{ verdict_summary.headline }}
{{ verdict_summary.narration }}
{{ verdict_summary.avoid_line }}  ← AVOID > 0일 때만
💡 오늘 할 일: {{ verdict_summary.action_hint }}
```

조건별 분기 (`_build_verdict_summary` 출력):

| 조건 | headline | narration | action_hint |
|---|---|---|---|
| ENTER > 0 | `✅ 오늘 신규 진입 가능 종목 {N}개` | `{ENTER 티커들}이 확정 트리거 발화 — 풀 진입 검토 가능` | `ENTER 종목 점검 후 비중 결정` |
| PROBE > 0 & ENTER = 0 | `⚡ 분할 진입 가능 종목 {N}개` | `{PROBE 티커들}이 약한 트리거 — 절반 진입 검토` | `PROBE 종목 절반 비중 진입` |
| ENTER = 0 & PROBE = 0 | `⏸ 오늘은 신규 진입할 종목이 없습니다 (ENTER 0, PROBE 0)` | `WATCH {N}개는 트리거 발화 대기, TRENDING {N}개는 다음 눌림목까지 관망` | `WATCH 트리거 발화 대기 — 오늘은 신규 매수 없음` |
| 추적 종목 0개 (5 그룹 모두 빈 list, `total == 0`) | `⚠ 추적 종목 없음 — 시그널 부재` | `오늘 평가된 종목이 없습니다 (전 종목 skip 또는 데이터 부족)` | `pipeline 로그 확인` |

추가 line (모든 케이스에 prepend, AVOID > 0일 때만):
- `🔴 {AVOID 티커들} {N}종목은 매수 금지 — 9일선 +{dist_max}% 이격, RSI {rsi_max}+로 과확장 상태`

### 5.5 🌊 종목 흐름 파이프라인 (`_lifecycle_pipeline.html`)

```html
<div class="pipeline">
  <h2>🌊 종목 흐름 파이프라인</h2>
  <p>왼쪽 → 오른쪽으로 갈수록 "진입 임박". 가장 오른쪽 빨강은 별개로 위험 상태.</p>

  <div class="pipe-flow">
    {%- macro stage(name, label, count, items, desc, action, color_class) -%}
      <div class="pipe-stage stage-{{ color_class }}">
        <div class="stage-head">
          <span class="stage-name">{{ name }} {{ label }}</span>
          <span class="stage-count">{{ count }}</span>
        </div>
        <div class="stage-desc">{{ desc }}</div>
        <div class="stage-action">{{ action }}</div>
        <div class="stage-tickers">
          {% if items %}
            {{ items|map(attribute='ticker')|join(' · ') }}
          {% else %}
            <span class="muted">— 오늘 해당 종목 없음 —</span>
          {% endif %}
        </div>
      </div>
    {%- endmacro -%}

    {{ stage('⚪', 'TRENDING', trending|length, trending, '추세 진행 중. 아직 눌림 자리 아님.', '📍 추격 자제', 'trending') }}
    <div class="pipe-arrow">▶</div>
    {{ stage('🔵', 'WATCH', watch|length, watch, '눌림 자리 도착. 트리거 대기.', '👀 반등 신호 관찰', 'watch') }}
    <div class="pipe-arrow">▶</div>
    {{ stage('🟡', 'PROBE', probe|length, probe, '약한 트리거 발화. 50% 진입 가능.', '⚡ 절반 진입', 'probe') }}
    <div class="pipe-arrow">▶</div>
    {{ stage('🟢', 'ENTER', enter|length, enter, '확정 트리거 발화. 풀 진입 가능.', '✅ 풀 진입', 'enter') }}
    <div class="pipe-arrow invisible">|</div>
    {{ stage('🔴', 'AVOID', avoid|length, avoid, '과확장 · 구조 깨짐. 별도 위험 상태.', '❌ 매수 금지', 'avoid') }}
  </div>

  <div class="flow-narration">
    <b>이 흐름의 의미</b>: 추세에 있는 종목(<b>TRENDING</b>)은 일정 기간 오르다가 잠시 쉬는 구간(<b>WATCH</b>=PULLBACK/BASE)으로 들어옵니다. 그 안에서 반등 신호가 살짝 뜨면 <b>PROBE</b>, 거래량 증가까지 확인되면 <b>ENTER</b>로 승격됩니다. 반대로 너무 많이 오르거나 추세가 깨지면 <b>AVOID</b>로 빠집니다 (별도 경로).
  </div>
</div>
```

**모바일**: `@media (max-width: 768px) { .pipe-flow { flex-direction: column; } .pipe-arrow { transform: rotate(90deg); } }`.

### 5.6 5개 상세 섹션

순서 (있는 그룹만 표시 — `{% if ... %}` 가드):
1. 🔴 AVOID 상세
2. 🟢 ENTER 상세 (🆕 new_confirmed 강조)
3. 🟡 PROBE 상세
4. 🔵 WATCH 상세
5. ⚪ TRENDING 상세

각 섹션 구조:
```
<section class="detail">
  <h2>🔴 매수 금지 (AVOID) — {N} 종목</h2>
  <p class="sub">{설명}</p>
  <div class="action-box action-{group}">
    <div class="head">{아이콘} {section title}</div>
    <div class="desc">{action narration}</div>
  </div>
  <div class="stock-list">
    {% for row in {group} %}
      <div class="stock-chip {danger-class-if-AVOID}">
        <div class="ticker">{{ row.ticker }}{% if market=='KR' %} <span class="kr-name">{{ row.name }}</span>{% endif %}</div>
        <div class="meta">{calculated chip line 1}</div>
        <div class="meta">{calculated chip line 2}</div>
      </div>
    {% endfor %}
  </div>
</section>
```

**칩 데이터 매핑 (균일하게 모든 종목 동일 포맷)**:

| Stage | meta 1줄차 | meta 2줄차 |
|---|---|---|
| 🔴 AVOID | `9일선 {{ row.dist_ema9_pct\|signed_pct }} · 21일선 {{ row.dist_ema21_pct\|signed_pct }}` | `⚠ {{ row.risk_tags\|join(', ') }}` |
| 🟢 ENTER | `9일선 {{ row.dist_ema9_pct\|signed_pct }} · vol {{ row.raw.volume_ratio\|x_fmt }} · trig {{ row.trigger_age_days\|trig_age_label }}` | `{% if row.is_new_confirmed %}🆕 NEW CONFIRMED{% else %}{{ row.setup_state }}{% endif %}` |
| 🟡 PROBE | `9일선 {{ row.dist_ema9_pct\|signed_pct }} · vol {{ row.raw.volume_ratio\|x_fmt }}` | `EARLY · {{ row.setup_streak }}일 압축` |
| 🔵 WATCH | `9일선 {{ row.dist_ema9_pct\|signed_pct }} · 21일선 {{ row.dist_ema21_pct\|signed_pct }}` | `{{ row.setup_state }} · {{ row.setup_streak }}일 압축` |
| ⚪ TRENDING | `9일선 {{ row.dist_ema9_pct\|signed_pct }} · {{ row.setup_streak }}일 추세 유지` | (생략 — 칩 짧게) |

**필드 출처**: `row.dist_ema9_pct`, `row.dist_ema21_pct`, `row.setup_state`, `row.setup_streak`, `row.trigger_age_days`, `row.risk_tags`는 `_attach_derived()`(`lifecycle_report.py`)가 이미 attach한 derived 필드. `row.raw.volume_ratio`는 원본 snapshot 필드. `row.is_new_confirmed`는 신규로 `build_page_context()`에서 attach (`row.trigger_age_days == 0 and row.raw.trigger == "CONFIRMED_TRIGGER"`). 이 derived 필드가 누락이면 구현 시 `_attach_derived()` 보완 필요.

**필터 정의** (template-side 또는 helper):
- `signed_pct(x)`: `+12.3%` / `-5.1%` / `0.0%`
- `x_fmt(x)`: `1.5×` (소수 1자리 + ×)
- `trig_age_label(d)`: 0→`오늘`, 1→`어제`, n→`{n}일전`, None→`—`

**KR 한글명 표시**: `{{ row.ticker }}` 옆 작은 회색 텍스트로 `{{ row.name }}` (예: `005930 삼성전자`).

### 5.7 📖 용어 사전 (`_lifecycle_glossary.html`)

5개 `<details>` 항목, 첫 1번만 기본 펼침(`open`):

1. **왜 5가지 그룹으로 나누나? (결정 매트릭스)** [open] — Setup × Trigger 표 (5 × 3)
2. **Setup (구조 진단) — 5단계** — 5 setups + 우선순위
3. **Trigger (진입 신호) — 3단계** — 3 triggers + 조건
4. **지표 약어 (테이블 컬럼)** — EMA9/21/65, dist_ema9, vol_ratio, ATR%, days_in_pb, setup_streak, trig_age
5. **위험 태그 (risk_tags)** — OVERHEAT, PARABOLIC, FAILED_BREAKOUT

**임계값 주입**: mockup의 하드코드(12%, 72, 80, 1.2배 등) → Jinja `{{ lifecycle_thresholds.* }}` 변수로 치환. `lifecycle_thresholds` 컨텍스트 키는 `lifecycle_config.py` 상수에서 build:

```python
lifecycle_thresholds = {
    "PULLBACK_MAX_DIST_FROM_EMA9": PULLBACK_MAX_DIST_FROM_EMA9,
    "EXTENDED_DIST_FROM_EMA9": EXTENDED_DIST_FROM_EMA9,
    "EXTENDED_RSI_MIN": EXTENDED_RSI_MIN,
    "RISK_OVERHEAT_RSI": RISK_OVERHEAT_RSI,
    "RISK_PARABOLIC_RET_1D": RISK_PARABOLIC_RET_1D,
    "RISK_PARABOLIC_VOL_RATIO": RISK_PARABOLIC_VOL_RATIO,
    "TRIGGER_CONFIRM_VOL_RATIO_MIN": TRIGGER_CONFIRM_VOL_RATIO_MIN,
    "BASE_FORMING_DAYS_MIN": BASE_FORMING_DAYS_MIN,
    "BASE_FORMING_DAYS_MAX": BASE_FORMING_DAYS_MAX,
}
```

### 5.8 ⚙ 고급 보기 (collapsible, 신규)

단일 `<details>` (기본 접힘):

```
▶ ⚙ 고급 보기 (디버깅·audit용)
  • 최근 상태 전환 — 50개 transitions 테이블 (ticker | from → to | as_of)
  • BROKEN 종목 — broken_table 칩 그리드 (별도 분류, AVOID와 구분)
  • 전체 종목 상세 데이터 테이블 — ticker | decision | setup | trigger | dist_ema9 | dist_ema21 | RSI | vol_ratio | ATR% | setup_streak | trig_age | risk_tags
```

기존 템플릿의 정보 보존. 평소엔 접혀서 mockup의 깔끔함 보장.

### 5.9 풋터
- `Lifecycle Phase A · {version} · 추적 {N} 종목`
- `※ 시장 국면 분류기(RISK_ON / TRENDING / CHOPPY / RISK_OFF)는 Phase B에서 추가 예정`
- `※ 본 문서는 정보 제공용이며 투자 권유가 아닙니다.`

## 6. 백엔드 변경 (lifecycle_report.py)

### 6.1 신규 헬퍼: `_build_verdict_summary()`

```python
def _build_verdict_summary(enter: list, probe: list, watch: list,
                            trending: list, avoid: list) -> dict:
    """Build dynamic narration for the 'Today's Verdict' summary box.

    Returns:
        {
          "headline": str,        # 큰 제목 (조건별 분기)
          "narration": str,       # 1-2 문장 설명
          "avoid_line": str | None,  # AVOID > 0일 때만
          "action_hint": str,     # 💡 오늘 할 일
        }
    """
    enter_n, probe_n, watch_n = len(enter), len(probe), len(watch)
    trending_n, avoid_n = len(trending), len(avoid)
    total = enter_n + probe_n + watch_n + trending_n + avoid_n

    # Headline + narration 분기
    if total == 0:
        headline = "⚠ 추적 종목 없음 — 시그널 부재"
        narration = "오늘 평가된 종목이 없습니다 (전 종목 skip 또는 데이터 부족)"
        action_hint = "pipeline 로그 확인"
    elif enter_n > 0:
        tickers = ", ".join(r["ticker"] for r in enter[:5])
        if enter_n > 5:
            tickers += f" 외 {enter_n - 5}개"
        headline = f"✅ 오늘 신규 진입 가능 종목 {enter_n}개"
        narration = f"{tickers}이 확정 트리거 발화 — 풀 진입 검토 가능"
        action_hint = "ENTER 종목 점검 후 비중 결정"
    elif probe_n > 0:
        tickers = ", ".join(r["ticker"] for r in probe[:5])
        if probe_n > 5:
            tickers += f" 외 {probe_n - 5}개"
        headline = f"⚡ 분할 진입 가능 종목 {probe_n}개"
        narration = f"{tickers}이 약한 트리거 — 절반 진입 검토"
        action_hint = "PROBE 종목 절반 비중 진입"
    else:
        headline = "⏸ 오늘은 신규 진입할 종목이 없습니다 (ENTER 0, PROBE 0)"
        narration = (
            f"WATCH {watch_n}개는 트리거 발화 대기, "
            f"TRENDING {trending_n}개는 다음 눌림목까지 관망"
        )
        action_hint = "WATCH 트리거 발화 대기 — 오늘은 신규 매수 없음"

    # AVOID line (모든 케이스에 추가)
    avoid_line = None
    if avoid_n > 0:
        tickers = " · ".join(r["ticker"] for r in avoid[:5])
        if avoid_n > 5:
            tickers += f" 외 {avoid_n - 5}개"
        # max dist + max rsi 추출 (실측치 동적 삽입)
        # row dict는 _attach_derived 통과 후 — dist_ema9_pct는 derived 필드, rsi14는 raw 안에 있음
        max_dist = max((r.get("dist_ema9_pct") or 0) for r in avoid)
        max_rsi = max((r.get("raw", {}).get("rsi14") or 0) for r in avoid)
        avoid_line = (
            f"🔴 {tickers} {avoid_n}종목은 매수 금지 — "
            f"9일선 +{max_dist:.1f}% 이격, RSI {max_rsi:.0f}+로 과확장 상태"
        )

    return {
        "headline": headline,
        "narration": narration,
        "avoid_line": avoid_line,
        "action_hint": action_hint,
    }
```

### 6.2 `build_page_context()` 변경

기존 return dict에 2개 키 추가:

```python
from lifecycle_config import (
    PULLBACK_MAX_DIST_FROM_EMA9, EXTENDED_DIST_FROM_EMA9, EXTENDED_RSI_MIN,
    RISK_OVERHEAT_RSI, RISK_PARABOLIC_RET_1D, RISK_PARABOLIC_VOL_RATIO,
    TRIGGER_CONFIRM_VOL_RATIO_MIN, BASE_FORMING_DAYS_MIN, BASE_FORMING_DAYS_MAX,
)

# ... 기존 enter/probe/watch/trending/avoid/broken_table 분류 ...

return {
    "market":       result.get("market", "US"),
    "as_of":        result.get("as_of"),
    "version":      LIFECYCLE_VERSION,
    "new_confirmed": new_confirmed,
    "enter":        enter,
    "probe":        probe,
    "watch":        watch,
    "trending":     trending,
    "avoid":        avoid,
    "broken_table": broken_table,
    "transitions":  (result.get("transitions") or [])[-50:],
    "DECISION_LABELS":   DECISION_LABELS,
    "DECISION_TOOLTIPS": DECISION_TOOLTIPS,
    "verdict_summary":   _build_verdict_summary(enter, probe, watch, trending, avoid),
    "lifecycle_thresholds": {
        "PULLBACK_MAX_DIST_FROM_EMA9": PULLBACK_MAX_DIST_FROM_EMA9,
        "EXTENDED_DIST_FROM_EMA9":     EXTENDED_DIST_FROM_EMA9,
        "EXTENDED_RSI_MIN":            EXTENDED_RSI_MIN,
        "RISK_OVERHEAT_RSI":           RISK_OVERHEAT_RSI,
        "RISK_PARABOLIC_RET_1D":       RISK_PARABOLIC_RET_1D,
        "RISK_PARABOLIC_VOL_RATIO":    RISK_PARABOLIC_VOL_RATIO,
        "TRIGGER_CONFIRM_VOL_RATIO_MIN": TRIGGER_CONFIRM_VOL_RATIO_MIN,
        "BASE_FORMING_DAYS_MIN":       BASE_FORMING_DAYS_MIN,
        "BASE_FORMING_DAYS_MAX":       BASE_FORMING_DAYS_MAX,
    },
}
```

## 7. 테스트 전략

### 7.1 단위 테스트 (`tests/test_lifecycle_verdict.py`)

5개 테스트로 4 분기 + AVOID 동적 삽입 커버:

1. `test_verdict_enter_present` — ENTER ≥ 1 → headline `✅ 오늘 신규 진입 가능 종목 X개`
2. `test_verdict_probe_only` — ENTER=0, PROBE≥1 → `⚡ 분할 진입 가능 종목 N개`
3. `test_verdict_watch_trending_only` — ENTER=0, PROBE=0 → `⏸ 오늘은 신규 진입할 종목이 없습니다`
4. `test_verdict_all_empty` — 모든 그룹 비어있음 → `⚠ 추적 종목 없음 — 시그널 부재`
5. `test_verdict_avoid_dynamic_line` — AVOID 종목들의 dist_ema9 / rsi 실측치가 narration에 정확히 삽입됨

### 7.2 통합 테스트

- `python pipeline.py`로 lifecycle 실행 후 HTML 생성 확인
- 4 분기 모두 시각 검증 (수동):
  - 평일 ENTER 있는 날 vs 없는 날
  - 평일 PROBE 있는 날
  - 주말/장 마감 후 (변동 없는 날)
- 모바일 viewport (DevTools 768px 이하)에서 파이프라인 세로 stack 확인

## 8. 파일 변경 요약

**Create:**
- `templates/_lifecycle_pipeline.html` — 5-stage 파이프라인 partial
- `templates/_lifecycle_glossary.html` — 용어 사전 partial (5 collapsible)
- `tests/test_lifecycle_verdict.py` — verdict_summary 단위 테스트
- `docs/superpowers/specs/2026-05-11-lifecycle-redesign-design.md` (이 문서)
- `docs/superpowers/plans/2026-05-11-lifecycle-redesign.md` (writing-plans 단계에서 생성)

**Modify:**
- `lifecycle_report.py` — `_build_verdict_summary()` 헬퍼 + `build_page_context()` 반환 dict에 2 키 추가
- `templates/lifecycle_us.html` — 전면 재작성 (mockup 구조 + 사이드바 + 모바일 nav 보존)
- `templates/lifecycle_kr.html` — 동일 재작성, KR 한글명 표시
- `CLAUDE.md` — "진행 중인 계획" 섹션에 신규 plan 등록

**Auto-generated**:
- `reports/lifecycle_us_*.html` (다음 pipeline 실행)
- `reports/lifecycle_kr_*.html`

## 9. 위험 분석

| 위험 | 영향 | 완화 |
|---|---|---|
| 사이드바 nav 깨짐 | 페이지 간 이동 끊김 | `_sidebar.html` include + `active_nav` 키 보존 |
| 모바일 nav 누락 | 모바일 사용성 ↓ | 기존 `<nav class="md:hidden">` 패턴 복사 |
| 테마 토글(dark/light) 회귀 | 라이트 모드 깨짐 | mockup의 `--bg`/`--card` → 기존 `--c-surface-*` CSS 변수 매핑. 양 모드 verify |
| 파이프라인 모바일 가로 스크롤 | 작은 화면 가독성 | `@media (max-width: 768px)` 세로 stack + 화살표 90° 회전 |
| `verdict_summary` narration이 misleading | UX 신뢰도 ↓ | 4가지 분기 명시적 정의 + 단위 테스트로 모든 케이스 커버 |
| 임계값 하드코드 | config 변경 시 문서 불일치 | 용어 사전에 Jinja `{{ lifecycle_thresholds.* }}` 변수로 주입 |
| BROKEN 종목 분류 변경 | 매수 후보 명단 변동 | 변경 없음 — broken_table 그대로, "고급 보기" 섹션에 별도 보존 |
| transitions 50개 누락 | audit 어려움 | "고급 보기" 안에 테이블로 보존 |
| 자동매매 / 시그널 로직 영향 | 부작용 위험 | **0** — `lifecycle_signal.py` 등 모든 시그널 path 무수정 |
| 작업 분량 (템플릿 2개 ~600줄씩) | 일정 ↑ | partial 추출(`_pipeline`, `_glossary`)로 중복 줄임. 신규 단위 테스트는 verdict_summary 1개만 |

## 10. 시그널 / 자동매매 영향

**없음.** 본 변경은 `templates/` + `lifecycle_report.py:build_page_context()` 한정. setup/trigger/decision 판정, history 저장 schema, pipeline orchestration 모두 무변경.

## 11. 후속 작업 (out of scope)

- **공통 base 템플릿 추출** (`_lifecycle_base.html`로 US/KR 공유 구조 통합) — 별도 PR
- **시장 국면 분류기** (RISK_ON / TRENDING / CHOPPY / RISK_OFF) — Lifecycle Phase B에서 별도 작업
- **칩 hover 시 tooltip** (RSI/ATR% 등 상세 수치) — UX 개선 별도 PR 후보
