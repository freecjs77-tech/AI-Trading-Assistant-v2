"""포트폴리오 히스토리 재계산 코어.

Yahoo Finance v8 chart API 직접 호출 + 배당 TTM 일별 합산 + me/wife 공통 스냅샷 빌더.
rebuild_portfolio_history.py / rebuild_trend_data.py / rebuild_wife_history.py 모두
이 모듈로 위임한다 (DRY, 단일 진실의 원천).

설계: docs/superpowers/plans/2026-04-28-portfolio-history-rebuild.md
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import pandas as pd
import requests
import yfinance as yf

from portfolio_data import is_kospi_ticker, get_ticker_name, get_ticker_class, is_korean_ticker, to_yfinance_symbol

START_DATE = "2026-01-02"
TICKER_DELAY = 0.7  # rate limit 회피
MAX_RETRIES = 3
MACRO_SYMBOLS = {
    "VIX": "^VIX",
    "yield_30Y": "^TYX",
    "USD_KRW": "USDKRW=X",
}


def compute_ttm_dividend(divs: pd.Series, target: pd.Timestamp) -> float:
    """target 이전 365일 윈도우의 배당 합계 (주당)."""
    if divs is None or len(divs) == 0:
        return 0.0
    cutoff = target - pd.DateOffset(years=1)
    mask = (divs.index > cutoff) & (divs.index <= target)
    return float(divs[mask].sum())


def normalize_dividends(divs) -> pd.Series:
    """yfinance Ticker.dividends 반환을 Series로 정규화 (Series/DataFrame 양 대응)."""
    if divs is None:
        return pd.Series(dtype=float)
    if hasattr(divs, "columns"):
        col = "Dividends" if "Dividends" in divs.columns else divs.columns[0]
        divs = divs[col]
    if len(divs) == 0:
        return pd.Series(dtype=float)
    if hasattr(divs.index, 'tz') and divs.index.tz is not None:
        divs.index = divs.index.tz_localize(None)
    return divs.astype(float)


def make_yahoo_session() -> tuple[requests.Session, str]:
    """Yahoo v8 API 쿠키/crumb을 포함한 세션 생성."""
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    })
    crumb = ""
    try:
        r = sess.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=10)
        if r.status_code == 200:
            crumb = r.text.strip()
    except Exception:
        pass
    return sess, crumb


def fetch_chart(sess: requests.Session, crumb: str, symbol: str, range_str: str = "1y") -> pd.DataFrame | None:
    """Yahoo v8 chart API → 일봉 OHLCV DataFrame."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": range_str, "interval": "1d", "includeAdjustedClose": "true"}
    if crumb:
        params["crumb"] = crumb
    try:
        r = sess.get(url, params=params, timeout=15)
        if r.status_code != 200:
            return None
        result = r.json().get("chart", {}).get("result", [])
        if not result:
            return None
        ts = result[0].get("timestamp", [])
        q = result[0].get("indicators", {}).get("quote", [{}])[0]
        if not ts or not q:
            return None
        df = pd.DataFrame({
            "Open": q.get("open", []),
            "High": q.get("high", []),
            "Low": q.get("low", []),
            "Close": q.get("close", []),
            "Volume": q.get("volume", []),
        }, index=pd.to_datetime(ts, unit="s", utc=True))
        df.index = df.index.tz_localize(None)
        return df.dropna(subset=["Close"])
    except Exception:
        return None


def download_all(symbols: list[str], range_str: str = "1y", logger=print) -> dict[str, pd.DataFrame]:
    """모든 심볼 직렬 다운로드 + 재시도. (rate limit 회피)"""
    sess, crumb = make_yahoo_session()
    logger(f"  세션: crumb={'OK' if crumb else 'EMPTY'} / 심볼 {len(symbols)}개")
    out: dict[str, pd.DataFrame] = {}
    for idx, sym in enumerate(symbols):
        df = None
        for attempt in range(MAX_RETRIES):
            df = fetch_chart(sess, crumb, sym, range_str=range_str)
            if df is not None and len(df) >= 10:
                break
            time.sleep(2 * (attempt + 1))
        if df is not None:
            out[sym] = df
            logger(f"  [{idx+1:2d}/{len(symbols)}] {sym:<12} OK ({len(df)}일)")
        else:
            logger(f"  [{idx+1:2d}/{len(symbols)}] {sym:<12} SKIP")
        time.sleep(TICKER_DELAY)
    return out


