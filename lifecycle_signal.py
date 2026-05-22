# lifecycle_signal.py
"""Phase A — pure-function lifecycle state machine.

State machines:
  setup_state    ∈ {TREND_OK, PULLBACK, BASE_FORMING, EXTENDED, BROKEN}
  trigger_state  ∈ {WAIT, EARLY_TRIGGER, CONFIRMED_TRIGGER}
  entry_decision ∈ {ENTER, PROBE, WATCH, TRENDING, AVOID}

  Decision semantics (Korean display via DECISION_LABELS):
    ENTER    = 본 진입       (CONFIRMED_TRIGGER on PULLBACK/BASE_FORMING)
    PROBE    = 분할 진입     (EARLY_TRIGGER on PULLBACK/BASE_FORMING)
    WATCH    = 진입 대기     (good setup PULLBACK/BASE_FORMING but no trigger yet)
    TRENDING = 눌림 대기     (TREND_OK — already in trend, wait for next pullback)
    AVOID    = 매수 금지     (EXTENDED, BROKEN, or FAILED_BREAKOUT — real risk)

setup_state evaluation order is strict (first match wins):
  1. BROKEN  2. EXTENDED  3. BASE_FORMING  4. PULLBACK  5. TREND_OK
"""
from __future__ import annotations

from typing import Optional

from lifecycle_config import (
    PULLBACK_MAX_DIST_FROM_EMA9,
    BASE_FORMING_DAYS_MIN, BASE_FORMING_DAYS_MAX,
    BASE_VOL_CONTRACTION_RATIO,
    EXTENDED_DIST_FROM_EMA9, EXTENDED_RSI_MIN,
    TRIGGER_CONFIRM_VOL_RATIO_MIN, TRIGGER_CONFIRM_CLOSE_HIGH_RATIO,
    FAILED_BREAKOUT_REQUIRE_BELOW_PRIOR_LOW,
    RISK_OVERHEAT_RSI, RISK_PARABOLIC_RET_1D, RISK_PARABOLIC_VOL_RATIO,
)


def _is_trend_ok(r: dict) -> bool:
    """ema9 > ema21 > ema65 AND ema65 slope positive.

    NOTE: close > ema21 is NOT required here — a close that has dipped below
    ema21 (but above ema65) still belongs in TREND_OK rather than BROKEN.
    The PULLBACK predicate separately rejects close < ema21 (so a deep
    intra-ema pullback falls straight through to TREND_OK — which is correct).
    """
    e9, e21, e65 = r.get("ema9"), r.get("ema21"), r.get("ema65")
    if e9 is None or e21 is None or e65 is None:
        return False
    if not (e9 > e21 > e65):
        return False
    if (r.get("ema65_slope_5d") or 0) <= 0:
        return False
    return True


def _is_broken(r: dict) -> bool:
    e21, e65 = r.get("ema21"), r.get("ema65")
    close = r.get("close")
    if e21 is None or e65 is None or close is None:
        return False
    return (e21 < e65) or (close < e65)


def _is_extended(r: dict) -> bool:
    e9, e21, e65 = r.get("ema9"), r.get("ema21"), r.get("ema65")
    close = r.get("close")
    rsi = r.get("rsi14")
    if e9 is None or e21 is None or e65 is None or close is None or rsi is None:
        return False
    if not (e9 > e21 > e65):
        return False
    dist_pct = abs(close - e9) / e9
    return dist_pct > EXTENDED_DIST_FROM_EMA9 and rsi > EXTENDED_RSI_MIN


def _is_base_forming(r: dict) -> bool:
    if not _is_trend_ok(r):
        return False
    days = r.get("days_sideways") or 0
    if not (BASE_FORMING_DAYS_MIN <= days <= BASE_FORMING_DAYS_MAX):
        return False
    a5  = r.get("atr14_pct_5d_avg")
    a20 = r.get("atr14_pct_20d_avg")
    if a5 is None or a20 is None or a5 >= a20:
        return False
    v5  = r.get("volume_5d_avg")
    v20 = r.get("volume_20d_avg")
    if v5 is None or v20 is None or v5 >= v20 * BASE_VOL_CONTRACTION_RATIO:
        return False
    if (r.get("ema21_slope_5d") or 0) <= 0:
        return False
    return True


def _is_pullback(r: dict) -> bool:
    if not _is_trend_ok(r):
        return False
    e9 = r.get("ema9")
    close = r.get("close")
    e21 = r.get("ema21")
    if e9 is None or close is None or e21 is None:
        return False
    if abs(close - e9) / e9 > PULLBACK_MAX_DIST_FROM_EMA9:
        return False
    if close < e21:
        return False
    return True


