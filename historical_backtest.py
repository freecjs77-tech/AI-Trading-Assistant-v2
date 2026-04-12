"""
historical_backtest.py — 1년 과거 데이터 기반 시그널 백테스트 + 파라미터 최적화

Usage:
    python historical_backtest.py                 # baseline 백테스트
    python historical_backtest.py --grid-search   # 파라미터 탐색 포함
    python historical_backtest.py --no-cache      # 캐시 무시 재다운로드
    python historical_backtest.py --period 2y     # 기간 변경
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
import pickle
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

# Windows encoding fix
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Import existing modules ──
from fetch_market_data import calc_rsi, calc_macd, calc_bollinger, calc_adx, find_double_bottom
from market_scanner import SP100_TICKERS
import signal_judge

CACHE_DIR = os.path.join(PROJECT_DIR, "cache")
HISTORY_DIR = os.path.join(PROJECT_DIR, "history")


# ═══════════════════════════════════════════════════════════
# Phase 1: Data Download & Cache
# ═══════════════════════════════════════════════════════════

def download_data(tickers: list[str], period: str = "2y",
                  cache_dir: str = CACHE_DIR, no_cache: bool = False) -> dict[str, pd.DataFrame]:
    """Download OHLCV data for all tickers. Cache as pickle."""
    os.makedirs(cache_dir, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    cache_path = os.path.join(cache_dir, f"hist_sp100_{today}.pkl")

    if not no_cache and os.path.exists(cache_path):
        print(f"  Loading cached data: {cache_path}")
        with open(cache_path, "rb") as f:
            return pickle.load(f)

    print(f"  Downloading {len(tickers)} tickers individually ({period})...")
    result = {}
    failed = []

    for i, ticker in enumerate(tickers):
        if (i + 1) % 10 == 0 or i == 0:
            print(f"  [{i + 1}/{len(tickers)}] ", end="", flush=True)

        for attempt in range(3):
            try:
                t = yf.Ticker(ticker)
                df = t.history(period=period, interval="1d", auto_adjust=True)
                if df is not None and not df.empty and len(df) >= 50:
                    df = df[df["Close"].notna()]
                    result[ticker] = df
                    print(".", end="", flush=True)
                    break
                else:
                    if attempt < 2:
                        time.sleep(5)
                    else:
                        failed.append(ticker)
                        print("x", end="", flush=True)
            except Exception:
                if attempt < 2:
                    time.sleep(10)
                else:
                    failed.append(ticker)
                    print("x", end="", flush=True)

        # Rate limit prevention
        if (i + 1) % 5 == 0:
            time.sleep(1)

        if (i + 1) % 10 == 0:
            print(f" ({len(result)} loaded)")

    # VIX
    try:
        vix = yf.Ticker("^VIX").history(period=period, interval="1d", auto_adjust=True)
        if vix is not None and not vix.empty:
            result["^VIX"] = vix
    except Exception:
        pass

    print(f"\n  Total: {len(result) - (1 if '^VIX' in result else 0)} tickers loaded")
    if failed:
        print(f"  Failed ({len(failed)}): {', '.join(failed[:10])}{'...' if len(failed) > 10 else ''}")

    with open(cache_path, "wb") as f:
        pickle.dump(result, f)
    print(f"  Cached: {cache_path}")

    return result


# ═══════════════════════════════════════════════════════════
# Phase 2: Build Technical Indicators (Vectorized)
# ═══════════════════════════════════════════════════════════

def build_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Pre-compute all technical indicators as DataFrame columns."""
    ind = df.copy()
    close = ind["Close"]
    high = ind["High"]
    low = ind["Low"]
    vol = ind["Volume"]

    # Moving Averages
    ind["ma20"] = close.rolling(20).mean()
    ind["ma50"] = close.rolling(50).mean()
    ind["ma200"] = close.rolling(200).mean()

    # RSI
    ind["rsi14"] = calc_rsi(close, 14)

    # MACD
    macd_line, sig_line, hist = calc_macd(close)
    ind["macd"] = macd_line
    ind["macd_signal"] = sig_line
    ind["macd_hist"] = hist

    # Bollinger Bands
    bb_u, bb_m, bb_l = calc_bollinger(close)
    ind["bb_upper"] = bb_u
    ind["bb_mid"] = bb_m
    ind["bb_lower"] = bb_l

    # ADX
    ind["adx"] = calc_adx(high, low, close)

    # Volume MA20
    ind["volume_ma20"] = vol.rolling(20).mean()

    # Drawdown 20d
    ind["high_20d"] = close.rolling(20).max()
    ind["high_52w"] = close.rolling(252).max()
    ind["low_52w"] = close.rolling(252).min()

    # Change %
    ind["prev_close"] = close.shift(1)
    ind["change_pct"] = (close / ind["prev_close"] - 1) * 100

    # 3-day cumulative change
    ind["change_3d_pct"] = (close / close.shift(3) - 1) * 100

    return ind


