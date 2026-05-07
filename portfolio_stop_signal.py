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


# ─── Entry point — Pipeline Step 4c3에서 호출 ──────────────

import os
from datetime import datetime
from portfolio_stop_config import (
    ANCHOR_DATE, NEW_POSITION_NOISE_DAYS,
)
from portfolio_stop_history import (
    load_stop_history, save_stop_history,
    update_highest_close_safe, evaluate_lifecycle,
    bootstrap_first_run, append_snapshot, prune_old_snapshots,
)


def _is_new_position(entry_date: str, today_str: str) -> bool:
    """Calendar days 기준 — entry_date 후 NEW_POSITION_NOISE_DAYS 이내."""
    try:
        a = datetime.strptime(today_str, "%Y-%m-%d").date()
        b = datetime.strptime(entry_date, "%Y-%m-%d").date()
        return (a - b).days <= NEW_POSITION_NOISE_DAYS
    except Exception:
        return False


def _gap_pct(close: float, stop: float) -> float:
    if stop and stop > 0:
        return round((close - stop) / stop * 100, 2)
    return 0.0


def _resolve_history_path(project_dir: str, owner: str) -> str:
    fname = ("portfolio_stops.json" if owner == "me"
             else f"portfolio_stops_{owner}.json")
    return os.path.join(project_dir, "history", fname)


