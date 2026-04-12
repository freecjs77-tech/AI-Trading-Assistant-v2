#!/usr/bin/env python3
"""
rerun_backtest.py — outcomes.json 초기화 후 백테스트 재실행
Yahoo Finance API 직접 호출로 yfinance rate limit 우회.
"""
import sys
import os
import json
import time
import requests
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

import pandas as pd

from backtest_evaluator import (
    _EVAL_DAYS, _CALENDAR_BUFFER, _TRACKABLE_SIGNALS,
    _merge_all_histories, _calc_max_gain_loss_td,
    save_outcomes, analyze_accuracy,
)

HISTORY_PATH = os.path.join(PROJECT_DIR, "history", "signals_history.json")
OUTCOMES_PATH = os.path.join(PROJECT_DIR, "history", "outcomes.json")
ANALYSIS_PATH = os.path.join(PROJECT_DIR, "history", "backtest_analysis.json")


def fetch_yahoo_chart(session, symbol, crumb=""):
    """Yahoo Finance v8 chart API로 1년 일봉 다운로드."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": "1y", "interval": "1d", "includeAdjustedClose": "true"}
    if crumb:
        params["crumb"] = crumb
    try:
        resp = session.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        chart = data.get("chart", {}).get("result", [])
        if not chart:
            return None
        result = chart[0]
        timestamps = result.get("timestamp", [])
        quote = result.get("indicators", {}).get("quote", [{}])[0]
        if not timestamps or not quote:
            return None
        df = pd.DataFrame({
            "Close": quote.get("close", []),
            "High": quote.get("high", []),
            "Low": quote.get("low", []),
        }, index=pd.to_datetime(timestamps, unit="s", utc=True))
        df.index = df.index.tz_localize(None)
        df = df.dropna(subset=["Close"])
        return df if len(df) >= 10 else None
    except Exception:
        return None


def main():
    print(f"\n{'='*60}")
    print(f"  백테스트 재실행 (outcomes.json 초기화)")
    print(f"{'='*60}")

    # 1) 히스토리 로드
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        history = json.load(f)

    # 스캐너 히스토리 로드
    scanner_histories = {}
    for name in ["sp100", "etf", "kospi"]:
        path = os.path.join(PROJECT_DIR, "history", f"scanner_{name}_history.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                scanner_histories[name] = json.load(f)

    # 2) 평가 대상 시그널 수집
    merged = _merge_all_histories(history, scanner_histories)
    print(f"  평가 대상 시그널: {len(merged)}건")

    if not merged:
        print("  평가할 시그널 없음")
        return

    # 필터: entry_price 유효한 것만
    valid = [(d, t, info, src, macro) for d, t, info, src, macro in merged
             if info.get("price") and info.get("price") > 0]
    print(f"  유효 시그널 (price > 0): {len(valid)}건")

    # 3) 필요한 티커 수집 + Yahoo API 다운로드
    tickers_needed = list({t for _, t, _, _, _ in valid})
    if "SPY" not in tickers_needed:
        tickers_needed.append("SPY")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })

    # crumb
    try:
        resp = session.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=10)
        crumb = resp.text.strip() if resp.status_code == 200 else ""
    except Exception:
        crumb = ""

    print(f"  Yahoo Finance 다운로드: {len(tickers_needed)}개 종목")
    ticker_dfs = {}
    for idx, t in enumerate(tickers_needed):
        yf_sym = f"{t}.KS" if (t.isdigit() and len(t) == 6) else t
        print(f"    [{idx+1:2d}/{len(tickers_needed)}] {yf_sym:<12} ... ", end="", flush=True)
        for attempt in range(3):
            df = fetch_yahoo_chart(session, yf_sym, crumb)
            if df is not None:
                ticker_dfs[t] = df
                print(f"OK ({len(df)}일)")
                break
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                print(f"재시도 ", end="", flush=True)
            else:
                print("SKIP")
        time.sleep(0.5)

    print(f"  다운로드 완료: {len(ticker_dfs)}/{len(tickers_needed)}")

    # 4) 각 시그널 평가
    outcomes = {"_meta": {"last_evaluated": "", "total_signals": 0}, "records": []}
    evaluated = 0
    skipped_no_data = 0

    for date_str, ticker, info, source, macro in valid:
        if ticker not in ticker_dfs:
            skipped_no_data += 1
            continue

        df = ticker_dfs[ticker]
        entry_price = info["price"]
        sig_date = pd.Timestamp(datetime.strptime(date_str, "%Y-%m-%d"))

        # 시그널일 이후 거래일
        trading_days = list(df.index[df.index > sig_date])
        if not trading_days:
            skipped_no_data += 1
            continue

        outcomes_data = {}

        for eval_day in _EVAL_DAYS:
            if eval_day <= len(trading_days):
                td = trading_days[eval_day - 1]
                price = float(df.loc[td, "Close"])
                ret = round((price - entry_price) / entry_price * 100, 2)
                if ticker.isdigit() and len(ticker) == 6:
                    outcomes_data[f"{eval_day}d"] = {"price": round(price), "return_pct": ret}
                else:
                    outcomes_data[f"{eval_day}d"] = {"price": round(price, 2), "return_pct": ret}

            # SPY 벤치마크
            if ticker != "SPY" and "SPY" in ticker_dfs:
                spy_df = ticker_dfs["SPY"]
                spy_days = list(spy_df.index[spy_df.index > sig_date])
                spy_near = spy_df.index[spy_df.index >= sig_date]
                if len(spy_near) > 0 and eval_day <= len(spy_days):
                    spy_entry = float(spy_df.loc[spy_near[0], "Close"])
                    spy_price = float(spy_df.loc[spy_days[eval_day - 1], "Close"])
                    spy_ret = round((spy_price - spy_entry) / spy_entry * 100, 2)
                    outcomes_data[f"spy_{eval_day}d"] = spy_ret

        # max gain/loss (10거래일 내)
        max_eval = max(_EVAL_DAYS)
        max_gain = max_loss = None
        for td in trading_days[:max_eval]:
            price = float(df.loc[td, "Close"])
            ret = (price - entry_price) / entry_price * 100
            if max_gain is None or ret > max_gain:
                max_gain = round(ret, 2)
            if max_loss is None or ret < max_loss:
                max_loss = round(ret, 2)
        if max_gain is not None:
            outcomes_data["max_gain_10d"] = max_gain
        if max_loss is not None:
            outcomes_data["max_loss_10d"] = max_loss

        if outcomes_data:
            signal = info.get("signal", "")
            record_id = f"{date_str}|{ticker}|{signal}|{source}"
            outcomes["records"].append({
                "id": record_id,
                "ticker": ticker,
                "signal": signal,
                "date": date_str,
                "source": source,
                "entry_price": entry_price,
                "context": {
                    "rsi": info.get("rsi"),
                    "macd_hist": info.get("macd_hist"),
                    "macd_hist_trend": info.get("macd_hist_trend"),
                    "drawdown": info.get("drawdown"),
                    "bb_pct": info.get("bb_pct"),
                    "price_vs_ma20": info.get("price_vs_ma20"),
                    "vix": macro.get("VIX") if macro else None,
                    "master_switch": macro.get("master_switch") if macro else None,
                },
                "note": info.get("note", ""),
                "outcomes": outcomes_data,
                "evaluated_at": datetime.now().strftime("%Y-%m-%d"),
            })
            evaluated += 1

    outcomes["_meta"]["last_evaluated"] = datetime.now().strftime("%Y-%m-%d")
    outcomes["_meta"]["total_signals"] = len(outcomes["records"])
    save_outcomes(outcomes, OUTCOMES_PATH)

    print(f"\n  평가 완료: {evaluated}건 (데이터 없음 스킵: {skipped_no_data}건)")

    # 5) 분석 실행
    print(f"\n  분석 실행 중...")
    analysis = analyze_accuracy(outcomes, ANALYSIS_PATH)

    # 6) 결과 요약
    print(f"\n{'='*60}")
    print(f"  백테스트 결과 요약")
    print(f"{'='*60}")
    print(f"  총 평가: {analysis['total_records']}건")
    print(f"  데이터 상태: {analysis['data_status']}")

    for sig, stats in analysis.get("by_signal", {}).items():
        wr3 = stats.get("win_rate_3d", "N/A")
        wr5 = stats.get("win_rate_5d", "N/A")
        wr10 = stats.get("win_rate_10d", "N/A")
        reach = stats.get("reach_rate_10d", "N/A")
        avg5 = stats.get("avg_return_5d", "N/A")
        n = stats.get("samples_5d", 0)
        print(f"  {sig:<16} n={n:>3} | 3D:{wr3} 5D:{wr5} 10D:{wr10} | reach:{reach} | avg5D:{avg5}%")

    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
