# portfolio_stop_signal.py
"""
Portfolio Stop Signal — Stop 계산 + 4-state 시그널 평가.

본 모듈은 순수 함수 위주. I/O는 portfolio_stop_history.py가 담당.
generate_portfolio_stop_signals() entry point는 Task 5에서 추가.
"""

from __future__ import annotations

from portfolio_stop_config import (
    DEFAULT_MODE, CATEGORY_TO_MODE, HIGH_VOL_KEYWORDS, MODE_OVERRIDES,
    STOP_PARAMS, TIGHT_RATIO, EXIT_BELOW_STOP_DAYS,
    NEW_POSITION_DISPLAY_DOWNGRADE,
)
from portfolio_data import is_korean_ticker


# ─── Mode 결정 (3-tier 우선순위) ──────────────────────────

def get_stop_mode(ticker: str, name: str | None, category: str | None) -> str:
    """Override > keyword > category → MOMENTUM default."""
    if ticker in MODE_OVERRIDES:
        return MODE_OVERRIDES[ticker]
    nm = name or ""
    for kw in HIGH_VOL_KEYWORDS:
        if kw in nm:
            return "HIGH_VOL"
    return CATEGORY_TO_MODE.get(category or "Other", DEFAULT_MODE)


# ─── 시장별 호가 단위 라운딩 ─────────────────────────────

def round_stop(price: float, ticker: str) -> float:
    """KR=정수, US=소수 2자리. portfolio_data.is_korean_ticker 재사용."""
    if is_korean_ticker(ticker):
        return float(round(price))
    return round(price, 2)


# ─── Stop 계산 ─────────────────────────────────────────────

def calculate_stop(highest_close: float, atr14: float | None,
                   mode: str, ticker: str) -> float:
    """4개 mode 공식 + min/max% 양방향 clamp + market-aware rounding."""
    p = STOP_PARAMS[mode]
    if p["type"] == "pct":
        return round_stop(highest_close * p["ratio"], ticker)
    # ATR 기반
    if atr14 is None or atr14 <= 0:
        # ATR fail → min_pct percentage fallback
        return round_stop(highest_close * (1.0 - p["min_pct"]), ticker)
    atr_distance = atr14 * p["multiplier"]
    min_distance = highest_close * p["min_pct"]
    max_distance = highest_close * p["max_pct"]
    distance = max(atr_distance, min_distance)
    distance = min(distance, max_distance)
    return round_stop(highest_close - distance, ticker)


# ─── 4-state 시그널 평가 ────────────────────────────────────

ACTION_MAP = {
    "HOLD":       "Hold",
    "TIGHT":      "Trim 10~15%",
    "EXIT_READY": "Trim 30~50%",
    "EXIT":       "Exit trading portion",
}


def _compute_raw_signal(today_close: float, stop_price: float,
                        new_below_count: int) -> str:
    """우선순위: EXIT > EXIT_READY > TIGHT > HOLD."""
    if new_below_count >= EXIT_BELOW_STOP_DAYS:
        return "EXIT"
    if new_below_count >= 1:
        return "EXIT_READY"
    if today_close <= stop_price * TIGHT_RATIO:
        return "TIGHT"
    return "HOLD"


def evaluate_signal(today_close: float, stop_price: float,
                    prev_below_count: int, is_new_position: bool) -> dict:
    """Daily 시그널 평가 — raw / display 분리.

    반환:
      raw_signal: 데이터 레이어 진실값 (positions/snapshots 저장용)
      display_signal: UI/Telegram 표시용 (신규 종목 다운그레이드 적용)
      display_downgraded: bool — 다운그레이드 여부 (분석/디버깅)
      below_stop_count: 갱신된 카운터
    """
    # `<=` — 정확히 stop 찍은 날도 하회 인정
    if today_close <= stop_price:
        new_count = prev_below_count + 1
    else:
        new_count = 0  # 회복 시 리셋 (비연속 누적 안 함)

    raw = _compute_raw_signal(today_close, stop_price, new_count)

    # Display 다운그레이드 — raw는 그대로, UI/Telegram만 톤 다운
    if (NEW_POSITION_DISPLAY_DOWNGRADE
            and is_new_position
            and raw in ("EXIT_READY", "EXIT")):
        display = "TIGHT"
        downgraded = True
    else:
        display = raw
        downgraded = False

    return {
        "raw_signal": raw,
        "display_signal": display,
        "display_downgraded": downgraded,
        "below_stop_count": new_count,
        "action": ACTION_MAP[raw],
        "display_action": ACTION_MAP[display],
    }
