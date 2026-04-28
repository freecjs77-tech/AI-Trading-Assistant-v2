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
