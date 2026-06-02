# Archive Navigation Hide — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 모든 사용자 진입 페이지의 사이드바/상단 nav에서 Archive 링크를 제거. `_generate_archive()` 함수와 `deploy/archive.html` 페이지는 유지.

**Architecture:** 7개 파일에서 archive.html을 참조하는 `<a>` 요소를 정확히 삭제. `_sidebar.html`이 공통 partial이라 6+ 페이지 영향을 한 번에 처리. backend / generate_site / 모든 history/state 무영향.

**Tech Stack:** HTML/Jinja2 템플릿 수정 only, 코드 변경 없음.

**Spec:** [docs/superpowers/specs/2026-05-27-archive-nav-hide-design.md](../specs/2026-05-27-archive-nav-hide-design.md)

---

## File Structure

**Modify:**
- `templates/_sidebar.html` — Archive 링크 (L56-58, 3줄) 제거
- `templates/backtest_template.html` — Archive 사이드바 (L56) 제거
- `templates/trend_template.html` — Archive 사이드바 (L54) 제거
- `templates/scanner_unified_template.html` — Archive 사이드바 (L72-74) 제거
- `templates/scanner_template.html` — `📁 아카이브` 버튼 (L90) 제거
- `templates/detail_template.html` — Archive nav 링크 (L165) 제거
- `tests/test_no_archive_nav.py` (신규) — regression guard

**Out of scope (변경 없음):**
- `generate_site.py::_generate_archive()` — 유지
- `generate_site.py:110` 호출 — 유지
- `deploy/archive.html` 파일 — 다음 deploy에서도 생성
- `detail_template`의 `nav_archive` ctx 변수 — defensive 유지
- 모든 backend / signal / scanner / lifecycle 로직

---

## Task 1: regression guard test 작성 (TDD)

**Files:**
- Create: `tests/test_no_archive_nav.py`

각 template을 렌더하거나 raw로 읽어 `archive.html` 링크가 없음을 확인하는 단순 grep-style assertion.

- [ ] **Step 1: Create failing test**

Create `tests/test_no_archive_nav.py`:

```python
"""Regression guard — Archive nav links must remain removed from user-facing templates.

Spec: docs/superpowers/specs/2026-05-27-archive-nav-hide-design.md
"""
import os
import pytest

PROJECT_DIR = os.path.join(os.path.dirname(__file__), "..")
TEMPLATES_DIR = os.path.join(PROJECT_DIR, "templates")


# Templates that user-facing pages render or include. Each must NOT
# reference archive.html in a clickable nav element.
USER_FACING_TEMPLATES = [
    "_sidebar.html",
    "backtest_template.html",
    "trend_template.html",
    "scanner_unified_template.html",
    "scanner_template.html",
    "detail_template.html",
]


@pytest.mark.parametrize("template_name", USER_FACING_TEMPLATES)
def test_template_has_no_archive_nav_link(template_name):
    """User-facing templates must not contain an <a href="archive.html"> or similar."""
    path = os.path.join(TEMPLATES_DIR, template_name)
    with open(path, encoding="utf-8") as f:
        content = f.read()
    # Allow occurrences in comments / CSS / JS only — but href="archive.html"
    # or Archive>...</...> entries should be gone.
    assert 'href="archive.html"' not in content, (
        f"{template_name}: archive.html link still present"
    )
    # Korean button in scanner_template.html
    assert "📁 아카이브" not in content, (
        f"{template_name}: 📁 아카이브 button still present"
    )
    # nav_archive ctx default fallback (Pattern C in detail_template.html)
    assert "nav_archive|default('../archive.html')" not in content, (
        f"{template_name}: nav_archive default fallback still present"
    )
```

- [ ] **Step 2: Run test to verify FAIL**

```
python -m pytest tests/test_no_archive_nav.py -xvs
```

Expected: 6 tests FAIL (archive.html links currently present in all 6 templates).

- [ ] **Step 3: No commit yet — tests should fail before implementation.**

---

## Task 2: `_sidebar.html` Archive 링크 제거

**Files:**
- Modify: `templates/_sidebar.html`

공통 사이드바 partial — lifecycle_us/kr, momentum_us/kr, portfolio_stops 등 다수 페이지가 include. 한 번 수정으로 6+ 페이지 동시 효과.

- [ ] **Step 1: Find exact block**

```
grep -n "archive" templates/_sidebar.html
```

Expected: lines 56-58 with the Archive `<a>` block.

- [ ] **Step 2: Read context (L52-62) to verify exact match**

Read `templates/_sidebar.html` lines 52-62 to confirm the structure:

```html
    <a class="flex items-center gap-3 px-4 py-3 text-slate-400 hover:bg-white/10 hover:text-white transition-all" href="archive.html">
      <span class="material-symbols-outlined">inventory_2</span><span>Archive</span>
    </a>
```

- [ ] **Step 3: Remove the Archive block**

Use Edit to remove the entire 3-line block. Old string (verbatim from file, preserve indentation):

```html
    <a class="flex items-center gap-3 px-4 py-3 text-slate-400 hover:bg-white/10 hover:text-white transition-all" href="archive.html">
      <span class="material-symbols-outlined">inventory_2</span><span>Archive</span>
    </a>
```

