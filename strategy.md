# Signal Decision Rules v5.3b — 익절 전용 판정 로직

## 핵심 원칙
- 시그널은 순수 기술지표로만 판정
- **시장 필터(Master switch, VIX 등)는 사용자가 참고하는 용도** — 판정에 사용하지 않음
- 30Y 금리는 채권 전략에서만 사용
- BLOCKED 시그널 없음 — 어떤 시장 상황에서도 BUY 가능
- **확실한 매수 타이밍**: 과매도 확인 + 반전 확인 + 2일 연속 유지
- **Exit 시그널은 고점에서 익절용으로만 사용** — 하락장에서는 절대 매도하지 않고 HOLD로 버팀 (손절 없음)

---

## 시그널 종류

### Entry (진입)
| 시그널 | 의미 | 비중 | 확정 기준 |
|--------|------|------|----------|
| **1st_BUY** | 과매도 바닥에서 첫 진입 | 20% | 2일 연속 |
| **2nd_BUY** | 바닥 확인 + 반전 확인 | 30% | 2일 연속 |
| **3rd_BUY** | 추세 전환 확정 | 50% | 2일 연속 |

### Observation (관찰)
- **WATCH**: 진입 조건 일부 충족 → 관찰 중
- **BOND_WATCH**: 채권 금리 트리거 직전 (30Y 4.9~5.0%)

### Neutral (중립)
- **HOLD**: 보유 유지, 특별한 액션 없음
- **CASH**: 현금성 자산 (BIL 등)

### Exit (익절) — 즉시 발동, 연속일 확인 없음
| 시그널 | 의미 | 조치 |
|--------|------|------|
| **TOP_SIGNAL** | 강한 과열 | 즉시 일부 익절 |
| **TAKE_PROFIT_2** | 상승 종료 신호 | 대량 익절 (50%) |
| **TAKE_PROFIT_1** | 상승 둔화 | 1차 익절 (30%) |

---

## 판정 우선순위

```
1. Entry 체크 (3rd → 2nd → 1st) — BUY 발동 시 즉시 리턴 (Exit보다 우선)
2. Exit 체크 (BUY 미발동 시에만)
   2a. TOP_SIGNAL — 3개 중 2개 충족 시 발동
   2b. 고점 영역 게이트 (DD > -5%) 통과 시:
       - TAKE_PROFIT_2 체크
       - TAKE_PROFIT_1 체크
3. WATCH (Entry 조건 일부 충족)
4. 해당 없으면 HOLD
```

---

## BUY 연속일 확인 제도

### 목적
하루 반짝 시그널(노이즈)을 걸러내고, **확실한 매수 타이밍**만 포착.

### 규칙
| 항목 | 내용 |
|------|------|
| **확정 기준** | BUY 시그널이 **2일 연속** 유지 |
| **1일차** | 시그널 표시 + `확인 대기 1/2일 ⏳` 배지 |
| **2일차+** | `확정 N일 연속 ✅` 배지 → **실제 매수 고려** |
| **2일차 면제** | 전일 BUY였으면 **거래량(volume_ratio) 조건 면제** (추세 지속성 집중) |
| **승격** | 1st→2nd→3rd 전환 시 연속 누적 (조건이 강화된 것이므로) |
| **리셋** | BUY 해제(WATCH/HOLD/Exit 전환) 시 카운트 초기화 |
| **Exit** | 연속일 확인 **없이 즉시 발동** (자본 보호 우선) |

### 연속일 판정 예시

| 어제 | 오늘 | streak | 확정? | 이유 |
|------|------|--------|-------|------|
| HOLD | 1st_BUY | 1 | ⏳ 대기 | 첫 발동 |
| 1st_BUY | 1st_BUY | 2 | ✅ 확정 | 2일 유지 |
| 1st_BUY | 2nd_BUY | 2 | ✅ 확정 | 상위 승격 = 강화 |
| 2nd_BUY | 3rd_BUY | 3 | ✅ 확정 | 계속 승격 |
| 2nd_BUY | 1st_BUY | 2 | ✅ 확정 | 하위지만 BUY 연속 |
| 2nd_BUY | WATCH | 0 | ❌ 리셋 | BUY 해제 |
| L3 | 1st_BUY | 1 | ⏳ 대기 | 전일 Exit이라 새 시작 |

