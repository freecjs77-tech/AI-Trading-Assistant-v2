# tests/test_lifecycle_golden.py
"""Phase A — Golden regression contract (spec §9).

Each scenario is a synthetic price+indicator history that drives a specific
state-machine path. Any rule change that breaks one of these tests must be
deliberate and the test file must be updated in the same commit.
"""
import pytest

from lifecycle_signal import (
    evaluate_setup_state, evaluate_trigger_state,
    evaluate_decision, compute_risk_tags,
)


# ── Scenario builder helpers ────────────────────────────
def _row(close, high, low, ema9, ema21, ema65, *,
          rsi=50, vol_ratio=1.0, slope65=0.3, slope21=0.3,
          days_sideways=0, atr5=2.0, atr20=2.0, vol5=1e6, vol20=1e6,
          change_pct=0.5):
    return {
        "close": close, "high": high, "low": low,
        "ema9": ema9, "ema21": ema21, "ema65": ema65,
        "rsi14": rsi, "volume_ratio": vol_ratio,
        "ema65_slope_5d": slope65, "ema21_slope_5d": slope21,
        "days_sideways": days_sideways,
        "atr14_pct_5d_avg": atr5, "atr14_pct_20d_avg": atr20,
        "volume_5d_avg": vol5, "volume_20d_avg": vol20,
        "atr14_pct": atr5,
        "change_pct": change_pct,
        "sector": "Technology",
    }


# ── Scenario 1: cooling_off — EXTENDED → TREND_OK → PULLBACK ───────────
def test_golden_cooling_off():
    days = [
        _row(close=120, high=121, low=118, ema9=105, ema21=98, ema65=90, rsi=78),  # EXTENDED
        _row(close=112, high=113, low=110, ema9=106, ema21=99, ema65=91),           # TREND_OK
        _row(close=104, high=107, low=103, ema9=105, ema21=100, ema65=91),          # PULLBACK
    ]
    setups = [evaluate_setup_state(d) for d in days]
    assert setups == ["EXTENDED", "TREND_OK", "PULLBACK"]


# ── Scenario 2: clean_entry — TREND_OK → PULLBACK → EARLY → CONFIRMED ──
def test_golden_clean_entry():
    days = [
        _row(close=104, high=105, low=103, ema9=99.5, ema21=97, ema65=90),
        _row(close=97.5, high=98, low=97, ema9=99,    ema21=97, ema65=90),
        _row(close=99.6, high=99.8, low=97.5, ema9=99, ema21=97, ema65=90),
        _row(close=101.5, high=101.8, low=100, ema9=99, ema21=97, ema65=90,
              vol_ratio=1.5),
    ]
    setups = [evaluate_setup_state(d) for d in days]
    assert setups[0] == "TREND_OK"
    # Day 2 close (97.5) is below ema9 (99) by ~1.5%, above ema21, alignment ok → PULLBACK.
    assert setups[1] == "PULLBACK"
    # Day 3 close (99.6) within 0.4% of ema9, above ema21 → PULLBACK.
    assert setups[2] == "PULLBACK"
    # Day 4 close (101.5), 2.5% above ema9 → still PULLBACK (≤3%).
    assert setups[3] == "PULLBACK"

    # Triggers — pass yesterday's row as the "yesterday" arg.
    trig_d3 = evaluate_trigger_state(days[2], days[1], setups[2])
    assert trig_d3 == "EARLY_TRIGGER"  # day-2 close 97.5 ≤ ema9 99, day-3 close 99.6 > 99
    trig_d4 = evaluate_trigger_state(days[3], days[2], setups[3])
    assert trig_d4 == "CONFIRMED_TRIGGER"  # vol 1.5x + close in upper 20% (101.5 vs high 101.8/low 100)
    assert evaluate_decision(setups[3], trig_d4) == "ENTER_OK"


# ── Scenario 3: failed_breakout ───────────────────────────────────────
def test_golden_failed_breakout():
    confirmed_day = _row(close=101.5, high=101.8, low=100, ema9=99, ema21=97, ema65=90,
                          vol_ratio=1.5)
    today = _row(close=98.5, high=99.5, low=97.5, ema9=100, ema21=97, ema65=90,
                  change_pct=-3.0)
    yesterday_snapshot = {
        "trigger": "CONFIRMED_TRIGGER",
        "raw": {"close": 101.5, "ema9": 99, "high": 101.8, "low": 100,
                 "risk_tags": []},
    }
    setup = evaluate_setup_state(today)
    trig = evaluate_trigger_state(today, yesterday_snapshot["raw"], setup)
    risk_tags = compute_risk_tags(today, yesterday_snapshot)
    assert trig == "WAIT"
    assert "FAILED_BREAKOUT" in risk_tags
    assert evaluate_decision(setup, trig, risk_tags=risk_tags) == "AVOID"


# ── Scenario 4: structure_break — TREND_OK → BROKEN ────────────────────
def test_golden_structure_break():
    pre = _row(close=104, high=105, low=103, ema9=99.5, ema21=97, ema65=90)
    post = _row(close=92, high=94, low=91, ema9=95, ema21=88, ema65=90)
    assert evaluate_setup_state(pre) == "TREND_OK"
    assert evaluate_setup_state(post) == "BROKEN"


# ── Scenario 5: weak_volume — PULLBACK + reclaim but vol < 1.2 → EARLY only ──
def test_golden_weak_volume():
    yesterday = _row(close=98.5, high=99, low=97.5, ema9=99, ema21=97, ema65=90)
    today = _row(close=99.6, high=100, low=98, ema9=99, ema21=97, ema65=90,
                  vol_ratio=0.9)
    setup = evaluate_setup_state(today)
    assert setup == "PULLBACK"
    trig = evaluate_trigger_state(today, yesterday, setup)
    assert trig == "EARLY_TRIGGER"


# ── Scenario 6: gap_up_exhaustion — close in lower portion stays WAIT ────
def test_golden_gap_up_exhaustion():
    """Spec §9 #6 — gap up that closes weak should NOT register EARLY_TRIGGER.

    Per the close-in-upper-band gate on the prior-high arm of _is_early_trigger
    (added in Task 4 to match spec §9 row 6 description "trigger stays at WAIT"),
    an exhaustion gap-up where close is in the lower portion of the day's
    range fails the trigger evaluation entirely.

    Day setup:
      yesterday: close=99.5, high=100, low=98 — quiet day, close > ema9=99.
      today:     close=100.5, high=104, low=100 — large gap up + high range,
                 but close 100.5 lands at the bottom of [100, 104] (vol 2.0x).

    Trigger checks:
      - ema9 reclaim: yesterday_close 99.5 > ema9 99 → arm 1 fails.
      - prior-high break: today_high 104 > yesterday_high 100 → arm 2 candidate.
        close-in-upper-band check: threshold = 104*0.8 + 100*0.2 = 103.2.
        close 100.5 < 103.2 → arm 2 fails.
      → trigger == WAIT.
    """
    yesterday = _row(close=99.5, high=100, low=98, ema9=99, ema21=97, ema65=90)
    today = _row(close=100.5, high=104, low=100, ema9=99, ema21=97, ema65=90,
                  vol_ratio=2.0)
    setup = evaluate_setup_state(today)
    trig = evaluate_trigger_state(today, yesterday, setup)
    assert trig == "WAIT"