def evaluate_setup_state(raw: dict) -> str:
    """Strict precedence: BROKEN > EXTENDED > BASE_FORMING > PULLBACK > TREND_OK."""
    if _is_broken(raw):
        return "BROKEN"
    if _is_extended(raw):
        return "EXTENDED"
    if _is_base_forming(raw):
        return "BASE_FORMING"
    if _is_pullback(raw):
        return "PULLBACK"
    if _is_trend_ok(raw):
        return "TREND_OK"
    return "BROKEN"  # No alignment + no break = degraded; treat as out-of-trend.


def _close_in_upper_band(today: dict) -> bool:
    """today_close >= today_high * ratio + today_low * (1-ratio)."""
    h = today.get("high"); l = today.get("low"); c = today.get("close")
    if h is None or l is None or c is None or h == l:
        return False
    threshold = h * TRIGGER_CONFIRM_CLOSE_HIGH_RATIO + l * (1 - TRIGGER_CONFIRM_CLOSE_HIGH_RATIO)
    # Small float tolerance — boundary closes (e.g. close == high*0.8 + low*0.2) should qualify.
    return c >= threshold - 1e-9


def _is_early_trigger(today: dict, yesterday: dict) -> bool:
    """EARLY_TRIGGER conditions per spec §4.3.

    Two arms (OR-combined):
      1. EMA9 reclaim — yesterday closed at-or-below ema9, today closes above.
      2. Prior-day-high break — today's high exceeds yesterday's high AND today
         closes in the upper band. The close-position gate on arm 2 prevents
         exhaustion gap-ups (big intraday print, weak close) from falsely
         registering as a trigger event. Spec §9 Golden #6.
    """
    e9 = today.get("ema9")
    if (e9 is not None
            and yesterday.get("close") is not None
            and today.get("close") is not None
            and yesterday["close"] <= e9 < today["close"]):
        return True
    if (today.get("high") is not None
            and yesterday.get("high") is not None
            and today["high"] > yesterday["high"]
            and _close_in_upper_band(today)):
        return True
    return False


def _is_confirmed_trigger(today: dict, yesterday: dict) -> bool:
    if not _is_early_trigger(today, yesterday):
        return False
    if (today.get("volume_ratio") or 0) < TRIGGER_CONFIRM_VOL_RATIO_MIN:
        return False
    return _close_in_upper_band(today)


def evaluate_trigger_state(today: dict, yesterday: dict, setup_state: str) -> str:
    """Trigger only meaningful when setup ∈ {PULLBACK, BASE_FORMING}; else WAIT."""
    if setup_state not in ("PULLBACK", "BASE_FORMING"):
        return "WAIT"
    if _is_confirmed_trigger(today, yesterday):
        return "CONFIRMED_TRIGGER"
    if _is_early_trigger(today, yesterday):
        return "EARLY_TRIGGER"
    return "WAIT"


# ── Decision display labels (Korean) ──────────────────────────────
# Internal keys are stable English (used by CSS classes, tests, history).
# Templates and Telegram render via this mapping for action-clear UX.
DECISION_LABELS = {
    "ENTER":    "본 진입",
    "PROBE":    "분할 진입",
    "WATCH":    "진입 대기",
    "TRENDING": "눌림 대기",
    "AVOID":    "매수 금지",
}

DECISION_TOOLTIPS = {
    "ENTER":    "본 진입: 확정 트리거 (vol 확장 + 종가 일중 상위 20%) — 풀 포지션 가능",
    "PROBE":    "분할 진입: 초기 트리거 (EMA9 reclaim 또는 prior-high break) — 50% 부분 진입 가능",
    "WATCH":    "진입 대기: PULLBACK/BASE_FORMING zone, 트리거 미발생 — 반등 신호 관찰",
    "TRENDING": "눌림 대기: 추세 살아있으나 setup 압축 부족 — 다음 PULLBACK까지 추격 자제",
    "AVOID":    "매수 금지: EXTENDED 과열 / BROKEN 추세 깨짐 / FAILED_BREAKOUT 가짜 돌파 — 진입 시 손실 위험 큼",
}


