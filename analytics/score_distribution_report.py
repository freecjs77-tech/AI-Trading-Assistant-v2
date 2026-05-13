# analytics/score_distribution_report.py
"""Calibration helper — emit score distribution stats from lifecycle history.

Usage:
    python analytics/score_distribution_report.py [US|KR|all]
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
HISTORY = PROJECT_DIR / "history"


def report(market: str):
    path = HISTORY / f"lifecycle_history_{market.lower()}.json"
    if not path.exists():
        print(f"  (no history for {market})")
        return

    with open(path, "rb") as f:
        state = json.loads(f.read().decode("utf-8"))

    score_histogram = Counter()
    feature_freq = Counter()
    decisions = Counter()
    by_track = Counter()
    probe_to_enter_streaks = 0
    probe_to_avoid_streaks = 0

    for tk, blk in (state.get("tickers") or {}).items():
        snaps = blk.get("snapshots") or []
        for i, snap in enumerate(snaps):
            sc = snap.get("score")
            if sc is not None:
                score_histogram[sc] += 1
                by_track[snap.get("score_track")] += 1
                for fname, active in (snap.get("features") or {}).items():
                    if active:
                        feature_freq[fname] += 1
            decisions[snap.get("decision")] += 1

            # PROBE → next-day outcome (informational)
            if snap.get("decision") == "PROBE" and i + 1 < len(snaps):
                nxt = snaps[i + 1].get("decision")
                if nxt == "ENTER":
                    probe_to_enter_streaks += 1
                elif nxt == "AVOID":
                    probe_to_avoid_streaks += 1

    total = sum(score_histogram.values())
    print(f"\n=== {market} score distribution (n={total}) ===")
    if total > 0:
        for sc in sorted(score_histogram):
            bar = "█" * int(score_histogram[sc] / max(score_histogram.values()) * 30)
            print(f"  {sc:>2d}: {score_histogram[sc]:>4d} {bar}")
    print(f"\nBy track: {dict(by_track)}")
    print(f"Decision distribution: {dict(decisions)}")
    print(f"\nFeature activation frequency (top 10):")
    for f, n in feature_freq.most_common(10):
        print(f"  {f:<25s} {n}")
    print(f"\nPROBE → ENTER (next day): {probe_to_enter_streaks}")
    print(f"PROBE → AVOID (next day): {probe_to_avoid_streaks}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    if arg.upper() == "ALL":
        for m in ("US", "KR"):
            report(m)
    else:
        report(arg.upper())