New string: (empty — remove the lines entirely)

Note: also remove any trailing blank line if it leaves a double-blank gap.

- [ ] **Step 4: Verify with test**

```
python -m pytest tests/test_no_archive_nav.py::test_template_has_no_archive_nav_link -xvs -k _sidebar
```

Expected: the `_sidebar.html` parametrized case PASS.

- [ ] **Step 5: Commit**

```
git add templates/_sidebar.html tests/test_no_archive_nav.py
git commit -m "feat(nav): remove Archive link from _sidebar partial"
```

---

## Task 3: `backtest_template.html` + `trend_template.html` 사이드바 Archive 제거

**Files:**
- Modify: `templates/backtest_template.html`
- Modify: `templates/trend_template.html`

두 파일 모두 동일 패턴 — 단일 라인 사이드바 `<a>` 요소.

- [ ] **Step 1: Verify positions**

```
grep -n "archive" templates/backtest_template.html templates/trend_template.html
```

Expected:
- `backtest_template.html:56`
- `trend_template.html:54`

- [ ] **Step 2: Read full line for `backtest_template.html`**

Read `templates/backtest_template.html` around L52-60 to capture the exact line including leading whitespace.

- [ ] **Step 3: Remove from `backtest_template.html`**

Use Edit. The exact line (verify by Read first):

```html
    <a class="flex items-center gap-3 px-4 py-3 text-slate-400 hover:bg-white/10 hover:text-white transition-all" href="archive.html"><span class="material-symbols-outlined">inventory_2</span><span>Archive</span></a>
```

Replace with empty string (delete the entire line).

- [ ] **Step 4: Repeat for `trend_template.html`**

Same pattern — Read L50-58, then Edit to remove L54.

- [ ] **Step 5: Verify with test**

```
python -m pytest tests/test_no_archive_nav.py -xvs -k "backtest or trend"
```

Expected: 2 parametrized cases (backtest_template, trend_template) PASS.

- [ ] **Step 6: Commit**

```
git add templates/backtest_template.html templates/trend_template.html
git commit -m "feat(nav): remove Archive link from backtest + trend templates"
```

---

## Task 4: `scanner_unified_template.html` 사이드바 Archive 제거

**Files:**
- Modify: `templates/scanner_unified_template.html`

3줄 다중 라인 패턴 (`_sidebar.html`와 동일 구조).

- [ ] **Step 1: Verify**

```
grep -n "archive" templates/scanner_unified_template.html
```

Expected: L72-74.

- [ ] **Step 2: Read L68-78 context**

확인된 블록 구조 (Read로 정확한 indentation 캡처):

```html
    <a class="flex items-center gap-3 px-4 py-3 text-slate-400 hover:bg-white/10 hover:text-white transition-all" href="archive.html">
      <span class="material-symbols-outlined">inventory_2</span><span>Archive</span>
    </a>
```

- [ ] **Step 3: Remove 3-line block**

Use Edit to delete the entire `<a>...archive.html...</a>` block, preserving surrounding whitespace.

- [ ] **Step 4: Verify**

```
python -m pytest tests/test_no_archive_nav.py -xvs -k scanner_unified
```

Expected: parametrized case PASS.

- [ ] **Step 5: Commit**

```
git add templates/scanner_unified_template.html
git commit -m "feat(nav): remove Archive link from scanner_unified template"
```

---

## Task 5: `scanner_template.html` 한글 아카이브 버튼 제거

**Files:**
- Modify: `templates/scanner_template.html`

상단 nav 영역의 한글 텍스트 버튼 — 다른 사이드바 패턴과 다른 별도 처리.

- [ ] **Step 1: Verify**

```
grep -n "아카이브\|archive" templates/scanner_template.html
```

Expected: L90 with `📁 아카이브` button.

- [ ] **Step 2: Read context L85-95**

확인된 라인:

```html
    <a href="archive.html" style="background:#64748b;">📁 아카이브</a>
```

- [ ] **Step 3: Remove the entire button line**

Use Edit to delete L90 entirely. Make sure surrounding sibling buttons (e.g., 다른 nav 항목들) 정렬 유지 — 단순 라인 제거이므로 들여쓰기 영향 없음.

- [ ] **Step 4: Verify**

```
python -m pytest tests/test_no_archive_nav.py -xvs -k scanner_template
```

Expected: PASS.

- [ ] **Step 5: Commit**

```
git add templates/scanner_template.html
git commit -m "feat(nav): remove 아카이브 button from scanner_template"
```

---

## Task 6: `detail_template.html` Archive nav 링크 제거

**Files:**
- Modify: `templates/detail_template.html`

상단 nav 링크 with `nav_archive` ctx fallback. ctx 변수 자체는 유지 (다른 곳에서 참조해도 KeyError 방지).

- [ ] **Step 1: Verify**

```
grep -n "archive\|nav_archive" templates/detail_template.html
```

Expected: L165 with the Archive `<a>` link.

- [ ] **Step 2: Read L160-170 context**

확인된 라인:

