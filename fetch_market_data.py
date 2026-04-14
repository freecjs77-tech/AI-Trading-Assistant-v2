#!/usr/bin/env python3
"""
fetch_market_data.py — AI Trading Assistant 기술지표 수집기 v2.1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
yfinance로 실시간 기술지표를 수집해 screenshots/market_data_YYYY-MM-DD.json에 저장합니다.
리포트 생성 시 이 파일을 자동으로 읽어 정확한 데이터로 시그널을 판정합니다.

수집 지표 (개별 종목):
  현재가, MA20/MA50/MA200, RSI(14), MACD/Signal/Hist (최근 3일 추세),
  Bollinger Bands (상단/중단/하단), ADX(14), 거래량/20일평균 거래량/비율,
  최근 20일 고점 대비 하락률,
  ★ 배당 (TTM): div_ttm (연간 배당/주), div_yield_ttm (배당수익률%)

수집 지표 (매크로 — 자동 포함):
  VIX (^VIX), 30Y 국채 금리 (^TYX), USD/KRW 환율 (USDKRW=X)

★ 포트폴리오 배당 집계 (_dividends 섹션):
  portfolio.md에서 보유주수를 읽어 종목별·합산 예상 연간 배당금을 계산합니다.
  직접 종목 입력 시에는 집계 생략 (보유주수 알 수 없음).

사용법:
  python fetch_market_data.py                          # portfolio.md 자동 읽기
  python fetch_market_data.py AAPL TSLA NVDA           # 직접 종목 입력
  python fetch_market_data.py --file tickers.txt       # 파일에서 읽기
  python fetch_market_data.py AAPL --add PLTR --add O  # portfolio.md + 추가 종목
  python fetch_market_data.py --output my_data.json    # 출력 경로 지정
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
import json
import re
import os
import argparse
from datetime import datetime, date, timezone, timedelta

KST = timezone(timedelta(hours=9))
EST = timezone(timedelta(hours=-5))   # 미국 동부 표준시 (보수적 기준)


def is_market_open_us() -> bool:
    """미국 시장 개장 여부 (09:30~16:00 ET, 평일). 서머타임 포함 보수적 판단."""
    now_utc = datetime.now(timezone.utc)
    weekday = now_utc.weekday()
    if weekday >= 5:
        return False
    h, m = now_utc.hour, now_utc.minute
    # 서머타임: 13:30~20:00 UTC, 표준시: 14:30~21:00 UTC → 보수적으로 13:30~21:00
    mins = h * 60 + m
    return 13 * 60 + 30 <= mins < 21 * 60


def is_market_open_krx() -> bool:
    """한국 시장 개장 여부 (09:00~15:30 KST, 평일)."""
    now_kst = datetime.now(KST)
    weekday = now_kst.weekday()
    if weekday >= 5:
        return False
    h, m = now_kst.hour, now_kst.minute
    mins = h * 60 + m
    return 9 * 60 <= mins < 15 * 60 + 30


def get_market_status() -> dict:
    """US/KRX 시장 상태 반환."""
    return {
        "US": "open" if is_market_open_us() else "closed",
        "KRX": "open" if is_market_open_krx() else "closed",
    }


# ── 의존성 확인 ──────────────────────────────────────
try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
except ImportError as e:
    print(f"\n❌ 필요한 패키지가 없습니다: {e}")
    print("   아래 명령어로 설치하세요:")
    print("   pip install yfinance pandas numpy\n")
    sys.exit(1)


# ── 기술지표 계산 함수 ───────────────────────────────

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_macd(close: pd.Series, fast=12, slow=26, signal=9):
    """MACD, Signal Line, Histogram 반환"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - signal_line
    return macd, signal_line, hist


def calc_bollinger(close: pd.Series, period=20, num_std=2):
    """Bollinger Bands: upper, mid, lower"""
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    return mid + num_std * std, mid, mid - num_std * std


