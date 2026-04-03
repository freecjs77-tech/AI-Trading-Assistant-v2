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

from portfolio_data import (
    STRATEGY_GROUP, get_strategy_group,
    get_ticker_name, get_ticker_class,
)


# ═══════════════════════════════════════════════════════
#  고점 영역 게이트 (v5.2)
# ═══════════════════════════════════════════════════════

def _is_profit_zone(d: dict) -> bool:
    """고점 영역 게이트: 최근 고점 대비 -5% 이내일 때만 익절 시그널 허용.
    이미 많이 하락한 상태에서는 Exit 발동하지 않음 → HOLD로 버팀."""
    dd = d.get("drawdown_20d_pct", 0)
    return dd > -5.0


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
    """TOP_SIGNAL — 과열 경보. 1개라도 충족 시 발동."""
    conditions = []
    rsi = d.get("rsi14")
    bb_pct = d.get("bb_pct")
    change_3d = _calc_3d_change(d)

    if rsi is not None and rsi >= 75:
        conditions.append(("ok", f"RSI {rsi:.1f} ≥ 75"))
    else:
        conditions.append(("no", f"RSI {rsi:.1f} < 75" if rsi else "RSI N/A"))

    # BB 상단 2일 연속 마감 (bb_pct > 100 = 상단 초과)
    bb_above_today = bb_pct is not None and bb_pct > 100
    if prev_day and prev_day.get("bb_pct") is not None:
        bb_above_yesterday = prev_day["bb_pct"] > 100
        if bb_above_today and bb_above_yesterday:
            conditions.append(("ok", f"BB 상단 2일 연속 (오늘 {bb_pct:.1f}%, 전일 {prev_day['bb_pct']:.1f}%)"))
        else:
            conditions.append(("no", f"BB 상단 2일 미충족 (오늘 {bb_pct:.1f}%, 전일 {prev_day['bb_pct']:.1f}%)"))
    else:
        conditions.append(("no", f"BB 상단: 전일 이력 없음 (오늘 {bb_pct:.1f}%)" if bb_pct is not None else "BB N/A"))

    if change_3d is not None and change_3d >= 10:
        conditions.append(("ok", f"3일내 +{change_3d:.1f}% ≥ 10%"))
    else:
        conditions.append(("no", f"3일내 {change_3d:+.1f}%" if change_3d else "3일 변동 N/A"))

    triggered = any(c[0] == "ok" for c in conditions)
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
        conditions.append(("no", f"MA20 이탈 → {'MACD bullish' if bullish else 'hist 회복 중'} 면제"))
    elif ma20_below_2d and macd_decreasing:
        conditions.append(("ok", f"MA20 이탈 2일 + MACD hist 감소"))
    else:
        if not ma20_below_2d:
            conditions.append(("no", "MA20 이탈 2일 미충족"))
        else:
            conditions.append(("no", "MA20 이탈 2일이지만 MACD hist 비감소"))

    # ② Higher Low 하향 돌파  [bullish/hist회복 시 면제]
    if bullish or hist_recovering:
        conditions.append(("no", f"Higher Low → {'MACD bullish' if bullish else 'hist 회복 중'} 면제"))
    else:
        price = d.get("price", 0)
        dbl = d.get("double_bottom", {})
        if isinstance(dbl, dict) and dbl.get("low1") and dbl.get("low2"):
            low1_p = dbl["low1"]["price"]
            low2_p = dbl["low2"]["price"]
            was_higher_low = low2_p > low1_p
            price_broke = price < low2_p
            if was_higher_low and price_broke:
                conditions.append(("ok",
                    f"Higher Low 붕괴: 현재가 ${price:.2f} < "
                    f"저점2 ${low2_p:.2f}({dbl['low2']['date']}) "
                    f"(저점1 ${low1_p:.2f})"))
            elif was_higher_low:
                conditions.append(("no",
                    f"Higher Low 유지: ${price:.2f} > 저점2 ${low2_p:.2f}"))
            else:
                conditions.append(("no",
                    f"Higher Low 미형성 (저점2 ${low2_p:.2f} ≤ 저점1 ${low1_p:.2f})"))
        else:
            conditions.append(("na", "Higher Low: 저점 데이터 부족"))

    # ③ MACD 데스크로스 + hist 3일 감소  [v5.2: MACD < 0 조건 삭제 → 조기 감지]
    if macd is not None and macd_signal is not None:
        macd_below_signal = macd < macd_signal
        hist_3d_decreasing = "decreasing" in macd_hist_trend
        if macd_below_signal and hist_3d_decreasing:
            conditions.append(("ok", f"MACD 데스크로스 ({macd:.4f} < signal {macd_signal:.4f}) + hist 감소"))
        else:
            reason_parts = []
            if not macd_below_signal:
                reason_parts.append(f"MACD({macd:.4f}) > signal({macd_signal:.4f})")
            if not hist_3d_decreasing:
                reason_parts.append(f"hist 비감소({macd_hist_trend})")
            conditions.append(("no", f"MACD 데스크로스: {', '.join(reason_parts)}"))
    else:
        conditions.append(("na", "MACD 데이터 없음"))

    triggered = any(c[0] == "ok" for c in conditions)
    return triggered, conditions