def build_day_dict(ind: pd.DataFrame, idx: int) -> dict | None:
    """Convert one row of indicator DataFrame to signal_judge dict format."""
    if idx < 200 or idx >= len(ind):
        return None

    row = ind.iloc[idx]
    close = ind["Close"]
    price = float(row["Close"])

    # Basic checks
    if pd.isna(price) or price <= 0:
        return None
    if pd.isna(row.get("rsi14")) or pd.isna(row.get("ma20")):
        return None

    ma20 = float(row["ma20"])
    ma50 = float(row.get("ma50", 0)) or 0
    ma200 = float(row.get("ma200", 0)) or 0

    # Volume ratio
    vol = float(row["Volume"]) if not pd.isna(row["Volume"]) else 0
    vol_ma20 = float(row["volume_ma20"]) if not pd.isna(row["volume_ma20"]) else 1
    volume_ratio = round(vol / vol_ma20, 2) if vol_ma20 > 0 else 1.0

    # MACD hist 3d
    hist_vals = ind["macd_hist"].iloc[max(0, idx - 2):idx + 1].tolist()
    while len(hist_vals) < 3:
        hist_vals.insert(0, 0.0)
    macd_hist_3d = [round(float(v), 6) if not pd.isna(v) else 0.0 for v in hist_vals]

    # MACD hist trend
    hist_trend = _compute_hist_trend(macd_hist_3d)

    # Drawdowns
    h20 = float(row["high_20d"]) if not pd.isna(row.get("high_20d")) else price
    h52 = float(row["high_52w"]) if not pd.isna(row.get("high_52w")) else price
    l52 = float(row["low_52w"]) if not pd.isna(row.get("low_52w")) else price
    dd_20d = round((price - h20) / h20 * 100, 2) if h20 > 0 else 0
    dd_52w = round((price - h52) / h52 * 100, 2) if h52 > 0 else 0

    # BB%
    bb_u = float(row["bb_upper"]) if not pd.isna(row.get("bb_upper")) else price
    bb_l = float(row["bb_lower"]) if not pd.isna(row.get("bb_lower")) else price
    bb_range = bb_u - bb_l
    bb_pct = round((price - bb_l) / bb_range * 100, 1) if bb_range > 0 else 50.0

    # Double bottom (use last 60 days of close)
    close_window = close.iloc[max(0, idx - 60):idx + 1]
    try:
        db = find_double_bottom(close_window)
    except Exception:
        db = {"detected": False}

    # sig_low_stopped
    if idx >= 3:
        recent_lows = close.iloc[idx - 3:idx].values
        sig_low_stopped = float(close.iloc[idx]) >= min(recent_lows) if len(recent_lows) > 0 else False
    else:
        sig_low_stopped = False

    macd_val = float(row["macd"]) if not pd.isna(row.get("macd")) else 0
    macd_sig = float(row["macd_signal"]) if not pd.isna(row.get("macd_signal")) else 0

    return {
        "price": price,
        "prev_close": float(row["prev_close"]) if not pd.isna(row.get("prev_close")) else price,
        "change_pct": round(float(row["change_pct"]), 2) if not pd.isna(row.get("change_pct")) else 0,
        "change_3d_pct": round(float(row["change_3d_pct"]), 2) if not pd.isna(row.get("change_3d_pct")) else 0,
        "ma20": ma20, "ma50": ma50, "ma200": ma200,
        "price_vs_ma20": "above" if price >= ma20 else "below",
        "price_vs_ma200": "above" if ma200 > 0 and price >= ma200 else "below",
        "rsi14": round(float(row["rsi14"]), 1),
        "macd": macd_val, "macd_signal": macd_sig,
        "macd_hist": round(float(row["macd_hist"]), 6) if not pd.isna(row.get("macd_hist")) else 0,
        "macd_hist_3d": macd_hist_3d,
        "macd_hist_trend": hist_trend,
        "macd_vs_signal": "above" if macd_val > macd_sig else "below",
        "bb_upper": bb_u, "bb_mid": float(row.get("bb_mid", ma20)),
        "bb_lower": bb_l, "bb_pct": bb_pct,
        "adx": round(float(row["adx"]), 1) if not pd.isna(row.get("adx")) else 0,
        "volume": int(vol), "volume_ma20": int(vol_ma20),
        "volume_ratio": volume_ratio,
        "drawdown_20d_pct": dd_20d,
        "drawdown_52w_pct": dd_52w,
        "high_52w": h52, "low_52w": l52,
        "double_bottom": db,
        "sig_low_stopped": sig_low_stopped,
        "data_days": idx,
    }


def _compute_hist_trend(hist_3d: list[float]) -> str:
    """Compute MACD histogram trend from last 3 values."""
    if len(hist_3d) < 2:
        return "mixed"
    inc = 0
    dec = 0
    for i in range(1, len(hist_3d)):
        if hist_3d[i] > hist_3d[i - 1]:
            inc += 1
        elif hist_3d[i] < hist_3d[i - 1]:
            dec += 1
    if inc > 0 and dec == 0:
        return f"increasing_{inc}d"
    elif dec > 0 and inc == 0:
        return f"decreasing_{dec}d"
    return "mixed"


# ═══════════════════════════════════════════════════════════
# Phase 3: Signal Simulation
# ═══════════════════════════════════════════════════════════

