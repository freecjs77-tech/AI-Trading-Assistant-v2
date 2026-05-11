# Lifecycle Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `templates/lifecycle_us.html`와 `lifecycle_kr.html`을 사용자 mockup 디자인(5-stage 파이프라인 + 컨셉 박스 + 동적 verdict + 칩 그리드 + 용어 사전 + 고급 보기 collapsible)으로 전면 재작성하고, `lifecycle_report.py`에 verdict 헬퍼 1개 + signed-distance derived 필드 + 임계값 컨텍스트 키를 추가한다.

**Architecture:** 시그널/히스토리/config 무수정. `lifecycle_report.py`의 derived 필드 attach 단계와 context 빌더만 확장. 파이프라인과 용어 사전을 partial(`_lifecycle_pipeline.html`, `_lifecycle_glossary.html`)로 추출해 US/KR 공유. 사이드바·모바일 nav·테마 토글은 기존 패턴 그대로 보존.

**Tech Stack:** Python 3.10+, Jinja2, Tailwind CSS (CDN), pytest, 기존 `--c-surface-*` CSS 변수 시스템.

**참고 디자인 문서:** `docs/superpowers/specs/2026-05-11-lifecycle-redesign-design.md`

---

## File Structure

**Create:**
- `templates/_lifecycle_pipeline.html` — 5-stage 파이프라인 partial (TRENDING/WATCH/PROBE/ENTER/AVOID 색깔 원 + 카운트 + 티커 리스트 + 모바일 stack)
- `templates/_lifecycle_glossary.html` — 5개 collapsible 용어 사전 partial (결정 매트릭스, Setup, Trigger, 지표 약어, 위험 태그). `lifecycle_thresholds` 변수 주입
- `tests/test_lifecycle_verdict.py` — `_build_verdict_summary()` 단위 테스트 (4 분기 + AVOID 동적 line)

**Modify:**
- `lifecycle_report.py` — `_attach_derived()` 확장 (signed dist 필드 2개 추가), `_build_verdict_summary()` 신규, `build_page_context()` 반환 dict에 `verdict_summary` + `lifecycle_thresholds` 추가, Jinja env에 커스텀 필터 3개 등록 (`signed_pct`, `x_fmt`, `trig_age_label`)
- `templates/lifecycle_us.html` — 전면 재작성 (사이드바 / 모바일 nav / 테마 토글 보존, mockup 콘텐츠 구조 적용)
- `templates/lifecycle_kr.html` — 동일 패턴 재작성 + KR 한글명 표시 차이만
- `CLAUDE.md` — "진행 중인 계획" 섹션에 신규 plan 등록

**Auto-generated (실행 결과):**
- `reports/lifecycle_us_*.html` (다음 pipeline 실행 시)
- `reports/lifecycle_kr_*.html` (동일)

---

## Design Decisions (locked from spec)

1. **스코프**: US + KR 둘 다 동시 재설계
2. **mockup에 없는 기존 정보**: collapsible `<details>` "⚙ 고급 보기"로 보존 (transitions / BROKEN / 상세 테이블)
3. **사이드바**: `_sidebar.html` include 유지 + 모바일 하단 nav bar 패턴
4. **5-stage 아이콘**: 색깔 원 통일 (🔴 AVOID / 🟢 ENTER / 🟡 PROBE / 🔵 WATCH / ⚪ TRENDING)
5. **칩 데이터**: 균일 포맷 (모든 종목 동일 1줄차/2줄차 패턴)
6. **임계값**: `lifecycle_config.py` 상수 → `lifecycle_thresholds` context dict → Jinja 변수로 용어 사전에 주입
7. **시그널 path**: 무수정 (`lifecycle_signal.py`, `lifecycle_history.py`, `lifecycle_config.py`, `pipeline.py` 모두 손대지 않음)
8. **신규 derived 필드**: `dist_ema9_signed_pct`, `dist_ema21_signed_pct` (raw 값은 abs라 칩의 `+X%` 표시 위해 부호 보전한 별도 필드 attach)

---

## Task 1: `_build_verdict_summary()` 단위 테스트 작성 (TDD)

**Files:**
- Create: `tests/test_lifecycle_verdict.py`

- [ ] **Step 1: 테스트 파일 작성**

```python
"""Tests for lifecycle_report._build_verdict_summary.

Covers 4 branches + AVOID dynamic line insertion:
- ENTER ≥ 1 → "✅ 오늘 신규 진입 가능 종목 N개"
- PROBE ≥ 1, ENTER = 0 → "⚡ 분할 진입 가능 종목 N개"
- ENTER = 0 & PROBE = 0 (with WATCH/TRENDING) → "⏸ 오늘은 신규 진입할 종목이 없습니다"
- All groups empty (total = 0) → "⚠ 추적 종목 없음 — 시그널 부재"
- AVOID > 0 → avoid_line populated with max dist + max RSI
"""
from __future__ import annotations

import pytest

from lifecycle_report import _build_verdict_summary


def _row(ticker, dist_ema9=None, rsi=None):
    """Minimal row dict for verdict tests. dist_ema9_pct attached at top-level
    (derived), rsi14 nested under raw (matches _attach_derived structure)."""
    return {
        "ticker": ticker,
        "dist_ema9_pct": dist_ema9,
        "raw": {"rsi14": rsi},
    }


def test_verdict_enter_present():
    """ENTER ≥ 1 → '✅ 신규 진입 가능 종목 N개' headline."""
    enter = [_row("AAPL"), _row("NVDA"), _row("MSFT")]
    result = _build_verdict_summary(enter, probe=[], watch=[], trending=[], avoid=[])

    assert "✅" in result["headline"]
    assert "3" in result["headline"]
    assert "신규 진입" in result["headline"]
    assert "AAPL" in result["narration"]
    assert "NVDA" in result["narration"]
    assert "확정 트리거" in result["narration"]
    assert result["avoid_line"] is None
    assert "ENTER 종목" in result["action_hint"]


def test_verdict_probe_only():
    """ENTER=0, PROBE≥1 → '⚡ 분할 진입 가능 종목 N개'."""
    probe = [_row("TSLA"), _row("AMZN")]
    result = _build_verdict_summary(enter=[], probe=probe, watch=[], trending=[], avoid=[])

    assert "⚡" in result["headline"]
    assert "2" in result["headline"]
    assert "분할 진입" in result["headline"]
    assert "TSLA" in result["narration"]
    assert "약한 트리거" in result["narration"]
    assert "PROBE 종목" in result["action_hint"]


def test_verdict_watch_trending_only():
    """ENTER=0 & PROBE=0 with WATCH/TRENDING → '⏸ 신규 진입할 종목 없음'."""
    watch = [_row("AFRM"), _row("ALGM"), _row("AVGO")]
    trending = [_row("NVDA"), _row("AAPL")]
    result = _build_verdict_summary(enter=[], probe=[], watch=watch,
                                     trending=trending, avoid=[])

    assert "⏸" in result["headline"]
    assert "신규 진입할 종목이 없습니다" in result["headline"]
    assert "WATCH 3개" in result["narration"]
    assert "TRENDING 2개" in result["narration"]
    assert "WATCH 트리거 발화 대기" in result["action_hint"]


def test_verdict_all_empty():
    """5 그룹 모두 빈 list (total=0) → '⚠ 추적 종목 없음'."""
    result = _build_verdict_summary(enter=[], probe=[], watch=[],
                                     trending=[], avoid=[])

    assert "⚠" in result["headline"]
    assert "추적 종목 없음" in result["headline"]
    assert "pipeline 로그" in result["action_hint"]


def test_verdict_avoid_dynamic_line():
    """AVOID > 0 → avoid_line에 max dist + max RSI 실측치 정확히 삽입."""
    avoid = [
        _row("AMD", dist_ema9=19.1, rsi=81.2),
        _row("INTC", dist_ema9=20.3, rsi=84.5),  # max RSI
        _row("MU", dist_ema9=21.2, rsi=80.0),    # max dist
    ]
    result = _build_verdict_summary(enter=[], probe=[], watch=[],
                                     trending=[], avoid=avoid)

    assert result["avoid_line"] is not None
    assert "🔴" in result["avoid_line"]
    assert "AMD" in result["avoid_line"]
    assert "INTC" in result["avoid_line"]
    assert "MU" in result["avoid_line"]
    assert "3종목" in result["avoid_line"]
    # max dist (MU's 21.2) and max RSI (INTC's 84.5 → 85 when rounded)
    assert "21.2" in result["avoid_line"]
    assert "84" in result["avoid_line"] or "85" in result["avoid_line"]
```

- [ ] **Step 2: 테스트 실행해서 ImportError로 실패 확인**

Run: `pytest tests/test_lifecycle_verdict.py -v`
Expected: 5 FAIL (collection error — `_build_verdict_summary` 미구현)

- [ ] **Step 3: Commit**

```bash
git add tests/test_lifecycle_verdict.py
git commit -m "test(lifecycle): failing tests for _build_verdict_summary

Covers 4 verdict branches (ENTER/PROBE/empty-with-watch/total-empty)
plus AVOID dynamic line with max dist + max RSI insertion. All 5 tests
fail at collection until Task 2 implements the helper."
```

---

## Task 2: `_build_verdict_summary()` 헬퍼 구현