### 적용 범위
- 포트폴리오 리포트 BUY 카드
- SP100 스캐너 BUY 카드
- ETF 스캐너 BUY 카드
- KOSPI 스캐너 BUY 카드

### 이력 저장
| 저장소 | 대상 |
|--------|------|
| `history/signals_history.json` | 포트폴리오 (buy_streak, buy_confirmed 필드) |
| `history/scanner_sp100_history.json` | SP100 스캐너 |
| `history/scanner_etf_history.json` | ETF 스캐너 |
| `history/scanner_kospi_history.json` | KOSPI 스캐너 |

---

## MACD 가드 체계

### _is_macd_bullish: 골든크로스 + hist 증가
```
MACD > signal AND hist_trend contains "increasing"
→ 모멘텀 회복 중
```

### hist_recovering: hist 증가 중 (골든크로스 불문)
```
hist_trend contains "increasing"
→ 하락 모멘텀 둔화 중
```

### 가드 적용 범위

| Exit 조건 | 고점 게이트 | MACD bullish | hist recovering | 가드 효과 |
|-----------|:---------:|:-----------:|:---------------:|----------|
| **TOP_SIGNAL** | 없음 | 없음 | 없음 | 과열은 무조건 발동 |
| **TP2 ① MA20 이탈** | DD > -5% | 면제 | 면제 | 반등 중이면 억제 |
| **TP2 ② Higher Low** | DD > -5% | 면제 | 면제 | 반등 중이면 억제 |
| **TP2 ③ MACD 데스크로스** | DD > -5% | — | — | 자체 필터링 |
| **TP1 전체** | DD > -5% | 전체 면제 | 전체 면제 | 모멘텀 회복 중이면 억제 |

---

## 고점 영역 게이트 (v5.2 신규)

```
DD = drawdown_20d_pct (20일 고점 대비 하락률)
DD > -5% → 고점 근처 → TP 시그널 허용
DD ≤ -5% → 이미 하락 → HOLD (바닥에서 안 팜)
```

TOP_SIGNAL은 게이트 없이 항상 발동 (과열은 무조건).

---

## Exit(익절) 판정 상세

> Exit 시그널은 고점에서 익절용으로만 사용한다.
> 시장 필터는 사용자가 참고하는 용도이며, 판정에 개입하지 않는다.

### 전체 흐름 (v5.4: BUY 우선)
```
① Entry 체크 (3rd → 2nd → 1st) → BUY 발동 시 즉시 리턴
   ↓ BUY 미발동
② TOP_SIGNAL 체크 → 3개 중 2개 충족 시 발동 (게이트/가드 없음)
   ↓ 미발동
③ 고점 영역 게이트: DD > -5% 인가?
   ↓ No → HOLD (이미 하락 중, 바닥에서 안 팜)
   ↓ Yes
④ MACD 가드: hist 회복 중(increasing) 또는 MACD bullish 인가?
   ↓ Yes → HOLD (반등 중, 안 팜)
   ↓ No
⑤ TAKE_PROFIT_2 조건 체크 (1개라도 충족 → 대량 익절 50%)
   ↓ 미발동
⑥ TAKE_PROFIT_1 조건 체크 (2/3 충족 → 1차 익절 30%)
   ↓ 미발동
⑦ WATCH (Entry 조건 일부 충족)
⑧ 해당 없으면 HOLD
```

### TOP_SIGNAL — 강한 과열 [3개 중 2개 충족]
- 고점 게이트: **없음** (과열은 무조건 발동)
- MACD 가드: **없음**

| 조건 | 임계값 | 데이터 소스 |
|------|--------|-----------|
| RSI 과열 | RSI ≥ 75 | `rsi14` |
| BB 상단 2일 연속 | bb_pct > 100 이 오늘 + 전일 모두 충족 | `bb_pct` + 전일 history `bb_pct` |
| 3일 급등 | change_3d_pct ≥ +10% | `change_3d_pct` |

