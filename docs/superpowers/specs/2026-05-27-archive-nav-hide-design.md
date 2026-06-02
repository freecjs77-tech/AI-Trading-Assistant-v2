# Archive Navigation — Hide Sidebar Links (Page Preserved)

**Date:** 2026-05-27
**Status:** Approved
**Scope:** Navigation visibility cleanup only — Archive 페이지 자체는 유지.

---

## Goal

모든 사용자 진입 페이지의 사이드바/상단 nav에서 "Archive" 링크 제거. `deploy/archive.html` 파일과 `_generate_archive()` 함수는 그대로 유지하여 URL 직접 입력 시에는 접근 가능 (안전한 되돌리기 보장).

## Rationale

- 사용자가 더 이상 navigation에서 Archive를 노출하지 않기로 결정
- 페이지 자체는 유지 — 향후 다시 필요해질 때 사이드바 링크만 복구하면 되돌릴 수 있음
- 데이터/로직 의존 없음 — Archive는 단순 날짜 인덱스라 다른 페이지에 영향 없음

## Affected Files (7개)

| 파일 | 라인 | 형태 |
|------|------|------|
| `templates/_sidebar.html` | 56-58 | 공통 사이드바 `<a href="archive.html">...Archive</a>` (3줄 다중 라인) |
| `templates/backtest_template.html` | 56 | 사이드바 (단일 라인) |
| `templates/trend_template.html` | 54 | 사이드바 (단일 라인) |
| `templates/scanner_unified_template.html` | 72-74 | 사이드바 (3줄 다중 라인) |
| `templates/scanner_template.html` | 90 | 상단 버튼 nav `📁 아카이브` |
| `templates/detail_template.html` | 165 | 상단 nav 링크 `nav_archive\|default('../archive.html')` |

`_sidebar.html`는 lifecycle_us/kr, momentum_us/kr, portfolio_stops, report_template 등이 `{% include "_sidebar.html" %}`로 import — 한 곳 수정으로 6+ 페이지의 사이드바가 동기화됨.

## Out of Scope (이번 PR 변경 없음)

- `generate_site.py::_generate_archive()` 함수 — 유지
- `generate_site.py:110`의 `_generate_archive()` 호출 — 유지 (deploy 시 여전히 archive.html 생성)
- `deploy/archive.html` 파일 — 다음 deploy에서도 생성됨, URL 직접 접근 가능
- `detail_template.html` ctx의 `nav_archive` 변수 정의/사용 — 사이드바 링크가 제거되어도 다른 코드 깨지지 않도록 ctx 자체는 유지 (defensive)
- 모든 백엔드 로직 / signal / scanner / lifecycle 무영향

## Design Decisions

### Decision 1 — 완전 삭제가 아닌 nav 숨김
사용자 명시. 안전한 되돌리기 + Archive 페이지의 일회성 직접 접근 가능성 유지.

### Decision 2 — `_sidebar.html` 우선
공통 사이드바이므로 여기 1줄 제거하면 7개 페이지(lifecycle/portfolio_stops/momentum 등)가 동시에 영향 받음 — DRY.

### Decision 3 — `detail_template.html`의 `nav_archive` ctx 변수 보존
사이드바 링크는 제거하되 ctx 변수는 유지. 다른 곳에서 `nav_archive`를 참조해도 KeyError 없음 (defensive).

### Decision 4 — `scanner_template.html`의 한글 버튼 "📁 아카이브"도 제거
"Archive" 영문이 아닌 한글 표기지만 같은 navigation 의도 — 함께 제거.

## Component Changes

각 template의 `<a ... archive.html ...>` 블록을 통째로 제거.

**Pattern A — 단일 라인 (`backtest_template.html`, `trend_template.html`, `scanner_template.html`):**

```html
<!-- 제거 대상 -->
<a class="..." href="archive.html"><span ...>inventory_2</span><span>Archive</span></a>
```

**Pattern B — 다중 라인 (`_sidebar.html`, `scanner_unified_template.html`):**

```html
<!-- 제거 대상 -->
<a class="..." href="archive.html">
  <span class="material-symbols-outlined">inventory_2</span><span>Archive</span>
</a>
```

**Pattern C — `detail_template.html` 상단 nav 링크:**

```html
<!-- 제거 대상 -->
<a href="{{ nav_archive|default('../archive.html') }}" style="...">Archive</a>
```

각 파일에서 해당 줄을 정확히 매치해 삭제하되, 주변 공백/들여쓰기는 보존.

## Tests

직접적인 navigation test는 없으나 golden HTML snapshot 테스트가 사이드바를 포함할 수 있음. Verification:

1. `tests/test_lifecycle_golden.py` — lifecycle 페이지 출력 snapshot 검증. KR/US 페이지가 `{% include "_sidebar.html" %}`을 사용 — 사이드바 변경이 snapshot diff을 유발하면 fixture 업데이트 필요.
2. `tests/test_generate_site_lifecycle.py` — generate_site flow 검증. _generate_archive()는 유지되므로 영향 없음.
3. 신규 테스트 — 각 template 렌더링 시 `'archive.html'` 문자열이 더 이상 출현하지 않음을 단순 assertion으로 검증 (regression guard).

## Risks & Mitigations

| 리스크 | 완화 |
|--------|------|
| `_sidebar.html`를 include하는 페이지 다수 → 광범위 영향 | DRY 변경이므로 의도된 효과. golden 테스트가 안전망. |
| `detail_template.html`의 nav_archive ctx 누락 시 다른 코드 깨질 가능성 | ctx 변수는 유지 — 사이드바 마크업만 제거하므로 KeyError 없음 |
| `deploy/archive.html`이 여전히 생성됨 → 혼란? | 의도된 동작 — direct URL fallback. `_generate_archive()` 호출은 그대로 둠 |
| Scanner 상단 한글 "📁 아카이브" 버튼 제거 시 다른 페이지 정렬 깨짐 | scanner_template.html 단일 줄 제거, 상위 컨테이너 정렬 그대로 |

## Success Criteria

- 모든 사용자 진입 페이지(report/lifecycle_us/lifecycle_kr/momentum_us/momentum_kr/scanner/backtest/trend/portfolio_stops/detail)의 navigation에 "Archive" 텍스트나 archive.html 링크가 더 이상 노출되지 않음
- `deploy/archive.html`은 여전히 생성됨 (다음 pipeline run 후 URL 직접 입력 시 접근 가능)
- 모든 기존 테스트 PASS (golden snapshot이 깨지면 fixture 업데이트로 처리)
- US/KR lifecycle, momentum, portfolio_stops, scanner, trend, backtest 페이지 모두 정상 렌더링 (브라우저 시각 확인)
