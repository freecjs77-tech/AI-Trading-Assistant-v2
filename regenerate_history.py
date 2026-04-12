#!/usr/bin/env python3
"""
regenerate_history.py — 과거 N거래일 시그널 히스토리 + 포트폴리오 스냅샷 재생성
Yahoo Finance 직접 API로 1년치 일봉 다운로드 →
  각 거래일별 기술지표 계산 → judge_all 순차 판정 → signals_history.json
  각 거래일별 포트폴리오 가치 계산 → portfolio_daily.json (트렌드 차트용)
"""
import sys
import os
import json
import re
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

import time
import requests
import numpy as np
import pandas as pd

from fetch_market_data import (
    calc_rsi, calc_macd, calc_bollinger, calc_adx,
    find_double_bottom, macd_hist_trend, parse_portfolio_md,
)
from signal_judge import judge_all
from history_manager import save_today, save_history
from portfolio_data import is_kospi_ticker, get_ticker_class, get_ticker_name

# ── 설정 ──
NUM_TRADING_DAYS = 30
HISTORY_PATH = os.path.join(PROJECT_DIR, "history", "signals_history.json")
PORTFOLIO_DAILY_PATH = os.path.join(PROJECT_DIR, "history", "portfolio_daily.json")
SCREENSHOTS_DIR = os.path.join(PROJECT_DIR, "screenshots")
PORTFOLIO_PATH = os.path.join(PROJECT_DIR, "portfolio.md")

MACRO_SYMBOLS = {
    "VIX": "^VIX",
    "yield_30Y": "^TYX",
    "USD_KRW": "USDKRW=X",
}


def parse_portfolio_holdings(path: str) -> list[dict]:
    """portfolio.md에서 보유수량, 평가금액, 수익금액 파싱 → avg_cost 계산."""
    holdings = []
    row_pat = re.compile(r"^\|\s*([A-Z0-9]{1,10})\s*\|")
    shares_pat = re.compile(r"([\d,]+\.?\d*)\s*주")
    value_pat = re.compile(r"[\$₩]([\d,]+\.?\d+)")
    pnl_pat = re.compile(r"([+-])[\$₩]([\d,]+\.?\d+)")

    with open(path, "r", encoding="utf-8") as f:
        in_table = False
        for line in f:
            line = line.rstrip()
            if "| Ticker |" in line:
                in_table = True
                continue
            if in_table and line.startswith("|---"):
                continue
            if in_table:
                if not line.startswith("|"):
                    in_table = False
                    continue
                m = row_pat.match(line)
                if m and m.group(1) not in ("Ticker",):
                    ticker = m.group(1).strip()
                    shares = 0
                    sm = shares_pat.search(line)
                    if sm:
                        shares = float(sm.group(1).replace(",", ""))
                    values = value_pat.findall(line)
                    value = float(values[0].replace(",", "")) if values else 0
                    pnl = 0
                    pm = pnl_pat.search(line)
                    if pm:
                        pnl = float(pm.group(2).replace(",", ""))
                        if pm.group(1) == "-":
                            pnl = -pnl
                    avg_cost = (value - pnl) / shares if shares > 0 else 0
                    holdings.append({
                        "ticker": ticker,
                        "shares": shares,
                        "value": value,
                        "pnl": pnl,
                        "avg_cost": avg_cost,
                    })
    return holdings


