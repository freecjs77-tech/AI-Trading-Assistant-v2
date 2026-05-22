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