def evaluate_decision(
    setup_state: str,
    trigger_state: str,
    *,
    risk_tags: Optional[list[str]] = None,
    regime: Optional[str] = None,
    # Score engine inputs (new; optional for legacy callers)
    today_raw: Optional[dict] = None,
    yesterday_snap: Optional[dict] = None,
    recent_3d_closes: Optional[list] = None,
    market_ret_5d_pct: Optional[float] = None,
) -> dict | str:
    """Evaluate decision. Backwards compatible with Phase A boolean signature.

    LIFECYCLE_ENGINE_MODE env var dispatches:
      - "legacy":        Phase A boolean path (returns str: ENTER/PROBE/WATCH/...)
      - "score_shadow":  Phase A decision (str) + side-channel score computed (NOT used for decision)
      - "score_active":  Score-driven decision (returns dict with score fields)

    All three modes guarantee the same invariants:
      - FAILED_BREAKOUT / BROKEN / EXTENDED → AVOID
      - Drift never ENTER when DRIFT_ALLOW_ENTER=False

    Returns:
        str: Phase A path (modes "legacy" and "score_shadow"). Decision key only.
        dict: Score engine path (mode "score_active"). Full snapshot fields.
              See spec §7.4 for shape.
    """
    import os
    from lifecycle_score_config import (
        DEFAULT_ENGINE_MODE, MODE_LEGACY, MODE_SCORE_SHADOW, MODE_SCORE_ACTIVE,
    )

    mode = os.environ.get("LIFECYCLE_ENGINE_MODE", DEFAULT_ENGINE_MODE)
    risk_tags = risk_tags or []

    # ── Legacy path (rollback target) — Phase A behavior exactly ──
    if mode == MODE_LEGACY:
        return _evaluate_decision_phase_a(setup_state, trigger_state, risk_tags=risk_tags)

    # ── Shadow + active paths both need score computation ──
    # In shadow mode the score is computed and returned in a side-channel form,
    # but the decision returned is the Phase A boolean output (str).
    if mode == MODE_SCORE_SHADOW:
        phase_a_decision = _evaluate_decision_phase_a(setup_state, trigger_state, risk_tags=risk_tags)
        # Shadow mode returns Phase A's str decision unchanged. Score computation
        # for shadow storage is wired into process_universe in Task 14 — not here.
        return phase_a_decision

    # ── score_active: full new engine ──
    if mode == MODE_SCORE_ACTIVE:
        return _evaluate_decision_score(
            setup_state=setup_state,
            today_raw=today_raw or {},
            yesterday_snap=yesterday_snap,
            recent_3d_closes=recent_3d_closes,
            risk_tags=risk_tags,
            market_ret_5d_pct=market_ret_5d_pct,
        )

    # Unknown mode — safe fallback to legacy
    print(f"[lifecycle_signal] WARN unknown LIFECYCLE_ENGINE_MODE={mode!r}, "
          f"falling back to legacy")
    return _evaluate_decision_phase_a(setup_state, trigger_state, risk_tags=risk_tags)


def _evaluate_decision_phase_a(setup_state: str, trigger_state: str,
                                *, risk_tags: list[str]) -> str:
    """Phase A boolean path — exact behavior of original evaluate_decision."""
    if "FAILED_BREAKOUT" in risk_tags:
        return "AVOID"
    if setup_state in ("EXTENDED", "BROKEN"):
        return "AVOID"
    if setup_state in ("PULLBACK", "BASE_FORMING"):
        if trigger_state == "CONFIRMED_TRIGGER":
            return "ENTER"
        if trigger_state == "EARLY_TRIGGER":
            return "PROBE"
        return "WATCH"
    if setup_state == "TREND_OK":
        return "TRENDING"
    return "AVOID"


