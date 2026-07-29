# Trend Page 카테고리 구성 (도넛 + 카드) Design

## 개요

트렌드 페이지의 기존 종목별 `Asset Allocation`(도넛 + 카드 그리드) 섹션 **바로 아래**에,
현재 포트폴리오를 4개 카테고리(**지수 · 배당주 · 개별주 · 현금**)로 묶어 보여주는
별도 카드 섹션을 추가한다. 기존 Asset Allocation과 **동일한 도넛 + 카드 그리드** 디자인 언어를
사용하고, owner 토글(내 포트/와이프/합산)과 연동해 재렌더한다.

## 확정된 요구사항

1. **카테고리 4종**: 지수 / 배당주 / 개별주 / 현금.
2. **분류 규칙** (아래 "분류 규칙" 표 참조, 단일 진실의 원천 = `portfolio_data.py`).
3. **디자인**: 기존 Asset Allocation과 동일 — 좌측 도넛(중앙에 최대 비중 카테고리 강조) + 우측 카테고리 카드 그리드(색상 좌측 보더 · 평가액 · 비중).
4. **owner 범위**: 내 포트 / 와이프 / 합산 토글 연동 (기존 `_applyOwner` 패턴 재사용).
5. **상세도**: 카테고리 단위만 (4개). 카드 부제로 대표 종목명 표기.
6. **배치**: 기존 Asset Allocation 섹션 바로 아래 **별도 카드**.
7. **시계열 아님**: 최신 스냅샷만 사용 → 히스토리 백필 불필요.

## 분류 규칙

`portfolio_data.py`에 신규 `USER_CATEGORY_MAP` (ticker → 카테고리)을 둔다. 명시적으로
매핑되지 않은 티커는 기본값 **개별주**.

| 카테고리 | 티커 |
|---|---|
| **지수** | VOO, SPY, QQQ, **QLD**(2x 나스닥100), 102110(TIGER 200), 069500(KODEX 200), 379800(KODEX 미국S&P500), 360750(TIGER 미국S&P500), 379810(KODEX 미국나스닥100), 133690(TIGER 미국나스닥100), 232080(TIGER 코스닥150), 229200(KODEX 코스닥150) |
| **배당주** | SCHD, JEPI, O, 458730(TIGER 미국배당다우존스), 446720(SOL 미국배당다우존스), 0153K0(KODEX 주주환원고배당주) |
| **현금** | BIL |
| **개별주** (명시 or 기본값) | US 개별주(AAPL·NVDA·TSLA·GOOGL·MSFT·AMZN·PLTR·UNH), KOSPI/KOSDAQ 개별주(디아이티·삼성전자·삼성전자우·SK하이닉스·현대차·삼성SDI·LG에너지솔루션·롯데케미칼·동원시스템즈·유안타증권우·현대모비스), 섹터/테마/레버리지 ETF(SOXX·**SOXL**·396500·466920·487240·381170·0183J0), TLT(채권) |

**판단 근거 (locked):**
- QLD는 나스닥100 2배 추종 → **지수**. SOXL(3x 반도체 섹터)은 특정 지수 추종이 아니므로 **개별주**.
- 섹터/테마 ETF(반도체TOP10·조선TOP3·AI전력·미국테크TOP10·우주테크·SOXX)는 개별 종목적 성격 → **개별주**.
- TLT(채권)는 별도 채권 카테고리 없음 → **개별주** (합산 비중 ~0.1% 미미).
- 미분류 신규 종목 → 기본값 **개별주** (오분류 시 지수/배당은 map에 추가하면 됨).

## 상세 설계

### 1. 분류기 (`portfolio_data.py`)

```python
USER_CATEGORY_MAP = {  # ticker -> '지수'|'배당주'|'현금'  (그 외는 '개별주')
    "VOO": "지수", "SPY": "지수", "QQQ": "지수", "QLD": "지수",
    "102110": "지수", "069500": "지수", "379800": "지수", "360750": "지수",
    "379810": "지수", "133690": "지수", "232080": "지수", "229200": "지수",
    "SCHD": "배당주", "JEPI": "배당주", "O": "배당주",
    "458730": "배당주", "446720": "배당주", "0153K0": "배당주",
    "BIL": "현금",
}

USER_CATEGORIES = ["지수", "배당주", "개별주", "현금"]  # 고정 표시 순서

def get_ticker_category(ticker: str) -> str:
    """4개 사용자 카테고리 중 하나 반환. 미분류는 '개별주'."""
    return USER_CATEGORY_MAP.get(ticker, "개별주")
```

스냅샷의 `weights_by_ticker` 키가 me(한글명) / wife(티커코드)로 불일치하므로, 이름→티커
해소 헬퍼도 함께 둔다:

```python
_NAME_TO_TICKER = {meta["name"]: t for t, meta in TICKER_META.items()}

def category_for_weight_key(key: str) -> str:
    """weights_by_ticker의 키(티커코드 또는 한글 표시명)를 카테고리로 해소."""
    ticker = key if key in USER_CATEGORY_MAP else _NAME_TO_TICKER.get(key, key)
    return get_ticker_category(ticker)
```

### 2. 집계 (`report_generator.py`)