def run_simulation(hist_data: dict[str, pd.DataFrame],
                   backtest_days: int = 252,
                   eval_days: list[int] | None = None) -> dict:
    """Run signal judgment on each ticker/date, measure forward returns."""
    if eval_days is None:
        eval_days = [3, 5, 10]

    records = []
    signal_counts = {"1st_BUY": 0, "2nd_BUY": 0, "3rd_BUY": 0, "WATCH": 0}
    tickers_processed = 0

    # Get VIX data for macro dict
    vix_df = hist_data.get("^VIX")

    for ticker, df in hist_data.items():
        if ticker.startswith("^"):
            continue
        tickers_processed += 1

        ind = build_indicators(df)
        n = len(ind)
        start_idx = max(200, n - backtest_days)

        for idx in range(start_idx, n):
            day_dict = build_day_dict(ind, idx)
            if day_dict is None:
                continue

            # Run entry check (Growth rules for SP100)
            signal, conditions = signal_judge._check_entry_growth(day_dict)

            if signal is None:
                continue
            if signal not in signal_counts:
                continue

            signal_counts[signal] += 1

            # Measure forward returns
            outcomes = {}
            entry_price = day_dict["price"]
            for ed in eval_days:
                future_idx = idx + ed
                if future_idx < n:
                    future_price = float(ind["Close"].iloc[future_idx])
                    ret = round((future_price - entry_price) / entry_price * 100, 2)
                    outcomes[f"{ed}d"] = ret

            # Max gain/loss within 10d
            future_slice = ind["Close"].iloc[idx + 1:min(idx + 11, n)]
            if len(future_slice) > 0:
                max_price = float(future_slice.max())
                min_price = float(future_slice.min())
                outcomes["max_gain_10d"] = round((max_price - entry_price) / entry_price * 100, 2)
                outcomes["max_loss_10d"] = round((min_price - entry_price) / entry_price * 100, 2)

            date_str = str(ind.index[idx].date()) if hasattr(ind.index[idx], 'date') else str(ind.index[idx])[:10]

            records.append({
                "date": date_str,
                "ticker": ticker,
                "signal": signal,
                "price": entry_price,
                "rsi": day_dict["rsi14"],
                "dd_52w": day_dict["drawdown_52w_pct"],
                "volume_ratio": day_dict["volume_ratio"],
                "outcomes": outcomes,
            })

    # Compute statistics
    stats = _compute_stats(records, eval_days)
    stats["tickers_processed"] = tickers_processed
    stats["signal_counts"] = signal_counts
    stats["total_signals"] = sum(signal_counts.values())
    stats["records"] = records

    return stats


def _compute_stats(records: list[dict], eval_days: list[int],
                   win_threshold: float = 3.0) -> dict:
    """Compute win rates and average returns."""
    if not records:
        return {"win_rate_5d": 0, "avg_return_5d": 0, "by_signal": {}}

    by_signal = {}
    for r in records:
        sig = r["signal"]
        if sig not in by_signal:
            by_signal[sig] = {"count": 0, "returns_5d": [], "returns_3d": [], "returns_10d": []}
        by_signal[sig]["count"] += 1
        for ed in eval_days:
            key = f"{ed}d"
            if key in r["outcomes"]:
                by_signal[sig][f"returns_{ed}d"].append(r["outcomes"][key])

    for sig, data in by_signal.items():
        for ed in eval_days:
            rets = data[f"returns_{ed}d"]
            if rets:
                data[f"win_rate_{ed}d"] = round(sum(1 for r in rets if r >= win_threshold) / len(rets), 3)
                data[f"avg_return_{ed}d"] = round(sum(rets) / len(rets), 2)
            else:
                data[f"win_rate_{ed}d"] = 0
                data[f"avg_return_{ed}d"] = 0

    # Overall BUY stats
    all_buy_5d = []
    for sig in ["1st_BUY", "2nd_BUY", "3rd_BUY"]:
        if sig in by_signal:
            all_buy_5d.extend(by_signal[sig]["returns_5d"])

    return {
        "win_rate_5d": round(sum(1 for r in all_buy_5d if r >= win_threshold) / len(all_buy_5d), 3) if all_buy_5d else 0,
        "avg_return_5d": round(sum(all_buy_5d) / len(all_buy_5d), 2) if all_buy_5d else 0,
        "by_signal": by_signal,
    }


# ═══════════════════════════════════════════════════════════
# Phase 4: Grid Search (Parameter-by-parameter)
# ═══════════════════════════════════════════════════════════

PARAM_GRID = {
    "entry_growth.1st_buy.rsi_max": [30, 35, 38, 40, 42, 45, 50],
    "entry_growth.1st_buy.dd_52w_max": [-25.0, -20.0, -18.0, -15.0, -12.0, -10.0],
    "entry_growth.2nd_buy.rsi_recovery": [30, 35, 40, 45],
    "entry_growth.2nd_buy.volume_ratio": [1.0, 1.2, 1.3, 1.5],
    "entry_growth.2nd_buy.double_bottom_diff": [2.0, 3.0, 5.0, 7.0],
    "entry_growth.3rd_buy.rsi_min": [45, 50, 55, 60],
    "entry_growth.3rd_buy.volume_ratio": [1.0, 1.3, 1.5, 2.0],
    "entry_growth.reject_rsi": [50, 55, 60, 65],
}