def _check_take_profit_1(d: dict, prev_day: dict | None) -> tuple[bool, list]:
    """TAKE_PROFIT_1 — 상승 둔화 (1차 익절). 3개 중 2개 충족. MACD 가드 적용."""
    macd_hist_trend_l2 = d.get("macd_hist_trend", "")
    hist_recovering_l2 = "increasing" in macd_hist_trend_l2
    if _is_macd_bullish(d):
        return False, [("no", "MACD 골든크로스 + hist 증가 — 모멘텀 회복 중 (TP1 면제)")]
    if hist_recovering_l2:
        return False, [("no", f"MACD hist 회복 중 ({macd_hist_trend_l2}) — 하락 모멘텀 둔화 (TP1 면제)")]

    conditions = []
    count = 0
    macd_hist_trend = d.get("macd_hist_trend", "")
    price_vs_ma20 = d.get("price_vs_ma20", "")
    rsi = d.get("rsi14")

    # ① MACD 히스토그램 3일 연속 감소
    if "decreasing" in macd_hist_trend:
        conditions.append(("ok", f"MACD hist 3일 감소 ({macd_hist_trend})"))
        count += 1
    else:
        conditions.append(("no", f"MACD hist 추세: {macd_hist_trend}"))

    # ② RSI 다이버전스: 전일 RSI > 금일 RSI, 둘 다 ≥50 (고점 영역 하락)  [v5.1 신규]
    if prev_day and rsi is not None:
        prev_rsi = prev_day.get("rsi")
        if prev_rsi is not None and prev_rsi > rsi and prev_rsi >= 50 and rsi >= 50:
            conditions.append(("ok", f"RSI 다이버전스: {prev_rsi:.1f} → {rsi:.1f} (고점 하락)"))
            count += 1
        else:
            conditions.append(("no", f"RSI 다이버전스 미충족 ({prev_rsi:.1f} → {rsi:.1f})" if prev_rsi else "전일 RSI N/A"))
    else:
        conditions.append(("na", "RSI 다이버전스 (전일 이력 없음)"))

    # ③ 종가 MA20 1일 이탈
    if price_vs_ma20 == "below":
        conditions.append(("ok", "종가 MA20 하회"))
        count += 1
    else:
        conditions.append(("no", "종가 MA20 상회"))

    triggered = count >= 2
    return triggered, conditions


# ═══════════════════════════════════════════════════════
#  ENTRY 판정 — Growth v2.3 (v5.1 개선)
# ═══════════════════════════════════════════════════════