def _evaluate_decision_score(*, setup_state: str, today_raw: dict,
                              yesterday_snap: Optional[dict],
                              recent_3d_closes: Optional[list],
                              risk_tags: list[str],
                              market_ret_5d_pct: Optional[float]) -> dict:
    """Score-driven decision evaluator. Returns full snapshot dict.

    See spec §7.4 for the algorithm.
    """
    from lifecycle_score import compute_trigger_score, compute_drift_score
    from lifecycle_score_config import (
        TRACK_TRIGGER, TRACK_DRIFT,
        DECISION_ENTER, DECISION_PROBE, DECISION_WATCH,
        DECISION_TRENDING, DECISION_AVOID,
        BADGE_PROBE_STRONG, VETO_UNKNOWN_SETUP,
        THRESHOLDS, DRIFT_ALLOW_ENTER,
        TRIGGER_TRACK_ACTIVE, DRIFT_TRACK_ACTIVE,
        SIZE_TIERS, DECISION_TO_TIER,
    )

    # ── Layer 0: hard risk veto ──
    veto = hard_risk_veto(setup_state, risk_tags)
    if veto:
        # Internal score still computed for analytics (spec §6.3).
        if setup_state in ("TREND_OK", "EXTENDED"):
            raw, raw_track = compute_drift_score(
                today_raw, yesterday_snap, recent_3d_closes, market_ret_5d_pct
            ), TRACK_DRIFT
        else:
            raw, raw_track = compute_trigger_score(
                today_raw, yesterday_snap, market_ret_5d_pct
            ), TRACK_TRIGGER
        return {
            "decision": DECISION_AVOID, "veto_reason": veto,
            "score": None, "score_track": None,
            "score_tier": None,                       # NEW
            "rs_tier": raw.rs_tier,                   # NEW (preserve RS tier for analytics)
            "features": None, "score_components": None,
            "active_components": None, "decision_badges": [],
            "_raw_score": raw.score, "_raw_features": raw.features,
            "_raw_score_track": raw_track,
            "suggested_entry_tier": None, "suggested_size_pct": 0.0,
            "rs_delta_pct": raw.rs_delta_pct,
            "trigger_state": "WAIT",
        }

    # ── Layer 2+3: score and promote ──
    if setup_state in ("PULLBACK", "BASE_FORMING"):
        sc = compute_trigger_score(today_raw, yesterday_snap, market_ret_5d_pct)
        track = TRACK_TRIGGER
        if not TRIGGER_TRACK_ACTIVE:
            # Trigger track not yet activated — degrade to WATCH but keep score visible.
            decision, badges = DECISION_WATCH, []
        elif sc.score >= THRESHOLDS["trigger_enter"]:
            decision, badges = DECISION_ENTER, []
        elif sc.score >= THRESHOLDS["trigger_probe"]:
            decision, badges = DECISION_PROBE, []
        else:
            decision, badges = DECISION_WATCH, []
    elif setup_state == "TREND_OK":
        sc = compute_drift_score(today_raw, yesterday_snap, recent_3d_closes, market_ret_5d_pct)
        track = TRACK_DRIFT
        if not DRIFT_TRACK_ACTIVE:
            # Drift track not yet activated — keep score visible, decision = TRENDING.
            decision, badges = DECISION_TRENDING, []
        elif sc.score >= THRESHOLDS["drift_enter"]:
            decision = DECISION_ENTER if DRIFT_ALLOW_ENTER else DECISION_PROBE
            badges   = [] if DRIFT_ALLOW_ENTER else [BADGE_PROBE_STRONG]
        elif sc.score >= THRESHOLDS["drift_probe"]:
            decision, badges = DECISION_PROBE, []
        else:
            decision, badges = DECISION_TRENDING, []
    else:
        # Unknown setup — safe fallback.
        return {
            "decision": DECISION_AVOID, "veto_reason": VETO_UNKNOWN_SETUP,
            "score": None, "score_track": None,
            "score_tier": None,                       # NEW
            "rs_tier": None,                          # NEW
            "features": None, "score_components": None,
            "active_components": None, "decision_badges": [],
            "_raw_score": None, "_raw_features": None, "_raw_score_track": None,
            "suggested_entry_tier": None, "suggested_size_pct": 0.0,
            "rs_delta_pct": None, "trigger_state": "WAIT",
        }

    tier_key = (decision, badges[0] if badges else None)
    tier = DECISION_TO_TIER.get(tier_key)
    size_pct = SIZE_TIERS.get(tier, SIZE_TIERS[None])["size_pct"]

    return {
        "decision": decision, "decision_badges": badges,
        "veto_reason": None,
        "score": sc.score, "score_track": track,
        "score_tier": sc.score_tier,        # NEW
        "rs_tier":    sc.rs_tier,           # NEW
        "active_components": sc.active_count,
        "features": sc.features, "score_components": sc.components_list,
        "rs_delta_pct": sc.rs_delta_pct,
        "suggested_entry_tier": tier,
        "suggested_size_pct": size_pct,
        "trigger_state": _derive_legacy_trigger_state(sc.score, track),
        "_raw_score": None, "_raw_features": None, "_raw_score_track": None,
    }


def compute_risk_tags(today: dict, yesterday_snapshot: Optional[dict]) -> list[str]:
    """Risk tags are derived metadata. Multiple may attach simultaneously."""
    # Re-import inside the function to allow monkeypatch to work in tests.
    from lifecycle_config import FAILED_BREAKOUT_REQUIRE_BELOW_PRIOR_LOW as STRICT
    tags: list[str] = []

    if (today.get("rsi14") or 0) >= RISK_OVERHEAT_RSI:
        tags.append("OVERHEAT")

    chg = today.get("change_pct")
    vr = today.get("volume_ratio")
    if (chg is not None and (chg / 100.0) >= RISK_PARABOLIC_RET_1D
            and vr is not None and vr >= RISK_PARABOLIC_VOL_RATIO):
        tags.append("PARABOLIC")

    # EXTENDED mirror — same predicate as setup_state's EXTENDED.
    if _is_extended(today):
        tags.append("EXTENDED")

    # FAILED_BREAKOUT — yesterday CONFIRMED + today close < ema9 (loose form).
    if yesterday_snapshot and yesterday_snapshot.get("trigger") == "CONFIRMED_TRIGGER":
        e9 = today.get("ema9")
        c = today.get("close")
        if e9 is not None and c is not None and c < e9:
            ok = True
            if STRICT:
                yl = (yesterday_snapshot.get("raw") or {}).get("low")
                ok = yl is not None and c < yl
            if ok:
                tags.append("FAILED_BREAKOUT")

    return tags


