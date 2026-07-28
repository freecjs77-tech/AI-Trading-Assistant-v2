# Trend Page 20년 자산 예측 그래프 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 트렌드 페이지에 합산 총자산을 시작점으로 향후 20년 복리 성장을 예측하는 인터랙티브 차트를 추가한다 — 연 수익률 슬라이더로 실시간 재계산, 합산 토글 선택 시에만 표시.

**Architecture:** 순수 클라이언트 사이드. 시작값(합산 총자산)은 이미 템플릿에 주입된 `ownersPayload.combined.latest.total_eok`에서 읽는다. 계산 `value = start × (1+r)^year`은 JS에서 즉시 수행. 백엔드/파이프라인/히스토리/데이터 스키마 전부 무변경 — 유일한 변경 파일은 `templates/trend_template.html`. Chart.js는 `display:none` 컨테이너에서 크기 측정이 부정확하므로 합산이 처음 선택되어 섹션이 보이는 시점에 lazy 생성한다.

**Tech Stack:** Jinja2 템플릿, Chart.js 4.x (CDN 기존 로드됨), Tailwind (CDN 기존 로드됨), pytest (렌더 검증), 브라우저 프리뷰 도구.

**참고 디자인 문서:** `docs/superpowers/specs/2026-07-28-trend-asset-forecast-design.md`

---

## File Structure

**Create:**
- `tests/test_trend_forecast_section.py` — `generate_trend_page()`로 실제 히스토리를 렌더해 예측 섹션 HTML/JS가 멀티 owner일 때 존재하고 단일 owner일 때 부재함을 검증

**Modify:**
- `templates/trend_template.html`
  - `#fxChart` 섹션(line 200) 다음, `{% else %}`(line 201) 앞에 예측 섹션 HTML 추가 (`{% if has_multi_owner %}` + `id="forecastSection"` + 초기 `hidden`)
  - owner 토글 클릭 리스너(line 299-309)에 `_toggleForecast(btn.dataset.owner)` 호출 추가
  - data_days 스크립트 블록 끝(line 385 `{% endif %}` 직전)에 예측 차트 JS 추가 (`{% if has_multi_owner %}` 래핑)

**변경 없음:** `report_generator.py`, `pipeline.py`, 모든 히스토리/데이터 파일.

---

## Design Decisions (locked from spec)

1. **시작값**: 합산 총자산 `ownersPayload.combined.latest.total_eok` 고정. 폴백 `{{ latest.total_eok }}`.
2. **표시 조건**: 합산 토글 선택 시에만. 초기(me 선택) `hidden`. 멀티 owner 환경에서만 존재.
3. **예측 기간**: 20년 (X축 `baseYear … baseYear+20`, baseYear = `{{ date }}`의 연도).
4. **수익률**: 슬라이더 1~15%, step 0.5, 기본 7%.
5. **마일스톤 카드**: 5/10/15/20년 4개, 각 연도 라벨 병기, 좁은 화면 2×2 줄바꿈.
6. **라인 스타일**: 점선(`borderDash:[6,4]`) secondary teal `#00E5BC`, fill 10%.
7. **계산**: 순수 복리, 추가 납입 없음. `value = start × (1+r)^year`.
8. **lazy init**: 합산 최초 선택 시 `_ensureForecastChart()`로 Chart 생성.

---

## Task 1: 예측 섹션 HTML 추가 (렌더 테스트 우선)

**Files:**
- Create: `tests/test_trend_forecast_section.py`
- Modify: `templates/trend_template.html` (line 200 다음)

- [ ] **Step 1: 실패하는 렌더 테스트 작성**

Create `tests/test_trend_forecast_section.py`:

```python
"""Tests for the 20-year asset forecast section in trend_template.html.

Renders the real trend page via generate_trend_page and asserts the forecast
section HTML/JS is present for multi-owner (합산 토글 존재) and absent for
single-owner. No backend logic to test — this guards the template wiring.
"""
from __future__ import annotations

import json
import os
import tempfile

from report_generator import generate_trend_page

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_daily():
    me_path = os.path.join(PROJECT_DIR, "history", "portfolio_daily.json")
    wife_path = os.path.join(PROJECT_DIR, "history", "portfolio_daily_wife.json")
    me = json.load(open(me_path, encoding="utf-8"))
    wife = json.load(open(wife_path, encoding="utf-8"))
    return me, wife


def _render(owner_daily):
    me, _ = _load_daily()
    with tempfile.TemporaryDirectory() as d:
        path = generate_trend_page(me, d, owner_daily=owner_daily, date_str="2026-07-28")
        with open(path, encoding="utf-8") as f:
            return f.read()


def test_forecast_section_present_multi_owner():
    _, wife = _load_daily()
    html = _render({"wife": wife})
    assert 'id="forecastSection"' in html
    assert 'id="forecastChart"' in html
    assert 'id="forecastRate"' in html


def test_forecast_section_absent_single_owner():
    html = _render(None)
    assert 'id="forecastSection"' not in html
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python -m pytest tests/test_trend_forecast_section.py -v`
Expected: `test_forecast_section_present_multi_owner` FAIL (forecastSection 없음),
`test_forecast_section_absent_single_owner` PASS (아직 아무것도 추가 안 됨).