def _check_entry_growth(d: dict, reject_rsi_threshold: float = 55) -> tuple[str | None, list]:
    """Growth 종목 Entry 판정. 3rd → 2nd → 1st → WATCH 순.
    reject_rsi_threshold: 거부 RSI 임계값 (Growth=55, Value=70)"""
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
    reject_drop = change_pct <= -5.0
    if reject_drop:
        conditions.append(("no", f"[거부] 당일 {change_pct:+.1f}% (≤-5% 급락)"))
        return _growth_watch_fallback(d, conditions)

    # ── 3rd BUY (50%) — ALL 충족 (RSI 거부 미적용 — 추세 확정 단계) ──
    c3 = []
    above_ma20_2d = price_vs_ma20 == "above"
    c3.append(("ok" if above_ma20_2d else "no", f"가격 {'>' if above_ma20_2d else '<'} MA20"))
    macd_above_zero = macd is not None and macd > 0
    macd_golden_c3 = macd is not None and macd_signal is not None and macd > macd_signal
    macd_c3_ok = macd_above_zero and macd_golden_c3
    c3.append(("ok" if macd_c3_ok else "no",
               f"MACD {macd:.4f} {'>' if macd_above_zero else '<'} 0, "
               f"{'>' if macd_golden_c3 else '<'} signal {macd_signal:.4f}"
               if macd is not None and macd_signal is not None else "MACD N/A"))
    vol_13 = volume_ratio is not None and volume_ratio >= 1.3
    c3.append(("ok" if vol_13 else "no", f"거래량비 {volume_ratio:.2f}x {'≥' if vol_13 else '<'} 1.3" if volume_ratio else "거래량 N/A"))
    rsi_above_55 = rsi is not None and rsi > 55
    c3.append(("ok" if rsi_above_55 else "no", f"RSI {rsi:.1f} {'>' if rsi_above_55 else '≤'} 55" if rsi else "RSI N/A"))
    # 3rd BUY 추가 거부: RSI > 75
    if rsi is not None and rsi > 75:
        c3.append(("no", f"[거부] RSI {rsi:.1f} > 75"))

    if all(c[0] == "ok" for c in c3) and not (rsi and rsi > 75):
        return "3rd_BUY", c3

    # ── 2nd BUY (30%) — ALL 충족  [v5.1b: 이중바닥 diff≥3%, MACD 골든크로스 필수] ──
    c2 = []
    # ① 이중 바닥 확인 (diff_pct ≥ 3% 이상만 유효)
    dbl = d.get("double_bottom", {})
    dbl_detected = dbl.get("detected", False) if isinstance(dbl, dict) else False
    dbl_diff = dbl.get("diff_pct", 99) if isinstance(dbl, dict) else 99
    dbl_valid = dbl_detected and dbl_diff <= 3.0
    if isinstance(dbl, dict) and dbl.get("low1"):
        c2.append(("ok" if dbl_valid else "no",
                   f"이중바닥: {dbl['low1']['price']}({dbl['low1']['date']}) vs "
                   f"{dbl['low2']['price']}({dbl['low2']['date']}) 차이 {dbl_diff:.1f}%"
                   f"{'' if dbl_valid else ' (3% 초과 → 무효)' if dbl_detected else ''}"))
    else:
        c2.append(("no", "이중 바닥 미감지 (최근 60일 로컬 최저점 2개 미만)"))
    # ② RSI > 35
    rsi_rising_3d = rsi is not None and rsi > 35
    c2.append(("ok" if rsi_rising_3d else "no", f"RSI {rsi:.1f} {'>' if rsi_rising_3d else '≤'} 35" if rsi else "RSI N/A"))
    # ③ MACD 골든크로스 필수 (hist 증가만으로는 불충분)
    macd_golden = macd is not None and macd_signal is not None and macd > macd_signal
    c2.append(("ok" if macd_golden else "no",
               f"MACD 골든크로스: {macd:.4f} {'>' if macd_golden else '<'} signal {macd_signal:.4f}"
               if macd is not None and macd_signal is not None else "MACD N/A"))
    # ④ 거래량 ≥ 1.2배
    vol_12 = volume_ratio is not None and volume_ratio >= 1.2
    c2.append(("ok" if vol_12 else "no", f"거래량비 {volume_ratio:.2f}x {'≥' if vol_12 else '<'} 1.2" if volume_ratio else "거래량 N/A"))

    if all(c[0] == "ok" for c in c2):
        return "2nd_BUY", c2

    # [v5.1b] RSI 거부 — 1st BUY에만 적용 (2nd/3rd는 추세 확인 단계라 면제)
    reject_rsi = rsi is not None and rsi > reject_rsi_threshold
    if reject_rsi:
        conditions.append(("no", f"[거부] RSI {rsi:.1f} > {reject_rsi_threshold} (1st BUY 금지)"))
        return _growth_watch_fallback(d, conditions)

    # ── 1st BUY (20%) — 필수 3개 + 선택 2/3  [v5.1b: 과매도 확인 강화] ──
    # [필수①] RSI ≤ 38 (과매도 확인)
    rsi_ok = rsi is not None and rsi <= 38
    conditions.append(("ok" if rsi_ok else "no",
                       f"[필수] RSI {rsi:.1f} {'≤' if rsi_ok else '>'} 38" if rsi else "[필수] RSI N/A"))

    # [필수②] 가격 < MA20 (조정 확인)
    below_ma20 = price_vs_ma20 == "below"
    conditions.append(("ok" if below_ma20 else "no",
                       f"[필수] 가격 {'<' if below_ma20 else '≥'} MA20"))

    # [필수③] MACD hist 2일 연속 증가 (반전 시작)
    hist_increasing = "increasing" in macd_hist_trend
    conditions.append(("ok" if hist_increasing else "no",
                       f"[필수] MACD hist 2일 증가: {macd_hist_trend}"))

    mandatory_ok = rsi_ok and below_ma20 and hist_increasing

    # [선택] 3개 중 2개 이상
    opt_count = 0
    opt_conds = []

    adx_ok = adx is not None and adx <= 25
    opt_conds.append(("ok" if adx_ok else "no", f"ADX {adx:.1f} {'≤' if adx_ok else '>'} 25" if adx else "ADX N/A"))
    if adx_ok: opt_count += 1

    bb_near = False
    if bb_lower and price > 0:
        bb_threshold = bb_lower * 1.02
        bb_near = price <= bb_threshold
        bb_dist = (price - bb_lower) / bb_lower * 100
        opt_conds.append(("ok" if bb_near else "no", f"종가 {'≤' if bb_near else '>'} BB하단x1.02 (거리 {bb_dist:.1f}%)"))
    else:
        opt_conds.append(("na", "BB 하단 N/A"))
    if bb_near: opt_count += 1

    rebound = change_pct >= 2.0
    opt_conds.append(("ok" if rebound else "no", f"전일 대비 {change_pct:+.1f}% {'≥' if rebound else '<'} +2%"))
    if rebound: opt_count += 1

    conditions.extend(opt_conds)

    if mandatory_ok and opt_count >= 2:
        return "1st_BUY", conditions

    # WATCH: 필수 2개 이상 + 선택 1개 이상
    mandatory_count = sum([rsi_ok, below_ma20, hist_increasing])
    if mandatory_count >= 2 and opt_count >= 1:
        return "WATCH", conditions
    if mandatory_count >= 1 and opt_count >= 2:
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

    # [거부] RSI > 70 (전 단계 공통)
    reject = rsi is not None and rsi > 70
    if reject:
        conditions.append(("no", f"[거부] RSI {rsi:.1f} > 70 (전 단계 매수 금지)"))
        return None, conditions

    # ── 1st BUY 조건 평가  [v5.1b: 필수 2개 + 선택 1/3 → 확실한 조정에서만 진입] ──
    # [필수①] RSI ≤ 35 (과매도 확인)
    rsi_ok = rsi is not None and rsi <= 35
    conditions.append(("ok" if rsi_ok else "no", f"[필수] RSI {rsi:.1f} {'≤' if rsi_ok else '>'} 35" if rsi else "RSI N/A"))

    # [필수②] 52주 고점 대비 -5% 이상 조정
    dd_ok = drawdown_52w <= -5.0
    conditions.append(("ok" if dd_ok else "no", f"[필수] 52주 고점 대비 {drawdown_52w:.1f}% {'≤' if dd_ok else '>'} -5%"))

    # [선택] 3개 중 1개 이상
    opt_count = 0

    # 가격 < MA20
    below_ma20 = price_vs_ma20 == "below"
    conditions.append(("ok" if below_ma20 else "no", f"가격 {'<' if below_ma20 else '≥'} MA20"))
    if below_ma20: opt_count += 1

    # BB 하단 근접
    bb_near = False
    if bb_lower and price > 0:
        bb_dist = (price - bb_lower) / bb_lower * 100
        bb_near = bb_dist <= 5
        conditions.append(("ok" if bb_near else "no", f"BB 하단 거리 {bb_dist:.1f}%"))
    else:
        conditions.append(("na", "BB 하단 N/A"))
    if bb_near: opt_count += 1

    # 하락 모멘텀 둔화 (MACD hist 감소폭 축소)
    momentum_slowing = False
    if len(macd_hist_3d) >= 2:
        diffs = [macd_hist_3d[i] - macd_hist_3d[i - 1] for i in range(1, len(macd_hist_3d))]
        if len(diffs) >= 2 and diffs[-1] > diffs[-2]:
            momentum_slowing = True
        elif len(diffs) == 1 and diffs[0] > 0:
            momentum_slowing = True
    conditions.append(("ok" if momentum_slowing else "no",
                       f"하락 모멘텀 {'둔화' if momentum_slowing else '지속'}"))
    if momentum_slowing: opt_count += 1

    # ── 3rd BUY (50%) — ALL 충족  [v5.1b: RSI>55, MACD 골든크로스+0선 돌파] ──
    macd = d.get("macd")
    macd_signal_val = d.get("macd_signal")
    c3 = []
    above_ma20 = price_vs_ma20 == "above"
    c3.append(("ok" if above_ma20 else "no", f"가격 {'>' if above_ma20 else '<'} MA20"))
    if above_ma20: pass
    rsi_55 = rsi is not None and rsi > 55
    c3.append(("ok" if rsi_55 else "no", f"RSI {rsi:.1f} {'>' if rsi_55 else '≤'} 55" if rsi else "RSI N/A"))
    macd_above_zero = macd is not None and macd > 0
    macd_golden_etf = macd is not None and macd_signal_val is not None and macd > macd_signal_val
    macd_c3_ok = macd_above_zero and macd_golden_etf
    c3.append(("ok" if macd_c3_ok else "no",
               f"MACD {macd:.4f} {'>' if macd_above_zero else '<'} 0, "
               f"{'>' if macd_golden_etf else '<'} signal {macd_signal_val:.4f}"
               if macd is not None and macd_signal_val is not None else "MACD N/A"))
    if all(c[0] == "ok" for c in c3):
        return "3rd_BUY", c3

    # ── 2nd BUY (30%) — Pick 3 of 4 ──
    macd_signal_val = d.get("macd_signal")
    c2_count = 0
    c2 = []
    rsi_42 = rsi is not None and rsi > 42
    c2.append(("ok" if rsi_42 else "no", f"RSI {rsi:.1f} {'>' if rsi_42 else '≤'} 42" if rsi else "RSI N/A"))
    if rsi_42: c2_count += 1
    macd_golden = macd is not None and macd_signal_val is not None and macd > macd_signal_val
    c2.append(("ok" if macd_golden else "no", f"MACD 골든크로스 {'발생' if macd_golden else '아직 미발생'} ({macd:.4f} vs Signal {macd_signal_val:.4f})" if macd and macd_signal_val else "MACD N/A"))
    if macd_golden: c2_count += 1
    above_or_near_ma20 = price_vs_ma20 == "above"
    c2.append(("ok" if above_or_near_ma20 else "no", f"MA20 {'위에 있거나 근접해요' if above_or_near_ma20 else '아래 (이탈 중)'}"))
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
            hl_note = (f"Higher Low: 단기 하락멈춤 + 중기저점상승 "
                       f"(${low2_p:.2f}({low2_d}) > ${low1_p:.2f}({low1_d}))")
        elif not sig_low_stopped and not mid_term_hl:
            hl_note = (f"Higher Low 미형성: 단기 저점갱신 중 + 중기저점하락 "
                       f"(${low2_p:.2f}({low2_d}) ≤ ${low1_p:.2f}({low1_d}))")
        elif not sig_low_stopped:
            hl_note = f"Higher Low 미형성: 단기 저점갱신 중 (오늘 최근3일 최저 미충족)"
        else:
            hl_note = (f"Higher Low 미형성: 중기저점 하락 중 "
                       f"(${low2_p:.2f}({low2_d}) ≤ ${low1_p:.2f}({low1_d}))")
        c2.append(("ok" if higher_low else "no", hl_note))
        if higher_low: c2_count += 1
    else:
        c2.append(("na", "Higher Low: 저점 데이터 부족 (60일 미만)"))
    if c2_count >= 3:
        return "2nd_BUY", c2

    # ── 1st BUY (20%) — 필수 2개(RSI≤35 + DD≤-5%) + 선택 1/3  [v5.1b 강화] ──
    if rsi_ok and dd_ok and opt_count >= 1:
        return "1st_BUY", conditions
    # WATCH: 필수 1개 + 선택 1개 이상
    if (rsi_ok or dd_ok) and opt_count >= 1:
        return "WATCH", conditions
    return None, conditions