def _set_nested(d: dict, path: str, value):
    """Set nested dict value by dot-separated path."""
    keys = path.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def _get_nested(d: dict, path: str, default=None):
    """Get nested dict value by dot-separated path."""
    keys = path.split(".")
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, default)
        else:
            return default
    return d


def grid_search(hist_data: dict[str, pd.DataFrame],
                backtest_days: int = 252) -> dict:
    """Run parameter-by-parameter grid search."""
    original_params = copy.deepcopy(signal_judge.PARAMS)
    results = []

    total_runs = sum(len(v) for v in PARAM_GRID.items())
    run_count = 0

    for param_path, values in PARAM_GRID.items():
        current_val = _get_nested(original_params, param_path)
        param_results = []

        for val in values:
            run_count += 1
            # Patch params
            patched = copy.deepcopy(original_params)
            _set_nested(patched, param_path, val)
            signal_judge.PARAMS = patched

            marker = " <-- current" if val == current_val else ""
            print(f"  [{run_count}] {param_path} = {val}{marker}", end="", flush=True)

            sim = run_simulation(hist_data, backtest_days, [3, 5, 10])
            wr = sim["win_rate_5d"]
            avg = sim["avg_return_5d"]
            cnt = sim["total_signals"]
            print(f"  -> signals={cnt}, win_5d={wr:.1%}, avg_5d={avg:+.2f}%")

            param_results.append({
                "value": val,
                "signal_count": cnt,
                "win_rate_5d": wr,
                "avg_return_5d": avg,
                "by_signal": {k: {"count": v["count"],
                                  "win_rate_5d": v.get("win_rate_5d", 0),
                                  "avg_return_5d": v.get("avg_return_5d", 0)}
                              for k, v in sim["by_signal"].items()},
                "is_current": val == current_val,
            })

        # Find best
        scored = [(r, r["win_rate_5d"] * 0.5 + max(0, r["avg_return_5d"]) / 10 * 0.3 +
                   (1.0 if 10 <= r["signal_count"] <= 200 else 0.5) * 0.2)
                  for r in param_results]
        scored.sort(key=lambda x: -x[1])
        best = scored[0][0]

        results.append({
            "param": param_path,
            "current_value": current_val,
            "best_value": best["value"],
            "results": param_results,
            "best_win_rate": best["win_rate_5d"],
            "best_avg_return": best["avg_return_5d"],
            "best_signal_count": best["signal_count"],
        })

    # Restore original
    signal_judge.PARAMS = original_params
    return {"grid_results": results}


# ═══════════════════════════════════════════════════════════
# Phase 4b: Composite Filter Search (Noise Reduction)
# ═══════════════════════════════════════════════════════════

# Each filter is a (name, function) that returns True if the day_dict passes
COMPOSITE_FILTERS = {
    # ── RSI Filters ──
    "RSI<=35":          lambda d: d["rsi14"] <= 35,
    "RSI<=38":          lambda d: d["rsi14"] <= 38,
    "RSI<=40":          lambda d: d["rsi14"] <= 40,
    "RSI<=45":          lambda d: d["rsi14"] <= 45,
    "RSI_rising":       lambda d: len(d.get("_rsi_prev", [])) > 0 and d["rsi14"] > d["_rsi_prev"][-1],
    # ── Drawdown Filters ──
    "DD52w<=-15%":      lambda d: d["drawdown_52w_pct"] <= -15,
    "DD52w<=-20%":      lambda d: d["drawdown_52w_pct"] <= -20,
    "DD52w<=-25%":      lambda d: d["drawdown_52w_pct"] <= -25,
    # ── MACD Filters ──
    "MACD_hist_inc":    lambda d: "increasing" in d.get("macd_hist_trend", ""),
    "MACD_hist_inc3d":  lambda d: "increasing" in d.get("macd_hist_trend", "") and
                        len([1 for i in range(1, len(d["macd_hist_3d"])) if d["macd_hist_3d"][i] > d["macd_hist_3d"][i-1]]) >= 2,
    "MACD_cross_up":    lambda d: d["macd"] > d["macd_signal"],
    "MACD_hist>0":      lambda d: d["macd_hist"] > 0,
    # ── Moving Average Filters ──
    "Price<MA20":       lambda d: d["price"] < d["ma20"],
    "Price>MA50":       lambda d: d["ma50"] > 0 and d["price"] > d["ma50"],
    "Price>MA200":      lambda d: d["ma200"] > 0 and d["price"] > d["ma200"],
    "MA20>MA50":        lambda d: d["ma50"] > 0 and d["ma20"] > 0 and d["ma20"] > d["ma50"],
    # ── Volume Filters ──
    "Vol>=1.2x":        lambda d: d["volume_ratio"] >= 1.2,
    "Vol>=1.5x":        lambda d: d["volume_ratio"] >= 1.5,
    "Vol>=2.0x":        lambda d: d["volume_ratio"] >= 2.0,
    # ── ADX Filters ──
    "ADX>=20":          lambda d: d["adx"] >= 20,
    "ADX>=25":          lambda d: d["adx"] >= 25,
    "ADX>=30":          lambda d: d["adx"] >= 30,
    # ── Bollinger Band Filters ──
    "BB_pct<20":        lambda d: d["bb_pct"] < 20,
    "BB_pct<30":        lambda d: d["bb_pct"] < 30,
    # ── Double Bottom / Higher Low ──
    "Double_bottom":    lambda d: d.get("double_bottom", {}).get("detected", False),
    "Low_stopped":      lambda d: d.get("sig_low_stopped", False),
    # ── RSI > thresholds (for 2nd/3rd BUY) ──
    "RSI>35":           lambda d: d["rsi14"] > 35,
    "RSI>40":           lambda d: d["rsi14"] > 40,
    "RSI>50":           lambda d: d["rsi14"] > 50,
    "RSI>55":           lambda d: d["rsi14"] > 55,
    "RSI>60":           lambda d: d["rsi14"] > 60,
    # ── Price above MA ──
    "Price>MA20":       lambda d: d["price"] > d["ma20"] and d["ma20"] > 0,
}

