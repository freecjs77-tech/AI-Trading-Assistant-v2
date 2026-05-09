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


def _load_momentum_history(project_dir: str, market: str) -> dict | None:
    """history/scanner_momentum_<us|kr>_history.json 로드. 없으면 None."""
    path = os.path.join(project_dir, "history", f"scanner_momentum_{market}_history.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def run_pipeline(project_dir: str, skip_ocr: bool = False, skip_fetch: bool = False, auto: bool = False) -> dict:
    today = date.today().strftime("%Y-%m-%d")
    screenshots_dir = os.path.join(project_dir, "screenshots")
    reports_dir = os.path.join(project_dir, "reports")
    history_path = os.path.join(project_dir, "history", "signals_history.json")
    from portfolio_paths import primary_portfolio_path
    portfolio_path = primary_portfolio_path(project_dir)
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
            # 다른 포트폴리오(와이프 등)의 전용 티커도 --add 로 포함 → 단일 market_data.json 공유
            from portfolio_paths import discover_portfolios, PRIMARY_OWNER
            from fetch_market_data import parse_portfolio_md as _parse_pmd
            _all_ports = discover_portfolios(project_dir)
            _me_tickers = set()
            _extra_tickers: list[str] = []
            for _owner, _ppath in _all_ports:
                _t, _ = _parse_pmd(_ppath)
                if _owner == PRIMARY_OWNER:
                    _me_tickers.update(_t)
            for _owner, _ppath in _all_ports:
                if _owner == PRIMARY_OWNER:
                    continue
                _t, _ = _parse_pmd(_ppath)
                for _sym in _t:
                    if _sym not in _me_tickers and _sym not in _extra_tickers:
                        _extra_tickers.append(_sym)
            _add_args = ["--add", "SPY"]
            for _sym in _extra_tickers:
                _add_args += ["--add", _sym]
            if _extra_tickers:
                print(f"  (포함: 타 포트폴리오 전용 티커 {len(_extra_tickers)}개 추가)")
            result = subprocess.run(
                [python_exe, fetch_script, *_add_args],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=600,
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

        # Step 4b: Scanner (S&P 100 + ETF + KOSPI + Watchlist)
        _mode = os.environ.get("MODE", "full")
        skip_scanners = (
            os.environ.get("SKIP_SCANNERS", "").lower() in ("1", "true", "yes")
            or _mode == "momentum_only"
        )
        if _mode != "full":
            print(f"[mode] MODE={_mode} (skip_scanners={skip_scanners})")
        scanner_sp100_result = None
        scanner_etf_result = None
        scanner_kospi_result = None
        scanner_watchlist_result = None
        if skip_scanners:
            print("[Step 4b] SKIP_SCANNERS=1 — 스캐너 스킵 (로컬 테스트 모드)")
        else:
            # 최적화: 4개 스캐너가 각각 fetch_market_data.py를 호출하던 기존 방식에서
            # union 티커를 한 번에 수집 → scanner_shared_{date}.json 으로 공유.
            # (각 스캐너의 _fetch_scanner_data가 이 파일을 우선 활용)
            print("[Step 4b] Prefetching scanner universe (shared cache)...")
            try:
                from market_scanner import (
                    SP100_TICKERS, ETF_TICKERS, KOSPI_TICKERS, WATCHLIST_TICKERS,
                )
                from watchlist_store import load_tickers as _load_watchlist_tickers
                _wl = []
                try:
                    _wl = _load_watchlist_tickers(project_dir) or []
                except Exception:
                    _wl = []
                if not _wl:
                    _wl = list(WATCHLIST_TICKERS)
                _scan_union = []
                _seen = set()
                for _group in (SP100_TICKERS, ETF_TICKERS, KOSPI_TICKERS, _wl):
                    for _t in _group:
                        if _t and _t not in _seen:
                            _seen.add(_t)
                            _scan_union.append(_t)
                # 포트폴리오 fetch와 스캐너 fetch가 같은 종목(AAPL 등)을 별도 시점에 호출하면
                # MACD/볼륨이 미세하게 달라져 시그널이 갈리는 문제를 방지한다.
                # → 포트폴리오에 이미 있는 종목은 prefetch에서 제외하고, 이후 portfolio data를
                #   shared cache에 병합해 동일 스냅샷을 공유한다.
                _portfolio_set = set(market_data.get("data", {}).keys())
                _to_prefetch = [_t for _t in _scan_union if _t not in _portfolio_set]
                _shared_path = os.path.join(project_dir, "screenshots", f"scanner_shared_{today}.json")
                _need_prefetch = not os.path.exists(_shared_path)
                if _need_prefetch:
                    _fetch_script = os.path.join(project_dir, "fetch_market_data.py")
                    _env = os.environ.copy()
                    _env["PYTHONIOENCODING"] = "utf-8"
                    _cmd = [sys.executable, _fetch_script, "--output", _shared_path, "--quiet"] + _to_prefetch
                    print(f"  Fetching {len(_to_prefetch)} scanner-only tickers ({len(_portfolio_set)} reused from portfolio)...")
                    _prefetch = subprocess.run(
                        _cmd, cwd=project_dir, capture_output=True, text=True,
                        timeout=900, env=_env, encoding="utf-8", errors="replace",
                    )
                    if _prefetch.returncode != 0:
                        print(f"  WARN prefetch failed ({_prefetch.stderr[:200]}) — falling back to per-scanner fetch")
                    else:
                        print(f"  OK shared cache: {_shared_path}")
                else:
                    print(f"  Using existing shared cache: {_shared_path}")

                # portfolio market_data를 shared cache에 병합 (portfolio 데이터 우선)
                # → 스캐너가 AAPL 등 portfolio 종목을 평가할 때 judge_all과 동일 스냅샷 사용
                try:
                    if os.path.exists(_shared_path):
                        with open(_shared_path, "rb") as _sf:
                            _shared = json.loads(_sf.read().rstrip(b" \t\n\r\x00").decode("utf-8"))
                    else:
                        _shared = {"data": {}, "_meta": market_data.get("_meta", {}),
                                   "_macro": market_data.get("_macro", {})}
                    _shared.setdefault("data", {})
                    _portfolio_data = market_data.get("data", {}) or {}
                    _merged = 0
                    for _t, _td in _portfolio_data.items():
                        _shared["data"][_t] = _td
                        _merged += 1
                    with open(_shared_path, "w", encoding="utf-8") as _sf:
                        json.dump(_shared, _sf, ensure_ascii=False, indent=2)
                    print(f"  OK merged {_merged} portfolio tickers into shared cache")
                except Exception as _mge:
                    print(f"  WARN portfolio merge into shared cache failed: {_mge}")
            except Exception as _pfe:
                print(f"  WARN prefetch skipped: {_pfe}")

            print("[Step 4b] Running scanners...")
            from market_scanner import scan_sp100, scan_etf, scan_kospi, scan_watchlist
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
            try:
                scanner_watchlist_result = scan_watchlist(project_dir)
                if scanner_watchlist_result.get("status") != "ok":
                    scanner_watchlist_result = None
            except Exception as e:
                print(f"  WARN Watchlist scanner failed: {e}")
            sp_count = (scanner_sp100_result or {}).get("total_signals", 0)
            etf_count = (scanner_etf_result or {}).get("total_signals", 0)
            kospi_count = (scanner_kospi_result or {}).get("total_signals", 0)
            watch_count = (scanner_watchlist_result or {}).get("total_signals", 0)
            print(f"  OK scanners: S&P100={sp_count}, ETF={etf_count}, KOSPI={kospi_count}, Watch={watch_count} signals")

        # Step 4c: Politician Trades (Capitol Trades scrape + aggregate into watchlist)
        # Independent of signal logic. Failures here must not block the rest of the pipeline
        # — fetcher/aggregator both exit 0 on error and keep stale caches.
        print("[Step 4c] Refreshing politician trades watchlist...")
        _pt_env = os.environ.copy()
        _pt_env["PYTHONIOENCODING"] = "utf-8"
        try:
            _pt_fetch = subprocess.run(
                [sys.executable, os.path.join(project_dir, "politician_trades_fetcher.py")],
                cwd=project_dir,
                env=_pt_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=900,
            )
            if _pt_fetch.returncode != 0:
                print(f"  WARN politician_trades_fetcher rc={_pt_fetch.returncode}: {_pt_fetch.stderr[:500]}")
            else:
                # last non-empty line of stdout tends to summarize
                _lines = [ln for ln in _pt_fetch.stdout.splitlines() if ln.strip()]
                if _lines:
                    print(f"  OK fetcher: {_lines[-1]}")
            _pt_agg = subprocess.run(
                [sys.executable, os.path.join(project_dir, "politician_trades_aggregator.py")],
                cwd=project_dir,
                env=_pt_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            if _pt_agg.returncode != 0:
                print(f"  WARN politician_trades_aggregator rc={_pt_agg.returncode}: {_pt_agg.stderr[:500]}")
            else:
                _lines = [ln for ln in _pt_agg.stdout.splitlines() if ln.strip()]
                if _lines:
                    # first 2 lines usually: "Wrote ...", "  watchlist: N entries ..."
                    for ln in _lines[:3]:
                        print(f"  OK aggregator: {ln}")
        except Exception as e:
            print(f"  WARN politician trades step failed ({type(e).__name__}: {e}); continuing")

        # Step 4c2: Momentum Scanner (US + KR, 독립 실행, 실패 격리)
        # 기존 strategy v5.3 시그널과 무관 — 별도 추세 추종 시그널.
        momentum_us_result = None
        momentum_kr_result = None
        _run_momentum = (_mode in ("full", "momentum_only"))
        if _run_momentum:
            print("[Step 4c2] Momentum scanners (US + KR)...")
            try:
                from momentum_scanner import scan_momentum_us, scan_momentum_kr
                try:
                    momentum_us_result = scan_momentum_us(project_dir)
                    if momentum_us_result and momentum_us_result.get("status") == "ok":
                        sigs = momentum_us_result.get("signals", {})
                        print(f"  OK [Step 4c2] Momentum US: "
                              f"M3={len(sigs.get('MOMENTUM_3', []))} "
                              f"M2={len(sigs.get('MOMENTUM_2', []))} "
                              f"M1={len(sigs.get('MOMENTUM_1', []))}")
                    elif momentum_us_result:
                        print(f"  WARN [Step 4c2] Momentum US status: "
                              f"{momentum_us_result.get('status')} "
                              f"({momentum_us_result.get('error_message', '')})")
                except Exception as e:
                    print(f"  WARN [Step 4c2] Momentum US failed: {e}")
                    momentum_us_result = None
                try:
                    momentum_kr_result = scan_momentum_kr(project_dir)
                    if momentum_kr_result and momentum_kr_result.get("status") == "ok":
                        sigs = momentum_kr_result.get("signals", {})
                        print(f"  OK [Step 4c2] Momentum KR: "
                              f"M3={len(sigs.get('MOMENTUM_3', []))} "
                              f"M2={len(sigs.get('MOMENTUM_2', []))} "
                              f"M1={len(sigs.get('MOMENTUM_1', []))}")
                    elif momentum_kr_result:
                        print(f"  WARN [Step 4c2] Momentum KR status: "
                              f"{momentum_kr_result.get('status')} "
                              f"({momentum_kr_result.get('error_message', '')})")
                except Exception as e:
                    print(f"  WARN [Step 4c2] Momentum KR failed: {e}")
                    momentum_kr_result = None
            except ImportError as e:
                print(f"  WARN [Step 4c2] momentum_scanner module unavailable: {e}")
        else:
            print(f"[Step 4c2] Skipped (MODE={_mode})")

        # Step 4c3: Portfolio Stop Signals (me)
        # 자동매매 ❌ / 매도 판단 보조 ✅. 4c3로 번호 잡아 4c2와 4d 사이.
        skip_stops = os.environ.get("SKIP_STOPS", "").lower() in ("1", "true", "yes")
        stop_result_me = None
        if skip_stops:
            print("[Step 4c3] SKIP_STOPS=1 — 포트폴리오 stop 시그널 스킵")
        else:
            print("[Step 4c3] Portfolio stop signals (me)...")
            try:
                from portfolio_stop_signal import generate_portfolio_stop_signals
                stop_result_me = generate_portfolio_stop_signals(
                    project_dir=project_dir, owner="me",
                    market_data=market_data,
                    portfolio=_parse_portfolio_for_report(portfolio_path),
                    today=today,
                )
                if stop_result_me and stop_result_me.get("status") == "ok":
                    s = stop_result_me["summary"]
                    print(f"  OK [4c3] me: HOLD={s.get('HOLD',0)} "
                          f"TIGHT={s.get('TIGHT',0)} "
                          f"EXIT_READY={s.get('EXIT_READY',0)} "
                          f"EXIT={s.get('EXIT',0)}")
            except Exception as e:
                import traceback as _tbs
                _tbs.print_exc()
                print(f"  WARN [4c3] me stop signals failed: {e}")
                stop_result_me = None

        # Step 4c4: Lifecycle US (Phase A — Trend Structure + Setup/Trigger)
        # Pure-additive. Failure must NOT block Step 5.
        skip_lifecycle = os.environ.get("SKIP_LIFECYCLE", "").lower() in ("1", "true", "yes")
        lifecycle_us_result = None
        lifecycle_kr_result = None
        if not skip_lifecycle:
            from lifecycle_signal import run_lifecycle
            _portfolio_tickers = {h["ticker"] for h in _parse_portfolio_for_report(portfolio_path)}

        if skip_lifecycle:
            print("[Step 4c4] SKIP_LIFECYCLE=1 — lifecycle US 스킵")
        else:
            print("[Step 4c4] Lifecycle US (setup/trigger/decision)...")
            try:
                _mom_us = os.path.join(project_dir, "history", "scanner_momentum_us_history.json")
                lifecycle_us_result = run_lifecycle(
                    "US", project_dir=project_dir,
                    market_data=market_data,
                    momentum_history_path=_mom_us,
                    portfolio_tickers=_portfolio_tickers,
                    today=today,
                )
                if lifecycle_us_result.get("status") == "ok":
                    n_snap = len(lifecycle_us_result["snapshots"])
                    n_trans = len(lifecycle_us_result["transitions"])
                    print(f"  OK [4c4] US: snapshots={n_snap} transitions={n_trans} "
                          f"active_set={lifecycle_us_result['active_set_size']}")
            except Exception as e:
                import traceback as _tb
                _tb.print_exc()
                print(f"  WARN [4c4] lifecycle US failed: {e}")
                lifecycle_us_result = None

        # Step 4c5: Lifecycle KR
        if skip_lifecycle:
            print("[Step 4c5] SKIP_LIFECYCLE=1 — lifecycle KR 스킵")
        else:
            print("[Step 4c5] Lifecycle KR (setup/trigger/decision)...")
            try:
                _mom_kr = os.path.join(project_dir, "history", "scanner_momentum_kr_history.json")
                lifecycle_kr_result = run_lifecycle(
                    "KR", project_dir=project_dir,
                    market_data=market_data,
                    momentum_history_path=_mom_kr,
                    portfolio_tickers=_portfolio_tickers,
                    today=today,
                )
                if lifecycle_kr_result.get("status") == "ok":
                    n_snap = len(lifecycle_kr_result["snapshots"])
                    n_trans = len(lifecycle_kr_result["transitions"])
                    print(f"  OK [4c5] KR: snapshots={n_snap} transitions={n_trans} "
                          f"active_set={lifecycle_kr_result['active_set_size']}")
            except Exception as e:
                import traceback as _tb
                _tb.print_exc()
                print(f"  WARN [4c5] lifecycle KR failed: {e}")
                lifecycle_kr_result = None

        # Step 4d: YTD benchmark (vs S&P KRW) — per owner
        print("[Step 4d] Computing YTD benchmark vs S&P (KRW)...")
        from benchmark_ytd import compute_owner_benchmark
        from portfolio_paths import discover_portfolios, PRIMARY_OWNER

        benchmark_by_owner: dict[str, dict] = {}
        try:
            me_holdings_for_bench = _parse_portfolio_for_report(portfolio_path)
            benchmark_by_owner["me"] = compute_owner_benchmark(
                holdings=me_holdings_for_bench,
                owner="me",
                project_dir=project_dir,
                market_data=market_data,
            )
            _bm = benchmark_by_owner["me"]
            if _bm.get("status") == "ok":
                print(f"  OK me: YTD={_bm['ytd_pct']:+.2f}%  S&P={_bm['spy_ytd_pct']:+.2f}%  alpha={_bm['alpha_pp']:+.2f}pp")
            else:
                print(f"  WARN me benchmark: {_bm.get('error_message', 'unknown')}")
        except Exception as _be:
            print(f"  WARN me benchmark exception: {_be}")
            benchmark_by_owner["me"] = {"status": "error", "error_message": str(_be), "ytd_pct": None, "spy_ytd_pct": None, "alpha_pp": None, "excluded_tickers": [], "anchor_date": None}

        try:
            _owners_iter = discover_portfolios(project_dir)
        except Exception as _de:
            print(f"  WARN discover_portfolios failed: {_de}")
            _owners_iter = []
        for _owner, _opath in _owners_iter:
            if _owner == PRIMARY_OWNER:
                continue
            try:
                _oholds = _parse_portfolio_for_report(_opath)
                benchmark_by_owner[_owner] = compute_owner_benchmark(
                    holdings=_oholds, owner=_owner, project_dir=project_dir,
                    market_data=market_data,
                )
                _ob = benchmark_by_owner[_owner]
                if _ob.get("status") == "ok":
                    print(f"  OK {_owner}: YTD={_ob['ytd_pct']:+.2f}%  S&P={_ob['spy_ytd_pct']:+.2f}%  alpha={_ob['alpha_pp']:+.2f}pp")
                else:
                    print(f"  WARN {_owner} benchmark: {_ob.get('error_message', 'unknown')}")
            except Exception as _be2:
                print(f"  WARN {_owner} benchmark exception: {_be2}")
                benchmark_by_owner[_owner] = {
                    "status": "error",
                    "error_message": str(_be2),
                    "ytd_pct": None,
                    "spy_ytd_pct": None,
                    "alpha_pp": None,
                    "excluded_tickers": [],
                    "anchor_date": None,
                }

        # Step 5: Report generation
        print("[Step 5] Generating report...")
        portfolio = _parse_portfolio_for_report(portfolio_path)
        prev_signals = get_previous_signals(history, today)

        # Step 5 (cont.): Stop signal page for me (fail-soft)
        stop_page_path_me = None
        if stop_result_me and stop_result_me.get("status") == "ok":
            try:
                from portfolio_stop_report import generate_portfolio_stop_page
                stop_page_path_me = generate_portfolio_stop_page(
                    stop_result_me, output_dir=reports_dir,
                )
                print(f"  OK stop page (me) -> {stop_page_path_me}")
            except Exception as e:
                print(f"  WARN stop page (me) failed: {e}")

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
            benchmark_data=benchmark_by_owner.get("me"),
            momentum_us=momentum_us_result,    # Task 21
            momentum_kr=momentum_kr_result,    # Task 21
            portfolio_stop_result=stop_result_me,
            lifecycle_us=lifecycle_us_result,
            lifecycle_kr=lifecycle_kr_result,
        )
        size = os.path.getsize(report_path)
        print(f"  OK report -> {report_path} ({size:,} bytes)")

        # Scanner pages (별도 HTML)
        scanner_files = generate_scanner_pages(
            market_data=market_data,
            scanner_sp100=scanner_sp100_result,
            scanner_etf=scanner_etf_result,
            scanner_kospi=scanner_kospi_result,
            scanner_watchlist=scanner_watchlist_result,
            output_dir=reports_dir,
        )
        print(f"  OK {len(scanner_files)} scanner pages generated")

        # Momentum pages (US + KR)
        try:
            from report_generator import generate_momentum_pages
            momentum_files = generate_momentum_pages(
                momentum_us=momentum_us_result,
                momentum_kr=momentum_kr_result,
                output_dir=reports_dir,
            )
            print(f"  OK {len(momentum_files)} momentum pages generated")
        except Exception as e:
            print(f"  WARN momentum pages failed: {e}")

        # Lifecycle pages (US + KR)
        try:
            from lifecycle_report import generate_lifecycle_pages
            _lc_paths = generate_lifecycle_pages(
                us_result=lifecycle_us_result, kr_result=lifecycle_kr_result,
                output_dir=os.path.join(project_dir, "reports"),
                us_state=(lifecycle_us_result or {}).get("state"),
                kr_state=(lifecycle_kr_result or {}).get("state"),
            )
            for m, p in _lc_paths.items():
                print(f"  Generated {m}: {p}")
        except Exception as e:
            print(f"  WARN lifecycle page render failed: {e}")

        # Step 5a: Charts + Detail pages
        print("[Step 5a] Generating charts...")
        details_dir = os.path.join(reports_dir, "details")
        charts_dir = os.path.join(details_dir, "charts")
        try:
            from chart_generator import generate_all_charts
            # 포트폴리오 + 스캐너 BUY 종목 + watchlist 전체 + secondary owner 포트폴리오 차트 생성
            tickers_list = [p["ticker"] for p in portfolio]
            extra_tickers = []
            # SP100/ETF/KOSPI 스캐너 BUY만
            for sc in (scanner_sp100_result, scanner_etf_result, scanner_kospi_result):
                if sc:
                    for key in ("buy_1st", "buy_2nd", "buy_3rd"):
                        for e in sc.get(key, []):
                            t = e.get("ticker", "")
                            if t and t not in tickers_list and t not in extra_tickers:
                                extra_tickers.append(t)
            # Watchlist 전체 (HOLD/WATCH 포함 — 상세 페이지가 all_signals 대상)
            if scanner_watchlist_result:
                for e in scanner_watchlist_result.get("all_signals", []):
                    t = e.get("ticker", "")
                    if t and t not in tickers_list and t not in extra_tickers:
                        extra_tickers.append(t)
            # 모멘텀 시그널 종목도 차트 생성 대상
            for mr in (momentum_us_result, momentum_kr_result):
                if not mr or mr.get("status") != "ok":
                    continue
                for stage in ("MOMENTUM_3", "MOMENTUM_2", "MOMENTUM_1"):
                    for e in mr.get("signals", {}).get(stage, []):
                        t = e.get("ticker", "")
                        if t and t not in tickers_list and t not in extra_tickers:
                            extra_tickers.append(t)
            # Secondary owner(wife 등) 포트폴리오 티커 — primary에 없는 것만
            try:
                from portfolio_paths import discover_portfolios, PRIMARY_OWNER as _PO
                from fetch_market_data import parse_portfolio_md as _ppmd
                for _o, _op in discover_portfolios(project_dir):
                    if _o == _PO:
                        continue
                    _ot, _ = _ppmd(_op)
                    for t in _ot:
                        if t and t not in tickers_list and t not in extra_tickers:
                            extra_tickers.append(t)
            except Exception as _oce:
                print(f"  WARN secondary owner charts enumerate failed: {_oce}")
            all_chart_tickers = tickers_list + extra_tickers
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
        _sc_watch_hist = _load_scanner_history(project_dir, "watchlist")

        detail_files = generate_detail_pages(
            market_data=market_data,
            portfolio=portfolio,
            signals=signals,
            history=history,
            output_dir=details_dir,
            scanner_sp100=scanner_sp100_result,
            scanner_etf=scanner_etf_result,
            scanner_kospi=scanner_kospi_result,
            scanner_watchlist=scanner_watchlist_result,
            scanner_sp100_history=_sc_sp100_hist,
            scanner_etf_history=_sc_etf_hist,
            scanner_kospi_history=_sc_kospi_hist,
            scanner_watchlist_history=_sc_watch_hist,
            momentum_us_history=_load_momentum_history(project_dir, "us"),    # Task 21
            momentum_kr_history=_load_momentum_history(project_dir, "kr"),    # Task 21
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

        # Step 5b momentum brief
        try:
            from telegram_sender import send_momentum_brief
            if momentum_us_result or momentum_kr_result:
                sent = send_momentum_brief(momentum_us_result, momentum_kr_result)
                if sent:
                    print("  OK momentum brief sent to Telegram")
        except Exception as e:
            print(f"  WARN momentum brief telegram failed: {e}")

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

            def _compute_owner_dividends(owner_portfolio: list) -> tuple[float, float]:
                """owner의 보유종목을 순회하며 연간 배당금(KRW 환산) 및 배당수익률(%) 계산.

                - market_data.data[ticker].div_ttm: 주당 연간 배당 (US=USD, KR=KRW)
                - KR 종목은 그대로, US 종목은 환율 적용 후 합산
                - yield = 총배당 / 평가금액(시장가) × 100  (me 로직과 일치)
                """
                ann_krw = 0.0
                mkt_krw_total = 0.0
                for p in owner_portfolio:
                    t = p["ticker"]
                    div_ttm = data.get(t, {}).get("div_ttm", 0) or 0
                    shares = p["shares"]
                    price = data.get(t, {}).get("price", 0) or 0
                    val = shares * price
                    if is_kospi_ticker(t):
                        ann_krw += shares * div_ttm
                        mkt_krw_total += val
                    else:
                        ann_krw += shares * div_ttm * rate
                        mkt_krw_total += val * rate
                y_pct = (ann_krw / mkt_krw_total * 100) if mkt_krw_total > 0 else 0
                return ann_krw, y_pct

            def _save_owner_snapshot(owner: str, owner_portfolio: list) -> dict:
                """주어진 owner의 보유종목을 KRW 통일 환산 → portfolio_daily_{owner}.json 저장."""
                us_v = us_c = 0.0
                ko_v = ko_c = 0.0
                for p in owner_portfolio:
                    t = p["ticker"]
                    price = data.get(t, {}).get("price", 0)
                    val = p["shares"] * price if price else p.get("value", 0)
                    cost = p["shares"] * p["avg_cost"]
                    if is_kospi_ticker(t):
                        ko_v += val; ko_c += cost
                    else:
                        us_v += val; us_c += cost
                total_krw = us_v * rate + ko_v
                cost_krw = us_c * rate + ko_c
                bil_p = next((p for p in owner_portfolio if p["ticker"] == "BIL"), None)
                bil_price = data.get("BIL", {}).get("price", 0)
                cash_v = bil_p["shares"] * bil_price if bil_p and bil_price else 0
                cash_k = cash_v * rate
                denom = us_v + ko_v / rate
                c_pct = (cash_v / denom * 100) if denom > 0 else 0
                # 배당/비중은 me 전용(메인) — 다른 owner는 총액·비중만 기록
                w_cat, w_tick = {}, {}
                for p in owner_portfolio:
                    t = p["ticker"]
                    price = data.get(t, {}).get("price", 0)
                    val = p["shares"] * price if price else p.get("value", 0)
                    val_k = val if is_kospi_ticker(t) else val * rate
                    w = (val_k / total_krw * 100) if total_krw > 0 else 0
                    nm = (get_ticker_name(t) or t) if is_kospi_ticker(t) else t
                    w_tick[nm] = round(w, 1)
                    cls = get_ticker_class(t) or "Other"
                    w_cat[cls] = w_cat.get(cls, 0) + w
                w_cat = {k: round(v, 1) for k, v in w_cat.items()}
                # 파일명: me는 기존 portfolio_daily.json, 그 외는 portfolio_daily_{owner}.json
                fname = "portfolio_daily.json" if owner == "me" else f"portfolio_daily_{owner}.json"
                path = os.path.join(project_dir, "history", fname)
                # 배당 계산: owner별로 직접 산정 (me/wife 공통 로직)
                # - me: fetch_market_data의 _dividends 집계 사용 (KRW 환산은 여기서)
                # - 그 외 owner: owner_portfolio 기반으로 재계산
                if owner == "me":
                    _div_ann_krw = dividends.get("total_annual", 0) * rate
                    _div_yield = dividends.get("portfolio_yield", 0)
                else:
                    _div_ann_krw, _div_yield = _compute_owner_dividends(owner_portfolio)
                _bm = benchmark_by_owner.get(owner) or {}
                return save_portfolio_snapshot(
                    path=path,
                    date_str=today,
                    total_value_krw=total_krw,
                    cost_basis_krw=cost_krw,
                    cash_value_krw=cash_k,
                    cash_pct=c_pct,
                    div_annual_krw=_div_ann_krw,
                    div_yield=_div_yield,
                    usd_krw=usd_krw,
                    vix=macro.get("VIX"),
                    yield_30y=macro.get("yield_30Y"),
                    master_switch=macro.get("master_switch", "UNKNOWN"),
                    holdings_count=len(owner_portfolio),
                    weights_by_category=w_cat,
                    weights_by_ticker=w_tick,
                    ytd_pct=_bm.get("ytd_pct"),
                    spy_ytd_pct=_bm.get("spy_ytd_pct"),
                    alpha_pp=_bm.get("alpha_pp"),
                    v0_krw=_bm.get("v0_krw"),
                    spy_v0_krw=_bm.get("spy_v0_krw"),
                )

            # me (기본) 스냅샷
            pd_data = _save_owner_snapshot("me", portfolio)
            print(f"  OK portfolio_daily.json ({len(pd_data)} days)")

            # 타 owner (wife 등) 스냅샷
            owner_daily_map = {}
            try:
                from portfolio_paths import discover_portfolios, PRIMARY_OWNER
                for _owner, _opath in discover_portfolios(project_dir):
                    if _owner == PRIMARY_OWNER:
                        continue
                    _owner_port = _parse_portfolio_for_report(_opath)
                    _odaily = _save_owner_snapshot(_owner, _owner_port)
                    owner_daily_map[_owner] = _odaily
                    print(f"  OK portfolio_daily_{_owner}.json ({len(_odaily)} days)")
            except Exception as _se:
                import traceback as _tbo
                _tbo.print_exc()
                print(f"  WARN owner snapshots failed: {_se}")

            trend_path = generate_trend_page(
                portfolio_daily=pd_data,
                output_dir=reports_dir,
                date_str=today,
                owner_daily=owner_daily_map,
            )
            print(f"  OK trend page -> {trend_path}")
        except Exception as e:
            import traceback as _tb2
            _tb2.print_exc()
            print(f"  WARN trend page failed: {e} (pipeline continues)")

        # Step 5d: 다른 포트폴리오 (wife 등) 리포트 생성
        print("[Step 5d] Generating secondary portfolio reports...")

        def _build_owner_dividends(owner_portfolio: list, mdata: dict) -> dict:
            """owner 보유 종목 기반으로 _dividends 딕셔너리 재구성.

            fetch_market_data._dividends는 me 포트 기준이므로 wife 등 다른 owner의
            리포트 생성 시에는 동일한 스키마로 owner 전용 배당 집계를 만들어
            ``_owner_market["_dividends"]``에 주입한다.

            스키마:
              { total_annual(USD), monthly_avg(USD), portfolio_yield(%),
                per_ticker: {ticker: {shares, div_per_sh, div_yield, annual_income(USD)}} }
            KOSPI 종목은 USD 환산하여 합산(me 쪽 규약과 동일).
            """
            _d = mdata.get("data", {})
            _rate = (mdata.get("_macro", {}) or {}).get("USD_KRW", 0) or 1
            total_annual = 0.0
            total_port_value = 0.0
            per_ticker: dict = {}
            for p in owner_portfolio:
                t = p["ticker"]
                info = _d.get(t) or {}
                if not info or "error" in info:
                    continue
                div_ttm = info.get("div_ttm", 0.0) or 0.0
                price = info.get("price", 0.0) or 0.0
                sh = p["shares"]
                annual_inc = round(div_ttm * sh, 2)
                port_val = round(price * sh, 2)
                if is_kospi_ticker(t) and _rate > 1:
                    annual_inc = round(annual_inc / _rate, 2)
                    port_val = round(port_val / _rate, 2)
                per_ticker[t] = {
                    "shares": sh,
                    "div_per_sh": div_ttm,
                    "div_yield": info.get("div_yield_ttm", 0.0),
                    "annual_income": annual_inc,
                    "div_source": info.get("div_source", "none"),
                }
                total_annual += annual_inc
                total_port_value += port_val
            port_yield = round(total_annual / total_port_value * 100, 4) if total_port_value > 0 else 0.0
            return {
                "total_annual": round(total_annual, 2),
                "monthly_avg": round(total_annual / 12, 2),
                "portfolio_yield": port_yield,
                "per_ticker": per_ticker,
                "note": "연간 예상 배당 (forward 우선, TTM 폴백). owner별 재계산 (pipeline.py).",
            }

        try:
            from portfolio_paths import discover_portfolios, PRIMARY_OWNER
            from fetch_market_data import parse_portfolio_md as _parse_pmd_all
            from portfolio_data import is_kospi_ticker
            _owners = [(o, p) for o, p in discover_portfolios(project_dir) if o != PRIMARY_OWNER]
            _wife_stop_results: dict = {}
            for _owner, _opath in _owners:
                _owner_tickers, _ = _parse_pmd_all(_opath)
                _owner_tickers_set = set(_owner_tickers)
                # market_data 필터: data는 owner 보유로 한정, _dividends는 owner 기준으로 재계산
                _filtered_data = {
                    k: v for k, v in market_data.get("data", {}).items()
                    if k in _owner_tickers_set
                }
                _owner_portfolio = _parse_portfolio_for_report(_opath)
                _owner_dividends = _build_owner_dividends(_owner_portfolio, market_data)
                _owner_market = {
                    **market_data,
                    "data": _filtered_data,
                    "_dividends": _owner_dividends,
                }
                _owner_history_path = os.path.join(
                    project_dir, "history", f"signals_history_{_owner}.json"
                )
                _owner_history = load_history(_owner_history_path)
                _owner_signals = judge_all(_owner_market, _owner_history)

                # Step 4c3 equivalent for secondary owner — independent state
                _owner_stop_result = None
                if not skip_stops:
                    try:
                        from portfolio_stop_signal import generate_portfolio_stop_signals
                        _owner_stop_result = generate_portfolio_stop_signals(
                            project_dir=project_dir, owner=_owner,
                            market_data=_owner_market,
                            portfolio=_owner_portfolio,
                            today=today,
                        )
                        if _owner_stop_result and _owner_stop_result.get("status") == "ok":
                            s = _owner_stop_result["summary"]
                            print(f"  OK [4c3] {_owner}: HOLD={s.get('HOLD',0)} "
                                  f"TIGHT={s.get('TIGHT',0)} "
                                  f"EXIT_READY={s.get('EXIT_READY',0)} "
                                  f"EXIT={s.get('EXIT',0)}")
                    except Exception as e:
                        print(f"  WARN [4c3] {_owner} stop signals failed: {e}")
                        _owner_stop_result = None
                _wife_stop_results[_owner] = _owner_stop_result

                # Stop signal page for secondary owner
                if _owner_stop_result and _owner_stop_result.get("status") == "ok":
                    try:
                        from portfolio_stop_report import generate_portfolio_stop_page
                        _owner_stop_page = generate_portfolio_stop_page(
                            _owner_stop_result, output_dir=reports_dir,
                        )
                        print(f"  OK stop page ({_owner}) -> {_owner_stop_page}")
                    except Exception as e:
                        print(f"  WARN stop page ({_owner}) failed: {e}")

                _owner_prev = get_previous_signals(_owner_history, today)
                _owner_report = os.path.join(
                    reports_dir, f"report_{_owner}_{today}.html"
                )
                generate_report(
                    market_data=_owner_market,
                    portfolio=_owner_portfolio,
                    signals=_owner_signals,
                    history=_owner_history,
                    prev_signals=_owner_prev,
                    output_path=_owner_report,
                    scanner_sp100=scanner_sp100_result,
                    scanner_etf=scanner_etf_result,
                    scanner_kospi=scanner_kospi_result,
                    nav_portfolio=f"report_{today}.html",
                    active_nav=_owner,
                    benchmark_data=benchmark_by_owner.get(_owner),
                    portfolio_stop_result=_owner_stop_result,
                    lifecycle_us=lifecycle_us_result,
                    lifecycle_kr=lifecycle_kr_result,
                )
                _sz = os.path.getsize(_owner_report)
                print(f"  OK {_owner} report -> {_owner_report} ({_sz:,} bytes)")
                # Owner 히스토리 업데이트 (거래일에만)
                if is_trading_day:
                    _owner_history = save_today(
                        _owner_history, today, _owner_signals, _owner_market,
                        f"portfolios/{_owner}.md",
                    )
                    backfill_prices(_owner_history, today, include_today=auto)
                    _owner_history = prune_old(_owner_history)
                    save_history(_owner_history, _owner_history_path)
                    print(f"  OK signals_history_{_owner}.json updated")

                # owner 전용 티커(primary에 없는 것)만 상세 페이지 생성
                # primary portfolio는 이미 위에서 상세 생성됨 — 중복 방지
                _primary_ticker_set = {p["ticker"] for p in portfolio}
                _owner_only_portfolio = [
                    p for p in _owner_portfolio
                    if p["ticker"] not in _primary_ticker_set
                ]
                if _owner_only_portfolio:
                    try:
                        _owner_details = generate_detail_pages(
                            market_data=_owner_market,
                            portfolio=_owner_only_portfolio,
                            signals=_owner_signals,
                            history=_owner_history,
                            output_dir=details_dir,
                        )
                        print(f"  OK {_owner} detail pages: {len(_owner_details)} generated")
                    except Exception as _dpe:
                        print(f"  WARN {_owner} detail pages failed: {_dpe}")
        except Exception as e:
            import traceback as _tb_sec
            _tb_sec.print_exc()
            print(f"  WARN secondary portfolio reports failed: {e} (pipeline continues)")

        # Portfolio Risk Telegram (Step 5d 끝난 후 wife 결과 합산해서 1회 발송)
        try:
            from telegram_sender import send_portfolio_risk_summary
            _base_url = os.environ.get(
                "REPORT_BASE_URL",
                "https://freecjs77-tech.github.io/AI-Trading-Assistant-v2",
            )
            _wife_stop = (_wife_stop_results or {}).get("wife")
            send_portfolio_risk_summary(
                stop_me=stop_result_me,
                stop_wife=_wife_stop,
                base_url=_base_url,
                date_str=today,
            )
        except Exception as e:
            print(f"  WARN portfolio risk telegram failed: {e} (pipeline continues)")

        try:
            from telegram_sender import send_lifecycle_brief
            _base = os.environ.get("REPORT_BASE_URL",
                                  "https://freecjs77-tech.github.io/AI-Trading-Assistant-v2/")
            send_lifecycle_brief(lifecycle_us_result, lifecycle_kr_result,
                                  base_url=_base, date_str=today)
        except Exception as e:
            print(f"  WARN lifecycle telegram brief failed: {e}")

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
