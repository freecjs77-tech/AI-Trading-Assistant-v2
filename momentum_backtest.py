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