def price_at(dfs: dict[str, pd.DataFrame], sym: str, target_ts: pd.Timestamp) -> float | None:
    """target_ts 이전 마지막 종가."""
    df = dfs.get(sym)
    if df is None or df.empty:
        return None
    sub = df["Close"][df["Close"].index <= target_ts]
    return float(sub.iloc[-1]) if not sub.empty else None


def _macro_at(dfs: dict[str, pd.DataFrame], target_ts: pd.Timestamp) -> dict:
    out = {}
    for key, sym in MACRO_SYMBOLS.items():
        v = price_at(dfs, sym, target_ts)
        out[key] = round(v, 4) if v is not None else None
    return out


def _master_switch_at(dfs: dict[str, pd.DataFrame], yf_map: dict, target_ts: pd.Timestamp) -> str:
    qqq_below = spy_below = False
    for bench in ("QQQ", "SPY"):
        df = dfs.get(yf_map.get(bench, bench))
        if df is None:
            continue
        s = df["Close"][df["Close"].index <= target_ts]
        if len(s) >= 200:
            ma200_val = float(s.rolling(200).mean().iloc[-1])
            cur = float(s.iloc[-1])
            if bench == "QQQ":
                qqq_below = cur < ma200_val
            else:
                spy_below = cur < ma200_val
    if qqq_below and spy_below:
        return "RED"
    if qqq_below or spy_below:
        return "YELLOW"
    return "GREEN"


def build_me_snapshot(
    target_ts: pd.Timestamp,
    holdings: list[dict],
    yf_map: dict[str, str],
    dfs: dict[str, pd.DataFrame],
    divs_map: dict[str, pd.Series],
    forward_map: dict[str, float] | None = None,
) -> dict | None:
    """me 포트폴리오 1일 스냅샷.

    holdings: [{ticker, shares, avg_cost}] (avg_cost는 네이티브 통화)
    yf_map:   {ticker -> yfinance symbol}
    dfs:      {symbol -> Close DataFrame}
    divs_map: {ticker -> 배당 Series (주당, 네이티브 통화)}
    forward_map: {ticker -> forward 연배당/주} — 있으면 TTM보다 우선 (파이프라인과 정합)
    """
    macro = _macro_at(dfs, target_ts)
    usd_krw = macro.get("USD_KRW") or 0
    rate = usd_krw if usd_krw and usd_krw > 1 else None
    if rate is None:
        return None  # FX 누락 일자 skip

    us_value = us_cost = 0.0
    kospi_value = kospi_cost = 0.0
    for p in holdings:
        t = p["ticker"]
        px = price_at(dfs, yf_map.get(t, t), target_ts)
        if px is None:
            continue
        val = p["shares"] * px
        cost = p["shares"] * p["avg_cost"]
        if is_kospi_ticker(t):
            kospi_value += val; kospi_cost += cost
        else:
            us_value += val;    us_cost += cost

    total_value_krw = us_value * rate + kospi_value
    cost_basis_krw = us_cost * rate + kospi_cost
    if total_value_krw <= 0:
        return None
    pnl_krw = total_value_krw - cost_basis_krw
    pnl_pct = (pnl_krw / cost_basis_krw * 100) if cost_basis_krw > 0 else 0

    # Cash (BIL)
    bil = next((p for p in holdings if p["ticker"] == "BIL"), None)
    cash_val = 0.0
    if bil:
        bp = price_at(dfs, "BIL", target_ts)
        if bp is not None:
            cash_val = bil["shares"] * bp
    cash_krw = cash_val * rate
    denom_usd = us_value + (kospi_value / rate)
    cash_pct = (cash_val / denom_usd * 100) if denom_usd > 0 else 0

    # 비중
    weights_cat: dict[str, float] = {}
    weights_ticker: dict[str, float] = {}
    for p in holdings:
        t = p["ticker"]
        px = price_at(dfs, yf_map.get(t, t), target_ts)
        if px is None:
            continue
        val = p["shares"] * px
        val_krw = val if is_kospi_ticker(t) else val * rate
        w = (val_krw / total_value_krw * 100) if total_value_krw > 0 else 0
        nm = (get_ticker_name(t) or t) if is_kospi_ticker(t) else t
        weights_ticker[nm] = round(w, 1)
        cls = get_ticker_class(t) or "Other"
        weights_cat[cls] = weights_cat.get(cls, 0) + w
    weights_cat = {k: round(v, 1) for k, v in weights_cat.items()}

    # 연배당 — forward 우선, 없으면 TTM 폴백 (fetch_market_data와 동일 로직)
    total_div_krw = 0.0
    for p in holdings:
        shares = p.get("shares", 0) or 0
        if shares <= 0:
            continue
        per_share = annual_dividend_per_share(p["ticker"], target_ts, divs_map, forward_map)
        if per_share <= 0:
            continue
        annual = per_share * shares
        total_div_krw += annual if is_kospi_ticker(p["ticker"]) else annual * rate
    div_annual_krw = round(total_div_krw)
    div_yield = round(total_div_krw / total_value_krw * 100, 2) if total_value_krw > 0 else 0.0

    return {
        "total_value_krw": round(total_value_krw),
        "cost_basis_krw": round(cost_basis_krw),
        "pnl_krw": round(pnl_krw),
        "pnl_pct": round(pnl_pct, 1),
        "cash_value_krw": round(cash_krw),
        "cash_pct": round(cash_pct, 1),
        "div_annual_krw": div_annual_krw,
        "div_yield": div_yield,
        "usd_krw": round(usd_krw, 2),
        "vix": round(macro["VIX"], 2) if macro.get("VIX") else None,
        "yield_30y": round(macro["yield_30Y"], 3) if macro.get("yield_30Y") else None,
        "master_switch": _master_switch_at(dfs, yf_map, target_ts),
        "holdings_count": len(holdings),
        "weights_by_category": weights_cat,
        "weights_by_ticker": weights_ticker,
    }


