# Politician Watchlist → Michael McCaul 전용 필터 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `data/politician_filter.json` 설정으로 Politician Watchlist 섹션을 단일 의원(Michael McCaul) 거래 timeline 으로 전환한다. 설정 파일 부재 시 기존 consensus 모드는 그대로 유지(백워드 호환).

**Architecture:**
- `politician_trades_aggregator.py` 출력 스키마에 `mode`(`"filter" | "consensus"`)와 `trades[]`(거래 단건 timeline) 추가
- 필터 모드에서는 raw 트레이드를 `politician_name in filter_set` 으로 사전 필터링하고, 집계·게이트(MIN_DISTINCT_POLITICIANS, MIN_SCORE) 우회
- `report_generator.py`가 새 필드들을 템플릿 컨텍스트로 전달
- `templates/_politician_watchlist.html`에 filter 모드 분기 추가 — 거래 단건 표 렌더링

**Tech Stack:** Python 3.10+, Jinja2. 추가 의존성 없음.

**Scope 가드레일:**
- `politician_trades_fetcher.py` 손대지 않음 — raw 데이터는 모든 의원 그대로 fetch
- `pipeline.py` 손대지 않음 — aggregator 호출 시그니처 불변
- 기존 consensus 모드 코드 경로(별점·color_bias·member_bonus) 보존 — config 부재 시 기존 동작
- 시그널 판정/전략 로직 무관

**결정 사항 (사용자 확정 2026-04-25):**
- D1=B (거래 단건 timeline)
- D2=B (`data/politician_filter.json` 설정)
- D3=90일 유지
- D4=B (config 부재 시 consensus fallback)

---

### Task 1: Config 로더 + 데이터 파일

**Files:**
- Create: `data/politician_filter.json`
- Modify: `politician_trades_aggregator.py` (lines ~50-65 area, near other constants)
- Test: `tests/test_politician_filter.py` (신규)

- [ ] **Step 1: 실패 테스트 작성 (config 로딩)**

`tests/test_politician_filter.py` 신규 파일:
```python
"""politician filter config 로딩 + 모드 결정 검증."""
import sys, os, json, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import politician_trades_aggregator as agg

def _with_temp_config(content: dict | None):
    """임시 config 파일 환경. content=None이면 파일 자체가 없음."""
    tmp = tempfile.mkdtemp()
    cfg_path = os.path.join(tmp, "politician_filter.json")
    if content is not None:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(content, f)
    return tmp, cfg_path

def test_load_filter_returns_empty_when_file_missing():
    tmp, cfg_path = _with_temp_config(None)
    try:
        names = agg._load_politician_filter(cfg_path)
        assert names == [], f"파일 부재 시 빈 리스트 기대, got {names}"
    finally:
        shutil.rmtree(tmp)

def test_load_filter_returns_names_when_present():
    tmp, cfg_path = _with_temp_config({"politicians": ["Michael McCaul"]})
    try:
        names = agg._load_politician_filter(cfg_path)
        assert names == ["Michael McCaul"], f"got {names}"
    finally:
        shutil.rmtree(tmp)

def test_load_filter_handles_malformed():
    tmp, cfg_path = _with_temp_config({"unrelated_key": "x"})  # politicians 없음
    try:
        names = agg._load_politician_filter(cfg_path)
        assert names == [], "politicians 키 부재 시 빈 리스트"
    finally:
        shutil.rmtree(tmp)

if __name__ == "__main__":
    test_load_filter_returns_empty_when_file_missing()
    test_load_filter_returns_names_when_present()
    test_load_filter_handles_malformed()
    print("[OK] config 로더 테스트 통과")
```

- [ ] **Step 2: 테스트 실행 → FAIL (`AttributeError: _load_politician_filter`)**

Run: `python tests/test_politician_filter.py`

- [ ] **Step 3: aggregator 에 로더 함수 추가**

