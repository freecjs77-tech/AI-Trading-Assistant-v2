"""
signal_judge.py — 시그널 판정 엔진
AI Trading Assistant v3.0

strategy.md v5.2 규칙을 Python으로 구현.
v5.2 변경사항:
  - Exit을 익절 전용으로 재설계 (고점 영역 게이트)
  - L3_BREAKDOWN → TAKE_PROFIT_2 (상승 종료, 대량 익절)
  - L2_WEAKENING → TAKE_PROFIT_1 (상승 둔화, 1차 익절)
  - Drawdown 기반 손절 조건 완전 삭제
  - MACD 데스크로스: MACD < 0 조건 삭제 (조기 감지)
  - 고점 게이트: DD > -5% 일 때만 익절 시그널 허용
"""
from __future__ import annotations

import json
import os

from portfolio_data import (
    STRATEGY_GROUP, get_strategy_group,
    get_ticker_name, get_ticker_class,
)


# ═══════════════════════════════════════════════════════
#  파라미터 로드 (strategy_params.json)
# ═══════════════════════════════════════════════════════

_PARAMS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategy_params.json")

def _load_params() -> dict:
    """strategy_params.json 로드. 파일 없으면 빈 dict 반환 (하드코딩 폴백)."""
    try:
        with open(_PARAMS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

PARAMS = _load_params()

def _p(path: str, default):
    """PARAMS에서 dot-separated 경로로 값 조회. 예: _p("top_signal.rsi", 75)"""
    keys = path.split(".")
    obj = PARAMS
    for k in keys:
        if isinstance(obj, dict) and k in obj:
            obj = obj[k]
        else:
            return default
    return obj


# ═══════════════════════════════════════════════════════
#  고점 영역 게이트 (v5.2)
# ═══════════════════════════════════════════════════════

def _is_profit_zone(d: dict) -> bool:
    """고점 영역 게이트: 최근 고점 대비 -5% 이내일 때만 익절 시그널 허용.
    이미 많이 하락한 상태에서는 Exit 발동하지 않음 → HOLD로 버팀."""
    dd = d.get("drawdown_20d_pct", 0)
    return dd > _p("profit_zone_gate.dd_threshold", -5.0)


# ═══════════════════════════════════════════════════════
#  MACD 상승 가드
# ═══════════════════════════════════════════════════════

def _is_macd_bullish(d: dict) -> bool:
    """MACD > signal(골든크로스) AND hist 증가 → 모멘텀 회복 중"""
    macd = d.get("macd")
    macd_signal = d.get("macd_signal")
    if macd is None or macd_signal is None:
        return False
    return macd > macd_signal and "increasing" in d.get("macd_hist_trend", "")


# ═══════════════════════════════════════════════════════
#  EXIT 판정 (모든 종목 공통, 우선순위 TOP → L3 → L2)
# ═══════════════════════════════════════════════════════

def _check_top_signal(d: dict, prev_day: dict | None = None) -> tuple[bool, list]:
    """TOP_SIGNAL — 과열 경보. 3개 중 2개 충족 시 발동."""
    conditions = []
    rsi = d.get("rsi14")
    bb_pct = d.get("bb_pct")
    change_3d = _calc_3d_change(d)
    _top_rsi = _p("top_signal.rsi", 75)

    if rsi is not None and rsi >= _top_rsi:
        conditions.append(("ok", f"RSI >= {_top_rsi}", f"RSI {rsi:.1f} — 과열 구간이에요"))
    elif rsi is not None:
        conditions.append(("no", f"RSI >= {_top_rsi}", f"RSI {rsi:.1f} — 아직 {_top_rsi} 미만이에요"))
    else:
        conditions.append(("no", f"RSI >= {_top_rsi}", "RSI 데이터가 없어요"))

    # BB 상단 2일 연속 마감 (bb_pct > 상단 = 상단 초과)
    _top_bb = _p("top_signal.bb_upper", 100)
    bb_above_today = bb_pct is not None and bb_pct > _top_bb
    if prev_day and prev_day.get("bb_pct") is not None:
        bb_above_yesterday = prev_day["bb_pct"] > _top_bb
        if bb_above_today and bb_above_yesterday:
            conditions.append(("ok", "BB 상단 2일 연속", f"오늘 {bb_pct:.1f}%, 전일 {prev_day['bb_pct']:.1f}% — 연속 돌파했어요"))
        else:
            conditions.append(("no", "BB 상단 2일 연속", f"오늘 {bb_pct:.1f}%, 전일 {prev_day['bb_pct']:.1f}% — 2일 연속이 아니에요"))
    elif bb_pct is not None:
        conditions.append(("no", "BB 상단 2일 연속", f"오늘 {bb_pct:.1f}% — 전일 이력이 없어요"))
    else:
        conditions.append(("no", "BB 상단 2일 연속", "BB 데이터가 없어요"))

    _top_chg = _p("top_signal.change_3d_pct", 10)
    if change_3d is not None and change_3d >= _top_chg:
        conditions.append(("ok", f"3일 누적 >= +{_top_chg}%", f"3일 변동 {change_3d:+.1f}% — 급등했어요"))
    elif change_3d is not None:
        conditions.append(("no", f"3일 누적 >= +{_top_chg}%", f"3일 변동 {change_3d:+.1f}% — {_top_chg}% 미만이에요"))
    else:
        conditions.append(("no", f"3일 누적 >= +{_top_chg}%", "3일 변동 데이터가 없어요"))

    _top_min = _p("top_signal.min_count", 2)
    triggered = sum(1 for c in conditions if c[0] == "ok") >= _top_min
    return triggered, conditions


def _check_take_profit_2(d: dict, prev_day: dict | None) -> tuple[bool, list]:
    """TAKE_PROFIT_2 — 상승 종료 신호 (대량 익절). 고점 게이트 + MACD 가드 통과 후 1개 충족."""
    conditions = []
    macd_hist_trend = d.get("macd_hist_trend", "")
    macd = d.get("macd")
    macd_signal = d.get("macd_signal")
    bullish = _is_macd_bullish(d)
    hist_recovering = "increasing" in macd_hist_trend

    # ① MA20 이탈 2일 + MACD hist 감소  [v5.2: DD조건 삭제]
    ma20_below_2d = _check_ma20_below_2d(d, prev_day)
    macd_decreasing = "decreasing" in macd_hist_trend

    if bullish or hist_recovering:
        conditions.append(("no", "MA20 이탈 2일 + MACD hist 감소",
                           f"{'MACD 골든크로스' if bullish else 'hist 회복 중'} — 면제돼요"))
    elif ma20_below_2d and macd_decreasing:
        conditions.append(("ok", "MA20 이탈 2일 + MACD hist 감소",
                           "MA20 아래 2일 연속 + hist 감소 — 하락 전환이에요"))
    else:
        if not ma20_below_2d:
            conditions.append(("no", "MA20 이탈 2일 + MACD hist 감소",
                               "MA20 이탈 2일 연속이 아니에요"))
        else:
            conditions.append(("no", "MA20 이탈 2일 + MACD hist 감소",
                               "MA20 이탈 2일이지만 MACD hist가 감소하지 않아요"))

    # ② Higher Low 하향 돌파  [bullish/hist회복 시 면제]
    if bullish or hist_recovering:
        conditions.append(("no", "Higher Low 하향 돌파",
                           f"{'MACD 골든크로스' if bullish else 'hist 회복 중'} — 면제돼요"))
    else:
        price = d.get("price", 0)
        dbl = d.get("double_bottom", {})
        if isinstance(dbl, dict) and dbl.get("low1") and dbl.get("low2"):
            low1_p = dbl["low1"]["price"]
            low2_p = dbl["low2"]["price"]
            was_higher_low = low2_p > low1_p
            price_broke = price < low2_p
            if was_higher_low and price_broke:
                conditions.append(("ok", "Higher Low 하향 돌파",
                    f"현재가 ${price:.2f} < 저점2 ${low2_p:.2f}({dbl['low2']['date']}) — 지지선이 무너졌어요"))
            elif was_higher_low:
                conditions.append(("no", "Higher Low 하향 돌파",
                    f"현재가 ${price:.2f} > 저점2 ${low2_p:.2f} — 지지선 위에 있어요"))
            else:
                conditions.append(("no", "Higher Low 하향 돌파",
                    f"저점2 ${low2_p:.2f} ≤ 저점1 ${low1_p:.2f} — Higher Low가 아니에요"))
        else:
            conditions.append(("na", "Higher Low 하향 돌파", "저점 데이터가 부족해요"))

    # ③ MACD 데스크로스 + hist 3일 감소  [v5.2: MACD < 0 조건 삭제 → 조기 감지]
    if macd is not None and macd_signal is not None:
        macd_below_signal = macd < macd_signal
        hist_3d_decreasing = "decreasing" in macd_hist_trend
        if macd_below_signal and hist_3d_decreasing:
            conditions.append(("ok", "MACD 데스크로스 + hist 3일 감소",
                               f"MACD {macd:.4f} < signal {macd_signal:.4f} + hist 감소 — 하락 전환이에요"))
        else:
            reason_parts = []
            if not macd_below_signal:
                reason_parts.append(f"MACD {macd:.4f} > signal {macd_signal:.4f}")
            if not hist_3d_decreasing:
                reason_parts.append(f"hist 추세 '{macd_hist_trend}'")
            conditions.append(("no", "MACD 데스크로스 + hist 3일 감소",
                               f"{', '.join(reason_parts)} — 조건 미충족이에요"))
    else:
        conditions.append(("na", "MACD 데스크로스 + hist 3일 감소", "MACD 데이터가 없어요"))

    triggered = any(c[0] == "ok" for c in conditions)
    return triggered, conditions


def _check_take_profit_1(d: dict, prev_day: dict | None) -> tuple[bool, list]:
    """TAKE_PROFIT_1 — 상승 둔화 (1차 익절). 3개 중 2개 충족. MACD 가드 적용."""
    macd_hist_trend_l2 = d.get("macd_hist_trend", "")
    hist_recovering_l2 = "increasing" in macd_hist_trend_l2
    if _is_macd_bullish(d):
        return False, [("no", "MACD 상승 가드", "MACD 골든크로스 + hist 증가 — 모멘텀 회복 중이라 TP1 면제돼요")]
    if hist_recovering_l2:
        return False, [("no", "MACD 상승 가드", f"MACD hist 회복 중 ({macd_hist_trend_l2}) — 하락 둔화라 TP1 면제돼요")]

    conditions = []
    count = 0
    macd_hist_trend = d.get("macd_hist_trend", "")
    price_vs_ma20 = d.get("price_vs_ma20", "")
    rsi = d.get("rsi14")

    # ① MACD 히스토그램 3일 연속 감소
    if "decreasing" in macd_hist_trend:
        conditions.append(("ok", "MACD hist 3일 감소", f"추세 '{macd_hist_trend}' — 모멘텀이 약해지고 있어요"))
        count += 1
    else:
        conditions.append(("no", "MACD hist 3일 감소", f"추세 '{macd_hist_trend}' — 아직 3일 연속 감소가 아니에요"))

    # ② RSI 다이버전스: 전일 RSI > 금일 RSI, 둘 다 ≥floor (고점 영역 하락)  [v5.1 신규]
    _tp1_rsi_floor = _p("take_profit_1.rsi_divergence_floor", 50)
    if prev_day and rsi is not None:
        prev_rsi = prev_day.get("rsi")
        if prev_rsi is not None and prev_rsi > rsi and prev_rsi >= _tp1_rsi_floor and rsi >= _tp1_rsi_floor:
            conditions.append(("ok", "RSI 다이버전스", f"전일 {prev_rsi:.1f} → 오늘 {rsi:.1f} — 고점에서 하락 중이에요"))
            count += 1
        elif prev_rsi is not None:
            conditions.append(("no", "RSI 다이버전스", f"전일 {prev_rsi:.1f} → 오늘 {rsi:.1f} — 다이버전스 조건 미충족이에요"))
        else:
            conditions.append(("no", "RSI 다이버전스", "전일 RSI 데이터가 없어요"))
    else:
        conditions.append(("na", "RSI 다이버전스", "전일 이력이 없어요"))

    # ③ 종가 MA20 1일 이탈
    if price_vs_ma20 == "below":
        conditions.append(("ok", "종가 < MA20", "MA20 아래로 내려왔어요"))
        count += 1
    else:
        conditions.append(("no", "종가 < MA20", "아직 MA20 위에 있어요"))

    triggered = count >= _p("take_profit_1.min_count", 2)
    return triggered, conditions


# ═══════════════════════════════════════════════════════
#  ENTRY 판정 — Growth v2.3 (v5.1 개선)
# ═══════════════════════════════════════════════════════

def _check_entry_growth(d: dict, reject_rsi_threshold: float = 55, skip_volume: bool = False) -> tuple[str | None, list]:
    """Growth 종목 Entry 판정. 3rd → 2nd → 1st → WATCH 순.
    reject_rsi_threshold: 거부 RSI 임계값 (Growth=55, Value=70)
    skip_volume: True이면 거래량 조건 면제 (BUY 2일차 확인용)"""
    rsi = d.get("rsi14")
    adx = d.get("adx")
    bb_pct = d.get("bb_pct")
    bb_lower = d.get("bb_lower")
    price = d.get("price", 0)
    ma20 = d.get("ma20")
    macd_hist_trend = d.get("macd_hist_trend", "")
    macd_hist_3d = d.get("macd_hist_3d", [])
    macd = d.get("macd")
    macd_signal = d.get("macd_signal")
    volume_ratio = d.get("volume_ratio")
    change_pct = d.get("change_pct", 0)
    price_vs_ma20 = d.get("price_vs_ma20", "")

    conditions = []

    # [v5.1b] 당일 급락 거부 — 전 단계 적용
    _g = PARAMS.get("entry_growth", {})
    reject_drop = change_pct <= _p("entry_growth.reject_drop_pct", -5.0)
    if reject_drop:
        conditions.append(("no", "[거부] 당일 급락", f"당일 {change_pct:+.1f}% — 5% 이상 급락이라 매수 금지예요"))
        return _growth_watch_fallback(d, conditions)

    # ── 3rd BUY (50%) — ALL 충족 (RSI 거부 미적용 — 추세 확정 단계) ──
    c3 = []
    above_ma20_2d = price_vs_ma20 == "above"
    c3.append(("ok" if above_ma20_2d else "no",
               "가격 > MA20",
               f"MA20 {'위에 있어요' if above_ma20_2d else '아래에 있어요'}"))
    macd_above_zero = macd is not None and macd > 0
    macd_golden_c3 = macd is not None and macd_signal is not None and macd > macd_signal
    macd_c3_ok = macd_above_zero and macd_golden_c3
    if macd is not None and macd_signal is not None:
        c3.append(("ok" if macd_c3_ok else "no",
                   "MACD > 0 + 골든크로스",
                   f"MACD {macd:.4f} {'>' if macd_above_zero else '<'} 0, {'>' if macd_golden_c3 else '<'} signal {macd_signal:.4f}"))
    else:
        c3.append(("no", "MACD > 0 + 골든크로스", "MACD 데이터가 없어요"))
    _g3_vol = _p("entry_growth.3rd_buy.volume_ratio", 1.5)
    vol_13 = volume_ratio is not None and volume_ratio >= _g3_vol
    if skip_volume:
        c3.append(("ok", f"거래량비 >= {_g3_vol}x",
                   f"거래량비 {volume_ratio:.2f}x — BUY 2일차 면제예요" if volume_ratio else "거래량 데이터 없음 — BUY 2일차 면제예요"))
    elif volume_ratio is not None:
        c3.append(("ok" if vol_13 else "no",
                   f"거래량비 >= {_g3_vol}x",
                   f"거래량비 {volume_ratio:.2f}x — {'평소보다 많아요' if vol_13 else '아직 부족해요'}"))
    else:
        c3.append(("no", f"거래량비 >= {_g3_vol}x", "거래량 데이터가 없어요"))
    _g3_rsi = _p("entry_growth.3rd_buy.rsi_min", 55)
    rsi_above_55 = rsi is not None and rsi > _g3_rsi
    if rsi is not None:
        c3.append(("ok" if rsi_above_55 else "no",
                   f"RSI > {_g3_rsi}",
                   f"RSI {rsi:.1f} — {'추세 확인이에요' if rsi_above_55 else f'아직 {_g3_rsi} 이하예요'}"))
    else:
        c3.append(("no", f"RSI > {_g3_rsi}", "RSI 데이터가 없어요"))
    # 3rd BUY 추가 거부: RSI > reject
    _g3_reject = _p("entry_growth.3rd_buy.rsi_reject", 75)
    if rsi is not None and rsi > _g3_reject:
        c3.append(("no", f"[거부] RSI > {_g3_reject}", f"RSI {rsi:.1f} — 과열 구간이라 3차 매수 금지예요"))

    # 3rd BUY 추가 거부: MACD hist 2일 감속 (v5.3e momentum quality)
    _g3_hist_filter = _p("entry_growth.3rd_buy.reject_decreasing_hist", True)
    hist_decel = _g3_hist_filter and macd_hist_trend == "decreasing_2d"
    if hist_decel:
        c3.append(("no", "[거부] MACD hist 2일 감속",
                   "MACD hist 2일 연속 감소 — 추세 둔화로 3차 매수 보류예요"))

    if all(c[0] == "ok" for c in c3) and not (rsi and rsi > _g3_reject) and not hist_decel:
        return "3rd_BUY", c3

    # ── 2nd BUY — ALL 충족  [v5.3d: MA20 돌파 확인 단계. 이중바닥→MA20 교체] ──
    c2 = []
    # ① MA20 돌파 확인 (반등이 실제 추세 전환임을 확인)
    above_ma20_2nd = price_vs_ma20 == "above"
    c2.append(("ok" if above_ma20_2nd else "no",
               "가격 > MA20 (돌파 확인)",
               f"MA20 {'위에 있어요 — 추세 전환 확인이에요' if above_ma20_2nd else '아래에 있어요 — 아직 MA20 돌파 전이에요'}"))
    # ② RSI > 40 (과매도 충분히 벗어남, 과열 아님)
    _g2_rsi = _p("entry_growth.2nd_buy.rsi_recovery", 40)
    rsi_mid = rsi is not None and rsi > _g2_rsi
    if rsi is not None:
        c2.append(("ok" if rsi_mid else "no",
                   f"RSI > {_g2_rsi}",
                   f"RSI {rsi:.1f} — {'회복 구간이에요' if rsi_mid else '아직 회복 전이에요'}"))
    else:
        c2.append(("no", f"RSI > {_g2_rsi}", "RSI 데이터가 없어요"))
    # ③ MACD 골든크로스 + hist 2일 증가 (페이크아웃 방지)
    macd_golden = macd is not None and macd_signal is not None and macd > macd_signal
    hist_inc_2nd = "increasing" in macd_hist_trend
    macd_2nd_ok = macd_golden and hist_inc_2nd
    if macd is not None and macd_signal is not None:
        c2.append(("ok" if macd_2nd_ok else "no",
                   "MACD 골든크로스 + hist 2일 증가",
                   f"MACD {macd:.4f} {'>' if macd_golden else '<'} signal {macd_signal:.4f}, "
                   f"hist {'증가중이에요' if hist_inc_2nd else '증가 미확인이에요'}"))
    else:
        c2.append(("no", "MACD 골든크로스 + hist 2일 증가", "MACD 데이터가 없어요"))
    # ④ 거래량 ≥ 1.5x
    _g2_vol = _p("entry_growth.2nd_buy.volume_ratio", 1.5)
    vol_12 = volume_ratio is not None and volume_ratio >= _g2_vol
    if skip_volume:
        c2.append(("ok", f"거래량비 >= {_g2_vol}x",
                   f"거래량비 {volume_ratio:.2f}x — BUY 2일차 면제예요" if volume_ratio else "거래량 데이터 없음 — BUY 2일차 면제예요"))
    elif volume_ratio is not None:
        c2.append(("ok" if vol_12 else "no",
                   f"거래량비 >= {_g2_vol}x",
                   f"거래량비 {volume_ratio:.2f}x — {'충분해요' if vol_12 else '아직 부족해요'}"))
    else:
        c2.append(("no", f"거래량비 >= {_g2_vol}x", "거래량 데이터가 없어요"))

    if all(c[0] == "ok" for c in c2):
        return "2nd_BUY", c2

    # [v5.1b] RSI 거부 — 1st BUY에만 적용 (2nd/3rd는 추세 확인 단계라 면제)
    reject_rsi = rsi is not None and rsi > reject_rsi_threshold
    if reject_rsi:
        conditions.append(("no", f"[거부] RSI > {reject_rsi_threshold}",
                           f"RSI {rsi:.1f} — 과열이라 1st BUY 금지예요"))
        return _growth_watch_fallback(d, conditions)

    # ── 1st BUY (20%) — 필수 4개 ALL, 선택 면제  [v5.3b] ──
    _g1_rsi = _p("entry_growth.1st_buy.rsi_max", 45)
    _g1_dd = _p("entry_growth.1st_buy.dd_52w_max", -15.0)
    _g1_watch_min = _p("entry_growth.1st_buy.watch_mandatory_min", 3)
    # [필수①] RSI ≤ threshold (조정 확인)
    rsi_ok = rsi is not None and rsi <= _g1_rsi
    if rsi is not None:
        conditions.append(("ok" if rsi_ok else "no",
                           f"[필수] RSI <= {_g1_rsi}",
                           f"RSI {rsi:.1f} — {'조정 구간이에요' if rsi_ok else f'아직 {_g1_rsi} 이하가 아니에요'}"))
    else:
        conditions.append(("no", f"[필수] RSI <= {_g1_rsi}", "RSI 데이터가 없어요"))

    # [필수②] 가격 < MA20 (조정 확인)
    below_ma20 = price_vs_ma20 == "below"
    conditions.append(("ok" if below_ma20 else "no",
                       "[필수] 가격 < MA20",
                       f"MA20 {'아래에 있어요 — 조정 확인이에요' if below_ma20 else '위에 있어요 — 아직 조정이 아니에요'}"))

    # [필수③] MACD hist 2일 연속 증가 (반전 시작)
    hist_increasing = "increasing" in macd_hist_trend
    conditions.append(("ok" if hist_increasing else "no",
                       "[필수] MACD hist 2일 증가",
                       f"추세 '{macd_hist_trend}' — {'반전 시작이에요' if hist_increasing else '아직 증가세가 아니에요'}"))

    # [필수④] 52주 고점 대비 ≤ threshold (의미 있는 조정)
    drawdown_52w = d.get("drawdown_52w_pct", 0)
    dd_ok = drawdown_52w <= _g1_dd
    conditions.append(("ok" if dd_ok else "no",
                       f"[필수] 52주 고점 대비 <= {_g1_dd}%",
                       f"52주 대비 {drawdown_52w:.1f}% — {'충분히 조정됐어요' if dd_ok else '아직 조정이 부족해요'}"))

    mandatory_ok = rsi_ok and below_ma20 and hist_increasing and dd_ok

    if mandatory_ok:
        return "1st_BUY", conditions

    # WATCH: 필수 N개 이상 충족
    mandatory_count = sum([rsi_ok, below_ma20, hist_increasing, dd_ok])
    if mandatory_count >= _g1_watch_min:
        return "WATCH", conditions

    return None, conditions


def _growth_watch_fallback(d: dict, reject_conditions: list) -> tuple[str | None, list]:
    """거부 조건 충족 시 WATCH 가능 여부 판정."""
    macd_hist_trend = d.get("macd_hist_trend", "")
    price_vs_ma20 = d.get("price_vs_ma20", "")
    rsi = d.get("rsi14")
    # 기술적 관심 요소가 있으면 WATCH
    if "increasing" in macd_hist_trend or price_vs_ma20 == "below":
        return "WATCH", reject_conditions
    return None, reject_conditions


# ═══════════════════════════════════════════════════════
#  ENTRY 판정 — ETF v2.4
# ═══════════════════════════════════════════════════════

def _check_entry_etf(d: dict) -> tuple[str | None, list]:
    """ETF 종목 Entry 판정. Pick 3 of 5."""
    rsi = d.get("rsi14")
    price_vs_ma20 = d.get("price_vs_ma20", "")
    bb_pct = d.get("bb_pct")
    bb_lower = d.get("bb_lower")
    price = d.get("price", 0)
    macd_hist_trend = d.get("macd_hist_trend", "")
    macd_hist_3d = d.get("macd_hist_3d", [])
    drawdown_52w = d.get("drawdown_52w_pct", d.get("drawdown_20d_pct", 0))  # 52주 고점 우선

    conditions = []

    # [거부] RSI > threshold (전 단계 공통)
    _etf_reject_rsi = _p("entry_etf.reject_rsi", 70)
    reject = rsi is not None and rsi > _etf_reject_rsi
    if reject:
        conditions.append(("no", f"[거부] RSI > {_etf_reject_rsi}", f"RSI {rsi:.1f} — 과열이라 전 단계 매수 금지예요"))
        return None, conditions

    # ── 1st BUY 조건 평가  [v5.3b: 필수 4개 ALL, 선택 면제 — Growth와 동일] ──
    _e1_rsi = _p("entry_etf.1st_buy.rsi_max", 45)
    _e1_dd = _p("entry_etf.1st_buy.dd_52w_max", -15.0)
    # [필수①] RSI ≤ threshold (조정 확인)
    rsi_ok = rsi is not None and rsi <= _e1_rsi
    if rsi is not None:
        conditions.append(("ok" if rsi_ok else "no",
                           f"[필수] RSI <= {_e1_rsi}",
                           f"RSI {rsi:.1f} — {'조정 구간이에요' if rsi_ok else f'아직 {_e1_rsi} 이하가 아니에요'}"))
    else:
        conditions.append(("no", f"[필수] RSI <= {_e1_rsi}", "RSI 데이터가 없어요"))

    # [필수②] 가격 < MA20 (조정 확인)
    below_ma20 = price_vs_ma20 == "below"
    conditions.append(("ok" if below_ma20 else "no",
                       "[필수] 가격 < MA20",
                       f"MA20 {'아래에 있어요 — 조정 확인이에요' if below_ma20 else '위에 있어요 — 아직 조정이 아니에요'}"))

    # [필수③] MACD hist 2일 연속 증가 (반전 시작)
    hist_increasing = "increasing" in macd_hist_trend
    conditions.append(("ok" if hist_increasing else "no",
                       "[필수] MACD hist 2일 증가",
                       f"추세 '{macd_hist_trend}' — {'반전 시작이에요' if hist_increasing else '아직 증가세가 아니에요'}"))

    # [필수④] 52주 고점 대비 ≤ threshold (의미 있는 조정)
    dd_ok = drawdown_52w <= _e1_dd
    conditions.append(("ok" if dd_ok else "no",
                       f"[필수] 52주 고점 대비 <= {_e1_dd}%",
                       f"52주 대비 {drawdown_52w:.1f}% — {'충분히 조정됐어요' if dd_ok else '아직 조정이 부족해요'}"))

    # ── 3rd BUY (50%) — ALL 충족  [v5.1b: RSI>55, MACD 골든크로스+0선 돌파] ──
    macd = d.get("macd")
    macd_signal_val = d.get("macd_signal")
    c3 = []
    above_ma20 = price_vs_ma20 == "above"
    c3.append(("ok" if above_ma20 else "no",
               "가격 > MA20",
               f"MA20 {'위에 있어요' if above_ma20 else '아래에 있어요'}"))
    if above_ma20: pass
    rsi_55 = rsi is not None and rsi > 55
    if rsi is not None:
        c3.append(("ok" if rsi_55 else "no",
                   "RSI > 55",
                   f"RSI {rsi:.1f} — {'추세 확인이에요' if rsi_55 else '아직 55 이하예요'}"))
    else:
        c3.append(("no", "RSI > 55", "RSI 데이터가 없어요"))
    macd_above_zero = macd is not None and macd > 0
    macd_golden_etf = macd is not None and macd_signal_val is not None and macd > macd_signal_val
    macd_c3_ok = macd_above_zero and macd_golden_etf
    if macd is not None and macd_signal_val is not None:
        c3.append(("ok" if macd_c3_ok else "no",
                   "MACD > 0 + 골든크로스",
                   f"MACD {macd:.4f} {'>' if macd_above_zero else '<'} 0, {'>' if macd_golden_etf else '<'} signal {macd_signal_val:.4f}"))
    else:
        c3.append(("no", "MACD > 0 + 골든크로스", "MACD 데이터가 없어요"))

    # 3rd BUY 추가 거부: MACD hist 2일 감속 (v5.3e momentum quality)
    _e3_hist_filter = _p("entry_etf.3rd_buy.reject_decreasing_hist", True)
    hist_decel_etf = _e3_hist_filter and macd_hist_trend == "decreasing_2d"
    if hist_decel_etf:
        c3.append(("no", "[거부] MACD hist 2일 감속",
                   "MACD hist 2일 연속 감소 — 추세 둔화로 3차 매수 보류예요"))

    if all(c[0] == "ok" for c in c3) and not hist_decel_etf:
        return "3rd_BUY", c3

    # ── 2nd BUY (30%) — Pick 3 of 4 ──
    _e2_rsi = _p("entry_etf.2nd_buy.rsi_recovery", 42)
    _e2_min = _p("entry_etf.2nd_buy.min_count", 3)
    macd_signal_val = d.get("macd_signal")
    c2_count = 0
    c2 = []
    rsi_42 = rsi is not None and rsi > _e2_rsi
    if rsi is not None:
        c2.append(("ok" if rsi_42 else "no",
                   f"RSI > {_e2_rsi}",
                   f"RSI {rsi:.1f} — {'과매도 탈출이에요' if rsi_42 else f'아직 {_e2_rsi} 이하예요'}"))
    else:
        c2.append(("no", f"RSI > {_e2_rsi}", "RSI 데이터가 없어요"))
    if rsi_42: c2_count += 1
    macd_golden = macd is not None and macd_signal_val is not None and macd > macd_signal_val
    if macd is not None and macd_signal_val is not None:
        c2.append(("ok" if macd_golden else "no",
                   "MACD 골든크로스",
                   f"MACD {macd:.4f} vs signal {macd_signal_val:.4f} — {'골든크로스 발생이에요' if macd_golden else '아직 미발생이에요'}"))
    else:
        c2.append(("no", "MACD 골든크로스", "MACD 데이터가 없어요"))
    if macd_golden: c2_count += 1
    above_or_near_ma20 = price_vs_ma20 == "above"
    c2.append(("ok" if above_or_near_ma20 else "no",
               "가격 > MA20",
               f"MA20 {'위에 있어요' if above_or_near_ma20 else '아래에 있어요 (이탈 중)'}"))
    if above_or_near_ma20: c2_count += 1
    # Higher Low — 단기(sig_low_stopped) AND 중기(low2 > low1) 이중 확인
    dbl2 = d.get("double_bottom", {})
    sig_low_stopped = d.get("sig_low_stopped", False)
    if isinstance(dbl2, dict) and dbl2.get("low1") and dbl2.get("low2"):
        low1_p = dbl2["low1"]["price"]
        low2_p = dbl2["low2"]["price"]
        low1_d = dbl2["low1"]["date"]
        low2_d = dbl2["low2"]["date"]
        mid_term_hl = dbl2.get("higher_low", low2_p > low1_p)   # 중기: 주요 저점 상승
        higher_low = sig_low_stopped and mid_term_hl             # AND 조합
        if higher_low:
            hl_desc = (f"단기 하락멈춤 + 중기저점상승 "
                       f"(${low2_p:.2f}({low2_d}) > ${low1_p:.2f}({low1_d})) — 바닥 확인이에요")
        elif not sig_low_stopped and not mid_term_hl:
            hl_desc = (f"단기 저점갱신 + 중기저점하락 "
                       f"(${low2_p:.2f}({low2_d}) ≤ ${low1_p:.2f}({low1_d})) — 아직 하락 중이에요")
        elif not sig_low_stopped:
            hl_desc = "단기 저점갱신 중 — 최근 3일 최저 미충족이에요"
        else:
            hl_desc = (f"중기저점 하락 중 "
                       f"(${low2_p:.2f}({low2_d}) ≤ ${low1_p:.2f}({low1_d})) — 저점이 낮아지고 있어요")
        c2.append(("ok" if higher_low else "no", "Higher Low 형성", hl_desc))
        if higher_low: c2_count += 1
    else:
        c2.append(("na", "Higher Low 형성", "저점 데이터가 부족해요 (60일 미만)"))
    if c2_count >= _e2_min:
        return "2nd_BUY", c2

    # ── 1st BUY (20%) — 필수 4개 ALL, 선택 면제  [v5.3b] ──
    mandatory_ok = rsi_ok and below_ma20 and hist_increasing and dd_ok
    if mandatory_ok:
        return "1st_BUY", conditions
    # WATCH: 필수 3개 이상 충족
    mandatory_count = sum([rsi_ok, below_ma20, hist_increasing, dd_ok])
    if mandatory_count >= 3:
        return "WATCH", conditions
    return None, conditions


# ═══════════════════════════════════════════════════════
#  ENTRY 판정 — Value v2.4 (독립 구현, 거부 RSI>70)  [v5.1]
# ═══════════════════════════════════════════════════════

def _check_entry_value(d: dict, skip_volume: bool = False) -> tuple[str | None, list]:
    """Value 종목 Entry 판정. Growth와 동일 구조, 거부 RSI>70."""
    return _check_entry_growth(d, reject_rsi_threshold=70, skip_volume=skip_volume)


# ═══════════════════════════════════════════════════════
#  ENTRY 판정 — Bond v2.6
# ═══════════════════════════════════════════════════════

def _check_entry_bond(d: dict, macro: dict) -> tuple[str | None, list]:
    """채권(TLT) Entry 판정. 30Y 금리 기반."""
    rsi = d.get("rsi14")
    yield_30y = macro.get("yield_30Y")
    macd = d.get("macd")
    macd_signal = d.get("macd_signal")
    conditions = []

    if yield_30y is None:
        conditions.append(("na", "30Y 금리 ≥ 5.0%", "30Y 금리 데이터가 없어요"))
        return None, conditions

    # 1st BUY: 30Y ≥ threshold AND RSI ≤ threshold
    _b_yield = _p("entry_bond.yield_30y", 5.0)
    _b_rsi = _p("entry_bond.rsi_max", 35)
    y_ok = yield_30y >= _b_yield
    r_ok = rsi is not None and rsi <= _b_rsi
    conditions.append(("ok" if y_ok else "no",
                       f"30Y 금리 >= {_b_yield}%",
                       f"30Y 금리 {yield_30y:.3f}% — {'매수 구간이에요' if y_ok else f'아직 {_b_yield}% 미만이에요'}"))
    if rsi is not None:
        conditions.append(("ok" if r_ok else "no",
                           f"RSI <= {_b_rsi}",
                           f"RSI {rsi:.1f} — {'과매도 구간이에요' if r_ok else f'아직 {_b_rsi} 이하가 아니에요'}"))
    else:
        conditions.append(("no", f"RSI <= {_b_rsi}", "RSI 데이터가 없어요"))

    if y_ok and r_ok:
        return "1st_BUY", conditions

    # BOND_WATCH: near trigger
    _b_watch = _p("entry_bond.watch_yield_min", 4.9)
    if _b_watch <= yield_30y < _b_yield:
        conditions.append(("ok", "30Y 트리거 직전", f"30Y {yield_30y:.3f}% — 4.9~5.0% 구간이라 주시해요"))
        return "BOND_WATCH", conditions

    return None, conditions


# ═══════════════════════════════════════════════════════
#  ENTRY 판정 — Metal v2.6
# ═══════════════════════════════════════════════════════

def _check_entry_metal(d: dict, macro: dict) -> tuple[str | None, list]:
    """Metal(SLV) Entry 판정. Pick 2 of 4."""
    rsi = d.get("rsi14")
    price_vs_ma20 = d.get("price_vs_ma20", "")
    vix = macro.get("VIX") or 0  # None → 0 (VIX 데이터 누락 시)
    bb_lower = d.get("bb_lower")
    price = d.get("price", 0)
    _m_rsi = _p("entry_metal.rsi_max", 40)
    _m_vix = _p("entry_metal.vix_min", 25)
    _m_bb = _p("entry_metal.bb_dist_max", 5)
    _m_rsi_warn = _p("entry_metal.rsi_warn", 80)
    _m_min = _p("entry_metal.min_count", 2)

    conditions = []
    count = 0

    rsi_ok = rsi is not None and rsi <= _m_rsi
    if rsi is not None:
        conditions.append(("ok" if rsi_ok else "no",
                           f"RSI <= {_m_rsi}",
                           f"RSI {rsi:.1f} — {'과매도 근접이에요' if rsi_ok else f'아직 {_m_rsi} 이하가 아니에요'}"))
    else:
        conditions.append(("no", f"RSI <= {_m_rsi}", "RSI 데이터가 없어요"))
    if rsi_ok:
        count += 1

    below_ma20 = price_vs_ma20 == "below"
    conditions.append(("ok" if below_ma20 else "no",
                       "가격 < MA20",
                       f"MA20 {'아래에 있어요' if below_ma20 else '위에 있어요'}"))
    if below_ma20:
        count += 1

    # VIX > threshold
    vix_ok = vix > _m_vix
    conditions.append(("ok" if vix_ok else "no",
                       f"VIX > {_m_vix}",
                       f"VIX {vix:.1f} — {'공포 구간이에요' if vix_ok else '아직 안정적이에요'}"))
    if vix_ok:
        count += 1

    # BB 하단 근접
    bb_near = False
    if bb_lower and price > 0:
        bb_dist = (price - bb_lower) / bb_lower * 100
        bb_near = bb_dist <= _m_bb
        conditions.append(("ok" if bb_near else "no",
                           f"BB 하단 <= {_m_bb}%",
                           f"BB 하단 거리 {bb_dist:.1f}% — {'하단 근접이에요' if bb_near else '아직 멀어요'}"))
    else:
        conditions.append(("na", f"BB 하단 <= {_m_bb}%", "BB 하단 데이터가 없어요"))
    if bb_near:
        count += 1

    # RSI > warn → TOP_SIGNAL 강제 (별도 처리)
    if rsi is not None and rsi > _m_rsi_warn:
        conditions.append(("no", f"[주의] RSI > {_m_rsi_warn}", f"RSI {rsi:.1f} — TOP_SIGNAL 영역이에요"))

    if count >= _m_min:
        return "1st_BUY", conditions
    if count >= 1:
        return "WATCH", conditions
    return None, conditions


# ═══════════════════════════════════════════════════════
#  유틸리티
# ═══════════════════════════════════════════════════════

def _check_ma20_below_2d(d: dict, prev_day: dict | None) -> bool:
    """현재 + 전일 모두 MA20 하회인지 확인"""
    current_below = d.get("price_vs_ma20") == "below"
    if prev_day is None:
        return False
    prev_below = prev_day.get("price_vs_ma20") == "below"
    return current_below and prev_below


def _calc_3d_change(d: dict) -> float | None:
    """최근 3일 누적 변동률. fetch_market_data의 change_3d_pct 우선 사용."""
    return d.get("change_3d_pct", d.get("change_pct"))


def _get_prev_day_data(ticker: str, history: dict, today_str: str = "") -> dict | None:
    """signals_history.json에서 전 거래일 데이터 가져오기.

    today_str을 명시하면 그 날짜를 제외하고 가장 최근 날짜를 본다.
    같은 날 재실행 시 자기 자신을 prev_day로 보는 버그 방지 — scanner의
    `_had_prior_buy`와 동일한 strict 정의."""
    dates = sorted(history.keys())
    dates = [dt for dt in dates if not dt.startswith("_")]
    if today_str:
        dates = [dt for dt in dates if dt < today_str]
    if not dates:
        return None
    last_date = dates[-1]
    day_data = history.get(last_date, {})
    return day_data.get(ticker)


# ═══════════════════════════════════════════════════════
#  스캐너용 간이 Exit 판정 (prev_day 불필요)
# ═══════════════════════════════════════════════════════

def check_exit_simple(ticker: str, d: dict) -> dict | None:
    """prev_day 없이 판정 가능한 Exit 체크 (스캐너용).
    v5.2: 익절 전용 — 고점 게이트 적용, Drawdown 조건 삭제.
    Exit 시그널이면 dict 반환, 아니면 None."""
    # TOP_SIGNAL (MACD 가드 없음, 고점 게이트 없음)
    top_hit, top_conds = _check_top_signal(d)
    if top_hit:
        return {"signal": "TOP_SIGNAL", "note": _make_note(top_conds), "conditions": top_conds}

    # 고점 영역 게이트: DD > -5% 일 때만 TP 시그널 허용
    if not _is_profit_zone(d):
        return None

    macd = d.get("macd")
    macd_signal_val = d.get("macd_signal")
    macd_hist_trend = d.get("macd_hist_trend", "")
    bullish = _is_macd_bullish(d)
    hist_recovering = "increasing" in macd_hist_trend

    # TP2: MACD 데스크로스 + hist 감소  [v5.2: MACD < 0 삭제]
    tp2_conditions = []
    tp2_hit = False
    if not bullish and not hist_recovering:
        if macd is not None and macd_signal_val is not None:
            if macd < macd_signal_val and "decreasing" in macd_hist_trend:
                tp2_conditions.append(("ok", "MACD 데스크로스 + hist 감소",
                                       f"MACD {macd:.4f} < signal + hist 감소 — 하락 전환이에요"))
                tp2_hit = True
    if tp2_hit:
        return {"signal": "TAKE_PROFIT_2", "note": _make_note(tp2_conditions), "conditions": tp2_conditions}

    # TP1: hist 감소 + MA20 이탈 (2/2)
    if not bullish and not hist_recovering:
        tp1_count = 0
        tp1_conditions = []
        if "decreasing" in macd_hist_trend:
            tp1_conditions.append(("ok", "MACD hist 감소",
                                   f"추세 '{macd_hist_trend}' — 모멘텀이 약해지고 있어요"))
            tp1_count += 1
        if d.get("price_vs_ma20") == "below":
            tp1_conditions.append(("ok", "종가 < MA20", "MA20 아래로 내려왔어요"))
            tp1_count += 1
        if tp1_count >= 2:
            return {"signal": "TAKE_PROFIT_1", "note": _make_note(tp1_conditions), "conditions": tp1_conditions}

    return None


# ═══════════════════════════════════════════════════════
#  판정 근거 전체 섹션 수집 (모든 Entry/Exit 레벨 평가)
# ═══════════════════════════════════════════════════════

def _count_ok(conditions: list) -> int:
    return sum(1 for c in conditions if c[0] == "ok")


def _build_exit_sections(d: dict, prev_day: dict | None) -> list:
    """Exit 판정 섹션들 (TOP → TP2 → TP1) 수집."""
    sections = []
    in_profit_zone = _is_profit_zone(d)
    bullish = _is_macd_bullish(d)

    # TOP_SIGNAL
    _, top_conds = _check_top_signal(d, prev_day)
    sections.append({
        "name": "TOP_SIGNAL — 과열 경보",
        "rule": "3개 중 2개 충족 시 발동",
        "conditions": top_conds,
        "met": _count_ok(top_conds),
        "total": len(top_conds),
        "gate": None,
    })

    # TAKE_PROFIT_2
    if in_profit_zone:
        _, tp2_conds = _check_take_profit_2(d, prev_day)
        gate = None
    else:
        tp2_conds = [("na", "고점 게이트", f"DD {d.get('drawdown_20d_pct', 0):.1f}% ≤ -5% — 이미 많이 하락해서 익절 대상이 아니에요")]
        gate = "고점 게이트 미통과"
    sections.append({
        "name": "TAKE_PROFIT_2 — 상승 종료",
        "rule": "고점 게이트 + 1개 충족",
        "conditions": tp2_conds,
        "met": _count_ok(tp2_conds),
        "total": len(tp2_conds),
        "gate": gate,
    })

    # TAKE_PROFIT_1
    if in_profit_zone:
        _, tp1_conds = _check_take_profit_1(d, prev_day)
        gate = None
    else:
        tp1_conds = [("na", "고점 게이트", f"DD {d.get('drawdown_20d_pct', 0):.1f}% ≤ -5% — 이미 많이 하락해서 익절 대상이 아니에요")]
        gate = "고점 게이트 미통과"
    sections.append({
        "name": "TAKE_PROFIT_1 — 상승 둔화",
        "rule": "3개 중 2개 충족",
        "conditions": tp1_conds,
        "met": _count_ok(tp1_conds),
        "total": len(tp1_conds),
        "gate": gate,
    })

    return sections


def _build_entry_sections_growth(d: dict, reject_rsi_threshold: float = 55) -> list:
    """Growth/Value Entry 전체 섹션 수집 (3rd → 2nd → 1st BUY)."""
    sections = []
    rsi = d.get("rsi14")
    adx = d.get("adx")
    bb_lower = d.get("bb_lower")
    price = d.get("price", 0)
    macd = d.get("macd")
    macd_signal = d.get("macd_signal")
    macd_hist_trend = d.get("macd_hist_trend", "")
    volume_ratio = d.get("volume_ratio")
    change_pct = d.get("change_pct", 0)
    price_vs_ma20 = d.get("price_vs_ma20", "")

    # 거부 조건
    reject_drop = change_pct <= -5.0
    reject_rsi_flag = rsi is not None and rsi > reject_rsi_threshold

    group_label = "성장주" if reject_rsi_threshold == 55 else "가치주"

    # ── 3rd BUY ──
    c3 = []
    above_ma20 = price_vs_ma20 == "above"
    c3.append(("ok" if above_ma20 else "no",
               "가격 > MA20",
               f"MA20 {'위에 있어요' if above_ma20 else '아래에 있어요'}"))
    macd_above_zero = macd is not None and macd > 0
    macd_golden_c3 = macd is not None and macd_signal is not None and macd > macd_signal
    macd_c3_ok = macd_above_zero and macd_golden_c3
    if macd is not None and macd_signal is not None:
        c3.append(("ok" if macd_c3_ok else "no",
                   "MACD > 0 + 골든크로스",
                   f"MACD {macd:.4f} {'>' if macd_above_zero else '<'} 0, {'>' if macd_golden_c3 else '<'} signal {macd_signal:.4f}"))
    else:
        c3.append(("no", "MACD > 0 + 골든크로스", "MACD 데이터가 없어요"))
    _g3_vol_display = _p("entry_growth.3rd_buy.volume_ratio", 1.5)
    vol_13 = volume_ratio is not None and volume_ratio >= _g3_vol_display
    if volume_ratio is not None:
        c3.append(("ok" if vol_13 else "no",
                   f"거래량비 >= {_g3_vol_display}x",
                   f"거래량비 {volume_ratio:.2f}x - {'평소보다 많아요' if vol_13 else '아직 부족해요'}"))
    else:
        c3.append(("no", f"거래량비 >= {_g3_vol_display}x", "거래량 데이터가 없어요"))
    rsi_above_55 = rsi is not None and rsi > 55
    if rsi is not None:
        c3.append(("ok" if rsi_above_55 else "no",
                   "RSI > 55",
                   f"RSI {rsi:.1f} - {'추세 확인이에요' if rsi_above_55 else '아직 55 이하예요'}"))
    else:
        c3.append(("no", "RSI > 55", "RSI 데이터가 없어요"))
    c3_reject = rsi is not None and rsi > 75
    sections.append({
        "name": f"3차 매수 조건 - {group_label} v2.2",
        "rule": "4개 모두 충족",
        "conditions": c3,
        "met": _count_ok(c3),
        "total": len(c3),
        "gate": "[거부] RSI > 75" if c3_reject else ("[거부] 당일 급락" if reject_drop else None),
    })

    # ── 2nd BUY ──  [v5.3d: MA20 돌파 확인 단계]
    c2 = []
    above_ma20_2nd = price_vs_ma20 == "above"
    c2.append(("ok" if above_ma20_2nd else "no",
               "가격 > MA20 (돌파 확인)",
               f"MA20 {'위에 있어요 — 추세 전환 확인이에요' if above_ma20_2nd else '아래에 있어요 — 아직 MA20 돌파 전이에요'}"))
    rsi_mid = rsi is not None and rsi > 40
    if rsi is not None:
        c2.append(("ok" if rsi_mid else "no",
                   "RSI > 40",
                   f"RSI {rsi:.1f} - {'회복 구간이에요' if rsi_mid else '아직 회복 전이에요'}"))
    else:
        c2.append(("no", "RSI > 40", "RSI 데이터가 없어요"))
    macd_golden = macd is not None and macd_signal is not None and macd > macd_signal
    hist_inc_2nd = "increasing" in macd_hist_trend
    macd_2nd_ok = macd_golden and hist_inc_2nd
    if macd is not None and macd_signal is not None:
        c2.append(("ok" if macd_2nd_ok else "no",
                   "MACD 골든크로스 + hist 2일 증가",
                   f"MACD {macd:.4f} {'>' if macd_golden else '<'} signal {macd_signal:.4f}, "
                   f"hist {'증가중이에요' if hist_inc_2nd else '증가 미확인이에요'}"))
    else:
        c2.append(("no", "MACD 골든크로스 + hist 2일 증가", "MACD 데이터가 없어요"))
    _g2_vol_display = _p("entry_growth.2nd_buy.volume_ratio", 1.5)
    vol_12 = volume_ratio is not None and volume_ratio >= _g2_vol_display
    if volume_ratio is not None:
        c2.append(("ok" if vol_12 else "no",
                   f"거래량비 >= {_g2_vol_display}x",
                   f"거래량비 {volume_ratio:.2f}x - {'충분해요' if vol_12 else '아직 부족해요'}"))
    else:
        c2.append(("no", f"거래량비 >= {_g2_vol_display}x", "거래량 데이터가 없어요"))
    sections.append({
        "name": f"2차 매수 조건 - {group_label} v5.3d",
        "rule": "4개 모두 충족",
        "conditions": c2,
        "met": _count_ok(c2),
        "total": len(c2),
        "gate": "[거부] 당일 급락" if reject_drop else None,
    })

    # ── 1st BUY ──  [v5.3b: 필수 4개 ALL, 선택 면제]
    c1 = []
    rsi_ok = rsi is not None and rsi <= 45
    if rsi is not None:
        c1.append(("ok" if rsi_ok else "no",
                   "[필수] RSI <= 45",
                   f"RSI {rsi:.1f} - {'조정 구간이에요' if rsi_ok else '아직 45 이하가 아니에요'}"))
    else:
        c1.append(("no", "[필수] RSI <= 45", "RSI 데이터가 없어요"))
    below_ma20 = price_vs_ma20 == "below"
    c1.append(("ok" if below_ma20 else "no",
               "[필수] 가격 < MA20",
               f"MA20 {'아래에 있어요 - 조정 확인이에요' if below_ma20 else '위에 있어요 - 아직 조정이 아니에요'}"))
    hist_increasing = "increasing" in macd_hist_trend
    c1.append(("ok" if hist_increasing else "no",
               "[필수] MACD hist 2일 증가",
               f"추세 '{macd_hist_trend}' - {'반전 시작이에요' if hist_increasing else '아직 증가세가 아니에요'}"))
    drawdown_52w_val = d.get("drawdown_52w_pct", 0)
    dd_1st_ok = drawdown_52w_val <= -15.0
    c1.append(("ok" if dd_1st_ok else "no",
               "[필수] 52주 고점 대비 <= -15%",
               f"52주 대비 {drawdown_52w_val:.1f}% - {'충분히 조정됐어요' if dd_1st_ok else '아직 조정이 부족해요'}"))

    gate_1st = None
    if reject_drop:
        gate_1st = f"[거부] 당일 {change_pct:+.1f}% (≤-5% 급락)"
    elif reject_rsi_flag:
        gate_1st = f"[거부] RSI {rsi:.1f} > {reject_rsi_threshold}"
    sections.append({
        "name": f"1차 매수 조건 — {group_label} v5.3b",
        "rule": "[필수] RSI<=45 + 가격<MA20 + MACD hist 2일증가 + DD_52w<=-15%",
        "conditions": c1,
        "met": _count_ok(c1),
        "total": len(c1),
        "gate": gate_1st,
    })

    return sections


def _build_entry_sections_etf(d: dict) -> list:
    """ETF Entry 전체 섹션 수집 (3rd → 2nd → 1st BUY)."""
    sections = []
    rsi = d.get("rsi14")
    price_vs_ma20 = d.get("price_vs_ma20", "")
    bb_lower = d.get("bb_lower")
    price = d.get("price", 0)
    macd = d.get("macd")
    macd_signal_val = d.get("macd_signal")
    macd_hist_trend = d.get("macd_hist_trend", "")
    macd_hist_3d = d.get("macd_hist_3d", [])
    drawdown_52w = d.get("drawdown_52w_pct", d.get("drawdown_20d_pct", 0))

    reject_rsi = rsi is not None and rsi > 70

    # ── 3rd BUY ──
    c3 = []
    above_ma20 = price_vs_ma20 == "above"
    c3.append(("ok" if above_ma20 else "no",
               "가격 > MA20",
               f"MA20 {'위에 있어요' if above_ma20 else '아래에 있어요'}"))
    rsi_55 = rsi is not None and rsi > 55
    if rsi is not None:
        c3.append(("ok" if rsi_55 else "no",
                   "RSI > 55",
                   f"RSI {rsi:.1f} - {'추세 확인이에요' if rsi_55 else '아직 55 이하예요'}"))
    else:
        c3.append(("no", "RSI > 55", "RSI 데이터가 없어요"))
    macd_above_zero = macd is not None and macd > 0
    macd_golden = macd is not None and macd_signal_val is not None and macd > macd_signal_val
    macd_c3_ok = macd_above_zero and macd_golden
    if macd is not None and macd_signal_val is not None:
        c3.append(("ok" if macd_c3_ok else "no",
                   "MACD > 0 + 골든크로스",
                   f"MACD {macd:.4f} {'>' if macd_above_zero else '<'} 0, {'>' if macd_golden else '<'} signal {macd_signal_val:.4f}"))
    else:
        c3.append(("no", "MACD > 0 + 골든크로스", "MACD 데이터가 없어요"))
    sections.append({
        "name": "3차 매수 조건 - ETF v2.4",
        "rule": "3개 ALL 충족",
        "conditions": c3,
        "met": _count_ok(c3),
        "total": len(c3),
        "gate": f"[거부] RSI {rsi:.1f} > 70" if reject_rsi else None,
    })

    # ── 2nd BUY ──
    c2 = []
    c2_count = 0
    rsi_42 = rsi is not None and rsi > 42
    if rsi is not None:
        c2.append(("ok" if rsi_42 else "no",
                   "RSI > 42",
                   f"RSI {rsi:.1f} - {'과매도 탈출이에요' if rsi_42 else '아직 42 이하예요'}"))
    else:
        c2.append(("no", "RSI > 42", "RSI 데이터가 없어요"))
    if rsi_42: c2_count += 1
    macd_golden_2 = macd is not None and macd_signal_val is not None and macd > macd_signal_val
    if macd is not None and macd_signal_val is not None:
        c2.append(("ok" if macd_golden_2 else "no",
                   "MACD 골든크로스",
                   f"MACD {macd:.4f} vs signal {macd_signal_val:.4f} - {'골든크로스 발생이에요' if macd_golden_2 else '아직 미발생이에요'}"))
    else:
        c2.append(("no", "MACD 골든크로스", "MACD 데이터가 없어요"))
    if macd_golden_2: c2_count += 1
    above_or_near = price_vs_ma20 == "above"
    c2.append(("ok" if above_or_near else "no",
               "가격 > MA20",
               f"MA20 {'위에 있어요' if above_or_near else '아래에 있어요'}"))
    if above_or_near: c2_count += 1
    # Higher Low
    dbl2 = d.get("double_bottom", {})
    sig_low_stopped = d.get("sig_low_stopped", False)
    if isinstance(dbl2, dict) and dbl2.get("low1") and dbl2.get("low2"):
        low1_p = dbl2["low1"]["price"]
        low2_p = dbl2["low2"]["price"]
        mid_term_hl = dbl2.get("higher_low", low2_p > low1_p)
        higher_low = sig_low_stopped and mid_term_hl
        c2.append(("ok" if higher_low else "no",
                   "Higher Low 형성",
                   f"Higher Low {'확인 - 바닥 형성이에요' if higher_low else '미형성 - 아직 저점이 올라오지 않았어요'}"))
        if higher_low: c2_count += 1
    else:
        c2.append(("na", "Higher Low 형성", "저점 데이터가 부족해요"))
    sections.append({
        "name": "2차 매수 조건 - ETF v2.4",
        "rule": "4개 중 3개 충족",
        "conditions": c2,
        "met": _count_ok(c2),
        "total": len(c2),
        "gate": f"[거부] RSI {rsi:.1f} > 70" if reject_rsi else None,
    })

    # ── 1st BUY ──  [v5.3b: 필수 4개 ALL, 선택 면제 — Growth와 동일]
    c1 = []
    rsi_ok = rsi is not None and rsi <= 45
    if rsi is not None:
        c1.append(("ok" if rsi_ok else "no",
                   "[필수] RSI <= 45",
                   f"RSI {rsi:.1f} - {'조정 구간이에요' if rsi_ok else '아직 45 이하가 아니에요'}"))
    else:
        c1.append(("no", "[필수] RSI <= 45", "RSI 데이터가 없어요"))
    below_ma20 = price_vs_ma20 == "below"
    c1.append(("ok" if below_ma20 else "no",
               "[필수] 가격 < MA20",
               f"MA20 {'아래에 있어요 - 조정 확인이에요' if below_ma20 else '위에 있어요 - 아직 조정이 아니에요'}"))
    hist_increasing = "increasing" in macd_hist_trend
    c1.append(("ok" if hist_increasing else "no",
               "[필수] MACD hist 2일 증가",
               f"추세 '{macd_hist_trend}' - {'반전 시작이에요' if hist_increasing else '아직 증가세가 아니에요'}"))
    dd_1st_ok = drawdown_52w <= -15.0
    c1.append(("ok" if dd_1st_ok else "no",
               "[필수] 52주 고점 대비 <= -15%",
               f"52주 대비 {drawdown_52w:.1f}% - {'충분히 조정됐어요' if dd_1st_ok else '아직 조정이 부족해요'}"))
    sections.append({
        "name": "1차 매수 조건 - ETF v5.3b",
        "rule": "[필수] RSI<=45 + 가격<MA20 + MACD hist 2일증가 + DD_52w<=-15%",
        "conditions": c1,
        "met": _count_ok(c1),
        "total": len(c1),
        "gate": f"[거부] RSI {rsi:.1f} > 70" if reject_rsi else None,
    })

    return sections


def _build_entry_sections_bond(d: dict, macro: dict) -> list:
    """Bond Entry 섹션 수집."""
    rsi = d.get("rsi14")
    yield_30y = macro.get("yield_30Y")
    c = []
    if yield_30y is not None:
        y_ok = yield_30y >= 5.0
        c.append(("ok" if y_ok else "no",
                  "30Y 금리 >= 5.0%",
                  f"30Y 금리 {yield_30y:.3f}% - {'매수 구간이에요' if y_ok else '아직 5.0% 미만이에요'}"))
    else:
        c.append(("na", "30Y 금리 >= 5.0%", "30Y 금리 데이터가 없어요"))
    r_ok = rsi is not None and rsi <= 35
    if rsi is not None:
        c.append(("ok" if r_ok else "no",
                  "RSI <= 35",
                  f"RSI {rsi:.1f} - {'과매도 구간이에요' if r_ok else '아직 35 이하가 아니에요'}"))
    else:
        c.append(("no", "RSI <= 35", "RSI 데이터가 없어요"))
    return [{
        "name": "1차 매수 조건 - 채권 v2.6",
        "rule": "2개 모두 충족",
        "conditions": c,
        "met": _count_ok(c),
        "total": len(c),
        "gate": None,
    }]


def _build_entry_sections_metal(d: dict, macro: dict) -> list:
    """Metal Entry 섹션 수집."""
    rsi = d.get("rsi14")
    price_vs_ma20 = d.get("price_vs_ma20", "")
    vix = macro.get("VIX") or 0
    bb_lower = d.get("bb_lower")
    price = d.get("price", 0)
    c = []
    rsi_ok = rsi is not None and rsi <= 40
    if rsi is not None:
        c.append(("ok" if rsi_ok else "no",
                  "RSI <= 40",
                  f"RSI {rsi:.1f} - {'과매도 근접이에요' if rsi_ok else '아직 40 이하가 아니에요'}"))
    else:
        c.append(("no", "RSI <= 40", "RSI 데이터가 없어요"))
    below_ma20 = price_vs_ma20 == "below"
    c.append(("ok" if below_ma20 else "no",
              "가격 < MA20",
              f"MA20 {'아래에 있어요' if below_ma20 else '위에 있어요'}"))
    vix_ok = vix > 25
    c.append(("ok" if vix_ok else "no",
              "VIX > 25",
              f"VIX {vix:.1f} - {'공포 구간이에요' if vix_ok else '아직 안정적이에요'}" if vix else "VIX 데이터 없음"))
    if bb_lower and price > 0:
        bb_dist = (price - bb_lower) / bb_lower * 100
        bb_near = bb_dist <= 5
        c.append(("ok" if bb_near else "no",
                  "BB 하단 <= 5%",
                  f"BB 하단 거리 {bb_dist:.1f}% - {'하단 근접이에요' if bb_near else '아직 멀어요'}"))
    else:
        c.append(("na", "BB 하단 <= 5%", "BB 하단 데이터가 없어요"))
    return [{
        "name": "1차 매수 조건 - 귀금속 v2.6",
        "rule": "4개 중 2개 충족",
        "conditions": c,
        "met": _count_ok(c),
        "total": len(c),
        "gate": None,
    }]


def build_judgment_sections(ticker: str, d: dict, macro: dict, prev_day: dict | None) -> list:
    """종목의 모든 판정 섹션 (Exit + Entry) 수집. 리포트 판정 근거 표시용."""
    group = get_strategy_group(ticker)
    if group == "cash":
        return []

    sections = _build_exit_sections(d, prev_day)

    if group == "growth":
        sections.extend(_build_entry_sections_growth(d))
    elif group == "value":
        sections.extend(_build_entry_sections_growth(d, reject_rsi_threshold=70))
    elif group == "etf":
        sections.extend(_build_entry_sections_etf(d))
    elif group == "bond":
        sections.extend(_build_entry_sections_bond(d, macro))
    elif group == "metal":
        sections.extend(_build_entry_sections_metal(d, macro))

    return sections


# ═══════════════════════════════════════════════════════
#  메인 판정 함수
# ═══════════════════════════════════════════════════════

def judge_ticker(ticker: str, d: dict, macro: dict, prev_day: dict | None, skip_volume: bool = False) -> dict:
    """
    단일 종목 시그널 판정.
    skip_volume: True이면 거래량 조건 면제 (BUY 2일차 확인용)
    반환: {signal, note, conditions, judgment_sections}
    """
    group = get_strategy_group(ticker)

    # BIL → 항상 CASH
    if group == "cash":
        return {
            "signal": "CASH",
            "note": "현금성 자산",
            "conditions": [("ok", "현금성 자산", "시그널 판정 대상이 아니에요")],
            "judgment_sections": [],
        }

    # 판정 근거 전체 섹션 수집 (모든 Exit/Entry 레벨 독립 평가)
    all_sections = build_judgment_sections(ticker, d, macro, prev_day)

    # ── [v5.4] Entry 우선 체크 (BUY 시그널이 Exit보다 우선) ──
    if group == "growth":
        signal, conds = _check_entry_growth(d, skip_volume=skip_volume)
    elif group == "etf":
        signal, conds = _check_entry_etf(d)
    elif group == "value":
        signal, conds = _check_entry_value(d, skip_volume=skip_volume)
    elif group == "bond":
        signal, conds = _check_entry_bond(d, macro)
    elif group == "metal":
        signal, conds = _check_entry_metal(d, macro)
    else:
        signal, conds = None, []

    if signal and signal in _BUY_SIGNALS:
        return {"signal": signal, "note": _make_note(conds), "conditions": conds,
                "judgment_sections": all_sections}

    # ── Exit(익절) 체크 (BUY 미발동 시에만) ──
    top_hit, top_conds = _check_top_signal(d, prev_day)
    if top_hit:
        return {"signal": "TOP_SIGNAL", "note": _make_note(top_conds), "conditions": top_conds,
                "judgment_sections": all_sections}

    if _is_profit_zone(d):
        tp2_hit, tp2_conds = _check_take_profit_2(d, prev_day)
        if tp2_hit:
            return {"signal": "TAKE_PROFIT_2", "note": _make_note(tp2_conds), "conditions": tp2_conds,
                    "judgment_sections": all_sections}

        tp1_hit, tp1_conds = _check_take_profit_1(d, prev_day)
        if tp1_hit:
            return {"signal": "TAKE_PROFIT_1", "note": _make_note(tp1_conds), "conditions": tp1_conds,
                    "judgment_sections": all_sections}

    # ── Entry의 WATCH도 여기서 반환 ──
    if signal:
        return {"signal": signal, "note": _make_note(conds), "conditions": conds,
                "judgment_sections": all_sections}

    # ── 해당 없으면 HOLD ──
    return {
        "signal": "HOLD",
        "note": "Exit/Entry 조건 미충족",
        "conditions": [("na", "조건 미충족", "Exit/Entry 조건 미충족 - 보유 유지예요")],
        "judgment_sections": all_sections,
    }


def _make_note(conditions: list) -> str:
    """충족된 조건들로 요약 노트 생성"""
    ok_items = [c[1] for c in conditions if c[0] == "ok"]
    if ok_items:
        return " + ".join(ok_items[:3])
    return "조건 미충족"


# ═══════════════════════════════════════════════════════
#  BUY 연속일 확인  [v5.1b]
# ═══════════════════════════════════════════════════════

_BUY_SIGNALS = {"1st_BUY", "2nd_BUY", "3rd_BUY"}
_BUY_RANK = {"1st_BUY": 1, "2nd_BUY": 2, "3rd_BUY": 3}
_MIN_CONSECUTIVE_DAYS = 2  # BUY 확정에 필요한 최소 연속일


def _count_buy_streak(ticker: str, current_signal: str, history: dict, today_str: str = "") -> int:
    """history에서 BUY 시그널 연속일 카운트 (오늘 포함).
    같은 등급 또는 상위 승격이면 연속 누적, BUY 해제 시 리셋."""
    if current_signal not in _BUY_SIGNALS:
        return 0

    streak = 1  # 오늘 포함

    # 최근 날짜순으로 역순 탐색 (오늘 날짜 제외 — 아직 저장 전이거나 이전 실행 데이터일 수 있음)
    dates = sorted([k for k in history.keys()
                    if not k.startswith("_") and k != today_str], reverse=True)
    for dt in dates:
        day_data = history.get(dt, {})
        ticker_data = day_data.get(ticker, {})
        prev_signal = ticker_data.get("signal", "")

        if prev_signal not in _BUY_SIGNALS:
            break  # BUY가 아니면 연속 끊김

        streak += 1
        if streak >= 5:  # 안전장치: 최대 5일까지만 추적
            break

    return streak


def _calc_hypo_return(ticker: str, current_price: float, history: dict, today_str: str = "") -> dict:
    """포트폴리오 BUY 연속 구간에서 1일차/2일차 매수 가상 수익률 계산."""
    result = {
        "day1_price": None, "day1_date": None, "day1_return": None,
        "day2_price": None, "day2_date": None, "day2_return": None,
    }
    if not current_price or current_price <= 0:
        return result

    dates = sorted([k for k in history.keys()
                    if not k.startswith("_") and k != today_str], reverse=True)
    buy_dates = []
    for dt in dates:
        day_data = history.get(dt, {})
        ticker_data = day_data.get(ticker, {})
        if ticker_data.get("signal", "") in _BUY_SIGNALS:
            buy_dates.append((dt, ticker_data))
        else:
            break
        # 안전 가드: history 길이만큼 (~30일) 끝까지 수집. SCHD처럼 14일+ streak도
        # day1을 정확히 잡도록 확장. 이전 10일 cap은 streak 시작일을 잘못 표시했음.
        if len(buy_dates) >= 60:
            break

    if not buy_dates:
        return result

    buy_dates.reverse()

    day1_dt, day1_data = buy_dates[0]
    day1_price = day1_data.get("price")
    if day1_price and day1_price > 0:
        result["day1_price"] = day1_price
        result["day1_date"] = day1_dt
        result["day1_return"] = round((current_price - day1_price) / day1_price * 100, 2)

    if len(buy_dates) >= 2:
        day2_dt, day2_data = buy_dates[1]
        day2_price = day2_data.get("price")
        if day2_price and day2_price > 0:
            result["day2_price"] = day2_price
            result["day2_date"] = day2_dt
            result["day2_return"] = round((current_price - day2_price) / day2_price * 100, 2)

    return result


def judge_all(market_data: dict, history: dict) -> dict[str, dict]:
    """
    전 종목 시그널 판정.
    market_data: fetch_market_data.py의 JSON 출력
    history: signals_history.json 내용
    반환: {ticker: {signal, note, conditions, price, rsi, ..., buy_streak, buy_confirmed}}
    """
    data = market_data.get("data", {})
    macro = market_data.get("_macro", {})
    today_str = market_data.get("_meta", {}).get("date", "")
    results = {}

    for ticker, d in data.items():
        if "error" in d:
            results[ticker] = {
                "signal": "ERROR",
                "note": d["error"],
                "conditions": [("no", "오류", d["error"])],
            }
            continue

        prev_day = _get_prev_day_data(ticker, history, today_str)

        # [v5.2] 전일 BUY였으면 2일차 거래량 면제 재판정 대상
        has_prior_streak = prev_day is not None and prev_day.get("signal", "") in _BUY_SIGNALS
        result = judge_ticker(ticker, d, macro, prev_day)

        # 전일 BUY였는데 오늘 BUY 미발동 → 거래량 면제로 재판정
        if has_prior_streak and result["signal"] not in _BUY_SIGNALS:
            retry = judge_ticker(ticker, d, macro, prev_day, skip_volume=True)
            if retry["signal"] in _BUY_SIGNALS:
                result = retry

        # [v5.1b] BUY 연속일 확인
        signal = result["signal"]
        if signal in _BUY_SIGNALS:
            streak = _count_buy_streak(ticker, signal, history, today_str)
            confirmed = streak >= _MIN_CONSECUTIVE_DAYS
            result["buy_streak"] = streak
            result["buy_confirmed"] = confirmed

            if not confirmed:
                # 미확정: 시그널 유지하되 태그 추가
                result["note"] = f"[확인 대기 {streak}/{_MIN_CONSECUTIVE_DAYS}일] {result['note']}"
            else:
                result["note"] = f"[확정 {streak}일 연속] {result['note']}"

            # 가상 수익률 계산
            hypo = _calc_hypo_return(ticker, d.get("price", 0), history, today_str)
            result["hypo_return"] = hypo
        else:
            result["buy_streak"] = 0
            result["buy_confirmed"] = False

        # 추가 메트릭 저장 (리포트용)
        result["price"] = d.get("price")
        result["rsi"] = d.get("rsi14")
        result["macd_hist"] = d.get("macd_hist")
        result["macd_hist_trend"] = d.get("macd_hist_trend")
        result["drawdown"] = d.get("drawdown_20d_pct")
        result["adx"] = d.get("adx")
        result["change_pct"] = d.get("change_pct")
        result["price_vs_ma20"] = d.get("price_vs_ma20")
        result["ma20"] = d.get("ma20")
        result["bb_pct"] = d.get("bb_pct")
        result["volume_ratio"] = d.get("volume_ratio")
        result["macd_hist_3d"] = d.get("macd_hist_3d", [])

        results[ticker] = result

    return results


# ── CLI 테스트용 ──────────────────────────────────────
if __name__ == "__main__":
    import json
    import sys
    import os

    project_dir = os.path.dirname(os.path.abspath(__file__))

    # 최신 market_data JSON 찾기
    screenshots_dir = os.path.join(project_dir, "screenshots")
    json_files = sorted([f for f in os.listdir(screenshots_dir) if f.startswith("market_data_") and f.endswith(".json")])
    if not json_files:
        print("❌ market_data JSON 파일이 없습니다.")
        sys.exit(1)

    json_path = os.path.join(screenshots_dir, json_files[-1])
    print(f"📂 사용 파일: {json_path}")

    with open(json_path, "rb") as f:
        raw = f.read()
    market_data = json.loads(raw.rstrip(b" \t\n\r\x00").decode("utf-8"))

    # 이력 로드
    history_path = os.path.join(project_dir, "history", "signals_history.json")
    history = {}
    if os.path.exists(history_path):
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)

    # 판정 실행
    results = judge_all(market_data, history)

    print(f"\n{'━' * 60}")
    print(f"  시그널 판정 결과 ({len(results)}종목)")
    print(f"{'━' * 60}")
    for ticker, r in sorted(results.items(), key=lambda x: x[1].get("signal", "")):
        sig = r["signal"]
        price = r.get("price", "N/A")
        note = r.get("note", "")[:60]
        print(f"  {ticker:<6} {sig:<16} ${price:>8}  {note}")
    print(f"{'━' * 60}")
