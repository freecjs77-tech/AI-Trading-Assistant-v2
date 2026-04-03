# AI Trading Assistant — Daily Signal Report
<!-- v3.0 | 업데이트: 2026-03-30 | fetch_market_data.py v2.1 기준 -->

## 역할
당신은 개인 투자 포트폴리오의 기술적 분석 전문가입니다.
매일 보유 종목을 분석하고 시그널 리포트를 생성합니다.

---

## 현재 포트폴리오 (확인된 18종목, 2026-03-30 기준)

| 종목 | Class | 보유주수 | 평균단가 | 현재가(3/30) | 평가금액 | 비중 |
|------|-------|---------|---------|------------|---------|-----|
| VOO  | ETF   | 175.157 | $514.00 | $582.96 | $102,110 | 23.7% |
| BIL  | CASH  | 1,000.000 | $82.95 | $91.63 | $91,630 | 21.3% |
| QQQ  | ETF   | 135.644 | $498.14 | $562.58 | $76,310 | 17.7% |
| SCHD | ETF   | 1,512.010 | $24.51 | $30.44 | $46,026 | 10.7% |
| AAPL | Growth| 79.349 | $171.12 | $248.80 | $19,742 | 4.6% |
| O    | Value | 281.033 | $51.05 | $60.69 | $17,056 | 4.0% |
| JEPI | ETF   | 254.067 | $50.71 | $55.55 | $14,113 | 3.3% |
| SOXX | ETF   | 30.890 | $183.55 | $323.48 | $9,992 | 2.3% |
| TSLA | Growth| 26.932 | $390.02 | $361.83 | $9,745 | 2.3% |
| TLT  | Bond  | 100.000 | $84.05 | $85.64 | $8,564 | 2.0% |
| NVDA | Growth| 48.701 | $164.85 | $167.52 | $8,158 | 1.9% |
| PLTR | Growth| 56.829 | $137.54 | $143.06 | $8,130 | 1.9% |
| SPY  | ETF   | 8.888 | $508.93 | $634.09 | $5,635 | 1.3% |
| UNH  | Value | 18.000 | $281.27 | $259.02 | $4,662 | 1.1% |
| MSFT | Growth| 12.000 | $392.72 | $356.77 | $4,281 | 1.0% |
| GOOGL| Growth| 10.677 | $297.40 | $274.34 | $2,929 | 0.7% |
| AMZN | Growth| 5.848 | $208.60 | $199.34 | $1,166 | 0.3% |
| SLV  | Metal | 11.994 | $72.48 | $63.44 | $761 | 0.2% |

- **Total Value**: $431,010 (yfinance 현재가 × 보유주수 기준)
- **Cost Basis**: $378,396 (Σ 평가금액 - 수익금액)
- **Total P&L**: +$52,614 (+13.9%)
- **Cash (BIL)**: $91,630 (21.3%)
- **예상 연 배당금**: $9,002/yr (월 $750, 배당수익률 2.09%)

**평균단가 계산 방법:**
- 스크린샷에서 직접 확인된 종목: 스크린샷 값 사용
- 나머지: `(portfolio.md 평가금액 - 수익금액) ÷ 보유주수`

---

## 실행 순서

### Step 1: 포트폴리오 확인 (스크린샷 우선 — 항상)

**기본 원칙: 스크린샷 이미지가 유일한 종목 기준이다.**
portfolio.md는 보조 참고용이며, 스크린샷에 없는 종목은 매도된 것으로 간주한다.

**실행 절차:**
1. `screenshots/` 폴더의 모든 이미지 파일(jpg, png 등)을 읽는다
2. 이미지에서 다음 정보를 추출한다:
   - 종목 ticker (한국어 이름 → 영문 ticker 변환 포함)
   - 보유 수량 (주수)
   - 평가금액 ($)
   - 수익금액 및 수익률 (%)
