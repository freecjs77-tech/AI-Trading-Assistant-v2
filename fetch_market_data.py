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
  ★ 배당 (연간 예상): div_ttm (연간 배당/주), div_yield_ttm (배당수익률%)
    ※ 필드명은 과거 호환을 위해 유지하되, 값은 yfinance.dividendRate(forward)을 우선 사용.
      Forward 없으면 ticker.dividends 최근 12개월 합산(TTM)로 폴백.
      세금/연간 예상 수입 계산 용도로 forward가 더 정확함.
    - div_source: "forward" | "ttm" | "none" — 실제 사용된 소스 표시

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
import time
import argparse
from datetime import datetime, date, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

KST = timezone(timedelta(hours=9))
EST = timezone(timedelta(hours=-5))   # 미국 동부 표준시 (보수적 기준)

# ── yfinance 재시도 래퍼 ───────────────────────────────
# 429(Rate Limited) / 503 / 네트워크 간헐 오류 시 exponential backoff

_RETRY_DELAYS = (1, 3, 9)  # 초 — 최대 3회 재시도


def _download_with_retry(call_fn, label: str = "yf_call", quiet: bool = False):
    """yfinance 호출을 backoff 재시도로 감쌈.

    call_fn: 인자 없는 callable. 내부에서 yf.download / yf.Ticker.history 등을 실행.
    label: 로그에 쓸 식별자.
    성공하면 호출 결과를 반환, 모든 재시도 실패 시 마지막 예외를 raise.
    """
    last_exc = None
    for attempt, delay in enumerate([0] + list(_RETRY_DELAYS)):
        if delay > 0:
            if not quiet:
                print(f"    ⏳ {label} 재시도 대기 {delay}s (시도 {attempt}/{len(_RETRY_DELAYS)})")
            time.sleep(delay)
        try:
            return call_fn()
        except Exception as e:  # yfinance는 429 시 일반 Exception으로 래핑
            last_exc = e
            msg = str(e).lower()
            # 명백히 영구 오류면 재시도 포기
            if "no data" in msg or "delisted" in msg or "symbol may be delisted" in msg:
                raise
    if last_exc is not None:
        raise last_exc
    return None


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

