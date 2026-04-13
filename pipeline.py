"""
pipeline.py -- Pipeline Orchestrator
AI Trading Assistant v3.0
"""

import os
import sys
import json
import subprocess
from datetime import date, datetime

# Windows cp949 stdout encoding fix
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from portfolio_data import TICKER_META
from signal_judge import judge_all
from history_manager import load_history, save_today, prune_old, save_history, get_previous_signals, backfill_prices
from report_generator import generate_report, generate_detail_pages, generate_scanner_pages, generate_backtest_page, generate_trend_page


def _load_market_data(json_path: str) -> dict:
    with open(json_path, "rb") as f:
        raw = f.read()
    return json.loads(raw.rstrip(b" \t\n\r\x00").decode("utf-8"))


def _parse_portfolio_for_report(portfolio_path: str) -> list[dict]:
    import re
    holdings = []
    row_pat = re.compile(r"^\|\s*([A-Z0-9]{1,10})\s*\|")
    shares_pat = re.compile(r"([\d,]+\.?\d*)\s*\uc8fc")
    value_pat = re.compile(r"[\$\u20a9]([\d,]+\.?\d+)")
    pnl_pat = re.compile(r"([+-])[\$\u20a9]([\d,]+\.?\d+)")

    try:
        with open(portfolio_path, "r", encoding="utf-8") as f:
            in_table = False
            for line in f:
                line = line.rstrip()
                if "| Ticker |" in line:
                    in_table = True
                    continue
                if in_table and line.startswith("|---"):
                    continue
                if in_table:
                    if not line.startswith("|"):
                        in_table = False
                        continue
                    m = row_pat.match(line)
                    if m and m.group(1) not in ("Ticker",):
                        ticker = m.group(1).strip()

                        shares = 0
                        sm = shares_pat.search(line)
                        if sm:
                            shares = float(sm.group(1).replace(",", ""))

                        values = value_pat.findall(line)
                        value = float(values[0].replace(",", "")) if values else 0

                        pnl = 0
                        pm = pnl_pat.search(line)
                        if pm:
                            pnl = float(pm.group(2).replace(",", ""))
                            if pm.group(1) == "-":
                                pnl = -pnl

                        avg_cost = (value - pnl) / shares if shares > 0 else 0

                        holdings.append({
                            "ticker": ticker,
                            "shares": shares,
                            "value": value,
                            "pnl": pnl,
                            "avg_cost": avg_cost,
                        })
    except FileNotFoundError:
        pass

    return holdings


