# Trade Lifecycle System — Roadmap

**Date**: 2026-05-08
**Owner**: freecjs77@gmail.com
**Status**: Phase A spec drafted; B/C/D placeholders only

## 1. Why this roadmap exists

The current system finds strong stocks well (sector RS gate, M1/M2/M3, risk tags) but cannot answer **"when do I actually enter, and how big?"** Today's gap is between *discovery* and *execution*. Adding more indicators on top of the scanner won't close it; the gap is structural.

The roadmap converts the system from a daily *snapshot scanner* into a *stateful lifecycle tracker*: every active ticker has a setup state, a trigger state, a decision, and a daily history that supports later expectancy analysis.

The roadmap is divided into four phases. Each later phase consumes outputs of the prior one; none of them depend on indicators that don't exist yet.

```
Phase A   Trend Structure + Setup/Trigger lifecycle (entry quality)
   ↓
Phase B   Market Regime + Sector Heat (environment filter)
   ↓
Phase C   Position Sizing + Multi-stage Entry + Initial Stop (sizing)
   ↓
Phase D   Expectancy Engine (statistical validation, R-multiple journal)
```

## 2. Guiding constraints (apply to every phase)

- **Never replace existing systems.** signal_judge v5.4 (mean-reversion entries) and momentum_scanner v1.0 (trend discovery) keep their current responsibilities. The lifecycle layer is additive.
- **Raw values over composite scores.** No `entry_score 87` summary numbers. Every state must be reproducible from raw fields a user can inspect.
- **Decisions are advisory.** No auto-trading. The system narrows the field; the human still places the order.
- **Snapshots stay minimal.** Save only what future expectancy analysis needs. Derived fields (`days_in_pullback`, `setup_streak`, `trigger_age_days`) are recomputed on read, not stored.
- **Module isolation.** Each phase ships a separate module + its own history JSON. No phase reaches across into another's internals.

## 3. Phase A — Trend Structure + Setup / Trigger lifecycle

**Goal:** For every active US/KR ticker, produce a daily `setup_state ∈ {TREND_OK, PULLBACK, BASE_FORMING, EXTENDED, BROKEN}` + `trigger_state ∈ {WAIT, EARLY_TRIGGER, CONFIRMED_TRIGGER}` + `entry_decision ∈ {ENTER_OK, EARLY, STAGING, AVOID}`, plus `FAILED_BREAKOUT` as a derived risk_tag + transition event (not a trigger_state — failure is not a forward-looking entry phase). Persist a snapshot per ticker per day, and surface the result on a dedicated `lifecycle_us.html` / `lifecycle_kr.html` page plus a daily Telegram brief.

**Inputs:** `fetch_market_data.py` price/indicator output (extended with `ema9`, `ema21`, `ema65`, `ema21_slope_5d`, `ema65_slope_5d`); existing `momentum_signal.py` M1/M2/M3 output (used only to seed the active set); `portfolio.md` (only to *exclude* held tickers from the active set).

**Outputs:**
- `history/lifecycle_history_us.json`, `history/lifecycle_history_kr.json` (ticker-keyed snapshots + transitions log)
- `reports/lifecycle_us_<DATE>.html`, `reports/lifecycle_kr_<DATE>.html`
- Telegram lifecycle brief (daily, US + KR sections, "🆕 New CONFIRMED Today" highlight)

**Open questions deferred to detail spec:** active-set bootstrap behaviour on first run; transition log archival cadence; whether `trigger_age_days` eventually splits into `confirmed_age_days` + `early_age_days` (Phase D decides).

**Detail spec:** [`2026-05-08-trade-lifecycle-phase-a-design.md`](2026-05-08-trade-lifecycle-phase-a-design.md)

## 4. Phase B — Market Regime + Sector Heat

**Goal:** Classify the daily market environment into `RISK_ON / TRENDING / CHOPPY / RISK_OFF` and produce a sector heat dashboard that explains *why this ticker, why now*. Feed both into the lifecycle decision layer so that, e.g., `RISK_OFF` downgrades `ENTER_OK` → `STAGING`.

**Inputs from Phase A:** the `evaluate_decision(setup, trigger, regime=None)` hook is already present; B fills `regime`. The lifecycle page already has a `[1] MARKET STATE` placeholder section; B fills it.

**Inputs from existing system:** `momentum_signal.evaluate_sector()` already computes per-sector RS, ret_5d, volume_ratio — Phase B aggregates these into a heatmap rather than re-implementing.

**Outputs:**
- `regime_classifier.py` returning `{state, score_components, raw}`
- Sector heat JSON consumed by the lifecycle page
- A small regime/sector card on the existing portfolio report (one-line indicator)

