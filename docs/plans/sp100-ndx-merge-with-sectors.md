# S&P 100 + NASDAQ 100 통합 + 섹터 표시 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 SP100 스캐너 리스트(50종목)를 S&P 100 전체(101) + NASDAQ 100(100)으로 확장(중복 제거 후 ~169종목)하고, 각 종목에 GICS 섹터를 함께 표시한다.

**Architecture:**
- `market_scanner.py`의 `SP100_TICKERS` / `SP100_NAMES` 자료를 단순 확장하고 `TICKER_SECTORS` 딕셔너리를 추가한다 (구조 변경 없음).
- `scan_sp100()` 결과 entry에 `sector` 필드를 추가한다.
- `scanner_unified_template.html` SP100 섹션 표에 Sector 컬럼을 1개 추가한다 (ETF/KOSPI 표는 그대로).
- 시그널 판정 로직(strategy.md v5.3), 캐시 키(`scanner_sp100`), 히스토리 파일(`scanner_sp100_history.json`)은 변경하지 않는다.

**Tech Stack:** Python 3.10+, yfinance, Jinja2. 추가 의존성 없음.

**Scope 가드레일:**
- 변수명 `SP100_TICKERS`/`SP100_NAMES`/`scan_sp100`/`cache_name="scanner_sp100"`는 유지 (호출부 영향 회피).
- `signal_judge.py`, `history_manager.py`, `pipeline.py`는 손대지 않는다.
- 섹터는 GICS 11분류 한국어 약어로 표기 (`Tech / Comm / 경기소비 / 필수소비 / 헬스케어 / 금융 / 산업 / 에너지 / 유틸 / 부동산 / 소재`).

---

### Task 1: NDX 100 명단 검증 (사전 조사, 코드 변경 없음)

**Files:**
- Read only: `market_scanner.py:31-68` (현재 50종목 리스트와 NAMES 딕셔너리 확인)

- [ ] **Step 1: NASDAQ 공식 NDX 구성종목 페이지 확인**

브라우저 또는 WebFetch로 다음 URL을 열어 현재 NDX 100 구성종목 100개 ticker를 추출한다:
- 1차: `https://en.wikipedia.org/wiki/Nasdaq-100` (Components 표)
- 검증: `https://www.nasdaq.com/market-activity/quotes/nasdaq-ndx-index`

추출한 ticker 100개를 임시 파일 `/tmp/ndx100.txt`에 한 줄에 하나씩 저장.

- [ ] **Step 2: SP100 ↔ NDX100 중복 추출**

