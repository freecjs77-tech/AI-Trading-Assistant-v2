"""트렌드 페이지 전용 히스토리 재생성 스크립트 (최근 N 거래일)

대상 파일:
  - history/portfolio_daily.json (me)
  - history/portfolio_daily_wife.json (wife)

원칙:
  - yfinance 라이브러리 우회 → Yahoo Finance v8 chart API 직접 호출
  - 모든 심볼 1회만 다운로드 (me/wife 공유 종목은 1번만 호출)
  - 0.7초 간격 + 3회 재시도 (지수 백오프) 로 레이트리밋 회피
  - me / wife 각자의 비용 모델은 기존과 동일하게 유지
    · me: avg_cost = native currency (USD or KRW)
    · wife: avg_cost_krw = 원래 매입한 KRW (rebuild_wife_history.py의 HOLDINGS 재사용)

DEPRECATED (2026-04-28):
  build_me_snapshot / build_wife_snapshot 는 portfolio_history_core.build_me_snapshot /
  build_wife_snapshot 으로 위임한다.  하드코딩 배당 상수(₩42,218,109 me base,
  ₩16,675,519 wife base, div_yield=2.08)는 완전히 제거되었다.
  전체 히스토리 재생성이 필요하면 rebuild_portfolio_history.py 를 사용한다.
"""
from __future__ import annotations
import sys
import os
import json
import time
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

import requests
import pandas as pd

from regenerate_history import parse_portfolio_holdings  # me 파서 재사용
from rebuild_wife_history import HOLDINGS as WIFE_HOLDINGS, USD_TICKERS as WIFE_USD_TICKERS
from fetch_market_data import parse_portfolio_md
from portfolio_data import (
    to_yfinance_symbol, is_kospi_ticker, get_ticker_name, get_ticker_class,
)
from portfolio_paths import primary_portfolio_path
import portfolio_history_core as core

# ── 설정 ──
NUM_TRADING_DAYS = 32  # 약 6주 (기존 데이터와 동일 범위)
TICKER_DELAY = 0.7     # 심볼 간 대기 (rate limit 회피)

ME_DAILY_PATH = os.path.join(PROJECT_DIR, "history", "portfolio_daily.json")
WIFE_DAILY_PATH = os.path.join(PROJECT_DIR, "history", "portfolio_daily_wife.json")

MACRO_SYMBOLS = {
    "VIX": "^VIX",
    "yield_30Y": "^TYX",
    "USD_KRW": "USDKRW=X",
}

# REMOVED 2026-04-28: 하드코딩 배당 base 폐기. portfolio_history_core.compute_ttm_dividend 사용.
# WIFE_DIV_BASE_KRW = 16675519
# WIFE_DIV_BASE_FX = 1481.24


# ── Yahoo Finance v8 chart API ──
def make_session() -> tuple[requests.Session, str]:
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/131.0.0.0 Safari/537.36",
    })
    crumb = ""
    try:
        r = sess.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=10)
        if r.status_code == 200:
            crumb = r.text.strip()
    except Exception:
        pass
    return sess, crumb