def calc_adx(high: pd.Series, low: pd.Series, close: pd.Series, period=14) -> pd.Series:
    """Average Directional Index (ADX)"""
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)

    dm_plus = high.diff()
    dm_minus = -low.diff()
    dm_plus = dm_plus.where((dm_plus > dm_minus) & (dm_plus > 0), 0.0)
    dm_minus = dm_minus.where((dm_minus > dm_plus) & (dm_minus > 0), 0.0)

    atr = tr.ewm(com=period - 1, min_periods=period).mean()
    di_plus  = 100 * dm_plus.ewm(com=period - 1, min_periods=period).mean() / atr
    di_minus = 100 * dm_minus.ewm(com=period - 1, min_periods=period).mean() / atr

    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
    return dx.ewm(com=period - 1, min_periods=period).mean()


def find_double_bottom(close: pd.Series, lookback=60, tolerance=0.03) -> dict:
    """
    최근 lookback일 일봉에서 이중 바닥 패턴 탐지.
    로컬 최저점(local minima)을 찾고 가장 최근 2개 비교.
    tolerance: 두 저점 간 허용 차이 비율 (기본 3%)
    반환: {
        "detected": bool,
        "low1": {"date": str, "price": float},
        "low2": {"date": str, "price": float},
        "diff_pct": float,  # 두 저점 간 차이 %
    }
    """
    data = close.iloc[-lookback:] if len(close) >= lookback else close
    if len(data) < 10:
        return {"detected": False}

    prices = data.values
    dates = data.index

    # 로컬 최저점 찾기: 양쪽보다 낮은 점 (±2일 윈도우)
    lows = []
    window = 3
    for i in range(window, len(prices) - window):
        local_min = min(prices[i - window:i + window + 1])
        if prices[i] == local_min:
            dt_str = str(dates[i].date()) if hasattr(dates[i], 'date') else str(dates[i])[:10]
            lows.append({"date": dt_str, "price": round(float(prices[i]), 2), "idx": i})

    # 너무 가까운 저점 병합 (5일 이내 → 더 낮은 것만 유지)
    merged = []
    for low in lows:
        if merged and low["idx"] - merged[-1]["idx"] < 5:
            if low["price"] < merged[-1]["price"]:
                merged[-1] = low
        else:
            merged.append(low)

    if len(merged) < 2:
        return {"detected": False}

    # 가장 최근 2개 저점 비교
    low1 = merged[-2]  # 이전 저점
    low2 = merged[-1]  # 최근 저점
    diff_pct = abs(low2["price"] - low1["price"]) / low1["price"] * 100

    detected = diff_pct <= tolerance * 100  # 3% 이내

    # Higher Low: 최근 저점(low2)이 이전 저점(low1)보다 높으면 저점 상승 추세
    higher_low = low2["price"] > low1["price"]

    return {
        "detected": detected,
        "higher_low": higher_low,
        "low1": {"date": low1["date"], "price": low1["price"]},
        "low2": {"date": low2["date"], "price": low2["price"]},
        "diff_pct": round(diff_pct, 2),
    }


def macd_hist_trend(hist_series: pd.Series, lookback=3) -> str:
    """최근 N일 MACD 히스토그램 추세 문자열 반환"""
    vals = hist_series.dropna().iloc[-lookback:].tolist()
    if len(vals) < 2:
        return "N/A"
    diffs = [vals[i] - vals[i-1] for i in range(1, len(vals))]
    if all(d > 0 for d in diffs):
        return f"increasing_{len(diffs)}d"
    if all(d < 0 for d in diffs):
        return f"decreasing_{len(diffs)}d"
    return "mixed"


# ── 매크로 지표 수집 ─────────────────────────────────