def build_ticker_data_for_date(
    close: pd.Series, high: pd.Series, low: pd.Series, volume: pd.Series,
    target_date: pd.Timestamp,
) -> dict | None:
    """해당 날짜까지의 데이터로 기술지표 계산. fetch_ticker()와 동일한 출력 형식."""
    # target_date까지의 데이터만 사용
    mask = close.index <= target_date
    c = close[mask]
    h = high[mask]
    lo = low[mask]
    v = volume[mask]

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
    recent_high_20d = float(c.iloc[-20:].max()) if len(c) >= 20 else float(c.max())
    drawdown_20d = (last_close - recent_high_20d) / recent_high_20d * 100
    high_52w = float(c.max())
    low_52w = float(c.min())
    drawdown_52w = (last_close - high_52w) / high_52w * 100

    dbl_bottom = find_double_bottom(c)
    hist_vals = [round(float(x), 4) for x in hist.dropna().iloc[-3:].tolist()]

    bb_upper_val = safe(bb_upper)
    bb_lower_val = safe(bb_lower)
    bb_pct = None
    if bb_upper_val and bb_lower_val and (bb_upper_val - bb_lower_val) > 0:
        bb_pct = round((last_close - bb_lower_val) / (bb_upper_val - bb_lower_val) * 100, 1)

    vol_ma20_val = safe(vol_ma20)
    volume_ratio = round(float(v.iloc[-1]) / float(vol_ma20.iloc[-1]), 2) if vol_ma20_val else None

    prev_close = round(float(c.iloc[-2]), 2) if len(c) >= 2 else None
    change_pct = round((last_close / float(c.iloc[-2]) - 1) * 100, 2) if len(c) >= 2 else None
    change_3d_pct = round((last_close / float(c.iloc[-4]) - 1) * 100, 2) if len(c) >= 4 else None

    return {
        "price": round(last_close, 2),
        "prev_close": prev_close,
        "change_pct": change_pct,
        "change_3d_pct": change_3d_pct,
        "ma20": safe(ma20),
        "ma50": safe(ma50),
        "ma200": safe(ma200),
        "price_vs_ma20": "above" if last_close > (safe(ma20) or 0) else "below",
        "price_vs_ma200": "above" if (safe(ma200) and last_close > safe(ma200)) else ("below" if safe(ma200) else "N/A"),
        "rsi14": safe(rsi),
        "macd": safe(macd_line),
        "macd_signal": safe(sig_line),
        "macd_hist": safe(hist),
        "macd_hist_3d": hist_vals,
        "macd_hist_trend": macd_hist_trend(hist),
        "macd_vs_signal": "above" if (safe(macd_line) or 0) > (safe(sig_line) or 0) else "below",
        "bb_upper": bb_upper_val,
        "bb_mid": safe(bb_mid),
        "bb_lower": bb_lower_val,
        "bb_pct": bb_pct,
        "adx": safe(adx),
        "volume": int(v.iloc[-1]),
        "volume_ma20": int(vol_ma20.iloc[-1]) if vol_ma20_val else None,
        "volume_ratio": volume_ratio,
        "drawdown_20d_pct": round(drawdown_20d, 2),
        "drawdown_52w_pct": round(drawdown_52w, 2),
        "high_52w": round(high_52w, 2),
        "low_52w": round(low_52w, 2),
        "market_cap": 0,
        "data_days": len(c),
        "sig_low_stopped": bool(len(c) >= 4 and float(c.iloc[-1]) >= min(float(p) for p in c.iloc[-4:-1])),
        "double_bottom": dbl_bottom,
        "div_ttm": 0.0,
        "div_yield_ttm": 0.0,
    }