def build_wife_snapshot(
    target_ts: pd.Timestamp,
    wife_holdings: list[tuple[str, float, float]],
    usd_tickers: set[str],
    yf_map: dict[str, str],
    dfs: dict[str, pd.DataFrame],
    divs_map: dict[str, pd.Series],
    forward_map: dict[str, float] | None = None,
) -> dict | None:
    """wife 포트폴리오 1일 스냅샷.

    wife_holdings: [(ticker, shares, avg_cost_krw)] — avg_cost는 이미 KRW 환산된 매입원가
    usd_tickers: 가격이 USD인 티커 집합 (가치 계산 시 FX 곱)
    forward_map: {ticker -> forward 연배당/주} — 있으면 TTM보다 우선 (파이프라인과 정합)
    """
    fx = price_at(dfs, "USDKRW=X", target_ts)
    if fx is None or fx <= 0:
        return None

    total_krw = 0.0
    cost_krw = 0.0
    weights_krw: dict[str, float] = {}
    miss = 0
    for ticker, shares, avg_cost_krw in wife_holdings:
        sym = yf_map.get(ticker, ticker)
        px = price_at(dfs, sym, target_ts)
        if px is None:
            miss += 1
            continue
        val_krw = px * shares * fx if ticker in usd_tickers else px * shares
        total_krw += val_krw
        cost_krw += avg_cost_krw * shares
        weights_krw[ticker] = val_krw

    if total_krw <= 0:
        return None
    pnl_krw = total_krw - cost_krw
    pnl_pct = round(pnl_krw / cost_krw * 100, 2) if cost_krw > 0 else 0
    weights_by_ticker = {t: round(v / total_krw * 100, 1) for t, v in weights_krw.items()}

    # 연배당 — forward 우선, 없으면 TTM 폴백 (fetch_market_data와 동일 로직)
    total_div_krw = 0.0
    for ticker, shares, _ in wife_holdings:
        if shares <= 0:
            continue
        per_share = annual_dividend_per_share(ticker, target_ts, divs_map, forward_map)
        if per_share <= 0:
            continue
        annual = per_share * shares
        total_div_krw += annual * fx if ticker in usd_tickers else annual
    div_annual_krw = round(total_div_krw)
    div_yield = round(total_div_krw / total_krw * 100, 2) if total_krw > 0 else 0.0

    macro = _macro_at(dfs, target_ts)

    return {
        "total_value_krw": round(total_krw),
        "cost_basis_krw": round(cost_krw),
        "pnl_krw": round(pnl_krw),
        "pnl_pct": pnl_pct,
        "cash_value_krw": 0,
        "cash_pct": 0.0,
        "div_annual_krw": div_annual_krw,
        "div_yield": div_yield,
        "usd_krw": round(fx, 2),
        "vix": round(macro["VIX"], 2) if macro.get("VIX") else None,
        "yield_30y": round(macro["yield_30Y"], 3) if macro.get("yield_30Y") else None,
        "master_switch": "UNKNOWN",
        "holdings_count": len(wife_holdings) - miss,
        "weights_by_category": {},
        "weights_by_ticker": weights_by_ticker,
    }