def fetch_chart(sess: requests.Session, crumb: str, symbol: str) -> pd.DataFrame | None:
    """Yahoo v8 chart API → 1년 일봉 DataFrame."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": "1y", "interval": "1d", "includeAdjustedClose": "true"}
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
        df = df.dropna(subset=["Close"])
        return df if len(df) >= 10 else None
    except Exception:
        return None


def download_all(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """모든 심볼을 0.7초 간격으로 직렬 다운로드 (3회 재시도)."""
    sess, crumb = make_session()
    print(f"  세션 초기화: crumb={'OK' if crumb else 'EMPTY'}")
    print(f"  다운로드 대상: {len(symbols)}개 심볼")

    out: dict[str, pd.DataFrame] = {}
    for idx, sym in enumerate(symbols):
        print(f"    [{idx+1:2d}/{len(symbols)}] {sym:<12} ", end="", flush=True)
        df = None
        for attempt in range(3):
            df = fetch_chart(sess, crumb, sym)
            if df is not None:
                break
            wait = 2 * (attempt + 1)
            print(f"재시도({wait}s) ", end="", flush=True)
            time.sleep(wait)
        if df is not None:
            out[sym] = df
            print(f"OK ({len(df)}일)")
        else:
            print("SKIP")
        time.sleep(TICKER_DELAY)
    print(f"  완료: {len(out)}/{len(symbols)} 성공")
    return out


# ── 가격 조회 헬퍼 ──
def price_at(dfs: dict[str, pd.DataFrame], sym: str, target_ts: pd.Timestamp) -> float | None:
    df = dfs.get(sym)
    if df is None or df.empty:
        return None
    s = df["Close"]
    sub = s[s.index <= target_ts]
    return float(sub.iloc[-1]) if not sub.empty else None


# ── me 스냅샷 생성 (portfolio_history_core 위임) ──
def build_me_snapshot(
    target_ts: pd.Timestamp,
    me_holdings: list[dict],
    yf_map: dict[str, str],
    dfs: dict[str, pd.DataFrame],
) -> dict | None:
    """me 포트폴리오 1일치 스냅샷 — portfolio_history_core.build_me_snapshot에 위임.

    DEPRECATED wrapper: 배당은 TTM 기반(compute_ttm_dividend).
    하드코딩 ₩42,218,109 × FX 비례 로직은 2026-04-28 제거.
    divs_map은 main()에서 fetch 후 build_me_snapshot._divs_map 으로 주입한다.
    """
    # REMOVED 2026-04-28: 하드코딩 ₩42,218,109 × FX 비례 폐기. core.compute_ttm_dividend 위임.
    divs_map = getattr(build_me_snapshot, "_divs_map", {})
    return core.build_me_snapshot(target_ts, me_holdings, yf_map, dfs, divs_map)


# ── wife 스냅샷 생성 (portfolio_history_core 위임) ──
def build_wife_snapshot(
    target_ts: pd.Timestamp,
    dfs: dict[str, pd.DataFrame],
) -> dict | None:
    """wife 포트폴리오 1일치 스냅샷 — portfolio_history_core.build_wife_snapshot에 위임.

    DEPRECATED wrapper: 배당은 TTM 기반(compute_ttm_dividend).
    하드코딩 ₩16,675,519 × FX 비례 로직은 2026-04-28 제거.
    divs_map은 main()에서 fetch 후 build_wife_snapshot._divs_map 으로 주입한다.
    """
    # REMOVED 2026-04-28: 하드코딩 WIFE_DIV_BASE_KRW × FX 비례 폐기. core.compute_ttm_dividend 위임.
    divs_map = getattr(build_wife_snapshot, "_divs_map", {})
    yf_map = {t: core.yf_symbol(t) for t, _, _ in WIFE_HOLDINGS}
    return core.build_wife_snapshot(target_ts, WIFE_HOLDINGS, WIFE_USD_TICKERS, yf_map, dfs, divs_map)


def main():
    print(f"\n{'='*60}")
    print(f"  트렌드 데이터 재생성 (최근 {NUM_TRADING_DAYS}거래일)")
    print(f"  대상: portfolio_daily.json (me) + portfolio_daily_wife.json (wife)")
    print(f"{'='*60}\n")

    # ── 1) 포트폴리오 파싱 ──
    me_path = primary_portfolio_path(PROJECT_DIR)
    me_tickers, _ = parse_portfolio_md(me_path)
    me_holdings = parse_portfolio_holdings(me_path)
    print(f"  me: {len(me_holdings)}종목 ({me_path})")
    print(f"  wife: {len(WIFE_HOLDINGS)}종목 (rebuild_wife_history.HOLDINGS)")

    # ── 2) 심볼 수집 (중복 제거) ──
    yf_map: dict[str, str] = {t: to_yfinance_symbol(t) for t in me_tickers}

    me_syms = set(yf_map.values())
    wife_syms = set()
    for t, _, _ in WIFE_HOLDINGS:
        wife_syms.add(to_yfinance_symbol(t) if is_kospi_ticker(t) else t)

    macro_syms = set(MACRO_SYMBOLS.values())

    all_syms = sorted(me_syms | wife_syms | macro_syms | {"SPY"})
    print(f"\n  유니크 심볼: {len(all_syms)}개 (me {len(me_syms)} + wife {len(wife_syms)} + 매크로 {len(macro_syms)})")

    # ── 3) Yahoo 직접 API 다운로드 ──
    print(f"\n{'─'*60}")
    print(f"  Yahoo Finance v8 chart API 다운로드")
    print(f"{'─'*60}")
    dfs = download_all(all_syms)

    if "SPY" not in dfs:
        print("\n  ERROR: SPY 데이터 없음 — 거래일 판별 불가")
        sys.exit(1)

    # ── 4) 거래일 추출 (US 기준) ──
    spy_close = dfs["SPY"]["Close"].dropna()
    trading_dates = spy_close.index[-NUM_TRADING_DAYS:]
    print(f"\n  거래일 {len(trading_dates)}일: "
          f"{trading_dates[0].strftime('%Y-%m-%d')} ~ "
          f"{trading_dates[-1].strftime('%Y-%m-%d')}")

    # ── 4b) 배당 시리즈 fetch + wrapper에 주입 ──
    print(f"\n{'─'*60}")
    print(f"  배당 히스토리 다운로드 (TTM 기반, 하드코딩 대체)")
    print(f"{'─'*60}")
    all_div_tickers = sorted(set(
        [p["ticker"] for p in me_holdings] +
        [t for t, _, _ in WIFE_HOLDINGS]
    ))
    divs_map = core.fetch_all_dividends(all_div_tickers)
    build_me_snapshot._divs_map = divs_map
    build_wife_snapshot._divs_map = divs_map

    # ── 5) me 스냅샷 생성 ──
    print(f"\n{'─'*60}")
    print(f"  me 스냅샷 생성")
    print(f"{'─'*60}")
    me_daily = {}
    for idx, ts in enumerate(trading_dates):
        date_str = ts.strftime("%Y-%m-%d")
        snap = build_me_snapshot(ts, me_holdings, yf_map, dfs)
        if snap is None:
            print(f"  [{idx+1:2d}] {date_str}: SKIP (FX/데이터 누락)")
            continue
        me_daily[date_str] = snap
        total_eok = snap["total_value_krw"] / 1e8
        print(f"  [{idx+1:2d}] {date_str}: 자산 {total_eok:.2f}억 | "
              f"PnL {snap['pnl_pct']:+.1f}% | USD/KRW {snap['usd_krw']:.0f} | "
              f"{snap['master_switch']}")

    # ── 6) wife 스냅샷 생성 ──
    print(f"\n{'─'*60}")
    print(f"  wife 스냅샷 생성")
    print(f"{'─'*60}")
    wife_daily = {}
    for idx, ts in enumerate(trading_dates):
        date_str = ts.strftime("%Y-%m-%d")
        snap = build_wife_snapshot(ts, dfs)
        if snap is None:
            print(f"  [{idx+1:2d}] {date_str}: SKIP (FX/데이터 누락)")
            continue
        wife_daily[date_str] = snap
        total_eok = snap["total_value_krw"] / 1e8
        print(f"  [{idx+1:2d}] {date_str}: 자산 {total_eok:.2f}억 | "
              f"PnL {snap['pnl_pct']:+.1f}% | USD/KRW {snap['usd_krw']:.0f}")

    # ── 7) 기존 마지막 날 데이터 보존 (수동 추출 우선) ──
    last_date = trading_dates[-1].strftime("%Y-%m-%d")
    if os.path.exists(WIFE_DAILY_PATH):
        with open(WIFE_DAILY_PATH, encoding="utf-8") as f:
            old_wife = json.load(f)
        if last_date in old_wife:
            wife_daily[last_date] = old_wife[last_date]
            print(f"\n  wife: {last_date} 기존 수동 추출 데이터 보존")

    # ── 8) 저장 ──
    os.makedirs(os.path.dirname(ME_DAILY_PATH), exist_ok=True)
    with open(ME_DAILY_PATH, "w", encoding="utf-8") as f:
        json.dump(me_daily, f, ensure_ascii=False, indent=2)
    with open(WIFE_DAILY_PATH, "w", encoding="utf-8") as f:
        json.dump(wife_daily, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"  완료!")
    print(f"  me:   {len(me_daily)}일 → {ME_DAILY_PATH}")
    print(f"  wife: {len(wife_daily)}일 → {WIFE_DAILY_PATH}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
