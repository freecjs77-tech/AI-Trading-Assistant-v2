"""
Market Momentum Scanner — entry points (US, KR).

scan_momentum_us(project_dir) / scan_momentum_kr(project_dir):
  1. Universe 구축 (Tasks 4-8)
  2. yfinance bulk fetch (Task 7)
  3. 종목별 indicator 보강 (price, MA, RSI, MACD trend 등 — yfinance 직접 또는 fetch_market_data 재사용)
  4. 섹터 ETF momentum 평가 (Task 9), Top N 선택
  5. Top sectors 종목 → pre-filter (Task 10) → classify_stage (Task 10) → evaluate_stock (Task 11)
  6. History 업데이트 (Task 12)
  7. Backtest 재집계 (Tasks 13-14)
  8. Return result dict
"""
import os, sys, json, time
from datetime import datetime, timezone, timedelta

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import momentum_config as cfg
import momentum_data as md
from momentum_universe import build_us_universe, build_kr_universe, fetch_daily_movers_for
import momentum_signal as msig
import momentum_history as mh
import momentum_backtest as mb


def _today_kst() -> str:
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")


def _lookup_name(ticker: str, market: str) -> str:
    """Ticker → 종목명. 못 찾으면 ticker 그대로 반환.

    KR: market_scanner.KOSPI_NAMES (한글)
    US: market_scanner.SP100_NAMES + ETF_NAMES + WATCHLIST_NAMES (영문, best effort)
    """
    try:
        if market == "KR":
            from market_scanner import KOSPI_NAMES
            return KOSPI_NAMES.get(ticker, ticker)
        # US: try multiple name sources
        from market_scanner import SP100_NAMES, ETF_NAMES, WATCHLIST_NAMES
        for src in (SP100_NAMES, ETF_NAMES, WATCHLIST_NAMES):
            if ticker in src:
                return src[ticker]
        return ticker
    except ImportError:
        return ticker


def _empty_result(market: str, status: str = "ok",
                  error_message: str | None = None) -> dict:
    return {
        "market": market,
        "version": cfg.VERSION,
        "as_of": _today_kst(),
        "scanned_count": 0,
        "top_sectors": [],
        "signals": {"MOMENTUM_3": [], "MOMENTUM_2": [], "MOMENTUM_1": []},
        "backtest_summary": None,
        "status": status,
        "error_message": error_message,
    }