def yf_symbol(ticker: str) -> str:
    """Wrapper around to_yfinance_symbol (handles korean/US tickers)."""
    return to_yfinance_symbol(ticker) if is_korean_ticker(ticker) else ticker


def fetch_all_dividends(tickers: list[str], delay: float = 0.4, logger=print) -> dict[str, pd.Series]:
    """티커별 전체 배당 시리즈."""
    out: dict[str, pd.Series] = {}
    for i, t in enumerate(tickers, 1):
        sym = yf_symbol(t)
        s = pd.Series(dtype=float)
        for attempt in range(MAX_RETRIES):
            try:
                s = normalize_dividends(yf.Ticker(sym).dividends)
                break
            except Exception:
                time.sleep(2 ** attempt)
        logger(f"  [{i:2}/{len(tickers)}] {sym}: {len(s)} events")
        out[t] = s
        time.sleep(delay)
    return out


def trading_dates_from(spy_df: pd.DataFrame, start: str) -> pd.DatetimeIndex:
    """SPY 일봉에서 start (YYYY-MM-DD) 이후 거래일 인덱스 추출."""
    s = spy_df["Close"].dropna()
    s = s[s.index >= pd.Timestamp(start)]
    return s.index


def fetch_all_forward_rates(
    tickers: list[str],
    delay: float = 0.2,
    logger=print,
) -> dict[str, float]:
    """티커별 forward 배당률 (yfinance.info.dividendRate, 연배당/주).

    fetch_market_data._fetch_forward_dividend_rate와 동일 로직 — 파이프라인과 정합.
    실패/없음 시 0.0. 호출자는 0.0인 경우 TTM 폴백.
    """
    out: dict[str, float] = {}
    for i, t in enumerate(tickers, 1):
        sym = yf_symbol(t)
        rate = 0.0
        for attempt in range(MAX_RETRIES):
            try:
                info = yf.Ticker(sym).info or {}
                v = info.get("dividendRate") or info.get("trailingAnnualDividendRate") or 0.0
                rate = float(v) if v else 0.0
                break
            except Exception:
                time.sleep(2 ** attempt)
        logger(f"  [{i:2}/{len(tickers)}] {sym}: forward {rate}")
        out[t] = rate
        time.sleep(delay)
    return out


def annual_dividend_per_share(
    ticker: str,
    target_ts: pd.Timestamp,
    divs_map: dict[str, pd.Series],
    forward_map: dict[str, float] | None = None,
) -> float:
    """Forward 우선, 없으면 TTM 폴백 — fetch_market_data와 동일 로직.

    파이프라인의 일일 갱신과 트렌드 백필이 같은 값을 산출하도록 통일.
    """
    if forward_map:
        fwd = forward_map.get(ticker, 0.0) or 0.0
        if fwd > 0:
            return float(fwd)
    return compute_ttm_dividend(divs_map.get(ticker, pd.Series(dtype=float)), target_ts)
