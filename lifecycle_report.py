# lifecycle_report.py
"""Phase A — lifecycle page renderer.

generate_lifecycle_pages(us_result, kr_result, output_dir) → {market: path}
"""
from __future__ import annotations

import os
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from lifecycle_config import (
    LIFECYCLE_VERSION,
    PULLBACK_MAX_DIST_FROM_EMA9, EXTENDED_DIST_FROM_EMA9, EXTENDED_RSI_MIN,
    RISK_OVERHEAT_RSI, RISK_PARABOLIC_RET_1D, RISK_PARABOLIC_VOL_RATIO,
    TRIGGER_CONFIRM_VOL_RATIO_MIN, TRIGGER_CONFIRM_CLOSE_HIGH_RATIO,
    BASE_FORMING_DAYS_MIN, BASE_FORMING_DAYS_MAX,
)
from lifecycle_history import derive_fields
from lifecycle_signal import DECISION_LABELS, DECISION_TOOLTIPS


def _lookup_ticker_name(ticker: str, market: str) -> str:
    """Resolve ticker → human-readable name. Falls back to ticker on miss.

    KR uses market_scanner.KOSPI_NAMES (한글). US returns ticker as-is —
    name maps exist (SP100_NAMES etc.) but tickers are already the more
    recognized identifier in US markets.
    """
    try:
        if market == "KR":
            from market_scanner import KOSPI_NAMES
            return KOSPI_NAMES.get(ticker, ticker)
    except ImportError:
        pass
    return ticker


def _attach_derived(snap: dict, ticker: str,
                     lifecycle_state: Optional[dict]) -> dict:
    out = dict(snap)
    if lifecycle_state and ticker in (lifecycle_state.get("tickers") or {}):
        derived = derive_fields(lifecycle_state["tickers"][ticker])
    else:
        # No lifecycle history for this ticker — infer from today's snapshot.
        # If today's snap already has a trigger (EARLY or CONFIRMED), age = 0
        # (first seen = today). None only when truly no trigger has ever fired.
        trigger = snap.get("trigger", "WAIT")
        if trigger in ("EARLY_TRIGGER", "CONFIRMED_TRIGGER"):
            trigger_age = 0
        else:
            trigger_age = None
        derived = {"setup_streak": 1, "days_in_pullback": 0, "trigger_age_days": trigger_age}
    out["setup_streak"]     = derived["setup_streak"]
    out["days_in_pullback"] = derived["days_in_pullback"]
    out["trigger_age_days"] = derived["trigger_age_days"]

    # Signed distance fields for chip display (raw values are abs).
    # close / ema9 / ema21 are in raw nested dict per lifecycle_signal._make_snapshot.
    raw = snap.get("raw") or {}
    close = raw.get("close")
    e9 = raw.get("ema9")
    e21 = raw.get("ema21")
    out["dist_ema9_signed_pct"] = (
        round((close / e9 - 1) * 100, 2) if (close and e9 and e9 > 0) else None
    )
    out["dist_ema21_signed_pct"] = (
        round((close / e21 - 1) * 100, 2) if (close and e21 and e21 > 0) else None
    )

    # Also surface raw abs value at top-level for verdict_summary max() (avoids
    # needing to dig into raw.* from the helper, keeps _build_verdict_summary lean).
    out["dist_ema9_pct"] = raw.get("dist_ema9_pct")

    return out


