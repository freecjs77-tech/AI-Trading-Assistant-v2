# lifecycle_history.py
"""Phase A — lifecycle history JSON I/O + schema + active-set + bootstrap.

File schema (per market):
  {
    "schema_version":  "1.0.0",
    "generator_version": "lifecycle_phase_a/0.1.0",
    "last_updated":     ISO-8601,
    "tickers": { TICKER: { first_seen, last_seen, snapshots: [...] } },
    "transitions": [ { event_id, date, ticker, event, from, to } ]
  }

Atomic writes via tmp + os.replace (mirrors portfolio_stop_history pattern).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional

from lifecycle_config import LIFECYCLE_VERSION

SCHEMA_VERSION = "1.0.0"


def new_empty_state(market: str) -> dict:
    return {
        "schema_version":    SCHEMA_VERSION,
        "generator_version": LIFECYCLE_VERSION,
        "market":            market,
        "last_updated":      None,
        "tickers":           {},
        "transitions":       [],
    }


def load_lifecycle_history(path: str, market: str = "US") -> dict:
    if not os.path.exists(path):
        return new_empty_state(market)
    try:
        with open(path, "rb") as f:
            raw = f.read()
        return json.loads(raw.rstrip(b" \t\n\r\x00").decode("utf-8"))
    except Exception as e:
        print(f"[lifecycle_history] WARN load failed ({e}) -- using empty state")
        return new_empty_state(market)


def save_lifecycle_history(state: dict, path: str) -> None:
    state["last_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def append_snapshot(state: dict, ticker: str, snapshot: dict) -> None:
    block = state["tickers"].setdefault(ticker, {
        "first_seen": snapshot["date"],
        "last_seen":  snapshot["date"],
        "snapshots":  [],
    })
    block["snapshots"].append(snapshot)
    block["last_seen"] = snapshot["date"]
    if snapshot["date"] < block["first_seen"]:
        block["first_seen"] = snapshot["date"]


def append_transition(state: dict, *, ticker: str, date_str: str,
                       event: str, from_value: Optional[str],
                       to_value: Optional[str]) -> None:
    state["transitions"].append({
        "event_id": f"{ticker}_{date_str}_{event}_v1",
        "date":     date_str,
        "ticker":   ticker,
        "event":    event,
        "from":     from_value,
        "to":       to_value,
    })


# ---------------------------------------------------------------------------
# Task 8: compute_active_set
# ---------------------------------------------------------------------------

def _days_between(d1: str, d2: str) -> int:
    a = datetime.strptime(d1, "%Y-%m-%d").date()
    b = datetime.strptime(d2, "%Y-%m-%d").date()
    return (a - b).days


def normalize_momentum_history(raw: dict) -> dict:
    """Normalize momentum_scanner's history shape to active-set's expected shape.

    momentum_history.py writes:
        {"_meta": {...}, "data": {TICKER: {DATE_STR: entry, ...}}}

    compute_active_set() expects:
        {"tickers": {TICKER: {"snapshots": [{"date": ..., "stage": ...}, ...]}}}

    This adapter converts the date-keyed dict to a date-sorted snapshot list.
    Already-normalized inputs (the "tickers" form) pass through unchanged.
    """
    if not isinstance(raw, dict):
        return {"tickers": {}}
    if "tickers" in raw and "data" not in raw:
        return raw  # already normalized
    src = raw.get("data") or {}
    out: dict = {"tickers": {}}
    for tk, by_date in src.items():
        if not isinstance(by_date, dict):
            continue
        snapshots = []
        for date_str in sorted(by_date.keys()):
            entry = by_date[date_str]
            if not isinstance(entry, dict):
                continue
            snap = dict(entry)
            snap["date"] = date_str
            snapshots.append(snap)
        if snapshots:
            out["tickers"][tk] = {"snapshots": snapshots}
    return out


def compute_active_set(*, momentum_history: dict,
                        lifecycle_state: dict,
                        portfolio_tickers: set,
                        today: str) -> set[str]:
    """active_set(today) per spec §3.

    Membership rules:
      ticker IN active_set IFF
        ( ticker has M1/M2/M3 hit within ACTIVE_M123_LOOKBACK_DAYS
          OR ticker.setup_state != BROKEN within ACTIVE_NONBROKEN_LOOKBACK_DAYS )
        AND ticker NOT IN portfolio.
    """
    from lifecycle_config import (
        ACTIVE_M123_LOOKBACK_DAYS, ACTIVE_NONBROKEN_LOOKBACK_DAYS,
        ACTIVE_SET_MAX_SIZE,
    )
    candidates: dict[str, str] = {}  # ticker -> most-recent activity date.

    for tk, block in (momentum_history.get("tickers") or {}).items():
        snaps = block.get("snapshots") or []
        for snap in reversed(snaps):
            d = snap.get("date")
            if not d:
                continue
            if _days_between(today, d) <= ACTIVE_M123_LOOKBACK_DAYS:
                candidates[tk] = d
            break

    for tk, block in (lifecycle_state.get("tickers") or {}).items():
        snaps = block.get("snapshots") or []
        if not snaps:
            continue
        last = snaps[-1]
        d = last.get("date") or block.get("last_seen")
        if not d:
            continue
        if last.get("setup") == "BROKEN":
            continue
        if _days_between(today, d) <= ACTIVE_NONBROKEN_LOOKBACK_DAYS:
            existing = candidates.get(tk)
            if not existing or d > existing:
                candidates[tk] = d

    for tk in list(portfolio_tickers):
        candidates.pop(tk, None)

    if len(candidates) > ACTIVE_SET_MAX_SIZE:
        sorted_tickers = sorted(candidates.items(),
                                  key=lambda kv: kv[1], reverse=True)
        candidates = dict(sorted_tickers[:ACTIVE_SET_MAX_SIZE])
        print(f"[lifecycle_history] WARN active set truncated to {ACTIVE_SET_MAX_SIZE}")

    return set(candidates.keys())


# ---------------------------------------------------------------------------
# Task 9: derive_fields
# ---------------------------------------------------------------------------

def derive_fields(ticker_block: dict) -> dict:
    """Recompute derived fields from snapshot history. Never stored."""
    snaps = ticker_block.get("snapshots") or []
    if not snaps:
        return {"setup_streak": 0, "days_in_pullback": 0, "trigger_age_days": None}

    # setup_streak — consecutive same setup back from latest.
    latest_setup = snaps[-1].get("setup")
    streak = 0
    for snap in reversed(snaps):
        if snap.get("setup") == latest_setup:
            streak += 1
        else:
            break

    # days_in_pullback — consecutive PULLBACK or BASE_FORMING days back from latest.
    in_pull = 0
    for snap in reversed(snaps):
        if snap.get("setup") in ("PULLBACK", "BASE_FORMING"):
            in_pull += 1
        else:
            break

    # trigger_age_days — days since last EARLY_TRIGGER or CONFIRMED_TRIGGER.
    today = snaps[-1].get("date")
    age = None
    for snap in reversed(snaps):
        if snap.get("trigger") in ("EARLY_TRIGGER", "CONFIRMED_TRIGGER"):
            age = _days_between(today, snap["date"])
            break

    return {
        "setup_streak":     streak,
        "days_in_pullback": in_pull,
        "trigger_age_days": age,
    }


# ---------------------------------------------------------------------------
# Task 10: compute_transitions
# ---------------------------------------------------------------------------

def compute_transitions(ticker: str,
                         yesterday: Optional[dict],
                         today: dict) -> list[dict]:
    """Diff yesterday's snapshot against today's. Emit events per spec §5.3.

    Five event types:
      SETUP_CHANGE / TRIGGER_CHANGE / DECISION_CHANGE
      FAILED_BREAKOUT (independent — risk_tag presence)
      RISK_ESCALATION (when EXTENDED newly added to risk_tags)
    """
    if yesterday is None:
        return []
    out: list[dict] = []
    date_str = today["date"]

    def _evt(event: str, frm, to):
        out.append({
            "event_id": f"{ticker}_{date_str}_{event}_v1",
            "date":     date_str,
            "ticker":   ticker,
            "event":    event,
            "from":     frm,
            "to":       to,
        })

    if yesterday.get("setup") != today.get("setup"):
        _evt("SETUP_CHANGE", yesterday.get("setup"), today.get("setup"))
    if yesterday.get("trigger") != today.get("trigger"):
        _evt("TRIGGER_CHANGE", yesterday.get("trigger"), today.get("trigger"))
    if yesterday.get("decision") != today.get("decision"):
        _evt("DECISION_CHANGE", yesterday.get("decision"), today.get("decision"))

    today_tags = set((today.get("raw") or {}).get("risk_tags") or [])
    y_tags = set((yesterday.get("raw") or {}).get("risk_tags") or [])

    if "FAILED_BREAKOUT" in today_tags:
        _evt("FAILED_BREAKOUT", None, None)

    if "EXTENDED" in today_tags and "EXTENDED" not in y_tags:
        _evt("RISK_ESCALATION", None, "EXTENDED")

    return out


# ---------------------------------------------------------------------------
# Task 11: bootstrap_active_set
# ---------------------------------------------------------------------------

def bootstrap_active_set(*, market: str, momentum_history: dict,
                          portfolio_tickers: set, today: str) -> dict:
    """First-run seed state.

    Creates an empty lifecycle state plus a `_bootstrap_meta` marker recording
    which tickers were known on day-0. The actual snapshot data is built by
    process_universe on the same day's run — bootstrap merely says "these
    tickers will be valid in active_set today even though there is no history".
    """
    seed = compute_active_set(momentum_history=momentum_history,
                                lifecycle_state={"tickers": {}},
                                portfolio_tickers=portfolio_tickers,
                                today=today)
    state = new_empty_state(market)
    state["_bootstrap_meta"] = {
        "bootstrapped_on": today,
        "seed_tickers":    sorted(seed),
    }
    return state
