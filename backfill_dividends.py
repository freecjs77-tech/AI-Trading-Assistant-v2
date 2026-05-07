#!/usr/bin/env python3
"""
backfill_dividends.py — portfolio_daily*.json 과거 배당 필드를 실제 TTM 배당으로 재계산.

regenerate_history.py가 하드코딩된 배당 상수(₩42.2M, 2.08%)를 쓰기 때문에 과거
30일치 배당이 수평선을 그리고 최신일과 큰 단차가 나는 문제를 해결한다.

각 날짜별로 target_date 이전 12개월간 배당 합산(TTM) → shares × TTM/주 → 원화 환산.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))

from fetch_market_data import parse_portfolio_md
from portfolio_data import is_korean_ticker, to_yfinance_symbol


def _yf_symbol(ticker: str) -> str:
    return to_yfinance_symbol(ticker) if is_korean_ticker(ticker) else ticker


def _normalize_dividends(divs) -> pd.Series:
    """yf.Ticker.dividends 반환이 Series/DataFrame 둘 다 나올 수 있어 Series로 정규화."""
    if divs is None:
        return pd.Series(dtype=float)
    if hasattr(divs, "columns"):
        col = "Dividends" if "Dividends" in divs.columns else divs.columns[0]
        divs = divs[col]
    if divs.empty:
        return pd.Series(dtype=float)
    if divs.index.tz is not None:
        divs.index = divs.index.tz_localize(None)
    return divs.astype(float)


def fetch_all_dividends(tickers: list, delay: float = 0.4) -> dict:
    """티커별 전체 배당 히스토리 다운로드."""
    out: dict[str, pd.Series] = {}
    for i, t in enumerate(tickers, 1):
        sym = _yf_symbol(t)
        series = pd.Series(dtype=float)
        for attempt in range(3):
            try:
                series = _normalize_dividends(yf.Ticker(sym).dividends)
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    print(f"  [{i:2}/{len(tickers)}] {sym}: FAILED ({e})")
        print(f"  [{i:2}/{len(tickers)}] {sym}: {len(series)} events")
        out[t] = series
        time.sleep(delay)
    return out


def fetch_fx_history(start: str, end: str) -> pd.Series:
    """USD/KRW 환율 일별."""
    df = yf.Ticker("USDKRW=X").history(start=start, end=end)
    if df is None or df.empty:
        return pd.Series(dtype=float)
    s = df["Close"].dropna()
    if s.index.tz is not None:
        s.index = s.index.tz_localize(None)
    return s


def compute_ttm_dividend(divs: pd.Series, target: pd.Timestamp) -> float:
    if divs.empty:
        return 0.0
    cutoff = target - pd.DateOffset(years=1)
    mask = (divs.index > cutoff) & (divs.index <= target)
    return float(divs[mask].sum())


def get_fx_at(fx: pd.Series, target: pd.Timestamp) -> float:
    s = fx[fx.index <= target]
    return float(s.iloc[-1]) if not s.empty else 0.0


def backfill(owner: str) -> None:
    # 경로
    if owner == "me":
        pf_path = PROJECT_DIR / "portfolios" / "me.md"
        if not pf_path.exists():
            pf_path = PROJECT_DIR / "portfolio.md"
        daily_path = PROJECT_DIR / "history" / "portfolio_daily.json"
    else:
        pf_path = PROJECT_DIR / "portfolios" / f"{owner}.md"
        daily_path = PROJECT_DIR / "history" / f"portfolio_daily_{owner}.json"

    if not pf_path.exists():
        print(f"[{owner}] portfolio 파일 없음: {pf_path}")
        return
    if not daily_path.exists():
        print(f"[{owner}] daily 파일 없음: {daily_path}")
        return

    tickers, shares_map = parse_portfolio_md(str(pf_path))
    print(f"\n[{owner}] 포트폴리오 {len(tickers)}종목")

    # 배당 히스토리 일괄 fetch
    print(f"[{owner}] 배당 히스토리 다운로드 ({len(tickers)}종목)...")
    divs_map = fetch_all_dividends(tickers)

    # daily 로드
    with open(daily_path, "r", encoding="utf-8") as f:
        daily = json.load(f)
    dates = sorted([k for k in daily.keys() if not k.startswith("_")])
    if not dates:
        print(f"[{owner}] daily 비어 있음")
        return
    print(f"[{owner}] 재계산 대상: {len(dates)}일 ({dates[0]} ~ {dates[-1]})")

    # FX: 시작일 1년 전부터 말일까지 (가끔 시작일보다 일찍 조회 필요)
    fx_start = (pd.Timestamp(dates[0]) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    fx_end = (pd.Timestamp(dates[-1]) + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    fx_series = fetch_fx_history(fx_start, fx_end)
    if fx_series.empty:
        print(f"[{owner}] USD/KRW 환율 조회 실패 — 중단")
        return

    updated = 0
    for date_str in dates:
        target = pd.Timestamp(date_str)
        fx = get_fx_at(fx_series, target)
        if fx <= 0:
            print(f"  {date_str}: FX 누락 - skip")
            continue

        total_div_krw = 0.0
        per_ticker = {}
        for ticker, shares in shares_map.items():
            ttm_per_share = compute_ttm_dividend(divs_map.get(ticker, pd.Series(dtype=float)), target)
            if ttm_per_share <= 0 or shares <= 0:
                continue
            annual = ttm_per_share * shares
            div_krw = annual if is_korean_ticker(ticker) else annual * fx
            total_div_krw += div_krw
            per_ticker[ticker] = round(div_krw)

        total_value = daily[date_str].get("total_value_krw", 0)
        div_yield = round(total_div_krw / total_value * 100, 2) if total_value > 0 else 0.0

        old_div = daily[date_str].get("div_annual_krw", 0)
        old_yield = daily[date_str].get("div_yield", 0)
        daily[date_str]["div_annual_krw"] = round(total_div_krw)
        daily[date_str]["div_yield"] = div_yield
        updated += 1
        print(
            f"  {date_str}: div ₩{old_div:>13,} → ₩{int(total_div_krw):>13,}  "
            f"yield {old_yield}% → {div_yield}%"
        )

    with open(daily_path, "w", encoding="utf-8") as f:
        json.dump(daily, f, ensure_ascii=False, indent=2)
    print(f"\n[{owner}] {updated}일 업데이트 → {daily_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="portfolio_daily 배당 백필")
    ap.add_argument("--owner", default="all", help="me, wife, all (default all)")
    args = ap.parse_args()

    if args.owner == "all":
        for o in ["me", "wife"]:
            backfill(o)
    else:
        backfill(args.owner)