def _build_verdict_summary(enter: list, probe: list, watch: list,
                            trending: list, avoid: list) -> dict:
    """Build dynamic narration for the 'Today's Verdict' summary box.

    Branches on which groups are non-empty (ENTER > PROBE > empty > total=0).
    AVOID line is appended whenever AVOID > 0, with max dist_ema9 and max
    rsi14 from the AVOID group inserted as live values.

    Returns:
        {
          "headline":    str,             # 큰 제목
          "narration":   str,             # 1-2 문장 설명
          "avoid_line":  str | None,      # AVOID > 0일 때만, else None
          "action_hint": str,             # 💡 오늘 할 일
        }
    """
    enter_n, probe_n = len(enter), len(probe)
    watch_n, trending_n, avoid_n = len(watch), len(trending), len(avoid)
    total = enter_n + probe_n + watch_n + trending_n + avoid_n

    def _ticker_list(rows: list, limit: int = 5) -> str:
        # Use display name when available (KR Korean name); falls back to ticker
        # for rows that don't have a name attached (unit-test fixtures).
        names = [r.get("name") or r["ticker"] for r in rows[:limit]]
        s = ", ".join(names)
        if len(rows) > limit:
            s += f" 외 {len(rows) - limit}개"
        return s

    if total == 0:
        headline = "⚠ 추적 종목 없음 — 시그널 부재"
        narration = "오늘 평가된 종목이 없습니다 (전 종목 skip 또는 데이터 부족)"
        action_hint = "pipeline 로그 확인"
    elif enter_n > 0:
        headline = f"✅ 오늘 신규 진입 가능 종목 {enter_n}개"
        narration = f"{_ticker_list(enter)}이 확정 트리거 발화 — 풀 진입 검토 가능"
        action_hint = "ENTER 종목 점검 후 비중 결정"
    elif probe_n > 0:
        headline = f"⚡ 분할 진입 가능 종목 {probe_n}개"
        narration = f"{_ticker_list(probe)}이 약한 트리거 — 절반 진입 검토"
        action_hint = "PROBE 종목 절반 비중 진입"
    else:
        headline = "⏸ 오늘은 신규 진입할 종목이 없습니다 (ENTER 0, PROBE 0)"
        narration = (
            f"WATCH {watch_n}개는 트리거 발화 대기, "
            f"TRENDING {trending_n}개는 다음 눌림목까지 관망"
        )
        action_hint = "WATCH 트리거 발화 대기 — 오늘은 신규 매수 없음"

    avoid_line = None
    if avoid_n > 0:
        # _ticker_list uses ', ' separator; mockup uses ' · ' for AVOID line.
        # Use display name when available (KR Korean name); falls back to ticker.
        names = [r.get("name") or r["ticker"] for r in avoid[:5]]
        tickers = " · ".join(names)
        if avoid_n > 5:
            tickers += f" 외 {avoid_n - 5}개"
        max_dist = max((r.get("dist_ema9_pct") or 0) for r in avoid)
        max_rsi = max((r.get("raw", {}).get("rsi14") or 0) for r in avoid)
        avoid_line = (
            f"🔴 {tickers} {avoid_n}종목은 매수 금지 — "
            f"9일선 +{max_dist:.1f}% 이격, RSI {max_rsi:.0f}+로 과확장 상태"
        )

    return {
        "headline":    headline,
        "narration":   narration,
        "avoid_line":  avoid_line,
        "action_hint": action_hint,
    }


def build_page_context(result: dict,
                         lifecycle_state: Optional[dict] = None) -> dict:
    market = result.get("market", "US")
    enter, probe, watch, trending, avoid, broken_table = [], [], [], [], [], []
    new_confirmed = []
    for ticker, snap in (result.get("snapshots") or {}).items():
        row = _attach_derived(snap, ticker, lifecycle_state)
        row["ticker"] = ticker
        # KR: 종목명 (한글) — fallback to ticker. US: ticker as-is.
        row["name"] = _lookup_ticker_name(ticker, market)
        d = snap["decision"]
        s = snap["setup"]
        if s == "BROKEN":
            broken_table.append(row)
            continue
        if d == "ENTER":
            enter.append(row)
            if (row["trigger_age_days"] == 0) and snap["trigger"] == "CONFIRMED_TRIGGER":
                new_confirmed.append(row)
        elif d == "PROBE":
            probe.append(row)
        elif d == "WATCH":
            watch.append(row)
        elif d == "TRENDING":
            trending.append(row)
        else:
            avoid.append(row)

    enter.sort(key=lambda r: ((r["trigger_age_days"] if r["trigger_age_days"] is not None else 999),
                               -(r["raw"].get("volume_ratio") or 0)))
    probe.sort(key=lambda r: -(r["raw"].get("volume_ratio") or 0))
    watch.sort(key=lambda r: -(r["setup_streak"] or 0))
    trending.sort(key=lambda r: -(r["setup_streak"] or 0))

    return {
        "market":       result.get("market", "US"),
        "as_of":        result.get("as_of"),
        "version":      LIFECYCLE_VERSION,
        "new_confirmed": new_confirmed,
        "enter":        enter,
        "probe":        probe,
        "watch":        watch,
        "trending":     trending,
        "avoid":        avoid,
        "broken_table": broken_table,
        "transitions":  (result.get("transitions") or [])[-50:],
        "DECISION_LABELS":   DECISION_LABELS,
        "DECISION_TOOLTIPS": DECISION_TOOLTIPS,
        "verdict_summary":   _build_verdict_summary(enter, probe, watch, trending, avoid),
        "lifecycle_thresholds": {
            "PULLBACK_MAX_DIST_FROM_EMA9":      PULLBACK_MAX_DIST_FROM_EMA9,
            "EXTENDED_DIST_FROM_EMA9":          EXTENDED_DIST_FROM_EMA9,
            "EXTENDED_RSI_MIN":                 EXTENDED_RSI_MIN,
            "RISK_OVERHEAT_RSI":                RISK_OVERHEAT_RSI,
            "RISK_PARABOLIC_RET_1D":            RISK_PARABOLIC_RET_1D,
            "RISK_PARABOLIC_VOL_RATIO":         RISK_PARABOLIC_VOL_RATIO,
            "TRIGGER_CONFIRM_VOL_RATIO_MIN":    TRIGGER_CONFIRM_VOL_RATIO_MIN,
            "TRIGGER_CONFIRM_CLOSE_HIGH_RATIO": TRIGGER_CONFIRM_CLOSE_HIGH_RATIO,
            "BASE_FORMING_DAYS_MIN":            BASE_FORMING_DAYS_MIN,
            "BASE_FORMING_DAYS_MAX":            BASE_FORMING_DAYS_MAX,
        },
    }