각 owner의 **최신 스냅샷** `weights_by_ticker`(%)와 `total_value_krw`로 카테고리별 KRW를
집계한다. 신규 헬퍼:

```python
def _category_breakdown_from_snapshot(snap: dict) -> list[dict]:
    from portfolio_data import USER_CATEGORIES, category_for_weight_key
    total = snap.get("total_value_krw", 0) or 0
    krw = {c: 0.0 for c in USER_CATEGORIES}
    for key, w in (snap.get("weights_by_ticker") or {}).items():
        krw[category_for_weight_key(key)] += (w / 100.0) * total
    return _category_rows(krw)   # -> [{"cat","krw","pct"}] 순서 USER_CATEGORIES

def _category_rows(krw: dict) -> list[dict]:
    from portfolio_data import USER_CATEGORIES
    g = sum(krw.values()) or 1
    return [{"cat": c, "krw": round(krw[c]), "pct": round(krw[c] / g * 100, 1)}
            for c in USER_CATEGORIES]
```

- `_build_owner_payload`: `payload["category_breakdown"] = _category_breakdown_from_snapshot(latest_snap)`.
- `_build_combined_payload`: me+wife 각 최신 스냅샷의 카테고리 **KRW를 합산**한 뒤 `_category_rows`로
  % 재계산 (가중평균 합산 회피 — 20년 예측·YTD 분해와 동일 원칙).
- 템플릿 초기 렌더용 `category_json` = 기본 owner(me)의 `category_breakdown` (기존 `ticker_json` 패턴과 동일).

### 3. 템플릿 (`templates/trend_template.html`)

기존 Asset Allocation 섹션(`#tickerPie` + `#tickerCards`) **직후**에 신규 카드 섹션 추가:

```html
<div class="rounded-xl bg-surface-container p-6 border border-outline-variant/10">
  <h2 class="text-lg font-headline font-bold mb-6" id="catTitle">카테고리 구성</h2>
  <div class="flex flex-col lg:flex-row items-center gap-8">
    <div class="relative" style="width:220px;height:220px;flex-shrink:0;">
      <canvas id="categoryPie"></canvas>
      <div class="absolute inset-0 flex flex-col items-center justify-center pointer-events-none" id="catPieCenter"></div>
    </div>
    <div class="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-3 w-full" id="categoryCards"></div>
  </div>
</div>
```

JS (기존 `tickerPie`/`_renderTicker` 패턴 그대로 복제):
- 색상: 지수 `#6dddff`, 배당주 `#ff716c`, 개별주 `#00E5BC`, 현금 `#fbbf24` (고정 매핑).
- `categoryPie` = 두 번째 doughnut (`cutout:'72%'`). 데이터는 카테고리별 KRW. 도넛은 비중 0 카테고리 자동 생략.
- 도넛 중앙(`catPieCenter`): 최대 비중 카테고리명 + 반올림 %.
- 카드: 4개 모두 표시(0 포함). 좌측 4px 색상 보더, 카테고리명 + 대표종목 부제, 우측 평가액 + 비중.
- 평가액 포맷: 기존 종목 카드와 동일 (`만` 단위 → `≥10000만이면 X.X억, 아니면 X,XXX만`).
- `_applyOwner(owner)`에 `_renderCategory(p.category_breakdown)` 호출 추가 → 토글 시 도넛·카드 재렌더.

카드 부제(대표 종목) 고정 문구:
- 지수: `S&P·나스닥·코스피·코스닥`
- 배당주: `SCHD·리얼티인컴·배당ETF`
- 개별주: `디아이티·삼성전자·AAPL`
- 현금: `BIL`

### 4. 백엔드 영향 범위

- **신규**: `portfolio_data.py`(맵/함수 2), `report_generator.py`(헬퍼 2 + payload 3곳 주입).
- **수정**: `templates/trend_template.html`(섹션 markup + JS).
- **무변경**: `pipeline.py`, `fetch_market_data.py`, 히스토리/데이터 JSON, 스냅샷 스키마.

## 테스트

- `tests/test_ticker_category.py` — `get_ticker_category` 대표 티커(카테고리별 2~3개 + QLD→지수 / SOXL→개별주 / 미분류→개별주) 및 `category_for_weight_key`(한글명 해소: '삼성전자'→개별주, '디아이티'→개별주) 단위 테스트.
- `tests/test_category_breakdown.py` — `_category_breakdown_from_snapshot`(합=100%, 4 카테고리 존재) + 합산(me+wife KRW 합산 후 % 재계산, 합=100%) 검증. 실제 `history/portfolio_daily*.json` fixture 사용.
- 렌더 스모크: `generate_trend_page`가 멀티 owner에서 `id="categoryPie"`/`categoryCards`를 포함하는지.

## 검증 계획

- 로컬 트렌드 HTML 재생성 후 브라우저 프리뷰:
  - 합산 기준 지수 26.7% / 배당주 7.9% / 개별주 61.2% / 현금 4.2% 표시 확인
  - owner 토글(내포트/와이프/합산) 전환 시 도넛·카드·중앙 라벨 갱신
  - 와이프 현금 0% → 카드엔 ₩0 표시, 도넛엔 세그먼트 없음
  - 다크/라이트 테마 정상
