"""
Aggregates raw Capitol Trades data into the Politician Watchlist structure used by the UI.

Input:  history/politician_trades_raw.json  (from politician_trades_fetcher.py)
        data/committee_sector_map.json      (committee tier/weight config)
        data/politician_committees.json     (politician_id -> committees)
        portfolios/me.md, portfolios/wife.md (for in_portfolio flag — best-effort)

Output: history/politician_trades.json
        {
          "updated_at": ISO timestamp,
          "window_days": int,
          "watchlist": [ {ticker, stars, color_bias, score breakdown, ...} ],
          "meta":      { diagnostic counters for §8 dashboards }
        }

Scoring formula (V2c, per plan §5.1-§5.4):
  per_trade_weight = direction × committee_factor × recency_factor × size_factor
  ticker_raw_score = Σ per_trade_weight
  final_score      = ticker_raw_score + member_bonus
  stars            = |final_score| → 0-5 (thresholds in STAR_THRESHOLDS)
  color_bias       = sign(final_score) → "buy" | "sell" | "neutral"

Graceful degradation: on any error, retains prior aggregated cache if present.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def _log(msg: str) -> None:
    print(msg, flush=True)


PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_PATH = os.path.join(PROJECT_DIR, "history", "politician_trades_raw.json")
OUT_PATH = os.path.join(PROJECT_DIR, "history", "politician_trades.json")
COMMITTEE_MAP_PATH = os.path.join(PROJECT_DIR, "data", "committee_sector_map.json")
POLITICIAN_COMMITTEES_PATH = os.path.join(PROJECT_DIR, "data", "politician_committees.json")
ME_PORTFOLIO_PATH = os.path.join(PROJECT_DIR, "portfolios", "me.md")
WIFE_PORTFOLIO_PATH = os.path.join(PROJECT_DIR, "portfolios", "wife.md")

# V2c scoring config (§5.1-§5.4)
RECENCY_BUCKETS = [(30, 1.0), (60, 0.7), (90, 0.5)]  # (max_days_ago, factor)
SIZE_THRESHOLD = 500_000  # amount_min >= $500K ⇒ size_factor 1.3
MEMBER_BONUS_TIERS = {5: 2.0, 3: 1.0}  # distinct politicians ≥ N ⇒ bonus magnitude

# §5.3 star thresholds on |final_score|
STAR_THRESHOLDS = [(8.0, 5), (5.0, 4), (3.0, 3), (1.5, 2), (0.5, 1)]

WATCHLIST_MIN_SCORE = 1.5  # only include tickers with |score| >= this
WATCHLIST_MIN_DISTINCT_POLITICIANS = 2  # noise filter: at least 2 distinct politicians (buyers∪sellers)
WATCHLIST_BUY_TOP = 10
WATCHLIST_SELL_TOP = 5
NOTABLE_TRADE_MIN_AMOUNT = 100_000
NOTABLE_TRADE_LIMIT = 3

BUY_TYPES = {"buy", "receive"}
SELL_TYPES = {"sell", "exchange"}


def _load_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        _log(f"WARN: could not load {path} ({type(e).__name__}: {e})")
        return None


def _load_portfolio_tickers(path: str) -> set[str]:
    if not os.path.exists(path):
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            txt = f.read()
    except OSError:
        return set()
    # Parse portfolio markdown: look for ticker in pipe-delimited table rows.
    # Structure: | TICKER | 종목명 | ... per existing CLAUDE.md conventions.
    tickers: set[str] = set()
    for line in txt.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells:
            continue
        first = cells[0]
        # Match plain US ticker (1-5 uppercase letters) or KR digits
        if re.match(r"^[A-Z]{1,5}$", first):
            tickers.add(first)
    return tickers


def _recency_factor(tx_date: str, today: date) -> float:
    try:
        tx_dt = datetime.strptime(tx_date, "%Y-%m-%d").date()
    except ValueError:
        return 0.5
    days_ago = (today - tx_dt).days
    if days_ago < 0:
        days_ago = 0
    for max_days, factor in RECENCY_BUCKETS:
        if days_ago <= max_days:
            return factor
    return 0.5  # outside 90d still gets floor


def _committee_factor(
    politician_id: str,
    politician_committees: dict,
    committee_map: dict,
) -> tuple[float, int, list[str]]:
    """Returns (factor, best_tier, committee_names). tier 1 → 2.0, tier 2 → 1.5, else 1.0."""
    entry = politician_committees.get(politician_id)
    if not entry:
        return 1.0, 3, []
    names = entry.get("committees", []) if isinstance(entry, dict) else []
    best_tier = 3
    best_factor = 1.0
    for name in names:
        meta = committee_map.get(name)
        if not meta:
            continue
        tier = meta.get("tier", 3)
        weight = meta.get("weight", 1.0)
        if tier < best_tier:
            best_tier = tier
            best_factor = weight
    return best_factor, best_tier, names


def _size_factor(amount_min: int | None) -> float:
    if amount_min is None:
        return 1.0
    return 1.3 if amount_min >= SIZE_THRESHOLD else 1.0


def _direction(tx_type: str) -> int:
    """+1 buy / -1 sell / 0 other. exchange treated as sell (position reduction)."""
    tl = (tx_type or "").lower()
    if tl in BUY_TYPES:
        return 1
    if tl in SELL_TYPES:
        return -1
    return 0


def _stars(abs_score: float) -> int:
    for threshold, stars in STAR_THRESHOLDS:
        if abs_score >= threshold:
            return stars
    return 0


def _member_bonus(distinct_buyers: int, distinct_sellers: int) -> float:
    bonus = 0.0
    for threshold in sorted(MEMBER_BONUS_TIERS.keys(), reverse=True):
        if distinct_buyers >= threshold:
            bonus += MEMBER_BONUS_TIERS[threshold]
            break
    for threshold in sorted(MEMBER_BONUS_TIERS.keys(), reverse=True):
        if distinct_sellers >= threshold:
            bonus -= MEMBER_BONUS_TIERS[threshold]
            break
    return bonus


def aggregate(
    raw: dict,
    committee_map: dict,
    politician_committees: dict,
    portfolio_tickers: set[str],
    today: date | None = None,
) -> dict:
    today = today or datetime.now(timezone.utc).date()
    window_days = raw.get("window_days", 90)
    trades = raw.get("trades", [])
    cutoff_7d = today - timedelta(days=7)

    # Group US trades by ticker
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    us_trade_count = 0
    for t in trades:
        if t.get("ticker_country") != "US" or not t.get("ticker"):
            continue
        us_trade_count += 1
        by_ticker[t["ticker"]].append(t)

    entries: list[dict] = []
    for ticker, ticker_trades in by_ticker.items():
        distinct_buyers: set[str] = set()
        distinct_sellers: set[str] = set()
        ticker_raw_score = 0.0
        buy_count = 0
        sell_count = 0
        committee_counts: dict[str, int] = Counter()
        committee_tiers: dict[str, int] = {}
        last_7d_activity = False

        notable_candidates: list[dict] = []

        for t in ticker_trades:
            pol_id = t.get("politician_id")
            if not pol_id:
                continue
            direction = _direction(t.get("tx_type", ""))
            if direction == 0:
                continue
            tx_date = t.get("tx_date", "")
            recency = _recency_factor(tx_date, today)
            comm_factor, comm_tier, comm_names = _committee_factor(
                pol_id, politician_committees, committee_map
            )
            size_f = _size_factor(t.get("amount_min"))

            per_weight = direction * comm_factor * recency * size_f
            ticker_raw_score += per_weight

            if direction > 0:
                distinct_buyers.add(pol_id)
                buy_count += 1
            else:
                distinct_sellers.add(pol_id)
                sell_count += 1

            for c in comm_names:
                meta = committee_map.get(c)
                if meta and meta.get("tier", 3) <= 2:
                    committee_counts[c] += 1
                    committee_tiers[c] = meta.get("tier", 3)

            try:
                if datetime.strptime(tx_date, "%Y-%m-%d").date() >= cutoff_7d:
                    last_7d_activity = True
            except ValueError:
                pass

            if (t.get("amount_min") or 0) >= NOTABLE_TRADE_MIN_AMOUNT:
                notable_candidates.append(
                    {
                        "politician_id": pol_id,
                        "politician_name": t.get("politician_name"),
                        "date": tx_date,
                        "direction": "buy" if direction > 0 else "sell",
                        "amount_min": t.get("amount_min"),
                        "amount_max": t.get("amount_max"),
                        "top_committee_tier": comm_tier,
                    }
                )

        member_bonus = _member_bonus(len(distinct_buyers), len(distinct_sellers))
        final_score = ticker_raw_score + member_bonus
        abs_score = abs(final_score)
        stars = _stars(abs_score)
        if abs_score < 0.5:
            color_bias = "neutral"
        else:
            color_bias = "buy" if final_score > 0 else "sell"

        if abs_score < WATCHLIST_MIN_SCORE:
            continue  # drop below threshold — keeps UI focused

        distinct_politicians_total = len(distinct_buyers | distinct_sellers)
        if distinct_politicians_total < WATCHLIST_MIN_DISTINCT_POLITICIANS:
            continue  # noise filter: need at least 2 distinct politicians — avoids single-trader artifacts

        # Sort notables by |amount_min| desc, keep top N
        notable_candidates.sort(key=lambda x: (x.get("amount_min") or 0), reverse=True)
        notable_trades = notable_candidates[:NOTABLE_TRADE_LIMIT]

        top_committees = [
            {"name": name, "tier": committee_tiers[name], "member_count": count}
            for name, count in committee_counts.most_common(4)
        ]

        issuer_name = next(
            (t.get("issuer_name") for t in ticker_trades if t.get("issuer_name")),
            ticker,
        )

        entries.append(
            {
                "ticker": ticker,
                "issuer_name": issuer_name,
                "final_score": round(final_score, 2),
                "stars": stars,
                "color_bias": color_bias,
                "buy_count": buy_count,
                "sell_count": sell_count,
                "net_count": buy_count - sell_count,
                "distinct_buyers": len(distinct_buyers),
                "distinct_sellers": len(distinct_sellers),
                "member_bonus": round(member_bonus, 2),
                "ticker_raw_score": round(ticker_raw_score, 2),
                "last_7d_activity": last_7d_activity,
                "notable_trades": notable_trades,
                "top_committees": top_committees,
                "in_portfolio": ticker in portfolio_tickers,
            }
        )

    # Split into buy/sell watchlists, each sorted by |final_score| desc
    buy_side = sorted(
        [e for e in entries if e["color_bias"] == "buy"],
        key=lambda e: -e["final_score"],
    )[:WATCHLIST_BUY_TOP]
    sell_side = sorted(
        [e for e in entries if e["color_bias"] == "sell"],
        key=lambda e: e["final_score"],  # most negative first
    )[:WATCHLIST_SELL_TOP]

    watchlist = buy_side + sell_side
    for rank, entry in enumerate(watchlist, start=1):
        entry["rank"] = rank

    politicians_active = len({t.get("politician_id") for t in trades if t.get("politician_id")})

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": window_days,
        "watchlist": watchlist,
        "meta": {
            "total_trades_considered": len(trades),
            "total_us_trades": us_trade_count,
            "unique_tickers_with_activity": len(by_ticker),
            "tickers_passing_threshold": len(entries),
            "politicians_active": politicians_active,
            "highlights_threshold_score": WATCHLIST_MIN_SCORE,
            "raw_fetched_at": raw.get("fetched_at"),
        },
    }


def main() -> int:
    raw = _load_json(RAW_PATH)
    if not raw:
        _log("WARN: no raw cache found; cannot aggregate. Keeping prior output if exists.")
        return 0

    committee_map = _load_json(COMMITTEE_MAP_PATH) or {}
    committee_map = {k: v for k, v in committee_map.items() if not k.startswith("_")}
    pol_committees = _load_json(POLITICIAN_COMMITTEES_PATH) or {}
    pol_committees = {k: v for k, v in pol_committees.items() if not k.startswith("_")}

    me_tickers = _load_portfolio_tickers(ME_PORTFOLIO_PATH)
    wife_tickers = _load_portfolio_tickers(WIFE_PORTFOLIO_PATH)
    portfolio_tickers = me_tickers | wife_tickers
    _log(f"Portfolio tickers loaded: me={len(me_tickers)}, wife={len(wife_tickers)}, total={len(portfolio_tickers)}")

    try:
        out = aggregate(raw, committee_map, pol_committees, portfolio_tickers)
    except Exception as e:
        _log(f"WARN: aggregation failed ({type(e).__name__}: {e}); keeping prior output")
        return 0

    tmp = OUT_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        os.replace(tmp, OUT_PATH)
    except OSError as e:
        _log(f"WARN: could not write {OUT_PATH}: {e}")
        return 0

    w = out["watchlist"]
    m = out["meta"]
    _log(f"Wrote {OUT_PATH}")
    _log(f"  watchlist: {len(w)} entries (buy-side + sell-side)")
    _log(f"  meta: {json.dumps(m, indent=2)}")
    if w:
        _log("\nTop 10 entries:")
        for e in w[:10]:
            stars = "★" * e["stars"] + "☆" * (5 - e["stars"])
            tag = " [PORT]" if e["in_portfolio"] else ""
            _log(
                f"  #{e['rank']:2d}  {stars}  {e['color_bias']:4s}  score={e['final_score']:+6.2f}  "
                f"{e['ticker']:6s}  buy={e['buy_count']}/sell={e['sell_count']}  "
                f"buyers={e['distinct_buyers']}/sellers={e['distinct_sellers']}{tag}  {e['issuer_name'][:40]}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
