"""
Market Momentum Scanner — Leg-based backtest.

Leg 정의:
  각 (ticker, stage) 진입 = 1 leg.
  - NEW M1 → leg start
  - UPGRADE → 새 leg start (이전 leg 종료, exit_reason="UPGRADE")
  - DOWNGRADE → 새 leg start (이전 leg 종료, exit_reason="DOWNGRADE")
  - EXIT → 현 leg 종료 (exit_reason="EXIT")
  - 진행 중인 leg → exit_date/exit_price = None
"""
import sys
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import momentum_config as cfg


def extract_legs(history: dict) -> list[dict]:
    """
    momentum_history.json → list of leg dicts.

    Leg schema:
      {ticker, stage, entry_date, entry_price, entry_context,
       exit_date | None, exit_price | None, exit_reason,
       duration_days}
    """
    legs: list[dict] = []
    data = history.get("data", {})
    for ticker, ticker_data in data.items():
        sorted_dates = sorted(ticker_data.keys())
        cur_leg = None
        for d in sorted_dates:
            entry = ticker_data[d]
            change = entry.get("change")
            stage = entry.get("stage")

            if change in ("NEW", "UPGRADE", "DOWNGRADE"):
                if cur_leg is not None:
                    cur_leg["exit_date"] = d
                    cur_leg["exit_price"] = entry.get("price")
                    cur_leg["exit_reason"] = change
                    cur_leg["duration_days"] = _days_between(cur_leg["entry_date"], d)
                    legs.append(cur_leg)
                cur_leg = {
                    "ticker": ticker, "stage": stage,
                    "entry_date": d, "entry_price": entry.get("price"),
                    "entry_context": entry.get("entry_context", {}),
                    "exit_date": None, "exit_price": None,
                    "exit_reason": None, "duration_days": None,
                }
            elif change == "HOLD":
                continue
            elif change == "EXIT":
                if cur_leg is not None:
                    cur_leg["exit_date"] = d
                    cur_leg["exit_price"] = entry.get("exit_price") or entry.get("price")
                    cur_leg["exit_reason"] = entry.get("exit_reason", "EXIT")
                    cur_leg["duration_days"] = _days_between(cur_leg["entry_date"], d)
                    legs.append(cur_leg)
                    cur_leg = None
        if cur_leg is not None:
            cur_leg["duration_days"] = _days_between(
                cur_leg["entry_date"], sorted_dates[-1] if sorted_dates else cur_leg["entry_date"]
            )
            legs.append(cur_leg)
    return legs


def _days_between(d1: str, d2: str) -> int:
    try:
        a = datetime.strptime(d1, "%Y-%m-%d")
        b = datetime.strptime(d2, "%Y-%m-%d")
        return (b - a).days
    except ValueError:
        return 0


def compute_leg_returns(leg: dict, closes: list[float],
                        highs: list[float] | None = None,
                        lows: list[float] | None = None) -> dict:
    """
    leg에 +3d/+5d/+10d 누적 수익률, max_ret, min_ret, mdd 추가.

    closes/highs/lows: entry_date 다음 거래일부터의 OHLC 시퀀스
                      (closes[0] = entry +1d 종가, closes[-1] = exit 직전).
    intraday 데이터 없으면 close 사용.
    """
    enriched = dict(leg)
    entry = leg.get("entry_price")
    if entry is None or not closes:
        for k in ("ret_3d_pct", "ret_5d_pct", "ret_10d_pct",
                  "max_ret_pct", "min_ret_pct", "mdd_pct"):
            enriched[k] = None
        return enriched

    if highs is None:
        highs = closes
    if lows is None:
        lows = closes

    def _ret(periods: int):
        if len(closes) <= periods:
            return None
        v = closes[periods]
        if v is None or entry == 0:
            return None
        return round((v / entry - 1) * 100, 2)

    enriched["ret_3d_pct"] = _ret(3)
    enriched["ret_5d_pct"] = _ret(5)
    enriched["ret_10d_pct"] = _ret(10)

    valid_h = [v for v in highs if v is not None]
    valid_l = [v for v in lows if v is not None]
    if valid_h:
        enriched["max_ret_pct"] = round((max(valid_h) / entry - 1) * 100, 2)
    else:
        enriched["max_ret_pct"] = None
    if valid_l:
        enriched["min_ret_pct"] = round((min(valid_l) / entry - 1) * 100, 2)
    else:
        enriched["min_ret_pct"] = None

    # MDD: peak-to-trough 가장 큰 낙폭
    if valid_h and valid_l:
        running_peak = -float("inf")
        worst_dd = 0.0
        for h, l in zip(highs, lows):
            if h is not None:
                running_peak = max(running_peak, h)
            if l is not None and running_peak > -float("inf") and running_peak > 0:
                dd = (l - running_peak) / running_peak * 100
                if dd < worst_dd:
                    worst_dd = dd
        enriched["mdd_pct"] = round(worst_dd, 2)
    else:
        enriched["mdd_pct"] = None
    return enriched