from lifecycle_config import (
    EMA_FAST, EMA_MEDIUM, EMA_LONG,
    EMA_LONG_SLOPE_WINDOW, EMA_MEDIUM_SLOPE_WINDOW,
)


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


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range (ATR) — Wilder smoothing (EWM with com=period-1).

    True Range = max(H-L, |H-Cprev|, |L-Cprev|)
    """
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()


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


def _compute_returns(close: pd.Series) -> dict:
    """
    종가 시리즈에서 N일 누적 수익률 계산. NaN/Zero 방어.

    Returns:
        {"change_5d_pct": float|None, "change_20d_pct": float|None}
    """
    out = {"change_5d_pct": None, "change_20d_pct": None}
    if close is None or len(close) == 0:
        return out
    last = float(close.iloc[-1])
    if pd.isna(last):
        return out

    def _ret(periods: int):
        if len(close) < periods + 1:
            return None
        denom = close.iloc[-(periods + 1)]
        if pd.isna(denom) or float(denom) == 0:
            return None
        return round((last / float(denom) - 1) * 100, 2)

    out["change_5d_pct"] = _ret(5)
    out["change_20d_pct"] = _ret(20)
    return out


# ── 매크로 지표 수집 ─────────────────────────────────

def fetch_macro() -> dict:
    """
    VIX, 30Y 국채 금리, USD/KRW 환율을 yfinance로 수집 (병렬 처리 + 재시도).
    항상 자동 실행됨 (별도 옵션 불필요).
    """
    macro: dict = {}
    targets = {
        "VIX":      "^VIX",
        "yield_30Y":"^TYX",   # 30Y Treasury yield (값 그대로 %, 예: 4.97)
        "USD_KRW":  "USDKRW=X",
    }

    def _fetch_one(key: str, symbol: str):
        try:
            df = _download_with_retry(
                lambda: yf.Ticker(symbol).history(period="5d", interval="1d", auto_adjust=True),
                label=f"macro:{key}",
                quiet=True,
            )
            if df is not None and not df.empty:
                df = df[df["Close"].notna()]
            if df is not None and not df.empty:
                return key, round(float(df["Close"].iloc[-1]), 4)
        except Exception:
            pass
        return key, None

    # 3개 매크로를 병렬로 수집 (직렬 ~6초 → 병렬 ~2초)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_fetch_one, k, s) for k, s in targets.items()]
        for fut in as_completed(futures):
            k, v = fut.result()
            macro[k] = v

    macro["fetched_at"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    return macro


# ── 단일 종목 수집 ───────────────────────────────────

def _ttm_sum_from_divs(cached_divs) -> float:
    """cached_divs(pd.Series)에서 최근 12개월 합산 배당금/주 반환. 실패/없음 시 0.0."""
    if cached_divs is None or len(cached_divs) == 0:
        return 0.0
    try:
        idx = cached_divs.index.tz_localize(None) if getattr(cached_divs.index, "tzinfo", None) else cached_divs.index
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=1)
        ttm = cached_divs[idx >= cutoff]
        return round(float(ttm.sum()), 4) if len(ttm) > 0 else 0.0
    except Exception:
        return 0.0


def _fetch_forward_dividend_rate(yf_sym: str, quiet: bool = True) -> float | None:
    """yfinance ticker.info.dividendRate(forward 연배당/주) 조회.

    None 반환 시 호출측이 TTM 폴백해야 함.
    rate limit을 고려해 _download_with_retry로 감싸고, 예외는 삼켜 None 반환.
    """
    try:
        def _call():
            tk = yf.Ticker(yf_sym)
            info = tk.info or {}
            rate = info.get("dividendRate")
            return float(rate) if rate else None
        return _download_with_retry(_call, label=f"info[{yf_sym}]", quiet=quiet)
    except Exception:
        return None


# 과거 호환 shim — 다른 모듈에서 import할 수 있으므로 alias 유지
def fetch_div_ttm(ticker: "yf.Ticker", current_price: float) -> tuple[float, float]:
    """(deprecated) ticker.dividends TTM 합산 + info 폴백. 신 코드는 _ttm_sum_from_divs 사용 권장."""
    try:
        divs = ticker.dividends
        div_ttm = _ttm_sum_from_divs(divs)
        if div_ttm > 0:
            div_yield = round(div_ttm / current_price * 100, 4) if current_price > 0 else 0.0
            return div_ttm, div_yield
    except Exception:
        pass
    try:
        info = ticker.info or {}
        div_ttm = info.get("dividendRate") or info.get("trailingAnnualDividendRate") or 0.0
        if div_ttm and div_ttm > 0:
            div_yield = round(float(div_ttm) / current_price * 100, 4) if current_price > 0 else 0.0
            return round(float(div_ttm), 4), div_yield
    except Exception:
        pass
    return 0.0, 0.0


def compute_indicators(df: pd.DataFrame, forward_div=None, cached_divs=None) -> dict:
    """Compute all technical indicators from a yfinance-shaped DataFrame.

    df must have columns: Open, High, Low, Close, Volume (yfinance Ticker.history shape).
    Returns the same dict that fetch_ticker returned previously, plus the new
    Phase A EMA fields (ema9/ema21/ema65/ema21_slope_5d/ema65_slope_5d).
    """
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
    atr14_series = calc_atr(high, low, close, period=14)
    atr14_val = (
        float(atr14_series.iloc[-1])
        if len(atr14_series) > 0
        and not pd.isna(atr14_series.iloc[-1])
        and np.isfinite(atr14_series.iloc[-1])
        else None
    )

    # ── Phase A: lifecycle EMAs ──
    # EMA9/21/65 + 5-day slopes (used by lifecycle_signal state machine).
    ema9_series  = close.ewm(span=EMA_FAST,   adjust=False).mean()
    ema21_series = close.ewm(span=EMA_MEDIUM, adjust=False).mean()
    ema65_series = close.ewm(span=EMA_LONG,   adjust=False).mean()

    def _slope(series, window: int):
        if len(series) <= window:
            return None
        cur = series.iloc[-1]
        prev = series.iloc[-1 - window]
        if pd.isna(cur) or pd.isna(prev) or not np.isfinite(cur) or not np.isfinite(prev):
            return None
        return round(float(cur - prev), 6)

    ema21_slope = _slope(ema21_series, EMA_MEDIUM_SLOPE_WINDOW)
    ema65_slope = _slope(ema65_series, EMA_LONG_SLOPE_WINDOW)

    # ── Momentum v1.5: dist (%) + 3-day slope (%) via shared helper ──
    # momentum_signal.classify_em / classify_maturity consume these fields.
    from momentum_data import compute_ema_fields
    ema_fields = compute_ema_fields(close)

    last_close  = float(close.iloc[-1])
    recent_high = float(close.iloc[-20:].max())
    # high_20d_prior — rolling 20-day high EXCLUDING today's bar.
    # Used by score_v1 'breakout' component to avoid self-reference contamination.
    if len(high) >= 21:
        high_20d_prior = float(high.iloc[-21:-1].max())
    else:
        high_20d_prior = None
    drawdown    = (last_close - recent_high) / recent_high * 100
    high_52w    = float(close.max())  # 전체 기간(~1년) 최고점
    low_52w     = float(close.min())  # 전체 기간(~1년) 최저점
    drawdown_52w = (last_close - high_52w) / high_52w * 100

    # 이중 바닥 패턴 탐지
    dbl_bottom = find_double_bottom(close)

    # 시가총액은 현재 사용되지 않으므로 제거 (ticker.info 호출 회피 — rate limit)
    market_cap = 0

    # 배당 수집 — forward(yfinance.dividendRate) 우선, TTM 합산 폴백
    # 세금/연간 예상 수입 계산에는 forward가 더 정확 (특별배당·분기 신설 반영)
    # forward_div는 main()에서 사전에 yf.Ticker.info로 조회해 전달 (배당 이력 있는 종목만)
    ttm_actual = _ttm_sum_from_divs(cached_divs)
    if forward_div is not None and forward_div > 0:
        div_annual = round(float(forward_div), 4)
        div_source = "forward"
    elif ttm_actual > 0:
        div_annual = ttm_actual
        div_source = "ttm"
    else:
        div_annual = 0.0
        div_source = "none"
    div_yield_annual = round(div_annual / last_close * 100, 4) if (div_annual > 0 and last_close > 0) else 0.0

    # 구 필드명 유지 (pipeline.py, report_generator.py 등 다운스트림 호환)
    div_ttm = div_annual
    div_yield_ttm = div_yield_annual

    def safe(series, idx=-1):
        v = series.iloc[idx]
        return round(float(v), 4) if not (pd.isna(v) or np.isinf(v)) else None

    hist_vals = [round(float(x), 4) for x in hist.dropna().iloc[-3:].tolist()]

    return {
        "price":             round(last_close, 2),
        "open":              round(float(df["Open"].iloc[-1]), 2),  # NEW — for lower_wick + intraday_reversal score components
        "prev_close":        round(float(close.iloc[-2]), 2) if len(close) >= 2 else None,
        "change_pct":        round((last_close / float(close.iloc[-2]) - 1) * 100, 2) if len(close) >= 2 else None,
        "change_3d_pct":     round((last_close / float(close.iloc[-4]) - 1) * 100, 2) if len(close) >= 4 else None,
        **_compute_returns(close),     # change_5d_pct + change_20d_pct
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
        # ATR — trailing stop 시스템에서 사용
        "atr14":     round(atr14_val, 4) if atr14_val is not None else None,
        "atr14_pct": round((atr14_val / last_close) * 100, 2)
                     if atr14_val is not None and last_close > 0
                     else None,
        # 거래량
        "volume":            int(volume.iloc[-1]),
        "volume_ma20":       int(vol_ma20.iloc[-1]) if safe(vol_ma20) else None,
        "volume_ratio":      round(float(volume.iloc[-1]) / float(vol_ma20.iloc[-1]), 2) if safe(vol_ma20) else None,
        # 기타
        "drawdown_20d_pct":  round(drawdown, 2),
        "drawdown_52w_pct":  round(drawdown_52w, 2),
        "high_52w":          round(high_52w, 2),
        "low_52w":           round(low_52w, 2),
        "high_20d_prior":    round(high_20d_prior, 2) if high_20d_prior is not None else None,  # NEW
        "market_cap":        market_cap,
        "data_days":         len(df),
        "fetched_at":        datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        # 하락 멈춤: 오늘 종가 >= 최근 3일 최저 종가 (저점 갱신 없음)
        "sig_low_stopped":   bool(len(close) >= 4 and float(close.iloc[-1]) >= min(float(p) for p in close.iloc[-4:-1])),
        # 이중 바닥 패턴
        "double_bottom":     dbl_bottom,
        # 배당 (연간 예상 — forward 우선, TTM 폴백)
        "div_ttm":           div_ttm,       # 연간 배당/주 (forward 우선값 — 필드명은 호환용)
        "div_yield_ttm":     div_yield_ttm, # 배당수익률 (%)
        "div_annual":        div_annual,    # div_ttm의 명시적 alias (forward 의미)
        "div_yield_annual":  div_yield_annual,
        "div_source":        div_source,    # "forward" | "ttm" | "none"
        "_last_date":        df.index[-1].strftime("%Y-%m-%d"),  # 마지막 거래일
        # Phase A: lifecycle EMAs (raw values, 5-day slopes)
        "ema9":              safe(ema9_series),
        "ema21":             safe(ema21_series),
        "ema65":             safe(ema65_series),
        "ema21_slope_5d":    ema21_slope,
        "ema65_slope_5d":    ema65_slope,
        # Momentum v1.5: dist (%) + 3-day slope (%) for EM/Maturity gates
        "dist_ema9_pct":      ema_fields["dist_ema9_pct"],
        "dist_ema21_pct":     ema_fields["dist_ema21_pct"],
        "ema21_slope_3d_pct": ema_fields["ema21_slope_3d_pct"],
        "ema65_slope_5d_pct": ema_fields["ema65_slope_5d_pct"],
    }


def fetch_ticker(symbol: str, cached_df=None, cached_divs=None, forward_div=None) -> dict:
    """yfinance로 종목 데이터 수집 후 기술지표 계산 (배당 포함).

    cached_df/cached_divs가 주어지면 네트워크 호출 없이 재사용 (레이트리밋 회피).
    forward_div: yfinance.info.dividendRate 값(연간 예상 배당/주). main()에서 사전 조회해 전달.
                 None이면 cached_divs TTM 합산으로 폴백."""
    try:
        if cached_df is not None:
            df = cached_df
        else:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1y", interval="1d", auto_adjust=True)

        if df is None or df.empty:
            return {"error": "데이터 없음 (상장폐지 또는 심볼 오류)"}

        # KOSPI(.KS/.KQ) 종목에서 yfinance가 같은 날 중복 인덱스를 반환하는
        # 케이스 방어 — 후속 reindex/groupby 연산에서 'cannot reindex on an axis
        # with duplicate labels' 에러를 일으킨다. 마지막 값을 신뢰값으로 채택.
        if df.index.has_duplicates:
            df = df[~df.index.duplicated(keep="last")]

        # 장 시작 전 auto_adjust가 NaN 행을 생성하는 문제 방지
        df = df[df["Close"].notna()]

        if len(df) < 26:
            return {"error": f"데이터 부족 ({len(df)}일, 최소 26일 필요)"}

        return compute_indicators(df, forward_div=forward_div, cached_divs=cached_divs)

    except Exception as e:
        # 진단성 강화 — 동일 에러 재발 시 워크플로우 로그에서 traceback 확인 가능
        import traceback
        print(f"  [fetch_ticker {symbol}] exception: {type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
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
    # 기본 portfolio 경로 = portfolios/me.md (없으면 레거시 portfolio.md로 폴백)
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    from portfolio_paths import primary_portfolio_path
    _default_portfolio = primary_portfolio_path(_script_dir)

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

    # ── 청크 단위 일괄 다운로드 (레이트리밋 회피: 종목당 3번→0번 HTTP 호출) ──
    from portfolio_data import to_yfinance_symbol
    yf_symbols = [to_yfinance_symbol(s) for s in tickers]
    bulk_df = None
    bulk_divs: dict = {}
    CHUNK = 20
    chunk_frames = []
    try:
        if not args.quiet:
            print(f"  📦 청크 다운로드 시작: {len(yf_symbols)}종목을 {CHUNK}개씩 분할")
        for ci in range(0, len(yf_symbols), CHUNK):
            chunk = yf_symbols[ci:ci + CHUNK]
            if not args.quiet:
                print(f"    [청크 {ci // CHUNK + 1}/{(len(yf_symbols) + CHUNK - 1) // CHUNK}] {len(chunk)}종목 ... ", end="", flush=True)
            try:
                cdf = _download_with_retry(
                    lambda _chunk=chunk: yf.download(
                        tickers=_chunk,
                        period="1y",
                        interval="1d",
                        auto_adjust=True,
                        actions=True,
                        group_by="ticker",
                        progress=False,
                        threads=False,  # 직렬 (레이트리밋 안정)
                    ),
                    label=f"chunk[{ci // CHUNK + 1}]",
                    quiet=args.quiet,
                )
                chunk_frames.append(cdf)
                if not args.quiet:
                    print(f"✅")
            except Exception as _ce:
                if not args.quiet:
                    print(f"⚠️ {type(_ce).__name__}")
        if chunk_frames:
            try:
                bulk_df = pd.concat(chunk_frames, axis=1)
            except Exception:
                bulk_df = chunk_frames[0]
        # 배당 시계열 분리 추출 (actions=True 덕분에 Dividends 컬럼 존재)
        if bulk_df is not None and not bulk_df.empty:
            for yf_sym in yf_symbols:
                try:
                    if isinstance(bulk_df.columns, pd.MultiIndex):
                        if yf_sym not in bulk_df.columns.get_level_values(0):
                            continue
                        sub = bulk_df[yf_sym]
                    else:
                        sub = bulk_df
                    if "Dividends" in sub.columns:
                        divs = sub["Dividends"].dropna()
                        bulk_divs[yf_sym] = divs[divs > 0]
                except Exception:
                    pass
    except Exception as _bulk_e:
        if not args.quiet:
            print(f"⚠️  일괄 다운로드 실패 ({_bulk_e}) — 종목별 폴백 사용")
        bulk_df = None

    # ── Forward 배당률 사전 조회 ──
    # yfinance.info.dividendRate는 forward(예상 연배당) — 세금/수입 예상에 정확
    # 후보: ①보유종목(portfolio_shares) 전체 + ②최근 1년 배당이력 있는 종목
    #   ─ ①은 세금 계산 정확도를 위해 TTM=0이어도 필수 (예: 006400 최근 미지급이지만 forward 977원 예측)
    #   ─ ②는 스캐너/와치리스트에서 배당 있는 것만 (스캐너 비배당주는 호출 스킵)
    forward_divs: dict[str, float] = {}
    owned_yf = set()
    if portfolio_shares:
        for _sym in portfolio_shares.keys():
            try:
                owned_yf.add(to_yfinance_symbol(_sym))
            except Exception:
                pass
    with_div_hist = {s for s in yf_symbols if bulk_divs.get(s) is not None and len(bulk_divs.get(s, [])) > 0}
    candidate_syms = [s for s in yf_symbols if s in owned_yf or s in with_div_hist]
    if candidate_syms:
        if not args.quiet:
            print(f"  💵 Forward 배당률 조회: 배당이력 있는 {len(candidate_syms)}종목 (info.dividendRate)")
        ok_cnt, fb_cnt = 0, 0
        for yf_sym in candidate_syms:
            fwd = _fetch_forward_dividend_rate(yf_sym, quiet=True)
            if fwd is not None and fwd > 0:
                forward_divs[yf_sym] = fwd
                ok_cnt += 1
            else:
                fb_cnt += 1
            time.sleep(0.2)  # rate limit 완화 (배치성이지만 info는 중량 엔드포인트)
        if not args.quiet:
            print(f"     forward {ok_cnt}건 / TTM 폴백 {fb_cnt}건")

    # ── 데이터 수집 (캐시 우선, 폴백 시 종목별 네트워크 호출) ──
    results = {}
    success, fail = 0, 0

    for i, sym in enumerate(tickers, 1):
        yf_sym = to_yfinance_symbol(sym)
        display_sym = sym  # 결과 키는 원래 심볼 유지

        if not args.quiet:
            print(f"  [{i:2d}/{len(tickers)}] {display_sym:<6} ... ", end="", flush=True)

        # 캐시에서 OHLCV 추출
        cached_df = None
        cached_divs = None
        if bulk_df is not None and not bulk_df.empty:
            try:
                if isinstance(bulk_df.columns, pd.MultiIndex):
                    if yf_sym in bulk_df.columns.get_level_values(0):
                        cached_df = bulk_df[yf_sym][["Open","High","Low","Close","Volume"]].dropna(how="all")
                else:
                    cached_df = bulk_df[["Open","High","Low","Close","Volume"]].dropna(how="all")
                # bulk concat에서 동일 인덱스가 중복으로 들어오는 KOSPI 케이스 방어
                if cached_df is not None and getattr(cached_df.index, "has_duplicates", False):
                    cached_df = cached_df[~cached_df.index.duplicated(keep="last")]
                cached_divs = bulk_divs.get(yf_sym)
                if cached_divs is not None and getattr(cached_divs.index, "has_duplicates", False):
                    cached_divs = cached_divs[~cached_divs.index.duplicated(keep="last")]
            except Exception:
                cached_df = None

        data = fetch_ticker(
            yf_sym,
            cached_df=cached_df,
            cached_divs=cached_divs,
            forward_div=forward_divs.get(yf_sym),
        )
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

    # ── 전체 실패 가드: 네트워크 실패로 모든 티커가 에러면 기존 파일 보존 ──
    if success == 0 and fail > 0:
        import glob as _glob
        _existing = sorted(_glob.glob(os.path.join(os.path.dirname(output_path) or ".", "market_data_*.json")))
        if _existing:
            print(f"\n⚠️  네트워크 장애로 전 종목 실패 — 기존 파일 유지: {_existing[-1]}")
            print(f"    (새 파일 저장 생략, 파이프라인은 기존 데이터로 계속)")
            return

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
                from portfolio_data import is_korean_ticker as _is_kr
                is_kospi = _is_kr(sym)
                if is_kospi and krw_rate > 1:
                    annual_inc = round(annual_inc / krw_rate, 2)
                    port_val   = round(port_val / krw_rate, 2)
                per_ticker[sym] = {
                    "shares":       sh,
                    "div_per_sh":   div_ttm,
                    "div_yield":    d.get("div_yield_ttm", 0.0),
                    "annual_income": annual_inc,
                    "div_source":   d.get("div_source", "none"),
                }
                total_annual     += annual_inc
                total_port_value += port_val

        port_yield = round(total_annual / total_port_value * 100, 4) if total_port_value > 0 else 0.0
        dividends_summary = {
            "total_annual":   round(total_annual, 2),
            "monthly_avg":    round(total_annual / 12, 2),
            "portfolio_yield": port_yield,
            "per_ticker":     per_ticker,
            "note":           "연간 예상 배당 (forward 우선). yfinance.info.dividendRate 있으면 사용, 없으면 최근 12개월 실배당(TTM) 합산으로 폴백. 세금/예상 수입 계산 용도.",
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
        _usd_krw = macro_data.get('USD_KRW')
        _usd_krw_str = f"{_usd_krw:.0f}" if isinstance(_usd_krw, (int, float)) else "N/A"
        print(f"  매크로: VIX={macro_data.get('VIX','N/A')}  "
              f"30Y={macro_data.get('yield_30Y','N/A')}%  "
              f"USD/KRW={_usd_krw_str}  "
              f"Master={macro_data.get('master_switch','N/A')}")
        if dividends_summary:
            print(f"  배당 집계: 연 ${dividends_summary['total_annual']:,.0f}  "
                  f"|  월 ${dividends_summary['monthly_avg']:,.0f}  "
                  f"|  수익률 {dividends_summary['portfolio_yield']:.2f}%")
        print(f"{'━'*60}\n")


if __name__ == "__main__":
    main()