# ─────────────────────────────────────────────────────────────────
# Score engine v1 — hard veto + legacy trigger_state derivation
# Added per docs/superpowers/specs/2026-05-13-lifecycle-probabilistic-engine-design.md
# ─────────────────────────────────────────────────────────────────


def hard_risk_veto(setup_state: str, risk_tags: list[str]) -> Optional[str]:
    """Layer 0 — deterministic veto. Returns veto reason or None.

    Spec §4.1. Vetoes are structural failures; no probabilistic score can
    override. FAILED_BREAKOUT / BROKEN / EXTENDED only — see spec §4.2 for
    why OVERHEAT/PARABOLIC are NOT vetoes.
    """
    from lifecycle_score_config import (
        VETO_FAILED_BREAKOUT, VETO_BROKEN, VETO_EXTENDED,
    )
    if VETO_FAILED_BREAKOUT in (risk_tags or []):
        return VETO_FAILED_BREAKOUT
    if setup_state == "BROKEN":
        return VETO_BROKEN
    if setup_state == "EXTENDED":
        return VETO_EXTENDED
    return None


def _derive_legacy_trigger_state(score: Optional[int], track: Optional[str]) -> str:
    """Map score+track to legacy trigger_state enum (WAIT/EARLY/CONFIRMED).

    Spec §7.3. trigger_state is now a DERIVED compatibility field. Primary
    truth is score + decision. This mapping keeps Phase A consumers (history
    parsers, Telegram brief, page renderers) working without modification.
    """
    from lifecycle_score_config import THRESHOLDS, TRACK_TRIGGER, TRACK_DRIFT
    if score is None or track is None:
        return "WAIT"
    if track == TRACK_TRIGGER:
        if score >= THRESHOLDS["trigger_enter"]:
            return "CONFIRMED_TRIGGER"
        if score >= THRESHOLDS["trigger_probe"]:
            return "EARLY_TRIGGER"
        return "WAIT"
    if track == TRACK_DRIFT:
        # Drift never maps to CONFIRMED — drift is anticipatory, not confirmation.
        if score >= THRESHOLDS["drift_probe"]:
            return "EARLY_TRIGGER"
        return "WAIT"
    return "WAIT"


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def _build_today_raw_for_signal(md_entry: dict) -> dict:
    """Map fetch_market_data row to lifecycle_signal raw shape.

    score_v1 adds: open, high_20d_prior, atr14_pct_5d_avg, atr14_pct_20d_avg,
    days_sideways (now consistently populated by fetch_market_data).
    """
    return {
        "close": md_entry.get("price") or md_entry.get("close"),
        "open":  md_entry.get("open"),           # NEW — score_v1 lower_wick + intraday_reversal
        "high":  md_entry.get("high"),
        "low":   md_entry.get("low"),
        "ema9":  md_entry.get("ema9"),
        "ema21": md_entry.get("ema21"),
        "ema65": md_entry.get("ema65"),
        "ema21_slope_5d": md_entry.get("ema21_slope_5d"),
        "ema65_slope_5d": md_entry.get("ema65_slope_5d"),
        "rsi14": md_entry.get("rsi14"),
        "atr14": md_entry.get("atr14"),           # NEW — score_v1 tight_range + tight_close_cluster
        "atr14_pct": md_entry.get("atr14_pct"),
        "atr14_pct_5d_avg":   md_entry.get("atr14_pct_5d_avg"),   # NEW (was passed-None before)
        "atr14_pct_20d_avg":  md_entry.get("atr14_pct_20d_avg"),  # NEW
        "volume_ratio": md_entry.get("volume_ratio"),
        "volume_5d_avg":  md_entry.get("volume_5d_avg"),
        "volume_20d_avg": md_entry.get("volume_20d_avg"),
        "high_20d_prior": md_entry.get("high_20d_prior"),  # NEW — score_v1 breakout
        "change_pct":   md_entry.get("change_pct"),
        "change_5d_pct": md_entry.get("change_5d_pct"),    # NEW — score_v1 rs_strong
        "days_sideways":      md_entry.get("days_sideways"),
        "sector": md_entry.get("sector") or md_entry.get("sector_etf"),
    }


