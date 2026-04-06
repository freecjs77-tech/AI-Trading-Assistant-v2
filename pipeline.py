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
from history_manager import load_history, save_today, prune_old, save_history, get_previous_signals
from report_generator import generate_report, generate_detail_pages, generate_scanner_pages


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


def run_pipeline(project_dir: str, skip_ocr: bool = False, skip_fetch: bool = False) -> dict:
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

        # Step 2: fetch_market_data
        if not skip_fetch or not os.path.exists(json_path):
            print("[Step 2] Fetching market data...")
            fetch_script = os.path.join(project_dir, "fetch_market_data.py")
            python_exe = sys.executable
            # --add SPY: master switch 판정에 필요 (포트폴리오에 없어도 항상 수집)
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            result = subprocess.run(
                [python_exe, fetch_script, "--output", json_path, "--add", "SPY"],
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
            print(f"  OK data saved -> {json_path}")
        else:
            print(f"[Step 2] Using existing JSON ({json_path})")

        # Step 4: Signal judgment
        print("[Step 4] Signal judgment...")
        market_data = _load_market_data(json_path)
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

        print("  Generating detail pages...")
        detail_files = generate_detail_pages(
            market_data=market_data,
            portfolio=portfolio,
            signals=signals,
            history=history,
            output_dir=details_dir,
            scanner_sp100=scanner_sp100_result,
            scanner_etf=scanner_etf_result,
            scanner_kospi=scanner_kospi_result,
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

        # Step 6: History update
        print("[Step 6] Updating history...")
        meta = market_data.get("_meta", {})
        history = save_today(history, today, signals, market_data, meta.get("ticker_source", "portfolio.md"))
        history = prune_old(history)
        save_history(history, history_path)
        print("  OK signals_history.json updated")

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
    result = run_pipeline(project_dir, skip_ocr="--skip-ocr" in sys.argv, skip_fetch="--skip-fetch" in sys.argv)
    if result["status"] != "ok":
        print(f"\nERROR: {result.get('error')}")
        sys.exit(1)