**Files:**
- Modify: `lifecycle_report.py` (Insert before `build_page_context()` at line 55)

- [ ] **Step 1: 헬퍼 함수 추가**

`lifecycle_report.py:54` (현재 `_attach_derived()` 종료) 다음, 현재 line 55 `def build_page_context(...)` 앞에 추가:

```python
def _build_verdict_summary(enter: list, probe: list, watch: list,
                            trending: list, avoid: list) -> dict:
    """Build dynamic narration for the 'Today's Verdict' summary box.

    Branches on which groups are non-empty (ENTER > PROBE > empty > total=0).
    AVOID line is appended whenever AVOID > 0, with max dist_ema9 and max
    rsi14 from the AVOID group inserted as live values.

    Returns:
        {
          "headline":    str,             # 큰 제목
          "narration":   str,             # 1-2 문장 설명
          "avoid_line":  str | None,      # AVOID > 0일 때만, else None
          "action_hint": str,             # 💡 오늘 할 일
        }
    """
    enter_n, probe_n = len(enter), len(probe)
    watch_n, trending_n, avoid_n = len(watch), len(trending), len(avoid)
    total = enter_n + probe_n + watch_n + trending_n + avoid_n

    def _ticker_list(rows: list, limit: int = 5) -> str:
        names = [r["ticker"] for r in rows[:limit]]
        s = ", ".join(names)
        if len(rows) > limit:
            s += f" 외 {len(rows) - limit}개"
        return s

    if total == 0:
        headline = "⚠ 추적 종목 없음 — 시그널 부재"
        narration = "오늘 평가된 종목이 없습니다 (전 종목 skip 또는 데이터 부족)"
        action_hint = "pipeline 로그 확인"
    elif enter_n > 0:
        headline = f"✅ 오늘 신규 진입 가능 종목 {enter_n}개"
        narration = f"{_ticker_list(enter)}이 확정 트리거 발화 — 풀 진입 검토 가능"
        action_hint = "ENTER 종목 점검 후 비중 결정"
    elif probe_n > 0:
        headline = f"⚡ 분할 진입 가능 종목 {probe_n}개"
        narration = f"{_ticker_list(probe)}이 약한 트리거 — 절반 진입 검토"
        action_hint = "PROBE 종목 절반 비중 진입"
    else:
        headline = "⏸ 오늘은 신규 진입할 종목이 없습니다 (ENTER 0, PROBE 0)"
        narration = (
            f"WATCH {watch_n}개는 트리거 발화 대기, "
            f"TRENDING {trending_n}개는 다음 눌림목까지 관망"
        )
        action_hint = "WATCH 트리거 발화 대기 — 오늘은 신규 매수 없음"

    avoid_line = None
    if avoid_n > 0:
        # _ticker_list uses ', ' separator; mockup uses ' · ' for AVOID line
        names = [r["ticker"] for r in avoid[:5]]
        tickers = " · ".join(names)
        if avoid_n > 5:
            tickers += f" 외 {avoid_n - 5}개"
        max_dist = max((r.get("dist_ema9_pct") or 0) for r in avoid)
        max_rsi = max((r.get("raw", {}).get("rsi14") or 0) for r in avoid)
        avoid_line = (
            f"🔴 {tickers} {avoid_n}종목은 매수 금지 — "
            f"9일선 +{max_dist:.1f}% 이격, RSI {max_rsi:.0f}+로 과확장 상태"
        )

    return {
        "headline":    headline,
        "narration":   narration,
        "avoid_line":  avoid_line,
        "action_hint": action_hint,
    }
```

- [ ] **Step 2: 테스트 통과 확인**

Run: `pytest tests/test_lifecycle_verdict.py -v`
Expected: 5 PASS

- [ ] **Step 3: 기존 테스트 회귀 확인**

Run: `pytest tests/ -k lifecycle 2>&1 | tail -5`
Expected: lifecycle 관련 모든 테스트 PASS (회귀 0)

- [ ] **Step 4: Commit**

```bash
git add lifecycle_report.py
git commit -m "feat(lifecycle): _build_verdict_summary helper for dynamic Today's Verdict

Returns {headline, narration, avoid_line, action_hint} with 4-way branching
on which decision groups are non-empty. AVOID line dynamically inserts max
dist_ema9 and max rsi14 from the AVOID group. 5/5 unit tests pass."
```

---

## Task 3: `_attach_derived()` — signed distance 필드 추가

**Files:**
- Modify: `lifecycle_report.py:34-52` (`_attach_derived()` 본문)

raw snapshot의 `dist_ema9_pct`, `dist_ema21_pct`는 `abs()` 값이라 부호가 없음 (lifecycle_signal.py:306). 칩에 `+X%` / `-Y%` 표시하려면 부호 보전한 derived 필드 필요.

- [ ] **Step 1: 함수 수정**

`lifecycle_report.py:34-52` (`_attach_derived` 본문)을 다음으로 교체:

```python
def _attach_derived(snap: dict, ticker: str,
                     lifecycle_state: Optional[dict]) -> dict:
    out = dict(snap)
    if lifecycle_state and ticker in (lifecycle_state.get("tickers") or {}):
        derived = derive_fields(lifecycle_state["tickers"][ticker])
    else:
        # No lifecycle history for this ticker — infer from today's snapshot.
        # If today's snap already has a trigger (EARLY or CONFIRMED), age = 0
        # (first seen = today). None only when truly no trigger has ever fired.
        trigger = snap.get("trigger", "WAIT")
        if trigger in ("EARLY_TRIGGER", "CONFIRMED_TRIGGER"):
            trigger_age = 0
        else:
            trigger_age = None
        derived = {"setup_streak": 1, "days_in_pullback": 0, "trigger_age_days": trigger_age}
    out["setup_streak"]     = derived["setup_streak"]
    out["days_in_pullback"] = derived["days_in_pullback"]
    out["trigger_age_days"] = derived["trigger_age_days"]

    # Signed distance fields for chip display (raw values are abs).
    # close / ema9 / ema21 are in raw nested dict per lifecycle_signal._make_snapshot.
    raw = snap.get("raw") or {}
    close = raw.get("close")
    e9 = raw.get("ema9")
    e21 = raw.get("ema21")
    out["dist_ema9_signed_pct"] = (
        round((close / e9 - 1) * 100, 2) if (close and e9 and e9 > 0) else None
    )
    out["dist_ema21_signed_pct"] = (
        round((close / e21 - 1) * 100, 2) if (close and e21 and e21 > 0) else None
    )

    # Also surface raw abs value at top-level for verdict_summary max() (avoids
    # needing to dig into raw.* from the helper, keeps _build_verdict_summary lean).
    out["dist_ema9_pct"] = raw.get("dist_ema9_pct")

    return out
```

- [ ] **Step 2: 기존 lifecycle 테스트 회귀 확인**

Run: `pytest tests/ -k lifecycle 2>&1 | tail -5`
Expected: 모든 lifecycle 테스트 PASS

- [ ] **Step 3: signed 필드 값 sanity check**

```bash
python -c "
from lifecycle_report import _attach_derived
snap = {'raw': {'close': 100.0, 'ema9': 95.0, 'ema21': 90.0, 'dist_ema9_pct': 5.26, 'dist_ema21_pct': 11.11}, 'trigger': 'WAIT'}
row = _attach_derived(snap, 'TEST', None)
print(f'signed_ema9={row[\"dist_ema9_signed_pct\"]}, signed_ema21={row[\"dist_ema21_signed_pct\"]}')
# Expected: signed_ema9=+5.26, signed_ema21=+11.11
# Test negative: price below ema9
snap2 = {'raw': {'close': 90.0, 'ema9': 95.0, 'ema21': 92.0, 'dist_ema9_pct': 5.26, 'dist_ema21_pct': 2.17}, 'trigger': 'WAIT'}
row2 = _attach_derived(snap2, 'TEST2', None)
print(f'below: signed_ema9={row2[\"dist_ema9_signed_pct\"]}, signed_ema21={row2[\"dist_ema21_signed_pct\"]}')
# Expected: below: signed_ema9=-5.26 (negative — price below ema9)
"
```
Expected output:
```
signed_ema9=5.26, signed_ema21=11.11
below: signed_ema9=-5.26, signed_ema21=-2.17
```

- [ ] **Step 4: Commit**

```bash
git add lifecycle_report.py
git commit -m "feat(lifecycle): attach signed distance fields for chip display

raw.dist_ema9_pct / dist_ema21_pct are abs values from signal layer.
Add dist_ema9_signed_pct and dist_ema21_signed_pct derived fields so
chip rendering can show +X% / -Y% with sign. Surface raw abs value
at row top-level too (dist_ema9_pct) for verdict_summary max()."
```

---

## Task 4: `build_page_context()` — verdict + thresholds + Jinja filters

**Files:**
- Modify: `lifecycle_report.py` (imports, `build_page_context()` return dict, `_render()` env setup)

- [ ] **Step 1: 임계값 상수 import 확장**

`lifecycle_report.py:13` 의 기존 import:
```python
from lifecycle_config import LIFECYCLE_VERSION
```

