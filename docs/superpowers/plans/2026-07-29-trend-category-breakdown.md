# Trend Page 카테고리 구성 (도넛 + 카드) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 트렌드 페이지 기존 Asset Allocation(종목별 도넛+카드) 바로 아래에, 현재 포트폴리오를 4개 카테고리(지수/배당주/개별주/현금)로 묶어 보여주는 도넛+카드 섹션을 추가한다. owner 토글 연동.

**Architecture:** 분류기(`portfolio_data.py`)가 ticker→카테고리 단일 진실의 원천. `report_generator.py`가 각 owner 최신 스냅샷의 `weights_by_ticker`를 카테고리별로 집계해 payload에 주입 — 합산은 `_build_combined_payload`가 `_build_owner_payload`를 재호출하므로 자동 처리(KRW 합산 후 % 재계산). 템플릿은 기존 `tickerPie` 도넛 패턴을 복제해 `categoryPie`를 렌더하고 owner 토글 시 재렌더. 백엔드 스냅샷 스키마·히스토리 무변경.

**Tech Stack:** Python 3.10+, Jinja2, Chart.js 4.x, pytest, 브라우저 프리뷰.

**참고 스펙:** `docs/superpowers/specs/2026-07-29-trend-category-breakdown-design.md`

---

## File Structure

**Create:**
- `tests/test_ticker_category.py` — 분류기 단위 테스트
- `tests/test_category_breakdown.py` — 집계 + 렌더 스모크 테스트

**Modify:**
- `portfolio_data.py` — `USER_CATEGORY_MAP`, `USER_CATEGORIES`, `_NAME_TO_TICKER`, `get_ticker_category()`, `category_for_weight_key()` 추가
- `report_generator.py` — `_user_category_rows()` 헬퍼 + `_build_owner_payload` 반환에 `category` + context에 `user_category_json`
- `templates/trend_template.html` — 카테고리 섹션 markup + JS(`categoryPie`/`_renderCategory`) + `_applyOwner` 훅

**무변경:** `pipeline.py`, `fetch_market_data.py`, 히스토리/데이터 JSON, 스냅샷 스키마.

---

## Task 1: 분류기 (`portfolio_data.py`)

**Files:**
- Create: `tests/test_ticker_category.py`
- Modify: `portfolio_data.py` (TICKER_META 정의 직후, 현재 line 73 `}` 다음에 삽입)

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_ticker_category.py`:

```python
"""Tests for portfolio_data user-category classifier."""
from __future__ import annotations

from portfolio_data import (
    USER_CATEGORIES,
    get_ticker_category,
    category_for_weight_key,
)


def test_user_categories_fixed_order():
    assert USER_CATEGORIES == ["지수", "배당주", "개별주", "현금"]


def test_index_tickers():
    for t in ["VOO", "SPY", "QQQ", "QLD", "102110", "069500", "232080", "229200"]:
        assert get_ticker_category(t) == "지수", t


def test_dividend_tickers():
    for t in ["SCHD", "JEPI", "O", "458730", "446720", "0153K0"]:
        assert get_ticker_category(t) == "배당주", t


def test_cash_ticker():
    assert get_ticker_category("BIL") == "현금"


def test_individual_and_default():
    # 개별주 (명시 성격) + 미분류 기본값
    for t in ["AAPL", "005930", "110990", "SOXL", "SOXX", "TLT", "396500", "UNKNOWN123"]:
        assert get_ticker_category(t) == "개별주", t


def test_qld_index_soxl_individual():
    assert get_ticker_category("QLD") == "지수"
    assert get_ticker_category("SOXL") == "개별주"


def test_category_for_weight_key_resolves_korean_name():
    # me 스냅샷은 KOSPI를 한글명으로 저장 → 이름 해소 필요
    assert category_for_weight_key("삼성전자") == "개별주"
    assert category_for_weight_key("디아이티") == "개별주"
    assert category_for_weight_key("TIGER 200") == "지수"
    # wife 스냅샷은 티커코드로 저장
    assert category_for_weight_key("069500") == "지수"
    assert category_for_weight_key("005935") == "개별주"
    # US는 티커 그대로
    assert category_for_weight_key("SCHD") == "배당주"
    assert category_for_weight_key("BIL") == "현금"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_ticker_category.py -v`
Expected: ImportError (USER_CATEGORIES 등 없음) → 전부 FAIL.

- [ ] **Step 3: 분류기 구현**

`portfolio_data.py`에서 `TICKER_META = { ... }` 딕셔너리가 닫히는 `}` (현재 line 73) **바로 다음 줄**에 삽입:

```python

