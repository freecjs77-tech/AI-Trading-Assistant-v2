# 프로젝트 리뷰 후속 조치 — 설계 개요

## 목적
코드 리뷰에서 발견된 보안 및 품질 이슈 수정

## 단계별 작업

### Phase 1: 보안 이슈 수정 (Critical)
1. **telegram_sender.py** — 하드코딩된 봇 토큰/채팅 ID 제거
   - 환경변수 미설정 시 에러 발생하도록 변경
   - 기존 하드코딩 폴백 값 완전 삭제

2. **app.py** — Flask 경로 탐색 방어
   - `/reports/<path:filename>` 라우트에 파일명 검증 추가
   - `report_*.html` 패턴만 허용

### Phase 2: 코드 품질 개선 (High)
3. **.gitignore** 보강
   - `.DS_Store`, `venv/`, `*.key`, `credentials.json` 등 추가

4. **requirements.txt** 버전 핀닝
   - 주요 패키지 메이저 버전 고정

### Phase 3: 안정성 개선 (Medium)
5. **history_manager.py** — `IOError` → `OSError` 수정
6. **chart_generator.py / fetch_market_data.py** — yfinance 호출 타임아웃 추가

## 영향 범위
- 수정 파일: 6개 (telegram_sender.py, app.py, .gitignore, requirements.txt, history_manager.py, chart_generator.py)
- 기능 변경 없음 (보안/안정성 개선만)
- 기존 테스트 호환성 유지