**Open questions:** breadth indicator source (advance/decline lines aren't in yfinance core — proxy via SPY/QQQ percent above MA50?); how often regime should change before downgrading existing decisions (hysteresis vs immediate).

**Risks:** regime classification with too few inputs becomes a noisy signal that flip-flops daily. Need at least 3 independent components (e.g. SPY vs MA50, VIX level, sector breadth) and a hysteresis buffer.

## 5. Phase C — Position Sizing + Multi-stage Entry + Initial Stop

**Goal:** When `entry_decision == ENTER_OK`, attach a recommended position size based on account risk + ATR-derived stop distance, plus a 3-stage scale-in plan (Pilot 25% / Confirm 25% / Follow-through 50%). Add a separate `initial_stop` (used during the first ~3 days after entry) that is distinct from the existing trailing stop.

**Inputs from Phase A:** `entry_decision`, `setup_state`, `trigger_state`, raw `atr_pct`. The lifecycle Decision Card has a `Recommended size: TBD — Phase C` placeholder.
**Inputs from Phase B:** regime — `RISK_ON` allows full sizing, `CHOPPY` halves it, `RISK_OFF` blocks new pilots.
**Inputs from existing system:** `portfolio_stop_signal.py` already has trailing-stop infrastructure with ATR-based clamps. Phase C adds initial stop alongside it without disturbing trailing logic.

**Outputs:**
- `position_sizing.py` (account-risk-based formula + stage planner)
- `initial_stop.py` or extension of `portfolio_stop_signal.py`
- Sizing card on the lifecycle page; stage progress on the existing portfolio report (when a holding goes from pilot → confirm → follow-through)

**Open questions:** account size source (single config file vs split me/wife totals); whether stage advancement is automatic on next-day signal or requires manual confirmation.

**Risks:** sizing rules that look correct on paper but fight existing portfolio.md state. Phase C must make sizing recommendations *advisory* and never write to portfolio.md.

## 6. Phase D — Expectancy Engine

**Goal:** For every transition sequence in the lifecycle history (e.g. `PULLBACK → EARLY → CONFIRMED`), compute forward returns at +3d / +5d / +10d, R-multiples (using Phase C's stop distance), and per-setup win rate. Produce a journal page that turns "feels like a good trade" into "this exact transition shape historically returns +1.8R at 62% win rate".

**Inputs from Phase A:** `lifecycle_history_*.json` is already designed for this — snapshots include `close/high/low` so forward returns and MAE/MFE are computable post-hoc.
**Inputs from Phase C:** stop distance per entry → R-multiples instead of raw percent returns.

**Outputs:**
- `expectancy_engine.py` running over historical lifecycle JSON
- `reports/expectancy_<DATE>.html` with setup-by-setup win rate / avg R / sample size
- Telegram weekly digest (Sunday) of last week's transitions and their forward results

**Open questions:** minimum sample size before reporting an expectancy figure (likely n ≥ 20); how to handle survivorship bias when active-set membership itself depends on momentum performance.

**Risks:** premature expectancy reporting on small samples becomes overconfident noise. Default to "insufficient data" labels until n ≥ 20 per cell.

## 7. Phase boundaries — what does NOT cross between phases

| From | To | Forbidden |
|---|---|---|
| Phase A | Phase B | A must not import regime state. The decision hook accepts `regime=None`. |
| Phase B | Phase C | B must not size positions. It outputs only environment classification. |
| Phase C | Phase D | C must not compute returns or win rates. It outputs only sizing + initial stop. |
| Phase D | (any) | D is read-only. It never writes back into Phases A/B/C state. |

This isolation is what makes the roadmap safe to build phase by phase — each phase ships a working slice without breaking the others.

## 8. Order of implementation and approximate scope

| Phase | Approx tasks | Approx duration | Blocks the next phase? |
|---|---|---|---|
| A | ~25 (similar shape to momentum-scanner plan) | 1 working session worth | Yes — B needs Phase A's hook in place |
| B | ~12 | half a session | Yes — C consumes regime |
| C | ~15 | full session | Mostly no — D can run on partial C output |
| D | ~20 | full session | No — D is terminal |

## 9. What this roadmap is *not*

- Not auto-trading. No order placement, no broker integration, ever.
- Not a replacement for `signal_judge`. The mean-reversion BUY/EXIT logic remains. Lifecycle is a parallel discovery+timing track for trend-followed names.
- Not a permanent freeze on indicators. New raw fields can be added per phase, but composite scores remain forbidden.
- Not a backtest framework. Phase D measures *forward* expectancy from accumulated lifecycle history. It does not run hypothetical historical strategies.

## 10. Acceptance criterion for the roadmap itself

Phase A is the first concrete deliverable. The roadmap is "valid" once Phase A ships and:

- The lifecycle pages render without errors for at least 5 consecutive trading days
- `lifecycle_history_*.json` accumulates ≥ 100 ticker-day snapshots
- At least one `EXTENDED → PULLBACK → CONFIRMED_TRIGGER` transition is visible in the transitions log

If any of those fail after a full week, the design is wrong and the roadmap is revisited before B/C/D begin.