def _safe_avg(values: list[float | None]) -> float | None:
    """리스트의 None 제외 평균."""
    vs = [v for v in values if v is not None]
    if not vs:
        return None
    return round(sum(vs) / len(vs), 2)


def _win_rate(values: list[float | None], threshold: float = 0.0) -> float | None:
    """threshold 초과 비율 (백분율)."""
    vs = [v for v in values if v is not None]
    if not vs:
        return None
    wins = sum(1 for v in vs if v > threshold)
    return round(wins / len(vs) * 100, 1)


def aggregate(legs: list[dict], as_of: str) -> dict:
    """
    Leg 리스트 → stage/streak 별 집계 + 연속 손실 alert.

    Returns: {as_of, version, by_stage, by_streak, alerts}
    """
    # by_stage 집계
    by_stage: dict[str, dict] = {}
    for stage in ("EM", "MOMENTUM_1", "MOMENTUM_2", "MOMENTUM_3"):
        s_legs = [L for L in legs if L.get("stage") == stage]
        if not s_legs:
            continue
        by_stage[stage] = {
            "leg_count": len(s_legs),
            "win_rate_5d_pct": _win_rate([L.get("ret_5d_pct") for L in s_legs]),
            "avg_ret_3d_pct": _safe_avg([L.get("ret_3d_pct") for L in s_legs]),
            "avg_ret_5d_pct": _safe_avg([L.get("ret_5d_pct") for L in s_legs]),
            "avg_ret_10d_pct": _safe_avg([L.get("ret_10d_pct") for L in s_legs]),
            "avg_max_ret_pct": _safe_avg([L.get("max_ret_pct") for L in s_legs]),
            "avg_min_ret_pct": _safe_avg([L.get("min_ret_pct") for L in s_legs]),
            "avg_mdd_pct": _safe_avg([L.get("mdd_pct") for L in s_legs]),
            "avg_duration_days": _safe_avg([float(L.get("duration_days") or 0)
                                            for L in s_legs]),
        }
        if stage == "EM":
            # transition_to_M1_pct counts ANY upgrade out of EM (to M1, M2, or M3) —
            # EM is the lowest RANK, so any UPGRADE exit_reason qualifies.
            closed = [L for L in s_legs if L.get("exit_reason") is not None]
            upgraded = [L for L in closed if L.get("exit_reason") == "UPGRADE"]
            if closed:
                by_stage[stage]["transition_to_M1_pct"] = round(
                    len(upgraded) / len(closed) * 100, 1)
            else:
                by_stage[stage]["transition_to_M1_pct"] = None

    # by_streak 집계 (1, 2, 3+)
    by_streak: dict[str, dict] = {}
    streak_groups = {"1": [], "2": [], "3+": []}
    for L in legs:
        s = (L.get("entry_context") or {}).get("streak", 1)
        if s == 1:
            streak_groups["1"].append(L)
        elif s == 2:
            streak_groups["2"].append(L)
        else:
            streak_groups["3+"].append(L)
    for k, group in streak_groups.items():
        if not group:
            continue
        by_streak[k] = {
            "leg_count": len(group),
            "avg_ret_5d": _safe_avg([L.get("ret_5d_pct") for L in group]),
            "win_rate_pct": _win_rate([L.get("ret_5d_pct") for L in group]),
        }

    # 연속 손실 alert: 최근 5개 leg (exit_date 기준 정렬)
    completed_sorted = sorted(
        [L for L in legs if L.get("exit_date")],
        key=lambda L: L.get("exit_date", "")
    )
    recent5 = completed_sorted[-5:]
    loss_count = sum(1 for L in recent5
                     if L.get("ret_5d_pct") is not None and L["ret_5d_pct"] < 0)

    return {
        "as_of": as_of,
        "version": cfg.VERSION,
        "by_stage": by_stage,
        "by_streak": by_streak,
        "alerts": {
            "consecutive_loss_warning": loss_count >= cfg.CONSECUTIVE_LOSS_THRESHOLD,
            "recent_5_legs_loss_count": loss_count,
        },
    }