```html
    <a href="{{ nav_archive|default('../archive.html') }}" style="color:var(--text-dim);text-decoration:none;padding:4px 10px;border-radius:6px;">Archive</a>
```

- [ ] **Step 3: Remove the entire `<a>` line**

Use Edit to delete L165 entirely.

- [ ] **Step 4: Verify**

```
python -m pytest tests/test_no_archive_nav.py -xvs -k detail_template
```

Expected: PASS.

- [ ] **Step 5: Run full regression suite**

```
python -m pytest tests/test_no_archive_nav.py tests/test_lifecycle_buy_candidates.py tests/test_lifecycle_report.py tests/test_lifecycle_golden.py tests/test_generate_site_lifecycle.py -x
```

Expected: All pass. golden snapshot에 사이드바가 포함된 경우 diff 발생 가능 — KR/US lifecycle golden을 새 사이드바 (Archive 없음) 출력으로 업데이트.

- [ ] **Step 6: Commit**

```
git add templates/detail_template.html
git commit -m "feat(nav): remove Archive link from detail_template"
```

---

## Task 7: Smoke pipeline run + 시각 확인

**Files:** 없음 (검증만)

실데이터로 렌더링 후 모든 사용자 진입 페이지에 Archive 링크가 없음을 확인.

- [ ] **Step 1: Run pipeline**

```
python pipeline.py 2>&1 | tail -30
```

Expected: 깨끗한 종료, lifecycle/momentum/scanner 모든 페이지 정상 생성.

- [ ] **Step 2: Grep all generated user-facing pages for archive links**

```
grep -l "archive.html" reports/lifecycle_*.html reports/momentum_*.html reports/portfolio_stops_*.html reports/report_2026*.html reports/scanner_*.html reports/trend_*.html reports/backtest_*.html 2>&1 | head
```

Expected: 빈 결과 (또는 detail_template만 제외하고 archive 링크 없음).

```
grep "archive.html\|아카이브\|>Archive<" reports/lifecycle_kr_*.html | head
```

Expected: 매치 없음.

- [ ] **Step 3: Verify `deploy/archive.html` still generated**

```
python generate_site.py 2>&1 | tail -5
ls -la deploy/archive.html
```

Expected: `archive.html generated (N entries)` log + 파일 존재.

- [ ] **Step 4: No commit (검증만)**

---

## Task 8: `CLAUDE.md` plans list 갱신

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Append plan entry**

`CLAUDE.md`의 "진행 중인 계획" 리스트 마지막에 추가:

```markdown
- [Archive Navigation Hide](docs/superpowers/plans/2026-05-27-archive-nav-hide.md) — 6개 template (`_sidebar.html` partial 포함)에서 Archive nav 링크 제거 · `_generate_archive()` 함수 + `deploy/archive.html` 페이지는 유지 (URL 직접 접근 가능) · `detail_template`의 `nav_archive` ctx 변수 유지 (defensive) · 모든 백엔드/시그널 무영향
```

- [ ] **Step 2: Commit**

```
git add CLAUDE.md
git commit -m "docs(claude): add archive nav hide plan to in-progress list"
```

---

## Final verification

- [ ] **Full test suite**

```
python -m pytest tests/test_no_archive_nav.py tests/test_lifecycle_buy_candidates.py tests/test_lifecycle_signal.py tests/test_lifecycle_history.py tests/test_lifecycle_report.py tests/test_lifecycle_golden.py tests/test_lifecycle_e2e.py tests/test_generate_site_lifecycle.py -x
```

Expected: All PASS (~250 tests).

- [ ] **Pipeline + 시각 확인**

```
python pipeline.py
```

Open `reports/lifecycle_kr_2026-05-29.html` and `reports/report_2026-05-29.html` 브라우저로 — Archive 항목이 사이드바에 없는지 확인.

- [ ] **Push to master**

Standard flow.

---

## Self-review notes (for the executing engineer)

- **Reversibility:** 모든 변경이 nav `<a>` 요소 1-3줄 삭제만. 되돌리기는 단순 복원. `_generate_archive()` 그대로 유지.
- **Test design:** 단순 grep-style assertion이라 충분 — 복잡한 Jinja2 렌더링 mock 불필요.
- **`_sidebar.html` partial 영향:** lifecycle_us/kr, momentum_us/kr, portfolio_stops, report_template 등이 include — Task 2 하나로 동시 적용.
- **detail_template ctx 변수:** `nav_archive`를 ctx에 넣는 코드는 그대로 유지 (defensive). 다른 코드에서 참조해도 KeyError 없음.
- **Golden snapshot:** lifecycle_golden은 KR/US 페이지 HTML을 snapshot으로 잡고 있을 가능성. Archive 줄 삭제로 diff 발생하면 fixture 업데이트 — diff가 사이드바 1줄 제거만 보여주는지 검증 후 fixture 교체.
- **Direct URL access:** `https://freecjs77-tech.github.io/AI-Trading-Assistant-v2/archive.html` 여전히 작동. 사용자가 즐겨찾기 등으로 직접 접근 가능.
- **Pipeline regression risk:** backend는 무변경. Smoke run은 안전.