# ── 사용자 카테고리 분류 (지수/배당주/개별주/현금) ──────
# 명시적으로 매핑되지 않은 티커는 기본값 '개별주'.
USER_CATEGORIES = ["지수", "배당주", "개별주", "현금"]  # 고정 표시 순서

USER_CATEGORY_MAP = {
    # 지수 (S&P/나스닥/코스피/코스닥 추종 ETF; QLD=2x 나스닥100)
    "VOO": "지수", "SPY": "지수", "QQQ": "지수", "QLD": "지수",
    "102110": "지수", "069500": "지수",
    "379800": "지수", "360750": "지수",
    "379810": "지수", "133690": "지수",
    "232080": "지수", "229200": "지수",
    # 배당주 (배당 ETF + 배당 성격 개별주)
    "SCHD": "배당주", "JEPI": "배당주", "O": "배당주",
    "458730": "배당주", "446720": "배당주", "0153K0": "배당주",
    # 현금
    "BIL": "현금",
}

# weights_by_ticker 키가 한글 표시명(me 스냅샷)일 때 티커로 역해소
_NAME_TO_TICKER = {meta["name"]: t for t, meta in TICKER_META.items()}


def get_ticker_category(ticker: str) -> str:
    """티커 → 4개 사용자 카테고리. 미분류는 '개별주'."""
    return USER_CATEGORY_MAP.get(ticker, "개별주")


def category_for_weight_key(key: str) -> str:
    """weights_by_ticker 키(티커코드 또는 한글 표시명)를 카테고리로 해소."""
    ticker = key if key in USER_CATEGORY_MAP else _NAME_TO_TICKER.get(key, key)
    return get_ticker_category(ticker)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_ticker_category.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add portfolio_data.py tests/test_ticker_category.py
git commit -m "feat(portfolio-data): add user-category classifier (지수/배당주/개별주/현금)

USER_CATEGORY_MAP + get_ticker_category (default 개별주) + category_for_weight_key
which resolves both ticker codes and Korean display names (me snapshots key
KOSPI by name, wife by code). QLD→지수, SOXL→개별주.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 집계 헬퍼 + payload/context 주입 (`report_generator.py`)

**Files:**
- Create: `tests/test_category_breakdown.py`
- Modify: `report_generator.py` (`_build_owner_payload` 반환 line 738 / context line 957·973 부근)

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_category_breakdown.py`:

```python
"""Tests for report_generator user-category breakdown aggregation."""
from __future__ import annotations

import json
import os

from portfolio_data import USER_CATEGORIES
from report_generator import (
    _user_category_rows,
    _build_owner_payload,
    _build_combined_payload,
)

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _latest(daily: dict) -> dict:
    return daily[max(k for k in daily if not k.startswith("_"))]


def _load(name: str) -> dict:
    p = os.path.join(PROJECT_DIR, "history", name)
    return json.load(open(p, encoding="utf-8"))


def test_rows_shape_and_order():
    me = _load("portfolio_daily.json")
    rows = _user_category_rows(_latest(me))
    assert [r["name"] for r in rows] == USER_CATEGORIES
    for r in rows:
        assert set(r.keys()) == {"name", "value", "amount_man"}
    # 비중 합 ≈ 100
    assert 99.0 <= sum(r["value"] for r in rows) <= 101.0


def test_amount_matches_total():
    me = _load("portfolio_daily.json")
    snap = _latest(me)
    rows = _user_category_rows(snap)
    total_man = round((snap.get("total_value_krw", 0) or 0) / 1e4)
    assert abs(sum(r["amount_man"] for r in rows) - total_man) <= 4


def test_owner_payload_includes_category():
    me = _load("portfolio_daily.json")
    payload = _build_owner_payload(me)
    assert "category" in payload
    assert [r["name"] for r in payload["category"]] == USER_CATEGORIES