def _fetch_indicators(tickers: list[str]) -> dict[str, dict]:
    """
    yfinance 사용해 ticker별 momentum indicator 산출.

    Returns: {ticker: {ret_3d_pct, ret_5d_pct, rsi14, macd_hist_trend,
                        close, ma20, ma50, high_20d, high_52w, volume_ratio,
                        change_pct, ret_20d_pct}}
    """
    if not tickers:
        return {}
    out: dict[str, dict] = {}
    closes, volumes = md.fetch_yf_bulk(tickers, period="90d")
    if closes is None or closes.empty:
        return {}

    import pandas as pd

    def _safe(x):
        try:
            v = float(x)
            return v if v == v else None
        except (TypeError, ValueError):
            return None

    for t in closes.columns:
        s = closes[t].dropna()
        if len(s) < 21:
            continue
        last = float(s.iloc[-1])
        prev = float(s.iloc[-2])
        prev3 = float(s.iloc[-4]) if len(s) >= 4 else None
        prev5 = float(s.iloc[-6]) if len(s) >= 6 else None
        prev20 = float(s.iloc[-21]) if len(s) >= 21 else None
        ma20 = float(s.iloc[-20:].mean())
        ma50 = float(s.iloc[-50:].mean()) if len(s) >= 50 else None
        # RSI14 — Wilder's
        deltas = s.diff().dropna()
        ups = deltas.where(deltas > 0, 0)
        dns = (-deltas).where(deltas < 0, 0)
        ru = ups.tail(14).mean()
        rd = dns.tail(14).mean()
        rsi = 100 - (100 / (1 + (ru / rd))) if rd > 0 else 100
        # MACD hist trend (3일)
        ema12 = s.ewm(span=12, adjust=False).mean()
        ema26 = s.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        sig_line = macd.ewm(span=9, adjust=False).mean()
        hist = macd - sig_line
        if len(hist) >= 3:
            h1, h2, h3 = float(hist.iloc[-3]), float(hist.iloc[-2]), float(hist.iloc[-1])
            macd_trend = "rising" if h1 < h2 < h3 else ("falling" if h1 > h2 > h3 else "flat")
        else:
            macd_trend = "flat"
        # 거래량 비율
        vol_ratio = None
        if t in volumes.columns:
            v = volumes[t].dropna()
            if len(v) >= 21:
                vol_ratio = float(v.iloc[-1]) / float(v.tail(20).mean()) if v.tail(20).mean() > 0 else None
        # high
        high_20d = float(s.tail(20).max())
        high_52w_window = s.tail(252) if len(s) >= 252 else s
        high_52w = float(high_52w_window.max())
        ema_fields = md.compute_ema_fields(s)

        out[t] = {
            "ticker": t,
            "close": last, "ma20": ma20, "ma50": ma50,
            "rsi14": rsi, "macd_hist_trend": macd_trend,
            "high_20d": high_20d, "high_52w": high_52w,
            "volume_ratio": vol_ratio if vol_ratio is not None else 1.0,
            "change_pct": round((last / prev - 1) * 100, 2) if prev > 0 else None,
            "ret_3d_pct": round((last / prev3 - 1) * 100, 2) if prev3 else None,
            "ret_5d_pct": round((last / prev5 - 1) * 100, 2) if prev5 else None,
            "ret_20d_pct": round((last / prev20 - 1) * 100, 2) if prev20 else None,
            "ema9": ema_fields["ema9"],
            "ema21": ema_fields["ema21"],
            "ema65": ema_fields["ema65"],
            "dist_ema9_pct": ema_fields["dist_ema9_pct"],
            "dist_ema21_pct": ema_fields["dist_ema21_pct"],
            "ema21_slope_3d_pct": ema_fields["ema21_slope_3d_pct"],
            "ema65_slope_5d_pct": ema_fields["ema65_slope_5d_pct"],
        }
    return out