# ═══════════════════════════════════════════════════════
#  ENTRY 판정 — Value v2.4 (독립 구현, 거부 RSI>70)  [v5.1]
# ═══════════════════════════════════════════════════════

def _check_entry_value(d: dict) -> tuple[str | None, list]:
    """Value 종목 Entry 판정. Growth와 동일 구조, 거부 RSI>70."""
    return _check_entry_growth(d, reject_rsi_threshold=70)


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
        conditions.append(("na", "30Y 금리 데이터 없음"))
        return None, conditions

    # 1st BUY: 30Y ≥ 5.0% AND RSI ≤ 35
    y_ok = yield_30y >= 5.0
    r_ok = rsi is not None and rsi <= 35
    conditions.append(("ok" if y_ok else "no", f"30Y 금리 {yield_30y:.3f}% {'≥' if y_ok else '<'} 5.0%"))
    conditions.append(("ok" if r_ok else "no", f"RSI {rsi:.1f} {'≤' if r_ok else '>'} 35" if rsi else "RSI N/A"))

    if y_ok and r_ok:
        return "1st_BUY", conditions

    # BOND_WATCH: 30Y 4.9~5.0%
    if 4.9 <= yield_30y < 5.0:
        conditions.append(("ok", f"30Y {yield_30y:.3f}% — 트리거 직전 (4.9~5.0%)"))
        return "BOND_WATCH", conditions

    return None, conditions


