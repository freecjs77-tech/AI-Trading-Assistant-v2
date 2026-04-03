"""
history_manager.py — 시그널 이력 관리
AI Trading Assistant v3.0

signals_history.json의 로드/저장/가지치기(30일) 관리.
변경④: price_vs_ma20, ma20 필드 추가 저장.
"""

import json
import os
from datetime import datetime, timedelta


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