def generate_portfolio_stop_signals(
    project_dir: str, owner: str,
    market_data: dict, portfolio: list,
    today: str | None = None,
    history_path: str | None = None,
) -> dict:
    """Pipeline Step 4c3 entry point.

    인자:
      project_dir: 프로젝트 루트
      owner: "me" | "wife" | ...
      market_data: fetch_market_data 출력 (atr14 필요)
      portfolio: pipeline._parse_portfolio_for_report 결과
      today: "YYYY-MM-DD" (None이면 오늘)
      history_path: 기본은 project_dir/history/portfolio_stops_{owner}.json

    반환:
      {"status": "ok", "owner", "date", "summary": {...},
       "positions": [...], "changes": [...]}
    """
    from datetime import date as _date
    today_str = today or _date.today().strftime("%Y-%m-%d")
    history_path = history_path or _resolve_history_path(project_dir, owner)

    state = load_stop_history(history_path, owner=owner)
    is_first_run = not state["positions"]

    data = market_data.get("data", {})

    # 1. mode 결정 + new_position_seed 구성
    from portfolio_data import get_ticker_class, get_ticker_name
    portfolio_tickers = set()
    new_seed: dict = {}
    for p in portfolio:
        tk = p["ticker"]
        portfolio_tickers.add(tk)
        d = data.get(tk, {})
        close = d.get("price", 0) or 0
        if close <= 0:
            continue
        mode = get_stop_mode(tk, get_ticker_name(tk),
                              get_ticker_class(tk) or "Other")
        new_seed[tk] = {"close": float(close), "mode": mode,
                         "shares": float(p.get("shares", 0))}

    # 2. 첫 실행 → bootstrap (yfinance YTD high)
    if is_first_run:
        boot = bootstrap_first_run(list(portfolio_tickers),
                                   anchor_date=ANCHOR_DATE,
                                   today_str=today_str)
        for tk in portfolio_tickers:
            if tk in boot and tk in new_seed:
                # bootstrap 성공 + market data 유효 → ANCHOR_DATE 앵커로 등록
                # (둘 중 하나라도 빠지면 lifecycle이 신규로 처리)
                state["positions"][tk] = {
                    "status": "active",
                    "mode": new_seed[tk]["mode"],
                    "entry_date": ANCHOR_DATE,
                    "highest_close": boot[tk]["highest_close"],
                    "highest_close_date": boot[tk]["highest_close_date"],
                    "current_stop": None,
                    "below_stop_count": 0,
                    "shares": new_seed[tk]["shares"],
                    "last_size_change": today_str,
                    "missing_since": None,
                    "last_signal": None,
                    "last_action": None,
                    "last_evaluated": None,
                }
        # bootstrap 실패한 종목은 이후 lifecycle에서 신규 처리됨

    # 3. Lifecycle (신규/재매수/매도 grace)
    evaluate_lifecycle(state, portfolio_tickers, today_str, new_seed)

    # 4. 종목별 평가
    summary = {"HOLD": 0, "TIGHT": 0, "EXIT_READY": 0, "EXIT": 0, "CLOSED": 0}
    positions_out = []
    changes = []

    for tk in sorted(portfolio_tickers):
        pos = state["positions"].get(tk)
        if pos is None or pos.get("status") != "active":
            continue
        d = data.get(tk, {})
        today_close = d.get("price", 0) or 0
        prev_close = d.get("prev_close")
        atr14 = d.get("atr14")
        if today_close <= 0:
            continue

        # 4a. highest_close 안전 갱신 (ticker는 WARN 로그용 — 끝나면 정리)
        pos["ticker"] = tk
        update_highest_close_safe(pos, today_close, prev_close, today_str)
        pos.pop("ticker", None)
        # 4b. shares 갱신 (변경 시만 last_size_change 업데이트)
        new_shares = float(new_seed.get(tk, {}).get("shares", pos.get("shares", 0)))
        if abs(new_shares - pos.get("shares", 0)) > 1e-9:
            pos["shares"] = new_shares
            pos["last_size_change"] = today_str
        # 4c. stop 계산
        stop_price = calculate_stop(pos["highest_close"], atr14,
                                     pos["mode"], tk)
        pos["current_stop"] = stop_price
        # 4d. 시그널 평가
        is_new = _is_new_position(pos["entry_date"], today_str)
        prev_count = pos.get("below_stop_count", 0)
        ev = evaluate_signal(today_close, stop_price, prev_count, is_new)
        # 4e. 상태 갱신
        prev_signal = pos.get("last_signal")
        pos["below_stop_count"] = ev["below_stop_count"]
        pos["last_signal"] = ev["raw_signal"]   # raw 보존
        pos["last_action"] = ev["action"]
        pos["last_evaluated"] = today_str

        # 4f. snapshot 기록 (raw 사용)
        append_snapshot(state, today_str, tk, {
            "signal": ev["raw_signal"],
            "close": round(today_close, 4),
            "stop": stop_price,
            "gap_pct": _gap_pct(today_close, stop_price),
            "below_stop_count": ev["below_stop_count"],
            "is_new_position": is_new,
            "display_downgraded": ev["display_downgraded"],
        })

        summary[ev["raw_signal"]] = summary.get(ev["raw_signal"], 0) + 1

        if prev_signal and prev_signal != ev["raw_signal"]:
            changes.append({"ticker": tk, "from": prev_signal,
                             "to": ev["raw_signal"]})

        positions_out.append({
            "ticker": tk,
            "name": get_ticker_name(tk) or tk,
            "mode": pos["mode"],
            "highest_close": pos["highest_close"],
            "highest_close_date": pos["highest_close_date"],
            "current_close": round(today_close, 4),
            "stop_price": stop_price,
            "gap_pct": _gap_pct(today_close, stop_price),
            "raw_signal": ev["raw_signal"],
            "display_signal": ev["display_signal"],
            "display_downgraded": ev["display_downgraded"],
            "is_new_position": is_new,
            "below_stop_count": ev["below_stop_count"],
            "action": ev["action"],
            "display_action": ev["display_action"],
            "entry_date": pos["entry_date"],
        })

    # 5. closed 항목도 summary에 1회 카운트
    for tk, pos in state["positions"].items():
        if pos.get("status") == "closed" and pos.get("closed_date") == today_str:
            summary["CLOSED"] += 1

    # 6. 정렬: severity desc (EXIT > EXIT_READY > TIGHT > HOLD), 그 안에서 gap_pct asc
    SEV = {"EXIT": 0, "EXIT_READY": 1, "TIGHT": 2, "HOLD": 3}
    positions_out.sort(key=lambda r: (SEV.get(r["display_signal"], 9),
                                        r["gap_pct"], r["ticker"]))

    # 7. snapshot prune + save
    prune_old_snapshots(state, today_str)
    save_stop_history(state, history_path)

    return {
        "status": "ok",
        "owner": owner,
        "date": today_str,
        "summary": summary,
        "positions": positions_out,
        "changes": changes,
        "history_path": history_path,
    }
