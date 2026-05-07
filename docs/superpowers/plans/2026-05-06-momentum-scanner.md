# Market Momentum Scanner v1.0 — Implementation Plan

**Date**: 2026-05-06
**Status**: Implemented (Tasks 1-25 complete)
**Owner**: freecjs77@gmail.com
**Spec**: [docs/superpowers/specs/2026-05-06-momentum-scanner-design.md](../specs/2026-05-06-momentum-scanner-design.md)

## Summary

Step 4c2 신규 추가 — 기존 저점매수 스캐너와 병렬로 동작하는 추세 추종형 모멘텀 스캐너.
US와 KR 별도 스캐너, IWB 1000 + KODEX 200/KOSDAQ 150 universe, M1/M2/M3 + Risk Tags + Streak/Change,
leg 백테스트 + 연속 손실 alert, momentum_us/kr.html + Telegram brief.
기존 strategy v5.3 시그널에 무영향.

## Tasks

| # | 파일 | 설명 | 상태 |
|---|------|------|------|
| 1 | `momentum_config.py` | 상수·파라미터 중앙 관리 | Done |
| 2 | `momentum_universe.py` | IWB 1000 / KODEX 200·KOSDAQ 150 universe 빌더 | Done |
| 3 | `momentum_data.py` | yfinance bulk fetch + 섹터 보유 종목 조회 | Done |
| 4 | `momentum_signal.py` | 섹터 평가 / 종목 pre-filter / stage 분류 / evaluate_stock | Done |
| 5 | `momentum_history.py` | streak·change·MDD 추적 / JSON 히스토리 I/O | Done |
| 6 | `momentum_backtest.py` | leg 추출 / +3d/+5d/+10d 집계 / 연속 손실 alert | Done |
| 7 | `momentum_scanner.py` | scan_momentum_us / scan_momentum_kr entry points | Done |
| 8 | `templates/momentum_us.html` | US 모멘텀 페이지 템플릿 | Done |
| 9 | `templates/momentum_kr.html` | KR 모멘텀 페이지 템플릿 | Done |
| 10 | `report_generator.py` | generate_momentum_pages 추가 | Done |
| 11 | `telegram_sender.py` | _format_momentum_message / send_momentum_brief 추가 | Done |
| 12 | `pipeline.py` | Step 4c2 모멘텀 스캔 + Step 5 통합 | Done |
| 13 | `.github/workflows/daily-report.yml` | momentum history 복원 + concurrency 추가 | Done |
| 14-24 | `tests/` | 단위 + 통합 + golden + E2E 테스트 | Done |
| 25 | `CLAUDE.md` + `tests/test_e2e_momentum_smoke.py` | 최종 통합 · 등록 · E2E 스모크 | Done |