def fetch_macro() -> dict:
    """
    VIX, 30Y 국채 금리, USD/KRW 환율을 yfinance로 수집.
    항상 자동 실행됨 (별도 옵션 불필요).
    """
    macro = {}
    targets = {
        "VIX":      "^VIX",
        "yield_30Y":"^TYX",   # 30Y Treasury yield (값 그대로 %, 예: 4.97)
        "USD_KRW":  "USDKRW=X",
    }
    for key, symbol in targets.items():
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="5d", interval="1d", auto_adjust=True)
            if df is not None and not df.empty:
                df = df[df["Close"].notna()]
            if df is not None and not df.empty:
                val = float(df["Close"].iloc[-1])
                macro[key] = round(val, 4)
            else:
                macro[key] = None
        except Exception as e:
            macro[key] = None

    # Master switch 판정 (참고용)
    # QQQ, SPY 는 개별 종목 수집 결과에서 가져오므로 여기선 스킵
    macro["fetched_at"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    return macro


# ── 단일 종목 수집 ───────────────────────────────────

def fetch_div_ttm(ticker: "yf.Ticker", current_price: float) -> tuple[float, float]:
    """
    TTM(최근 12개월) 배당/주 및 배당수익률 계산.
    반환: (div_ttm, div_yield_pct)  — 실패 시 (0.0, 0.0)
    """
    # 방법 1: ticker.dividends (배당 히스토리에서 직접 합산)
    try:
        divs = ticker.dividends
        if divs is not None and len(divs) > 0:
            idx = divs.index.tz_localize(None) if divs.index.tzinfo else divs.index
            cutoff = pd.Timestamp.now() - pd.DateOffset(years=1)
            ttm = divs[idx >= cutoff]
            if len(ttm) > 0:
                div_ttm = round(float(ttm.sum()), 4)
                div_yield = round(div_ttm / current_price * 100, 4) if current_price > 0 else 0.0
                return div_ttm, div_yield
    except Exception:
        pass

    # 방법 2: ticker.info fallback (yfinance 버전 호환성)
    try:
        info = ticker.info or {}
        div_ttm = info.get("trailingAnnualDividendRate") or info.get("dividendRate") or 0.0
        if div_ttm and div_ttm > 0:
            div_yield = round(float(div_ttm) / current_price * 100, 4) if current_price > 0 else 0.0
            return round(float(div_ttm), 4), div_yield
    except Exception:
        pass

    return 0.0, 0.0


def fetch_ticker(symbol: str) -> dict:
    """yfinance로 종목 데이터 수집 후 기술지표 계산 (배당 포함)"""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="1y", interval="1d", auto_adjust=True)

        if df is None or df.empty:
            return {"error": "데이터 없음 (상장폐지 또는 심볼 오류)"}

        # 장 시작 전 auto_adjust가 NaN 행을 생성하는 문제 방지
        df = df[df["Close"].notna()]

        if len(df) < 26:
            return {"error": f"데이터 부족 ({len(df)}일, 최소 26일 필요)"}

        close  = df["Close"]
        high   = df["High"]
        low    = df["Low"]
        volume = df["Volume"]

        rsi                       = calc_rsi(close)
        macd, sig_line, hist      = calc_macd(close)
        bb_upper, bb_mid, bb_lower = calc_bollinger(close)
        ma20  = close.rolling(20).mean()
        ma50  = close.rolling(50).mean()
        ma200 = close.rolling(200).mean() if len(close) >= 200 else pd.Series([np.nan] * len(close), index=close.index)
        vol_ma20 = volume.rolling(20).mean()
        adx  = calc_adx(high, low, close) if len(df) >= 28 else pd.Series([np.nan] * len(df), index=df.index)

        last_close  = float(close.iloc[-1])
        recent_high = float(close.iloc[-20:].max())
        drawdown    = (last_close - recent_high) / recent_high * 100
        high_52w    = float(close.max())  # 전체 기간(~1년) 최고점
        low_52w     = float(close.min())  # 전체 기간(~1년) 최저점
        drawdown_52w = (last_close - high_52w) / high_52w * 100

        # 이중 바닥 패턴 탐지
        dbl_bottom = find_double_bottom(close)

        # 시가총액
        try:
            market_cap = ticker.info.get("marketCap", 0) or 0
        except Exception:
            market_cap = 0

        # 배당 수집 (TTM)
        div_ttm, div_yield_ttm = fetch_div_ttm(ticker, last_close)

        def safe(series, idx=-1):
            v = series.iloc[idx]
            return round(float(v), 4) if not (pd.isna(v) or np.isinf(v)) else None

        hist_vals = [round(float(x), 4) for x in hist.dropna().iloc[-3:].tolist()]

        return {
            "price":             round(last_close, 2),
            "prev_close":        round(float(close.iloc[-2]), 2) if len(close) >= 2 else None,
            "change_pct":        round((last_close / float(close.iloc[-2]) - 1) * 100, 2) if len(close) >= 2 else None,
            "change_3d_pct":     round((last_close / float(close.iloc[-4]) - 1) * 100, 2) if len(close) >= 4 else None,
            # 이동평균
            "ma20":              safe(ma20),
            "ma50":              safe(ma50),
            "ma200":             safe(ma200),
            "price_vs_ma20":     "above" if last_close > (safe(ma20) or 0) else "below",
            "price_vs_ma200":    "above" if (safe(ma200) and last_close > safe(ma200)) else ("below" if safe(ma200) else "N/A"),
            # RSI
            "rsi14":             safe(rsi),
            # MACD
            "macd":              safe(macd),
            "macd_signal":       safe(sig_line),
            "macd_hist":         safe(hist),
            "macd_hist_3d":      hist_vals,
            "macd_hist_trend":   macd_hist_trend(hist),
            "macd_vs_signal":    "above" if (safe(macd) or 0) > (safe(sig_line) or 0) else "below",
            # Bollinger Bands
            "bb_upper":          safe(bb_upper),
            "bb_mid":            safe(bb_mid),
            "bb_lower":          safe(bb_lower),
            "bb_pct":            round((last_close - (safe(bb_lower) or 0)) / ((safe(bb_upper) or 1) - (safe(bb_lower) or 0)) * 100, 1) if safe(bb_upper) and safe(bb_lower) else None,
            # ADX
            "adx":               safe(adx),
            # 거래량
            "volume":            int(volume.iloc[-1]),
            "volume_ma20":       int(vol_ma20.iloc[-1]) if safe(vol_ma20) else None,
            "volume_ratio":      round(float(volume.iloc[-1]) / float(vol_ma20.iloc[-1]), 2) if safe(vol_ma20) else None,
            # 기타
            "drawdown_20d_pct":  round(drawdown, 2),
            "drawdown_52w_pct":  round(drawdown_52w, 2),
            "high_52w":          round(high_52w, 2),
            "low_52w":           round(low_52w, 2),
            "market_cap":        market_cap,
            "data_days":         len(df),
            "fetched_at":        datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
            # 하락 멈춤: 오늘 종가 >= 최근 3일 최저 종가 (저점 갱신 없음)
            "sig_low_stopped":   bool(len(close) >= 4 and float(close.iloc[-1]) >= min(float(p) for p in close.iloc[-4:-1])),
            # 이중 바닥 패턴
            "double_bottom":     dbl_bottom,
            # 배당 (TTM — 최근 12개월 합산)
            "div_ttm":           div_ttm,       # 연간 배당/주 ($)
            "div_yield_ttm":     div_yield_ttm, # 배당수익률 (%)
            "_last_date":        df.index[-1].strftime("%Y-%m-%d"),  # 마지막 거래일
        }

    except Exception as e:
        return {"error": str(e)}


