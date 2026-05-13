# portfolio_stop_report.py
"""
Portfolio Stop Signal — HTML page renderer (Signal Theme design).

stop_result(dict) → portfolio_stops.html 렌더링.
view-only 필드(is_us, days_label, gap_class, prices format 등) 주입 +
EXIT/EXIT_READY / TIGHT / HOLD 섹션, USD / KRW 통화 분리.
"""

import os
from jinja2 import Environment, FileSystemLoader

from portfolio_stop_config import VERSION, ANCHOR_DATE
from portfolio_data import is_korean_ticker


_SIGNAL_LABEL = {
    "HOLD":       "Hold",
    "TIGHT":      "Tight",
    "EXIT_READY": "Exit Ready",
    "EXIT":       "Exit",
}

_UI_ACTION = {
    "HOLD":       "Hold",
    "TIGHT":      "Trim 10~15%",
    "EXIT_READY": "Trim 30~50%",
    "EXIT":       "Exit",
}

_MODE_FORMULA = {
    "CORE":      "12% fix",
    "DEFENSIVE": "8% fix",
    "MOMENTUM":  "ATR×3",
    "HIGH_VOL":  "ATR×4",
}


# ── 포맷 헬퍼 ─────────────────────────────────────────────

def _fmt_price(value: float, is_us: bool) -> str:
    if is_us:
        return "${:,.2f}".format(value)
    return "{:,}원".format(int(round(value)))


def _fmt_price_short(value: float, is_us: bool) -> str:
    """HOLD chip용 — KR은 '원' 생략."""
    if is_us:
        return "${:,.2f}".format(value)
    return "{:,}".format(int(round(value)))


def _fmt_signed_pct(pct: float) -> str:
    sign = "+" if pct >= 0 else "−"
    digits = 2 if abs(pct) < 0.1 else 1
    return "{}{:.{}f}%".format(sign, abs(pct), digits)


def _fmt_drop_pct(highest: float, stop: float) -> str:
    """High − X.X% — stop이 highest 대비 몇 % 떨어졌는지."""
    if not highest or highest <= 0:
        return "−"
    pct = (stop - highest) / highest * 100  # always negative
    return "−{:.1f}%".format(abs(pct))


def _gap_class(display_signal: str, below_count: int) -> str:
    if display_signal == "EXIT" and below_count >= 2:
        return "red"
    if display_signal in ("EXIT", "EXIT_READY", "TIGHT"):
        return "amber"
    return "green"


def _days_badge(below_count: int) -> tuple[str, str]:
    """(label, class) — count==1: 1D NEW amber, count>=2: ND red."""
    if below_count <= 0:
        return ("", "")
    if below_count == 1:
        return ("1D NEW", "amber")
    return ("{}D".format(below_count), "")


def _action_class(display_signal: str) -> str:
    return "exit" if display_signal == "EXIT" else "trim"


def _mode_label(mode: str) -> str:
    formula = _MODE_FORMULA.get(mode, "")
    if formula:
        return "{} · {}".format(mode, formula)
    return mode


def _change_name(ticker: str, name: str, is_us: bool) -> str:
    if is_us:
        return ticker
    return "{} {}".format(ticker, name)


# ── 표시용 데이터 enrichment ───────────────────────────────

def _enrich_position(r: dict) -> dict:
    tk = r["ticker"]
    is_us = not is_korean_ticker(tk)
    name = r.get("name") or tk
    display_signal = r.get("display_signal", "HOLD")
    below = r.get("below_stop_count", 0)
    gap_pct = r.get("gap_pct", 0)

    days_label, days_cls = _days_badge(below)
    rr = dict(r)
    rr.update({
        "is_us": is_us,
        "display_name": (tk if is_us else name),
        "mode_label": _mode_label(r.get("mode", "")),
        "mode_sub": (_mode_label(r.get("mode", ""))
                     if is_us
                     else "{} · {}".format(tk, _mode_label(r.get("mode", "")))),
        "days_label": days_label,
        "days_class": days_cls,
        "gap_class": _gap_class(display_signal, below),
        "gap_text": _fmt_signed_pct(gap_pct),
        "current_fmt": _fmt_price(r.get("current_close", 0), is_us),
        "highest_fmt": _fmt_price(r.get("highest_close", 0), is_us),
        "stop_fmt": _fmt_price(r.get("stop_price", 0), is_us),
        "drop_pct_text": _fmt_drop_pct(r.get("highest_close", 0),
                                        r.get("stop_price", 0)),
        "action_class": _action_class(display_signal),
        "action_label": _UI_ACTION.get(display_signal, r.get("display_action", "")),
        "signal_label": _SIGNAL_LABEL.get(display_signal, display_signal),
        # HOLD chip
        "chip_tk": (tk if is_us else name),
        "chip_prices": "{} → {}".format(
            _fmt_price_short(r.get("current_close", 0), is_us),
            _fmt_price_short(r.get("stop_price", 0), is_us),
        ),
    })
    return rr