`politician_trades_aggregator.py` 상단의 상수 정의 직후 (대략 line 65 근처, `STAR_THRESHOLDS` 다음)에 추가:
```python
POLITICIAN_FILTER_PATH = os.path.join(PROJECT_DIR, "data", "politician_filter.json")


def _load_politician_filter(path: str = POLITICIAN_FILTER_PATH) -> list[str]:
    """
    Returns list of politician names to filter to (empty = consensus mode).
    Graceful: missing file, malformed JSON, missing 'politicians' key → [].
    """
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        names = cfg.get("politicians", []) or []
        return [n for n in names if isinstance(n, str) and n.strip()]
    except (json.JSONDecodeError, IOError):
        return []
```

- [ ] **Step 4: 테스트 실행 → PASS**

Run: `python tests/test_politician_filter.py`
Expected: `[OK] config 로더 테스트 통과`

- [ ] **Step 5: 데이터 파일 생성**

`data/politician_filter.json` 신규 파일:
```json
{
  "_comment": "Politician Watchlist 섹션을 단일/소수 의원 거래로 필터한다. politicians 배열이 비어있거나 파일이 없으면 consensus 모드. 변경 시 다음 파이프라인 실행에서 자동 반영.",
  "politicians": ["Michael McCaul"]
}
```

- [ ] **Step 6: 커밋**

```bash
git add data/politician_filter.json politician_trades_aggregator.py tests/test_politician_filter.py
git commit -m "feat(politician): filter config 로더 + 데이터 파일 추가

- data/politician_filter.json: 단일 의원 필터 설정 (Michael McCaul)
- _load_politician_filter(): graceful 로딩 (파일 부재/malformed → [])
- tests: 3개 (file missing / present / malformed)"
```

---

### Task 2: 필터링 + mode 분기 (집계 단계)

**Files:**
- Modify: `politician_trades_aggregator.py` 메인 함수 — raw 데이터 로딩 직후 필터 적용

- [ ] **Step 1: 메인 진입 함수 위치 확인**

`grep -n "def aggregate\|def main\|raw_trades = " politician_trades_aggregator.py` 로 raw 로딩 위치 확인.

- [ ] **Step 2: 필터 활성 시 raw 트레이드 사전 필터링**

raw 데이터를 by_ticker 로 그루핑하기 직전에 다음 블록 삽입:
```python
filter_names = _load_politician_filter()
filter_active = bool(filter_names)
if filter_active:
    filter_set = {n.strip() for n in filter_names}
    before = len(raw_trades)
    raw_trades = [t for t in raw_trades if (t.get("politician_name") or "").strip() in filter_set]
    _log(f"[Aggregator] Filter mode: {len(filter_names)} politicians → {len(raw_trades)}/{before} trades")
```

- [ ] **Step 3: 필터 모드에서 게이트 우회**

watchlist entry 빌드 루프 안에서:
- `WATCHLIST_MIN_DISTINCT_POLITICIANS` 게이트 (현재 line ~276) 를 `if filter_active or distinct_politicians_total >= WATCHLIST_MIN_DISTINCT_POLITICIANS:` 형태로 전환
- `WATCHLIST_MIN_SCORE` 게이트 (line ~272) 도 동일하게 `if filter_active or abs_score >= WATCHLIST_MIN_SCORE:` 로 전환

(필터 모드는 1명 한정이라 distinct ≥ 2 가 절대 충족 안 됨 → 우회 필수)

- [ ] **Step 4: 출력 스키마에 mode/filter_politicians 추가**

함수 끝의 `output = {...}` (또는 `result = {...}`) 딕셔너리에 추가:
```python
output["mode"] = "filter" if filter_active else "consensus"
output["filter_politicians"] = list(filter_names)
```

`trades[]` 는 Task 3 에서 추가.

- [ ] **Step 5: 회귀 테스트 — consensus 모드 그대로 동작 확인**

