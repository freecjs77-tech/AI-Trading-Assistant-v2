# portfolio_stop_report.py
"""
Portfolio Stop Signal — HTML page renderer.

Jinja2로 portfolio_stops.html 템플릿 렌더링. positions에 view-only
필드(badge_class, gap_class, display_label, is_us 등)를 주입.
"""

import os
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

from portfolio_stop_config import VERSION, ANCHOR_DATE
from portfolio_data import is_korean_ticker


_BADGE_MAP = {
    "HOLD":       "hold",
    "TIGHT":      "tight",
    "EXIT_READY": "exit-ready",
    "EXIT":       "exit",
}
_LABEL_MAP = {
    "HOLD":       "🟢 HOLD",
    "TIGHT":      "🟡 TIGHT",
    "EXIT_READY": "🟠 EXIT READY",
    "EXIT":       "🔴 EXIT",
}


def _gap_class(gap_pct: float) -> str:
    if gap_pct > 10:
        return "green-dark"
    if gap_pct > 3:
        return "green-light"
    if gap_pct >= 0:
        return "yellow"
    return "red"


def _badge_class(display_signal: str, below_count: int) -> str:
    base = _BADGE_MAP.get(display_signal, "hold")
    if display_signal == "EXIT" and below_count >= 4:
        return f"{base} deep3"
    if display_signal == "EXIT" and below_count >= 3:
        return f"{base} deep2"
    return base


def _display_label(display_signal: str, is_new: bool, below_count: int) -> str:
    base = _LABEL_MAP.get(display_signal, display_signal)
    if is_new and display_signal == "TIGHT":
        return f"{base} (new)"
    if display_signal in ("EXIT_READY", "EXIT") and below_count >= 1:
        return f"{base} ({below_count}d)"
    return base


def _enrich(positions: list) -> list:
    out = []
    for r in positions:
        is_us = not is_korean_ticker(r["ticker"])
        rr = dict(r)
        rr["is_us"] = is_us
        rr["gap_class"] = _gap_class(r.get("gap_pct", 0))
        rr["badge_class"] = _badge_class(r.get("display_signal", "HOLD"),
                                           r.get("below_stop_count", 0))
        rr["display_label"] = _display_label(
            r.get("display_signal", "HOLD"),
            r.get("is_new_position", False),
            r.get("below_stop_count", 0),
        )
        out.append(rr)
    return out


def generate_portfolio_stop_page(stop_result: dict, output_dir: str,
                                  anchor_date: str = ANCHOR_DATE,
                                  template_dir: str | None = None) -> str:
    """stop_result(generate_portfolio_stop_signals 반환) → HTML 파일.

    파일명:
      me  → portfolio_stops_<DATE>.html
      其他 → portfolio_stops_<owner>_<DATE>.html
    """
    if template_dir is None:
        template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)
    tmpl = env.get_template("portfolio_stops.html")

    owner = stop_result.get("owner", "me")
    date_str = stop_result.get("date", "")
    enriched = _enrich(stop_result.get("positions", []))

    html = tmpl.render(
        owner=owner,
        date=date_str,
        anchor_date=anchor_date,
        version=VERSION,
        summary=stop_result.get("summary", {}),
        changes=stop_result.get("changes", []),
        positions=enriched,
    )

    fname = ("portfolio_stops_{}.html".format(date_str) if owner == "me"
             else "portfolio_stops_{}_{}.html".format(owner, date_str))
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path