def _enrich_change(c: dict) -> dict:
    tk = c.get("ticker", "")
    is_us = not is_korean_ticker(tk)
    # name lookup via portfolio_data
    from portfolio_data import get_ticker_name
    name = get_ticker_name(tk) or tk
    return {
        "ticker": tk,
        "display_name": _change_name(tk, name, is_us),
        "from_label": _SIGNAL_LABEL.get(c.get("from"), c.get("from", "")),
        "to_label":   _SIGNAL_LABEL.get(c.get("to"),   c.get("to", "")),
    }


def _split_by_currency(rows: list, sort_key) -> tuple[list, list]:
    us = [r for r in rows if r["is_us"]]
    kr = [r for r in rows if not r["is_us"]]
    us.sort(key=sort_key)
    kr.sort(key=sort_key)
    return us, kr


def _anchor_short(anchor_date: str) -> str:
    """2026-01-02 → '01-02'."""
    parts = anchor_date.split("-")
    if len(parts) == 3:
        return "{}-{}".format(parts[1], parts[2])
    return anchor_date


# ── Public entry ─────────────────────────────────────────

def generate_portfolio_stop_page(stop_result: dict, output_dir: str,
                                  anchor_date: str = ANCHOR_DATE,
                                  template_dir: str | None = None,
                                  nav_ctx: dict | None = None) -> str:
    """stop_result(generate_portfolio_stop_signals 반환) → HTML 파일.

    파일명:
      me  → portfolio_stops_<DATE>.html
      其他 → portfolio_stops_<owner>_<DATE>.html

    nav_ctx: shared sidebar context (pipeline._shared_nav). 누락 시 사이드바는
             최소 모드(My Risk만)로 동작.
    """
    if template_dir is None:
        template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)
    tmpl = env.get_template("portfolio_stops.html")

    owner = stop_result.get("owner", "me")
    date_str = stop_result.get("date", "")
    summary = stop_result.get("summary", {})
    positions = [_enrich_position(p) for p in stop_result.get("positions", [])]
    changes = [_enrich_change(c) for c in stop_result.get("changes", [])]

    # 시그널별 분리
    exit_rows = [p for p in positions
                 if p.get("display_signal") in ("EXIT", "EXIT_READY")]
    tight_rows = [p for p in positions if p.get("display_signal") == "TIGHT"]
    hold_rows = [p for p in positions if p.get("display_signal") == "HOLD"]

    # 정렬: EXIT/READY는 gap_pct asc (가장 마이너스 먼저)
    #       TIGHT는 gap asc (가장 작은 양수 먼저)
    #       HOLD는 gap desc (안전한 종목 먼저)
    exit_us,  exit_kr  = _split_by_currency(exit_rows,
                                            sort_key=lambda r: (r["gap_pct"], r["ticker"]))
    tight_us, tight_kr = _split_by_currency(tight_rows,
                                            sort_key=lambda r: (r["gap_pct"], r["ticker"]))
    hold_us,  hold_kr  = _split_by_currency(hold_rows,
                                            sort_key=lambda r: (-r["gap_pct"], r["ticker"]))

    tracked = (summary.get("HOLD", 0) + summary.get("TIGHT", 0)
               + summary.get("EXIT_READY", 0) + summary.get("EXIT", 0))

    summary_padded = {
        "EXIT":       "{:02d}".format(summary.get("EXIT", 0)),
        "EXIT_READY": "{:02d}".format(summary.get("EXIT_READY", 0)),
        "TIGHT":      "{:02d}".format(summary.get("TIGHT", 0)),
        "HOLD":       "{:02d}".format(summary.get("HOLD", 0)),
    }

    ctx = dict(nav_ctx) if nav_ctx else {}
    ctx.update(dict(
        owner=owner,
        date=date_str,
        anchor_date=anchor_date,
        anchor_short=_anchor_short(anchor_date),
        version=VERSION,
        version_short=VERSION.replace("PortfolioStop ", ""),
        summary=summary,
        summary_padded=summary_padded,
        tracked=tracked,
        changes=changes,
        exit_us=exit_us,   exit_kr=exit_kr,
        tight_us=tight_us, tight_kr=tight_kr,
        hold_us=hold_us,   hold_kr=hold_kr,
        exit_total=len(exit_rows),
        tight_total=len(tight_rows),
        hold_total=len(hold_rows),
        active_nav=("risk_me" if owner == "me" else "risk_wife"),
    ))
    html = tmpl.render(**ctx)

    fname = ("portfolio_stops_{}.html".format(date_str) if owner == "me"
             else "portfolio_stops_{}_{}.html".format(owner, date_str))
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path