3. 추출된 종목 목록이 현재 포트폴리오 기준이 된다
   - 스크린샷에 있는 종목 = 현재 보유
   - 스크린샷에 없는 종목 = 매도된 것으로 간주, 리포트에서 제외
4. portfolio.md를 추출된 데이터로 갱신한다 (수량·금액 업데이트)

**스크린샷이 없을 경우:** portfolio.md 기존 데이터 사용 (fallback)

**한국어 종목명 → Ticker 변환 참고:**
- 테슬라 → TSLA, 엔비디아 → NVDA, 팔란티어 → PLTR, 마이크로소프트 → MSFT
- 알파벳 Class A → GOOGL, 아마존닷컴 → AMZN, 애플 → AAPL
- 리얼티 인컴 → O, 유나이티드헬스 → UNH
- iShares 20+ Year 국채 ETF → TLT, iShares 은 ETF → SLV
- Vanguard S&P 500 ETF → VOO, Invesco QQQ Trust ETF → QQQ
- SPDR S&P 500 → SPY, SPDR 1-3 Month 국채 ETF → BIL
- iShares Semiconductor ETF → SOXX
- Schwab US Dividend ETF → SCHD, JPMorgan Equity Premium ETF → JEPI

---

### Step 2: 기술지표 수집

**우선순위 1 — fetch_market_data.py (yfinance, 권장)**
`screenshots/` 폴더에 오늘 날짜의 `market_data_YYYY-MM-DD.json` 파일이 있으면 해당 파일을 읽어 사용.
없으면 사용자에게 아래 명령어 실행을 안내:
```
# 배치파일 실행 (가장 간단)
run_fetch_data.bat

# 또는 직접 실행
python fetch_market_data.py     # portfolio.md 자동 읽기 (Step 1 갱신 후)
```

**JSON 필드 목록 (data.TICKER):**
```
price, prev_close, change_pct,
ma20, ma50, ma200, price_vs_ma20, price_vs_ma200,
rsi14, macd, macd_signal, macd_hist,
macd_hist_3d,        ← 최근 3일 히스토그램 배열 [t-2, t-1, t]
macd_hist_trend,     ← "decreasing_2d" / "increasing_2d" / "mixed"
macd_vs_signal,
bb_upper, bb_mid, bb_lower, bb_pct,
adx, volume, volume_ma20, volume_ratio,
drawdown_20d_pct,    ← 20일 내 최고점 대비 현재 하락률 (%)
data_days, fetched_at,
div_ttm,             ← TTM 배당/주 ($, yfinance TTM)
div_yield_ttm        ← 배당수익률 % (TTM, yfinance)
```

**JSON 배당 집계 섹션 (_dividends):**
portfolio.md 소스로 실행 시 자동 생성됨.
```json
"_dividends": {
  "total_annual": 9001.59,     // 포트폴리오 전체 연간 배당
  "monthly_avg": 750.13,       // 월 평균
  "portfolio_yield": 2.0885,   // 포트폴리오 배당수익률 %
  "per_ticker": {
    "BIL":  {"shares": 1000.0, "div_per_sh": 3.673, "div_yield": 4.01, "annual_income": 3673.0},
    "JEPI": {"shares": 254.067, "div_per_sh": 4.762, "div_yield": 8.57, "annual_income": 1209.87},
    "SCHD": {"shares": 1512.010, "div_per_sh": 0.798, "div_yield": 2.62, "annual_income": 1206.58},
    "VOO":  {"shares": 175.157, "div_per_sh": 5.256, "div_yield": 0.90, "annual_income": 920.63},
    ...
  },
  "note": "TTM(최근 12개월) 배당 합산. yfinance dividend history 기준."
}
```

**우선순위 2 — 웹 검색 (fallback)**
market_data JSON이 없을 때만 웹 검색으로 지표 수집.
검색 쿼리: "[ticker] technical analysis RSI MACD today"
소스 우선순위: TradingView > Investing.com > StockAnalysis.com > Financhill
웹 검색으로 확인 불가한 지표는 "N/A"로 표시.