`tests/test_politician_filter.py` 에 추가:
```python
def test_aggregator_consensus_mode_when_no_filter(monkeypatch=None):
    # 임시로 config 경로를 존재하지 않는 곳으로 돌려 consensus 모드 강제
    orig = agg.POLITICIAN_FILTER_PATH
    agg.POLITICIAN_FILTER_PATH = "/nonexistent/path.json"
    try:
        # raw 파일이 있어야 의미 있음 — 없으면 skip
        if not os.path.exists(agg.RAW_PATH):
            print("(raw 데이터 없음, consensus 회귀 테스트 skip)")
            return
        result = agg.aggregate(agg.RAW_PATH, today=None)  # 함수 시그니처에 맞게 조정
        assert result.get("mode") == "consensus"
        assert result.get("filter_politicians") == []
        print(f"[OK] consensus mode (watchlist={len(result.get('watchlist', []))}건)")
    finally:
        agg.POLITICIAN_FILTER_PATH = orig
```

(메인 진입 함수명이 `aggregate` 가 아닐 수 있음. `grep "^def " politician_trades_aggregator.py | head -10` 으로 확인 후 시그니처 맞춰 호출)

- [ ] **Step 6: 테스트 실행 → 모두 PASS**

Run: `python tests/test_politician_filter.py`

- [ ] **Step 7: 커밋**

```bash
git add politician_trades_aggregator.py tests/test_politician_filter.py
git commit -m "feat(politician): filter mode 진입 — raw 사전 필터 + 게이트 우회

- filter 활성 시 politician_name 매칭 트레이드만 통과
- MIN_DISTINCT_POLITICIANS / MIN_SCORE 게이트 우회 (1명이라 의미 없음)
- 출력에 mode + filter_politicians 추가
- consensus 회귀 테스트 추가"
```

---

### Task 3: trades[] timeline 빌드

**Files:**
- Modify: `politician_trades_aggregator.py` — 새 헬퍼 `_build_trade_timeline()` + 출력에 추가

- [ ] **Step 1: 단위 테스트 작성**

`tests/test_politician_filter.py` 에 추가:
```python
def test_trade_timeline_sorts_desc_and_keeps_raw_fields():
    """trades[] 가 날짜 desc 정렬되고 핵심 필드를 raw 그대로 포함하는지."""
    fake_trades = [
        {"politician_name": "Michael McCaul", "tx_date": "2026-03-10",
         "ticker": "AAPL", "issuer_name": "Apple Inc",
         "tx_type": "Purchase", "amount_min": 15001, "amount_max": 50000,
         "politician_id": "M001"},
        {"politician_name": "Michael McCaul", "tx_date": "2026-04-05",
         "ticker": "NVDA", "issuer_name": "NVIDIA Corp",
         "tx_type": "Sale (Full)", "amount_min": 100001, "amount_max": 250000,
         "politician_id": "M001"},
    ]
    timeline = agg._build_trade_timeline(fake_trades, portfolio_tickers={"AAPL"})
    assert len(timeline) == 2
    # 날짜 desc
    assert timeline[0]["tx_date"] == "2026-04-05", "최신 거래가 먼저"
    assert timeline[1]["tx_date"] == "2026-03-10"
    # 방향 정규화
    assert timeline[0]["direction"] == "sell"
    assert timeline[1]["direction"] == "buy"
    # in_portfolio
    assert timeline[1]["in_portfolio"] == True   # AAPL
    assert timeline[0]["in_portfolio"] == False  # NVDA
    # raw 필드 보존
    assert timeline[1]["amount_min"] == 15001
    assert timeline[0]["issuer_name"] == "NVIDIA Corp"
```

- [ ] **Step 2: 테스트 실행 → FAIL (`AttributeError: _build_trade_timeline`)**

Run: `python tests/test_politician_filter.py`

- [ ] **Step 3: 헬퍼 구현**

