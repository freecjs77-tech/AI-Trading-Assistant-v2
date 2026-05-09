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


def passes_prefilter(stock_data: dict) -> bool:
    """
    Pre-filter (종목 게이트) — Top 2~3 섹터 종목만 본 스캔.

    ALL 통과 시 True:
      ① ret_3d_pct ≥ PREFILTER_3D_MIN_PCT (4.0%)
      ② close > ma20
      ③ rsi14 ≥ PREFILTER_RSI_MIN (55)
    """
    r3 = _safe_float(stock_data.get("ret_3d_pct"))
    rsi = _safe_float(stock_data.get("rsi14"))
    close = _safe_float(stock_data.get("close"))
    ma20 = _safe_float(stock_data.get("ma20"))
    if r3 is None or rsi is None or close is None or ma20 is None:
        return False
    return (
        r3 >= cfg.PREFILTER_3D_MIN_PCT
        and close > ma20
        and rsi >= cfg.PREFILTER_RSI_MIN
    )


def classify_stage(stock_data: dict) -> str | None:
    """
    M1/M2/M3 단계 판정 — 가장 높은 단계 반환.

    M1: ret_3d ≥ 8% AND rsi ≥ 60 AND close > ma20
    M2: M1 충족 AND (volume_ratio≥1.2, macd rising, close>ma50) 중 2개 이상
    M3: M2 충족 AND close ≥ high_52w × 0.99 AND rsi ≥ 65

    Returns: "MOMENTUM_3" | "MOMENTUM_2" | "MOMENTUM_1" | None
    """
    r3 = _safe_float(stock_data.get("ret_3d_pct"))
    rsi = _safe_float(stock_data.get("rsi14"))
    close = _safe_float(stock_data.get("close"))
    ma20 = _safe_float(stock_data.get("ma20"))
    ma50 = _safe_float(stock_data.get("ma50"))
    vol_ratio = _safe_float(stock_data.get("volume_ratio"), 0.0)
    macd_trend = stock_data.get("macd_hist_trend") or "flat"
    high_52w = _safe_float(stock_data.get("high_52w"))

    # M1
    if (r3 is None or rsi is None or close is None or ma20 is None
            or r3 < cfg.M1_3D_MIN_PCT
            or rsi < cfg.M1_RSI_MIN
            or close <= ma20):
        return None
    stage = "MOMENTUM_1"

    # M2 acceleration count (3개 중 2개)
    accel = 0
    if vol_ratio >= cfg.M2_VOLUME_RATIO_MIN:
        accel += 1
    if macd_trend == "rising":
        accel += 1
    if ma50 is not None and close > ma50:
        accel += 1
    if accel >= 2:
        stage = "MOMENTUM_2"

    # M3
    if (stage == "MOMENTUM_2"
            and high_52w is not None
            and close >= high_52w * cfg.M3_HIGH_52W_RATIO
            and rsi >= cfg.M3_RSI_MIN):
        stage = "MOMENTUM_3"

    return stage


def compute_risk_tags(stock_data: dict, stage: str) -> list[str]:
    """
    종목 risk tag 계산 (출력 전용 — 단계 영향 없음).

    🔴 OVERHEAT:  RSI ≥ 80
    🟠 PARABOLIC: change_pct ≥ +8%
    🟡 EXTENDED:  (close - ma20) / ma20 ≥ 0.10
    ⚪ EARLY:     stage == M1 AND 60 ≤ RSI < 65
    """
    tags: list[str] = []
    rsi = _safe_float(stock_data.get("rsi14"))
    chg = _safe_float(stock_data.get("change_pct"))
    close = _safe_float(stock_data.get("close"))
    ma20 = _safe_float(stock_data.get("ma20"))

    if rsi is not None and rsi >= cfg.RISK_OVERHEAT_RSI:
        tags.append("OVERHEAT")
    if chg is not None and chg >= cfg.RISK_PARABOLIC_PCT:
        tags.append("PARABOLIC")
    if close is not None and ma20 is not None and ma20 > 0:
        ext = (close - ma20) / ma20 * 100
        if ext >= cfg.RISK_EXTENDED_MA20_PCT:
            tags.append("EXTENDED")
    if (stage == "MOMENTUM_1" and rsi is not None
            and cfg.RISK_EARLY_RSI_MIN <= rsi < cfg.RISK_EARLY_RSI_MAX):
        tags.append("EARLY")
    return tags


def classify_maturity(stock_data: dict) -> str | None:
    """
    Maturity 분류 — EARLY / MID / EXTENDED 중 하나, 또는 None.

    EXTENDED 우선:  dist_ema9_pct >= 8% OR rsi14 >= 75
    EARLY:          dist_ema9_pct < 3% AND rsi14 < 68 AND ema9 > ema21
    MID:            그 외 (둘 다 아닌 경우)

    Returns None if dist_ema9_pct or rsi14 missing.
    """
    dist = _safe_float(stock_data.get("dist_ema9_pct"))
    rsi = _safe_float(stock_data.get("rsi14"))
    if dist is None or rsi is None:
        return None

    # EXTENDED first
    if dist >= cfg.MATURITY_EXT_DIST_PCT or rsi >= cfg.MATURITY_EXT_RSI:
        return "EXTENDED"

    # EARLY: all three required
    ema9 = _safe_float(stock_data.get("ema9"))
    ema21 = _safe_float(stock_data.get("ema21"))
    if (dist < cfg.MATURITY_EARLY_DIST_PCT
            and rsi < cfg.MATURITY_EARLY_RSI
            and ema9 is not None and ema21 is not None
            and ema9 > ema21):
        return "EARLY"

    return "MID"


def position_hint(risk_tags: list[str]) -> str:
    """
    Risk tag → 포지션 힌트 (한글).
    Priority: OVERHEAT > PARABOLIC > EXTENDED > EARLY > (none → "적극")
    """
    for tag in cfg.RISK_PRIORITY:
        if tag in risk_tags:
            return cfg.POSITION_HINT[tag]
    return cfg.POSITION_HINT[None]


def evaluate_stock(stock_data: dict, sector_5d_return: float | None = None) -> dict | None:
    """
    한 종목 종합 평가 — pre-filter는 caller가 사전 적용.

    Returns:
        None — M1 미달 (시그널 없음)
        dict — {ticker, stage, risk_tags, hint, rs_vs_sector, ...}
    """
    stage = classify_stage(stock_data)
    if stage is None:
        return None

    risk_tags = compute_risk_tags(stock_data, stage)
    hint = position_hint(risk_tags)

    rs_vs_sector = None
    stock_5d = _safe_float(stock_data.get("ret_5d_pct"))
    if stock_5d is not None and sector_5d_return is not None:
        rs_vs_sector = stock_5d > sector_5d_return

    return {
        "ticker": stock_data.get("ticker"),
        "stage": stage,
        "risk_tags": risk_tags,
        "hint": hint,
        "rs_vs_sector": rs_vs_sector,
        "sector": stock_data.get("sector"),
        "price": _safe_float(stock_data.get("close")),
        "rsi": _safe_float(stock_data.get("rsi14")),
        "ret_1d_pct": _safe_float(stock_data.get("change_pct")),
        "ret_3d_pct": _safe_float(stock_data.get("ret_3d_pct")),
        "ret_5d_pct": stock_5d,
    }