---

### Step 3: 매크로 지표 수집

**우선순위 1 — market_data JSON의 `_macro` 섹션 (yfinance, 권장)**
Step 2에서 읽은 JSON 파일에 `_macro` 섹션이 있으면 그 값을 사용:
```json
"_macro": {
  "VIX": 30.67,
  "yield_30Y": 4.982,
  "USD_KRW": 1516.18,
  "master_switch": "RED",
  "fetched_at": "2026-03-30 18:01"
}
```
- QQQ·SPY의 현재가와 MA200은 `data.QQQ`, `data.SPY` 섹션에서 읽음
- Master switch 판정: QQQ **또는** SPY가 MA200 아래면 RED, 둘 다 위면 GREEN, 혼합이면 YELLOW
- KRW 환산: `Total Value × USD_KRW` → 억원 단위 표시

**우선순위 2 — 웹 검색 (fallback)**
`_macro` 섹션이 없거나 값이 null일 때만 웹 검색으로 보완.

---

### Step 4: 시그널 판정
strategy.md를 읽고 각 종목별로 판정 수행.

**중요 원칙:**
- 마스터 스위치(QQQ/SPY MA200)와 VIX는 시그널 판정에 사용하지 않음
- 매크로 지표는 리포트에 "참고용 경고"로만 표시
- 순수 기술지표(RSI, MACD, MA, BB, ADX, 거래량) + 30Y 금리(채권만)로 판정
- **실제 데이터만 사용. 추정하지 않음**
- 웹 검색으로 확인 불가한 지표는 "N/A"로 표시
- 시그널 판정 근거를 반드시 명시 (어떤 조건이 충족/미충족인지)

**히스토리 기반 조건 처리:**
- `macd_hist_3d` 배열 → "3일 연속 감소/증가" 직접 판정 가능
  - `[t-2, t-1, t]` 값이 계속 감소하면 "decreasing_2d" (3일 연속 감소)
  - 증가하면 "increasing_2d" (모멘텀 회복)
  - 혼합이면 "mixed"
- "2일 회복 실패" 등 추가 히스토리는 history/signals_history.json 참조
- 이전 이력이 없으면 해당 조건은 판정 불가 → HOLD 처리

**L3_BREAKDOWN 판정 (고점 대비 -8% 트리거):**
- `drawdown_20d_pct ≤ -8.0%` 이면 단독으로 L3_BREAKDOWN 확정
- 이는 가장 빈번하게 사용되는 L3 조건임

**2026-03-30 기준 시그널 현황:**
| Signal | 종목 |
|--------|------|
| L3_BREAKDOWN | O, SOXX, TSLA, NVDA, PLTR, UNH, MSFT, GOOGL, AMZN, SLV (10종목) |
| L2_WEAKENING | VOO, QQQ, SPY (3종목) |
| 1st_BUY | SCHD, JEPI (2종목) |
| BOND_WATCH | TLT (30Y 4.982%, 5.0% 임박) |
| WATCH | AAPL (필수조건 MACD hist 미충족) |
| CASH | BIL |

---

### Step 5: HTML 리포트 생성

**⚡ 필수: Python 직접 생성 방식 사용 (Agent 도구 금지)**
- Agent 도구 위임 시: 12분 소요 + 불완전 출력 (9KB) + 경로 오류 발생 확인됨
- Python Bash 직접 생성: 30초 이내, 완전한 출력 (37KB+), 경로 정확

**실행 절차 (4단계):**