`politician_trades_aggregator.py` 의 `_direction()` 헬퍼 근처에 추가:
```python
def _build_trade_timeline(trades: list[dict], portfolio_tickers: set[str] | None = None) -> list[dict]:
    """
    Filter mode 전용 — 거래 단건을 날짜 desc 로 정렬한 timeline 빌드.
    Raw 필드를 그대로 보존 (별점·스코어 없음).
    """
    portfolio_tickers = portfolio_tickers or set()
    items = []
    for t in trades:
        ticker = (t.get("ticker") or "").strip()
        if not ticker:
            continue
        direction_n = _direction(t.get("tx_type", ""))
        if direction_n == 0:
            continue
        items.append({
            "tx_date": t.get("tx_date", ""),
            "direction": "buy" if direction_n > 0 else "sell",
            "ticker": ticker,
            "issuer_name": t.get("issuer_name", ""),
            "amount_min": t.get("amount_min"),
            "amount_max": t.get("amount_max"),
            "tx_type": t.get("tx_type", ""),
            "politician_name": t.get("politician_name", ""),
            "in_portfolio": ticker in portfolio_tickers,
        })
    items.sort(key=lambda x: x.get("tx_date", ""), reverse=True)
    return items
```

- [ ] **Step 4: 메인 출력에 트랜드 timeline 연결**

aggregator 메인 함수에서 filter_active 분기 시:
```python
if filter_active:
    portfolio_tickers = _load_portfolio_tickers()  # 기존 헬퍼 재사용
    output["trades"] = _build_trade_timeline(raw_trades, portfolio_tickers)
else:
    output["trades"] = []
```

(`_load_portfolio_tickers` 가 없으면 raw_trades에서 portfolio_tickers를 받는 부분을 찾아 그대로 사용)

- [ ] **Step 5: 테스트 실행 → PASS**

Run: `python tests/test_politician_filter.py`

- [ ] **Step 6: 실데이터 검증**

```bash
python -c "
import politician_trades_aggregator as agg
result = agg._main() if hasattr(agg, '_main') else None  # entry point 확인
# 또는 모듈 실행
"
python politician_trades_aggregator.py
python -c "
import json
with open('history/politician_trades.json','r',encoding='utf-8') as f:
    d = json.load(f)
print('mode:', d.get('mode'))
print('filter_politicians:', d.get('filter_politicians'))
print('trades count:', len(d.get('trades', [])))
if d.get('trades'):
    t = d['trades'][0]
    print('latest:', t['tx_date'], t['direction'], t['ticker'], t['amount_min'])
"
```
Expected:
- `mode: filter`
- `filter_politicians: ['Michael McCaul']`
- `trades count` > 0 (raw 데이터에 McCaul 다수 존재)

- [ ] **Step 7: 커밋**

```bash
git add politician_trades_aggregator.py tests/test_politician_filter.py
git commit -m "feat(politician): filter 모드 trades[] timeline 빌드

- _build_trade_timeline(): 날짜 desc 정렬, raw 필드 보존
- in_portfolio 플래그 부착
- 출력에 trades[] 추가 (consensus 모드는 빈 배열)"
```

---

### Task 4: report_generator 컨텍스트 전달

**Files:**
- Modify: `report_generator.py` — politician 관련 컨텍스트 빌드 부분

- [ ] **Step 1: 기존 politician 컨텍스트 위치 확인**

`grep -n "politician_buy_cards\|politician_sell_cards\|politician_meta" report_generator.py | head -5`

- [ ] **Step 2: 새 컨텍스트 키 추가**