def _make_snapshot(date_str: str, raw: dict, setup: str, trigger: str,
                   decision: str, risk_tags: list[str],
                   score_payload: Optional[dict] = None) -> dict:
    """Build a snapshot dict.

    score_payload (when present) merges in the new score_v1 fields:
      score, score_track, active_components, features, score_components,
      decision_badges, veto_reason, suggested_entry_tier, suggested_size_pct,
      rs_delta_pct, engine_version, _raw_score / _raw_features / _raw_score_track.
    """
    from lifecycle_score_config import ENGINE_VERSION

    e9, e21, c = raw.get("ema9"), raw.get("ema21"), raw.get("close")
    snap = {
        "date":            date_str,
        "engine_version":  ENGINE_VERSION,
        "setup":           setup,
        "trigger":         trigger,
        "decision":        decision,
        "raw": {
            "close": c,
            "open":  raw.get("open"),
            "high":  raw.get("high"),
            "low":   raw.get("low"),
            "ema9":  e9,
            "ema21": e21,
            "ema65": raw.get("ema65"),
            "rsi14": raw.get("rsi14"),
            "dist_ema9_pct":  round(abs(c - e9) / e9 * 100, 4) if (c and e9) else None,
            "dist_ema21_pct": round(abs(c - e21) / e21 * 100, 4) if (c and e21) else None,
            "volume_ratio":   raw.get("volume_ratio"),
            "atr_pct":        raw.get("atr14_pct"),
            "high_20d_prior": raw.get("high_20d_prior"),
            "sector":         raw.get("sector"),
            "risk_tags":      risk_tags,
        },
    }

    if score_payload:
        # Merge new fields verbatim — they were built by _evaluate_decision_score.
        for k in ("score", "score_track", "score_tier", "rs_tier",
                  "active_components", "features",
                  "score_components", "decision_badges", "veto_reason",
                  "suggested_entry_tier", "suggested_size_pct", "rs_delta_pct",
                  "_raw_score", "_raw_features", "_raw_score_track"):
            snap[k] = score_payload.get(k)

    return snap