### TAKE_PROFIT_2 — 상승 종료 신호, 대량 익절 50% [1개 충족]
- 고점 게이트: **DD > -5% 필수** (drawdown_20d_pct)
- MACD 가드: **①② 적용** (bullish 또는 hist recovering이면 면제)

| # | 조건 | 세부 | MACD 가드 |
|---|------|------|----------|
| ① | MA20 이탈 2일 + hist 감소 | 오늘+전일 price_vs_ma20=="below" AND macd_hist_trend에 "decreasing" 포함 | bullish/recovering → 면제 |
| ② | Higher Low 붕괴 | double_bottom에서 저점2 > 저점1 (Higher Low 형성) AND 현재가 < 저점2 | bullish/recovering → 면제 |
| ③ | MACD 데스크로스 + hist 감소 | MACD < signal AND macd_hist_trend에 "decreasing" 포함 (MACD < 0 불필요) | 자체 필터링 (hist 감소 필요) |

### TAKE_PROFIT_1 — 상승 둔화, 1차 익절 30% [3개 중 2개]
- 고점 게이트: **DD > -5% 필수**
- MACD 가드: **전체 적용** (bullish 또는 hist recovering이면 전체 면제)

| # | 조건 | 세부 |
|---|------|------|
| ① | MACD hist 3일 감소 | macd_hist_trend에 "decreasing" 포함 |
| ② | RSI 다이버전스 | 전일 RSI > 금일 RSI AND 둘 다 ≥ 50 (고점 영역 하락) |
| ③ | MA20 1일 이탈 | price_vs_ma20 == "below" |

---

## Entry 판정 — Growth v5.3b

### 대상: NVDA, TSLA, PLTR, AAPL, MSFT, GOOGL, AMZN + KOSPI 성장주

### 거부 조건
| 조건 | 적용 범위 |
|------|----------|
| 당일 -5% 이상 급락 | **전 단계** 매수 금지 |
| RSI > 55 | **1st BUY에만** 적용 (2nd/3rd는 추세 확인 단계라 면제) |

### 1st BUY (20%) — 과매도 바닥 진입
```
[필수 4개 ALL]
  ① RSI ≤ 45          (과매도 확인)
  ② 가격 < MA20        (조정 확인)
  ③ MACD hist 2일 증가  (반전 시작)
  ④ 52주 고점 대비 DD ≤ -15%  (충분한 조정 확인)
```

### 2nd BUY (30%) — 반전 확인
```
[ALL 4개 충족]
  ① 이중 바닥 확인     (diff ≤ 3% 이내만 유효)
  ② RSI > 35          (과매도 탈출)
  ③ MACD 골든크로스    (MACD > signal 필수, hist 증가만으로 불충분)
  ④ 거래량 ≥ 1.5x     (매수세 동반)
```

### 3rd BUY (50%) — 추세 확정
```
[ALL 4개 충족]
  ① 가격 > MA20       (추세 복귀)
  ② MACD > 0 + 골든크로스 (MACD > signal)  (완전 양전환)
  ③ 거래량 ≥ 1.5x     (강한 매수세)
  ④ RSI > 55          (상승 모멘텀 확인)

[추가 거부] RSI > 75 → 과열 구간 진입 금지
```

### WATCH 판정
- 1st BUY 필수 4개 조건 중 3개 이상 충족 시 WATCH

### 단계 간 에스컬레이션 흐름
```
과매도(RSI≤45) + 조정(DD≤-15%) + 반전시작(hist↑)
    ↓ 1st BUY (20%)
이중바닥 + 골든크로스 + 거래량 1.5x
    ↓ 2nd BUY (30%)
MA20 위 + MACD 0선돌파 + RSI>55 + 거래량 1.5x
    ↓ 3rd BUY (50%)
```

---

## Entry 판정 — ETF v5.3b

### 대상: VOO, QQQ, SCHD, SOXX, JEPI, SPY + KOSPI ETF

### 거부 조건
RSI > 70 → 전 단계 매수 금지

### 1st BUY (20%) — 확실한 조정에서 진입
```
[필수 4개 ALL]  ← v5.3b: Growth와 동일 구조로 통합
  ① RSI ≤ 45          (과매도 확인)
  ② 가격 < MA20        (조정 확인)
  ③ MACD hist 2일 증가  (반전 시작)
  ④ 52주 고점 대비 DD ≤ -15%  (충분한 조정 확인)
```

