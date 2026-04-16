"""트렌드 페이지 전용 히스토리 재생성 스크립트

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


# ── me 스냅샷 생성 ──
def build_me_snapshot(
    target_ts: pd.Timestamp,
    me_holdings: list[dict],
    yf_map: dict[str, str],
    dfs: dict[str, pd.DataFrame],
) -> dict | None:
    """me 포트폴리오 1일치 스냅샷 (regenerate_history.py 로직과 동일)."""
    date_str = target_ts.strftime("%Y-%m-%d")

    # 매크로
    macro_day = {}
    for key, sym in MACRO_SYMBOLS.items():
        v = price_at(dfs, sym, target_ts)
        macro_day[key] = round(v, 4) if v is not None else None

    usd_krw = macro_day.get("USD_KRW") or 0
    rate = usd_krw if usd_krw > 1 else 1
    if rate <= 1:
        return None  # FX 누락 시 스냅샷 생성 불가

    # Master switch (QQQ/SPY vs MA200)
    qqq_below = spy_below = False
    for bench in ["QQQ", "SPY"]:
        df = dfs.get(yf_map.get(bench, bench))
        if df is None:
            continue
        s = df["Close"]
        s_until = s[s.index <= target_ts]
        if len(s_until) >= 200:
            ma200_val = float(s_until.rolling(200).mean().iloc[-1])
            cur = float(s_until.iloc[-1])
            if bench == "QQQ":
                qqq_below = cur < ma200_val
            else:
                spy_below = cur < ma200_val
    if qqq_below and spy_below:
        master = "RED"
    elif qqq_below or spy_below:
        master = "YELLOW"
    else:
        master = "GREEN"

    # 종목별 가치
    us_value = us_cost = 0.0
    kospi_value = kospi_cost = 0.0
    weights_cat: dict[str, float] = {}
    weights_ticker: dict[str, float] = {}

    for p in me_holdings:
        t = p["ticker"]
        yf_sym = yf_map.get(t, t)
        px = price_at(dfs, yf_sym, target_ts)
        if px is None:
            continue
        val = p["shares"] * px
        cost = p["shares"] * p["avg_cost"]
        if is_kospi_ticker(t):
            kospi_value += val
            kospi_cost += cost
        else:
            us_value += val
            us_cost += cost

    total_value_krw = us_value * rate + kospi_value
    cost_basis_krw = us_cost * rate + kospi_cost
    if total_value_krw <= 0:
        return None
    pnl_krw = total_value_krw - cost_basis_krw
    pnl_pct = (pnl_krw / cost_basis_krw * 100) if cost_basis_krw > 0 else 0

    # Cash (BIL)
    bil = next((p for p in me_holdings if p["ticker"] == "BIL"), None)
    cash_val = 0.0
    if bil:
        bil_px = price_at(dfs, "BIL", target_ts)
        if bil_px is not None:
            cash_val = bil["shares"] * bil_px
    cash_krw = cash_val * rate
    total_usd_equiv = us_value + (kospi_value / rate)
    cash_pct = (cash_val / total_usd_equiv * 100) if total_usd_equiv > 0 else 0

    # 비중 계산
    for p in me_holdings:
        t = p["ticker"]
        yf_sym = yf_map.get(t, t)
        px = price_at(dfs, yf_sym, target_ts)
        if px is None:
            continue
        val = p["shares"] * px
        val_krw = val if is_kospi_ticker(t) else val * rate
        w = (val_krw / total_value_krw * 100) if total_value_krw > 0 else 0
        display_name = (get_ticker_name(t) or t) if is_kospi_ticker(t) else t
        weights_ticker[display_name] = round(w, 1)
        cls = get_ticker_class(t) or "Other"
        weights_cat[cls] = weights_cat.get(cls, 0) + w

    weights_cat = {k: round(v, 1) for k, v in weights_cat.items()}

    # 배당 (고정값 — 기존 로직과 동일)
    div_annual_krw = round(42218109 * (rate / 1481.53), 0) if rate > 1 else 42218109
    div_yield = 2.08

    return {
        "total_value_krw": round(total_value_krw),
        "cost_basis_krw": round(cost_basis_krw),
        "pnl_krw": round(pnl_krw),
        "pnl_pct": round(pnl_pct, 1),
        "cash_value_krw": round(cash_krw),
        "cash_pct": round(cash_pct, 1),
        "div_annual_krw": round(div_annual_krw),
        "div_yield": round(div_yield, 2),
        "usd_krw": round(usd_krw, 2),
        "vix": round(macro_day.get("VIX"), 2) if macro_day.get("VIX") else None,
        "yield_30y": round(macro_day.get("yield_30Y"), 3) if macro_day.get("yield_30Y") else None,
        "master_switch": master,
        "holdings_count": len(me_holdings),
        "weights_by_category": weights_cat,
        "weights_by_ticker": weights_ticker,
    }


# ── wife 스냅샷 생성 (rebuild_wife_history.py 로직과 동일) ──
def build_wife_snapshot(
    target_ts: pd.Timestamp,
    dfs: dict[str, pd.DataFrame],
) -> dict | None:
    fx = price_at(dfs, "USDKRW=X", target_ts)
    if fx is None or fx <= 0:
        return None

    total_krw = 0.0
    cost_krw = 0.0
    weights_krw: dict[str, float] = {}
    missing = []

    for ticker, shares, avg_cost_krw in WIFE_HOLDINGS:
        sym = to_yfinance_symbol(ticker) if is_kospi_ticker(ticker) else ticker
        px = price_at(dfs, sym, target_ts)
        if px is None:
            missing.append(sym)
            continue
        if ticker in WIFE_USD_TICKERS:
            val_krw = px * shares * fx
        else:
            val_krw = px * shares
        total_krw += val_krw
        cost_krw += avg_cost_krw * shares
        weights_krw[ticker] = val_krw

    if total_krw <= 0:
        return None

    pnl_krw = total_krw - cost_krw
    pnl_pct = round(pnl_krw / cost_krw * 100, 2) if cost_krw > 0 else 0
    weights_by_ticker = {
        t: round(v / total_krw * 100, 2) for t, v in weights_krw.items()
    }

    return {
        "total_value_krw": int(total_krw),
        "cost_basis_krw": int(cost_krw),
        "pnl_krw": int(pnl_krw),
        "pnl_pct": pnl_pct,
        "cash_value_krw": 0,
        "cash_pct": 0.0,
        "div_annual_krw": 0,
        "div_yield": 0,
        "usd_krw": round(fx, 2),
        "vix": None,
        "yield_30y": None,
        "master_switch": "UNKNOWN",
        "holdings_count": len(WIFE_HOLDINGS) - len(missing),
        "weights_by_category": {},
        "weights_by_ticker": weights_by_ticker,
    }


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