# Pre-defined composite strategies to test
COMPOSITE_STRATEGIES = [
    # ── Baseline (current 1st_BUY) ──
    {
        "name": "Baseline (current 1st_BUY)",
        "filters": ["RSI<=45", "Price<MA20", "MACD_hist_inc", "DD52w<=-15%"],
        "min_match": 4,  # ALL
    },
    # ── Tighter RSI ──
    {
        "name": "Tight RSI (<=35) + DD-20%",
        "filters": ["RSI<=35", "Price<MA20", "MACD_hist_inc", "DD52w<=-20%"],
        "min_match": 4,
    },
    # ── RSI<=38 + Volume confirmation ──
    {
        "name": "RSI38 + Volume 1.5x",
        "filters": ["RSI<=38", "Price<MA20", "MACD_hist_inc", "DD52w<=-15%", "Vol>=1.5x"],
        "min_match": 5,
    },
    # ── RSI + ADX trend confirmation ──
    {
        "name": "RSI40 + ADX>=25 (trend)",
        "filters": ["RSI<=40", "Price<MA20", "MACD_hist_inc", "DD52w<=-15%", "ADX>=25"],
        "min_match": 5,
    },
    # ── Deep value: extreme oversold ──
    {
        "name": "Deep Value (RSI35 + DD-25% + BB<20)",
        "filters": ["RSI<=35", "DD52w<=-25%", "BB_pct<20", "MACD_hist_inc"],
        "min_match": 4,
    },
    # ── RSI38 + DD20 + MACD cross ──
    {
        "name": "RSI38 + DD20 + MACD cross",
        "filters": ["RSI<=38", "DD52w<=-20%", "MACD_cross_up", "Price<MA20"],
        "min_match": 4,
    },
    # ── Confirmation combo: RSI + Vol + ADX ──
    {
        "name": "RSI40 + Vol1.2 + ADX20",
        "filters": ["RSI<=40", "Price<MA20", "MACD_hist_inc", "DD52w<=-15%", "Vol>=1.2x", "ADX>=20"],
        "min_match": 6,
    },
    # ── Moderate: pick 5 of 6 ──
    {
        "name": "Pick-5-of-6 (RSI40+DD15+MACD+MA+Vol+ADX)",
        "filters": ["RSI<=40", "DD52w<=-15%", "MACD_hist_inc", "Price<MA20", "Vol>=1.2x", "ADX>=20"],
        "min_match": 5,
    },
    # ── BB bottom + RSI ──
    {
        "name": "BB bottom + RSI38 + DD20",
        "filters": ["RSI<=38", "BB_pct<20", "DD52w<=-20%", "MACD_hist_inc", "Price<MA20"],
        "min_match": 5,
    },
    # ── MACD golden + RSI rising ──
    {
        "name": "MACD golden + RSI<=40 + DD15",
        "filters": ["RSI<=40", "MACD_cross_up", "DD52w<=-15%", "Price<MA20"],
        "min_match": 4,
    },
    # ── Ultra strict: all signals ──
    {
        "name": "Ultra (RSI35+DD20+Vol1.5+ADX25+BB30)",
        "filters": ["RSI<=35", "DD52w<=-20%", "Vol>=1.5x", "ADX>=25", "BB_pct<30", "MACD_hist_inc"],
        "min_match": 6,
    },
    # ── Double bottom confirmation ──
    {
        "name": "Double Bottom + RSI40 + MACD",
        "filters": ["RSI<=40", "Double_bottom", "MACD_hist_inc", "DD52w<=-15%"],
        "min_match": 4,
    },
    # ── Trend reversal: MA200 above + oversold ──
    {
        "name": "Above MA200 + RSI<=40 + DD15",
        "filters": ["RSI<=40", "Price>MA200", "DD52w<=-15%", "MACD_hist_inc", "Price<MA20"],
        "min_match": 5,
    },
    # ── Volume spike + deep pullback ──
    {
        "name": "Vol2x Spike + RSI38 + DD20",
        "filters": ["RSI<=38", "DD52w<=-20%", "Vol>=2.0x", "MACD_hist_inc"],
        "min_match": 4,
    },
    # ── RSI35 + 3d MACD hist increasing ──
    {
        "name": "RSI35 + MACD 3d inc + DD15",
        "filters": ["RSI<=35", "MACD_hist_inc3d", "DD52w<=-15%", "Price<MA20"],
        "min_match": 4,
    },

    # ═══════════════════════════════════════════
    # 2nd BUY strategies (Recovery Confirmation)
    # ═══════════════════════════════════════════
    {
        "name": "[2nd] Baseline (DB+RSI35+MACD+Vol1.2)",
        "filters": ["Double_bottom", "RSI>35", "MACD_cross_up", "Vol>=1.2x"],
        "min_match": 4,
    },
    {
        "name": "[2nd] DB+RSI40+MACD+Vol1.2",
        "filters": ["Double_bottom", "RSI>40", "MACD_cross_up", "Vol>=1.2x"],
        "min_match": 4,
    },
    {
        "name": "[2nd] DB+RSI35+MACD+Vol1.5",
        "filters": ["Double_bottom", "RSI>35", "MACD_cross_up", "Vol>=1.5x"],
        "min_match": 4,
    },
    {
        "name": "[2nd] DB+RSI40+MACD+ADX20",
        "filters": ["Double_bottom", "RSI>40", "MACD_cross_up", "ADX>=20"],
        "min_match": 4,
    },
    {
        "name": "[2nd] Pick3(DB+RSI35+MACD+Vol1.2)",
        "filters": ["Double_bottom", "RSI>35", "MACD_cross_up", "Vol>=1.2x"],
        "min_match": 3,
    },
    {
        "name": "[2nd] DB+RSI40+MACD+Vol1.2+ADX25",
        "filters": ["Double_bottom", "RSI>40", "MACD_cross_up", "Vol>=1.2x", "ADX>=25"],
        "min_match": 5,
    },
    {
        "name": "[2nd] MACD_cross+RSI>35+Price>MA20",
        "filters": ["MACD_cross_up", "RSI>35", "Price>MA20", "Vol>=1.2x"],
        "min_match": 4,
    },
    {
        "name": "[2nd] MACD_cross+RSI>40+HigherLow+Vol1.2",
        "filters": ["MACD_cross_up", "RSI>40", "Low_stopped", "Vol>=1.2x"],
        "min_match": 4,
    },

    # ═══════════════════════════════════════════
    # 3rd BUY strategies (Trend Continuation)
    # ═══════════════════════════════════════════
    {
        "name": "[3rd] Baseline (MA20+MACD>0+Vol1.3+RSI55)",
        "filters": ["Price>MA20", "MACD_hist>0", "MACD_cross_up", "Vol>=1.2x", "RSI>55"],
        "min_match": 5,
    },
    {
        "name": "[3rd] MA20+MACD>0+Vol1.5+RSI55",
        "filters": ["Price>MA20", "MACD_hist>0", "MACD_cross_up", "Vol>=1.5x", "RSI>55"],
        "min_match": 5,
    },
    {
        "name": "[3rd] MA20+MACD>0+RSI55+ADX25",
        "filters": ["Price>MA20", "MACD_hist>0", "MACD_cross_up", "RSI>55", "ADX>=25"],
        "min_match": 5,
    },
    {
        "name": "[3rd] MA20+MA50+MACD>0+RSI50",
        "filters": ["Price>MA20", "MA20>MA50", "MACD_hist>0", "RSI>50"],
        "min_match": 4,
    },
    {
        "name": "[3rd] MA20+MACD>0+RSI60+Vol1.3+ADX20",
        "filters": ["Price>MA20", "MACD_hist>0", "MACD_cross_up", "RSI>60", "Vol>=1.2x", "ADX>=20"],
        "min_match": 6,
    },
    {
        "name": "[3rd] Pick4(MA20+MACD+RSI50+Vol1.2+ADX20)",
        "filters": ["Price>MA20", "MACD_cross_up", "RSI>50", "Vol>=1.2x", "ADX>=20"],
        "min_match": 4,
    },
    {
        "name": "[3rd] MA200+MA20+MACD>0+RSI55",
        "filters": ["Price>MA200", "Price>MA20", "MACD_hist>0", "RSI>55"],
        "min_match": 4,
    },
    {
        "name": "[3rd] MA20+MACD>0+RSI55 (no vol)",
        "filters": ["Price>MA20", "MACD_hist>0", "MACD_cross_up", "RSI>55"],
        "min_match": 4,
    },
]