def compute_single_snapshot(*, ticker: str,
                              market_data_entry: dict,
                              market_ret_5d_pct: Optional[float],
                              yesterday: Optional[dict],
                              today: str,
                              regime: Optional[str] = None,
                              _y_snap_list_for_drift: Optional[list] = None,
                              ) -> Optional[dict]:
    """Build a lifecycle snapshot for one ticker without touching history.

    Mirrors the per-ticker body of process_universe. Returns None for skipped
    tickers (missing close/ema9, or `error` in market_data_entry).

    `yesterday` may be None — internally normalized to an empty raw dict so the
    Phase A trigger helpers (which call yesterday.get(...)) remain None-safe.
    With no yesterday, trigger will resolve to WAIT.

    The internal `_y_snap_list_for_drift` kwarg is used ONLY by process_universe
    to preserve the 3-day-close window for drift scoring across the full
    yesterday-snapshots list. External callers should leave it as None — in
    that case we fall back to just `yesterday` (if present) for the window.
    """
    import os
    from lifecycle_score_config import (
        DEFAULT_ENGINE_MODE, MODE_SCORE_SHADOW, MODE_SCORE_ACTIVE,
    )
    from lifecycle_score import compute_trigger_score, compute_drift_score

    mode = os.environ.get("LIFECYCLE_ENGINE_MODE", DEFAULT_ENGINE_MODE)

    if not market_data_entry or "error" in market_data_entry:
        return None
    today_raw = _build_today_raw_for_signal(market_data_entry)
    if today_raw["close"] is None or today_raw["ema9"] is None:
        return None

    # Normalize yesterday: process_universe builds y_for_legacy_trigger from y_raw
    # (which is {} when no history). Same here — pass {} so .get() is safe inside
    # _is_early_trigger / _is_confirmed_trigger.
    y_raw = (yesterday or {}).get("raw") or {}
    y_for_legacy_trigger = {
        "close": y_raw.get("close"),
        "ema9":  y_raw.get("ema9"),
        "high":  y_raw.get("high"),
    }

    # Layer 1 — setup state (unchanged from Phase A)
    setup = evaluate_setup_state(today_raw)
    trigger = evaluate_trigger_state(today_raw, y_for_legacy_trigger, setup)
    risk_tags = compute_risk_tags(today_raw, yesterday)

    # Last 3 closes for drift's tight_close_cluster.
    # For active_set tickers, process_universe passes the full y_snap_list via
    # _y_snap_list_for_drift to preserve the original window. For momentum-only
    # callers (no history), we use just `yesterday` if present.
    recent_3d_closes = []
    src_list = _y_snap_list_for_drift if _y_snap_list_for_drift is not None else (
        [yesterday] if yesterday else []
    )
    for s in src_list[-3:]:
        c = (s.get("raw") or {}).get("close")
        if c is not None:
            recent_3d_closes.append(c)
    recent_3d_closes.append(today_raw["close"])  # include today

    # Build yesterday_snap for higher_low / ema_reclaim component access
    yesterday_snap_for_score = {
        "close": y_raw.get("close"),
        "low":   y_raw.get("low"),
        "high":  y_raw.get("high"),
        "ema9":  y_raw.get("ema9"),
    } if yesterday else None

    score_payload = None
    if mode in (MODE_SCORE_SHADOW, MODE_SCORE_ACTIVE):
        # Compute scores in BOTH shadow and active modes.
        # Shadow: scores stored, decision from Phase A path.
        # Active: scores drive decision (via evaluate_decision dispatch).
        decision = evaluate_decision(
            setup, trigger, risk_tags=risk_tags, regime=regime,
            today_raw=today_raw,
            yesterday_snap=yesterday_snap_for_score,
            recent_3d_closes=recent_3d_closes,
            market_ret_5d_pct=market_ret_5d_pct,
        )
        if isinstance(decision, dict):
            # score_active path — payload is the full evaluator result.
            score_payload = decision
            final_decision = decision["decision"]
            final_trigger = decision["trigger_state"]
        else:
            # score_shadow path — decision is Phase A str. Compute scores
            # for storage WITHOUT affecting the decision.
            final_decision = decision
            final_trigger = trigger
            if setup in ("TREND_OK", "EXTENDED"):
                sc = compute_drift_score(
                    today_raw, yesterday_snap_for_score,
                    recent_3d_closes, market_ret_5d_pct,
                )
                track = "drift"
            else:
                sc = compute_trigger_score(
                    today_raw, yesterday_snap_for_score, market_ret_5d_pct,
                )
                track = "trigger"
            score_payload = {
                "score": sc.score, "score_track": track,
                "score_tier": sc.score_tier,         # NEW
                "rs_tier":    sc.rs_tier,            # NEW
                "active_components": sc.active_count,
                "features": sc.features,
                "score_components": sc.components_list,
                "decision_badges": [], "veto_reason": None,
                "suggested_entry_tier": None, "suggested_size_pct": 0.0,
                "rs_delta_pct": sc.rs_delta_pct,
                "_raw_score": None, "_raw_features": None, "_raw_score_track": None,
            }
    else:
        # mode == "legacy" — call without score inputs.
        decision = evaluate_decision(setup, trigger,
                                      risk_tags=risk_tags, regime=regime)
        final_decision = decision
        final_trigger = trigger

    return _make_snapshot(
        today, today_raw, setup, final_trigger, final_decision, risk_tags,
        score_payload=score_payload,
    )


def process_universe(*, active_set: set[str], market_data: dict,
                     yesterday_state: dict, today: str,
                     regime: Optional[str] = None,
                     market_ret_5d_pct: Optional[float] = None) -> dict:
    """Run setup/trigger/decision/risk_tags across the active set.

    Now also computes scores (when LIFECYCLE_ENGINE_MODE != legacy) and
    passes them through to snapshots.

    Returns:
      {"as_of": today, "snapshots": {ticker: snapshot}, "skipped": [...]}
    """
    flat = market_data.get("data") if isinstance(market_data, dict) and "data" in market_data else market_data
    snapshots: dict[str, dict] = {}
    skipped: list[str] = []

    for ticker in sorted(active_set):
        entry = (flat or {}).get(ticker)
        if not entry or "error" in entry:
            skipped.append(ticker)
            continue

        # Resolve yesterday from history
        y_block = (yesterday_state.get("tickers") or {}).get(ticker)
        y_snap_list = (y_block or {}).get("snapshots", [])
        yesterday = y_snap_list[-1] if y_snap_list else None

        # Delegate per-ticker computation to compute_single_snapshot. Pass the
        # full y_snap_list via the internal _y_snap_list_for_drift kwarg so the
        # 3-day-close window used for drift scoring matches the original loop
        # exactly (byte-equivalent for golden-test parity).
        snap = compute_single_snapshot(
            ticker=ticker,
            market_data_entry=entry,
            market_ret_5d_pct=market_ret_5d_pct,
            yesterday=yesterday,
            today=today,
            regime=regime,
            _y_snap_list_for_drift=y_snap_list,
        )
        if snap is None:
            skipped.append(ticker)
            continue
        snapshots[ticker] = snap

    return {"as_of": today, "snapshots": snapshots, "skipped": skipped}