# ── portfolio.md 파싱 ────────────────────────────────

def parse_portfolio_md(path: str) -> tuple[list[str], dict[str, float]]:
    """
    portfolio.md에서 Ticker 심볼과 보유주수를 함께 추출.
    반환: (tickers 리스트, {ticker: shares} 딕셔너리)
    보유주수 컬럼이 없는 경우 shares 딕셔너리는 빈 값.
    """
    tickers = []
    shares = {}
    header_pat = re.compile(r"^\|\s*Ticker\s*\|", re.IGNORECASE)
    # 예: | VOO | Vanguard S&P 500 ETF | 175.157486주 | ...
    row_pat    = re.compile(r"^\|\s*([A-Z0-9]{1,10})\s*\|")
    shares_pat = re.compile(r"([\d,]+\.?\d*)주")   # "175.157486주" 또는 "1,000주"

    try:
        with open(path, "r", encoding="utf-8") as f:
            in_table = False
            for line in f:
                line = line.rstrip()
                if header_pat.match(line):
                    in_table = True
                    continue
                if in_table:
                    if not line.startswith("|"):
                        in_table = False
                        continue
                    m = row_pat.match(line)
                    if m and m.group(1) not in ("---", "Ticker"):
                        sym = m.group(1).strip()
                        if sym not in tickers:
                            tickers.append(sym)
                        # 보유주수 파싱
                        sm = shares_pat.search(line)
                        if sm:
                            shares[sym] = float(sm.group(1).replace(",", ""))
    except FileNotFoundError:
        print(f"⚠️  portfolio.md를 찾을 수 없습니다: {path}")
    return tickers, shares