- [ ] **Step 3: 예측 섹션 HTML 추가**

`templates/trend_template.html`의 line 200 (`<div ...><canvas id="fxChart" ...></canvas></div>`) 다음,
line 201 (`{% else %}`) 앞에 다음을 삽입:

```html

    {% if has_multi_owner %}
    <div id="forecastSection" class="hidden space-y-4">
      <h2 class="text-xl font-headline font-bold flex items-center gap-2"><span class="material-symbols-outlined text-secondary">trending_up</span> 향후 20년 자산 예측 (복리 시뮬레이션)</h2>
      <p class="text-[11px] text-outline -mt-2">합산 총자산 기준 · 추가 납입 없음 · 순수 복리</p>
      <div class="rounded-xl bg-surface-container p-6 border border-outline-variant/10 space-y-5">
        <div class="flex items-center gap-4 flex-wrap">
          <label for="forecastRate" class="text-sm text-on-surface-variant whitespace-nowrap">연 수익률</label>
          <input type="range" id="forecastRate" min="1" max="15" step="0.5" value="7" class="flex-1 min-w-[180px] accent-secondary">
          <span id="forecastRateOut" class="text-base font-bold text-secondary min-w-[64px] text-right">연 7.0%</span>
        </div>
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div class="rounded-lg bg-secondary/5 p-4">
            <div class="text-[10px] font-label text-on-surface-variant uppercase tracking-widest mb-1" id="fcLabel5">5년 후</div>
            <div class="text-xl font-headline font-bold text-secondary" id="fcVal5">&mdash;</div>
          </div>
          <div class="rounded-lg bg-secondary/5 p-4">
            <div class="text-[10px] font-label text-on-surface-variant uppercase tracking-widest mb-1" id="fcLabel10">10년 후</div>
            <div class="text-xl font-headline font-bold text-secondary" id="fcVal10">&mdash;</div>
          </div>
          <div class="rounded-lg bg-secondary/5 p-4">
            <div class="text-[10px] font-label text-on-surface-variant uppercase tracking-widest mb-1" id="fcLabel15">15년 후</div>
            <div class="text-xl font-headline font-bold text-secondary" id="fcVal15">&mdash;</div>
          </div>
          <div class="rounded-lg bg-secondary/5 p-4">
            <div class="text-[10px] font-label text-on-surface-variant uppercase tracking-widest mb-1" id="fcLabel20">20년 후</div>
            <div class="text-xl font-headline font-bold text-secondary" id="fcVal20">&mdash;</div>
          </div>
        </div>
        <div><canvas id="forecastChart" style="max-height:320px;"></canvas></div>
      </div>
    </div>
    {% endif %}
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `python -m pytest tests/test_trend_forecast_section.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_trend_forecast_section.py templates/trend_template.html
git commit -m "feat(trend): add 20-year forecast section markup (hidden by default)

Section rendered only for multi-owner (합산 토글 존재), hidden until the
combined toggle is selected. Slider + 4 milestone cards (5/10/15/20y) +
forecast canvas. JS wiring lands in the next task.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 예측 차트 JS + 슬라이더 + 토글 연동

**Files:**
- Modify: `templates/trend_template.html` (owner 토글 리스너 line 299-309, data_days 스크립트 끝 line 385 앞)
- Modify: `tests/test_trend_forecast_section.py` (JS 마커 검증 추가)

- [ ] **Step 1: JS 마커 검증 테스트 추가 (실패)**

`tests/test_trend_forecast_section.py`의 `test_forecast_section_present_multi_owner` 함수 끝(마지막 assert 다음)에 4줄 추가:

```python
    assert "_toggleForecast" in html
    assert "_ensureForecastChart" in html
    assert "_fcSeries" in html
    assert "_toggleForecast(btn.dataset.owner)" in html
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python -m pytest tests/test_trend_forecast_section.py::test_forecast_section_present_multi_owner -v`
Expected: FAIL (`_toggleForecast` 등 JS 아직 없음).

- [ ] **Step 3: owner 토글 리스너에 forecast 토글 호출 추가**

`templates/trend_template.html`의 line 307 `_applyOwner(btn.dataset.owner);` 다음 줄에 추가.

기존 (line 305-308):
```javascript
    btn.classList.add('bg-primary/20','text-primary','border-primary/30');
    btn.classList.remove('bg-surface-container-high','text-on-surface-variant','border-outline-variant/20');
    _applyOwner(btn.dataset.owner);
  });
```

수정 후:
```javascript
    btn.classList.add('bg-primary/20','text-primary','border-primary/30');
    btn.classList.remove('bg-surface-container-high','text-on-surface-variant','border-outline-variant/20');
    _applyOwner(btn.dataset.owner);
    if (typeof _toggleForecast === 'function') _toggleForecast(btn.dataset.owner);
  });
```

- [ ] **Step 4: 예측 차트 JS 블록 추가**

`templates/trend_template.html`의 line 384 (`new Chart(document.getElementById('fxChart')...` 블록의 닫는 줄) 다음,
line 385 (`{% endif %}` — data_days 블록을 닫는 줄) **앞**에 다음을 삽입:

```javascript

{% if has_multi_owner %}
// ── 향후 20년 자산 예측 (복리) — 합산 토글 전용 ──
const _fcStartEok = (ownersPayload.combined && ownersPayload.combined.latest) ? ownersPayload.combined.latest.total_eok : {{ latest.total_eok }};
const _fcBaseYear = parseInt("{{ date }}".slice(0,4), 10);
const _fcHorizon = 20;
const _fcMilestones = [5,10,15,20];
const _fcYears = Array.from({length:_fcHorizon+1}, (_,y) => String(_fcBaseYear + y));
function _fcSeries(ratePct){ const k = 1 + ratePct/100; const out = []; for(let y=0;y<=_fcHorizon;y++) out.push(+(_fcStartEok*Math.pow(k,y)).toFixed(2)); return out; }
function _fcFmt(v){ return '₩' + v.toFixed(1) + '억'; }
let _forecastChart = null;
function _ensureForecastChart(){
  if(_forecastChart) return;
  _forecastChart = new Chart(document.getElementById('forecastChart'), { type:'line', data:{ labels:_fcYears, datasets:[
    { label:'예측 자산 (억원)', data:_fcSeries(parseFloat(document.getElementById('forecastRate').value)), borderColor:'#00E5BC', backgroundColor:'rgba(0,229,188,0.08)', borderDash:[6,4], fill:true, tension:0.25, pointRadius:0, pointHoverRadius:4, borderWidth:2 }
  ]}, options:{ responsive:true, plugins:{ legend:{ display:false }, tooltip:{ callbacks:{ label:function(c){ return _fcFmt(c.parsed.y); }}}}, scales:{ y:{ ...dso, ticks:{ ...dso.ticks, callback:function(v){ return v+'억'; }}, title:{ display:true, text:'억원', color:'#a3aac4' }}, x:{ ...dso }}}});
}
function _fcRender(ratePct){
  document.getElementById('forecastRateOut').textContent = '연 ' + ratePct.toFixed(1) + '%';
  const k = 1 + ratePct/100;
  _fcMilestones.forEach(function(n){
    document.getElementById('fcLabel'+n).textContent = n + '년 후 (' + (_fcBaseYear+n) + ')';
    document.getElementById('fcVal'+n).textContent = _fcFmt(_fcStartEok*Math.pow(k,n));
  });
  if(_forecastChart){ _forecastChart.data.datasets[0].data = _fcSeries(ratePct); _forecastChart.update(); }
}
function _toggleForecast(owner){
  const sec = document.getElementById('forecastSection');
  if(!sec) return;
  if(owner === 'combined'){ sec.classList.remove('hidden'); _ensureForecastChart(); _fcRender(parseFloat(document.getElementById('forecastRate').value)); }
  else { sec.classList.add('hidden'); }
}
document.getElementById('forecastRate').addEventListener('input', function(){ _fcRender(parseFloat(this.value)); });
_fcRender(7);
{% endif %}
```

- [ ] **Step 5: 테스트 실행해서 통과 확인**