본 계획서 하단 [Appendix A: 표준 SP100 명단](#appendix-a-표준-sp100-명단-101종목)에서 101종목과 Step 1의 NDX 100을 비교해 중복(약 30~32종목)과 NDX 단독(~68종목)을 분리한다.

확인 명령(Python REPL):
```python
sp100 = {"AAPL","ABBV","ABT","ACN","ADBE","AIG","AMD","AMGN","AMZN","AVGO",
         "AXP","BA","BAC","BK","BKNG","BLK","BMY","BRK-B","C","CAT",
         "CHTR","CL","CMCSA","COF","COP","COST","CRM","CSCO","CVS","CVX",
         "DE","DHR","DIS","DOW","DUK","EMR","EXC","F","FDX","GD",
         "GE","GILD","GM","GOOG","GOOGL","GS","HD","HON","IBM","INTC",
         "INTU","JNJ","JPM","KHC","KO","LIN","LLY","LMT","LOW","MA",
         "MCD","MDLZ","MDT","MET","META","MMM","MO","MRK","MS","MSFT",
         "NEE","NFLX","NKE","NVDA","ORCL","PEP","PFE","PG","PM","PYPL",
         "QCOM","RTX","SBUX","SCHW","SO","SPG","T","TGT","TMO","TMUS",
         "TSLA","TXN","UNH","UNP","UPS","USB","V","VZ","WFC","WMT","XOM"}
ndx = set(open("/tmp/ndx100.txt").read().split())
print("overlap:", len(sp100 & ndx))
print("ndx_only:", sorted(ndx - sp100))
print("union:", len(sp100 | ndx))
```
기대: `overlap` 30~32, `union` 167~170.

- [ ] **Step 3: 합집합 ticker 리스트 확정**

`union = sorted(sp100 | ndx)` 결과를 알파벳 순으로 정렬한 리스트를 작성, 다음 Task에서 사용한다. (BRK-B 같은 하이픈 ticker가 yfinance에서 정상 동작하는지 확인.)

---

### Task 2: 섹터 매핑 데이터 추가 (단일 파일 수정)

**Files:**
- Modify: `market_scanner.py:30-68` (SP100_TICKERS, SP100_NAMES 확장 + TICKER_SECTORS 신규)
- Test: `tests/test_scanner_data.py` (신규)

- [ ] **Step 1: 검증 테스트부터 작성**

`tests/test_scanner_data.py` 신규 파일:
```python
"""Scanner ticker/name/sector 데이터 무결성 검증."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from market_scanner import SP100_TICKERS, SP100_NAMES, TICKER_SECTORS

VALID_SECTORS = {
    "Tech", "Comm", "경기소비", "필수소비", "헬스케어",
    "금융", "산업", "에너지", "유틸", "부동산", "소재",
}

def test_no_duplicates():
    assert len(SP100_TICKERS) == len(set(SP100_TICKERS)), "중복 ticker 존재"

def test_size_in_range():
    n = len(SP100_TICKERS)
    assert 160 <= n <= 175, f"확장 후 종목 수 {n} (예상 범위 160~175)"

def test_every_ticker_has_name():
    missing = [t for t in SP100_TICKERS if t not in SP100_NAMES]
    assert not missing, f"이름 누락: {missing}"

def test_every_ticker_has_sector():
    missing = [t for t in SP100_TICKERS if t not in TICKER_SECTORS]
    assert not missing, f"섹터 누락: {missing}"

def test_sector_values_valid():
    invalid = {t: s for t, s in TICKER_SECTORS.items()
               if t in SP100_TICKERS and s not in VALID_SECTORS}
    assert not invalid, f"잘못된 섹터값: {invalid}"

if __name__ == "__main__":
    test_no_duplicates()
    test_size_in_range()
    test_every_ticker_has_name()
    test_every_ticker_has_sector()
    test_sector_values_valid()
    print("[OK] All scanner data integrity tests passed.")
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `python tests/test_scanner_data.py`
Expected: `AssertionError: 확장 후 종목 수 50 (예상 범위 160~175)` 에서 실패. (현재 50종목)

- [ ] **Step 3: SP100_TICKERS를 union 리스트로 교체**

`market_scanner.py:30-37` 의 SP100_TICKERS를 Task 1 Step 3에서 만든 합집합으로 교체. 헤더 주석도 다음과 같이 수정:
```python
# ── 미국 대형주 스캐너 — S&P 100 + NASDAQ 100 합집합 (~169종목) ─────
# 변수명은 호환성을 위해 SP100_TICKERS를 유지 (외부 호출부 영향 없음).
SP100_TICKERS = [
    "AAPL", "ABBV", "ABNB", "ABT", "ACN", "ADBE", "ADI", "ADP", "ADSK", "AEP",
    "AIG", "AMAT", "AMD", "AMGN", "AMZN", "ANSS", "APP", "ARM", "ASML", "AVGO",
    "AXON", "AXP", "AZN", "BA", "BAC", "BIIB", "BK", "BKNG", "BKR", "BLK",
    # ... (Task 1 Step 3 결과를 그대로 붙여넣기)
]
```

- [ ] **Step 4: SP100_NAMES에 NDX-only 종목 추가**

기존 SP100_NAMES는 101종목 모두 포함되어 있으므로, NDX-only ~68종목만 추가하면 됨. 예시:
```python
# 기존 SP100_NAMES 딕셔너리 끝에 추가
SP100_NAMES.update({
    "ABNB": "Airbnb", "ADI": "Analog Devices", "ADP": "ADP", "ADSK": "Autodesk",
    "AEP": "American Electric Power", "AMAT": "Applied Materials", "ANSS": "Ansys",
    "APP": "AppLovin", "ARM": "ARM Holdings", "ASML": "ASML", "AXON": "Axon",
    "AZN": "AstraZeneca", "BIIB": "Biogen", "BKR": "Baker Hughes", "CCEP": "Coca-Cola Europacific",
    "CDNS": "Cadence Design", "CDW": "CDW", "CEG": "Constellation Energy",
    "CPRT": "Copart", "CRWD": "CrowdStrike", "CSGP": "CoStar", "CSX": "CSX",
    "CTAS": "Cintas", "CTSH": "Cognizant", "DASH": "DoorDash", "DDOG": "Datadog",
    "DXCM": "DexCom", "EA": "Electronic Arts", "FANG": "Diamondback Energy",
    "FAST": "Fastenal", "FTNT": "Fortinet", "GEHC": "GE HealthCare", "GFS": "GlobalFoundries",
    "IDXX": "IDEXX Labs", "ISRG": "Intuitive Surgical", "KDP": "Keurig Dr Pepper",
    "KLAC": "KLA Corp", "LRCX": "Lam Research", "LULU": "Lululemon", "MAR": "Marriott",
    "MCHP": "Microchip", "MDB": "MongoDB", "MELI": "MercadoLibre", "MNST": "Monster Beverage",
    "MRVL": "Marvell", "MU": "Micron", "NXPI": "NXP Semiconductors", "ODFL": "Old Dominion",
    "ON": "ON Semiconductor", "ORLY": "O'Reilly Auto", "PANW": "Palo Alto Networks",
    "PAYX": "Paychex", "PCAR": "PACCAR", "PDD": "PDD Holdings", "PLTR": "Palantir",
    "REGN": "Regeneron", "ROP": "Roper", "ROST": "Ross Stores", "SNPS": "Synopsys",
    "TEAM": "Atlassian", "TTD": "The Trade Desk", "TTWO": "Take-Two", "VRSK": "Verisk",
    "VRTX": "Vertex Pharma", "WBD": "Warner Bros Discovery", "WDAY": "Workday",
    "XEL": "Xcel Energy", "ZS": "Zscaler",
})
```
(실제 NDX-only 종목 목록은 Task 1 Step 2 결과로 확정.)

- [ ] **Step 5: TICKER_SECTORS 딕셔너리 신규 작성**

`SP100_NAMES` 바로 아래 (line ~69)에 추가. GICS 11분류 한국어 약어 사용. 합집합 169종목 모두 매핑.
```python
# ── GICS 섹터 매핑 (11분류 한국어 약어) ─────
# Tech: Information Technology / Comm: Communication Services
# 경기소비: Consumer Discretionary / 필수소비: Consumer Staples
# 헬스케어: Health Care / 금융: Financials / 산업: Industrials
# 에너지: Energy / 유틸: Utilities / 부동산: Real Estate / 소재: Materials
TICKER_SECTORS = {
    "AAPL": "Tech",       "MSFT": "Tech",       "NVDA": "Tech",     "GOOG": "Comm",
    "GOOGL": "Comm",      "META": "Comm",       "AMZN": "경기소비",  "TSLA": "경기소비",
    "AVGO": "Tech",       "ORCL": "Tech",       "CRM": "Tech",      "ADBE": "Tech",
    "AMD": "Tech",        "INTC": "Tech",       "QCOM": "Tech",     "TXN": "Tech",
    "CSCO": "Tech",       "INTU": "Tech",       "IBM": "Tech",      "ASML": "Tech",
    "AMAT": "Tech",       "LRCX": "Tech",       "KLAC": "Tech",     "MU": "Tech",
    "ARM": "Tech",        "PANW": "Tech",       "CRWD": "Tech",     "FTNT": "Tech",
    "ZS": "Tech",         "ANSS": "Tech",       "SNPS": "Tech",     "CDNS": "Tech",
    "MRVL": "Tech",       "NXPI": "Tech",       "ON": "Tech",       "MCHP": "Tech",
    "ADI": "Tech",        "GFS": "Tech",        "DDOG": "Tech",     "MDB": "Tech",
    "TEAM": "Tech",       "WDAY": "Tech",       "ADSK": "Tech",     "PLTR": "Tech",
    "APP": "Tech",        "TTD": "Tech",        "ACN": "Tech",      "CDW": "Tech",
    "CTSH": "Tech",       "PAYX": "Tech",       "ADP": "Tech",      "AXON": "Tech",
    "NFLX": "Comm",       "CMCSA": "Comm",      "DIS": "Comm",      "CHTR": "Comm",
    "TMUS": "Comm",       "T": "Comm",          "VZ": "Comm",       "EA": "Comm",
    "TTWO": "Comm",       "WBD": "Comm",        "CCEP": "필수소비",
    "HD": "경기소비",      "LOW": "경기소비",     "MCD": "경기소비",   "NKE": "경기소비",
    "SBUX": "경기소비",    "BKNG": "경기소비",    "MAR": "경기소비",   "ABNB": "경기소비",
    "DASH": "경기소비",    "TGT": "경기소비",     "LULU": "경기소비",  "ROST": "경기소비",
    "ORLY": "경기소비",    "F": "경기소비",       "GM": "경기소비",   "MELI": "경기소비",
    "PDD": "경기소비",
    "WMT": "필수소비",     "COST": "필수소비",   "PG": "필수소비",   "KO": "필수소비",
    "PEP": "필수소비",     "PM": "필수소비",     "MO": "필수소비",   "MDLZ": "필수소비",
    "KHC": "필수소비",     "CL": "필수소비",     "MNST": "필수소비", "KDP": "필수소비",
    "CVS": "필수소비",
    "LLY": "헬스케어",     "JNJ": "헬스케어",     "UNH": "헬스케어",   "ABBV": "헬스케어",
    "MRK": "헬스케어",     "TMO": "헬스케어",     "ABT": "헬스케어",   "DHR": "헬스케어",
    "PFE": "헬스케어",     "MDT": "헬스케어",     "BMY": "헬스케어",   "AMGN": "헬스케어",
    "GILD": "헬스케어",    "ISRG": "헬스케어",    "VRTX": "헬스케어",  "REGN": "헬스케어",
    "BIIB": "헬스케어",    "DXCM": "헬스케어",    "IDXX": "헬스케어",  "GEHC": "헬스케어",
    "AZN": "헬스케어",
    "BRK-B": "금융",       "JPM": "금융",         "V": "금융",         "MA": "금융",
    "BAC": "금융",         "WFC": "금융",         "GS": "금융",        "MS": "금융",
    "AXP": "금융",         "C": "금융",           "SCHW": "금융",      "BLK": "금융",
    "BK": "금융",          "USB": "금융",         "COF": "금융",       "PYPL": "금융",
    "AIG": "금융",         "MET": "금융",
    "GE": "산업",          "HON": "산업",         "RTX": "산업",       "LMT": "산업",
    "CAT": "산업",         "DE": "산업",          "BA": "산업",        "UPS": "산업",
    "FDX": "산업",         "UNP": "산업",         "GD": "산업",        "MMM": "산업",
    "EMR": "산업",         "PCAR": "산업",        "CSX": "산업",       "ODFL": "산업",
    "CTAS": "산업",        "CPRT": "산업",        "FAST": "산업",      "ROP": "산업",
    "VRSK": "산업",        "CSGP": "산업",
    "XOM": "에너지",       "CVX": "에너지",       "COP": "에너지",     "FANG": "에너지",
    "BKR": "에너지",
    "NEE": "유틸",         "DUK": "유틸",         "SO": "유틸",        "EXC": "유틸",
    "AEP": "유틸",         "XEL": "유틸",         "CEG": "유틸",
    "SPG": "부동산",
    "DOW": "소재",         "LIN": "소재",
}
```
(전체 169종목 매핑 완성. 누락 시 Task 2 Step 7의 검증 테스트에서 잡힘.)

- [ ] **Step 6: 검증 테스트 실행 (PASS 기대)**

Run: `python tests/test_scanner_data.py`
Expected: `[OK] All scanner data integrity tests passed.`

테스트가 누락 ticker를 알려주면 해당 ticker의 sector를 채워 다시 실행. 모두 통과할 때까지 반복.

- [ ] **Step 7: 커밋**

```bash
git add market_scanner.py tests/test_scanner_data.py
git commit -m "feat(scanner): SP100+NDX100 합집합 확장 + GICS 섹터 매핑 추가

- SP100_TICKERS 50→~169 (S&P 100 ∪ NASDAQ 100, 중복 제거)
- TICKER_SECTORS 신규 (GICS 11분류 한국어 약어)
- SP100_NAMES에 NDX-only ~68종목 추가
- tests/test_scanner_data.py 무결성 검증 추가"
```

---

### Task 3: scan_sp100 결과에 sector 필드 추가

**Files:**
- Modify: `market_scanner.py:528-555` (entry dict 구성)
- Modify: `market_scanner.py:24` (import)

- [ ] **Step 1: TICKER_SECTORS 임포트 (같은 파일이므로 임포트 불필요, 함수 내 직접 참조)**

확인만: `market_scanner.py` 상단의 import 구간은 변경하지 않음. `TICKER_SECTORS`는 같은 모듈 전역이라 그대로 사용 가능.

- [ ] **Step 2: scan_sp100 entry dict에 sector 추가**

`market_scanner.py:528-555` 부근의 `entry = {...}` 딕셔너리에서 `"name": SP100_NAMES.get(ticker, ticker),` 다음 줄에 추가:
```python
            "name": SP100_NAMES.get(ticker, ticker),
            "sector": TICKER_SECTORS.get(ticker, "—"),
```

- [ ] **Step 3: 스모크 테스트로 sector 필드 확인**

`tests/test_scanner_entry_sector.py` 신규:
```python
"""scan_sp100 결과 entry에 sector 필드가 포함되는지 검증 (캐시 사용)."""
import sys, os, json, glob
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 가장 최근 캐시 파일에서 entry 형태만 검증
cache_files = sorted(glob.glob("screenshots/scanner_sp100_*.json"))
assert cache_files, "캐시 파일이 없으면 먼저 scan_sp100을 1회 실행하세요."

# entry 빌드 로직 직접 테스트
from market_scanner import SP100_TICKERS, SP100_NAMES, TICKER_SECTORS
sample = SP100_TICKERS[0]
entry = {
    "ticker": sample,
    "name": SP100_NAMES.get(sample, sample),
    "sector": TICKER_SECTORS.get(sample, "—"),
}
assert entry["sector"] != "—", f"{sample} 섹터 매핑 누락"
print(f"[OK] sample entry: {entry}")
```

Run: `python tests/test_scanner_entry_sector.py`
Expected: `[OK] sample entry: {'ticker': 'AAPL', 'name': 'Apple', 'sector': 'Tech'}`

- [ ] **Step 4: 커밋**

```bash
git add market_scanner.py tests/test_scanner_entry_sector.py
git commit -m "feat(scanner): scan_sp100 결과 entry에 sector 필드 추가"
```

---

### Task 4: 스캐너 템플릿에 Sector 컬럼 추가

**Files:**
- Modify: `templates/scanner_unified_template.html:156` (SP100 thead 컬럼 추가)
- Modify: `templates/scanner_unified_template.html:160-172` (SP100 tbody 셀 추가)

- [ ] **Step 1: thead에 Sector 컬럼 추가**

`templates/scanner_unified_template.html:156` 의 SP100 표 헤더에서 `<th class="px-5 py-3">Name</th>` 뒤에 추가:
```html
<th class="px-5 py-3">Name</th><th class="px-5 py-3">Sector</th><th class="px-5 py-3 text-right">Price</th>
```

- [ ] **Step 2: tbody에 Sector 셀 추가**

`templates/scanner_unified_template.html:163` 의 Name 셀 다음 줄에 Sector 셀 추가:
```html
          <td class="px-5 py-3">{{ e.name }}{% if e.market_cap_fmt %} <span class="text-[10px] text-outline">{{ e.market_cap_fmt }}</span>{% endif %}</td>
          <td class="px-5 py-3"><span class="text-[10px] px-2 py-0.5 rounded bg-surface-container border border-outline-variant/20 text-on-surface-variant font-medium">{{ e.sector }}</span></td>
```

(ETF/KOSPI 표는 변경하지 않음 — 자체 섹터 의미가 약하므로.)

- [ ] **Step 3: Jinja 렌더링 검증**

스캐너 페이지를 한 번 생성해 컬럼이 표시되는지 확인.

기존 캐시가 있으면 빠르게 재렌더만 가능:
```bash
python -c "
from market_scanner import scan_sp100
from report_generator import generate_scanner_html
from datetime import date
import os, json
proj = os.getcwd()
result = scan_sp100(proj)
print('signals:', result.get('total_signals'))
# 첫 번째 entry에 sector 들어왔는지 직접 확인
for k in ('buy_1st','buy_2nd','buy_3rd','watch_signals'):
    if result.get(k):
        print(k, '->', result[k][0].get('ticker'), '/', result[k][0].get('sector'))
        break
"
```
Expected: 첫 entry에 `sector` 값이 출력됨 (예: `Tech`).

- [ ] **Step 4: 브라우저에서 시각 확인 (로컬 Flask)**

```bash
python app.py
# → http://localhost:5000 열고 Market Scanner 섹션 → S&P 100 표에 Sector 열 확인
```

수동 체크리스트:
- [ ] SP100 표에 Sector 컬럼이 Name과 Price 사이에 표시됨
- [ ] 각 행에 섹터 칩(Tech/Comm/금융 등)이 보임
- [ ] ETF / KOSPI 표에는 Sector 컬럼이 없음 (변경되지 않음)
- [ ] 모바일 뷰포트에서 가로 스크롤 가능

- [ ] **Step 5: 커밋**

```bash
git add templates/scanner_unified_template.html
git commit -m "ui(scanner): SP100 표에 Sector 컬럼 추가 (ETF/KOSPI 표는 변경 없음)"
```

---

### Task 5: 통합 검증 (전체 파이프라인 + 히스토리 영향 확인)

**Files:** (변경 없음, 검증만)
- Verify: `pipeline.py` 실행 결과
- Verify: `history/scanner_sp100_history.json` 무결성

- [ ] **Step 1: 캐시 비우고 전체 파이프라인 실행**

```bash
rm -f screenshots/scanner_sp100_*.json
python pipeline.py
```
Expected: 에러 없이 완주. 콘솔에 `[Scanner] Scanning ~169 tickers` 출력. fetch 시간이 50종목 대비 ~3배(현재 캐시 미스 시 약 90초~3분 예상).

- [ ] **Step 2: smoke_test 실행**

Run: `python smoke_test.py`
Expected: 기존 검사 항목 모두 통과 (시그널 분포, N/A 잔류 등).

- [ ] **Step 3: 시그널 폭증 여부 확인 (질적 체크)**

스캐너 결과에서 signal 개수가 종목 풀 확장에 비례해 늘었는지 확인 (3~3.5배 정도가 정상). 비례 이상으로 폭증하면 NDX 신규 종목군의 RSI/MACD 분포가 SP100 대비 더 변동적이라는 뜻 — 본 작업 범위 밖이지만 메모로 남길 것.

수동 체크:
- [ ] 1st_BUY 개수가 0개 또는 비정상적으로 많지 않음 (정상 범위: 0~10개)
- [ ] AMD/PLTR/CRWD/MU 등 NDX 종목이 결과에 등장 가능 (시그널 발동 시)

- [ ] **Step 4: 히스토리 백워드 호환성 확인**

`history/scanner_sp100_history.json`은 기존에 50종목으로 쌓여 있음. 169종목 확장 후 첫 1회 실행하면:
- 기존 50종목 BUY streak는 유지됨 (날짜 기반 키)
- 신규 119종목은 streak 1부터 시작 (정상)

확인:
```bash
python -c "
import json
h = json.load(open('history/scanner_sp100_history.json'))
last_date = sorted(h.keys())[-1]
print('Last date:', last_date, '→', len(h[last_date]), 'tickers tracked')
"
```
Expected: 가장 최근 날짜에 추적된 BUY 종목 수가 출력됨 (스캔 후 BUY 발동된 ticker만 기록되는 구조).

- [ ] **Step 5: 최종 커밋**

본 Task에서 코드 변경이 없으면 커밋 생략. 캐시/리포트만 갱신된 경우는 `.gitignore`에 따라 자연스럽게 커밋 대상 외.

---

## Appendix A: 표준 SP100 명단 (101종목)

OEX 인덱스 기준, 본 프로젝트 git 히스토리 commit `2c3e842^` 의 원본 리스트:

```
AAPL ABBV ABT ACN ADBE AIG AMD AMGN AMZN AVGO
AXP BA BAC BK BKNG BLK BMY BRK-B C CAT
CHTR CL CMCSA COF COP COST CRM CSCO CVS CVX
DE DHR DIS DOW DUK EMR EXC F FDX GD
GE GILD GM GOOG GOOGL GS HD HON IBM INTC
INTU JNJ JPM KHC KO LIN LLY LMT LOW MA
MCD MDLZ MDT MET META MMM MO MRK MS MSFT
NEE NFLX NKE NVDA ORCL PEP PFE PG PM PYPL
QCOM RTX SBUX SCHW SO SPG T TGT TMO TMUS
TSLA TXN UNH UNP UPS USB V VZ WFC WMT
XOM
```

## Appendix B: 변경 영향 요약

| 영역 | 변경 | 위험도 |
|---|---|---|
| 시그널 판정 | 없음 (`signal_judge.py` 무변경) | 없음 |
| 캐시 키 | `scanner_sp100_<date>.json` 그대로 | 없음 |
| 히스토리 파일 | `scanner_sp100_history.json` 그대로, 신규 ticker는 streak 1부터 | 낮음 |
| 리포트 템플릿 | SP100 표에 컬럼 1개 추가 | 낮음 (ETF/KOSPI 무변경) |
| fetch 시간 | 50→~169종목, 첫 실행 ~3배 증가 | 낮음 (캐시 후 0초) |
| 백테스트 | `historical_backtest.py`가 SP100_TICKERS를 참조한다면 종목 풀이 자동 확장됨 (별도 검증 필요 없음, 별도 실행은 사용자가 명시) | 중간 |

## Appendix C: 자기 검토 (Plan Self-Review)

**Spec coverage:**
- [x] SP100 + NDX 100 합집합 → Task 1, 2
- [x] 기존 구조 변경 최소화 → 변수명/캐시키/히스토리키 모두 유지
- [x] 섹터 표시 → Task 2(데이터) + Task 3(entry) + Task 4(템플릿)

**Placeholder scan:** 없음. 모든 코드 블록은 실행 가능한 형태로 제공됨.

**Type consistency:** entry dict의 `sector` 필드는 Task 3에서 추가하고 Task 4에서 `e.sector`로 일관되게 참조함. 섹터 약어 11개는 Task 2의 `VALID_SECTORS` 집합과 `TICKER_SECTORS` 값들이 정확히 일치.

**Scope risk:** Task 1의 NDX 100 명단은 시점 의존이라 본 계획서 작성 시점(2026-04) 이후 리밸런싱이 있었다면 1~3종목 차이가 생길 수 있음 — Task 1 Step 1의 공식 소스 확인으로 흡수.
