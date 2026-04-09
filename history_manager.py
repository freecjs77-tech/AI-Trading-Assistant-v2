"""
history_manager.py — 시그널 이력 관리
AI Trading Assistant v3.0

signals_history.json의 로드/저장/가지치기(30일) 관리.
변경④: price_vs_ma20, ma20 필드 추가 저장.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf


def load_history(path: str) -> dict:
    """signals_history.json 로드. 파일 없으면 빈 dict 반환."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_history(history: dict, path: str):
    """signals_history.json 저장."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def save_today(
    history: dict,
    date_str: str,
    signals: dict,
    market_data: dict,
    portfolio_source: str,
) -> dict:
    """
    오늘 시그널 결과를 history에 추가.
    signals: judge_all()의 반환값 {ticker: {signal, note, ...}}
    """
    macro = market_data.get("_macro", {})
    meta = market_data.get("_meta", {})

    day_entry = {
        "_meta": {
            "data_source": "yfinance",
            "fetched_at": meta.get("generated_at", datetime.now().strftime("%Y-%m-%d %H:%M")),
            "portfolio_source": portfolio_source,
            "tickers": len(signals),
        },
        "_macro": {
            "VIX": macro.get("VIX"),
            "yield_30Y": macro.get("yield_30Y"),
            "USD_KRW": macro.get("USD_KRW"),
            "master_switch": macro.get("master_switch", "UNKNOWN"),
        },
    }

    for ticker, result in signals.items():
        # conditions_met: 충족된 조건 이름 리스트 (백테스트 분석용)
        conditions_met = [c[1] for c in result.get("conditions", []) if c[0] == "ok"]
        day_entry[ticker] = {
            "signal": result.get("signal"),
            "price": result.get("price"),
            "rsi": result.get("rsi"),
            "macd_hist": result.get("macd_hist"),
            "macd_hist_trend": result.get("macd_hist_trend"),
            "drawdown": result.get("drawdown"),
            "price_vs_ma20": result.get("price_vs_ma20"),  # 변경④ 추가
            "ma20": result.get("ma20"),                      # 변경④ 추가
            "bb_pct": result.get("bb_pct"),                  # v5.1 추가
            "buy_streak": result.get("buy_streak", 0),      # v5.1b 연속일
            "buy_confirmed": result.get("buy_confirmed", False),
            "conditions_met": conditions_met,                # 백테스트용
            "note": result.get("note", ""),
        }

    history[date_str] = day_entry
    return history


def prune_old(history: dict, keep_days: int = 30) -> dict:
    """keep_days일 이전 데이터 삭제."""
    cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    keys_to_remove = [k for k in history.keys() if k < cutoff and not k.startswith("_")]
    for k in keys_to_remove:
        del history[k]
    return history


def backfill_prices(history: dict, today_str: str = ""):
    """과거 날짜의 price를 yfinance 실제 종가로 교정.

    장중 실행 시 현재가가 저장되므로, 오늘이 아닌 모든 과거 항목의
    가격을 실제 종가로 덮어쓴다.
    """
    targets: dict[str, list[str]] = {}  # {ticker: [date1, date2, ...]}
    for dt, day_data in history.items():
        if dt == today_str or dt.startswith("_"):
            continue
        for ticker, info in day_data.items():
            if ticker.startswith("_"):
                continue
            if info.get("price") is not None:
                targets.setdefault(ticker, []).append(dt)

    if not targets:
        return

    all_dates = sorted(set(d for dates in targets.values() for d in dates))
    start = (datetime.strptime(all_dates[0], "%Y-%m-%d") - timedelta(days=10)).strftime("%Y-%m-%d")
    end = (datetime.strptime(all_dates[-1], "%Y-%m-%d") + timedelta(days=5)).strftime("%Y-%m-%d")

    tickers_list = list(targets.keys())
    # KOSPI 종목은 .KS 접미사 필요
    yf_map: dict[str, str] = {}
    for t in tickers_list:
        if t.isdigit() and len(t) == 6:
            yf_map[t] = f"{t}.KS"
        else:
            yf_map[t] = t

    yf_tickers = list(yf_map.values())
    print(f"  [Portfolio Backfill] {len(yf_tickers)}개 종목 종가 조회 ({all_dates[0]}~{all_dates[-1]})")
    try:
        df = yf.download(yf_tickers, start=start, end=end,
                         auto_adjust=True, progress=False)
        if df is None or df.empty:
            print("  [Portfolio Backfill] yfinance 데이터 없음")
            return
    except Exception as ex:
        print(f"  [Portfolio Backfill] yfinance 오류: {ex}")
        return

    filled = 0
    num_tickers = len(yf_tickers)
    for ticker, dates in targets.items():
        yf_ticker = yf_map[ticker]
        for dt in dates:
            try:
                ts = pd.Timestamp(dt)
                if num_tickers == 1:
                    if ts in df.index:
                        close = float(df.loc[ts, "Close"])
                    else:
                        prior = df[:ts]["Close"].dropna()
                        close = float(prior.iloc[-1]) if not prior.empty else None
                else:
                    if ts in df.index:
                        val = df.loc[ts, ("Close", yf_ticker)]
                        close = float(val) if pd.notna(val) else None
                    else:
                        prior = df[:ts][("Close", yf_ticker)].dropna()
                        close = float(prior.iloc[-1]) if not prior.empty else None

                if close is not None:
                    # KRW 종목은 정수로 반올림
                    if ticker.isdigit() and len(ticker) == 6:
                        close = round(close)
                    else:
                        close = round(close, 2)
                    old_price = history[dt][ticker].get("price")
                    if old_price != close:
                        history[dt][ticker]["price"] = close
                        filled += 1
            except Exception:
                continue

    if filled:
        print(f"  [Portfolio Backfill] {filled}건 종가 교정 완료")


def load_portfolio_daily(path: str) -> dict:
    """portfolio_daily.json 로드."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_portfolio_snapshot(
    path: str,
    date_str: str,
    total_value_krw: float,
    cost_basis_krw: float,
    cash_value_krw: float,
    cash_pct: float,
    div_annual_krw: float,
    div_yield: float,
    usd_krw: float,
    vix: float | None,
    yield_30y: float | None,
    master_switch: str,
    holdings_count: int,
    weights_by_category: dict,
    weights_by_ticker: dict,
):
    """일별 포트폴리오 스냅샷을 portfolio_daily.json에 저장."""
    daily = load_portfolio_daily(path)

    pnl_krw = total_value_krw - cost_basis_krw
    pnl_pct = (pnl_krw / cost_basis_krw * 100) if cost_basis_krw > 0 else 0

    daily[date_str] = {
        "total_value_krw": round(total_value_krw),
        "cost_basis_krw": round(cost_basis_krw),
        "pnl_krw": round(pnl_krw),
        "pnl_pct": round(pnl_pct, 1),
        "cash_value_krw": round(cash_value_krw),
        "cash_pct": round(cash_pct, 1),
        "div_annual_krw": round(div_annual_krw),
        "div_yield": round(div_yield, 2),
        "usd_krw": round(usd_krw, 2) if usd_krw else 0,
        "vix": round(vix, 2) if vix else None,
        "yield_30y": round(yield_30y, 3) if yield_30y else None,
        "master_switch": master_switch,
        "holdings_count": holdings_count,
        "weights_by_category": weights_by_category,
        "weights_by_ticker": weights_by_ticker,
    }

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(daily, f, ensure_ascii=False, indent=2)

    return daily


def get_previous_signals(history: dict, date_str: str) -> dict:
    """
    지정 날짜 직전의 시그널 데이터를 반환.
    반환: {ticker: {signal, price, ...}}
    """
    dates = sorted([k for k in history.keys() if not k.startswith("_") and k < date_str])
    if not dates:
        return {}
    prev_date = dates[-1]
    prev_data = history[prev_date]
    return {k: v for k, v in prev_data.items() if not k.startswith("_")}