def run_pipeline(project_dir: str, skip_ocr: bool = False, skip_fetch: bool = False, auto: bool = False) -> dict:
    today = date.today().strftime("%Y-%m-%d")
    screenshots_dir = os.path.join(project_dir, "screenshots")
    reports_dir = os.path.join(project_dir, "reports")
    history_path = os.path.join(project_dir, "history", "signals_history.json")
    portfolio_path = os.path.join(project_dir, "portfolio.md")
    json_path = os.path.join(screenshots_dir, f"market_data_{today}.json")

    try:
        # Step 1: OCR
        if not skip_ocr:
            print("[Step 1] Screenshot OCR...")
            from screenshot_ocr import extract_portfolio_from_screenshots, update_portfolio_md
            holdings_ocr = extract_portfolio_from_screenshots(screenshots_dir)
            if holdings_ocr:
                update_portfolio_md(holdings_ocr, portfolio_path)
                print(f"  OK portfolio.md updated ({len(holdings_ocr)} tickers)")
            else:
                print("  WARN OCR failed - using existing portfolio.md")
        else:
            print("[Step 1] OCR skipped (using existing portfolio.md)")

        # Step 2: fetch_market_data (--output 미지정 → 거래일 기준 파일명 자동 결정)
        if not skip_fetch or not os.path.exists(json_path):
            print("[Step 2] Fetching market data...")
            fetch_script = os.path.join(project_dir, "fetch_market_data.py")
            python_exe = sys.executable
            # --add SPY: master switch 판정에 필요 (포트폴리오에 없어도 항상 수집)
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            result = subprocess.run(
                [python_exe, fetch_script, "--add", "SPY"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode != 0:
                return {"status": "error", "error": f"fetch_market_data failed: {result.stderr[:200]}"}
            # fetch 결과에서 실제 저장된 파일 경로 탐색 (비거래일이면 직전 거래일 파일명)
            import glob
            candidates = sorted(glob.glob(os.path.join(screenshots_dir, "market_data_*.json")))
            if candidates:
                json_path = candidates[-1]
            print(f"  OK data saved -> {json_path}")
        else:
            print(f"[Step 2] Using existing JSON ({json_path})")

        # Step 4: Signal judgment
        print("[Step 4] Signal judgment...")
        market_data = _load_market_data(json_path)
        meta = market_data.get("_meta", {})
        is_trading_day = meta.get("is_trading_day", True)
        data_date = meta.get("date", today)
        if not is_trading_day:
            print(f"  *** 비거래일 (실행일: {today}) → 직전 거래일({data_date}) 데이터 사용, 히스토리 업데이트 스킵 ***")
            today = data_date
        history = load_history(history_path)
        signals = judge_all(market_data, history)

        sig_counts = {}
        for r in signals.values():
            sig = r.get("signal", "UNKNOWN")
            sig_counts[sig] = sig_counts.get(sig, 0) + 1
        print(f"  OK {len(signals)} tickers judged: {sig_counts}")

        # Step 4b: Scanner (S&P 100 + ETF + KOSPI)
        print("[Step 4b] Running scanners...")
        from market_scanner import scan_sp100, scan_etf, scan_kospi
        scanner_sp100_result = None
        scanner_etf_result = None
        scanner_kospi_result = None
        try:
            scanner_sp100_result = scan_sp100(project_dir)
            if scanner_sp100_result.get("status") != "ok":
                scanner_sp100_result = None
        except Exception as e:
            print(f"  WARN S&P 100 scanner failed: {e}")
        try:
            scanner_etf_result = scan_etf(project_dir)
            if scanner_etf_result.get("status") != "ok":
                scanner_etf_result = None
        except Exception as e:
            print(f"  WARN ETF scanner failed: {e}")
        try:
            scanner_kospi_result = scan_kospi(project_dir)
            if scanner_kospi_result.get("status") != "ok":
                scanner_kospi_result = None
        except Exception as e:
            print(f"  WARN KOSPI scanner failed: {e}")
        sp_count = (scanner_sp100_result or {}).get("total_signals", 0)
        etf_count = (scanner_etf_result or {}).get("total_signals", 0)
        kospi_count = (scanner_kospi_result or {}).get("total_signals", 0)
        print(f"  OK scanners: S&P100={sp_count}, ETF={etf_count}, KOSPI={kospi_count} signals")

        # Step 5: Report generation
        print("[Step 5] Generating report...")
        portfolio = _parse_portfolio_for_report(portfolio_path)
        prev_signals = get_previous_signals(history, today)

        report_path = os.path.join(reports_dir, f"report_{today}.html")
        generate_report(
            market_data=market_data,
            portfolio=portfolio,
            signals=signals,
            history=history,
            prev_signals=prev_signals,
            output_path=report_path,
            scanner_sp100=scanner_sp100_result,
            scanner_etf=scanner_etf_result,
            scanner_kospi=scanner_kospi_result,
        )
        size = os.path.getsize(report_path)
        print(f"  OK report -> {report_path} ({size:,} bytes)")

        # Scanner pages (별도 HTML)
        scanner_files = generate_scanner_pages(
            market_data=market_data,
            scanner_sp100=scanner_sp100_result,
            scanner_etf=scanner_etf_result,
            scanner_kospi=scanner_kospi_result,
            output_dir=reports_dir,
        )
        print(f"  OK {len(scanner_files)} scanner pages generated")

        # Step 5a: Charts + Detail pages
        print("[Step 5a] Generating charts...")
        details_dir = os.path.join(reports_dir, "details")
        charts_dir = os.path.join(details_dir, "charts")
        try:
            from chart_generator import generate_all_charts
            # 포트폴리오 + 스캐너 BUY 종목 차트 생성
            tickers_list = [p["ticker"] for p in portfolio]
            scanner_buy_tickers = []
            for sc in (scanner_sp100_result, scanner_etf_result, scanner_kospi_result):
                if sc:
                    for key in ("buy_1st", "buy_2nd", "buy_3rd"):
                        for e in sc.get(key, []):
                            t = e.get("ticker", "")
                            if t and t not in tickers_list and t not in scanner_buy_tickers:
                                scanner_buy_tickers.append(t)
            all_chart_tickers = tickers_list + scanner_buy_tickers
            chart_results = generate_all_charts(all_chart_tickers, charts_dir)
            print(f"  OK {len(chart_results)}/{len(all_chart_tickers)} charts generated")
        except Exception as e:
            print(f"  WARN Charts skipped: {e} (pipeline continues)")

        print("  Generating detail pages...")
        # 스캐너 히스토리 로드 (상세 페이지 이력 표시용)
        from market_scanner import _load_scanner_history
        _sc_sp100_hist = _load_scanner_history(project_dir, "sp100")
        _sc_etf_hist = _load_scanner_history(project_dir, "etf")
        _sc_kospi_hist = _load_scanner_history(project_dir, "kospi")

        detail_files = generate_detail_pages(
            market_data=market_data,
            portfolio=portfolio,
            signals=signals,
            history=history,
            output_dir=details_dir,
            scanner_sp100=scanner_sp100_result,
            scanner_etf=scanner_etf_result,
            scanner_kospi=scanner_kospi_result,
            scanner_sp100_history=_sc_sp100_hist,
            scanner_etf_history=_sc_etf_hist,
            scanner_kospi_history=_sc_kospi_hist,
        )
        print(f"  OK {len(detail_files)} detail pages -> {details_dir}")

        # Step 5b: Telegram notification
        print("[Step 5b] Sending Telegram notification...")
        try:
            from telegram_sender import send_report as tg_send
            tg_ok = tg_send(signals, market_data, portfolio, report_path)
            if tg_ok:
                print("  OK Telegram sent")
            else:
                print("  WARN Telegram partial/failed (pipeline continues)")
        except Exception as e:
            print(f"  WARN Telegram error: {e} (pipeline continues)")

        # Step 5c: Portfolio snapshot + Trend page
        print("[Step 5c] Saving portfolio snapshot & trend page...")
        try:
            from history_manager import save_portfolio_snapshot, load_portfolio_daily
            from portfolio_data import get_ticker_name, get_ticker_class, is_kospi_ticker

            macro = market_data.get("_macro", {})
            dividends = market_data.get("_dividends", {})
            data = market_data.get("data", {})
            usd_krw = macro.get("USD_KRW", 0)
            rate = usd_krw if usd_krw else 1

            # USD/KRW 분리 계산
            us_value = us_cost = 0
            kospi_value = kospi_cost = 0
            for p in portfolio:
                t = p["ticker"]
                price = data.get(t, {}).get("price", 0)
                val = p["shares"] * price if price else p.get("value", 0)
                cost = p["shares"] * p["avg_cost"]
                if is_kospi_ticker(t):
                    kospi_value += val
                    kospi_cost += cost
                else:
                    us_value += val
                    us_cost += cost

            total_value_krw = us_value * rate + kospi_value
            cost_basis_krw = us_cost * rate + kospi_cost

            bil = next((p for p in portfolio if p["ticker"] == "BIL"), None)
            bil_price = data.get("BIL", {}).get("price", 0)
            cash_val = bil["shares"] * bil_price if bil and bil_price else 0
            cash_krw = cash_val * rate
            cash_pct = (cash_val / (us_value + kospi_value / rate) * 100) if (us_value + kospi_value / rate) > 0 else 0

            div_annual = dividends.get("total_annual", 0)
            div_annual_krw = div_annual * rate
            div_yield = dividends.get("portfolio_yield", 0)

            # 비중 계산
            weights_cat = {}
            weights_ticker = {}
            for p in portfolio:
                t = p["ticker"]
                price = data.get(t, {}).get("price", 0)
                val = p["shares"] * price if price else p.get("value", 0)
                if is_kospi_ticker(t):
                    val_krw = val
                else:
                    val_krw = val * rate
                w = (val_krw / total_value_krw * 100) if total_value_krw > 0 else 0

                # 종목명 (KOSPI는 한글명, 미국은 티커)
                if is_kospi_ticker(t):
                    display_name = get_ticker_name(t) or t
                else:
                    display_name = t
                weights_ticker[display_name] = round(w, 1)

                cls = get_ticker_class(t) or "Other"
                weights_cat[cls] = weights_cat.get(cls, 0) + w

            weights_cat = {k: round(v, 1) for k, v in weights_cat.items()}

            portfolio_daily_path = os.path.join(project_dir, "history", "portfolio_daily.json")
            pd_data = save_portfolio_snapshot(
                path=portfolio_daily_path,
                date_str=today,
                total_value_krw=total_value_krw,
                cost_basis_krw=cost_basis_krw,
                cash_value_krw=cash_krw,
                cash_pct=cash_pct,
                div_annual_krw=div_annual_krw,
                div_yield=div_yield,
                usd_krw=usd_krw,
                vix=macro.get("VIX"),
                yield_30y=macro.get("yield_30Y"),
                master_switch=macro.get("master_switch", "UNKNOWN"),
                holdings_count=len(portfolio),
                weights_by_category=weights_cat,
                weights_by_ticker=weights_ticker,
            )
            print(f"  OK portfolio_daily.json ({len(pd_data)} days)")

            trend_path = generate_trend_page(
                portfolio_daily=pd_data,
                output_dir=reports_dir,
                date_str=today,
            )
            print(f"  OK trend page -> {trend_path}")
        except Exception as e:
            import traceback as _tb2
            _tb2.print_exc()
            print(f"  WARN trend page failed: {e} (pipeline continues)")

        # Step 6: History update (비거래일 스킵)
        if is_trading_day:
            print("[Step 6] Updating history...")
            history = save_today(history, today, signals, market_data, meta.get("ticker_source", "portfolio.md"))
            backfill_prices(history, today, include_today=auto)
            history = prune_old(history)
            save_history(history, history_path)
            print("  OK signals_history.json updated")
        else:
            print("[Step 6] 비거래일 → 히스토리 업데이트 스킵")

        # Step 6b: Backtest evaluation (portfolio + scanner histories)
        print("[Step 6b] Backtest evaluation...")
        outcomes_path = os.path.join(project_dir, "history", "outcomes.json")
        analysis_path = os.path.join(project_dir, "history", "backtest_analysis.json")
        backtest_analysis = {}
        try:
            from backtest_evaluator import evaluate_outcomes, analyze_accuracy, get_pending_signals
            scanner_histories = {
                "sp100": _sc_sp100_hist,
                "etf": _sc_etf_hist,
                "kospi": _sc_kospi_hist,
            }
            outcomes = evaluate_outcomes(history, outcomes_path, scanner_histories=scanner_histories)
            backtest_analysis = analyze_accuracy(outcomes, analysis_path)
            pending_signals = get_pending_signals(history, scanner_histories)
            print(f"  OK backtest: {backtest_analysis.get('total_records', 0)} records, status={backtest_analysis.get('data_status', 'unknown')}")

            # Backtest dashboard page
            bt_path = generate_backtest_page(
                backtest_analysis=backtest_analysis,
                outcomes=outcomes,
                pending_signals=pending_signals,
                output_dir=reports_dir,
                date_str=today,
            )
            print(f"  OK backtest page -> {bt_path}")
        except Exception as e:
            import traceback as _tb
            _tb.print_exc()
            print(f"  WARN backtest evaluation failed: {e} (pipeline continues)")

        # Step 7: Smoke test
        print("[Step 7] Running smoke test...")
        from smoke_test import run_smoke_test
        smoke_result = run_smoke_test(project_dir, today)
        if smoke_result["critical"] > 0:
            print(f"  FAIL {smoke_result['critical']} critical issues found!")
        elif smoke_result["errors"] > 0:
            print(f"  WARN {smoke_result['errors']} errors found")
        else:
            print("  OK all checks passed")

        print(f"\n=== Pipeline complete! Report: {report_path} ===")

        return {
            "status": "ok",
            "report_path": report_path,
            "signals_summary": sig_counts,
            "date": today,
            "smoke_test": smoke_result,
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    project_dir = os.path.dirname(os.path.abspath(__file__))
    result = run_pipeline(project_dir, skip_ocr="--skip-ocr" in sys.argv, skip_fetch="--skip-fetch" in sys.argv, auto="--auto" in sys.argv)
    if result["status"] != "ok":
        print(f"\nERROR: {result.get('error')}")
        sys.exit(1)