### 2nd BUY (30%) — Pick 3 of 4
```
  · RSI > 42
  · MACD > Signal (골든크로스)
  · 종가 > MA20
  · Higher Low 형성 (단기 하락멈춤 + 중기 저점 상승)
```

### 3rd BUY (50%) — ALL 충족
```
  ① 종가 > MA20       (추세 복귀)
  ② RSI > 55          (상승 모멘텀)
  ③ MACD > 0 + 골든크로스 (MACD > signal)  (완전 양전환)
```

### WATCH 판정
1st BUY 필수 4개 조건 중 3개 이상 충족 시 WATCH

---

## Entry 판정 — Value v5.3b

### 대상: O (Realty Income), UNH (UnitedHealth), 005380 (현대차)

Growth v5.3b와 동일 구조.
**차이점**: RSI 거부 임계값 55 → **70** (Value 종목은 RSI 변동폭이 작으므로)

---

## Entry 판정 — Bond v2.6

### 채권 (TLT)
| 단계 | 조건 |
|------|------|
| **1st BUY** | 30Y 금리 ≥ 5.0% AND RSI ≤ 35 |
| **2nd BUY** | 30Y 금리 ≥ 5.2% OR MACD 골든크로스 |
| **3rd BUY** | TLT > MA20 2일 유지 AND 30Y 금리 피크 대비 하락 전환 |
| **BOND_WATCH** | 30Y 금리 4.9~5.0% (트리거 직전) |

---

## Entry 판정 — Metal v2.6

### 금/은 (SLV, GLD)
| 단계 | 조건 |
|------|------|
| **1st BUY** | Pick 2/4: RSI≤40 / MA20 아래 / VIX>25 / BB 하단 근접 |
| **2nd BUY** | Pick 2/4: MACD>Signal / RSI>42 / Higher Low / MA20 평탄화 |
| **3rd BUY** | Pick 2/3: 종가>MA20 2일 / MA20 상승 / MACD>0 |

금 포트폴리오 상한: 5~10%. RSI > 80 시 TOP_SIGNAL 강제.

### BIL (현금성)
항상 **CASH**. 별도 판정 없음.

---

## Entry 판정 — Speculative

### 대상: QLD, SOXL, ETHU, CRCL, XLE, XLF, NKE

Growth v5.3b 로직 동일 적용.
소액 종목($500 미만)은 판정 후 "소액 — 관망" 코멘트 추가.

---

## 스캐너 판정

### 공통 적용 사항
- Entry 전에 **간이 Exit 체크** (`check_exit_simple`) 수행
  - TOP_SIGNAL, TP2(MACD 데스크로스), TP1(hist감소+MA20이탈) — 고점 게이트 적용
  - prev_day 없이 판정 가능한 조건만 (MA20 2일 이탈 등은 스킵)
  - Exit 시그널이면 Entry 스캔 대상에서 **제외**
- **BUY 연속일** 관리: 스캐너별 전용 history JSON에 저장

### 스캐너별 적용 규칙
| 스캐너 | Entry 규칙 | Exit 체크 | 연속일 |
|--------|-----------|----------|--------|
| **SP100** `/scanner` | Growth v5.3b | ✅ | `scanner_sp100_history.json` |
| **ETF** `/scanner-etf` | ETF v5.3b | ✅ | `scanner_etf_history.json` |
| **KOSPI** (메인 리포트 내) | Growth v5.3b | ✅ | `scanner_kospi_history.json` |

---

## 시장 필터 — 사용자 참고용 (판정에 사용하지 않음)

> 시장 필터는 사용자가 참고하는 용도이며, 시그널 판정에 개입하지 않는다.

| 지표 | 리포트 표시 | 시그널 판정 | 사용자 참고 포인트 |
|------|-----------|-----------|-----------------|
| Master switch (QQQ/SPY vs MA200) | 경고 배너 (RED/YELLOW/GREEN) | ✗ 판정 미사용 | RED면 신규 매수 신중 검토 |
| VIX 수준 | 매크로 표시 (현재값 + 단계) | ✗ 판정 미사용 | VIX > 25면 변동성 주의 |
| USD/KRW 환율 | 원화 환산 표시 | ✗ 판정 미사용 | 환율 변동 참고 |
| 30Y Treasury yield | 매크로 표시 | ✗ 채권 전략에서만 사용 | 금리 방향성 참고 |