def run_lifecycle(market: str, *, project_dir: str, market_data: dict,
                  momentum_history_path: str, portfolio_tickers: set,
                  today: str) -> dict:
    """One-call entry: load history, compute active set, evaluate, write back.

    Returns: { status, market, as_of, snapshots, transitions, skipped, ... }
    """
    import json
    import os as _os
    from lifecycle_history import (
        load_lifecycle_history, save_lifecycle_history,
        compute_active_set, append_snapshot, append_transition,
        compute_transitions, bootstrap_active_set,
        normalize_momentum_history,
    )
    from market_benchmark import get_market_ret_5d

    history_dir = _os.path.join(project_dir, "history")
    _os.makedirs(history_dir, exist_ok=True)
    state_path = _os.path.join(history_dir, f"lifecycle_history_{market.lower()}.json")

    # NEW: fetch market benchmark ONCE per run (cached, with 3d fallback).
    market_ret_5d_pct = get_market_ret_5d(market, project_dir=project_dir)
    print(f"[lifecycle:{market}] market_ret_5d_pct = {market_ret_5d_pct}")

    # ── existing momentum_state / active_set logic unchanged ──
    momentum_state = {"tickers": {}}
    _scanner_raw: dict = {}          # raw scanner format for top5 selector
    if _os.path.exists(momentum_history_path):
        try:
            with open(momentum_history_path, "rb") as f:
                raw_momentum = json.loads(f.read().rstrip(b" \t\n\r\x00").decode("utf-8"))
            _scanner_raw = raw_momentum          # keep {"data": {ticker: {date: entry}}}
            momentum_state = normalize_momentum_history(raw_momentum)
        except Exception as e:
            print(f"[lifecycle:{market}] WARN momentum history load failed ({e})")

    state = load_lifecycle_history(state_path, market=market)
    if not state["tickers"] and not state.get("_bootstrap_meta"):
        state = bootstrap_active_set(market=market,
                                     momentum_history=momentum_state,
                                     portfolio_tickers=portfolio_tickers,
                                     today=today)

    active = compute_active_set(momentum_history=momentum_state,
                                lifecycle_state=state,
                                portfolio_tickers=portfolio_tickers,
                                today=today)
    if not active:
        return {"status": "ok", "market": market, "as_of": today,
                "snapshots": {}, "transitions": [], "skipped": [],
                "active_set_size": 0}

    # ── existing missing-ticker fetch logic unchanged ──
    flat = market_data.get("data") if isinstance(market_data, dict) and "data" in market_data else market_data
    flat = flat or {}
    missing = sorted(tk for tk in active if tk not in flat)
    if missing:
        print(f"[lifecycle:{market}] fetching {len(missing)} active-set tickers absent from market_data...")
        from fetch_market_data import fetch_ticker
        fetched_count = 0
        merged = dict(flat)
        for tk in missing:
            try:
                row = fetch_ticker(tk)
                if row and "error" not in row:
                    merged[tk] = row
                    fetched_count += 1
            except Exception as fetch_err:
                print(f"  WARN [lifecycle:{market}] fetch {tk}: {fetch_err}")
        print(f"[lifecycle:{market}] fetched {fetched_count}/{len(missing)} successfully")
        if isinstance(market_data, dict) and "data" in market_data:
            market_data = {**market_data, "data": merged}
        else:
            market_data = merged

    # NEW: pass market_ret_5d_pct into process_universe
    proc = process_universe(active_set=active, market_data=market_data,
                            yesterday_state=state, today=today,
                            market_ret_5d_pct=market_ret_5d_pct)

    new_transitions: list[dict] = []
    for ticker, today_snap in proc["snapshots"].items():
        y_block = (state.get("tickers") or {}).get(ticker)
        y_snap_list = (y_block or {}).get("snapshots", [])
        y_snap = y_snap_list[-1] if y_snap_list else None
        events = compute_transitions(ticker, y_snap, today_snap)
        new_transitions.extend(events)
        append_snapshot(state, ticker, today_snap)

    state["transitions"].extend(new_transitions)
    # Mark current engine version on the state (top-level)
    from lifecycle_score_config import ENGINE_VERSION as _EV
    state["current_engine_version"] = _EV
    state["market"] = market
    save_lifecycle_history(state, state_path)

    return {
        "status": "ok",
        "market": market,
        "as_of":  today,
        "snapshots":   proc["snapshots"],
        "transitions": new_transitions,
        "skipped":     proc["skipped"],
        "active_set_size": len(active),
        "state":       state,
        "engine_version": _EV,
        "market_ret_5d_pct": market_ret_5d_pct,
        "momentum_history": _scanner_raw,     # raw scanner format for top5 selector
    }
