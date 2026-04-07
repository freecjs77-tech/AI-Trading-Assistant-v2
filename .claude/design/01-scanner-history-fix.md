# Phase 1: 스캐너 상세 페이지 시그널 이력 수정

## 원인
1. `market_scanner.py:186-188` — 스캐너 히스토리에 `signal`만 저장, 기술지표 없음
2. `report_generator.py:808` — 스캐너 상세 페이지에 `history_rows: []` 하드코딩
3. `pipeline.py:222-231` — 스캐너 히스토리를 `generate_detail_pages()`에 미전달

## 수정 계획

### 파일 1: market_scanner.py — _update_scanner_history()
- `signal`만 저장하던 것을 `price, rsi, macd_hist, drawdown` 추가 저장
- BUY 엔트리에 이미 이 값들이 있으므로 그대로 복사

### 파일 2: report_generator.py — generate_detail_pages()
- 파라미터 3개 추가: `scanner_sp100_history`, `scanner_etf_history`, `scanner_kospi_history`
- 스캐너 엔트리 루프에서 올바른 히스토리 소스 선택 후 `_build_history_rows()` 호출
- `history_rows: []` 하드코딩 제거

### 파일 3: pipeline.py — generate_detail_pages() 호출부
- 스캐너 히스토리 JSON 3개 로드하여 전달

### 파일 4: smoke_test.py — 스캐너 상세 페이지 이력 검증 추가
- 스캐너 상세 페이지에 history-row 존재 여부 검사

## 완료 조건
- 스캐너 상세 페이지에 시그널 이력 테이블 렌더링됨
- 기존 포트폴리오 상세 페이지 동작 영향 없음
- smoke_test.py 통과
- py_compile 통과
