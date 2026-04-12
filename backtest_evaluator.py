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

_EVAL_DAYS = [3, 5, 10]  # 거래일 기준 (trading days)
_WIN_THRESHOLD_PCT = 3.0  # BUY 시그널 승리 기준: N거래일 내 +3% 이상
_CALENDAR_BUFFER = 1.5  # 거래일 → 캘린더일 변환 계수 (10거래일 ≈ 15캘린더일)
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


def _merge_all_histories(portfolio_history: dict, scanner_histories: dict | None) -> list:
    """포트폴리오 + 스캐너 히스토리를 통합하여 (date, ticker, info, source) 리스트로 반환."""
    merged = []
    today = datetime.now()
    # 거래일 기준: 10거래일 ≈ 14캘린더일. 여유 포함해서 필터링
    min_calendar_days = int(max(_EVAL_DAYS) * _CALENDAR_BUFFER)

    # 포트폴리오 히스토리
    dates = sorted([k for k in portfolio_history.keys() if not k.startswith("_")])
    for date_str in dates:
        signal_date = datetime.strptime(date_str, "%Y-%m-%d")
        days_ago = (today - signal_date).days
        if days_ago < min_calendar_days:
            continue

        day_data = portfolio_history[date_str]
        macro = day_data.get("_macro", {})

        for ticker, info in day_data.items():
            if ticker.startswith("_") or not isinstance(info, dict):
                continue
            signal = info.get("signal", "")
            if signal not in _TRACKABLE_SIGNALS:
                continue
            merged.append((date_str, ticker, info, "portfolio", macro))

    # 스캐너 히스토리
    if scanner_histories:
        for source_name, hist in scanner_histories.items():
            if not hist:
                continue
            sc_dates = sorted([k for k in hist.keys() if not k.startswith("_")])
            for date_str in sc_dates:
                signal_date = datetime.strptime(date_str, "%Y-%m-%d")
                days_ago = (today - signal_date).days
                if days_ago < min_calendar_days:
                    continue

                day_data = hist[date_str]
                for ticker, info in day_data.items():
                    if ticker.startswith("_") or not isinstance(info, dict):
                        continue
                    signal = info.get("signal", "")
                    if signal not in _TRACKABLE_SIGNALS:
                        continue
                    merged.append((date_str, ticker, info, source_name, {}))

    return merged