기존 `politician_*` 컨텍스트 빌드 블록에서 `politician_trades.json` 로딩 후 다음 키들을 함께 컨텍스트에 추가:
```python
politician_mode = pol_data.get("mode", "consensus")
politician_filter_names = pol_data.get("filter_politicians", [])
politician_trades_list = pol_data.get("trades", [])
# ... 기존 buy_cards/sell_cards 빌드는 consensus 모드일 때만 의미 ...
context.update({
    "politician_mode": politician_mode,
    "politician_filter_names": politician_filter_names,
    "politician_trades_list": politician_trades_list,
    # 기존 키 유지
    "politician_buy_cards": buy_cards,
    "politician_sell_cards": sell_cards,
    "politician_meta": pol_data.get("meta", {}),
    "politician_updated_at": pol_data.get("updated_at"),
})
```

- [ ] **Step 3: smoke check**

```bash
python pipeline.py 2>&1 | grep -E "politician|Aggregator" | head -5
```
Expected: 에러 없음, "[Aggregator] Filter mode: 1 politicians → N/M trades" 로그 출력.

- [ ] **Step 4: 커밋**

```bash
git add report_generator.py
git commit -m "feat(politician): report context에 mode/trades_list/filter_names 추가"
```

---

### Task 5: 템플릿 filter 모드 분기

**Files:**
- Modify: `templates/_politician_watchlist.html`

- [ ] **Step 1: 기존 헤더에 모드별 분기 추가**

파일 상단의 `{% if politician_buy_cards or politician_sell_cards %}` 라인을 다음으로 교체:
```jinja
{% set _has_filter = politician_mode == "filter" and politician_trades_list %}
{% set _has_consensus = politician_mode != "filter" and (politician_buy_cards or politician_sell_cards) %}
{% if _has_filter or _has_consensus %}
```

해당 if 의 닫기 `{% endif %}` 도 그대로 둠.

섹션 헤더(`<h2>`)에서 모드별 제목 변경:
```jinja
<h2 class="text-xl font-headline font-bold text-on-surface">
  {% if _has_filter %}
    {{ politician_filter_names|join(', ') }} 거래
    <span class="text-on-surface-variant text-sm font-normal">(최근 90일)</span>
  {% else %}
    Politician Watchlist <span class="text-on-surface-variant text-sm font-normal">(최근 90일)</span>
  {% endif %}
</h2>
<p class="text-xs text-on-surface-variant mt-1">
  {% if _has_filter %}공시된 매매 내역 (timeline){% else %}의원들이 거래한 TOP 종목 · 가중 스코어 기반{% endif %}
</p>
```

- [ ] **Step 2: filter 모드 본문 추가**

기존 `<div class="grid grid-cols-1 lg:grid-cols-2 gap-5">` 시작 직전에 분기 삽입:
```jinja
{% if _has_filter %}
<!-- Filter mode: trade timeline -->
<div class="overflow-x-auto rounded-xl border border-outline-variant/10 bg-surface-container-low">
  <table class="w-full text-left border-collapse text-sm">
    <thead class="bg-surface-container text-on-surface-variant font-label text-[10px] uppercase tracking-widest">
      <tr>
        <th class="px-4 py-3">날짜</th>
        <th class="px-4 py-3">방향</th>
        <th class="px-4 py-3">Ticker</th>
        <th class="px-4 py-3">회사</th>
        <th class="px-4 py-3 text-right">금액 (USD)</th>
        <th class="px-4 py-3">공시 종류</th>
      </tr>
    </thead>
    <tbody class="divide-y divide-outline-variant/10">
      {% for t in politician_trades_list %}
      <tr class="hover:bg-surface-container-high/40 transition-colors">
        <td class="px-4 py-3 text-on-surface-variant whitespace-nowrap">{{ t.tx_date }}</td>
        <td class="px-4 py-3">
          {% if t.direction == 'buy' %}
            <span class="text-[11px] font-bold uppercase tracking-wider bg-primary/15 text-primary px-2 py-0.5 rounded">매수</span>
          {% else %}
            <span class="text-[11px] font-bold uppercase tracking-wider bg-error/15 text-error px-2 py-0.5 rounded">매도</span>
          {% endif %}
        </td>
        <td class="px-4 py-3 font-mono font-bold text-on-surface">
          {{ t.ticker }}
          {% if t.in_portfolio %}<span class="ml-1 text-[9px] uppercase tracking-wider bg-tertiary/20 text-tertiary px-1 py-0.5 rounded">보유</span>{% endif %}
        </td>
        <td class="px-4 py-3 text-on-surface-variant truncate max-w-[200px]" title="{{ t.issuer_name }}">{{ t.issuer_name }}</td>
        <td class="px-4 py-3 text-right text-on-surface-variant whitespace-nowrap">
          {% if t.amount_min %}${{ '{:,}'.format(t.amount_min) }}{% if t.amount_max %} – ${{ '{:,}'.format(t.amount_max) }}{% endif %}{% else %}—{% endif %}
        </td>
        <td class="px-4 py-3 text-[11px] text-outline">{{ t.tx_type }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% else %}
```