def run_composite_search(hist_data: dict[str, pd.DataFrame],
                         backtest_days: int = 252,
                         eval_days: list[int] | None = None) -> list[dict]:
    """Test multiple composite filter strategies on historical data."""
    if eval_days is None:
        eval_days = [3, 5, 10]

    # Pre-compute all indicators and day_dicts
    print("  Pre-computing indicators for all tickers...")
    all_days = []  # list of (ticker, idx, day_dict, ind_df)
    for ticker, df in hist_data.items():
        if ticker.startswith("^"):
            continue
        ind = build_indicators(df)
        n = len(ind)
        start_idx = max(200, n - backtest_days)

        # Pre-compute RSI prev for RSI_rising filter
        rsi_series = ind["rsi14"]

        for idx in range(start_idx, n):
            day_dict = build_day_dict(ind, idx)
            if day_dict is None:
                continue
            # Add RSI prev for rising check
            if idx >= 1 and not pd.isna(rsi_series.iloc[idx - 1]):
                day_dict["_rsi_prev"] = [float(rsi_series.iloc[idx - 1])]
            else:
                day_dict["_rsi_prev"] = []
            all_days.append((ticker, idx, day_dict, ind))

    print(f"  Total day-points: {len(all_days)}")

    results = []
    for strat in COMPOSITE_STRATEGIES:
        name = strat["name"]
        filters = strat["filters"]
        min_match = strat["min_match"]

        records = []
        for ticker, idx, d, ind in all_days:
            # Count matching filters
            matched = sum(1 for f_name in filters if COMPOSITE_FILTERS[f_name](d))
            if matched < min_match:
                continue

            # Signal triggered — measure outcomes
            entry_price = d["price"]
            outcomes = {}
            n = len(ind)
            for ed in eval_days:
                fi = idx + ed
                if fi < n:
                    fp = float(ind["Close"].iloc[fi])
                    outcomes[f"{ed}d"] = round((fp - entry_price) / entry_price * 100, 2)

            future_slice = ind["Close"].iloc[idx + 1:min(idx + 11, n)]
            if len(future_slice) > 0:
                outcomes["max_gain_10d"] = round((float(future_slice.max()) - entry_price) / entry_price * 100, 2)
                outcomes["max_loss_10d"] = round((float(future_slice.min()) - entry_price) / entry_price * 100, 2)

            records.append(outcomes)

        # Stats
        total = len(records)
        if total == 0:
            results.append({"name": name, "count": 0, "win_3d": 0, "win_5d": 0,
                            "win_10d": 0, "avg_5d": 0, "avg_10d": 0, "max_gain_avg": 0, "max_loss_avg": 0,
                            "profit_rate": 0, "filters": filters, "min_match": min_match})
            continue

        win_3d = sum(1 for r in records if r.get("3d", -99) >= 3) / total
        win_5d = sum(1 for r in records if r.get("5d", -99) >= 3) / total
        win_10d = sum(1 for r in records if r.get("10d", -99) >= 3) / total
        profit_rate = sum(1 for r in records if r.get("5d", -99) > 0) / total  # >0% win
        avg_5d = sum(r.get("5d", 0) for r in records) / total
        avg_10d = sum(r.get("10d", 0) for r in records) / total
        max_gain_avg = sum(r.get("max_gain_10d", 0) for r in records) / total
        max_loss_avg = sum(r.get("max_loss_10d", 0) for r in records) / total

        results.append({
            "name": name, "count": total,
            "win_3d": round(win_3d, 3), "win_5d": round(win_5d, 3), "win_10d": round(win_10d, 3),
            "profit_rate": round(profit_rate, 3),
            "avg_5d": round(avg_5d, 2), "avg_10d": round(avg_10d, 2),
            "max_gain_avg": round(max_gain_avg, 2), "max_loss_avg": round(max_loss_avg, 2),
            "filters": filters, "min_match": min_match,
        })

    return results