# ═══════════════════════════════════════════════════════
#  ENTRY 판정 — Metal v2.6
# ═══════════════════════════════════════════════════════

def _check_entry_metal(d: dict, macro: dict) -> tuple[str | None, list]:
    """Metal(SLV) Entry 판정. Pick 2 of 4."""
    rsi = d.get("rsi14")
    price_vs_ma20 = d.get("price_vs_ma20", "")
    vix = macro.get("VIX", 0)
    bb_lower = d.get("bb_lower")
    price = d.get("price", 0)

    conditions = []
    count = 0

    rsi_ok = rsi is not None and rsi <= 40
    conditions.append(("ok" if rsi_ok else "no", f"RSI {rsi:.1f} {'≤' if rsi_ok else '>'} 40" if rsi else "RSI N/A"))
    if rsi_ok:
        count += 1

    below_ma20 = price_vs_ma20 == "below"
    conditions.append(("ok" if below_ma20 else "no", f"가격 {'<' if below_ma20 else '≥'} MA20"))
    if below_ma20:
        count += 1

    # VIX > 25 (변경③: 지정학 리스크 → VIX 대체)
    vix_ok = vix > 25
    conditions.append(("ok" if vix_ok else "no", f"VIX {vix:.1f} {'>' if vix_ok else '≤'} 25"))
    if vix_ok:
        count += 1

    # BB 하단 근접
    bb_near = False
    if bb_lower and price > 0:
        bb_dist = (price - bb_lower) / bb_lower * 100
        bb_near = bb_dist <= 5
        conditions.append(("ok" if bb_near else "no", f"BB 하단 거리 {bb_dist:.1f}%"))
    else:
        conditions.append(("na", "BB 하단 N/A"))
    if bb_near:
        count += 1

    # RSI > 80 → TOP_SIGNAL 강제 (별도 처리)
    if rsi is not None and rsi > 80:
        conditions.append(("no", f"[주의] RSI {rsi:.1f} > 80 — TOP_SIGNAL 영역"))

    if count >= 2:
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


