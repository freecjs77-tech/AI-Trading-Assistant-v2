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
            _shared_path = os.path.join(project_dir, "screenshots", f"scanner_shared_{today}.json")
            _need_prefetch = not os.path.exists(_shared_path)
            if _need_prefetch:
                _fetch_script = os.path.join(project_dir, "fetch_market_data.py")
                _env = os.environ.copy()
                _env["PYTHONIOENCODING"] = "utf-8"
                _cmd = [sys.executable, _fetch_script, "--output", _shared_path, "--quiet"] + _scan_union
                print(f"  Fetching {len(_scan_union)} unique scanner tickers in one pass...")
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
        except Exception as _pfe:
            print(f"  WARN prefetch skipped: {_pfe}")

        print("[Step 4b] Running scanners...")
        from market_scanner import scan_sp100, scan_etf, scan_kospi, scan_watchlist
        scanner_sp100_result = None
        scanner_etf_result = None
        scanner_kospi_result = None
        scanner_watchlist_result = None
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
            scanner_watchlist=scanner_watchlist_result,
            output_dir=reports_dir,
        )
        print(f"  OK {len(scanner_files)} scanner pages generated")

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
                }
                total_annual += annual_inc
                total_port_value += port_val
            port_yield = round(total_annual / total_port_value * 100, 4) if total_port_value > 0 else 0.0
            return {
                "total_annual": round(total_annual, 2),
                "monthly_avg": round(total_annual / 12, 2),
                "portfolio_yield": port_yield,
                "per_ticker": per_ticker,
                "note": "TTM 배당 합산. owner별 재계산 (pipeline.py).",
            }

        try:
            from portfolio_paths import discover_portfolios, PRIMARY_OWNER
            from fetch_market_data import parse_portfolio_md as _parse_pmd_all
            from portfolio_data import is_kospi_ticker
            _owners = [(o, p) for o, p in discover_portfolios(project_dir) if o != PRIMARY_OWNER]
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