다음으로 교체:
```python
from lifecycle_config import (
    LIFECYCLE_VERSION,
    PULLBACK_MAX_DIST_FROM_EMA9, EXTENDED_DIST_FROM_EMA9, EXTENDED_RSI_MIN,
    RISK_OVERHEAT_RSI, RISK_PARABOLIC_RET_1D, RISK_PARABOLIC_VOL_RATIO,
    TRIGGER_CONFIRM_VOL_RATIO_MIN, TRIGGER_CONFIRM_CLOSE_HIGH_RATIO,
    BASE_FORMING_DAYS_MIN, BASE_FORMING_DAYS_MAX,
)
```

- [ ] **Step 2: `build_page_context()` 반환 dict에 2 키 추가**

`lifecycle_report.py` 의 `build_page_context()` 끝 (현재 `return {...}` 블록)에서, 기존 마지막 key `"DECISION_TOOLTIPS": DECISION_TOOLTIPS,` 뒤에 추가:

```python
        "DECISION_LABELS":   DECISION_LABELS,
        "DECISION_TOOLTIPS": DECISION_TOOLTIPS,
        "verdict_summary":   _build_verdict_summary(enter, probe, watch, trending, avoid),
        "lifecycle_thresholds": {
            "PULLBACK_MAX_DIST_FROM_EMA9":      PULLBACK_MAX_DIST_FROM_EMA9,
            "EXTENDED_DIST_FROM_EMA9":          EXTENDED_DIST_FROM_EMA9,
            "EXTENDED_RSI_MIN":                 EXTENDED_RSI_MIN,
            "RISK_OVERHEAT_RSI":                RISK_OVERHEAT_RSI,
            "RISK_PARABOLIC_RET_1D":            RISK_PARABOLIC_RET_1D,
            "RISK_PARABOLIC_VOL_RATIO":         RISK_PARABOLIC_VOL_RATIO,
            "TRIGGER_CONFIRM_VOL_RATIO_MIN":    TRIGGER_CONFIRM_VOL_RATIO_MIN,
            "TRIGGER_CONFIRM_CLOSE_HIGH_RATIO": TRIGGER_CONFIRM_CLOSE_HIGH_RATIO,
            "BASE_FORMING_DAYS_MIN":            BASE_FORMING_DAYS_MIN,
            "BASE_FORMING_DAYS_MAX":            BASE_FORMING_DAYS_MAX,
        },
    }
```

(`}` 위치 주의 — 기존 닫기 brace를 그대로 유지하고 위 2 키만 그 사이에 추가)

- [ ] **Step 3: Jinja 커스텀 필터 3개 등록**

`lifecycle_report.py` 의 `_render()` 함수에서 env 생성 직후 (현재 line ~111 `env = Environment(...)` 다음):

기존:
```python
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)
    tmpl = env.get_template(f"lifecycle_{market.lower()}.html")
```

다음으로 교체:
```python
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)

    # Custom filters for chip rendering
    def _signed_pct(x):
        """Format signed percentage: +5.3% / -2.1% / 0.0% / — (None)."""
        if x is None:
            return "—"
        return f"{x:+.1f}%"

    def _x_fmt(x):
        """Format multiplier: 1.5× / — (None)."""
        if x is None:
            return "—"
        return f"{x:.1f}×"

    def _trig_age_label(d):
        """Format trigger age: 오늘 / 어제 / N일전 / —."""
        if d is None:
            return "—"
        if d == 0:
            return "오늘"
        if d == 1:
            return "어제"
        return f"{d}일전"

    env.filters["signed_pct"] = _signed_pct
    env.filters["x_fmt"] = _x_fmt
    env.filters["trig_age_label"] = _trig_age_label

    tmpl = env.get_template(f"lifecycle_{market.lower()}.html")
```

- [ ] **Step 4: import 검증**

Run:
```bash
python -c "
from lifecycle_report import build_page_context
result = {'market': 'US', 'as_of': '2026-05-08', 'snapshots': {}}
ctx = build_page_context(result, lifecycle_state={'tickers': {}})
assert 'verdict_summary' in ctx
assert 'lifecycle_thresholds' in ctx
assert ctx['lifecycle_thresholds']['EXTENDED_RSI_MIN'] == 72
print('OK verdict_summary + lifecycle_thresholds present')
"
```
Expected: `OK verdict_summary + lifecycle_thresholds present`

- [ ] **Step 5: 회귀 테스트**

Run: `pytest tests/ -k lifecycle 2>&1 | tail -5`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add lifecycle_report.py
git commit -m "feat(lifecycle): expose verdict_summary + lifecycle_thresholds + Jinja filters

build_page_context() now returns 2 additional keys:
- verdict_summary: dynamic 'Today's Verdict' narration
- lifecycle_thresholds: config constants for in-template threshold display