def evaluate_outcomes(history: dict, outcomes_path: str,
                      scanner_histories: dict | None = None) -> dict:
    """
    signals_history.json + 스캐너 히스토리에서 추적 가능한 시그널을 찾고,
    N일 후 가격을 yfinance에서 조회하여 outcomes.json에 기록.
    이미 평가된 시그널은 스킵.
    """
    outcomes = load_outcomes(outcomes_path)
    existing_ids = {r["id"] for r in outcomes["records"]}

    today = datetime.now()
    max_eval_day = max(_EVAL_DAYS)

    # 통합 히스토리에서 추적 대상 시그널 수집
    merged = _merge_all_histories(history, scanner_histories)

    new_signals = []
    for date_str, ticker, info, source, macro in merged:
        signal = info.get("signal", "")
        # source 포함 ID (기존 레코드 호환: source 없으면 portfolio)
        record_id = f"{date_str}|{ticker}|{signal}|{source}"
        # 기존 포맷 호환 체크
        old_id = f"{date_str}|{ticker}|{signal}"
        if record_id in existing_ids or old_id in existing_ids:
            continue

        new_signals.append({
            "id": record_id,
            "ticker": ticker,
            "signal": signal,
            "date": date_str,
            "source": source,
            "entry_price": info.get("price"),
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
        })

    if not new_signals:
        print("  [Backtest] No new signals to evaluate")
        return outcomes

    # yfinance에서 가격 데이터 일괄 조회
    tickers_needed = list({s["ticker"] for s in new_signals})
    # SPY도 항상 포함 (벤치마크)
    if "SPY" not in tickers_needed:
        tickers_needed.append("SPY")

    all_dates = [s["date"] for s in new_signals]
    earliest = min(all_dates)
    # 거래일 기준이므로 충분한 캘린더 여유 확보
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

    # SPY yf ticker
    spy_yf = yf_map.get("SPY", "SPY")

    for sig in new_signals:
        ticker = sig["ticker"]
        yf_ticker = yf_map[ticker]
        entry_price = sig["entry_price"]

        if not entry_price or entry_price <= 0:
            continue

        sig_date = datetime.strptime(sig["date"], "%Y-%m-%d")
        outcomes_data = {}

        # 거래일 인덱스 추출 (시그널 발생일 이후)
        trading_days = _get_trading_days_after(df, yf_ticker, sig_date, num_tickers)

        for eval_day in _EVAL_DAYS:
            if eval_day <= len(trading_days):
                td = trading_days[eval_day - 1]  # 0-indexed → N번째 거래일
                price = _get_close(df, yf_ticker, td, num_tickers)
                if price is not None:
                    ret = round((price - entry_price) / entry_price * 100, 2)
                    outcomes_data[f"{eval_day}d"] = {
                        "price": round(price, 2) if not (ticker.isdigit() and len(ticker) == 6) else round(price),
                        "return_pct": ret,
                    }

            # SPY 벤치마크 (같은 거래일 수 기준)
            if ticker != "SPY":
                spy_trading_days = _get_trading_days_after(df, spy_yf, sig_date, num_tickers)
                spy_entry_price = _get_close_near(df, spy_yf, sig_date, num_tickers)
                if eval_day <= len(spy_trading_days) and spy_entry_price:
                    spy_td = spy_trading_days[eval_day - 1]
                    spy_price = _get_close(df, spy_yf, spy_td, num_tickers)
                    if spy_price and spy_entry_price > 0:
                        spy_ret = round((spy_price - spy_entry_price) / spy_entry_price * 100, 2)
                        outcomes_data[f"spy_{eval_day}d"] = spy_ret

        # max gain/loss 계산 (max_eval_day 거래일 내)
        max_eval_day = max(_EVAL_DAYS)
        max_gain, max_loss = _calc_max_gain_loss_td(
            df, yf_ticker, trading_days, max_eval_day, entry_price, num_tickers
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


def _get_trading_days_after(df, yf_ticker: str, sig_date: datetime, num_tickers: int) -> list:
    """시그널 발생일 이후의 거래일 목록 반환 (Timestamp 리스트)."""
    sig_ts = pd.Timestamp(sig_date)
    # df.index에서 시그널일 이후 거래일만 필터
    if num_tickers == 1:
        after = df.index[df.index > sig_ts]
    else:
        try:
            # 해당 ticker에 데이터가 있는 날만
            close_col = df["Close"][yf_ticker] if yf_ticker in df["Close"].columns else pd.Series(dtype=float)
            valid_dates = close_col.dropna().index
            after = valid_dates[valid_dates > sig_ts]
        except (KeyError, TypeError):
            after = df.index[df.index > sig_ts]
    return list(after)


def _get_close(df, yf_ticker: str, ts: pd.Timestamp, num_tickers: int) -> float | None:
    """특정 거래일의 종가 조회."""
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
        pass
    return None


def _get_close_near(df, yf_ticker: str, target_date: datetime, num_tickers: int) -> float | None:
    """target_date 당일 또는 직후 거래일의 종가 조회."""
    for offset in range(0, 5):
        dt = target_date + timedelta(days=offset)
        ts = pd.Timestamp(dt)
        price = _get_close(df, yf_ticker, ts, num_tickers)
        if price is not None:
            return price
    return None


def _calc_max_gain_loss_td(df, yf_ticker: str, trading_days: list,
                           max_td: int, entry_price: float, num_tickers: int) -> tuple:
    """시그널 발생 후 max_td 거래일 이내의 최대 상승/하락률."""
    max_gain = None
    max_loss = None

    for td in trading_days[:max_td]:
        price = _get_close(df, yf_ticker, td, num_tickers)
        if price is not None:
            ret = (price - entry_price) / entry_price * 100
            if max_gain is None or ret > max_gain:
                max_gain = round(ret, 2)
            if max_loss is None or ret < max_loss:
                max_loss = round(ret, 2)

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
            "by_source": {},
            "by_condition": {},
            "benchmark": {},
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

    # 소스별 분석
    source_stats = _analyze_by_source(records)

    # 컨텍스트별 분석 (RSI 구간, VIX 구간 등)
    condition_stats = _analyze_conditions(records)

    # 벤치마크 (SPY 대비 alpha)
    benchmark = _analyze_benchmark(records)

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
        "by_source": source_stats,
        "by_condition": condition_stats,
        "benchmark": benchmark,
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
        reach_wins = 0  # reach rate용 (BUY만)
        for r in records:
            out = r.get("outcomes", {}).get(eval_key)
            if out and out.get("return_pct") is not None:
                ret = out["return_pct"]
                returns.append(ret)
                if is_buy and ret >= _WIN_THRESHOLD_PCT:
                    wins += 1
                elif not is_buy:
                    # EXIT 시그널: max_gain이 +3% 이하면 성공 (크게 안 올랐다 = 익절 적절)
                    max_gain = r.get("outcomes", {}).get("max_gain_10d")
                    if max_gain is not None and max_gain <= _WIN_THRESHOLD_PCT:
                        wins += 1

            # Reach rate (BUY만): max_gain이 +3% 이상 도달한 적 있는지
            if is_buy:
                max_gain = r.get("outcomes", {}).get("max_gain_10d")
                if max_gain is not None and max_gain >= _WIN_THRESHOLD_PCT:
                    reach_wins += 1

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

    # Reach rate (BUY 시그널)
    if is_buy:
        total_with_max = sum(1 for r in records if r.get("outcomes", {}).get("max_gain_10d") is not None)
        if total_with_max > 0:
            stats["reach_rate_10d"] = round(reach_wins / total_with_max, 3)

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


def _analyze_by_source(records: list) -> dict:
    """소스별 (portfolio, sp100, etf, kospi) 통계."""
    by_source = defaultdict(list)
    for r in records:
        source = r.get("source", "portfolio")
        by_source[source].append(r)

    source_stats = {}
    for source, recs in by_source.items():
        buy_recs = [r for r in recs if r["signal"] in _BUY_SIGNALS]
        exit_recs = [r for r in recs if r["signal"] in _EXIT_SIGNALS]

        stats = {"count": len(recs), "buy_count": len(buy_recs), "exit_count": len(exit_recs)}

        # BUY 5d 승률
        buy_returns = []
        buy_wins = 0
        for r in buy_recs:
            out = r.get("outcomes", {}).get("5d")
            if out and out.get("return_pct") is not None:
                ret = out["return_pct"]
                buy_returns.append(ret)
                if ret >= _WIN_THRESHOLD_PCT:
                    buy_wins += 1
        if buy_returns:
            stats["buy_win_rate_5d"] = round(buy_wins / len(buy_returns), 3)
            stats["buy_avg_return_5d"] = round(sum(buy_returns) / len(buy_returns), 2)

        source_stats[source] = stats

    return source_stats


def _analyze_benchmark(records: list) -> dict:
    """SPY 벤치마크 대비 alpha 계산."""
    benchmark = {}
    buy_records = [r for r in records if r["signal"] in _BUY_SIGNALS]

    for eval_day in _EVAL_DAYS:
        eval_key = f"{eval_day}d"
        spy_key = f"spy_{eval_day}d"
        signal_returns = []
        spy_returns = []

        for r in buy_records:
            out = r.get("outcomes", {})
            sig_ret = out.get(eval_key, {}).get("return_pct") if isinstance(out.get(eval_key), dict) else None
            spy_ret = out.get(spy_key)
            if sig_ret is not None and spy_ret is not None:
                signal_returns.append(sig_ret)
                spy_returns.append(spy_ret)

        if signal_returns:
            avg_signal = round(sum(signal_returns) / len(signal_returns), 2)
            avg_spy = round(sum(spy_returns) / len(spy_returns), 2)
            benchmark[eval_key] = {
                "avg_signal": avg_signal,
                "avg_spy": avg_spy,
                "alpha": round(avg_signal - avg_spy, 2),
                "samples": len(signal_returns),
            }

    return benchmark


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
                "reason": f"샘플 {count}/{min_samples}건 -- 데이터 축적 중",
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
                "reason": f"승률 {win_rate:.0%} < 50% -- 조건 강화 검토 필요",
                "confidence": "medium" if count >= 30 else "low",
                "sample_size": count,
            })
        elif win_rate >= 0.7:
            recommendations.append({
                "param": f"{sig_type} conditions",
                "current_win_rate": win_rate,
                "avg_return": avg_return,
                "status": "good",
                "reason": f"승률 {win_rate:.0%} -- 현재 기준 유효",
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
                "suggestion": "RSI 임계값을 35~45 범위에서 미세 조정 검토",
                "confidence": "low",
                "sample_size": rsi_low["count"] + rsi_mid["count"],
            })

    return recommendations