def parse_ticker_file(path: str) -> list[str]:
    """텍스트 파일에서 종목 읽기 (줄당 하나, # 주석 무시)"""
    tickers = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                sym = line.strip().split("#")[0].strip().upper()
                if sym and sym not in tickers:
                    tickers.append(sym)
    except FileNotFoundError:
        print(f"❌ 파일 없음: {path}")
        sys.exit(1)
    return tickers


# ── 메인 ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="fetch_market_data.py",
        description="AI Trading Assistant — yfinance 기술지표 수집기",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python fetch_market_data.py                           # portfolio.md 자동 읽기
  python fetch_market_data.py AAPL TSLA NVDA            # 직접 종목 입력
  python fetch_market_data.py --file tickers.txt        # 파일에서 읽기
  python fetch_market_data.py --add PLTR --add SOXX     # portfolio.md + 추가 종목
  python fetch_market_data.py --portfolio ../port.md    # portfolio.md 경로 지정
  python fetch_market_data.py --output data.json        # 출력 경로 지정
        """,
    )
    parser.add_argument(
        "tickers", nargs="*",
        help="종목 코드 직접 입력 (예: AAPL TSLA NVDA). 입력 시 portfolio.md는 무시됩니다."
    )
    parser.add_argument(
        "--file", "-f", metavar="FILE",
        help="종목 코드가 담긴 텍스트 파일 경로 (한 줄에 하나, # 주석 가능)"
    )
    parser.add_argument(
        "--add", "-a", action="append", default=[], metavar="TICKER",
        help="portfolio.md 종목에 추가할 종목 (여러 번 사용 가능)"
    )
    # 기본 portfolio.md 경로 = 스크립트 파일과 같은 폴더
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _default_portfolio = os.path.join(_script_dir, "portfolio.md")

    parser.add_argument(
        "--portfolio", "-p", default=_default_portfolio,
        help=f"portfolio.md 파일 경로 (기본: {_default_portfolio})"
    )
    parser.add_argument(
        "--output", "-o", metavar="FILE",
        help="출력 JSON 파일 경로 (기본: screenshots/market_data_YYYY-MM-DD.json)"
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="진행 메시지 숨기기"
    )
    args = parser.parse_args()

    # ── 종목 목록 결정 ──
    portfolio_shares = {}   # {ticker: shares} — portfolio.md 소스일 때만 채워짐
    if args.tickers:
        tickers = [t.upper() for t in args.tickers]
        source = "직접 입력"
    elif args.file:
        tickers = parse_ticker_file(args.file)
        source = f"파일 ({args.file})"
    else:
        tickers, portfolio_shares = parse_portfolio_md(args.portfolio)
        if not tickers:
            print(f"\n❌ portfolio.md ({args.portfolio})에서 종목을 찾지 못했습니다.")
            print("   직접 입력: python fetch_market_data.py AAPL TSLA NVDA")
            sys.exit(1)
        source = f"portfolio.md ({args.portfolio})"

    # 추가 종목 병합 (--add 옵션)
    for t in args.add:
        if t.upper() not in tickers:
            tickers.append(t.upper())

    if not args.quiet:
        print(f"\n{'━'*60}")
        print(f"  AI Trading Assistant — 기술지표 수집기")
        print(f"{'━'*60}")
        print(f"  종목 출처: {source}")
        print(f"  수집 대상: {len(tickers)}개  →  {', '.join(tickers)}")
        print(f"{'━'*60}")

    # ── 매크로 수집 (항상 자동) ──
    if not args.quiet:
        print(f"  📡 매크로 수집 중 (VIX / 30Y 금리 / USD/KRW) ... ", end="", flush=True)
    macro_data = fetch_macro()
    if not args.quiet:
        vix_str = f"{macro_data.get('VIX', 'N/A')}"
        y30_str = f"{macro_data.get('yield_30Y', 'N/A')}%"
        krw_str = f"₩{macro_data.get('USD_KRW', 'N/A'):.0f}" if macro_data.get('USD_KRW') else "N/A"
        print(f"✅  VIX={vix_str}  30Y={y30_str}  USD/KRW={krw_str}")

    # ── 데이터 수집 ──
    results = {}
    success, fail = 0, 0

    for i, sym in enumerate(tickers, 1):
        # 한국 종목 (숫자만): yfinance에 .KS/.KQ 접미사 필요
        from portfolio_data import to_yfinance_symbol
        yf_sym = to_yfinance_symbol(sym)
        display_sym = sym  # 결과 키는 원래 심볼 유지

        if not args.quiet:
            print(f"  [{i:2d}/{len(tickers)}] {display_sym:<6} ... ", end="", flush=True)

        data = fetch_ticker(yf_sym)
        results[display_sym] = data

        if "error" in data:
            fail += 1
            if not args.quiet:
                print(f"❌  {data['error']}")
        else:
            success += 1
            if not args.quiet:
                trend_icon = "📈" if "increasing" in data["macd_hist_trend"] else ("📉" if "decreasing" in data["macd_hist_trend"] else "➡️")
                print(
                    f"✅  가격={data['price']:>8.2f}  "
                    f"RSI={str(data['rsi14']):>5}  "
                    f"MACD_hist={str(data['macd_hist']):>8}  "
                    f"추세={trend_icon}{data['macd_hist_trend']}"
                )

    # ── 거래일 판별 ──
    today = date.today().strftime("%Y-%m-%d")
    last_trading_date = today
    for _sym in ("SPY", "QQQ"):
        if _sym in results and "error" not in results[_sym]:
            _ltd = results[_sym].get("_last_date")
            if _ltd:
                last_trading_date = _ltd
                break
    is_trading_day = (last_trading_date == today)
    data_date = last_trading_date if not is_trading_day else today

    # ── 저장 ──
    if args.output:
        output_path = args.output
    else:
        _script_dir = os.path.dirname(os.path.abspath(__file__))
        output_path = os.path.join(_script_dir, "screenshots", f"market_data_{data_date}.json")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Master switch 계산 (QQQ, SPY 데이터가 있을 때만)
    master = "UNKNOWN"
    if "QQQ" in results and "error" not in results["QQQ"] and "SPY" in results and "error" not in results["SPY"]:
        qqq_below = results["QQQ"].get("price_vs_ma200") == "below"
        spy_below = results["SPY"].get("price_vs_ma200") == "below"
        if qqq_below and spy_below:
            master = "RED"
        elif qqq_below or spy_below:
            master = "YELLOW"
        else:
            master = "GREEN"
    macro_data["master_switch"] = master

    # ── 포트폴리오 배당 집계 (_dividends) ──────────────────
    # portfolio.md 소스이고 보유주수 데이터가 있을 때만 계산
    # KOSPI 배당금(KRW)은 USD로 변환하여 합산
    dividends_summary = {}
    krw_rate = macro_data.get("USD_KRW", 0) or 1
    if portfolio_shares:
        total_annual = 0.0
        total_port_value = 0.0
        per_ticker = {}
        for sym, sh in portfolio_shares.items():
            if sym in results and "error" not in results[sym]:
                d = results[sym]
                div_ttm    = d.get("div_ttm", 0.0) or 0.0
                cur_price  = d.get("price", 0.0) or 0.0
                annual_inc = round(div_ttm * sh, 2)
                port_val   = round(cur_price * sh, 2)
                # KOSPI 종목(6자리 숫자): KRW → USD 변환
                is_kospi = sym.isdigit() and len(sym) == 6
                if is_kospi and krw_rate > 1:
                    annual_inc = round(annual_inc / krw_rate, 2)
                    port_val   = round(port_val / krw_rate, 2)
                per_ticker[sym] = {
                    "shares":       sh,
                    "div_per_sh":   div_ttm,
                    "div_yield":    d.get("div_yield_ttm", 0.0),
                    "annual_income": annual_inc,
                }
                total_annual     += annual_inc
                total_port_value += port_val

        port_yield = round(total_annual / total_port_value * 100, 4) if total_port_value > 0 else 0.0
        dividends_summary = {
            "total_annual":   round(total_annual, 2),
            "monthly_avg":    round(total_annual / 12, 2),
            "portfolio_yield": port_yield,
            "per_ticker":     per_ticker,
            "note":           "TTM(최근 12개월) 배당 합산. yfinance dividend history 기준.",
        }
        if not args.quiet:
            print(f"\n  💰 배당 집계: 연 ${total_annual:,.0f}  |  월 ${total_annual/12:,.0f}  |  수익률 {port_yield:.2f}%")

    mkt_status = get_market_status()
    payload = {
        "_meta": {
            "date": data_date,
            "run_date": today,
            "is_trading_day": is_trading_day,
            "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
            "source": "yfinance",
            "ticker_source": source,
            "tickers": tickers,
            "success": success,
            "fail": fail,
            "market_status": mkt_status,
        },
        "_macro": macro_data,
        "_dividends": dividends_summary,  # 포트폴리오 배당 집계 (portfolio.md 소스일 때)
        "data": results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    if not args.quiet:
        print(f"\n{'━'*60}")
        if not is_trading_day:
            print(f"  ⚠️  비거래일 (오늘: {today}) → 직전 거래일({data_date}) 데이터 사용")
        print(f"  ✅ 저장 완료  →  {output_path}")
        print(f"  종목 수집: 성공 {success}개  |  실패 {fail}개")
        print(f"  매크로: VIX={macro_data.get('VIX','N/A')}  "
              f"30Y={macro_data.get('yield_30Y','N/A')}%  "
              f"USD/KRW={macro_data.get('USD_KRW','N/A'):.0f}  "
              f"Master={macro_data.get('master_switch','N/A')}")
        if dividends_summary:
            print(f"  배당 집계: 연 ${dividends_summary['total_annual']:,.0f}  "
                  f"|  월 ${dividends_summary['monthly_avg']:,.0f}  "
                  f"|  수익률 {dividends_summary['portfolio_yield']:.2f}%")
        print(f"{'━'*60}\n")


if __name__ == "__main__":
    main()
