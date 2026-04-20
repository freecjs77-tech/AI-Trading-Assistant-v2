# AI Trading Assistant v3.0

## 프로젝트 개요
개인 미국 주식 포트폴리오(18종목, ~$440K)의 일일 기술적 분석 및 시그널 리포트 자동 생성 시스템.
GitHub Pages에서 리포트를 서빙하고, GitHub Actions로 파이프라인을 자동/수동 실행한다.

## 진행 중인 계획
- [Capitol Trades 의원 거래 보조 지표 통합 V2c](docs/plans/capitol-trades-integration.md) — Politician Watchlist 독립 섹션 · Capitol Trades 스크랩 · 가중 스코어 + 별점 0-5 + 색상 (파랑=매수/빨강=매도) · 시그널 로직 불변

## 배포 (GitHub Pages + Actions)
- **리포트 URL**: https://freecjs77-tech.github.io/AI-Trading-Assistant-v2/
- **자동 실행**: 매일 UTC 21:30 (EST 16:30, KST 06:30) 평일 장마감 후
- **수동 실행**: GitHub Actions 탭 → Daily Trading Report → Run workflow
- **워크플로우**: `.github/workflows/daily-report.yml`
- **배포 스크립트**: `generate_site.py` → `deploy/` 디렉토리 생성 → gh-pages 브랜치 배포
- **히스토리 영속성**: gh-pages 브랜치에 `history/` 저장, 워크플로우 시작 시 복원
- **GitHub Secrets 필요**: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

## 로컬 개발
```bash
# 의존성 설치
pip install -r requirements.txt

# Flask 서버 시작 (로컬 개발용)
python app.py
# → http://localhost:5000 접속
```

## 파이프라인 흐름
1. portfolio.md 읽기 (수동 유지)
2. fetch_market_data.py → yfinance에서 기술지표 수집 → screenshots/market_data_YYYY-MM-DD.json
3. signal_judge.py → strategy.md v5.0 규칙으로 시그널 판정
4. report_generator.py → Jinja2 템플릿으로 HTML 리포트 생성 → reports/
5. history_manager.py → signals_history.json 이력 업데이트

## 핵심 파일 구조
```
├── app.py                    # Flask 웹서버 (GET / , POST /api/run-pipeline)
├── pipeline.py               # 파이프라인 오케스트레이터
├── signal_judge.py           # 시그널 판정 엔진 (strategy.md v5.0 코드화)
├── report_generator.py       # Jinja2 기반 HTML 리포트 생성
├── history_manager.py        # 시그널 이력 관리 (30일 유지)
├── portfolio_data.py         # 종목 메타데이터, 한글→Ticker 변환맵
├── fetch_market_data.py      # yfinance 데이터 수집기
├── screenshot_ocr.py         # 스크린샷 OCR (현재 미사용, 수동 portfolio.md 운영)
├── strategy.md               # 시그널 판정 규칙 문서 v5.3
├── portfolio.md              # 보유 종목 현황 (수동 유지)
├── templates/report_template.html  # Jinja2 리포트 템플릿
├── reports/                  # 생성된 HTML 리포트
├── screenshots/              # market_data JSON + 스크린샷 이미지
└── history/signals_history.json    # 시그널 이력
```

## 시그널 판정 규칙 (strategy.md v5.3 주요 변경사항)
- TOP_SIGNAL: 1개 충족 → **3개 중 2개 충족** (과민 반응 해소)
- BUY 2일차 확인: **거래량 조건 면제** (추세 지속성 집중)
- Exit을 익절 전용으로 재설계: L3→TAKE_PROFIT_2, L2→TAKE_PROFIT_1
- 고점 영역 게이트 추가 (DD > -5% 일 때만 TP 발동, 하락장에서는 HOLD)
- Drawdown 손절 조건 완전 삭제, MACD<0 조건 삭제 (조기 감지)
- MACD 상승 가드: 골든크로스+hist증가 시 TP 전체 면제
- L1_WARNING 삭제 (RSI≥60 과민 발동 해소)
- L3 MACD 데스크로스 강화: MACD < 0 실제 하회 + hist 3일감소 필요
- L2 RSI 다이버전스 구현 (전일 RSI 비교), 이중천장 조건 삭제 → 3개 중 2개
- Growth 거부 RSI>55 (기존 50), 2nd/3rd BUY ALL 유지
- **v5.3c 노이즈 감소**: 2nd_BUY volume 1.2x→1.5x, 3rd_BUY volume 1.3x→1.5x (백테스트 검증)
- **스캐너 종목 축소**: SP100 101→50, ETF 20→10, KOSPI 101→50 (대형주 집중)
- Value Entry 독립화 (거부 RSI>70)
- **1st BUY 통합 (v5.3b)**: Growth/ETF 동일 — 필수 4개 ALL(RSI≤45 + 가격<MA20 + MACD hist 2일증가 + DD_52w≤-15%), 선택 면제
- 스캐너(SP100/ETF)에 Exit 판정 추가 → 포트폴리오와 판정 일관성 확보
- fetch_market_data: change_3d_pct 3일 누적 변동률 추가
- history: bb_pct 필드 추가 저장

## 리포트 UI 기능
- 💱 원화 보기: USD↔KRW 통화 토글 (JS 클라이언트 사이드)
- 🔄 업데이트: Flask API 호출 → 전체 파이프라인 실행 → 자동 리로드
- Signal Reference Index: 모든 시그널의 상세 판정 조건 테이블

## 포트폴리오 업데이트 방법
portfolio.md를 직접 편집한다. 형식:
```
| Ticker | 종목명 | 보유수량 | 평가금액 | 수익금액 | 수익률 |
```
맨 아래 Ticker 목록도 함께 갱신해야 fetch_market_data가 올바른 종목을 수집한다.

## Windows 인코딩 주의
- print 문에 이모지/특수문자 사용 시 cp949 에러 발생
- pipeline.py, app.py에 `sys.stdout.reconfigure(encoding="utf-8")` 적용됨
- subprocess 실행 시 `env["PYTHONIOENCODING"] = "utf-8"` 필요

## 다른 PC에서 실행 시 필요사항
1. Python 3.10+ 설치
2. pip install yfinance pandas numpy flask jinja2
3. run_server.bat의 Python 경로를 로컬 환경에 맞게 수정 (또는 python이 PATH에 있으면 자동 탐색)
