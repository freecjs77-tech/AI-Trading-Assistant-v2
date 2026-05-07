#!/usr/bin/env python3
"""
smoke_test.py -- AI Trading Assistant Smoke Test
=================================================
파이프라인 실행 후 생성된 리포트/상세페이지의 데이터 품질을 자동 검사.
독립 실행 및 pipeline.py Step 7 자동 호출 모두 지원.

검사 항목:
  1. 메인 리포트 존재 + 기본 구조
  2. 상세 페이지: N/A 잔류, 통화 오류($→₩), 차트 이미지 존재
  3. 시그널 분포 이상 (전부 HOLD 등)
  4. 판정 조건 3-튜플 렌더링 확인
"""

import sys
import os
import re
import json
import glob as glob_mod
from datetime import date


def _find_project_dir():
    """프로젝트 루트 자동 탐지"""
    d = os.path.dirname(os.path.abspath(__file__))
    if os.path.exists(os.path.join(d, "pipeline.py")):
        return d
    return os.getcwd()


def _load_html(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ═══════════════════════════════════════════════════════
#  개별 검사 함수
# ═══════════════════════════════════════════════════════

def check_main_report(reports_dir: str, today: str) -> list:
    """메인 리포트 존재 및 기본 구조 검사"""
    errors = []
    report_path = os.path.join(reports_dir, f"report_{today}.html")
    if not os.path.exists(report_path):
        errors.append(f"[CRITICAL] 메인 리포트 없음: {report_path}")
        return errors

    html = _load_html(report_path)
    size = os.path.getsize(report_path)
    if size < 10000:
        errors.append(f"[WARN] 메인 리포트 크기 의심: {size:,} bytes (< 10KB)")

    # 시그널 배지 존재 확인
    badges = re.findall(r'class="badge badge-\w+"[^>]*>([^<]+)', html)
    if len(badges) < 5:
        errors.append(f"[WARN] 시그널 배지 {len(badges)}개 (최소 5개 예상)")

    return errors


def check_detail_pages(details_dir: str, kospi_tickers: list, today: str = None) -> list:
    """상세 페이지 데이터 품질 검사 (오늘 생성된 파일만)"""
    errors = []
    pages = glob_mod.glob(os.path.join(details_dir, "*.html"))
    if not pages:
        errors.append("[CRITICAL] 상세 페이지 없음")
        return errors

    # 오늘 생성된 파일만 검사 (이전 날짜 잔여 파일 제외)
    if today:
        from datetime import datetime
        today_dt = datetime.strptime(today, "%Y-%m-%d").date()
        pages = [p for p in pages
                 if datetime.fromtimestamp(os.path.getmtime(p)).date() >= today_dt]

    for page_path in pages:
        fname = os.path.basename(page_path)
        ticker = fname.replace(".html", "")
        html = _load_html(page_path)

        # 1) 메트릭 카드 N/A 검사 (metric-value 안의 N/A)
        metric_nas = re.findall(r'metric-value[^>]*>\s*N/A\s*<', html)
        if metric_nas:
            errors.append(f"[WARN] {ticker}: 메트릭 카드 N/A {len(metric_nas)}건")

        # 2) KOSPI 통화 오류: 현재가에 $ 표시
        is_kospi = ticker.isdigit() and len(ticker) == 6
        if is_kospi:
            # 현재가 영역에서 $ 검사
            price_match = re.search(r'class="[^"]*price[^"]*"[^>]*>\s*\$', html)
            if price_match:
                errors.append(f"[ERROR] {ticker}: KOSPI 종목인데 현재가에 $ 표시")

        # 3) 차트 이미지 존재 확인
        chart_match = re.search(r'src="charts/([^"]+\.png)"', html)
        if chart_match:
            chart_file = chart_match.group(1)
            chart_path = os.path.join(details_dir, "charts", chart_file)
            if not os.path.exists(chart_path):
                errors.append(f"[ERROR] {ticker}: 차트 파일 없음 ({chart_file})")

        # 4) 판정 카드 렌더링 확인 (3-tuple)
        cards = re.findall(r'cond-card-title', html)
        descs = re.findall(r'cond-card-desc', html)
        if cards and not descs:
            errors.append(f"[WARN] {ticker}: 판정 카드 title은 있는데 desc 없음")

    return errors


def check_signal_distribution(reports_dir: str, today: str) -> list:
    """시그널 분포 이상 검사"""
    errors = []
    report_path = os.path.join(reports_dir, f"report_{today}.html")
    if not os.path.exists(report_path):
        return errors

    html = _load_html(report_path)
    signals = re.findall(r'class="badge badge-\w+"[^>]*>([^<]+)', html)

    if not signals:
        errors.append("[CRITICAL] 시그널 배지를 찾을 수 없음")
        return errors

    from collections import Counter
    dist = Counter(signals)
    total = len(signals)

    # 전부 HOLD면 의심
    if dist.get("HOLD", 0) == total:
        errors.append(f"[WARN] 모든 시그널이 HOLD ({total}개) -- 데이터 문제 가능성")

    # BUY 비율이 너무 높으면 의심 (80% 이상)
    buy_count = sum(v for k, v in dist.items() if "BUY" in k)
    if total > 5 and buy_count / total > 0.8:
        errors.append(f"[WARN] BUY 비율 과다: {buy_count}/{total} ({buy_count/total:.0%})")

    return errors


def check_scanner_pages(reports_dir: str, today: str) -> list:
    """스캐너 리포트 존재 확인"""
    errors = []
    for scanner_type in ["sp100", "etf", "kospi"]:
        path = os.path.join(reports_dir, f"scanner_{scanner_type}_{today}.html")
        if not os.path.exists(path):
            errors.append(f"[WARN] 스캐너 리포트 없음: scanner_{scanner_type}_{today}.html")
            continue
        size = os.path.getsize(path)
        if size < 5000:
            errors.append(f"[WARN] 스캐너 {scanner_type} 크기 의심: {size:,} bytes")

    return errors


def check_scanner_detail_history(details_dir: str, project_dir: str, today: str = None) -> list:
    """스캐너 상세 페이지 시그널 이력 존재 검사"""
    errors = []
    history_dir = os.path.join(project_dir, "history")

    # 스캐너 히스토리에서 이력이 있는 티커 수집
    scanner_tickers_with_history = set()
    for scanner_name in ["sp100", "etf", "kospi"]:
        hist_path = os.path.join(history_dir, f"scanner_{scanner_name}_history.json")
        if not os.path.exists(hist_path):
            continue
        try:
            with open(hist_path, "r", encoding="utf-8") as f:
                hist = json.load(f)
            for date_key, tickers in hist.items():
                for ticker in tickers:
                    scanner_tickers_with_history.add(ticker)
        except (json.JSONDecodeError, IOError):
            continue

    if not scanner_tickers_with_history:
        return errors  # 스캐너 히스토리 자체가 없으면 스킵

    # 포트폴리오 종목 (스캐너 전용 상세 페이지만 검사)
    portfolio_tickers = set()
    from portfolio_paths import primary_portfolio_path
    portfolio_path = primary_portfolio_path(project_dir)
    if os.path.exists(portfolio_path):
        with open(portfolio_path, "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\|\s*([A-Z]{1,6})\s*\|", line)
                if m and m.group(1) not in ("Ticker",):
                    portfolio_tickers.add(m.group(1).strip())

    # 스캐너 전용 상세 페이지에서 이력 테이블 존재 확인
    checked = 0
    missing_history = []
    for ticker in scanner_tickers_with_history:
        if ticker in portfolio_tickers:
            continue  # 포트폴리오 종목은 이미 별도 검사
        ticker_file = ticker.replace(".KS", "_KS") if ".KS" in ticker else ticker
        page_path = os.path.join(details_dir, f"{ticker_file}.html")
        if not os.path.exists(page_path):
            continue
        html = _load_html(page_path)
        checked += 1
        # history-row 클래스 또는 이력 테이블 존재 확인
        if "history-row" not in html and "시그널 이력" not in html and "<td>" not in html:
            missing_history.append(ticker)

    if missing_history:
        errors.append(
            f"[WARN] 스캐너 상세 페이지 이력 미표시: {', '.join(missing_history[:5])}"
            + (f" 외 {len(missing_history)-5}건" if len(missing_history) > 5 else "")
        )

    return errors


def check_market_data(screenshots_dir: str, today: str) -> list:
    """마켓 데이터 JSON 기본 검사"""
    errors = []
    json_path = os.path.join(screenshots_dir, f"market_data_{today}.json")
    if not os.path.exists(json_path):
        errors.append(f"[CRITICAL] 마켓 데이터 없음: {json_path}")
        return errors

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("_meta", {})
    ticker_count = meta.get("success", 0)
    fail_count = meta.get("fail", 0)

    if ticker_count == 0:
        errors.append("[CRITICAL] 수집 성공 종목 0개")
    if fail_count > 5:
        errors.append(f"[WARN] 수집 실패 {fail_count}개 종목")

    # 매크로 데이터
    macro = data.get("_macro", {})
    if not macro.get("VIX"):
        errors.append("[WARN] VIX 데이터 없음")
    if not macro.get("USD_KRW"):
        errors.append("[WARN] USD/KRW 데이터 없음")

    return errors


def check_portfolio_stop_signals(project_dir: str, today: str) -> list:
    """Stop signal 산출물 일관성 — JSON 있으면 페이지도 있어야."""
    errors = []
    me_json = os.path.join(project_dir, "history", "portfolio_stops.json")
    me_html = os.path.join(project_dir, "reports",
                            f"portfolio_stops_{today}.html")
    if os.path.exists(me_json):
        if not os.path.exists(me_html):
            errors.append(
                f"[WARN] portfolio_stops.json exists but page missing: "
                f"{me_html}"
            )
    # wife는 선택 — 파일 부재는 정상 (wife portfolio가 없을 수도)
    wife_json = os.path.join(project_dir, "history",
                              "portfolio_stops_wife.json")
    wife_html = os.path.join(project_dir, "reports",
                              f"portfolio_stops_wife_{today}.html")
    if os.path.exists(wife_json) and not os.path.exists(wife_html):
        errors.append(
            f"[WARN] portfolio_stops_wife.json exists but page missing: "
            f"{wife_html}"
        )
    return errors


# ═══════════════════════════════════════════════════════
#  메인 실행
# ═══════════════════════════════════════════════════════

def run_smoke_test(project_dir: str = None, today: str = None) -> dict:
    """스모크 테스트 실행. 결과 dict 반환."""
    if project_dir is None:
        project_dir = _find_project_dir()
    if today is None:
        today = date.today().strftime("%Y-%m-%d")

    reports_dir = os.path.join(project_dir, "reports")
    details_dir = os.path.join(reports_dir, "details")
    screenshots_dir = os.path.join(project_dir, "screenshots")

    # KOSPI 종목 리스트 (6자리 숫자)
    kospi_tickers = [
        f.replace(".html", "")
        for f in os.listdir(details_dir)
        if f.endswith(".html") and f.replace(".html", "").isdigit()
    ] if os.path.exists(details_dir) else []

    all_errors = []

    # 검사 실행
    checks = [
        ("Market Data", check_market_data(screenshots_dir, today)),
        ("Main Report", check_main_report(reports_dir, today)),
        ("Detail Pages", check_detail_pages(details_dir, kospi_tickers, today)),
        ("Signal Distribution", check_signal_distribution(reports_dir, today)),
        ("Scanner Pages", check_scanner_pages(reports_dir, today)),
        ("Scanner Detail History", check_scanner_detail_history(details_dir, project_dir, today)),
        ("Portfolio Stop Signals", check_portfolio_stop_signals(project_dir, today)),
    ]

    results = {}
    for name, errs in checks:
        results[name] = errs
        all_errors.extend(errs)

    # 결과 출력
    critical = [e for e in all_errors if "[CRITICAL]" in e]
    error_items = [e for e in all_errors if "[ERROR]" in e]
    warns = [e for e in all_errors if "[WARN]" in e]

    print(f"\n{'='*60}")
    print(f"  Smoke Test Results ({today})")
    print(f"{'='*60}")

    if not all_errors:
        print("  ALL PASSED -- No issues found")
    else:
        for name, errs in checks:
            if errs:
                print(f"\n  [{name}]")
                for e in errs:
                    print(f"    {e}")

    print(f"\n  Summary: {len(critical)} critical, {len(error_items)} errors, {len(warns)} warnings")
    print(f"{'='*60}\n")

    return {
        "passed": len(all_errors) == 0,
        "critical": len(critical),
        "errors": len(error_items),
        "warnings": len(warns),
        "details": results,
    }


if __name__ == "__main__":
    result = run_smoke_test()
    sys.exit(0 if result["passed"] else 1)