def print_composite_report(results: list[dict]):
    """Print composite filter search results."""
    print("\n" + "=" * 100)
    print("  COMPOSITE FILTER SEARCH — Noise Reduction Analysis")
    print("=" * 100)
    print(f"\n  {'#':<3} {'Strategy':<42} {'Signals':>7} {'Profit%':>8} {'W5d(3%)':>8} {'W10d':>6} {'Avg5d':>7} {'Avg10d':>7} {'MaxG':>6} {'MaxL':>6}")
    print("  " + "-" * 98)

    # Sort by profit_rate descending
    sorted_results = sorted(results, key=lambda r: -r["profit_rate"])
    for i, r in enumerate(sorted_results):
        marker = " ***" if r["profit_rate"] >= 0.55 and r["count"] >= 10 else ""
        print(f"  {i+1:<3} {r['name']:<42} {r['count']:>7} {r['profit_rate']:>7.0%} {r['win_5d']:>7.0%} "
              f"{r['win_10d']:>5.0%} {r['avg_5d']:>+6.2f}% {r['avg_10d']:>+6.2f}% "
              f"{r['max_gain_avg']:>+5.1f}% {r['max_loss_avg']:>+5.1f}%{marker}")

    print("\n  *** = Profit Rate >= 55% AND Signals >= 10 (recommended)")
    print("  Profit% = 5일 후 양수 수익 비율 (>0%)")
    print("  W5d(3%) = 5일 내 +3% 이상 비율")
    print("=" * 100)


# ═══════════════════════════════════════════════════════════
# Phase 5: Report Output
# ═══════════════════════════════════════════════════════════

