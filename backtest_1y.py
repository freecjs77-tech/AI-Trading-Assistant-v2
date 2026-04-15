#!/usr/bin/env python3
"""
backtest_1y.py — 과거 1년 전체 거래일 백테스트
Yahoo Finance 1년 데이터로 매일 시그널 판정 → master_switch별 BUY 승률 분석
"""
import sys
import os
import json
import time
import requests
from datetime import datetime, timedelta
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

import numpy as np
import pandas as pd

from fetch_market_data import (
    calc_rsi, calc_macd, calc_bollinger, calc_adx,
    find_double_bottom, macd_hist_trend, parse_portfolio_md,
)
from signal_judge import judge_all, _BUY_SIGNALS
from history_manager import save_today

from portfolio_paths import primary_portfolio_path as _primary_portfolio_path
PORTFOLIO_PATH = _primary_portfolio_path(PROJECT_DIR)
WIN_THRESHOLD = 3.0  # +3% 이상이면 승리

MACRO_SYMBOLS = {
    "VIX": "^VIX",
    "yield_30Y": "^TYX",
    "USD_KRW": "USDKRW=X",
}


def fetch_yahoo_chart(session, symbol, crumb=""):
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
            "Open": quote.get("open", []),
            "High": quote.get("high", []),
            "Low": quote.get("low", []),
            "Close": quote.get("close", []),
            "Volume": quote.get("volume", []),
        }, index=pd.to_datetime(timestamps, unit="s", utc=True))
        df.index = df.index.tz_localize(None)
        df = df.dropna(subset=["Close"])
        return df if len(df) >= 10 else None
    except Exception:
        return None


def build_ticker_data_for_date(close, high, low, volume, target_date):
    """해당 날짜까지의 데이터로 기술지표 계산."""
    mask = close.index <= target_date
    c, h, lo, v = close[mask], high[mask], low[mask], volume[mask]
    if len(c) < 26:
        return None

    rsi = calc_rsi(c)
    macd_line, sig_line, hist = calc_macd(c)
    bb_upper, bb_mid, bb_lower = calc_bollinger(c)
    ma20 = c.rolling(20).mean()
    ma50 = c.rolling(50).mean()
    ma200 = c.rolling(200).mean() if len(c) >= 200 else pd.Series([np.nan] * len(c), index=c.index)
    vol_ma20 = v.rolling(20).mean()
    adx = calc_adx(h, lo, c) if len(c) >= 28 else pd.Series([np.nan] * len(c), index=c.index)

    def safe(series, idx=-1):
        try:
            val = series.iloc[idx]
            return round(float(val), 4) if not (pd.isna(val) or np.isinf(val)) else None
        except (IndexError, ValueError):
            return None

    last_close = float(c.iloc[-1])
    recent_high = float(c.iloc[-20:].max()) if len(c) >= 20 else float(c.max())
    drawdown_20d = (last_close - recent_high) / recent_high * 100
    high_52w = float(c.max())
    low_52w = float(c.min())
    drawdown_52w = (last_close - high_52w) / high_52w * 100
    dbl_bottom = find_double_bottom(c)
    hist_vals = [round(float(x), 4) for x in hist.dropna().iloc[-3:].tolist()]
    bb_upper_val, bb_lower_val = safe(bb_upper), safe(bb_lower)
    bb_pct = None
    if bb_upper_val and bb_lower_val and (bb_upper_val - bb_lower_val) > 0:
        bb_pct = round((last_close - bb_lower_val) / (bb_upper_val - bb_lower_val) * 100, 1)
    vol_ma20_val = safe(vol_ma20)
    volume_ratio = round(float(v.iloc[-1]) / float(vol_ma20.iloc[-1]), 2) if vol_ma20_val else None

    return {
        "price": round(last_close, 2),
        "prev_close": round(float(c.iloc[-2]), 2) if len(c) >= 2 else None,
        "change_pct": round((last_close / float(c.iloc[-2]) - 1) * 100, 2) if len(c) >= 2 else None,
        "change_3d_pct": round((last_close / float(c.iloc[-4]) - 1) * 100, 2) if len(c) >= 4 else None,
        "ma20": safe(ma20), "ma50": safe(ma50), "ma200": safe(ma200),
        "price_vs_ma20": "above" if last_close > (safe(ma20) or 0) else "below",
        "price_vs_ma200": "above" if (safe(ma200) and last_close > safe(ma200)) else ("below" if safe(ma200) else "N/A"),
        "rsi14": safe(rsi),
        "macd": safe(macd_line), "macd_signal": safe(sig_line), "macd_hist": safe(hist),
        "macd_hist_3d": hist_vals, "macd_hist_trend": macd_hist_trend(hist),
        "macd_vs_signal": "above" if (safe(macd_line) or 0) > (safe(sig_line) or 0) else "below",
        "bb_upper": bb_upper_val, "bb_mid": safe(bb_mid), "bb_lower": bb_lower_val, "bb_pct": bb_pct,
        "adx": safe(adx),
        "volume": int(v.iloc[-1]),
        "volume_ma20": int(vol_ma20.iloc[-1]) if vol_ma20_val else None,
        "volume_ratio": volume_ratio,
        "drawdown_20d_pct": round(drawdown_20d, 2), "drawdown_52w_pct": round(drawdown_52w, 2),
        "high_52w": round(high_52w, 2), "low_52w": round(low_52w, 2),
        "market_cap": 0, "data_days": len(c),
        "sig_low_stopped": bool(len(c) >= 4 and float(c.iloc[-1]) >= min(float(p) for p in c.iloc[-4:-1])),
        "double_bottom": dbl_bottom, "div_ttm": 0.0, "div_yield_ttm": 0.0,
    }


