# Phase 2: 스캐너 BUY 카드에 가상 수익률 표시

## 기능 설명
스캐너 BUY 종목 카드에 "이 시그널에 매수했다면 현재 수익률은?" 표시.
- **1일차 매수**: BUY 시그널 최초 발생일 가격 기준 수익률
- **2일 연속 확정 매수**: 2일 연속 BUY 확정 시점 가격 기준 수익률

## 데이터 소스
- `history/scanner_{sp100|etf|kospi}_history.json`에 날짜별 `price` 저장됨
- 기존 데이터(4/3, 4/4)는 price 없음 → 다음 실행부터 저장 시작 (이전 수정에서 반영)
- `_calc_scanner_streak()`가 이미 연속일을 역추적하므로 같은 로직 활용

## 수정 대상 파일

### 파일 1: `market_scanner.py` — 가상 수익률 계산 함수 추가
```python
def _calc_hypothetical_return(ticker, current_price, history, today_str):
    """
    BUY 시그널 연속 구간에서 1일차/2일차 매수 가상 수익률 계산.
    반환: {
        "day1_price": float,   # 1일차(최초 BUY) 가격
        "day1_date": str,      # 1일차 날짜
        "day1_return": float,  # 1일차 매수 수익률 %
        "day2_price": float,   # 2일차(확정) 가격 (없으면 None)
        "day2_date": str,
        "day2_return": float,
    }
    """
```
- 히스토리를 역순 탐색하여 현재 BUY 연속 구간의 시작점 찾기
- 1일차 = 연속 구간 첫 날, 2일차 = 그 다음 날
- 가격 데이터 없으면 None 반환

### 파일 2: `market_scanner.py` — `_apply_streak_to_entries()`에서 수익률 계산 호출
- 기존 streak/confirmed 계산 후 `_calc_hypothetical_return()` 호출
- entry에 `hypo_return` 딕셔너리 추가

### 파일 3: `templates/scanner_template.html` — BUY 카드에 수익률 표시 UI
```
가격 아래에:
┌─────────────────────────────────┐
│ 📊 매수 시뮬레이션               │
│ 1일차 매수 ($95.20, 4/1):  +3.4%│
│ 확정 매수 ($96.10, 4/2):  +2.5% │
└─────────────────────────────────┘
```
- 수익률 양수: 녹색, 음수: 빨간색
- 가격 데이터 없으면 해당 행 미표시

### 파일 4: `report_generator.py` — `generate_scanner_pages()`에 히스토리 전달
- pipeline에서 이미 로드한 스캐너 히스토리를 scanner_pages에도 전달
- 또는 market_scanner.py의 entry 생성 시점에 수익률 계산 (더 깔끔)

## 설계 결정: entry 생성 시점에 계산 (파일 4 불필요)
- `market_scanner.py`의 `_apply_streak_to_entries()`에서 수익률을 entry에 직접 추가
- 이미 history 객체를 갖고 있으므로 추가 전달 불필요
- 템플릿에서는 entry의 값을 바로 표시

## 수정 파일 최종 정리
| # | 파일 | 변경 |
|---|------|------|
| 1 | `market_scanner.py` | `_calc_hypothetical_return()` 함수 추가 |
| 2 | `market_scanner.py` | `_apply_streak_to_entries()`에서 호출, entry에 추가 |
| 3 | `templates/scanner_template.html` | BUY 카드에 수익률 UI 추가 |

## 완료 조건
- BUY 카드에 1일차/확정 매수 수익률이 색상 코딩으로 표시됨
- 가격 데이터 없는 기존 히스토리는 graceful 처리 (미표시)
- py_compile 통과
- 기존 카드 레이아웃/기능 영향 없음