def _get_prev_day_data(ticker: str, history: dict) -> dict | None:
    """signals_history.json에서 전일 데이터 가져오기"""
    dates = sorted(history.keys())
    # _meta, _macro 키 제외
    dates = [dt for dt in dates if not dt.startswith("_")]
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
                tp2_conditions.append(("ok", f"MACD 데스크로스 ({macd:.4f}) + hist 감소"))
                tp2_hit = True
    if tp2_hit:
        return {"signal": "TAKE_PROFIT_2", "note": _make_note(tp2_conditions), "conditions": tp2_conditions}

    # TP1: hist 감소 + MA20 이탈 (2/2)
    if not bullish and not hist_recovering:
        tp1_count = 0
        tp1_conditions = []
        if "decreasing" in macd_hist_trend:
            tp1_conditions.append(("ok", f"MACD hist 감소 ({macd_hist_trend})"))
            tp1_count += 1
        if d.get("price_vs_ma20") == "below":
            tp1_conditions.append(("ok", "종가 MA20 하회"))
            tp1_count += 1
        if tp1_count >= 2:
            return {"signal": "TAKE_PROFIT_1", "note": _make_note(tp1_conditions), "conditions": tp1_conditions}

    return None


# ═══════════════════════════════════════════════════════
#  메인 판정 함수
# ═══════════════════════════════════════════════════════

