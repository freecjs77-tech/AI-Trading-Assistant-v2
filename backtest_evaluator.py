"""
backtest_evaluator.py — 시그널 성과 기록 + 적중률 분석
AI Trading Assistant v3.0

Stage 1: 과거 시그널 발생 → N일 후 실제 가격 변동 기록 (outcomes.json)
Stage 2: 시그널 유형별 승률/평균수익 분석 (backtest_analysis.json)
Stage 3: 파라미터 추천 (analysis에 포함)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from collections import defaultdict

import yfinance as yf
import pandas as pd


# ── 설정 ──────────────────────────────────────────────

_EVAL_DAYS = [3, 5, 10]
_WIN_THRESHOLD_PCT = 3.0  # BUY 시그널 승리 기준: N일 내 +3% 이상
_BUY_SIGNALS = {"1st_BUY", "2nd_BUY", "3rd_BUY"}
_EXIT_SIGNALS = {"TAKE_PROFIT_1", "TAKE_PROFIT_2", "TOP_SIGNAL"}
_TRACKABLE_SIGNALS = _BUY_SIGNALS | _EXIT_SIGNALS

# strategy_params.json에서 백테스트 설정 오버라이드
_PARAMS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategy_params.json")
try:
    with open(_PARAMS_PATH, "r", encoding="utf-8") as _f:
        _bt_params = json.load(_f).get("backtest", {})
        _WIN_THRESHOLD_PCT = _bt_params.get("win_threshold_pct", _WIN_THRESHOLD_PCT)
        _EVAL_DAYS = _bt_params.get("eval_days", _EVAL_DAYS)
except (FileNotFoundError, json.JSONDecodeError):
    pass


def load_outcomes(path: str) -> dict:
    """outcomes.json 로드."""
    if not os.path.exists(path):
        return {"_meta": {}, "records": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "records" not in data:
                data["records"] = []
            if "_meta" not in data:
                data["_meta"] = {}
            return data
    except (json.JSONDecodeError, IOError):
        return {"_meta": {}, "records": []}


def save_outcomes(outcomes: dict, path: str):
    """outcomes.json 저장."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(outcomes, f, ensure_ascii=False, indent=2)