기존 grid 블록 시작 위에 위 분기를 추가하고, 기존 buy/sell consensus 블록 전체를 위 `{% else %}` 아래에 두며, grid `</div>` 닫기 다음에 `{% endif %}` 를 추가해 분기 종료.

- [ ] **Step 3: 빈 결과 메시지 (filter 모드 + trades=[])**

`{% if _has_filter or _has_consensus %}` 의 ELSE 분기 (현재는 nothing render) 에 다음 추가 — 단, filter 모드인데 trades 가 비었을 때만 표시:
```jinja
{% elif politician_mode == "filter" %}
<section class="rounded-xl bg-surface-container border border-outline-variant/10 p-4 text-center text-xs text-on-surface-variant">
  {{ politician_filter_names|join(', ') }}의 최근 90일간 공시된 매매 거래가 없습니다.
</section>
{% endif %}
```

- [ ] **Step 4: 렌더 검증**

```bash
python pipeline.py 2>&1 | tail -5
```
Generated 리포트의 스캐너 페이지(`reports/scanner_<DATE>.html`) 에서:
```bash
grep -c "Michael McCaul 거래" reports/scanner_*.html | head -1
grep -c '날짜</th>' reports/scanner_*.html | head -1
```
Expected: 양쪽 모두 1 이상 (해당 섹션이 렌더됨).

- [ ] **Step 5: 커밋**

```bash
git add templates/_politician_watchlist.html
git commit -m "ui(politician): filter mode timeline 표 렌더링 분기 추가

- 섹션 제목/부제 모드별 분기
- trades[] 단건 표 (날짜·방향·ticker·회사·금액·공시 종류)
- in_portfolio 시 보유 배지
- 빈 결과 시 안내 메시지
- consensus 모드는 변경 없음"
```

---

### Task 6: 통합 검증

**Files:** (변경 없음, 검증만)

- [ ] **Step 1: 모든 테스트 통과 확인**

```bash
python tests/test_scanner_data.py
python tests/test_scanner_entry_sector.py
python tests/test_politician_filter.py
```
3개 모두 `[OK]` 출력해야 함.

- [ ] **Step 2: 전체 파이프라인 실행**

```bash
python pipeline.py 2>&1 | tail -25
```
Expected: 에러 없이 완주, "[Aggregator] Filter mode: 1 politicians → N/M trades" 로그 확인.

- [ ] **Step 3: 출력 데이터 검사**

```bash
python -c "
import json
with open('history/politician_trades.json','r',encoding='utf-8') as f:
    d = json.load(f)
print('mode:', d['mode'])
print('filter_politicians:', d['filter_politicians'])
print('trades count:', len(d['trades']))
print('latest 3 trades:')
for t in d['trades'][:3]:
    print(f\"  {t['tx_date']} {t['direction']:5} {t['ticker']:6} {t['issuer_name']}\")
"
```

- [ ] **Step 4: Flask 로컬 시각 확인**

```bash
python app.py  # 백그라운드
```
브라우저 http://localhost:5000/scanner — Politician Watchlist 섹션이 "Michael McCaul 거래" 제목 + timeline 표로 보여야 함.

