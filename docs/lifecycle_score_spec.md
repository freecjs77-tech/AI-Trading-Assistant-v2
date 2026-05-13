# Lifecycle Score Engine v1 — Runtime Reference

**Engine version**: `score_v1`
**Source design**: [docs/superpowers/specs/2026-05-13-lifecycle-probabilistic-engine-design.md](./superpowers/specs/2026-05-13-lifecycle-probabilistic-engine-design.md)
**Last updated**: 2026-05-13

This file is a fast lookup for operators. The design doc is authoritative.

---

## Quick reference

### Layer 0 — Veto (deterministic)
Returns `AVOID` immediately. Three triggers:
- `FAILED_BREAKOUT` risk tag present
- `setup_state == "BROKEN"`
- `setup_state == "EXTENDED"`

### Layer 2 — Score (probabilistic)
- **trigger_score** (PULLBACK/BASE_FORMING): 9 components, max 14 pts
  - ema_reclaim(+2) higher_low(+2) rs_strong(+2) vol_expansion(+2) breakout(+2)
    lower_wick(+1) tight_range(+1) close_strong(+1) intraday_reversal(+1)
- **drift_score** (TREND_OK): 7 components, max 9 pts
  - higher_low(+2) rs_strong(+2) ema_alignment(+1) close_above_ema9(+1)
    atr_contraction(+1) low_vol_drift(+1) tight_close_cluster(+1)

### Layer 3 — Decision
| Setup | Track | Score | Decision |
|---|---|---|---|
| PULLBACK / BASE_FORMING | trigger | ≥ 7 | ENTER |
| PULLBACK / BASE_FORMING | trigger | 3-6 | PROBE |
| PULLBACK / BASE_FORMING | trigger | < 3 | WATCH |
| TREND_OK | drift | ≥ 6 | PROBE + PROBE_STRONG badge |
| TREND_OK | drift | 4-5 | PROBE |
| TREND_OK | drift | < 4 | TRENDING |

### Sizing hints
- ENTER → `core` tier, 0.35
- PROBE + PROBE_STRONG → `starter_plus`, 0.25
- PROBE → `starter`, 0.25
- WATCH / TRENDING / AVOID → null, 0.0

## Engine modes

Set via `LIFECYCLE_ENGINE_MODE` env var:
- `legacy` — Phase A boolean path (rollback target)
- `score_shadow` — score computed + stored; decision from Phase A (PR#1 default)
- `score_active` — score-driven decision (PR#2+ default)

## Activation flags (in `lifecycle_score_config.py`)
- `TRIGGER_TRACK_ACTIVE` — `False` in PR#1, `True` in PR#2+
- `DRIFT_TRACK_ACTIVE` — `False` in PR#1+PR#2, `True` in PR#3+
- `DRIFT_ALLOW_ENTER` — `False` always until calibration says otherwise

## Rollback
```bash
LIFECYCLE_ENGINE_MODE=legacy python pipeline.py
```

No code revert needed. History JSON's new fields remain (harmless extras).

## See also
- Design dialogue context: brainstorm/spec docs above
- Test invariants: [tests/test_lifecycle_invariants.py](../tests/test_lifecycle_invariants.py)
- Decision matrix: [tests/test_lifecycle_decision_matrix.py](../tests/test_lifecycle_decision_matrix.py)
- Calibration boundary (archetype-collapse guardrail): spec §11.1