def print_report(baseline: dict, grid: dict | None = None):
    """Print formatted report to console."""
    print("\n" + "=" * 70)
    print("  HISTORICAL BACKTEST REPORT")
    print("=" * 70)

    print(f"\n  Tickers: {baseline['tickers_processed']}")
    print(f"  Total Signals: {baseline['total_signals']}")
    print(f"  BUY Win Rate (5d): {baseline['win_rate_5d']:.1%}")
    print(f"  BUY Avg Return (5d): {baseline['avg_return_5d']:+.2f}%")

    print(f"\n  {'Signal':<12} {'Count':>6} {'Win3d':>7} {'Win5d':>7} {'Win10d':>7} {'Avg5d':>8}")
    print("  " + "-" * 55)
    for sig, data in baseline["by_signal"].items():
        print(f"  {sig:<12} {data['count']:>6} "
              f"{data.get('win_rate_3d', 0):>6.0%} "
              f"{data.get('win_rate_5d', 0):>6.0%} "
              f"{data.get('win_rate_10d', 0):>6.0%} "
              f"{data.get('avg_return_5d', 0):>+7.2f}%")

    if grid:
        print("\n" + "=" * 70)
        print("  PARAMETER OPTIMIZATION RESULTS")
        print("=" * 70)
        print(f"\n  {'Parameter':<40} {'Current':>8} {'Best':>8} {'WinRate':>8} {'Signals':>8}")
        print("  " + "-" * 75)
        for r in grid["grid_results"]:
            changed = " *" if r["current_value"] != r["best_value"] else ""
            print(f"  {r['param']:<40} {str(r['current_value']):>8} {str(r['best_value']):>8} "
                  f"{r['best_win_rate']:>7.0%} {r['best_signal_count']:>7}{changed}")

        # Recommended changes
        changes = [r for r in grid["grid_results"] if r["current_value"] != r["best_value"]]
        if changes:
            print(f"\n  RECOMMENDED CHANGES ({len(changes)}):")
            for r in changes:
                print(f"    {r['param']}: {r['current_value']} -> {r['best_value']} "
                      f"(win {r['best_win_rate']:.0%}, signals {r['best_signal_count']})")

    print("\n" + "=" * 70)


def save_results(baseline: dict, grid: dict | None, output_path: str):
    """Save results to JSON."""
    today = datetime.now().strftime("%Y-%m-%d")
    result = {
        "_meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "backtest_type": "historical_1y",
            "tickers": baseline["tickers_processed"],
        },
        "baseline": {
            "total_signals": baseline["total_signals"],
            "signal_counts": baseline["signal_counts"],
            "win_rate_5d": baseline["win_rate_5d"],
            "avg_return_5d": baseline["avg_return_5d"],
            "by_signal": {k: {"count": v["count"],
                              "win_rate_3d": v.get("win_rate_3d", 0),
                              "win_rate_5d": v.get("win_rate_5d", 0),
                              "win_rate_10d": v.get("win_rate_10d", 0),
                              "avg_return_5d": v.get("avg_return_5d", 0)}
                          for k, v in baseline["by_signal"].items()},
        },
    }
    if grid:
        result["grid_search"] = grid["grid_results"]

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  Results saved: {output_path}")


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Historical Backtest Engine")
    parser.add_argument("--period", default="2y", help="Data download period (default: 2y)")
    parser.add_argument("--backtest-days", type=int, default=252, help="Trading days to backtest (default: 252)")
    parser.add_argument("--grid-search", action="store_true", help="Run parameter grid search")
    parser.add_argument("--composite", action="store_true", help="Run composite filter search")
    parser.add_argument("--no-cache", action="store_true", help="Ignore cached data")
    parser.add_argument("--output", default=None, help="Output JSON path")
    args = parser.parse_args()

    start_time = time.time()
    today = datetime.now().strftime("%Y-%m-%d")

    print("=" * 60)
    print("  Historical Backtest Engine")
    print(f"  Date: {today}")
    print(f"  Tickers: S&P 100 ({len(SP100_TICKERS)})")
    print(f"  Period: {args.period} (backtest: {args.backtest_days} trading days)")
    print(f"  Grid Search: {'ON' if args.grid_search else 'OFF'}")
    print("=" * 60)

    # Phase 1: Download
    print("\n[Phase 1] Downloading historical data...")
    hist_data = download_data(SP100_TICKERS, period=args.period, no_cache=args.no_cache)

    # Phase 2+3: Baseline simulation
    print("\n[Phase 2] Running baseline simulation...")
    baseline = run_simulation(hist_data, args.backtest_days)
    print(f"  Baseline: {baseline['total_signals']} signals, "
          f"win={baseline['win_rate_5d']:.1%}, avg={baseline['avg_return_5d']:+.2f}%")

    # Phase 4: Grid search (optional)
    grid = None
    if args.grid_search:
        print(f"\n[Phase 3] Grid Search ({sum(len(v) for v in PARAM_GRID.values())} runs)...")
        grid = grid_search(hist_data, args.backtest_days)

    # Phase 4b: Composite filter search (optional)
    composite = None
    if args.composite:
        print(f"\n[Phase 4] Composite Filter Search ({len(COMPOSITE_STRATEGIES)} strategies)...")
        composite = run_composite_search(hist_data, args.backtest_days)
        print_composite_report(composite)

    # Phase 5: Report
    print_report(baseline, grid)

    # Save
    output_path = args.output or os.path.join(HISTORY_DIR, f"backtest_grid_{today}.json")
    save_results(baseline, grid, output_path)

    elapsed = time.time() - start_time
    print(f"\n  Completed in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