수동 체크리스트:
- [ ] 섹션 제목이 "Michael McCaul 거래 (최근 90일)" 표시
- [ ] 표 컬럼: 날짜 / 방향 / Ticker / 회사 / 금액 / 공시 종류
- [ ] 매수는 파란색, 매도는 빨간색 배지
- [ ] 포트폴리오 보유 종목엔 "보유" 배지
- [ ] 정렬: 최신 거래 맨 위
- [ ] 별점·"의원 N명" 표기 사라짐 확인
- [ ] consensus disclaimer 박스 사라짐 (별점·색상 언급 무의미)

- [ ] **Step 5: 백워드 호환 회귀 — config 비활성 시 consensus 복원**

```bash
mv data/politician_filter.json data/politician_filter.json.bak
python pipeline.py 2>&1 | grep "Aggregator" | head -3
python -c "
import json
print('mode:', json.load(open('history/politician_trades.json'))['mode'])
"
mv data/politician_filter.json.bak data/politician_filter.json
```
Expected: 첫 실행에서 `mode: consensus`, 두 번째에서 `mode: filter`.

- [ ] **Step 6: 런타임 산출물 정리 (커밋 없음)**

`git status --short | head -10` 으로 자동 생성물이 워킹 트리에 남아있는지 확인. 필요시 `git checkout -- history/ reports/` 로 원복 (다음 자동 파이프라인에서 재생성).

---

### Task 7: 문서 업데이트 + 최종 검증

**Files:**
- Modify: `CLAUDE.md` (진행 중인 계획 → 완료 항목으로 이동 또는 제거)

- [ ] **Step 1: CLAUDE.md 진행 중인 계획 정리**

`docs/plans/politician-mccaul-only.md` 항목 제거 (완료) 또는 `[완료]` 마커 추가. 사용자 선호에 맞춰 결정.

- [ ] **Step 2: 최종 커밋**

```bash
git add CLAUDE.md
git commit -m "docs: McCaul 필터 작업 완료 반영"
```

- [ ] **Step 3: 머지 옵션 제시 (subagent-driven 종료 단계)**

`superpowers:finishing-a-development-branch` 스킬 호출.

---

## Appendix A: 변경 영향 요약

| 영역 | 변경 | 위험도 |
|---|---|---|
| Raw fetcher | 없음 (`politician_trades_fetcher.py` 무변경) | 없음 |
| Aggregator | filter mode 분기 추가 (consensus 코드 경로 보존) | 낮음 |
| Report generator | 컨텍스트 키 3개 추가 | 낮음 |
| Template | filter 모드 분기 (consensus 분기 보존) | 낮음 |
| Pipeline | 변경 없음 | 없음 |
| Signal/strategy | 무관 | 없음 |
| 백워드 호환 | `data/politician_filter.json` 부재 → 기존 consensus 모드로 fallback | 낮음 |

## Appendix B: 자기 검토

**Spec coverage:**
- [x] Michael McCaul 거래만 표시 → Task 1+2+3
- [x] 설정 파일 기반 (D2=B) → `data/politician_filter.json` + `_load_politician_filter()`
- [x] 거래 단건 timeline (D1=B) → `_build_trade_timeline` + 표 UI
- [x] 90일 룩백 유지 (D3) → 변경 없음
- [x] consensus fallback (D4=B) → config 부재 시 기존 동작

**Placeholder scan:** 없음.

**Type consistency:** `_build_trade_timeline` 출력 키 (tx_date, direction, ticker, issuer_name, amount_min, amount_max, tx_type, in_portfolio) 가 Task 5 템플릿에서 동일 이름으로 참조됨.

**Risk:** McCaul이 90일간 거래 0건이면 빈 메시지 표시 (Task 5 Step 3에서 처리). raw 데이터 grep 결과 다수 존재 확인.