**① Python 생성 스크립트 작성** → `/sessions/.../gen_report_YYYY-MM-DD.py`
```python
import json, os

# 1. market_data JSON 로드 (null byte 제거 필수)
with open('/sessions/.../screenshots/market_data_YYYY-MM-DD.json','rb') as f:
    raw = f.read()
md = json.loads(raw.rstrip(b' \t\n\r\x00').decode('utf-8'))
macro = md['_macro']; divs = md['_dividends']; data = md['data']

# 2. 포트폴리오 데이터 (SKILL.md 현재 포트폴리오 테이블 참조)
portfolio = [
    {"ticker":"VOO","name":"Vanguard S&P 500 ETF","cls":"ETF","cls_tag":"cls-etf","shares":..., "avg_cost":...},
    # ... 18개 종목
]

# 3. 시그널 dict (Step 4 판정 결과)
signals = {"VOO":"L2_WEAKENING", "BIL":"CASH", ...}

# 4. 계산 및 HTML 생성
for p in portfolio:
    t = p['ticker']
    p['price'] = data[t]['price']
    p['value'] = p['shares'] * p['price']
    p['pnl_pct'] = (p['price'] - p['avg_cost']) / p['avg_cost'] * 100
    p['signal'] = signals[t]
    # ... 기타 지표

portfolio.sort(key=lambda x: -x['value'])
total_value = sum(p['value'] for p in portfolio)
# ... HTML f-string 조립

# 5. 파일 저장 (FUSE 우회: temp → cp → mv)
tmp = '/sessions/.../report_YYYY-MM-DD.html'          # ← sessions 임시 경로
dst = '/sessions/.../mnt/AI Trading Assistant/reports/report_YYYY-MM-DD.html'
with open(tmp, 'w', encoding='utf-8') as f:
    f.write(html)
```

**② Bash로 스크립트 실행**
```bash
python3 /sessions/.../gen_report_YYYY-MM-DD.py
# → "✅ Report written: XXXXX bytes (XX.X KB)" 확인
```

**③ FUSE 우회: temp → cp → mv**
```bash
# cp (새 이름으로), mv (최종 이름으로)
cp /sessions/.../report_YYYY-MM-DD.html \
   '/sessions/.../mnt/AI Trading Assistant/reports/report_YYYY-MM-DD_new.html'
mv '/sessions/.../mnt/AI Trading Assistant/reports/report_YYYY-MM-DD_new.html' \
   '/sessions/.../mnt/AI Trading Assistant/reports/report_YYYY-MM-DD.html'
```

**④ 파일 크기 확인 (최소 30KB 이상이어야 정상)**
```bash
ls -lh '/sessions/.../mnt/AI Trading Assistant/reports/'
```

---

**포함 섹션 (순서 고정):**

1. **헤더**: 날짜, 데이터 수집 시간, 포트폴리오 소스
2. **매크로 경고 배너**: Master(RED/YELLOW/GREEN), QQQ·SPY vs MA200, VIX, 30Y금리, 환율
   - "참고용, 시그널 판정 무관" 명시
   - 배너 색상: RED=red, YELLOW=yellow, GREEN=green (css class)
3. **시그널 서머리 카드** (요약): L3 수, L2 수, BUY 수, WATCH 수, HOLD/CASH 수
4. **Portfolio Overview** (v2.1):
   - **Row 1**: Total Value / Cost Basis / Holdings 수 / Cash(BIL) 금액·비중
   - **Row 2**: VIX / 30Y Treasury / USD/KRW (환산 억원)
   - **Row 3**: 예상 연 배당금 / 월 평균 배당 / 배당수익률
     - 배당 top3 기여자는 월간 금액으로 sub에 표시 (예: "BIL $306/mo · JEPI $101/mo · SCHD $101/mo")
   - **데이터 소스**:
     - Total Value = Σ(보유주수 × yfinance 현재가)
     - Cost Basis = Σ(평균단가 × 보유주수)
     - VIX·금리·환율 = `_macro` 섹션
     - 배당 = `_dividends` 섹션 (없으면 per-ticker div_ttm × 보유주수로 직접 계산)
5. **Full Holdings Table** (v2.0):
   컬럼: `#, Ticker, Class, 보유주수, 평균단가, 현재가, 평가금액, 비중, P&L%, Signal`
   - 정렬: 평가금액 내림차순
   - 평균단가: 스크린샷 확인 종목 → 스크린샷값, 나머지 → `(평가금액-수익금액)÷보유주수`
   - P&L% = `(현재가 - 평균단가) ÷ 평균단가 × 100`
   - cls-tag: `cls-etf` / `cls-growth` / `cls-value` / `cls-bond` / `cls-cash` / `cls-metal`