def main():
    print(f"\n{'='*60}")
    print(f"  1년 백테스트 — master_switch별 BUY 승률 분석")
    print(f"{'='*60}")

    # 1) 티커 목록
    tickers, _ = parse_portfolio_md(PORTFOLIO_PATH)
    if "SPY" not in tickers:
        tickers.append("SPY")

    yf_map = {}
    for t in tickers:
        from portfolio_data import to_yfinance_symbol
        yf_map[t] = to_yfinance_symbol(t)

    all_yf_symbols = list(yf_map.values())
    for sym in MACRO_SYMBOLS.values():
        if sym not in all_yf_symbols:
            all_yf_symbols.append(sym)

    # 2) 데이터 다운로드
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    try:
        resp = session.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=10)
        crumb = resp.text.strip() if resp.status_code == 200 else ""
    except Exception:
        crumb = ""

    print(f"  다운로드: {len(all_yf_symbols)}개 심볼")
    ticker_dfs = {}
    for idx, sym in enumerate(all_yf_symbols):
        print(f"    [{idx+1:2d}/{len(all_yf_symbols)}] {sym:<12} ... ", end="", flush=True)
        for attempt in range(3):
            df = fetch_yahoo_chart(session, sym, crumb)
            if df is not None:
                ticker_dfs[sym] = df
                print(f"OK ({len(df)}일)")
                break
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                print(f"재시도 ", end="", flush=True)
            else:
                print("SKIP")
        time.sleep(0.5)

    def get_series(field, yf_sym):
        if yf_sym in ticker_dfs and field in ticker_dfs[yf_sym].columns:
            return ticker_dfs[yf_sym][field].dropna()
        return pd.Series(dtype=float)

    # 3) 거래일 목록 (SPY 기준, 초반 200일 제외 — MA200 계산 필요)
    spy_close = get_series("Close", "SPY")
    if spy_close.empty:
        print("  ERROR: SPY 데이터 없음")
        return

    # MA200 계산에 200일 필요하므로 201번째 거래일부터 시작
    start_idx = max(200, 0)
    all_trading_dates = spy_close.index[start_idx:]
    print(f"  분석 대상: {len(all_trading_dates)}거래일 ({all_trading_dates[0].strftime('%Y-%m-%d')} ~ {all_trading_dates[-1].strftime('%Y-%m-%d')})")

    # 4) 전 거래일 시그널 판정 + 수익률 계산
    # BUY 시그널 기록: (date, ticker, signal, master_switch, entry_price)
    buy_signals = []
    history = {}
    day_count = len(all_trading_dates)

    for day_idx, target_ts in enumerate(all_trading_dates):
        date_str = target_ts.strftime("%Y-%m-%d")

        if day_idx % 20 == 0:
            print(f"  [{day_idx+1}/{day_count}] {date_str} ...", flush=True)

        # 매크로
        macro = {}
        for key, sym in MACRO_SYMBOLS.items():
            s = get_series("Close", sym)
            s_until = s[s.index <= target_ts]
            macro[key] = round(float(s_until.iloc[-1]), 4) if not s_until.empty else None

        # Master switch
        qqq_below = spy_below = False
        for bench in ["QQQ", "SPY"]:
            yf_sym = yf_map.get(bench, bench)
            s = get_series("Close", yf_sym)
            if not s.empty:
                s_until = s[s.index <= target_ts]
                if len(s_until) >= 200:
                    ma200_val = float(s_until.rolling(200).mean().iloc[-1])
                    if bench == "QQQ":
                        qqq_below = float(s_until.iloc[-1]) < ma200_val
                    else:
                        spy_below = float(s_until.iloc[-1]) < ma200_val
        if qqq_below and spy_below:
            master = "RED"
        elif qqq_below or spy_below:
            master = "YELLOW"
        else:
            master = "GREEN"
        macro["master_switch"] = master

        # 종목 데이터
        data = {}
        for ticker in tickers:
            yf_sym = yf_map[ticker]
            c_s = get_series("Close", yf_sym)
            h_s = get_series("High", yf_sym)
            l_s = get_series("Low", yf_sym)
            v_s = get_series("Volume", yf_sym)
            if c_s.empty:
                data[ticker] = {"error": "no data"}
                continue
            result = build_ticker_data_for_date(c_s, h_s, l_s, v_s, target_ts)
            if result is None:
                data[ticker] = {"error": "insufficient"}
            else:
                data[ticker] = result

        market_data = {
            "_meta": {"date": date_str},
            "_macro": macro,
            "_dividends": {},
            "data": data,
        }

        signals = judge_all(market_data, history)
        save_today(history, date_str, signals, market_data, "backtest_1y")

        # BUY 시그널 기록
        for ticker, r in signals.items():
            sig = r.get("signal", "")
            if sig in _BUY_SIGNALS:
                buy_signals.append({
                    "date": date_str,
                    "date_ts": target_ts,
                    "ticker": ticker,
                    "signal": sig,
                    "master_switch": master,
                    "price": r.get("price"),
                    "rsi": r.get("rsi"),
                })

    print(f"\n  시그널 판정 완료: {len(buy_signals)}건 BUY")

    # 5) BUY 시그널별 N일 후 수익률 계산
    results_by_switch = defaultdict(lambda: {
        "total": 0,
        "by_signal": defaultdict(lambda: {"count": 0, "wins_5d": 0, "wins_10d": 0, "returns_5d": [], "returns_10d": [], "reach": 0, "reach_total": 0}),
    })

    for bs in buy_signals:
        ticker = bs["ticker"]
        yf_sym = yf_map.get(ticker, ticker)
        c_s = get_series("Close", yf_sym)
        if c_s.empty:
            continue

        entry_price = bs["price"]
        if not entry_price or entry_price <= 0:
            continue

        # 시그널일 이후 거래일
        future_days = c_s.index[c_s.index > bs["date_ts"]]
        if len(future_days) < 5:
            continue  # 5일 후 데이터 없으면 스킵

        ms = bs["master_switch"]
        sig = bs["signal"]
        bucket = results_by_switch[ms]["by_signal"][sig]
        bucket["count"] += 1
        results_by_switch[ms]["total"] += 1

        # 5D return
        if len(future_days) >= 5:
            price_5d = float(c_s.loc[future_days[4]])
            ret_5d = (price_5d - entry_price) / entry_price * 100
            bucket["returns_5d"].append(ret_5d)
            if ret_5d >= WIN_THRESHOLD:
                bucket["wins_5d"] += 1

        # 10D return
        if len(future_days) >= 10:
            price_10d = float(c_s.loc[future_days[9]])
            ret_10d = (price_10d - entry_price) / entry_price * 100
            bucket["returns_10d"].append(ret_10d)
            if ret_10d >= WIN_THRESHOLD:
                bucket["wins_10d"] += 1

        # Reach (max gain in 10d)
        max_days = min(10, len(future_days))
        if max_days > 0:
            max_price = max(float(c_s.loc[future_days[i]]) for i in range(max_days))
            max_gain = (max_price - entry_price) / entry_price * 100
            bucket["reach_total"] += 1
            if max_gain >= WIN_THRESHOLD:
                bucket["reach"] += 1

    # 6) 결과 출력
    print(f"\n{'='*70}")
    print(f"  1년 백테스트 결과 — master_switch별 BUY 승률")
    print(f"  기간: {all_trading_dates[0].strftime('%Y-%m-%d')} ~ {all_trading_dates[-1].strftime('%Y-%m-%d')}")
    print(f"  승리 기준: +{WIN_THRESHOLD}% 이상")
    print(f"{'='*70}")

    for ms in ["GREEN", "YELLOW", "RED"]:
        data = results_by_switch.get(ms)
        if not data or data["total"] == 0:
            continue

        print(f"\n  {'='*50}")
        print(f"  {ms} (총 {data['total']}건)")
        print(f"  {'='*50}")
        print(f"  {'시그널':<12} {'건수':>5} {'5D승률':>8} {'10D승률':>9} {'도달률':>8} {'평균5D':>9} {'평균10D':>9}")
        print(f"  {'-'*62}")

        total_5d_wins = 0
        total_10d_wins = 0
        total_5d_n = 0
        total_10d_n = 0
        total_reach = 0
        total_reach_n = 0

        for sig in ["1st_BUY", "2nd_BUY", "3rd_BUY"]:
            b = data["by_signal"].get(sig)
            if not b or b["count"] == 0:
                continue
            n = b["count"]
            n5 = len(b["returns_5d"])
            n10 = len(b["returns_10d"])
            wr5 = b["wins_5d"] / n5 * 100 if n5 else 0
            wr10 = b["wins_10d"] / n10 * 100 if n10 else 0
            reach = b["reach"] / b["reach_total"] * 100 if b["reach_total"] else 0
            avg5 = sum(b["returns_5d"]) / n5 if n5 else 0
            avg10 = sum(b["returns_10d"]) / n10 if n10 else 0

            total_5d_wins += b["wins_5d"]
            total_10d_wins += b["wins_10d"]
            total_5d_n += n5
            total_10d_n += n10
            total_reach += b["reach"]
            total_reach_n += b["reach_total"]

            print(f"  {sig:<12} {n:>5} {wr5:>7.1f}% {wr10:>8.1f}% {reach:>7.1f}% {avg5:>+8.2f}% {avg10:>+8.2f}%")

        # 합계
        if total_5d_n > 0:
            print(f"  {'-'*62}")
            wr5_t = total_5d_wins / total_5d_n * 100
            wr10_t = total_10d_wins / total_10d_n * 100 if total_10d_n else 0
            reach_t = total_reach / total_reach_n * 100 if total_reach_n else 0
            print(f"  {'합계':<12} {data['total']:>5} {wr5_t:>7.1f}% {wr10_t:>8.1f}% {reach_t:>7.1f}%")

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    main()
