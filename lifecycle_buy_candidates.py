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


def _flatten_scanner_signals(momentum_today: list[dict] | dict | None) -> list[dict]:
    """Accept either:
      - flat list of evaluate_stock dicts: [{ticker, stage, ...}, ...]
      - scanner_*_result dict: {"signals": {"MOMENTUM_3": [...], ...}, ...}
    Returns a flat list of per-ticker dicts.
    """
    if momentum_today is None:
        return []
    if isinstance(momentum_today, list):
        return list(momentum_today)
    if isinstance(momentum_today, dict) and "signals" in momentum_today:
        flat: list[dict] = []
        for tier in ("MOMENTUM_3", "MOMENTUM_2", "MOMENTUM_1", "EM"):
            flat.extend(momentum_today["signals"].get(tier, []) or [])
        return flat
    return []


def _extract_today_momentum(momentum_history: dict, today: str) -> dict:
    """Pull {ticker: today_entry_dict} from scanner_momentum_*_history.json.

    History shape (from momentum_history.py):
        {"_meta": {...}, "data": {ticker: {date_str: entry, ...}}}
    """
    data = (momentum_history or {}).get("data") or {}
    out: dict = {}
    for ticker, by_date in data.items():
        if not isinstance(by_date, dict):
            continue
        entry = by_date.get(today)
        if entry:
            out[ticker] = entry
    return out


def _size_hint_label(setup: str, is_portfolio: bool) -> str:
    """Display label: 신규/추가 + percent based on EXTENDED override."""
    prefix = "추가" if is_portfolio else "신규"
    pct = "25%" if setup == "EXTENDED" else "50%"
    return f"{prefix} {pct}"


def select_top5_buy_candidates(*, snapshots: dict, portfolio_tickers: set,
                                  momentum_history: dict, today: str,
                                  threshold: float = 5.0, cap: int = 5,
                                  momentum_today: list[dict] | dict | None = None,
                                  market_data: dict | None = None,
                                  market_ret_5d_pct: float | None = None) -> dict:
    """One-call entry. Returns dict ready for template ctx injection.

    Args:
        snapshots: lifecycle process_universe result snapshots (active_set 종목).
        portfolio_tickers: 보유 종목 set — is_portfolio 마킹용.
        momentum_history: scanner_momentum_*_history.json raw dict (fallback path,
            기존 기능 유지 — momentum_bonus 산정 시 활용).
        today: "YYYY-MM-DD".
        threshold / cap: ranking 임계 / 상한 (기본 5.0 / 5).
        momentum_today: (선택) 오늘 momentum 스캐너 라이브 결과. flat list 또는
            scanner_*_result dict. snapshots에 없는 ticker를 즉석 합성 snapshot
            으로 pool에 추가 — universe 확장 경로.
        market_data: (선택) momentum-only ticker의 합성 snapshot 계산 source.
            pipeline의 market_data dict (`{"data": {ticker: entry, ...}}` 또는
            `{ticker: entry, ...}`).
        market_ret_5d_pct: (선택) RS bonus 계산을 위한 시장 5일 수익률.

    Returns:
        {
            "candidates": list of ranked dicts (with size_hint_label, snapshot, scores),
            "count":      len(candidates),
            "max":        cap,
            "threshold":  threshold,
        }
    """
    pool = build_candidate_pool(snapshots, portfolio_tickers)

    # --- Universe expansion: momentum-only tickers (NEW) ---
    if momentum_today is not None and market_data is not None:
        from lifecycle_signal import compute_single_snapshot
        scanner_list = _flatten_scanner_signals(momentum_today)
        existing_tickers = {entry["ticker"] for entry in pool}
        market_data_flat = (market_data.get("data")
                             if isinstance(market_data, dict) and "data" in market_data
                             else market_data) or {}
        seen_extra: set[str] = set()
        for sig in scanner_list:
            tk = sig.get("ticker")
            if not tk or tk in existing_tickers or tk in seen_extra:
                continue
            md_entry = market_data_flat.get(tk)
            if not md_entry:
                continue
            synthetic = compute_single_snapshot(
                ticker=tk,
                market_data_entry=md_entry,
                market_ret_5d_pct=market_ret_5d_pct,
                yesterday=None,
                today=today,
            )
            if synthetic is None:
                continue
            if synthetic.get("setup") == "BROKEN":
                continue
            synthetic["_scanner_only"] = True
            pool.append({
                "ticker":       tk,
                "snapshot":     synthetic,
                "is_portfolio": tk in (portfolio_tickers or set()),
            })
            seen_extra.add(tk)

    momentum_today_for_bonus = _extract_today_momentum(momentum_history, today)
    # Also include live scanner stages so momentum-only tickers get momentum_bonus
    if momentum_today is not None:
        for sig in _flatten_scanner_signals(momentum_today):
            tk = sig.get("ticker")
            if tk and tk not in momentum_today_for_bonus:
                momentum_today_for_bonus[tk] = {"stage": sig.get("stage")}

    ranked = rank_top_n(pool, momentum_today_for_bonus,
                          threshold=threshold, cap=cap)

    for c in ranked:
        setup = (c["snapshot"] or {}).get("setup")
        c["size_hint_label"] = _size_hint_label(setup, c["is_portfolio"])

    return {
        "candidates": ranked,
        "count":      len(ranked),
        "max":        cap,
        "threshold":  threshold,
    }