def _render(market: str, result: dict, output_dir: str,
              template_dir: Optional[str], lifecycle_state: Optional[dict],
              nav_ctx: Optional[dict] = None) -> str:
    if template_dir is None:
        template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)

    # Custom filters for chip rendering
    def _signed_pct(x):
        """Format signed percentage: +5.3% / -2.1% / 0.0% / — (None)."""
        if x is None:
            return "—"
        return f"{x:+.1f}%"

    def _x_fmt(x):
        """Format multiplier: 1.5× / — (None)."""
        if x is None:
            return "—"
        return f"{x:.1f}×"

    def _trig_age_label(d):
        """Format trigger age: 오늘 / 어제 / N일전 / —."""
        if d is None:
            return "—"
        if d == 0:
            return "오늘"
        if d == 1:
            return "어제"
        return f"{d}일전"

    env.filters["signed_pct"] = _signed_pct
    env.filters["x_fmt"] = _x_fmt
    env.filters["trig_age_label"] = _trig_age_label

    tmpl = env.get_template(f"lifecycle_{market.lower()}.html")
    ctx = build_page_context(result, lifecycle_state=lifecycle_state)

    # Merge nav vars for sidebar rendering
    if nav_ctx:
        ctx.update(nav_ctx)
    # Set active_nav for current page
    ctx["active_nav"] = f"lifecycle_{market.lower()}"

    html = tmpl.render(**ctx)
    os.makedirs(output_dir, exist_ok=True)
    fname = f"lifecycle_{market.lower()}_{result['as_of']}.html"
    path = os.path.join(output_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def generate_lifecycle_pages(*, us_result: Optional[dict],
                                kr_result: Optional[dict],
                                output_dir: str,
                                template_dir: Optional[str] = None,
                                us_state: Optional[dict] = None,
                                kr_state: Optional[dict] = None,
                                nav_ctx: Optional[dict] = None) -> dict[str, str]:
    """Render lifecycle pages for US and/or KR markets.

    Args:
        us_result: lifecycle scan result for US, or None
        kr_result: lifecycle scan result for KR, or None
        output_dir: directory to write HTML files to
        template_dir: Jinja2 templates directory (default: ./templates)
        us_state: lifecycle history state for US (from lifecycle_history)
        kr_state: lifecycle history state for KR (from lifecycle_history)
        nav_ctx: optional dict with sidebar nav keys (nav_portfolio, nav_wife,
                 nav_scanner, nav_backtest, nav_trend, has_momentum_us,
                 momentum_us_url, etc.) — passed directly into template context
    """
    out: dict[str, str] = {}
    if us_result and us_result.get("snapshots"):
        out["us"] = _render("US", us_result, output_dir, template_dir, us_state, nav_ctx)
    if kr_result and kr_result.get("snapshots"):
        out["kr"] = _render("KR", kr_result, output_dir, template_dir, kr_state, nav_ctx)
    return out