---

## 변경 이력

### v5.4 (현재)
- **BUY 우선 판정**: Entry(BUY) → Exit(TOP/TP2/TP1) → WATCH → HOLD
  - BUY 조건 충족 시 Exit 체크 없이 즉시 BUY 발동
  - BUY 미발동 시에만 Exit 체크 (기존: Exit 먼저 체크)
  - 추세 반전 시 BUY 조건이 먼저 무너지므로 Exit은 자연스럽게 발동

### v5.3b
- **1st BUY 조건 통합 개편** (Growth/ETF 동일):
  - 필수 4개 ALL: RSI≤45 + 가격<MA20 + MACD hist 2일증가 + DD_52w≤-15%
  - 선택 조건 면제 (필수 4개로 충분한 필터링)
  - RSI 38→45 완화 (V자 반등 조기 포착), DD_52w≤-15% 게이트로 보상
- **2nd/3rd BUY 거래량 기준 강화**: 2nd 1.2x→**1.5x**, 3rd 1.3x→**1.5x** (백테스트 검증)
- **WATCH 판정 통합**: 1st BUY 필수 4개 중 3개 충족 시 WATCH

### v5.3
- TOP_SIGNAL 발동 기준 완화: 1개 충족 → **3개 중 2개 충족** (과민 반응 해소)
- BUY 2일차 확인: **거래량(volume_ratio) 조건 면제** (거래량 스파이크 1일 소멸 대응, 추세 지속성 집중)

### v5.2
- Exit을 익절 전용으로 재설계 (고점 영역 게이트: DD > -5% 일 때만 발동)
- L3_BREAKDOWN → TAKE_PROFIT_2, L2_WEAKENING → TAKE_PROFIT_1 이름 변경
- Drawdown 기반 손절 조건 완전 삭제 (L3④ 제거, L3① DD조건 제거)
- MACD 데스크로스: MACD < 0 조건 삭제 (0선 근처 조기 감지)
- 하락장에서는 Exit 미발동 → HOLD로 버팀

### v5.1c
- TOP_SIGNAL: BB 상단 2일 연속 구현 (bb_pct > 100 이 2일 연속, 전일 history 참조)
- L3②: Higher Low 하향 돌파 구현 (double_bottom 저점 데이터 활용, bullish/hist recovering 가드)
- L3② + L2: hist recovering 가드 확장 (모멘텀 회복 중이면 Exit 면제 → 보유 우선)

### v5.1b
- BUY 연속일 확인 제도 추가 (2일 연속 → 확정)
- Growth 1st BUY: 필수 3개(RSI≤38 + MA20이탈 + hist증가) + 선택 2/3
- Growth 2nd BUY: 이중바닥 diff≤3% + MACD 골든크로스 필수
- Growth 3rd BUY: MACD 골든크로스+0선돌파 + RSI>55
- ETF 1st BUY: 필수 RSI≤35 + DD≤-5%
- ETF 3rd BUY: ALL(MA20위 + RSI>55 + 골든크로스+0선돌파)
- RSI 거부를 1st BUY에만 적용 (2nd/3rd 면제 — 3rd RSI>55 모순 해소)
- 스캐너 전체에 Exit 체크 + BUY 연속일 적용 (SP100/ETF/KOSPI)

### v5.1
- MACD 상승 가드 도입 (골든크로스+hist증가 → L2 전체면제, L3 ①④ 면제)
- hist recovering 가드 추가 (hist 증가만으로도 L3 ①④ 면제)
- L1_WARNING 삭제
- L3 MACD 데스크로스 강화 (MACD<0 필수 + hist 3일감소)
- L2 RSI 다이버전스 구현, 이중천장 조건 삭제
- Value Entry 독립화 (거부 RSI>70)
- 스캐너에 Exit 판정 추가 (포트폴리오와 일관성)
- fetch_market_data: change_3d_pct 추가
- history: bb_pct 필드 추가