def judge_ticker(ticker: str, d: dict, macro: dict, prev_day: dict | None) -> dict:
    """
    단일 종목 시그널 판정.
    반환: {signal, note, conditions: [(ok/no/na, text), ...]}
    """
    group = get_strategy_group(ticker)

    # BIL → 항상 CASH
    if group == "cash":
        return {
            "signal": "CASH",
            "note": "현금성 자산",
            "conditions": [("ok", "현금성 자산 — 시그널 판정 대상 아님")],
        }

    # ── Exit(익절) 체크 (TOP → TP2 → TP1)  [v5.2: 익절 전용 재설계] ──
    top_hit, top_conds = _check_top_signal(d, prev_day)
    if top_hit:
        return {"signal": "TOP_SIGNAL", "note": _make_note(top_conds), "conditions": top_conds}

    # 고점 영역 게이트: DD > -5% 일 때만 TP 시그널 허용
    if _is_profit_zone(d):
        tp2_hit, tp2_conds = _check_take_profit_2(d, prev_day)
        if tp2_hit:
            return {"signal": "TAKE_PROFIT_2", "note": _make_note(tp2_conds), "conditions": tp2_conds}

        tp1_hit, tp1_conds = _check_take_profit_1(d, prev_day)
        if tp1_hit:
            return {"signal": "TAKE_PROFIT_1", "note": _make_note(tp1_conds), "conditions": tp1_conds}

    # ── Entry 체크 (카테고리별) ──
    if group == "growth":
        signal, conds = _check_entry_growth(d)
    elif group == "etf":
        signal, conds = _check_entry_etf(d)
    elif group == "value":
        signal, conds = _check_entry_value(d)
    elif group == "bond":
        signal, conds = _check_entry_bond(d, macro)
    elif group == "metal":
        signal, conds = _check_entry_metal(d, macro)
    else:
        signal, conds = None, []

    if signal:
        return {"signal": signal, "note": _make_note(conds), "conditions": conds}

    # ── 해당 없으면 HOLD ──
    return {
        "signal": "HOLD",
        "note": "Exit/Entry 조건 미충족",
        "conditions": [("na", "Exit/Entry 조건 미충족 — 보유 유지")],
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
                "conditions": [("no", d["error"])],
            }
            continue

        prev_day = _get_prev_day_data(ticker, history)
        result = judge_ticker(ticker, d, macro, prev_day)

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
