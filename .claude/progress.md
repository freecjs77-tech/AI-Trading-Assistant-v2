# 진행 상태

## 완료: 스캐너 백필 - yfinance 실제 종가 조회 (2026-04-07)

### 문제
과거 히스토리에 `price: null`로 저장된 항목을 현재 가격으로 백필하여 매수 시뮬레이션 수익률이 항상 0%로 표시

### 수정 파일 1개
1. **market_scanner.py**
   - `_extract_close()` 신규 — yfinance DataFrame에서 특정 날짜/티커 종가 추출 (주말/휴일→이전 거래일 fallback)
   - `_backfill_missing_prices()` 신규 — price=None 항목을 yfinance 실제 종가로 백필
   - `_apply_streak_to_entries()` 수정 — 기존 현재가 백필 → yfinance 백필 호출
   - `_update_scanner_history()` 수정 — 기존 현재가 백필 → yfinance 백필 호출

### 상태
- py_compile 통과
- 단독 백필 테스트: ETF 16/16건 실제 종가 백필 성공 (XLF $49.53 등)
- 파이프라인 실행은 미완 (GitHub Actions 또는 수동 실행 필요)

---

## 완료: 스캐너 상세 페이지 시그널 이력 수정 (2026-04-07)

### 수정 파일 4개
1. **market_scanner.py** — `_update_scanner_history()`에서 `price, rsi, macd_hist, drawdown` 추가 저장
2. **report_generator.py** — `generate_detail_pages()`에 스캐너 히스토리 3개 파라미터 추가, 스캐너별 티커 매핑으로 `_build_history_rows()` 연결
3. **pipeline.py** — `_load_scanner_history()` 호출하여 스캐너 히스토리를 `generate_detail_pages()`에 전달
4. **smoke_test.py** — `check_scanner_detail_history()` 검사 추가

### 상태
- py_compile 4개 파일 전부 통과
- smoke_test.py 실행 완료 — 새 검사 항목 정상 작동
- 기존 이력 데이터(signal만)도 호환됨 (price=0, rsi=None 표시)
- 다음 파이프라인 실행 시 기술지표 포함 히스토리가 저장됨

### 참고
- 오늘(4/7) 파이프라인 미실행이라 Market Data/Main Report CRITICAL은 정상
- KOSPI $ 표시 ERROR는 기존 이슈 (이번 수정 범위 밖)

---

## 완료: 스캐너 BUY 카드 가상 수익률 표시 (2026-04-07)

### 수정 파일 2개
1. **market_scanner.py** — `_calc_hypothetical_return()` 함수 추가, `_apply_streak_to_entries()`에서 호출하여 entry에 `hypo_return` 삽입
2. **templates/scanner_template.html** — Jinja2 매크로 `hypo_return_box()` 정의, 1st/2nd/3rd BUY 카드 3곳에 적용

### 표시 형태
```
📊 매수 시뮬레이션
 1일차 매수 ($95.20, 04-03):  +3.45%
 확정 매수 ($96.10, 04-04):   +2.49%
```

### 상태
- py_compile 통과
- Jinja2 렌더링 테스트 통과 (테스트 데이터로 확인)
- 히스토리에 price 없는 기존 데이터는 자동 미표시 (graceful)
- 커밋 `96bccc5` 푸시 완료