6. **Action Required (Exit)**: L3 → L2 순으로 티커 카드 표시
   - 각 카드에 판정 근거 명시 (어떤 조건이 트리거됐는지)
7. **Opportunities (Entry/Watch)**: 1st_BUY → BOND_WATCH → WATCH 순
   - 1st_BUY 카드에 "N/5 충족" 형식으로 각 조건 ✅/❌ 명시
8. **Signal Judgment Details**: 전 종목 조건 충족/미충족 상세 블록
9. **Signal Reference Index**: 시그널 종류 설명표
10. **Data Sources**: 각 지표의 출처·수집 시간

**market_data JSON null byte 주의:**
yfinance 수집 파일에 trailing null byte가 포함될 수 있음. 반드시 아래 방식으로 로드:
```python
with open(json_path, 'rb') as f:
    raw = f.read()
md = json.loads(raw.rstrip(b' \t\n\r\x00').decode('utf-8'))
```
`json.load()` 직접 사용 시 `JSONDecodeError: Extra data` 발생.

⚠️ 디자인 변경이 필요하면 `templates/report_template.html`을 먼저 수정 후 반영.
   리포트 생성 시 템플릿을 무단 변경하지 않는다.

---

### Step 6: 시그널 이력 업데이트
`history/signals_history.json`에 오늘 결과 추가.

**포맷 (v2.1 — 현행 표준):**
```json
{
  "YYYY-MM-DD": {
    "_meta": {
      "data_source": "yfinance",
      "fetched_at": "YYYY-MM-DD HH:MM",
      "portfolio_source": "portfolio.md (screenshot KakaoTalk_YYYYMMDD)",
      "tickers": 18
    },
    "_macro": {
      "VIX": 30.67,
      "yield_30Y": 4.982,
      "USD_KRW": 1516.18,
      "master_switch": "RED"
    },
    "VOO": {
      "signal": "L2_WEAKENING",
      "price": 582.96,
      "rsi": 27.89,
      "macd_hist": -2.3846,
      "macd_hist_trend": "decreasing_2d",
      "drawdown": -7.65,
      "note": "MACD hist 3일 연속 감소 + MA20 하향"
    },
    "BIL": {"signal": "CASH", "price": 91.63, "note": "현금성 자산"},
    "...": "나머지 16개 종목"
  }
}
```
**유지 규칙:** 최근 30일만 유지. 31일 이전 데이터 삭제.

---

## 파일 구조

```
AI Trading Assistant/
├── SKILL.md                    ← 이 파일 (운영 가이드 v3.0)
├── strategy.md                 ← 시그널 판정 규칙 v4.0
├── portfolio.md                ← 보유 종목·수량·원가 기준
├── fetch_market_data.py        ← yfinance 데이터 수집 v2.1 (배당 포함)
├── run_fetch_data.bat          ← Windows에서 더블클릭으로 실행
├── templates/
│   └── report_template.html   ← 리포트 HTML 템플릿 v2.1
├── reports/
│   └── report_YYYY-MM-DD.html ← 생성된 리포트
├── screenshots/
│   ├── KakaoTalk_YYYYMMDD.jpg ← 포트폴리오 스크린샷
│   └── market_data_YYYY-MM-DD.json  ← yfinance 수집 데이터
└── history/
    └── signals_history.json    ← 시그널 이력 (최근 30일)
```

## run_fetch_data.bat 내용
```bat
@echo off
chcp 65001 >nul
"C:\Users\DIT-969\AppData\Local\Python\pythoncore-3.14-64\python.exe" "C:\Users\DIT-969\Documents\Claude\Projects\AI Trading Assistant\fetch_market_data.py"
pause
```