_render() registers 3 custom Jinja filters: signed_pct, x_fmt, trig_age_label
for chip data formatting."
```

---

## Task 5: `_lifecycle_pipeline.html` partial 작성

**Files:**
- Create: `templates/_lifecycle_pipeline.html`

5-stage 가로 flow 파이프라인. US/KR 공통 (decision 라벨 자체는 보편적이라 한글 그대로). 호출하는 부모 템플릿이 `enter`, `probe`, `watch`, `trending`, `avoid` 변수를 컨텍스트에 제공.

- [ ] **Step 1: partial 파일 작성**

```html
{# templates/_lifecycle_pipeline.html
   5-stage 종목 흐름 파이프라인. parent context 요구:
     enter, probe, watch, trending, avoid (list of row dicts)
#}
{%- macro _stage(icon, label, ko_label, rows, desc, action_label, color_class) -%}
<div class="pipe-stage stage-{{ color_class }}">
  <div class="stage-head">
    <span class="stage-name">{{ icon }} {{ label }}</span>
    <span class="stage-count">{{ rows|length }}</span>
  </div>
  <div class="stage-desc">{{ desc }}</div>
  <div class="stage-action">{{ action_label }}</div>
  <div class="stage-tickers">
    {%- if rows -%}
      {{ rows|map(attribute='ticker')|join(' · ') }}
    {%- else -%}
      <span class="muted">— 오늘 해당 종목 없음 —</span>
    {%- endif -%}
  </div>
</div>
{%- endmacro -%}

<div class="pipeline">
  <h2>🌊 종목 흐름 파이프라인</h2>
  <p class="sub">왼쪽 → 오른쪽으로 갈수록 "진입 임박". 가장 오른쪽 빨강은 별개로 "위험 상태".</p>

  <div class="pipe-flow">
    {{ _stage('⚪', 'TRENDING', '눌림 대기',  trending, '추세 진행 중. 아직 눌림 자리 아님.',     '📍 추격 자제',    'trending') }}
    <div class="pipe-arrow">▶</div>
    {{ _stage('🔵', 'WATCH',    '진입 대기',  watch,    '눌림 자리 도착. 트리거(반등 신호) 대기.', '👀 반등 신호 관찰', 'watch')    }}
    <div class="pipe-arrow">▶</div>
    {{ _stage('🟡', 'PROBE',    '분할 진입',  probe,    '약한 트리거 발화. 50% 진입 가능.',        '⚡ 절반 진입',     'probe')    }}
    <div class="pipe-arrow">▶</div>
    {{ _stage('🟢', 'ENTER',    '본 진입',    enter,    '확정 트리거 발화. 풀 진입 가능.',         '✅ 풀 진입',       'enter')    }}
    <div class="pipe-arrow invisible">|</div>
    {{ _stage('🔴', 'AVOID',    '매수 금지',  avoid,    '과확장 · 구조 깨짐. 별도 위험 상태.',      '❌ 매수 금지',     'avoid')    }}
  </div>

  <div class="flow-narration">
    <b>이 흐름의 의미</b>: 추세에 있는 종목(<b>TRENDING</b>)은 일정 기간 오르다가 잠시 쉬는 구간(<b>WATCH</b>=PULLBACK/BASE)으로 들어옵니다. 그 안에서 반등 신호가 살짝 뜨면 <b>PROBE</b>, 거래량 증가까지 확인되면 <b>ENTER</b>로 승격됩니다. 반대로 너무 많이 오르거나 추세가 깨지면 <b>AVOID</b>로 빠집니다 (별도 경로).
  </div>
</div>
```

- [ ] **Step 2: Commit**

```bash
git add templates/_lifecycle_pipeline.html
git commit -m "feat(lifecycle): _lifecycle_pipeline.html partial — 5-stage flow

Macro-based 5-stage horizontal flow (TRENDING → WATCH → PROBE → ENTER + AVOID).
Color-coded circles match decision palette. Empty stages show '— 오늘 해당
종목 없음 —' fallback. Used by both lifecycle_us.html and lifecycle_kr.html."
```

---

## Task 6: `_lifecycle_glossary.html` partial 작성

**Files:**
- Create: `templates/_lifecycle_glossary.html`

5개 collapsible `<details>` 용어 사전. 첫 번째 (결정 매트릭스)만 `open`. `lifecycle_thresholds` 변수로 임계값 주입.

- [ ] **Step 1: partial 파일 작성**

```html
{# templates/_lifecycle_glossary.html
   용어 사전 5 collapsible sections. parent context 요구:
     lifecycle_thresholds (dict from build_page_context)
#}
<section class="glossary">
  <h2>📖 용어 사전</h2>

  <details open>
    <summary>왜 5가지 그룹으로 나누나? (결정 매트릭스)</summary>
    <div class="gbody">
      시스템은 종목을 두 축으로 보고 최종 그룹을 정합니다:
      <br><b>① Setup</b> (구조 진단) × <b>② Trigger</b> (진입 신호)
      <table class="matrix-table">
        <thead>
          <tr>
            <th>Setup \ Trigger</th>
            <th>WAIT<br>(신호 없음)</th>
            <th>EARLY<br>(약한 신호)</th>
            <th>CONFIRMED<br>(거래량 동반)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td class="setup-name">TREND_OK (추세)</td>
            <td class="cell-trending" colspan="3">⚪ 눌림 대기 (TRENDING)</td>
          </tr>
          <tr>
            <td class="setup-name">PULLBACK (눌림)</td>
            <td class="cell-watch">🔵 WATCH</td>
            <td class="cell-probe">🟡 PROBE</td>
            <td class="cell-enter">🟢 ENTER</td>
          </tr>
          <tr>
            <td class="setup-name">BASE_FORMING (베이스)</td>
            <td class="cell-watch">🔵 WATCH</td>
            <td class="cell-probe">🟡 PROBE</td>
            <td class="cell-enter">🟢 ENTER</td>
          </tr>
          <tr>
            <td class="setup-name">EXTENDED (과확장)</td>
            <td class="cell-avoid" colspan="3">🔴 AVOID — 트리거 무시</td>
          </tr>
          <tr>
            <td class="setup-name">BROKEN (깨짐)</td>
            <td class="cell-avoid" colspan="3">🔴 AVOID — 트리거 무시</td>
          </tr>
        </tbody>
      </table>
      <p class="note">※ 추가: <b>FAILED_BREAKOUT</b> 태그가 붙으면 무조건 AVOID로 강제 분류.</p>
    </div>
  </details>

  <details>
    <summary>Setup (구조 진단) — 5단계</summary>
    <div class="gbody">
      종목의 추세 구조를 진단하는 5단계 분류.
      평가 우선순위: <b>BROKEN &gt; EXTENDED &gt; BASE_FORMING &gt; PULLBACK &gt; TREND_OK</b>
      <table>
        <tr><th>단계</th><th>의미</th><th>판정 조건</th></tr>
        <tr><td><span class="tag tag-TREND_OK">TREND_OK</span></td>
            <td>정상 상승 추세</td>
            <td>EMA9 &gt; EMA21 &gt; EMA65 정렬 + EMA65 5일 기울기 양수</td></tr>
        <tr><td><span class="tag tag-PULLBACK">PULLBACK</span></td>
            <td>추세 안의 단기 하락 (=진입 자리)</td>
            <td>TREND_OK 조건 + EMA9 거리 ≤ {{ (lifecycle_thresholds.PULLBACK_MAX_DIST_FROM_EMA9 * 100)|round(0)|int }}% + EMA21 위</td></tr>
        <tr><td><span class="tag tag-BASE">BASE_FORMING</span></td>
            <td>{{ lifecycle_thresholds.BASE_FORMING_DAYS_MIN }}–{{ lifecycle_thresholds.BASE_FORMING_DAYS_MAX }}일 횡보 + 변동성 수축 (=VCP)</td>
            <td>5d ATR &lt; 20d ATR + 거래량 수축 + EMA21 기울기 양수</td></tr>
        <tr><td><span class="tag tag-EXTENDED">EXTENDED</span></td>
            <td>과확장</td>
            <td>정렬 유지 + EMA9 거리 &gt; {{ (lifecycle_thresholds.EXTENDED_DIST_FROM_EMA9 * 100)|round(0)|int }}% + RSI &gt; {{ lifecycle_thresholds.EXTENDED_RSI_MIN }}</td></tr>
        <tr><td><span class="tag tag-BROKEN">BROKEN</span></td>
            <td>구조 깨짐</td>
            <td>EMA21 &lt; EMA65 또는 종가 &lt; EMA65</td></tr>
      </table>
    </div>
  </details>

  <details>
    <summary>Trigger (진입 신호) — 3단계</summary>
    <div class="gbody">
      Setup이 PULLBACK 또는 BASE_FORMING일 때만 의미 있음.
      <table>
        <tr><th>신호</th><th>조건</th></tr>
        <tr><td><b>WAIT</b></td><td>진입 신호 없음 (대다수의 일상)</td></tr>
        <tr><td><b>EARLY_TRIGGER</b></td><td>EMA9 reclaim 또는 전일 고점 돌파 + 종가가 일중 상위 {{ ((1 - lifecycle_thresholds.TRIGGER_CONFIRM_CLOSE_HIGH_RATIO) * 100)|round(0)|int }}%</td></tr>
        <tr><td><b>CONFIRMED_TRIGGER</b></td><td>EARLY 조건 + 거래량 {{ lifecycle_thresholds.TRIGGER_CONFIRM_VOL_RATIO_MIN }}배 + 종가 일중 상위 {{ ((1 - lifecycle_thresholds.TRIGGER_CONFIRM_CLOSE_HIGH_RATIO) * 100)|round(0)|int }}%</td></tr>
      </table>
    </div>
  </details>

  <details>
    <summary>지표 약어 (테이블 컬럼)</summary>
    <div class="gbody">
      <table>
        <tr><th>약어</th><th>설명</th></tr>
        <tr><td><b>EMA9 / EMA21 / EMA65</b></td><td>9일, 21일, 65일 지수이동평균</td></tr>
        <tr><td><b>dist_ema9 / dist_ema21</b></td><td>현재 가격이 해당 이평선보다 얼마나 위 (%)</td></tr>
        <tr><td><b>vol_ratio</b></td><td>20일 평균 거래량 대비 비율. 1.0 = 평균, 1.2 = 평균의 1.2배</td></tr>
        <tr><td><b>ATR %</b></td><td>평균 진폭 (변동성). 종가 대비 %</td></tr>
        <tr><td><b>days_in_pb</b></td><td>PULLBACK/BASE_FORMING에 머문 연속 일수</td></tr>
        <tr><td><b>setup_streak</b></td><td>같은 setup 유지 연속 일수</td></tr>
        <tr><td><b>trig_age</b></td><td>마지막 trigger 발화로부터 경과 일수 (0=오늘)</td></tr>
      </table>
    </div>
  </details>

  <details>
    <summary>위험 태그 (risk_tags)</summary>
    <div class="gbody">
      <table>
        <tr><th>태그</th><th>조건</th></tr>
        <tr><td><b>OVERHEAT</b></td><td>RSI ≥ {{ lifecycle_thresholds.RISK_OVERHEAT_RSI }}</td></tr>
        <tr><td><b>PARABOLIC</b></td><td>1일 수익률 ≥ +{{ (lifecycle_thresholds.RISK_PARABOLIC_RET_1D * 100)|round(0)|int }}% &amp; 거래량 ≥ {{ lifecycle_thresholds.RISK_PARABOLIC_VOL_RATIO }}배</td></tr>
        <tr><td><b>FAILED_BREAKOUT</b></td><td>어제 CONFIRMED → 오늘 종가 &lt; EMA9. 가짜 돌파 → 강제 AVOID</td></tr>
      </table>
    </div>
  </details>
</section>
```

- [ ] **Step 2: Commit**

```bash
git add templates/_lifecycle_glossary.html
git commit -m "feat(lifecycle): _lifecycle_glossary.html partial — 5 collapsible sections

Decision matrix (open by default), Setup states, Trigger signals, indicator
abbreviations, and risk tags. Threshold values dynamically injected from
lifecycle_thresholds context (driven by lifecycle_config.py)."
```

---

## Task 7: `lifecycle_us.html` 전면 재작성

**Files:**
- Modify: `templates/lifecycle_us.html` (entire file replaced)

전체 새로 작성. 사이드바 include / 테마 토글 / 모바일 nav 보존. mockup 콘텐츠 적용.

- [ ] **Step 1: 새 템플릿 작성**

`templates/lifecycle_us.html` 의 전체 내용을 다음으로 **교체**:

```html
<!DOCTYPE html>
<html lang="ko">
<head>
<script>document.documentElement.classList.add(localStorage.getItem('theme')||'dark')</script>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🔄 Lifecycle US — {{ as_of }}</title>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Manrope:wght@300;400;500;600;700;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap" rel="stylesheet">
<script>
tailwind.config = {
  darkMode: "class",
  theme: { extend: {
    colors: {
      "surface-container": "rgb(var(--c-surface-container) / <alpha-value>)",
      "surface-container-high": "rgb(var(--c-surface-container-high) / <alpha-value>)",
      "surface": "rgb(var(--c-surface) / <alpha-value>)",
      "primary": "rgb(var(--c-primary) / <alpha-value>)",
      "on-surface": "rgb(var(--c-on-surface) / <alpha-value>)",
      "on-surface-variant": "rgb(var(--c-on-surface-variant) / <alpha-value>)",
      "outline-variant": "rgb(var(--c-outline-variant) / <alpha-value>)",
    },
    fontFamily: { headline: ["Space Grotesk"], body: ["Manrope"], label: ["Inter"] },
  }}
}
</script>
<style>
  html.dark {
    --c-surface-container: 15 25 48; --c-surface-container-high: 20 31 56;
    --c-surface: 6 14 32; --c-background: 6 14 32;
    --c-primary: 109 221 255;
    --c-on-surface: 222 229 255; --c-on-surface-variant: 163 170 196;
    --c-outline-variant: 64 72 93;
    --bg: #0a1226; --card: #0f1a36; --card-2: #14203f;
    --border: rgba(148,163,184,0.15); --text: #e2e8f0; --muted: #94a3b8;
    --primary-c: #6dddff;
    --green: #22c55e; --yellow: #eab308; --blue: #3b82f6; --gray: #64748b; --red: #ef4444;
  }
  html.light {
    --c-surface-container: 255 255 255; --c-surface-container-high: 248 250 252;
    --c-surface: 241 245 249; --c-background: 241 245 249;
    --c-primary: 2 132 199;
    --c-on-surface: 15 23 42; --c-on-surface-variant: 71 85 105;
    --c-outline-variant: 148 163 184;
    --bg: #f1f5f9; --card: #ffffff; --card-2: #f8fafc;
    --border: rgba(100,116,139,0.2); --text: #0f172a; --muted: #64748b;
    --primary-c: #0284c7;
    --green: #16a34a; --yellow: #ca8a04; --blue: #2563eb; --gray: #64748b; --red: #dc2626;
  }
  body { background: var(--bg); color: var(--text); }

  .concept-box, .pipeline, section.detail, .glossary > details {
    background: var(--card); border: 1px solid var(--border); border-radius: 12px;
  }
  .concept-box, .pipeline, section.detail { padding: 18px 22px; margin-bottom: 20px; }
  .concept-box h3, .pipeline h2, section.detail h2 {
    margin: 0 0 6px; font-size: 17px; color: var(--primary-c);
    display: flex; align-items: center; gap: 8px;
  }
  .concept-box p { margin: 6px 0; font-size: 14px; }
  .concept-box b { color: var(--text); }
  .pipeline .sub, section.detail .sub { color: var(--muted); font-size: 13px; margin-bottom: 14px; }

  .summary-box {
    margin: 20px 0 28px; padding: 20px 24px;
    background: linear-gradient(135deg, rgba(109,221,255,0.08), rgba(34,197,94,0.04));
    border: 1px solid rgba(109,221,255,0.25); border-radius: 12px;
  }
  .summary-box h2 { margin: 0 0 12px; font-size: 15px; color: var(--primary-c); }
  .summary-box .big-verdict { font-size: 18px; font-weight: 700; margin: 6px 0 14px; color: #fde047; }
  .summary-box .verdict { font-size: 14px; line-height: 1.7; color: var(--text); margin: 4px 0; }

  .pipe-flow { display: flex; gap: 12px; align-items: stretch; overflow-x: auto; }
  .pipe-stage {
    flex: 1; min-width: 150px;
    background: var(--card-2); border-radius: 10px; padding: 14px; border-top: 4px solid;
    display: flex; flex-direction: column;
  }
  .stage-trending { border-color: var(--gray); }
  .stage-watch    { border-color: var(--blue); }
  .stage-probe    { border-color: var(--yellow); }
  .stage-enter    { border-color: var(--green); }
  .stage-avoid    { border-color: var(--red); }
  .stage-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4px; }
  .stage-name { font-weight: 700; font-size: 14px; }
  .stage-count { font-size: 22px; font-weight: 800; }
  .stage-trending .stage-name, .stage-trending .stage-count { color: var(--gray); }
  .stage-watch    .stage-name, .stage-watch    .stage-count { color: var(--blue); }
  .stage-probe    .stage-name, .stage-probe    .stage-count { color: var(--yellow); }
  .stage-enter    .stage-name, .stage-enter    .stage-count { color: var(--green); }
  .stage-avoid    .stage-name, .stage-avoid    .stage-count { color: var(--red); }
  .stage-desc { font-size: 11.5px; color: var(--muted); margin-bottom: 10px; min-height: 36px; }
  .stage-action {
    font-size: 12px; font-weight: 600;
    padding: 4px 8px; border-radius: 4px; margin-bottom: 10px; display: inline-block;
    background: rgba(100,116,139,0.15);
  }
  .stage-tickers { font-size: 12px; line-height: 1.55; word-break: break-word; }
  .stage-tickers .muted { color: var(--muted); }
  .pipe-arrow { align-self: center; color: var(--muted); font-size: 20px; padding: 0 2px; }
  .pipe-arrow.invisible { color: transparent; }
  .flow-narration { margin-top: 18px; padding: 14px 16px; background: rgba(0,0,0,0.15); border-radius: 8px; font-size: 13px; color: var(--text); line-height: 1.7; }

  .action-box {
    padding: 10px 12px; border-radius: 8px; font-size: 13px; line-height: 1.55;
    border-left: 3px solid; margin-bottom: 14px;
  }
  .action-box .head { display: flex; align-items: center; gap: 6px; font-weight: 700; margin-bottom: 4px; }
  .action-box .desc { color: var(--text); }
  .action-box .desc b { color: var(--text); font-weight: 700; }
  .action-danger { background: rgba(239,68,68,0.08); border-color: #ef4444; }
  .action-danger .head { color: #fca5a5; }
  .action-watch { background: rgba(59,130,246,0.08); border-color: #3b82f6; }
  .action-watch .head { color: #93c5fd; }
  .action-trend { background: rgba(100,116,139,0.1); border-color: #64748b; }
  .action-trend .head { color: #cbd5e1; }
  .action-enter { background: rgba(34,197,94,0.08); border-color: #22c55e; }
  .action-enter .head { color: #86efac; }
  .action-probe { background: rgba(234,179,8,0.08); border-color: #eab308; }
  .action-probe .head { color: #fde047; }

  .stock-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 8px; }
  .stock-chip {
    background: var(--card-2); border: 1px solid var(--border); border-radius: 6px;
    padding: 8px 10px; font-size: 12px;
  }
  .stock-chip .ticker { font-weight: 700; color: var(--primary-c); font-size: 13px; }
  .stock-chip .meta { color: var(--muted); margin-top: 2px; font-size: 11px; line-height: 1.5; }
  .stock-chip .risk { color: #fca5a5; font-weight: 600; font-size: 11px; margin-top: 2px; }
  .stock-chip.danger { border-color: rgba(239,68,68,0.3); background: rgba(239,68,68,0.05); }
  .stock-chip.new-confirmed { border-color: rgba(34,197,94,0.4); background: rgba(34,197,94,0.05); }

  .tag {
    display: inline-block; padding: 1px 6px; border-radius: 3px;
    font-size: 10.5px; font-weight: 700; margin-right: 3px;
  }
  .tag-PULLBACK { background: rgba(59,130,246,0.18); color: #93c5fd; }
  .tag-TREND_OK { background: rgba(100,116,139,0.2); color: #cbd5e1; }
  .tag-EXTENDED { background: rgba(239,68,68,0.18); color: #fca5a5; }
  .tag-BASE     { background: rgba(34,197,94,0.18); color: #86efac; }
  .tag-BROKEN   { background: rgba(239,68,68,0.3);  color: #fca5a5; }

  .glossary > details { padding: 12px 16px; margin-bottom: 8px; }
  .glossary summary { cursor: pointer; font-weight: 600; color: var(--primary-c); font-size: 14px; }
  .glossary .gbody { margin-top: 10px; font-size: 13px; line-height: 1.7; color: var(--text); }
  .glossary table { width: 100%; border-collapse: collapse; margin-top: 6px; font-size: 13px; }
  .glossary th, .glossary td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); vertical-align: top; }
  .glossary th { color: var(--muted); font-weight: 500; font-size: 11px; text-transform: uppercase; }
  .glossary .note { margin-top: 10px; font-size: 12px; color: var(--muted); }

  .matrix-table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 12px; }
  .matrix-table th, .matrix-table td { padding: 8px; text-align: center; border: 1px solid var(--border); }
  .matrix-table th { background: rgba(0,0,0,0.2); color: var(--muted); }
  .matrix-table td.setup-name { background: rgba(0,0,0,0.1); font-weight: 600; text-align: left; padding-left: 12px; }
  .cell-trending { background: rgba(100,116,139,0.12); color: #cbd5e1; }
  .cell-watch    { background: rgba(59,130,246,0.12); color: #93c5fd; }
  .cell-probe    { background: rgba(234,179,8,0.12); color: #fde047; }
  .cell-enter    { background: rgba(34,197,94,0.12); color: #86efac; }
  .cell-avoid    { background: rgba(239,68,68,0.12); color: #fca5a5; }

  .advanced > details { padding: 12px 16px; margin-bottom: 8px; background: var(--card); border: 1px solid var(--border); border-radius: 12px; }
  .advanced summary { cursor: pointer; font-weight: 600; color: var(--primary-c); font-size: 14px; }
  .advanced .abody { margin-top: 12px; }
  .data-table { width: 100%; border-collapse: collapse; font-size: 11px; margin-top: 8px; }
  .data-table th, .data-table td { padding: 4px 6px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }
  .data-table th { color: var(--muted); font-size: 10px; text-transform: uppercase; }

  footer { margin-top: 30px; padding-top: 16px; border-top: 1px solid var(--border); font-size: 12px; color: var(--muted); }
  footer p { margin: 4px 0; }

  @media (max-width: 768px) {
    .pipe-flow { flex-direction: column; }
    .pipe-arrow { transform: rotate(90deg); padding: 4px 0; }
  }
</style>
</head>
<body class="font-body">

{% include "_sidebar.html" %}
<div class="fixed inset-0 bg-black/50 z-40 hidden" id="sidebarOverlay" onclick="toggleSidebar()"></div>

<main class="md:ml-64 min-h-screen">
  <header class="flex justify-between items-center w-full px-8 py-4 bg-surface/60 backdrop-blur-xl z-40 shadow-[0_40px_40px_0_rgba(222,229,255,0.08)] sticky top-0">
    <div class="flex items-center gap-4">
      <button class="md:hidden text-on-surface" onclick="toggleSidebar()"><span class="material-symbols-outlined">menu</span></button>
      <span class="text-xl font-bold text-on-surface uppercase font-headline tracking-tight">🔄 Lifecycle US</span>
      <span class="text-xs text-on-surface-variant font-label hidden sm:block">{{ as_of }} 기준 · {{ version }}</span>
    </div>
    <button onclick="toggleTheme()" class="p-2 text-on-surface/60 hover:text-primary transition-colors" title="Toggle Theme"><span class="material-symbols-outlined" id="themeIcon">light_mode</span></button>
  </header>

  <div class="p-8 space-y-0 max-w-[1100px] mx-auto">

    {# 컨셉 박스 #}
    <div class="concept-box">
      <h3>📌 이 페이지는 뭐 하는 페이지인가요?</h3>
      <p>Momentum 스캐너가 추세 후보로 뽑은 종목들이 <b>지금 어느 단계에 있는지</b> 매일 추적하는 페이지입니다. 각 종목을 <b>"사도 되는가 / 기다려야 하는가 / 피해야 하는가"</b> 5단계로 분류합니다.</p>
      <p>⚠️ <b>매수 판단 보조용</b>이지 자동 매매가 아닙니다. 또한 <b>보유 종목 매도</b>는 Portfolio Risk 페이지에서 별도로 봅니다.</p>
    </div>

    {# 오늘의 결론 #}
    <div class="summary-box">
      <h2>📊 오늘의 결론 ({{ as_of }})</h2>
      <div class="big-verdict">{{ verdict_summary.headline }}</div>
      <div class="verdict">{{ verdict_summary.narration }}</div>
      {% if verdict_summary.avoid_line %}
      <div class="verdict" style="margin-top: 8px;">{{ verdict_summary.avoid_line }}</div>
      {% endif %}
      <div class="verdict" style="margin-top: 12px;">💡 <b>오늘 할 일</b>: {{ verdict_summary.action_hint }}</div>
    </div>

    {# 파이프라인 partial #}
    {% include "_lifecycle_pipeline.html" %}

    {# AVOID 상세 #}
    {% if avoid %}
    <section class="detail">
      <h2>🔴 매수 금지 (AVOID) — {{ avoid|length }} 종목</h2>
      <p class="sub">9일선 대비 {{ (lifecycle_thresholds.EXTENDED_DIST_FROM_EMA9 * 100)|round(0)|int }}% 이상 이격 + RSI {{ lifecycle_thresholds.EXTENDED_RSI_MIN }} 초과 = EXTENDED (과확장). 지금 진입은 손실 위험 큼.</p>
      <div class="action-box action-danger">
        <div class="head">⚠ 공통 상황</div>
        <div class="desc">3종목 모두 <b>EXTENDED</b> 상태로, RSI는 {{ lifecycle_thresholds.RISK_OVERHEAT_RSI }} 이상 과매수, 9일선 이격은 정상 범위(±10%)를 크게 초과. <b>신규 진입 절대 금지</b>, 보유자는 분할 익절 검토.</div>
      </div>
      <div class="stock-list">
        {% for row in avoid %}
        <div class="stock-chip danger">
          <div class="ticker">{{ row.ticker }}</div>
          <div class="meta">9일선 {{ row.dist_ema9_signed_pct|signed_pct }} · 21일선 {{ row.dist_ema21_signed_pct|signed_pct }}</div>
          {% if row.raw and row.raw.risk_tags %}
          <div class="risk">⚠ {{ row.raw.risk_tags|join(', ') }}</div>
          {% endif %}
        </div>
        {% endfor %}
      </div>
    </section>
    {% endif %}

    {# ENTER 상세 #}
    {% if enter %}
    <section class="detail">
      <h2>🟢 본 진입 (ENTER) — {{ enter|length }} 종목</h2>
      <p class="sub">PULLBACK/BASE 자리에서 확정 트리거(거래량 동반) 발화. 풀 진입 검토 가능.</p>
      <div class="action-box action-enter">
        <div class="head">✅ 오늘 할 일</div>
        <div class="desc">확정 트리거가 발화한 종목들입니다. 비중과 손절 기준을 정한 뒤 <b>풀 진입</b>을 검토하세요. 🆕 표시는 트리거 발화 첫날입니다.</div>
      </div>
      <div class="stock-list">
        {% for row in enter %}
        <div class="stock-chip {% if row.trigger_age_days == 0 and row.trigger == 'CONFIRMED_TRIGGER' %}new-confirmed{% endif %}">
          <div class="ticker">{{ row.ticker }}{% if row.trigger_age_days == 0 and row.trigger == 'CONFIRMED_TRIGGER' %} 🆕{% endif %}</div>
          <div class="meta">9일선 {{ row.dist_ema9_signed_pct|signed_pct }} · vol {{ row.raw.volume_ratio|x_fmt }} · trig {{ row.trigger_age_days|trig_age_label }}</div>
          <div class="meta">{{ row.setup }}</div>
        </div>
        {% endfor %}
      </div>
    </section>
    {% endif %}

    {# PROBE 상세 #}
    {% if probe %}
    <section class="detail">
      <h2>🟡 분할 진입 (PROBE) — {{ probe|length }} 종목</h2>
      <p class="sub">PULLBACK/BASE 자리에서 약한 트리거(거래량 미동반) 발화. 50% 비중 진입 검토.</p>
      <div class="action-box action-probe">
        <div class="head">⚡ 오늘 할 일</div>
        <div class="desc">약한 트리거 발화 — 거래량 부족으로 신뢰도가 풀 트리거보다 낮습니다. <b>절반 비중</b>으로 진입하고 다음 거래일 확인 후 추가 진입 결정.</div>
      </div>
      <div class="stock-list">
        {% for row in probe %}
        <div class="stock-chip">
          <div class="ticker">{{ row.ticker }}</div>
          <div class="meta">9일선 {{ row.dist_ema9_signed_pct|signed_pct }} · vol {{ row.raw.volume_ratio|x_fmt }}</div>
          <div class="meta">EARLY · {{ row.setup_streak }}일 압축</div>
        </div>
        {% endfor %}
      </div>
    </section>
    {% endif %}

    {# WATCH 상세 #}
    {% if watch %}
    <section class="detail">
      <h2>🔵 진입 대기 (WATCH) — {{ watch|length }} 종목</h2>
      <p class="sub">PULLBACK(눌림목) 자리에 도착했지만 반등 신호(트리거)가 아직 안 뜸. <b>매일 다시 평가</b>되며 신호 발화 시 PROBE/ENTER로 자동 승격.</p>
      <div class="action-box action-watch">
        <div class="head">👀 오늘 할 일</div>
        <div class="desc">지금 사지 마세요. 이 종목들이 <b>"반등 신호 + 거래량 증가"</b>를 보이면 시스템이 자동으로 ENTER로 올려줍니다. 다음 거래일에 이 페이지를 다시 확인하세요.<br>👉 <b>관전 포인트</b>: 거래량 평균 대비 {{ lifecycle_thresholds.TRIGGER_CONFIRM_VOL_RATIO_MIN }}배 이상 + 종가가 일중 상위 {{ ((1 - lifecycle_thresholds.TRIGGER_CONFIRM_CLOSE_HIGH_RATIO) * 100)|round(0)|int }}% 마감.</div>
      </div>
      <div class="stock-list">
        {% for row in watch %}
        <div class="stock-chip">
          <div class="ticker">{{ row.ticker }}</div>
          <div class="meta">9일선 {{ row.dist_ema9_signed_pct|signed_pct }} · 21일선 {{ row.dist_ema21_signed_pct|signed_pct }}</div>
          <div class="meta">{{ row.setup }} · {{ row.setup_streak }}일 압축</div>
        </div>
        {% endfor %}
      </div>
    </section>
    {% endif %}

    {# TRENDING 상세 #}
    {% if trending %}
    <section class="detail">
      <h2>⚪ 눌림 대기 (TRENDING) — {{ trending|length }} 종목</h2>
      <p class="sub">추세는 살아있으나 아직 눌림 자리가 안 형성됨. 지금 추격 매수는 자제하고, 다음 PULLBACK을 기다림.</p>
      <div class="action-box action-trend">
        <div class="head">📍 오늘 할 일</div>
        <div class="desc">이 종목들은 <b>이미 추세 중</b>이라 따라잡기 매수는 평균단가가 높아질 위험이 있습니다. 다음에 <b>EMA9 근처까지 단기 조정</b>이 오면 그때 WATCH로 이동하고 진입 검토 가능.<br>👉 지금은 <b>관망</b>만, 차트 알람만 걸어두기.</div>
      </div>
      <div class="stock-list">
        {% for row in trending %}
        <div class="stock-chip">
          <div class="ticker">{{ row.ticker }}</div>
          <div class="meta">9일선 {{ row.dist_ema9_signed_pct|signed_pct }} · {{ row.setup_streak }}일 추세 유지</div>
        </div>
        {% endfor %}
      </div>
    </section>
    {% endif %}

    {# 용어 사전 partial #}
    {% include "_lifecycle_glossary.html" %}

    {# 고급 보기 #}
    <section class="advanced">
      <details>
        <summary>⚙ 고급 보기 (디버깅·audit용)</summary>
        <div class="abody">

          {# 최근 상태 전환 #}
          {% if transitions %}
          <h3 style="font-size:14px; margin: 10px 0 6px;">최근 상태 전환 (transitions, 최근 {{ transitions|length }}개)</h3>
          <table class="data-table">
            <thead><tr><th>ticker</th><th>from → to</th><th>as_of</th></tr></thead>
            <tbody>
              {% for t in transitions|reverse %}
              <tr>
                <td><b>{{ t.ticker }}</b></td>
                <td>{{ t.from_decision }} → {{ t.to_decision }}</td>
                <td>{{ t.as_of }}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
          {% endif %}

          {# BROKEN 별도 #}
          {% if broken_table %}
          <h3 style="font-size:14px; margin: 16px 0 6px;">BROKEN 종목 — 구조 깨짐 (매수 후보 자격 상실)</h3>
          <div class="stock-list">
            {% for row in broken_table %}
            <div class="stock-chip danger">
              <div class="ticker">{{ row.ticker }}</div>
              <div class="meta">{{ row.setup }} · 9일선 {{ row.dist_ema9_signed_pct|signed_pct }}</div>
            </div>
            {% endfor %}
          </div>
          {% endif %}

          {# 전체 상세 테이블 #}
          <h3 style="font-size:14px; margin: 16px 0 6px;">전체 종목 상세 데이터</h3>
          <table class="data-table">
            <thead>
              <tr>
                <th>ticker</th><th>decision</th><th>setup</th><th>trigger</th>
                <th>dist_ema9</th><th>dist_ema21</th>
                <th>vol_ratio</th><th>setup_streak</th><th>trig_age</th><th>risk_tags</th>
              </tr>
            </thead>
            <tbody>
              {% for row in (enter + probe + watch + trending + avoid + broken_table) %}
              <tr>
                <td><b>{{ row.ticker }}</b></td>
                <td>{{ row.decision }}</td>
                <td>{{ row.setup }}</td>
                <td>{{ row.trigger }}</td>
                <td>{{ row.dist_ema9_signed_pct|signed_pct }}</td>
                <td>{{ row.dist_ema21_signed_pct|signed_pct }}</td>
                <td>{{ row.raw.volume_ratio|x_fmt }}</td>
                <td>{{ row.setup_streak }}</td>
                <td>{{ row.trigger_age_days|trig_age_label }}</td>
                <td>{{ (row.raw.risk_tags or [])|join(', ') }}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>

        </div>
      </details>
    </section>

    <footer>
      <p>Lifecycle Phase A · {{ version }} · 추적 {{ (enter + probe + watch + trending + avoid + broken_table)|length }} 종목</p>
      <p>※ 시장 국면 분류기(RISK_ON / TRENDING / CHOPPY / RISK_OFF)는 Phase B에서 추가 예정</p>
      <p>※ 본 문서는 정보 제공용이며 투자 권유가 아닙니다.</p>
    </footer>

  </div>
</main>

<nav class="md:hidden fixed bottom-0 left-0 right-0 bg-surface-container-high/90 backdrop-blur-xl border-t border-outline-variant/10 z-50 px-6 py-4 flex justify-between items-center">
  <a href="{{ nav_portfolio }}" class="text-on-surface-variant flex flex-col items-center gap-1"><span class="material-symbols-outlined">dashboard</span><span class="text-[10px]">Home</span></a>
  <a href="{{ nav_scanner }}" class="text-on-surface-variant flex flex-col items-center gap-1"><span class="material-symbols-outlined">analytics</span><span class="text-[10px]">Scan</span></a>
  <a href="{{ nav_trend }}" class="text-on-surface-variant flex flex-col items-center gap-1"><span class="material-symbols-outlined">trending_up</span><span class="text-[10px]">Trend</span></a>
  <a href="{{ nav_backtest }}" class="text-on-surface-variant flex flex-col items-center gap-1"><span class="material-symbols-outlined">history</span><span class="text-[10px]">Backtest</span></a>
</nav>

<script>
function toggleSidebar(){const s=document.getElementById('sidebar'),o=document.getElementById('sidebarOverlay');s.classList.toggle('hidden');s.classList.toggle('flex');o.classList.toggle('hidden');}
function toggleTheme(){const h=document.documentElement,d=h.classList.contains('dark');h.classList.remove('dark','light');const t=d?'light':'dark';h.classList.add(t);localStorage.setItem('theme',t);document.getElementById('themeIcon').textContent=t==='dark'?'light_mode':'dark_mode';}
document.addEventListener('DOMContentLoaded',function(){document.getElementById('themeIcon').textContent=document.documentElement.classList.contains('dark')?'light_mode':'dark_mode';});
</script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add templates/lifecycle_us.html
git commit -m "feat(lifecycle): rewrite lifecycle_us.html with mockup design

Full template rewrite — sidebar/theme-toggle/mobile-nav preserved,
mockup content adopted: 📌 concept box, 📊 dynamic verdict box,
🌊 5-stage pipeline (via partial), 5 detail sections with chip grid,
📖 collapsible glossary (via partial), ⚙ advanced view (transitions
+ BROKEN + full data table)."
```

---

## Task 8: `lifecycle_kr.html` 전면 재작성

**Files:**
- Modify: `templates/lifecycle_kr.html`

US 템플릿과 95% 동일. 차이만 적용: 제목 `🔄 Lifecycle KR`, 칩에 한글명 표시.

- [ ] **Step 1: 새 KR 템플릿 작성**

Task 7의 US 템플릿 내용을 그대로 **복사**하되, 다음 4개 변경:

**(a) `<title>` 라인 (line 7)**:
```html
<title>🔄 Lifecycle KR — {{ as_of }}</title>
```

**(b) header `<span>` 제목 (라인 ~227)**:
```html
<span class="text-xl font-bold text-on-surface uppercase font-headline tracking-tight">🔄 Lifecycle KR</span>
```

**(c) AVOID/ENTER/PROBE/WATCH/TRENDING 각 섹션의 칩 ticker 라인 — `{{ row.ticker }}` 옆에 한글명 추가**:

각 `<div class="ticker">{{ row.ticker }}{% if row... %}{% endif %}</div>` 라인을 다음으로 변경 (각 섹션마다 다른 `🆕` 분기 보존):

- AVOID/PROBE/WATCH/TRENDING/BROKEN 칩:
```html
<div class="ticker">{{ row.ticker }} <span class="kr-name">{{ row.name }}</span></div>
```

- ENTER 칩 (🆕 분기 보존):
```html
<div class="ticker">{{ row.ticker }} <span class="kr-name">{{ row.name }}</span>{% if row.trigger_age_days == 0 and row.trigger == 'CONFIRMED_TRIGGER' %} 🆕{% endif %}</div>
```

**(d) `<style>` 블록에 `.kr-name` 클래스 추가** (`.stock-chip .ticker` 정의 다음에):
```css
  .stock-chip .ticker .kr-name { font-weight: 400; color: var(--muted); font-size: 11px; margin-left: 4px; }
```

**(e) 고급 보기 상세 테이블의 ticker 셀도 한글명 표시**:

`<td><b>{{ row.ticker }}</b></td>` → `<td><b>{{ row.ticker }}</b> <span style="color:var(--muted); font-size:10px;">{{ row.name }}</span></td>`

- [ ] **Step 2: Commit**

```bash
git add templates/lifecycle_kr.html
git commit -m "feat(lifecycle): rewrite lifecycle_kr.html with mockup design + KR names

Same structure as lifecycle_us.html with KR-specific differences:
title '🔄 Lifecycle KR', chip headers show both ticker and Korean name
(e.g. '005930 삼성전자' from market_scanner.KOSPI_NAMES), and the
advanced detail table includes Korean name column."
```

---

## Task 9: 로컬 pipeline 실행 + 시각 검증

**Files:** 실행만, 코드 변경 없음

- [ ] **Step 1: SKIP_SCANNERS 실행**

Bash:
```bash
SKIP_SCANNERS=1 PYTHONIOENCODING=utf-8 python pipeline.py 2>&1 | tail -20
```

PowerShell:
```powershell
$env:SKIP_SCANNERS="1"; $env:PYTHONIOENCODING="utf-8"; python pipeline.py 2>&1 | Select-Object -Last 20
```

Expected: 에러 없이 완료. `reports/lifecycle_us_YYYY-MM-DD.html` + `reports/lifecycle_kr_YYYY-MM-DD.html` 생성.

If lifecycle 단계가 SKIP_SCANNERS로 스킵되면 그 환경변수 없이 재실행:
```bash
PYTHONIOENCODING=utf-8 python pipeline.py 2>&1 | tail -30
```

- [ ] **Step 2: 생성된 lifecycle US HTML 검사**

```bash
python -c "
import glob, os, re, json
files = sorted(glob.glob('reports/lifecycle_us_*.html'), key=os.path.getmtime, reverse=True)
if not files:
    print('FAIL: no lifecycle_us HTML found')
    exit(1)
latest = files[0]
print(f'Latest: {latest}')
with open(latest, 'r', encoding='utf-8') as f:
    html = f.read()

checks = [
    ('컨셉 박스', '이 페이지는 뭐 하는 페이지인가요' in html),
    ('오늘의 결론 헤더', '오늘의 결론' in html),
    ('파이프라인 헤더', '종목 흐름 파이프라인' in html),
    ('TRENDING stage', '⚪' in html and 'TRENDING' in html),
    ('WATCH stage', '🔵' in html and 'WATCH' in html),
    ('PROBE stage', '🟡' in html and 'PROBE' in html),
    ('ENTER stage', '🟢' in html and 'ENTER' in html),
    ('AVOID stage', '🔴' in html and 'AVOID' in html),
    ('용어 사전', '용어 사전' in html),
    ('결정 매트릭스', '결정 매트릭스' in html),
    ('고급 보기', '고급 보기' in html),
    ('사이드바 (My Portfolio)', 'My Portfolio' in html or 'nav_portfolio' in html),
    ('모바일 nav (Trend 링크)', 'Trend' in html),
    ('테마 토글 (toggleTheme)', 'toggleTheme' in html),
    ('verdict 동적 narration', '오늘 할 일' in html),
]
print()
for name, ok in checks:
    print(f'  {\"OK\" if ok else \"FAIL\"}: {name}')
all_ok = all(ok for _, ok in checks)
print(f'\n{\"ALL OK\" if all_ok else \"SOME FAILED\"}')
exit(0 if all_ok else 1)
"
```

Expected: 모두 OK.

- [ ] **Step 3: KR HTML도 동일 검증**

Step 2 명령에서 `lifecycle_us_*.html` → `lifecycle_kr_*.html`로 바꿔 실행. 추가로:
```bash
python -c "
import glob, os
files = sorted(glob.glob('reports/lifecycle_kr_*.html'), key=os.path.getmtime, reverse=True)
with open(files[0], 'r', encoding='utf-8') as f:
    html = f.read()
# KR-specific: 한글명 표시 검증 — 보유 KOSPI 종목 중 하나라도 한글명 포함
import re
kr_name_pattern = re.compile(r'kr-name')
matches = kr_name_pattern.findall(html)
print(f'kr-name 클래스 발견 횟수: {len(matches)}')
assert len(matches) > 0, 'KR template should have kr-name spans for Korean stock names'
print('OK KR 한글명 표시 확인')
"
```

- [ ] **Step 4: 브라우저 시각 확인 (수동)**

사용자에게 다음 확인 요청:
- [ ] 파이프라인 5 스테이지 색상 정확 (회색/파랑/노랑/녹색/빨강)
- [ ] 칩 데이터 정상 표시 (9일선 +X%, 21일선 +Y% 등 부호 + 단위)
- [ ] Owner 사이드바 nav 작동 (Portfolio/Scanner/Trend 링크)
- [ ] 모바일 viewport (DevTools 768px 이하) 파이프라인 세로 stack
- [ ] 테마 토글 (☀/🌙) 작동 — 다크/라이트 양쪽 모두 정상
- [ ] 용어 사전 첫 항목 (결정 매트릭스) 펼침 + 나머지 4 접힘
- [ ] 고급 보기 클릭 시 transitions / BROKEN / 상세 테이블 표시
- [ ] verdict 동적 narration 케이스 정상 표시

- [ ] **Step 5: 리포트 commit**

```bash
git add reports/lifecycle_us_*.html reports/lifecycle_kr_*.html
git commit -m "data(report): regenerate lifecycle pages with new design

Pipeline run after Task 7-8 confirms US/KR HTML renders correctly:
컨셉 박스, 오늘의 결론, 5-stage 파이프라인, 5 detail sections (with
chip grid), 용어 사전, 고급 보기. Sidebar + mobile nav + theme toggle
all working. Visual confirmation pending human review."
```

---

## Task 10: CLAUDE.md "진행 중인 계획" 등록

**Files:**
- Modify: `CLAUDE.md` (`## 진행 중인 계획` 섹션)

- [ ] **Step 1: CLAUDE.md 수정**

`CLAUDE.md`의 `## 진행 중인 계획` 섹션 끝(마지막 bullet 다음)에 추가:

```markdown
- [Lifecycle Page Redesign](docs/superpowers/plans/2026-05-11-lifecycle-redesign.md) — Lifecycle US/KR 페이지 mockup 디자인 적용 · 🌊 5-stage 파이프라인 (TRENDING/WATCH/PROBE/ENTER/AVOID 색깔 원 통일) · 📌 컨셉 박스 + 📊 오늘의 결론 동적 narration · 칩 그리드 (테이블 대체) · 📖 용어 사전 collapsible (`lifecycle_thresholds` 변수 주입) · ⚙ 고급 보기 collapsible (transitions/BROKEN/상세 테이블 보존) · 사이드바·모바일 nav·테마 토글 유지 · 시그널/히스토리 path 무수정
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: register lifecycle redesign plan in CLAUDE.md"
```

---

## Self-Review Checklist

(plan 실행 후 reviewer 점검용)

### 1. Spec coverage
- [x] §3 결정 1 (US + KR 둘 다) → Tasks 7, 8
- [x] §3 결정 2 (collapsible 고급 보기) → Task 7 (advanced section)
- [x] §3 결정 3 (사이드바 + 모바일 nav) → Task 7 (sidebar include + mobile nav at end)
- [x] §3 결정 4 (5-stage 색깔 원 통일) → Task 5 (partial), Task 7 (CSS), Task 6 (matrix)
- [x] §4 아키텍처 (백엔드 minimal) → Tasks 2-4
- [x] §5.3 컨셉 박스 → Task 7
- [x] §5.4 동적 verdict (4 분기 + AVOID 동적 line) → Task 1 (tests), Task 2 (impl), Task 7 (use)
- [x] §5.5 파이프라인 partial → Task 5
- [x] §5.6 칩 데이터 (signed_pct + x_fmt + trig_age) → Task 3 (signed fields), Task 4 (filters), Task 7 (use)
- [x] §5.7 용어 사전 partial + 임계값 주입 → Task 6
- [x] §5.8 고급 보기 collapsible → Task 7 (advanced section)
- [x] §5.9 풋터 → Task 7
- [x] §6 백엔드 변경 (helper + signed fields + context keys + filters) → Tasks 2, 3, 4
- [x] §7 테스트 5개 (4 분기 + AVOID 동적) → Task 1
- [x] §8 파일 변경 전체 → Tasks 1-8 망라
- [x] §9 위험 완화 → Task 7 (사이드바/모바일/테마 보존), Task 9 (모바일/테마 시각 검증)

### 2. Placeholder scan
- "TBD" / "implement later" / "fill in details": 없음 ✓
- "add appropriate error handling" 없음 ✓
- "Similar to Task N" 없음 (Task 8 = Task 7 + 명시적 4개 변경 — diff 구체) ✓
- 모든 step에 코드/명령/예상 출력 명시 ✓

### 3. Type consistency
- 헬퍼 이름: `_build_verdict_summary` (Task 1, 2, 4, 7 일관) ✓
- 반환 dict 키 (4개): `headline`, `narration`, `avoid_line`, `action_hint` — Task 1, 2, 7 일관 ✓
- Context 키: `verdict_summary`, `lifecycle_thresholds` — Task 4, 6, 7 일관 ✓
- 신규 derived 필드: `dist_ema9_signed_pct`, `dist_ema21_signed_pct` — Task 3, 7, 8 일관 ✓
- Jinja 필터: `signed_pct`, `x_fmt`, `trig_age_label` — Task 4, 7, 8 일관 ✓
- Partial 이름: `_lifecycle_pipeline.html`, `_lifecycle_glossary.html` — Task 5, 6, 7, 8 일관 ✓

### 4. 실행 순서 의존성
- Task 1 → Task 2 (테스트 작성 → 통과)
- Task 2 → Task 4 (`_build_verdict_summary` 존재 → context에서 호출)
- Task 3 → Task 7, 8 (signed 필드 attach → 템플릿이 사용)
- Task 4 → Task 7, 8 (filters 등록 → 템플릿이 사용)
- Task 5, 6 → Task 7 (partials 존재 → US 템플릿이 include)
- Task 7 → Task 8 (US 완성 → KR이 US와 동일 + 4 변경)
- Task 7, 8 → Task 9 (템플릿 완성 → pipeline 실행 검증)

---

## Execution Notes

- **Worktree**: 이 plan은 `feature/lifecycle-redesign` 브랜치 + `.claude/worktrees/lifecycle-redesign` worktree에서 실행됨.
- **회귀 방지**: 시그널/히스토리/config path는 무수정. Task 2-4의 모든 변경은 `lifecycle_report.py`에만. 모든 task에 회귀 테스트 명령 포함.
- **시각 검증**: Task 9 Step 4는 사용자 수동 확인 단계. subagent로 자동화 불가능.
- **Windows 인코딩**: pipeline 실행 시 `PYTHONIOENCODING=utf-8` 환경변수 필수 (한글 출력 cp949 에러 방지).