Run: `python -m pytest tests/test_trend_forecast_section.py -v`
Expected: 2 PASS (JS 마커 포함).

- [ ] **Step 6: Commit**

```bash
git add templates/trend_template.html tests/test_trend_forecast_section.py
git commit -m "feat(trend): wire forecast chart JS, slider, and combined-toggle reveal

_fcSeries computes start × (1+r)^year; slider input re-renders line + 4
milestone cards. _toggleForecast shows the section only on the combined
toggle and lazy-inits the chart on first reveal (Chart.js display:none fix).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: 브라우저 프리뷰 검증

**Files:**
- 실행/검증만, 코드 변경 없음 (문제 발견 시 Task 1/2로 회귀 수정)

- [ ] **Step 1: 실제 데이터로 트렌드 HTML 재생성**

Run:
```bash
python -c "import json; from report_generator import generate_trend_page; me=json.load(open('history/portfolio_daily.json',encoding='utf-8')); wife=json.load(open('history/portfolio_daily_wife.json',encoding='utf-8')); p=generate_trend_page(me,'reports',owner_daily={'wife':wife},date_str='2026-07-28'); print(p)"
```
Expected: `reports/trend_2026-07-28.html` 경로 출력, 에러 없음.

- [ ] **Step 2: 브라우저 프리뷰로 파일 열기**

`preview_start`(url 모드) 또는 `navigate`로 생성된 `reports/trend_2026-07-28.html`를 연다
(로컬 파일 경로 → `file:///.../reports/trend_2026-07-28.html`).

- [ ] **Step 3: 초기 상태 확인 (me 선택)**

`read_page`로 확인: 페이지 로드 직후(기본 `내 포트` 선택) `#forecastSection`이 `hidden`이어서
"향후 20년 자산 예측" 섹션이 보이지 않아야 한다.

- [ ] **Step 4: 합산 토글 → 섹션 표시 + 차트 렌더 확인**

`computer`로 `합산` 버튼 클릭 → `read_page`/`screenshot`으로 확인:
- 예측 섹션이 나타난다
- 4개 카드가 값으로 채워진다 (기본 7%: 5년 41.0억 / 10년 57.4억 / 15년 80.6억 / 20년 113.0억 근처)
- 예측 라인 차트(점선)가 그려진다
- `read_console_messages`로 JS 에러 없음 확인

- [ ] **Step 5: 슬라이더 인터랙션 확인**

`form_input` 또는 `computer`로 `#forecastRate`를 예: 10%로 변경 → `read_page`로 확인:
- 라벨이 `연 10.0%`로 갱신
- 4개 카드 값 갱신 (20년 후 = 29.2 × 1.10^20 ≈ 196.4억)
- 차트 라인이 가팔라짐

- [ ] **Step 6: 다시 내 포트/와이프 → 섹션 숨김 확인**

`computer`로 `내 포트` 클릭 → 예측 섹션이 다시 `hidden`이 되는지 확인.

- [ ] **Step 7: 다크/라이트 테마 확인**

`resize_window`의 colorScheme 또는 테마 토글 버튼 클릭으로 라이트 모드 전환 → 차트/카드/슬라이더가
정상 표시되는지 screenshot으로 확인.

- [ ] **Step 8: 재생성한 임시 리포트 정리 (선택)**

검증용으로 생성한 `reports/trend_2026-07-28.html`가 커밋 대상이 아니면 삭제하거나 그대로 둔다
(기존 `reports/trend_*.html`도 커밋되어 있으므로 파이프라인 산출물로 방치 가능 — git status 확인 후 판단).

---

## Self-Review 결과

- **Spec coverage**: 배치(#fxChart 다음)·표시 조건(합산 토글 전용, has_multi_owner+hidden)·계산(start×(1+r)^y)·슬라이더(1~15% step0.5 기본7%)·4 마일스톤 카드(5/10/15/20y)·lazy init·점선 teal 라인·백엔드 무변경 — 모두 Task 1/2에 매핑됨. ✅
- **Placeholder scan**: 모든 코드 스텝에 실제 코드 포함, TBD/TODO 없음. ✅
- **Type/이름 일관성**: `forecastSection`/`forecastChart`/`forecastRate`/`forecastRateOut`/`fcLabelN`/`fcValN`/`_fcSeries`/`_fcRender`/`_ensureForecastChart`/`_toggleForecast`/`_forecastChart` — Task 1 HTML id와 Task 2 JS 참조가 일치. ✅