def test_combined_is_krw_sum_of_owners():
    me = _load("portfolio_daily.json")
    wife = _load("portfolio_daily_wife.json")
    me_rows = _user_category_rows(_latest(me))
    wife_rows = _user_category_rows(_latest(wife))
    comb = _build_combined_payload(me, {"wife": wife})["category"]

    def man(rows, cat):
        return next(r["amount_man"] for r in rows if r["name"] == cat)

    for cat in USER_CATEGORIES:
        assert abs(man(comb, cat) - (man(me_rows, cat) + man(wife_rows, cat))) <= 3
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_category_breakdown.py -v`
Expected: ImportError (`_user_category_rows` 없음) → 전부 FAIL.

- [ ] **Step 3: `_user_category_rows` 헬퍼 추가**

`report_generator.py`에서 `_build_owner_payload` 함수 정의(현재 line 701 `def _build_owner_payload`) **바로 앞**에 삽입:

```python
def _user_category_rows(snap: dict) -> list[dict]:
    """최신 스냅샷 weights_by_ticker → 4 사용자 카테고리 rows (고정 순서).

    반환 shape은 ticker rows와 동일: {name, value(pct), amount_man}.
    합산 스냅샷도 weights_by_ticker(KRW 합산 후 %)를 담으므로 동일 경로로 처리된다.
    """
    from portfolio_data import USER_CATEGORIES, category_for_weight_key
    total = snap.get("total_value_krw", 0) or 0
    krw = {c: 0.0 for c in USER_CATEGORIES}
    for key, w in (snap.get("weights_by_ticker") or {}).items():
        krw[category_for_weight_key(key)] += total * w / 100.0
    g = sum(krw.values()) or 1
    return [
        {"name": c, "value": round(krw[c] / g * 100, 1), "amount_man": round(krw[c] / 1e4)}
        for c in USER_CATEGORIES
    ]


```

- [ ] **Step 4: `_build_owner_payload` 반환에 `category` 추가**

`report_generator.py` 현재 line 738:

```python
    return {"latest": latest, "trend": _series_from_daily(daily), "ticker": ticker_data}
```

를 다음으로 교체:

```python
    return {
        "latest": latest,
        "trend": _series_from_daily(daily),
        "ticker": ticker_data,
        "category": _user_category_rows(latest_snap),
    }
