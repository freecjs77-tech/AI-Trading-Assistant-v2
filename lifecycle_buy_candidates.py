"""Top 5 Buy Candidates — hybrid ranking module.

Combines lifecycle setup score (normalized to 0~14) + today's momentum
scanner tier bonus + RS vs market bonus. See spec
docs/superpowers/specs/2026-05-22-lifecycle-top5-buy-candidates-design.md.
"""
from __future__ import annotations

import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


_DRIFT_MAX = 9
_TRIGGER_MAX = 14

_MOMENTUM_BONUS = {
    "MOMENTUM_3": 4,
    "MOMENTUM_2": 3,
    "MOMENTUM_1": 2,
    "EM": 1,
}


def compute_momentum_bonus(momentum_today: dict | None) -> int:
    """Map today's momentum scanner stage to bonus points.

    momentum_today is the per-ticker entry from
    scanner_momentum_us_history.json data[<ticker>][<today>] dict,
    or None when the ticker had no momentum entry today.
    """
    if not momentum_today:
        return 0
    return _MOMENTUM_BONUS.get(momentum_today.get("stage"), 0)


def compute_rs_bonus(rs_delta_pct: float | None) -> int:
    """rs_delta_pct (vs market): >10:+3 / >5:+2 / >0:+1 / else 0.

    Boundary semantics: strictly greater than threshold. e.g. 5.0 → +1 (not +2).
    """
    if rs_delta_pct is None:
        return 0
    try:
        v = float(rs_delta_pct)
    except (TypeError, ValueError):
        return 0
    if v > 10:
        return 3
    if v > 5:
        return 2
    if v > 0:
        return 1
    return 0


def normalize_base_score(snapshot: dict) -> float:
    """Return lifecycle score on 0~14 scale, regardless of original track.

    PULLBACK / BASE_FORMING: snapshot.score is on trigger scale (0~14) — return as-is.
    TREND_OK: snapshot.score is on drift scale (0~9) — scale to 14.
    EXTENDED: veto'd; use snapshot._raw_score (drift) and scale to 14.
    Any other / missing: 0.
    """
    if not snapshot:
        return 0.0
    setup = snapshot.get("setup")
    if setup in ("PULLBACK", "BASE_FORMING"):
        s = snapshot.get("score")
        return float(s) if s is not None else 0.0
    if setup == "TREND_OK":
        s = snapshot.get("score")
        if s is None:
            return 0.0
        return float(s) * _TRIGGER_MAX / _DRIFT_MAX
    if setup == "EXTENDED":
        s = snapshot.get("_raw_score")
        if s is None:
            return 0.0
        return float(s) * _TRIGGER_MAX / _DRIFT_MAX
    return 0.0


def compute_final_score(snapshot: dict, momentum_today: dict | None) -> dict:
    """Compute hybrid ranking score breakdown.

    Returns dict with keys: base_score, momentum_bonus, rs_bonus, final_score.
    """
    base = normalize_base_score(snapshot)
    m_bonus = compute_momentum_bonus(momentum_today)
    rs_bonus = compute_rs_bonus(snapshot.get("rs_delta_pct"))
    return {
        "base_score":     base,
        "momentum_bonus": m_bonus,
        "rs_bonus":       rs_bonus,
        "final_score":    base + m_bonus + rs_bonus,
    }


def build_candidate_pool(snapshots: dict, portfolio_tickers: set) -> list[dict]:
    """Pool = snapshots minus BROKEN, with portfolio membership marked.

    Returns list of dicts: {ticker, snapshot, is_portfolio}.
    """
    portfolio_tickers = portfolio_tickers or set()
    pool: list[dict] = []
    for ticker, snap in (snapshots or {}).items():
        if not snap:
            continue
        if snap.get("setup") == "BROKEN":
            continue
        pool.append({
            "ticker":       ticker,
            "snapshot":     snap,
            "is_portfolio": ticker in portfolio_tickers,
        })
    return pool


def rank_top_n(pool: list[dict], momentum_data: dict, *,
                threshold: float = 5.0, cap: int = 5) -> list[dict]:
    """Rank candidates, filter by threshold, cap at top N.

    Args:
        pool: list of {ticker, snapshot, is_portfolio} from build_candidate_pool.
        momentum_data: {ticker: today_entry_dict} from
            scanner_momentum_us_history.json data → today section.
            Pass {} if no momentum data available.
        threshold: minimum final_score to include (default 5.0).
        cap: maximum number of candidates returned (default 5).

    Returns: list of dicts with keys: ticker, snapshot, is_portfolio,
        base_score, momentum_bonus, rs_bonus, final_score.
        Sorted by final_score desc, then rs_delta_pct desc.
    """
    scored: list[dict] = []
    for entry in pool:
        snap = entry["snapshot"]
        m_today = momentum_data.get(entry["ticker"])
        breakdown = compute_final_score(snap, m_today)
        if breakdown["final_score"] < threshold:
            continue
        scored.append({
            "ticker":         entry["ticker"],
            "snapshot":       snap,
            "is_portfolio":   entry["is_portfolio"],
            "base_score":     breakdown["base_score"],
            "momentum_bonus": breakdown["momentum_bonus"],
            "rs_bonus":       breakdown["rs_bonus"],
            "final_score":    breakdown["final_score"],
        })
    scored.sort(key=lambda c: (-c["final_score"],
                                 -(c["snapshot"].get("rs_delta_pct") or 0)))
    return scored[:cap]