def get_pending_signals(history: dict, scanner_histories: dict | None = None) -> list:
    """아직 평가할 수 없는 시그널 (거래일 기준 미달) 목록 반환."""
    pending = []
    today = datetime.now()
    # 거래일 기준 대기: 10거래일 ≈ 14캘린더일
    min_calendar_days = int(max(_EVAL_DAYS) * _CALENDAR_BUFFER)

    def _collect(hist, source):
        dates = sorted([k for k in hist.keys() if not k.startswith("_")])
        for date_str in dates:
            signal_date = datetime.strptime(date_str, "%Y-%m-%d")
            days_ago = (today - signal_date).days
            if days_ago >= min_calendar_days:
                continue
            day_data = hist[date_str]
            for ticker, info in day_data.items():
                if ticker.startswith("_") or not isinstance(info, dict):
                    continue
                signal = info.get("signal", "")
                if signal not in _TRACKABLE_SIGNALS:
                    continue
                # 남은 캘린더일 (거래일 아닌 근사치)
                remaining = max(0, min_calendar_days - days_ago)
                pending.append({
                    "date": date_str,
                    "ticker": ticker,
                    "signal": signal,
                    "source": source,
                    "price": info.get("price"),
                    "rsi": info.get("rsi"),
                    "days_until_eval": remaining,
                })

    _collect(history, "portfolio")
    if scanner_histories:
        for source_name, hist in scanner_histories.items():
            if hist:
                _collect(hist, source_name)

    pending.sort(key=lambda x: (x["date"], x["source"], x["ticker"]))
    return pending


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