```

- [ ] **Step 5: context에 `user_category_json` 추가**

`report_generator.py` 의 `generate_trend_page` 안, ticker_data 블록이 끝나는 지점(현재 line 957 `ticker_data.append({"name": "기타", ...})` 를 닫는 `if others > 0:` 블록 직후, `context = {` (현재 line 959) **앞**)에 삽입:

```python
    user_category_data = _user_category_rows(latest_snap)

```

그리고 context dict 안 `"ticker_json": _json.dumps(ticker_data, ensure_ascii=False),` (현재 line 974) **다음 줄**에 추가:

```python
        "user_category_json": _json.dumps(user_category_data, ensure_ascii=False),
```

- [ ] **Step 6: 통과 + 회귀 확인**

Run: `python -m pytest tests/test_category_breakdown.py tests/test_ticker_category.py -v`
Expected: 모두 PASS.

Run: `python -m pytest -q`
Expected: 전체 PASS (회귀 없음).

- [ ] **Step 7: Commit**

```bash
git add report_generator.py tests/test_category_breakdown.py
git commit -m "feat(report): inject user-category breakdown into trend payload

_user_category_rows aggregates latest snapshot weights_by_ticker into
지수/배당주/개별주/현금 (same {name,value,amount_man} shape as ticker rows).
Added to _build_owner_payload so me/wife/combined all get it (combined routes
through _build_owner_payload → KRW-summed weights → correct % recompute).
Context gains user_category_json for initial render.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: 템플릿 섹션 + JS (`templates/trend_template.html`)

**Files:**
- Modify: `templates/trend_template.html` (Asset Allocation 카드 직후 markup / `_applyOwner` 훅 / tickerPie JS 직후)
- Modify: `tests/test_category_breakdown.py` (렌더 스모크 추가)

- [ ] **Step 1: 렌더 스모크 테스트 추가 (실패)**

`tests/test_category_breakdown.py` 끝에 다음 함수 추가:

```python
def test_category_section_rendered_multi_owner():
    import tempfile
    from report_generator import generate_trend_page
    me = _load("portfolio_daily.json")
    wife = _load("portfolio_daily_wife.json")
    with tempfile.TemporaryDirectory() as d:
        path = generate_trend_page(me, d, owner_daily={"wife": wife}, date_str="2026-07-29")
        html = open(path, encoding="utf-8").read()
    assert 'id="categoryPie"' in html
    assert 'id="categoryCards"' in html
    assert "_renderCategory" in html
    assert "_renderCategory(p.category)" in html
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_category_breakdown.py::test_category_section_rendered_multi_owner -v`
Expected: FAIL (categoryPie 등 아직 없음).

- [ ] **Step 3: 카테고리 섹션 markup 추가**

`templates/trend_template.html` 의 Asset Allocation 카드를 닫는 `</div>` (현재 line 158 — `<!-- Asset Allocation -->` 블록의 마지막 `</div>`) **다음 줄**, `{% if data_days >= 1 %}` (현재 line 160) **앞**에 삽입:

```html

    <!-- Category Breakdown -->
    <div class="rounded-xl bg-surface-container p-6 border border-outline-variant/10">
      <h2 class="text-lg font-headline font-bold mb-6">카테고리 구성</h2>
      <div class="flex flex-col lg:flex-row items-center gap-8">
        <div class="relative" style="width:260px;height:260px;flex-shrink:0;">
          <canvas id="categoryPie"></canvas>
          <div class="absolute inset-0 flex flex-col items-center justify-center pointer-events-none" id="catPieCenter"></div>
        </div>
        <div class="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-3 w-full" id="categoryCards"></div>
      </div>
    </div>
```

- [ ] **Step 4: `_applyOwner`에 카테고리 재렌더 훅 추가**

`templates/trend_template.html` 현재 line 307 `  _renderTicker(p.ticker);` **다음 줄**에 추가:

```javascript
  _renderCategory(p.category);
```

- [ ] **Step 5: 카테고리 도넛+카드 JS 추가**

`templates/trend_template.html` 현재 line 470 `_renderTicker(tickerData);` **다음 줄**, `</script>` (현재 line 471) **앞**에 삽입:

```javascript
const categoryData = {{ user_category_json }};
const catColors = {'지수':'#6dddff','배당주':'#ff716c','개별주':'#00E5BC','현금':'#fbbf24'};
const catSub = {'지수':'S&P·나스닥·코스피·코스닥','배당주':'SCHD·리얼티인컴·배당ETF','개별주':'디아이티·삼성전자·AAPL','현금':'BIL'};
let _catCurrent = categoryData;
let _categoryPie = new Chart(document.getElementById('categoryPie'), { type:'doughnut', data:{ labels:[], datasets:[{ data:[], backgroundColor:[], borderWidth:0, spacing:2 }]}, options:{ responsive:true, cutout:'72%', plugins:{ legend:{ display:false }, tooltip:{ callbacks:{ label:function(c){ var shown=_catCurrent.filter(function(x){return x.value>0;}); var d=shown[c.dataIndex],a=d.amount_man,s=a>=10000?'₩'+(a/10000).toFixed(1)+'억':'₩'+a.toLocaleString()+'만'; return d.name+': '+c.parsed.toFixed(1)+'% ('+s+')'; }}}}}});
function _renderCategory(data){
  _catCurrent = data;
  var shown = data.filter(function(d){return d.value>0;});
  _categoryPie.data.labels = shown.map(function(d){return d.name;});
  _categoryPie.data.datasets[0].data = shown.map(function(d){return d.value;});
  _categoryPie.data.datasets[0].backgroundColor = shown.map(function(d){return catColors[d.name];});
  _categoryPie.update();
  var top = data.slice().sort(function(a,b){return b.value-a.value;})[0];
  if(top){ document.getElementById('catPieCenter').innerHTML='<span class="text-[10px] font-label text-on-surface-variant uppercase tracking-widest">'+top.name+'</span><span class="text-3xl font-headline font-bold text-on-surface">'+Math.round(top.value)+'%</span>'; } else { document.getElementById('catPieCenter').innerHTML=''; }
  var cardsHtml='';
  data.forEach(function(d){var a=d.amount_man,s=a>=10000?'₩'+(a/10000).toFixed(1)+'억':'₩'+a.toLocaleString()+'만';var c=catColors[d.name];cardsHtml+='<div class="rounded-lg bg-surface-container-high p-4" style="border-left:4px solid '+c+'"><div class="flex justify-between items-center gap-2"><div class="min-w-0"><div class="font-bold text-sm text-on-surface">'+d.name+'</div><div class="text-[10px] text-outline truncate">'+catSub[d.name]+'</div></div><div class="text-right flex-shrink-0"><div class="font-bold text-sm text-on-surface">'+s+'</div><div class="text-[10px] text-outline">'+d.value.toFixed(1)+'%</div></div></div></div>';});
  document.getElementById('categoryCards').innerHTML=cardsHtml;
}
_renderCategory(categoryData);
```

- [ ] **Step 6: 통과 + 회귀 확인**

Run: `python -m pytest tests/test_category_breakdown.py -v`
Expected: 렌더 스모크 포함 전부 PASS.

Run: `python -m pytest -q`
Expected: 전체 PASS.

- [ ] **Step 7: Commit**

```bash
git add templates/trend_template.html tests/test_category_breakdown.py
git commit -m "feat(trend): add category breakdown donut+cards below Asset Allocation

Second doughnut (categoryPie) mirroring the tickerPie pattern: 지수/배당주/
개별주/현금 with fixed color-by-name, 0-value categories skipped in the donut
but shown as cards. Re-renders on owner toggle via _applyOwner(p.category).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 브라우저 프리뷰 검증

**Files:** 실행/검증만 (문제 발견 시 Task 1~3으로 회귀).

- [ ] **Step 1: 실제 데이터로 트렌드 HTML 재생성**

Run:
```bash
python -c "import json; from report_generator import generate_trend_page; me=json.load(open('history/portfolio_daily.json',encoding='utf-8')); wife=json.load(open('history/portfolio_daily_wife.json',encoding='utf-8')); print(generate_trend_page(me,'reports',owner_daily={'wife':wife},date_str='2026-07-29'))"
```
Expected: `reports/trend_2026-07-29.html` 출력, 에러 없음.

- [ ] **Step 2: 브라우저로 열기**

`preview_start`(url 모드)로 `file:///.../reports/trend_2026-07-29.html` 열기.

- [ ] **Step 3: 초기(내 포트) 상태 확인**

`javascript_tool`로 `Chart.getChart(document.getElementById('categoryPie'))` 데이터 확인:
- 카드 4개(지수/배당주/개별주/현금) 렌더, 도넛 세그먼트 존재
- 내 포트 기준 개별주 최대(약 63%), 중앙 라벨 "개별주 63%" 근처
- `read_console_messages`로 JS 에러 0

- [ ] **Step 4: 합산 토글 확인**

`computer`로 `합산` 클릭 → 도넛·카드·중앙 라벨이 합산값(지수 26.7% / 배당주 7.9% / 개별주 61.2% / 현금 4.2% 근처)으로 갱신되는지 확인.

- [ ] **Step 5: 와이프 토글 — 현금 0 처리 확인**

`computer`로 `와이프` 클릭 → 현금 카드는 ₩0/0.0% 표시되고 도넛엔 현금 세그먼트가 없는지 확인.

- [ ] **Step 6: 다크/라이트 + 스크린샷**

`resize_window` colorScheme로 라이트 모드 확인 후 screenshot으로 시각 증빙 확보. (스크린샷 도구가 정적 스냅샷에서 멈추면 `read_page`/`javascript_tool` 상태 확인으로 대체.)

- [ ] **Step 7: 임시 리포트 정리**

검증용 `reports/trend_2026-07-29.html`는 추적 대상 아니면 삭제 (`git status`로 확인 후 `rm -f`).

---

## Self-Review 결과

- **Spec coverage**: 4 카테고리·분류 규칙(QLD→지수/SOXL→개별주/기본 개별주)·도넛+카드 디자인·owner 토글 연동·Asset Allocation 직후 배치·최신 스냅샷(백필 불필요)·백엔드 무변경 — 모두 Task 1~3에 매핑. ✅
- **Placeholder scan**: 전 스텝 실제 코드 포함, TBD/TODO 없음. ✅
- **이름 일관성**: `USER_CATEGORIES`/`USER_CATEGORY_MAP`/`get_ticker_category`/`category_for_weight_key`/`_user_category_rows`/payload `category`/context `user_category_json`/DOM `categoryPie`·`categoryCards`·`catPieCenter`/JS `_renderCategory`·`catColors`·`catSub` — Task 간 참조 일치. ✅
- **shape 일관성**: category rows = ticker rows와 동일 `{name, value, amount_man}` → 기존 카드/도넛 포맷 재사용. ✅
