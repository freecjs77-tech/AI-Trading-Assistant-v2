# lifecycle_report.py
"""Phase A — lifecycle page renderer.

generate_lifecycle_pages(us_result, kr_result, output_dir) → {market: path}
"""
from __future__ import annotations

import os
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from lifecycle_config import LIFECYCLE_VERSION
from lifecycle_history import derive_fields


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
    return out


def build_page_context(result: dict,
                         lifecycle_state: Optional[dict] = None) -> dict:
    market = result.get("market", "US")
    enter_ok, early, staging, avoid, broken_table = [], [], [], [], []
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
        if d == "ENTER_OK":
            enter_ok.append(row)
            if (row["trigger_age_days"] == 0) and snap["trigger"] == "CONFIRMED_TRIGGER":
                new_confirmed.append(row)
        elif d == "EARLY":
            early.append(row)
        elif d == "STAGING":
            staging.append(row)
        else:
            avoid.append(row)

    enter_ok.sort(key=lambda r: ((r["trigger_age_days"] if r["trigger_age_days"] is not None else 999),
                                   -(r["raw"].get("volume_ratio") or 0)))
    early.sort(key=lambda r: -(r["raw"].get("volume_ratio") or 0))
    staging.sort(key=lambda r: -(r["setup_streak"] or 0))

    return {
        "market":       result.get("market", "US"),
        "as_of":        result.get("as_of"),
        "version":      LIFECYCLE_VERSION,
        "new_confirmed": new_confirmed,
        "enter_ok":     enter_ok,
        "early":        early,
        "staging":      staging,
        "avoid":        avoid,
        "broken_table": broken_table,
        "transitions":  (result.get("transitions") or [])[-50:],
    }


def _render(market: str, result: dict, output_dir: str,
              template_dir: Optional[str], lifecycle_state: Optional[dict]) -> str:
    if template_dir is None:
        template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)
    tmpl = env.get_template(f"lifecycle_{market.lower()}.html")
    ctx = build_page_context(result, lifecycle_state=lifecycle_state)
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
                                kr_state: Optional[dict] = None) -> dict[str, str]:
    out: dict[str, str] = {}
    if us_result and us_result.get("snapshots"):
        out["us"] = _render("US", us_result, output_dir, template_dir, us_state)
    if kr_result and kr_result.get("snapshots"):
        out["kr"] = _render("KR", kr_result, output_dir, template_dir, kr_state)
    return out