def main():
    print(f"\n{'='*60}")
    print(f"  히스토리 재생성 스크립트 (최근 {NUM_TRADING_DAYS}거래일)")
    print(f"  시그널 히스토리 + 포트폴리오 스냅샷 동시 생성")
    print(f"{'='*60}")

    # 1) 포트폴리오 티커 + 보유수량/원가 추출
    tickers, shares_map = parse_portfolio_md(PORTFOLIO_PATH)
    portfolio = parse_portfolio_holdings(PORTFOLIO_PATH)
    if "SPY" not in tickers:
        tickers.append("SPY")
    print(f"  포트폴리오: {len(tickers)}개 종목, {len(portfolio)}개 보유")

    # yfinance 심볼 매핑
    yf_map = {}
    for t in tickers:
        yf_map[t] = f"{t}.KS" if (t.isdigit() and len(t) == 6) else t

    all_yf_symbols = list(yf_map.values())

    # 매크로 심볼 추가
    for key, sym in MACRO_SYMBOLS.items():
        if sym not in all_yf_symbols:
            all_yf_symbols.append(sym)

    # 2) Yahoo Finance v8 chart API 직접 호출 (yfinance rate limit 우회)
    TICKER_DELAY = 0.5
    ticker_dfs: dict[str, pd.DataFrame] = {}

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    })

    # 먼저 crumb/cookie 가져오기
    print("  Yahoo Finance 세션 초기화 ...", end=" ", flush=True)
    try:
        resp = session.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=10)
        crumb = resp.text.strip() if resp.status_code == 200 else ""
        print(f"OK (crumb: {crumb[:8]}...)" if crumb else "crumb 없음 (계속 진행)")
    except Exception as e:
        crumb = ""
        print(f"세션 초기화 실패: {e} (계속 진행)")

    def fetch_yahoo_chart(symbol: str) -> pd.DataFrame | None:
        """Yahoo Finance v8 chart API로 1년 일봉 다운로드."""
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {
            "range": "1y",
            "interval": "1d",
            "includeAdjustedClose": "true",
        }
        if crumb:
            params["crumb"] = crumb

        try:
            resp = session.get(url, params=params, timeout=15)
            if resp.status_code == 429:
                return None  # rate limited
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

    print(f"  Yahoo Finance 다운로드: {len(all_yf_symbols)}개 심볼")

    for idx, sym in enumerate(all_yf_symbols):
        print(f"    [{idx+1:2d}/{len(all_yf_symbols)}] {sym:<12} ... ", end="", flush=True)
        for attempt in range(3):
            df = fetch_yahoo_chart(sym)
            if df is not None:
                ticker_dfs[sym] = df
                print(f"OK ({len(df)}일)")
                break
            else:
                if attempt < 2:
                    wait = 2 * (attempt + 1)
                    print(f"재시도 ({wait}s) ", end="", flush=True)
                    time.sleep(wait)
                else:
                    print("SKIP")
        time.sleep(TICKER_DELAY)

    print(f"  다운로드 완료: {len(ticker_dfs)}/{len(all_yf_symbols)}개 종목")

    def get_series(field: str, yf_sym: str) -> pd.Series:
        if yf_sym in ticker_dfs and field in ticker_dfs[yf_sym].columns:
            return ticker_dfs[yf_sym][field].dropna()
        return pd.Series(dtype=float)

    # 3) 거래일 추출 (US 기준 — SPY 인덱스 사용)
    spy_close = get_series("Close", "SPY")
    if spy_close.empty:
        print("  ERROR: SPY 데이터 없음 — 거래일 판별 불가")
        sys.exit(1)

    trading_dates = spy_close.index[-NUM_TRADING_DAYS:]
    print(f"  거래일 {len(trading_dates)}일: {trading_dates[0].strftime('%Y-%m-%d')} ~ {trading_dates[-1].strftime('%Y-%m-%d')}")

    # 4) 순차적으로 각 거래일 판정
    history = {}

    for day_idx, target_ts in enumerate(trading_dates):
        date_str = target_ts.strftime("%Y-%m-%d")
        print(f"\n  [{day_idx+1}/{len(trading_dates)}] {date_str} 판정 중 ...", end=" ", flush=True)

        # 매크로 데이터
        macro = {}
        for key, sym in MACRO_SYMBOLS.items():
            s = get_series("Close", sym)
            mask = s.index <= target_ts
            s_until = s[mask]
            macro[key] = round(float(s_until.iloc[-1]), 4) if not s_until.empty else None

        # Master switch (QQQ/SPY vs MA200)
        master = "UNKNOWN"
        for bench in ["QQQ", "SPY"]:
            yf_sym = yf_map.get(bench, bench)
            s = get_series("Close", yf_sym)
            if not s.empty:
                s_until = s[s.index <= target_ts]
                if len(s_until) >= 200:
                    ma200 = s_until.rolling(200).mean().iloc[-1]
                    if bench == "QQQ":
                        qqq_below = float(s_until.iloc[-1]) < float(ma200)
                    else:
                        spy_below = float(s_until.iloc[-1]) < float(ma200)
        try:
            if qqq_below and spy_below:
                master = "RED"
            elif qqq_below or spy_below:
                master = "YELLOW"
            else:
                master = "GREEN"
        except NameError:
            master = "UNKNOWN"

        macro["master_switch"] = master

        # 각 종목 데이터 생성
        data = {}
        success = 0
        for ticker in tickers:
            yf_sym = yf_map[ticker]
            close_s = get_series("Close", yf_sym)
            high_s = get_series("High", yf_sym)
            low_s = get_series("Low", yf_sym)
            vol_s = get_series("Volume", yf_sym)

            if close_s.empty:
                data[ticker] = {"error": "데이터 없음"}
                continue

            # KOSPI 종목은 거래일이 다를 수 있음 — 해당 날짜 이전 마지막 데이터까지 사용
            result = build_ticker_data_for_date(close_s, high_s, low_s, vol_s, target_ts)
            if result is None:
                data[ticker] = {"error": "데이터 부족 (26일 미만)"}
            else:
                data[ticker] = result
                success += 1

        market_data = {
            "_meta": {
                "date": date_str,
                "generated_at": f"{date_str} 16:30:00",
                "source": "yfinance (regenerated)",
                "tickers": tickers,
                "success": success,
                "fail": len(tickers) - success,
            },
            "_macro": macro,
            "_dividends": {},
            "data": data,
        }

        # market_data JSON 저장
        md_path = os.path.join(SCREENSHOTS_DIR, f"market_data_{date_str}.json")
        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
        with open(md_path, "w", encoding="utf-8") as f:
            json.dump(market_data, f, ensure_ascii=False, indent=2)

        # 시그널 판정
        signals = judge_all(market_data, history)

        # 히스토리에 추가
        save_today(history, date_str, signals, market_data, f"portfolio.md (regenerated)")

        # 통계 출력
        sig_counts = {}
        for t, r in signals.items():
            sig = r.get("signal", "UNKNOWN")
            sig_counts[sig] = sig_counts.get(sig, 0) + 1

        stats = ", ".join(f"{k}:{v}" for k, v in sorted(sig_counts.items()))
        print(f"OK ({success}/{len(tickers)}) [{stats}]")

    # 5) 시그널 히스토리 저장
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    save_history(history, HISTORY_PATH)
    print(f"\n  시그널 히스토리 저장: {len(history)}개 거래일 → {HISTORY_PATH}")

    # 6) portfolio_daily.json 생성 (트렌드 차트용)
    print(f"\n{'='*60}")
    print(f"  포트폴리오 스냅샷 생성 (30거래일)")
    print(f"{'='*60}")

    portfolio_daily = {}

    for day_idx, target_ts in enumerate(trading_dates):
        date_str = target_ts.strftime("%Y-%m-%d")

        # 매크로
        macro_day = {}
        for key, sym in MACRO_SYMBOLS.items():
            s = get_series("Close", sym)
            s_until = s[s.index <= target_ts]
            macro_day[key] = round(float(s_until.iloc[-1]), 4) if not s_until.empty else None

        usd_krw = macro_day.get("USD_KRW") or 1
        rate = usd_krw if usd_krw > 1 else 1

        # Master switch
        master = "UNKNOWN"
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

        # 종목별 가치 계산
        us_value = us_cost = 0
        kospi_value = kospi_cost = 0
        weights_cat = {}
        weights_ticker = {}

        for p in portfolio:
            t = p["ticker"]
            yf_sym = yf_map.get(t, t)
            s = get_series("Close", yf_sym)
            if s.empty:
                continue
            s_until = s[s.index <= target_ts]
            if s_until.empty:
                continue

            price = float(s_until.iloc[-1])
            val = p["shares"] * price
            cost = p["shares"] * p["avg_cost"]

            if is_kospi_ticker(t):
                kospi_value += val
                kospi_cost += cost
            else:
                us_value += val
                us_cost += cost

        total_value_krw = us_value * rate + kospi_value
        cost_basis_krw = us_cost * rate + kospi_cost
        pnl_krw = total_value_krw - cost_basis_krw
        pnl_pct = (pnl_krw / cost_basis_krw * 100) if cost_basis_krw > 0 else 0

        # Cash (BIL)
        bil = next((p for p in portfolio if p["ticker"] == "BIL"), None)
        cash_val = 0
        if bil:
            bil_s = get_series("Close", "BIL")
            bil_until = bil_s[bil_s.index <= target_ts]
            if not bil_until.empty:
                cash_val = bil["shares"] * float(bil_until.iloc[-1])
        cash_krw = cash_val * rate
        total_usd_equiv = us_value + kospi_value / rate if rate > 1 else us_value + kospi_value
        cash_pct = (cash_val / total_usd_equiv * 100) if total_usd_equiv > 0 else 0

        # 비중 계산
        for p in portfolio:
            t = p["ticker"]
            yf_sym = yf_map.get(t, t)
            s = get_series("Close", yf_sym)
            if s.empty:
                continue
            s_until = s[s.index <= target_ts]
            if s_until.empty:
                continue

            price = float(s_until.iloc[-1])
            val = p["shares"] * price
            val_krw = val if is_kospi_ticker(t) else val * rate
            w = (val_krw / total_value_krw * 100) if total_value_krw > 0 else 0

            display_name = get_ticker_name(t) or t if is_kospi_ticker(t) else t
            weights_ticker[display_name] = round(w, 1)

            cls = get_ticker_class(t) or "Other"
            weights_cat[cls] = weights_cat.get(cls, 0) + w

        weights_cat = {k: round(v, 1) for k, v in weights_cat.items()}

        # 배당 (고정값 — 30일간 크게 변동 없음)
        # 기존 2026-04-09 데이터 기준: div_annual_krw=42218109, div_yield=2.08
        div_annual_krw = round(42218109 * (rate / 1481.53), 0) if rate > 1 else 42218109
        div_yield = 2.08

        portfolio_daily[date_str] = {
            "total_value_krw": round(total_value_krw),
            "cost_basis_krw": round(cost_basis_krw),
            "pnl_krw": round(pnl_krw),
            "pnl_pct": round(pnl_pct, 1),
            "cash_value_krw": round(cash_krw),
            "cash_pct": round(cash_pct, 1),
            "div_annual_krw": round(div_annual_krw),
            "div_yield": round(div_yield, 2),
            "usd_krw": round(usd_krw, 2) if usd_krw else 0,
            "vix": round(macro_day.get("VIX"), 2) if macro_day.get("VIX") else None,
            "yield_30y": round(macro_day.get("yield_30Y"), 3) if macro_day.get("yield_30Y") else None,
            "master_switch": master,
            "holdings_count": len(portfolio),
            "weights_by_category": weights_cat,
            "weights_by_ticker": weights_ticker,
        }

        total_억 = total_value_krw / 100_000_000
        pnl_억 = pnl_krw / 100_000_000
        print(f"  {date_str}: 자산 {total_억:.1f}억 | PnL {pnl_pct:+.1f}% ({pnl_억:+.1f}억) | USD/KRW {usd_krw:.0f} | {master}")

    # portfolio_daily.json 저장
    os.makedirs(os.path.dirname(PORTFOLIO_DAILY_PATH), exist_ok=True)
    with open(PORTFOLIO_DAILY_PATH, "w", encoding="utf-8") as f:
        json.dump(portfolio_daily, f, ensure_ascii=False, indent=2)
    print(f"\n  포트폴리오 스냅샷 저장: {len(portfolio_daily)}일 → {PORTFOLIO_DAILY_PATH}")

    # 최종 요약
    print(f"\n{'='*60}")
    print(f"  완료!")
    print(f"  시그널 히스토리: {len(history)}일 → {HISTORY_PATH}")
    print(f"  포트폴리오 스냅샷: {len(portfolio_daily)}일 → {PORTFOLIO_DAILY_PATH}")
    print(f"{'='*60}\n")

    for dt in sorted(history.keys()):
        if dt.startswith("_"):
            continue
        day = history[dt]
        tickers_in = [k for k in day.keys() if not k.startswith("_")]
        errors = sum(1 for k in tickers_in if day[k].get("signal") == "ERROR")
        buys = sum(1 for k in tickers_in if "BUY" in day[k].get("signal", ""))
        exits = sum(1 for k in tickers_in if day[k].get("signal", "") in ("TOP_SIGNAL", "TAKE_PROFIT_1", "TAKE_PROFIT_2"))
        print(f"  {dt}: {len(tickers_in)}종목 | BUY:{buys} EXIT:{exits} ERR:{errors}")


if __name__ == "__main__":
    main()
