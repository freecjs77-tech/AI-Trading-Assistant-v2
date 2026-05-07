"""
Market Momentum Scanner — Signal logic.

This module computes Sector Momentum + (Pre-filter, M1/M2/M3, Risk tags)
in subsequent tasks. Task 9 covers Sector only.
"""
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import momentum_config as cfg


def _safe_float(x, default=None):
    try:
        if x is None:
            return default
        f = float(x)
        return f if f == f else default
    except (TypeError, ValueError):
        return default


def evaluate_sector(sector_data: dict,
                    market_5d: float,
                    peer_20d_returns: list[float]) -> dict:
    """
    한 섹터 ETF의 모멘텀 평가.

    필수 (ALL met):
      ① ret_5d ≥ SECTOR_5D_MIN_PCT   (3.0%)
      ② close > ma20
      ③ rsi14 ≥ SECTOR_RSI_MIN       (55)
      게이트: sector_5d > market_5d   (RS)

    가속 (4 중 충족 개수):
      ④ close ≥ max(high_20d, high_52w * SECTOR_HIGH_52W_RATIO)
      ⑤ macd_hist_trend == "rising"
      ⑥ volume_ratio ≥ SECTOR_VOLUME_RATIO_MIN
      ⑦ ret_20d 상위 50% (peer_20d_returns 중)

    Score:
      trend_score    = 40   (필수 ALL 시 고정)
      momentum_score = accel_count × 10   (0~40)
      rs_score       = min(20, max(0, (sector_5d - market_5d) × SECTOR_RS_SCALE))
    """
    ret_5d = _safe_float(sector_data.get("ret_5d_pct"))
    rsi = _safe_float(sector_data.get("rsi14"))
    close = _safe_float(sector_data.get("close"))
    ma20 = _safe_float(sector_data.get("ma20"))
    high_20d = _safe_float(sector_data.get("high_20d"))
    high_52w = _safe_float(sector_data.get("high_52w"))
    vol_ratio = _safe_float(sector_data.get("volume_ratio"), 0.0)
    macd_trend = sector_data.get("macd_hist_trend") or "flat"
    ret_20d = _safe_float(sector_data.get("ret_20d_pct"))

    # ── RS gate first
    if ret_5d is None or ret_5d <= market_5d:
        return {"ticker": sector_data.get("ticker"),
                "passes_required": False, "fail_reason": "rs_below_market",
                "score": 0, "accel_count": 0, "rs_score": 0,
                "ret_5d_pct": ret_5d}

    # ── Required (ALL)
    req_pass = (
        ret_5d is not None and ret_5d >= cfg.SECTOR_5D_MIN_PCT and
        close is not None and ma20 is not None and close > ma20 and
        rsi is not None and rsi >= cfg.SECTOR_RSI_MIN
    )
    if not req_pass:
        return {"ticker": sector_data.get("ticker"),
                "passes_required": False, "fail_reason": "required_gate",
                "score": 0, "accel_count": 0, "rs_score": 0,
                "ret_5d_pct": ret_5d}

    # ── Acceleration count
    accel = 0
    # ④ 신고가 근접
    if close is not None and high_20d is not None and high_52w is not None:
        threshold = max(high_20d, high_52w * cfg.SECTOR_HIGH_52W_RATIO)
        if close >= threshold:
            accel += 1
    # ⑤ MACD hist 상승
    if macd_trend == "rising":
        accel += 1
    # ⑥ 거래량 비율
    if vol_ratio >= cfg.SECTOR_VOLUME_RATIO_MIN:
        accel += 1
    # ⑦ 20d return 상위 50%
    if ret_20d is not None and peer_20d_returns:
        sorted_rets = sorted(peer_20d_returns, reverse=True)
        median = sorted_rets[len(sorted_rets) // 2]
        if ret_20d >= median:
            accel += 1

    # ── Scores
    trend_score = 40
    momentum_score = accel * 10
    diff = ret_5d - market_5d
    rs_score = max(0, min(20, int(round(diff * cfg.SECTOR_RS_SCALE))))
    total = trend_score + momentum_score + rs_score

    return {
        "ticker": sector_data.get("ticker"),
        "passes_required": True,
        "score": total,
        "trend_score": trend_score,
        "momentum_score": momentum_score,
        "accel_count": accel,
        "rs_score": rs_score,
        "ret_5d_pct": ret_5d,
    }


def select_top_sectors(evaluated: list[dict], n: int = None) -> list[dict]:
    """필수 통과 섹터 중 score 내림차순. 동점 시 ret_5d_pct 큰 순. Top N."""
    if n is None:
        n = cfg.SECTOR_TOP_N
    passing = [s for s in evaluated if s.get("passes_required")]
    passing.sort(key=lambda s: (-s["score"], -s.get("ret_5d_pct", 0)))
    return passing[:n]