def evaluate_outcomes(history: dict, outcomes_path: str) -> dict:
    """
    signals_history.json에서 추적 가능한 시그널을 찾고,
    N일 후 가격을 yfinance에서 조회하여 outcomes.json에 기록.
    이미 평가된 시그널은 스킵.
    """
    outcomes = load_outcomes(outcomes_path)
    existing_ids = {r["id"] for r in outcomes["records"]}

    today = datetime.now()
    max_eval_day = max(_EVAL_DAYS)

    # 히스토리에서 추적 대상 시그널 수집
    new_signals = []
    dates = sorted([k for k in history.keys() if not k.startswith("_")])

    for date_str in dates:
        signal_date = datetime.strptime(date_str, "%Y-%m-%d")
        days_ago = (today - signal_date).days

        # 최소 max_eval_day일 이상 지난 시그널만 평가 (결과 확인 가능)
        if days_ago < max_eval_day:
            continue

        day_data = history[date_str]
        macro = day_data.get("_macro", {})

        for ticker, info in day_data.items():
            if ticker.startswith("_"):
                continue
            if not isinstance(info, dict):
                continue

            signal = info.get("signal", "")
            if signal not in _TRACKABLE_SIGNALS:
                continue

            record_id = f"{date_str}|{ticker}|{signal}"
            if record_id in existing_ids:
                continue

            new_signals.append({
                "id": record_id,
                "ticker": ticker,
                "signal": signal,
                "date": date_str,
                "entry_price": info.get("price"),
                "context": {
                    "rsi": info.get("rsi"),
                    "macd_hist": info.get("macd_hist"),
                    "macd_hist_trend": info.get("macd_hist_trend"),
                    "drawdown": info.get("drawdown"),
                    "bb_pct": info.get("bb_pct"),
                    "price_vs_ma20": info.get("price_vs_ma20"),
                    "vix": macro.get("VIX"),
                    "master_switch": macro.get("master_switch"),
                },
                "note": info.get("note", ""),
            })

    if not new_signals:
        print("  [Backtest] No new signals to evaluate")
        return outcomes

    # yfinance에서 가격 데이터 일괄 조회
    tickers_needed = list({s["ticker"] for s in new_signals})
    all_dates = [s["date"] for s in new_signals]
    earliest = min(all_dates)
    start = (datetime.strptime(earliest, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d")
    end = (today + timedelta(days=2)).strftime("%Y-%m-%d")

    # KOSPI 종목 매핑
    yf_map = {}
    for t in tickers_needed:
        if t.isdigit() and len(t) == 6:
            yf_map[t] = f"{t}.KS"
        else:
            yf_map[t] = t

    print(f"  [Backtest] Fetching prices for {len(tickers_needed)} tickers ({earliest} ~ now)")
    try:
        yf_tickers = list(yf_map.values())
        df = yf.download(yf_tickers, start=start, end=end,
                         auto_adjust=True, progress=False)
        if df is None or df.empty:
            print("  [Backtest] No price data from yfinance")
            return outcomes
    except Exception as ex:
        print(f"  [Backtest] yfinance error: {ex}")
        return outcomes

    num_tickers = len(yf_tickers)
    evaluated = 0

    for sig in new_signals:
        ticker = sig["ticker"]
        yf_ticker = yf_map[ticker]
        entry_price = sig["entry_price"]

        if not entry_price or entry_price <= 0:
            continue

        sig_date = datetime.strptime(sig["date"], "%Y-%m-%d")
        outcomes_data = {}
        prices_after = []

        for eval_day in _EVAL_DAYS:
            target_date = sig_date + timedelta(days=eval_day)
            # 주말/공휴일 → 가장 가까운 이전 거래일 사용
            price = _get_price_near(df, yf_ticker, target_date, num_tickers)
            if price is not None:
                ret = round((price - entry_price) / entry_price * 100, 2)
                outcomes_data[f"{eval_day}d"] = {
                    "price": round(price, 2) if not (ticker.isdigit() and len(ticker) == 6) else round(price),
                    "return_pct": ret,
                }
                prices_after.append(ret)

        # max gain/loss 계산 (eval 기간 내 전체 거래일)
        max_gain, max_loss = _calc_max_gain_loss(
            df, yf_ticker, sig_date, max_eval_day, entry_price, num_tickers
        )
        if max_gain is not None:
            outcomes_data["max_gain_10d"] = max_gain
        if max_loss is not None:
            outcomes_data["max_loss_10d"] = max_loss

        if outcomes_data:
            sig["outcomes"] = outcomes_data
            sig["evaluated_at"] = today.strftime("%Y-%m-%d")
            outcomes["records"].append(sig)
            existing_ids.add(sig["id"])
            evaluated += 1

    outcomes["_meta"]["last_evaluated"] = today.strftime("%Y-%m-%d")
    outcomes["_meta"]["total_signals"] = len(outcomes["records"])

    save_outcomes(outcomes, outcomes_path)
    print(f"  [Backtest] {evaluated} new signals evaluated (total: {len(outcomes['records'])})")

    return outcomes


def _get_price_near(df, yf_ticker: str, target_date: datetime, num_tickers: int) -> float | None:
    """target_date 근처의 종가 조회. 주말/공휴일이면 직전 거래일 사용."""
    for offset in range(0, 5):
        dt = target_date + timedelta(days=offset)
        ts = pd.Timestamp(dt)
        try:
            if num_tickers == 1:
                if ts in df.index:
                    val = df.loc[ts, "Close"]
                    if pd.notna(val):
                        return float(val)
            else:
                if ts in df.index:
                    val = df.loc[ts, ("Close", yf_ticker)]
                    if pd.notna(val):
                        return float(val)
        except (KeyError, TypeError):
            continue
    return None


def _calc_max_gain_loss(df, yf_ticker: str, sig_date: datetime,
                        max_days: int, entry_price: float, num_tickers: int) -> tuple:
    """시그널 발생 후 max_days 이내의 최대 상승/하락률."""
    max_gain = None
    max_loss = None

    for offset in range(1, max_days + 5):
        dt = sig_date + timedelta(days=offset)
        ts = pd.Timestamp(dt)
        try:
            if num_tickers == 1:
                if ts in df.index:
                    val = df.loc[ts, "Close"]
                    if pd.notna(val):
                        ret = (float(val) - entry_price) / entry_price * 100
                        if max_gain is None or ret > max_gain:
                            max_gain = round(ret, 2)
                        if max_loss is None or ret < max_loss:
                            max_loss = round(ret, 2)
            else:
                if ts in df.index:
                    val = df.loc[ts, ("Close", yf_ticker)]
                    if pd.notna(val):
                        ret = (float(val) - entry_price) / entry_price * 100
                        if max_gain is None or ret > max_gain:
                            max_gain = round(ret, 2)
                        if max_loss is None or ret < max_loss:
                            max_loss = round(ret, 2)
        except (KeyError, TypeError):
            continue

    return max_gain, max_loss


# ═══════════════════════════════════════════════════════
#  Stage 2: 적중률 분석
# ═══════════════════════════════════════════════════════

def analyze_accuracy(outcomes: dict, analysis_path: str) -> dict:
    """
    outcomes.json의 기록을 분석하여 시그널별 통계 생성.
    결과를 backtest_analysis.json에 저장.
    """
    records = outcomes.get("records", [])
    if not records:
        analysis = {
            "generated_at": datetime.now().strftime("%Y-%m-%d"),
            "total_records": 0,
            "by_signal": {},
            "by_condition": {},
            "recommendations": [],
            "data_status": "insufficient",
        }
        _save_analysis(analysis, analysis_path)
        return analysis

    # 시그널 유형별 그룹핑
    by_signal = defaultdict(list)
    for r in records:
        by_signal[r["signal"]].append(r)

    signal_stats = {}
    for sig_type, sig_records in by_signal.items():
        stats = _calc_signal_stats(sig_type, sig_records)
        signal_stats[sig_type] = stats

    # 컨텍스트별 분석 (RSI 구간, VIX 구간 등)
    condition_stats = _analyze_conditions(records)

    # 파라미터 추천
    recommendations = _generate_recommendations(signal_stats, condition_stats, records)

    all_dates = [r["date"] for r in records]
    analysis = {
        "generated_at": datetime.now().strftime("%Y-%m-%d"),
        "period": {
            "from": min(all_dates),
            "to": max(all_dates),
        },
        "total_records": len(records),
        "by_signal": signal_stats,
        "by_condition": condition_stats,
        "recommendations": recommendations,
        "data_status": "sufficient" if len(records) >= 20 else "accumulating",
    }

    _save_analysis(analysis, analysis_path)
    print(f"  [Backtest] Analysis complete: {len(records)} records, {len(signal_stats)} signal types")
    return analysis


def _calc_signal_stats(sig_type: str, records: list) -> dict:
    """단일 시그널 유형의 통계."""
    stats = {"count": len(records)}
    is_buy = sig_type in _BUY_SIGNALS

    for eval_key in [f"{d}d" for d in _EVAL_DAYS]:
        returns = []
        wins = 0
        for r in records:
            out = r.get("outcomes", {}).get(eval_key)
            if out and out.get("return_pct") is not None:
                ret = out["return_pct"]
                returns.append(ret)
                if is_buy and ret >= _WIN_THRESHOLD_PCT:
                    wins += 1
                elif not is_buy and ret <= 0:
                    # EXIT 시그널: 이후 하락이면 성공
                    wins += 1

        if returns:
            stats[f"win_rate_{eval_key}"] = round(wins / len(returns), 3)
            stats[f"avg_return_{eval_key}"] = round(sum(returns) / len(returns), 2)
            stats[f"samples_{eval_key}"] = len(returns)

            positive = [r for r in returns if r > 0]
            negative = [r for r in returns if r < 0]
            if positive:
                stats[f"avg_gain_{eval_key}"] = round(sum(positive) / len(positive), 2)
            if negative:
                stats[f"avg_loss_{eval_key}"] = round(sum(negative) / len(negative), 2)

    # Best / Worst
    best = None
    worst = None
    eval_10d_key = f"{max(_EVAL_DAYS)}d"
    for r in records:
        out = r.get("outcomes", {}).get(eval_10d_key)
        if out and out.get("return_pct") is not None:
            ret = out["return_pct"]
            if best is None or ret > best.get("return", -999):
                best = {"ticker": r["ticker"], "date": r["date"], "return": ret}
            if worst is None or ret < worst.get("return", 999):
                worst = {"ticker": r["ticker"], "date": r["date"], "return": ret}

    if best:
        stats["best"] = best
    if worst:
        stats["worst"] = worst

    return stats


def _analyze_conditions(records: list) -> dict:
    """RSI 구간, VIX 구간별 승률 분석."""
    condition_stats = {}

    # RSI 구간별 (BUY 시그널만)
    buy_records = [r for r in records if r["signal"] in _BUY_SIGNALS]
    if buy_records:
        rsi_bins = {"RSI<=35": [], "RSI_36-45": [], "RSI_46-55": []}
        for r in buy_records:
            rsi = r.get("context", {}).get("rsi")
            ret_5d = r.get("outcomes", {}).get("5d", {}).get("return_pct")
            if rsi is None or ret_5d is None:
                continue
            if rsi <= 35:
                rsi_bins["RSI<=35"].append(ret_5d)
            elif rsi <= 45:
                rsi_bins["RSI_36-45"].append(ret_5d)
            elif rsi <= 55:
                rsi_bins["RSI_46-55"].append(ret_5d)

        for label, returns in rsi_bins.items():
            if returns:
                wins = sum(1 for r in returns if r >= _WIN_THRESHOLD_PCT)
                condition_stats[label] = {
                    "count": len(returns),
                    "win_rate_5d": round(wins / len(returns), 3),
                    "avg_return_5d": round(sum(returns) / len(returns), 2),
                }

    # Master Switch별
    ms_bins = defaultdict(list)
    for r in buy_records:
        ms = r.get("context", {}).get("master_switch", "UNKNOWN")
        ret_5d = r.get("outcomes", {}).get("5d", {}).get("return_pct")
        if ret_5d is not None:
            ms_bins[f"MS_{ms}"].append(ret_5d)

    for label, returns in ms_bins.items():
        if returns:
            wins = sum(1 for r in returns if r >= _WIN_THRESHOLD_PCT)
            condition_stats[label] = {
                "count": len(returns),
                "win_rate_5d": round(wins / len(returns), 3),
                "avg_return_5d": round(sum(returns) / len(returns), 2),
            }

    return condition_stats


def _generate_recommendations(signal_stats: dict, condition_stats: dict,
                              records: list) -> list:
    """분석 결과 기반 파라미터 조정 추천. 사람이 검토 후 적용."""
    recommendations = []
    min_samples = 20

    # RSI 임계값 완화 추천 (BUY 데이터 충분할 때)
    for sig_type in _BUY_SIGNALS:
        stats = signal_stats.get(sig_type, {})
        count = stats.get("count", 0)
        if count < min_samples:
            recommendations.append({
                "param": f"{sig_type} RSI threshold",
                "status": "data_needed",
                "reason": f"샘플 {count}/{min_samples}건 — 데이터 축적 중",
                "confidence": "none",
                "sample_size": count,
            })
            continue

        win_rate = stats.get("win_rate_5d", 0)
        avg_return = stats.get("avg_return_5d", 0)

        if win_rate < 0.5:
            recommendations.append({
                "param": f"{sig_type} conditions",
                "current_win_rate": win_rate,
                "avg_return": avg_return,
                "status": "review",
                "reason": f"승률 {win_rate:.0%} < 50% — 조건 강화 검토 필요",
                "confidence": "medium" if count >= 30 else "low",
                "sample_size": count,
            })
        elif win_rate >= 0.7:
            recommendations.append({
                "param": f"{sig_type} conditions",
                "current_win_rate": win_rate,
                "avg_return": avg_return,
                "status": "good",
                "reason": f"승률 {win_rate:.0%} — 현재 기준 유효",
                "confidence": "medium" if count >= 30 else "low",
                "sample_size": count,
            })

    # RSI 구간 인사이트
    rsi_low = condition_stats.get("RSI<=35", {})
    rsi_mid = condition_stats.get("RSI_36-45", {})
    if rsi_low.get("count", 0) >= 5 and rsi_mid.get("count", 0) >= 5:
        low_wr = rsi_low.get("win_rate_5d", 0)
        mid_wr = rsi_mid.get("win_rate_5d", 0)
        if mid_wr > low_wr + 0.1:
            recommendations.append({
                "param": "entry_growth.1st_buy.rsi_max",
                "insight": f"RSI 36-45 승률({mid_wr:.0%}) > RSI<=35 승률({low_wr:.0%})",
                "suggestion": "RSI 임계값을 35→45 범위에서 미세 조정 검토",
                "confidence": "low",
                "sample_size": rsi_low["count"] + rsi_mid["count"],
            })

    return recommendations


def _save_analysis(analysis: dict, path: str):
    """backtest_analysis.json 저장."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)


# ── CLI ──────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    project_dir = os.path.dirname(os.path.abspath(__file__))
    history_path = os.path.join(project_dir, "history", "signals_history.json")
    outcomes_path = os.path.join(project_dir, "history", "outcomes.json")
    analysis_path = os.path.join(project_dir, "history", "backtest_analysis.json")

    from history_manager import load_history
    history = load_history(history_path)
    outcomes = evaluate_outcomes(history, outcomes_path)
    analysis = analyze_accuracy(outcomes, analysis_path)

    print(f"\nTotal records: {analysis.get('total_records', 0)}")
    print(f"Data status: {analysis.get('data_status', 'unknown')}")
    for sig, stats in analysis.get("by_signal", {}).items():
        wr = stats.get("win_rate_5d", "N/A")
        print(f"  {sig}: {stats['count']}건, 5d 승률 {wr}")