def _scan_market(market: str, build_universe_fn, sector_etfs: list[str],
                 benchmark_tickers: list[str],
                 history_path: str, backtest_path: str) -> dict:
    """공통 스캐너 코어 — US/KR이 공유."""
    t0 = time.time()
    result = _empty_result(market)
    try:
        universe = build_universe_fn()
        result["scanned_count"] = len(universe)
        if not universe:
            return result

        # 섹터 ETF + 벤치마크 데이터 수집
        sector_data = _fetch_indicators(sector_etfs)
        bench_data = _fetch_indicators(benchmark_tickers)
        bench_5d_returns = [
            v.get("ret_5d_pct", 0.0) or 0.0
            for v in bench_data.values()
        ]
        market_5d = max(bench_5d_returns) if bench_5d_returns else 0.0

        # 섹터 평가 → Top N
        peer_20d = [v.get("ret_20d_pct") for v in sector_data.values()
                     if v.get("ret_20d_pct") is not None]
        evaluated_sectors = []
        for etf, sd in sector_data.items():
            sd["ticker"] = etf
            evaluated_sectors.append(
                msig.evaluate_sector(sd, market_5d=market_5d,
                                      peer_20d_returns=peer_20d)
            )
        top_sectors = msig.select_top_sectors(evaluated_sectors)
        result["top_sectors"] = top_sectors

        # ticker → sector 매핑 (Task 6)
        if market == "US":
            holdings_dict = md.get_us_sector_holdings()
            ticker_sector_map = md.build_sector_mapping(holdings_dict, market="us")
        else:
            # KR: use KOSPI_SECTORS hardcoded mapping (English GICS-compatible names).
            # KRX public API requires authentication since 2025; no public ETF
            # holdings endpoint is available. KOSPI_SECTORS maps the curated
            # KOSPI_TICKERS list directly to English sector names.
            try:
                from market_scanner import KOSPI_SECTORS
                ticker_sector_map = dict(KOSPI_SECTORS)
            except ImportError:
                ticker_sector_map = {}

        # Top sectors → ticker filter (US only — KR has no sector ETFs)
        if market == "US":
            top_sector_etfs = {s["ticker"] for s in top_sectors}
            top_tickers = [t for t in universe
                            if ticker_sector_map.get(t) in top_sector_etfs]
            if not top_tickers:
                top_tickers = universe[:300]
        else:
            # KR: scan all universe (no sector gate).
            # top_sectors is reset to [] so the KR page shows no misleading
            # sector leaderboard; M1/M2/M3 tables still populate from
            # prefilter + classify.
            top_tickers = list(universe)
            top_sectors = []
            result["top_sectors"] = top_sectors

        # bulk indicators
        stock_data_map = _fetch_indicators(top_tickers)

        # pre-filter + evaluate
        signals = {"MOMENTUM_3": [], "MOMENTUM_2": [], "MOMENTUM_1": []}
        today_signal_list: list[dict] = []
        for ticker, sd in stock_data_map.items():
            if not msig.passes_prefilter(sd):
                continue
            sector_etf = ticker_sector_map.get(ticker)
            sector_5d = None
            if sector_etf and sector_etf in sector_data:
                sector_5d = sector_data[sector_etf].get("ret_5d_pct")
            sd["ticker"] = ticker
            sd["sector"] = sector_etf
            evaluation = msig.evaluate_stock(sd, sector_5d_return=sector_5d)
            if evaluation is None:
                continue
            evaluation["name"] = _lookup_name(ticker, market)
            signals[evaluation["stage"]].append(evaluation)
            today_signal_list.append(evaluation)

        result["signals"] = signals

        # History update + save
        history = mh.load_history(history_path,
                                   scanner_name=f"momentum_{market.lower()}")
        history = mh.update_history(history, today_signal_list, today=result["as_of"])
        mh.save_history(history_path, history)

        # Backtest
        legs = mb.extract_legs(history)
        backtest = mb.aggregate(legs, as_of=result["as_of"])
        result["backtest_summary"] = backtest
        with open(backtest_path, "w", encoding="utf-8") as f:
            json.dump(backtest, f, ensure_ascii=False, indent=2)

        result["elapsed_s"] = round(time.time() - t0, 1)
        return result
    except Exception as e:
        print(f"[momentum_scanner] CRITICAL {market} scan failed: {e}")
        return _empty_result(market, status="failed", error_message=str(e))


def scan_momentum_us(project_dir: str) -> dict:
    """US 모멘텀 스캔 entry."""
    history_dir = os.path.join(project_dir, "history")
    os.makedirs(history_dir, exist_ok=True)
    return _scan_market(
        market="US",
        build_universe_fn=build_us_universe,
        sector_etfs=cfg.US_SECTOR_ETFS,
        benchmark_tickers=cfg.US_MARKET_BENCHMARKS,
        history_path=os.path.join(history_dir, "scanner_momentum_us_history.json"),
        backtest_path=os.path.join(history_dir, "momentum_backtest_us.json"),
    )


def scan_momentum_kr(project_dir: str) -> dict:
    """KR 모멘텀 스캔 entry."""
    history_dir = os.path.join(project_dir, "history")
    os.makedirs(history_dir, exist_ok=True)
    return _scan_market(
        market="KR",
        build_universe_fn=build_kr_universe,
        sector_etfs=cfg.KR_SECTOR_ETFS,
        benchmark_tickers=cfg.KR_MARKET_BENCHMARKS,
        history_path=os.path.join(history_dir, "scanner_momentum_kr_history.json"),
        backtest_path=os.path.join(history_dir, "momentum_backtest_kr.json"),
    )
