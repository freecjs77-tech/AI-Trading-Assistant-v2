# Emerging Momentum + Maturity Classifier v1.5 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Emerging Momentum (EM) tier + Maturity classifier (EARLY/MID/EXTENDED) to the momentum scanner without altering v5.3 strategy or v1.0 M1/M2/M3 thresholds.

**Architecture:** Extend existing `momentum_*` modules in-place — no new modules. EMA9/21/65 computation lives in a shared helper (`momentum_data.compute_ema_fields`) called by both `fetch_market_data.py` (global) and `momentum_scanner._fetch_indicators` (in-memory) so calculation has one source. Maturity is a 3-state categorical orthogonal to Tier. EM is a single tier evaluated on Full IWB / KR_BASE universe (sector filter bypass) when M+ is None. History migrates schema_version 1 → 2 in-place; legacy `EARLY`/`EXTENDED` risk tags are filtered on read.

**Tech Stack:** Python 3.10+, pandas, yfinance, pytest, Jinja2.

**Spec:** [docs/superpowers/specs/2026-05-09-emerging-momentum-maturity-design.md](../specs/2026-05-09-emerging-momentum-maturity-design.md)

---

## File Structure

| File | Role | Change |
|---|---|---|
| `momentum_config.py` | Threshold constants | Add Maturity/EM consts, RANK[EM]=0, legacy tag set, schema 2 |
| `momentum_data.py` | Data layer + EMA helper | Add `compute_ema_fields(close_series)` shared helper |
| `fetch_market_data.py` | Global market data | Call shared helper, add 7 EMA fields to per-ticker dict |
| `momentum_scanner.py` | Orchestration | Call shared helper in `_fetch_indicators`; Full-IWB EM scan; sector annotation; rotation radar |
| `momentum_signal.py` | Signal logic | `classify_maturity`, `classify_em`, `classify_tier`; Risk Tag cleanup; new `position_hint` 2-axis |
| `momentum_history.py` | History I/O | RANK[EM]=0; `maturity`/`sector_top_rank`/`dist_ema9_pct`/`ret_20d_pct` in entry; schema v2; legacy tag filter |
| `momentum_backtest.py` | Backtest aggregation | EM in by_stage; `transition_to_M1_pct` KPI |
| `templates/base_momentum.html` | Report UI | Two sections (Leaders/Emerging); Sector Rotation Radar block; new columns (Tier, Maturity, Streak, dist_ema9); drop Change/Price |
| `templates/detail_template.html` | Per-ticker page | Maturity line in CURRENT STATUS block |
| `telegram_sender.py` | Brief message | EM count + Rotation Radar lines |
| `tests/test_momentum_signal.py` | Existing | Augment with maturity/EM/tier tests |
| `tests/test_momentum_history.py` | Existing | Augment with EM RANK + schema v2 tests |
| `tests/test_momentum_backtest.py` | Existing | Augment with EM by_stage + transition tests |
| `tests/test_emerging_momentum_golden.py` | New | Golden regression fixture |
| `tests/test_e2e_emerging_smoke.py` | New | E2E smoke (`MODE=momentum_only`, mocked yfinance) |
| `CLAUDE.md` | Plan registration | Add bullet under "진행 중인 계획" |

**Total**: 10 source files modified, 0 new modules, 6 test files (2 new, 4 augmented), 1 doc file updated.

---

## Conventions

- **Run tests** from repo root with `python -m pytest tests/<file>.py::<test> -v`
- **Test imports** use `sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))` (existing pattern in `tests/test_momentum_signal.py:2-3`)
- **Commit messages** follow project pattern: `<type>(<scope>): <description>` then trailer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` via HEREDOC
- **No emojis in code/comments** unless already present (matches CLAUDE.md "Avoid writing emojis")
- **Windows console**: existing modules already do `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` — maintain pattern

---

## Task 1: momentum_config.py — Add Maturity/EM constants + RANK extension

**Files:**
- Modify: `momentum_config.py`
- Test: `tests/test_momentum_config.py`

- [ ] **Step 1: Write failing test for new constants**

Append to `tests/test_momentum_config.py`:
```python
def test_maturity_constants_present():
    import momentum_config as cfg
    assert cfg.MATURITY_EXT_DIST_PCT == 8.0
    assert cfg.MATURITY_EXT_RSI == 75.0
    assert cfg.MATURITY_EARLY_DIST_PCT == 3.0
    assert cfg.MATURITY_EARLY_RSI == 68.0


def test_em_constants_present():
    import momentum_config as cfg
    assert cfg.EM_RET_5D_MIN_PCT == 4.0
    assert cfg.EM_RET_20D_MIN_PCT == 10.0
    assert cfg.EM_RSI_MAX == 72.0
    assert cfg.EM_DIST_EMA9_MAX == 8.0
    assert cfg.EM_VOL_RATIO_MIN == 1.05
    assert cfg.EM_EMA21_SLOPE_MIN_PCT == 0.0


def test_legacy_risk_tags_set():
    import momentum_config as cfg
    assert cfg.LEGACY_RISK_TAGS == frozenset({"EARLY", "EXTENDED"})


def test_risk_priority_only_two_tags():
    import momentum_config as cfg
    assert cfg.RISK_PRIORITY == ["OVERHEAT", "PARABOLIC"]


def test_history_schema_version_v2():
    import momentum_config as cfg
    assert cfg.HISTORY_SCHEMA_VERSION == 2


def test_version_string_v15():
    import momentum_config as cfg
    assert cfg.VERSION == "Momentum v1.5"
```

- [ ] **Step 2: Run tests to verify failure**

```bash
python -m pytest tests/test_momentum_config.py -v
```
Expected: 6 new tests FAIL (AttributeError on missing attrs).

- [ ] **Step 3: Update `momentum_config.py`**

Replace content of `momentum_config.py` with:
```python
"""
Market Momentum Scanner — 임계값 상수 단일 진입점.

모든 RSI/비율/TTL/필터값은 여기서만 정의. 추후 튜닝 시 한 곳에서만 변경.
"""

VERSION = "Momentum v1.5"
HISTORY_SCHEMA_VERSION = 2

# ── Sector momentum ─────────────────────────────────────
SECTOR_RSI_MIN = 55
SECTOR_5D_MIN_PCT = 3.0
SECTOR_HIGH_52W_RATIO = 0.95
SECTOR_HIGH_20D_USE = True
SECTOR_VOLUME_RATIO_MIN = 1.2
SECTOR_RS_SCALE = 5
SECTOR_TOP_N = 3

# ── Pre-filter (Top-sector 종목 게이트, M+ 평가용) ───────
PREFILTER_3D_MIN_PCT = 4.0
PREFILTER_RSI_MIN = 55

# ── M1/M2/M3 thresholds (v1.0 unchanged) ────────────────
M1_3D_MIN_PCT = 8.0
M1_RSI_MIN = 60
M2_VOLUME_RATIO_MIN = 1.2
M3_HIGH_52W_RATIO = 0.99
M3_RSI_MIN = 65

# ── Maturity classifier (v1.5 신규) ─────────────────────
MATURITY_EXT_DIST_PCT = 8.0     # dist_ema9_pct ≥ 8% → EXTENDED
MATURITY_EXT_RSI = 75.0         # rsi14 ≥ 75 → EXTENDED
MATURITY_EARLY_DIST_PCT = 3.0   # dist_ema9_pct < 3% (AND ...) → EARLY
MATURITY_EARLY_RSI = 68.0       # rsi14 < 68 (AND ...) → EARLY

# ── Emerging Momentum (EM) tier (v1.5 신규) ─────────────
EM_RET_5D_MIN_PCT = 4.0
EM_RET_20D_MIN_PCT = 10.0
EM_RSI_MAX = 72.0
EM_DIST_EMA9_MAX = 8.0
EM_VOL_RATIO_MIN = 1.05
EM_EMA21_SLOPE_MIN_PCT = 0.0    # rising = positive slope

# ── Risk tags (v1.5 정리: EARLY/EXTENDED 삭제) ──────────
RISK_OVERHEAT_RSI = 80
RISK_PARABOLIC_PCT = 8.0
LEGACY_RISK_TAGS = frozenset({"EARLY", "EXTENDED"})  # filtered on history read

# ── Position hint (Maturity + Risk 2-axis) ──────────────
POSITION_HINT = {
    None:           "적극",
    "OVERHEAT":     "신중",
    "PARABOLIC":    "눌림",
    "MAT_EXTENDED": "분할",
    "MAT_EARLY":    "관찰",
    # legacy keys for history read compatibility (never written)
    "EARLY":        "관찰",
    "EXTENDED":     "분할",
}
RISK_PRIORITY = ["OVERHEAT", "PARABOLIC"]

# ── Universe / Daily movers ────────────────────────────
CACHE_TTL_DAYS = 7
KR_LIQUIDITY_MIN_KRW = 10_000_000_000
DAILY_MOVER_1D_PCT = 5.0
DAILY_MOVER_3D_PCT = 8.0

# ── Backtest ──────────────────────────────────────────
BACKTEST_WINDOW_DAYS = 90
CONSECUTIVE_LOSS_THRESHOLD = 4
LEG_RETURN_HORIZONS_DAYS = (3, 5, 10)

# ── ETF 매핑 ──────────────────────────────────────────
US_SECTOR_ETFS = [
    "XLK", "XLF", "XLE", "XLV", "XLI",
    "XLY", "XLP", "XLU", "XLRE", "XLB", "XLC",
]
KR_SECTOR_ETFS = [
    "091160.KS", "091170.KS", "117460.KS", "261240.KS",
    "091180.KS", "229200.KS", "069500.KS",
]
US_MARKET_BENCHMARKS = ["SPY", "QQQ"]
KR_MARKET_BENCHMARKS = ["^KS11", "^KQ11"]
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/test_momentum_config.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add momentum_config.py tests/test_momentum_config.py
git commit -m "$(cat <<'EOF'
feat(momentum): add v1.5 config constants — Maturity, EM, RANK extension

- VERSION 1.0 → 1.5, HISTORY_SCHEMA_VERSION 1 → 2
- Maturity thresholds (EXTENDED/EARLY)
- EM tier thresholds (5d/20d, RSI, dist_ema9, vol_ratio, slope)
- LEGACY_RISK_TAGS for history read compat
- RISK_PRIORITY 4 → 2 (OVERHEAT/PARABOLIC only)
- POSITION_HINT 2-axis keys (MAT_EXTENDED/MAT_EARLY)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: momentum_data.py — Add `compute_ema_fields` shared helper

**Files:**
- Modify: `momentum_data.py` (add new function + export)
- Test: `tests/test_momentum_data.py`

- [ ] **Step 1: Write failing tests for the helper**

Append to `tests/test_momentum_data.py`:
```python
def test_compute_ema_fields_basic():
    import pandas as pd
    import momentum_data as md
    # 90 day rising series — all EMAs should rise
    close = pd.Series([100 + i * 0.3 for i in range(90)])
    out = md.compute_ema_fields(close)
    assert out["ema9"] is not None
    assert out["ema21"] is not None
    assert out["ema65"] is not None
    assert out["dist_ema9_pct"] is not None
    assert out["dist_ema21_pct"] is not None
    assert out["ema21_slope_3d_pct"] is not None
    assert out["ema65_slope_5d_pct"] is not None
    assert out["ema21_slope_3d_pct"] > 0  # rising
    assert out["ema65_slope_5d_pct"] > 0  # rising


def test_compute_ema_fields_short_series():
    """series < 65 — ema65 should be None, ema9/21 may compute."""
    import pandas as pd
    import momentum_data as md
    close = pd.Series([100 + i for i in range(40)])
    out = md.compute_ema_fields(close)
    assert out["ema9"] is not None
    assert out["ema21"] is not None
    assert out["ema65"] is None
    assert out["ema65_slope_5d_pct"] is None


def test_compute_ema_fields_too_short():
    """series < 9 — all None."""
    import pandas as pd
    import momentum_data as md
    close = pd.Series([100, 101, 102, 103, 104])
    out = md.compute_ema_fields(close)
    assert out["ema9"] is None
    assert out["ema21"] is None
    assert out["ema65"] is None
    assert out["dist_ema9_pct"] is None


def test_compute_ema_fields_handles_nan_in_tail():
    """trailing NaN — utility returns None gracefully."""
    import pandas as pd
    import numpy as np
    import momentum_data as md
    close = pd.Series([100 + i * 0.5 for i in range(80)] + [np.nan, np.nan])
    out = md.compute_ema_fields(close)
    # ema computed on dropna in caller; helper expects clean input.
    # This test documents that helper handles NaN-containing series gracefully:
    # any None-yielding output should be None (no exception).
    # No assertion on specific value, just no exception.
    assert isinstance(out, dict)


def test_compute_ema_fields_zero_division_guard():
    """ema base = 0 → dist None, no exception."""
    import pandas as pd
    import momentum_data as md
    close = pd.Series([0.0] * 70)
    out = md.compute_ema_fields(close)
    # ema9 = 0 → dist_ema9_pct should be None (zero division guard)
    assert out["dist_ema9_pct"] is None
```

- [ ] **Step 2: Run tests to verify failure**

```bash
python -m pytest tests/test_momentum_data.py::test_compute_ema_fields_basic tests/test_momentum_data.py::test_compute_ema_fields_short_series tests/test_momentum_data.py::test_compute_ema_fields_too_short tests/test_momentum_data.py::test_compute_ema_fields_handles_nan_in_tail tests/test_momentum_data.py::test_compute_ema_fields_zero_division_guard -v
```
Expected: 5 tests FAIL with AttributeError on `compute_ema_fields`.

- [ ] **Step 3: Add helper to `momentum_data.py`**

Append to `momentum_data.py` (top-level function, after existing functions):
```python
def compute_ema_fields(close: "pd.Series") -> dict:
    """
    Compute EMA9/21/65 + dist + slope fields from a close series.

    Single source of truth for EMA calculation. Called by both
    fetch_market_data.py (per-ticker) and momentum_scanner._fetch_indicators
    (in-memory bulk). momentum_signal.py must NOT compute EMAs.

    Returns dict with 7 keys; each value is float or None.
    """
    import pandas as pd

    out = {
        "ema9": None, "ema21": None, "ema65": None,
        "dist_ema9_pct": None, "dist_ema21_pct": None,
        "ema21_slope_3d_pct": None, "ema65_slope_5d_pct": None,
    }
    if close is None or len(close) == 0:
        return out
    s = close.dropna() if hasattr(close, "dropna") else pd.Series(close).dropna()
    if len(s) < 9:
        return out

    last = float(s.iloc[-1])

    def _last_or_none(series):
        try:
            v = float(series.iloc[-1])
            return v if v == v else None
        except (TypeError, ValueError, IndexError):
            return None

    def _slope_pct(series, lookback):
        if len(series) <= lookback:
            return None
        try:
            cur = float(series.iloc[-1])
            prev = float(series.iloc[-1 - lookback])
        except (TypeError, ValueError, IndexError):
            return None
        if cur != cur or prev != prev or prev == 0:
            return None
        return round((cur - prev) / prev * 100, 2)

    def _dist_pct(close_v, ema_v):
        if ema_v is None or ema_v == 0:
            return None
        return round((close_v - ema_v) / ema_v * 100, 2)

    if len(s) >= 9:
        ema9 = s.ewm(span=9, adjust=False).mean()
        out["ema9"] = _last_or_none(ema9)
        out["dist_ema9_pct"] = _dist_pct(last, out["ema9"])

    if len(s) >= 21:
        ema21 = s.ewm(span=21, adjust=False).mean()
        out["ema21"] = _last_or_none(ema21)
        out["dist_ema21_pct"] = _dist_pct(last, out["ema21"])
        out["ema21_slope_3d_pct"] = _slope_pct(ema21, 3)

    if len(s) >= 65:
        ema65 = s.ewm(span=65, adjust=False).mean()
        out["ema65"] = _last_or_none(ema65)
        out["ema65_slope_5d_pct"] = _slope_pct(ema65, 5)

    return out
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/test_momentum_data.py -v -k compute_ema_fields
```
Expected: all 5 new tests PASS, existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add momentum_data.py tests/test_momentum_data.py
git commit -m "$(cat <<'EOF'
feat(momentum): add compute_ema_fields shared helper for EMA9/21/65

- Single source of truth for EMA calculation
- Used by both fetch_market_data.py and momentum_scanner._fetch_indicators
- Returns 7 fields: ema9/21/65, dist_ema9/21_pct, ema21_slope_3d, ema65_slope_5d
- All None on insufficient series length, with zero-division guards

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: fetch_market_data.py — Wire EMA fields globally

**Files:**
- Modify: `fetch_market_data.py:~414` (per-ticker indicator block)
- Test: `tests/test_momentum_change_fields.py` (existing — augment)

- [ ] **Step 1: Locate insertion point**

Read `fetch_market_data.py` around line 414-502 (per-ticker dict assembly). The block computes `ma20`, `ma50`, `ma200`, then assembles `ticker_data.update({...})` with all per-ticker keys.

- [ ] **Step 2: Write failing test**

Append to `tests/test_momentum_change_fields.py`:
```python
def test_fetch_market_data_includes_ema_fields():
    """fetch_market_data dict has ema9/21/65 + dist + slope fields."""
    # Use a stub: synthesize a clean close series and call compute_ema_fields directly,
    # then verify fetch_market_data integrates the helper output into ticker_data.
    # Since fetch_market_data does live yfinance calls, integration check is via
    # symbol presence in source code.
    import re
    src = open("fetch_market_data.py", encoding="utf-8").read()
    assert "compute_ema_fields" in src, "fetch_market_data must call compute_ema_fields"
    # All 7 keys propagated into ticker_data
    for key in ("ema9", "ema21", "ema65",
                "dist_ema9_pct", "dist_ema21_pct",
                "ema21_slope_3d_pct", "ema65_slope_5d_pct"):
        assert f'"{key}"' in src, f"missing {key} in fetch_market_data.py"
```

- [ ] **Step 3: Run test to verify failure**

```bash
python -m pytest tests/test_momentum_change_fields.py::test_fetch_market_data_includes_ema_fields -v
```
Expected: FAIL.

- [ ] **Step 4: Modify `fetch_market_data.py`**

Locate the existing block that computes `ma20/ma50/ma200` and adds them to `ticker_data` (around line 414+ based on prior grep). Add EMA computation immediately after the MA block, then propagate fields.

Find the existing block (anchor: `ma20  = close.rolling(20).mean()`) and add **immediately after** the line `vol_ma20 = volume.rolling(20).mean()`:

```python
        # EMA fields (Momentum v1.5 — global)
        from momentum_data import compute_ema_fields
        ema_fields = compute_ema_fields(close)
```

Then in the `ticker_data.update({...})` block (anchor: `"ma20":              safe(ma20),`) add **at the end of the dict** (before the closing brace):
```python
            "ema9":               ema_fields["ema9"],
            "ema21":              ema_fields["ema21"],
            "ema65":              ema_fields["ema65"],
            "dist_ema9_pct":      ema_fields["dist_ema9_pct"],
            "dist_ema21_pct":     ema_fields["dist_ema21_pct"],
            "ema21_slope_3d_pct": ema_fields["ema21_slope_3d_pct"],
            "ema65_slope_5d_pct": ema_fields["ema65_slope_5d_pct"],
```

- [ ] **Step 5: Run test to verify pass**

```bash
python -m pytest tests/test_momentum_change_fields.py -v
```
Expected: all PASS.

- [ ] **Step 6: Verify no regression in other tests**

```bash
python -m pytest tests/ -v --ignore=tests/test_e2e_momentum_smoke.py -x
```
Expected: green (or only previously-known failures unrelated to EMA).

- [ ] **Step 7: Commit**

```bash
git add fetch_market_data.py tests/test_momentum_change_fields.py
git commit -m "$(cat <<'EOF'
feat(market-data): propagate EMA9/21/65 fields globally

fetch_market_data.py now calls momentum_data.compute_ema_fields per ticker
and adds 7 EMA-derived keys to ticker_data. Backwards-compatible (existing
keys unchanged); new keys are optional None-safe.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: momentum_scanner._fetch_indicators — Use shared EMA helper

**Files:**
- Modify: `momentum_scanner.py:67-142` (`_fetch_indicators` function)
- Test: `tests/test_momentum_scanner.py` (existing)

- [ ] **Step 1: Write failing test**

Append to `tests/test_momentum_scanner.py`:
```python
def test_fetch_indicators_includes_ema_fields(monkeypatch):
    """_fetch_indicators output dict has all EMA fields."""
    import pandas as pd
    import momentum_scanner as msc
    import momentum_data as md

    n = 90
    closes = pd.DataFrame({"AAA": [100 + i * 0.5 for i in range(n)]})
    volumes = pd.DataFrame({"AAA": [1_000_000] * n})

    def _fake_bulk(tickers, period="90d"):
        return closes, volumes
    monkeypatch.setattr(md, "fetch_yf_bulk", _fake_bulk)

    result = msc._fetch_indicators(["AAA"])
    assert "AAA" in result
    for key in ("ema9", "ema21", "ema65",
                "dist_ema9_pct", "dist_ema21_pct",
                "ema21_slope_3d_pct", "ema65_slope_5d_pct"):
        assert key in result["AAA"], f"missing {key}"
        assert result["AAA"][key] is not None  # 90 day series has all
```

- [ ] **Step 2: Run test to verify failure**

```bash
python -m pytest tests/test_momentum_scanner.py::test_fetch_indicators_includes_ema_fields -v
```
Expected: FAIL (KeyError).

- [ ] **Step 3: Modify `_fetch_indicators` in `momentum_scanner.py`**

Inside the `for t in closes.columns:` loop in `_fetch_indicators` (line ~91-141), after computing all existing indicators, before the `out[t] = {...}` dict construction, add:

```python
        ema_fields = md.compute_ema_fields(s)
```

Then in the `out[t] = {...}` dict (line ~131-141), append the 7 EMA keys at the end (before closing brace):
```python
            "ema9": ema_fields["ema9"],
            "ema21": ema_fields["ema21"],
            "ema65": ema_fields["ema65"],
            "dist_ema9_pct": ema_fields["dist_ema9_pct"],
            "dist_ema21_pct": ema_fields["dist_ema21_pct"],
            "ema21_slope_3d_pct": ema_fields["ema21_slope_3d_pct"],
            "ema65_slope_5d_pct": ema_fields["ema65_slope_5d_pct"],
```

- [ ] **Step 4: Run test to verify pass**

```bash
python -m pytest tests/test_momentum_scanner.py::test_fetch_indicators_includes_ema_fields -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add momentum_scanner.py tests/test_momentum_scanner.py
git commit -m "$(cat <<'EOF'
feat(momentum): wire EMA fields into _fetch_indicators via shared helper

momentum_scanner._fetch_indicators now uses momentum_data.compute_ema_fields,
matching the global path in fetch_market_data.py. No duplicated EMA math.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: momentum_signal.classify_maturity

**Files:**
- Modify: `momentum_signal.py` (add new function near `compute_risk_tags`)
- Test: `tests/test_momentum_signal.py`

- [ ] **Step 1: Write failing tests for boundary cases**

Append to `tests/test_momentum_signal.py`:
```python
def _stock_basic(dist_ema9=4.0, rsi=65, ema9=110, ema21=108):
    return {
        "ticker": "TEST",
        "dist_ema9_pct": dist_ema9, "rsi14": rsi,
        "ema9": ema9, "ema21": ema21,
    }


# EXTENDED — dist OR rsi
def test_maturity_extended_by_dist():
    s = _stock_basic(dist_ema9=8.0, rsi=60)  # at boundary
    assert ms.classify_maturity(s) == "EXTENDED"


def test_maturity_not_extended_just_below_dist():
    s = _stock_basic(dist_ema9=7.99, rsi=60)
    assert ms.classify_maturity(s) != "EXTENDED"


def test_maturity_extended_by_rsi():
    s = _stock_basic(dist_ema9=4.0, rsi=75.0)  # at boundary
    assert ms.classify_maturity(s) == "EXTENDED"


def test_maturity_not_extended_just_below_rsi():
    s = _stock_basic(dist_ema9=4.0, rsi=74.99)
    assert ms.classify_maturity(s) != "EXTENDED"


# EARLY — dist AND rsi AND ema9>ema21
def test_maturity_early_all_three_satisfied():
    s = _stock_basic(dist_ema9=2.0, rsi=64, ema9=110, ema21=108)
    assert ms.classify_maturity(s) == "EARLY"


def test_maturity_not_early_dist_at_boundary():
    s = _stock_basic(dist_ema9=3.0, rsi=64, ema9=110, ema21=108)  # < 3 strict
    assert ms.classify_maturity(s) != "EARLY"


def test_maturity_not_early_rsi_at_boundary():
    s = _stock_basic(dist_ema9=2.0, rsi=68.0, ema9=110, ema21=108)  # < 68 strict
    assert ms.classify_maturity(s) != "EARLY"


def test_maturity_not_early_when_ema9_below_ema21():
    s = _stock_basic(dist_ema9=2.0, rsi=64, ema9=108, ema21=110)
    assert ms.classify_maturity(s) != "EARLY"


# MID — fallback
def test_maturity_mid_fallback():
    s = _stock_basic(dist_ema9=5.0, rsi=70, ema9=110, ema21=108)
    assert ms.classify_maturity(s) == "MID"


def test_maturity_mid_when_ema9_below_ema21_but_not_extended():
    s = _stock_basic(dist_ema9=2.0, rsi=64, ema9=108, ema21=110)
    assert ms.classify_maturity(s) == "MID"


def test_maturity_none_when_required_fields_missing():
    s = {"ticker": "TEST", "rsi14": 65}  # no dist_ema9_pct
    assert ms.classify_maturity(s) is None


def test_maturity_extended_takes_precedence_over_early():
    """if both EXTENDED conditions true, EXTENDED wins (eval order)."""
    s = _stock_basic(dist_ema9=8.0, rsi=64, ema9=110, ema21=108)
    assert ms.classify_maturity(s) == "EXTENDED"
```

- [ ] **Step 2: Run tests to verify failure**

```bash
python -m pytest tests/test_momentum_signal.py -v -k maturity
```
Expected: 12 tests FAIL (AttributeError on `classify_maturity`).

- [ ] **Step 3: Add `classify_maturity` to `momentum_signal.py`**

Insert after `compute_risk_tags` function:
```python
def classify_maturity(stock_data: dict) -> str | None:
    """
    Maturity 분류 — EARLY / MID / EXTENDED 중 하나, 또는 None.

    EXTENDED 우선:  dist_ema9_pct >= 8% OR rsi14 >= 75
    EARLY:          dist_ema9_pct < 3% AND rsi14 < 68 AND ema9 > ema21
    MID:            그 외 (둘 다 아닌 경우)

    Returns None if dist_ema9_pct or rsi14 missing.
    """
    dist = _safe_float(stock_data.get("dist_ema9_pct"))
    rsi = _safe_float(stock_data.get("rsi14"))
    if dist is None or rsi is None:
        return None

    # EXTENDED first
    if dist >= cfg.MATURITY_EXT_DIST_PCT or rsi >= cfg.MATURITY_EXT_RSI:
        return "EXTENDED"

    # EARLY: all three required
    ema9 = _safe_float(stock_data.get("ema9"))
    ema21 = _safe_float(stock_data.get("ema21"))
    if (dist < cfg.MATURITY_EARLY_DIST_PCT
            and rsi < cfg.MATURITY_EARLY_RSI
            and ema9 is not None and ema21 is not None
            and ema9 > ema21):
        return "EARLY"

    return "MID"
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/test_momentum_signal.py -v -k maturity
```
Expected: all 12 PASS.

- [ ] **Step 5: Commit**

```bash
git add momentum_signal.py tests/test_momentum_signal.py
git commit -m "$(cat <<'EOF'
feat(momentum): add classify_maturity (EARLY/MID/EXTENDED)

Orthogonal to Tier — EMA9 distance + RSI 2-axis classifier.
- EXTENDED first: dist_ema9 >= 8% OR RSI >= 75
- EARLY: dist_ema9 < 3% AND RSI < 68 AND ema9 > ema21
- MID: fallback
- None when dist_ema9_pct or rsi14 missing

12 boundary tests covering eval order, missing fields, EARLY structure check.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: momentum_signal.classify_em + classify_tier

**Files:**
- Modify: `momentum_signal.py` (add 2 functions)
- Test: `tests/test_momentum_signal.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_momentum_signal.py`:
```python
def _stock_em_pass(**overrides):
    """Build a stock dict that passes all EM gates by default."""
    base = {
        "ticker": "EM_OK",
        # Structure
        "ema9": 110.0, "ema21": 108.0, "ema65": 105.0,
        "ema21_slope_3d_pct": 0.5,
        "close": 111.0,
        # Momentum
        "ret_5d_pct": 5.0, "ret_20d_pct": 12.0,
        # Anti-overheat
        "rsi14": 65.0, "dist_ema9_pct": 0.9,
        # Participation
        "volume_ratio": 1.10,
    }
    base.update(overrides)
    return base


def test_classify_em_passes_all_gates():
    assert ms.classify_em(_stock_em_pass()) is True


def test_classify_em_fails_when_ema9_not_above_ema21():
    s = _stock_em_pass(ema9=107.0, ema21=108.0)
    assert ms.classify_em(s) is False


def test_classify_em_fails_when_ema21_not_above_ema65():
    s = _stock_em_pass(ema21=104.0, ema65=105.0)
    assert ms.classify_em(s) is False


def test_classify_em_fails_when_ema21_not_rising():
    s = _stock_em_pass(ema21_slope_3d_pct=-0.1)
    assert ms.classify_em(s) is False


def test_classify_em_fails_when_close_below_ema21():
    s = _stock_em_pass(close=107.0, ema21=108.0)
    assert ms.classify_em(s) is False


def test_classify_em_passes_with_5d_only():
    """5d>=4% OR 20d>=10% — 5d alone is enough."""
    s = _stock_em_pass(ret_5d_pct=4.0, ret_20d_pct=2.0)
    assert ms.classify_em(s) is True


def test_classify_em_passes_with_20d_only():
    s = _stock_em_pass(ret_5d_pct=1.0, ret_20d_pct=10.0)
    assert ms.classify_em(s) is True


def test_classify_em_fails_when_neither_momentum_threshold_met():
    s = _stock_em_pass(ret_5d_pct=2.0, ret_20d_pct=8.0)
    assert ms.classify_em(s) is False


def test_classify_em_fails_overheated_rsi():
    s = _stock_em_pass(rsi14=72.0)  # >= 72
    assert ms.classify_em(s) is False


def test_classify_em_fails_overheated_dist():
    s = _stock_em_pass(dist_ema9_pct=8.0)  # >= 8
    assert ms.classify_em(s) is False


def test_classify_em_fails_low_volume():
    s = _stock_em_pass(volume_ratio=1.04)
    assert ms.classify_em(s) is False


def test_classify_em_returns_false_on_missing_fields():
    """missing ema9 → cannot evaluate → False."""
    s = _stock_em_pass()
    s.pop("ema9")
    assert ms.classify_em(s) is False


# classify_tier — M+ priority over EM
def test_classify_tier_returns_m1_when_both_qualify():
    """Stock satisfies both M1 (3d=9, RSI=65) and EM. Tier should be MOMENTUM_1."""
    s = _stock_em_pass()
    s.update({
        "ret_3d_pct": 9.0, "ma20": 100.0, "ma50": 99.0,
        "macd_hist_trend": "rising", "high_52w": 120.0,
    })
    assert ms.classify_tier(s) == "MOMENTUM_1"


def test_classify_tier_returns_em_when_only_em_qualifies():
    """3d=2% (under M1) but EM passes → tier=EM."""
    s = _stock_em_pass()
    s.update({"ret_3d_pct": 2.0, "ma20": 100.0})
    assert ms.classify_tier(s) == "EM"


def test_classify_tier_returns_none_when_neither_qualifies():
    s = {"ticker": "X", "ret_3d_pct": 2.0, "rsi14": 50.0,
         "close": 100.0, "ma20": 105.0}
    assert ms.classify_tier(s) is None
```

- [ ] **Step 2: Run tests to verify failure**

```bash
python -m pytest tests/test_momentum_signal.py -v -k "classify_em or classify_tier"
```
Expected: FAIL (AttributeError on both).

- [ ] **Step 3: Add `classify_em` and `classify_tier` to `momentum_signal.py`**

Insert after `classify_maturity`:
```python
def classify_em(stock_data: dict) -> bool:
    """
    Emerging Momentum (EM) tier 검사 — Structural Inflection Discovery.

    Returns True if all gates pass:
      Structure: ema9 > ema21 > ema65 AND ema21_slope_3d > 0 AND close > ema21
      Momentum:  ret_5d >= 4% OR ret_20d >= 10%
      Anti-overheat: rsi14 < 72 AND dist_ema9 < 8%
      Participation: volume_ratio >= 1.05
    """
    ema9 = _safe_float(stock_data.get("ema9"))
    ema21 = _safe_float(stock_data.get("ema21"))
    ema65 = _safe_float(stock_data.get("ema65"))
    slope = _safe_float(stock_data.get("ema21_slope_3d_pct"))
    close = _safe_float(stock_data.get("close"))
    if (ema9 is None or ema21 is None or ema65 is None
            or slope is None or close is None):
        return False
    if not (ema9 > ema21 > ema65):
        return False
    if slope <= cfg.EM_EMA21_SLOPE_MIN_PCT:
        return False
    if close <= ema21:
        return False

    r5 = _safe_float(stock_data.get("ret_5d_pct"))
    r20 = _safe_float(stock_data.get("ret_20d_pct"))
    has_5d = r5 is not None and r5 >= cfg.EM_RET_5D_MIN_PCT
    has_20d = r20 is not None and r20 >= cfg.EM_RET_20D_MIN_PCT
    if not (has_5d or has_20d):
        return False

    rsi = _safe_float(stock_data.get("rsi14"))
    dist = _safe_float(stock_data.get("dist_ema9_pct"))
    if rsi is None or dist is None:
        return False
    if rsi >= cfg.EM_RSI_MAX or dist >= cfg.EM_DIST_EMA9_MAX:
        return False

    vr = _safe_float(stock_data.get("volume_ratio"))
    if vr is None or vr < cfg.EM_VOL_RATIO_MIN:
        return False

    return True


def classify_tier(stock_data: dict) -> str | None:
    """
    Single tier label resolution.

    Priority: M3 > M2 > M1 > EM > None.
    M+ wins when both M+ and EM would qualify (strength label single).
    """
    stage = classify_stage(stock_data)
    if stage is not None:
        return stage
    if classify_em(stock_data):
        return "EM"
    return None
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/test_momentum_signal.py -v -k "classify_em or classify_tier"
```
Expected: all 15 PASS.

- [ ] **Step 5: Commit**

```bash
git add momentum_signal.py tests/test_momentum_signal.py
git commit -m "$(cat <<'EOF'
feat(momentum): add classify_em + classify_tier (M+ over EM precedence)

- classify_em: structural inflection discovery on Full IWB
  - ema9>ema21>ema65 + slope>0 + close>ema21
  - ret_5d>=4% OR ret_20d>=10%
  - RSI<72 AND dist_ema9<8%
  - volume_ratio>=1.05
- classify_tier: single label, M+ over EM
- 15 tests cover all gates + missing fields + precedence

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: momentum_signal Risk Tag cleanup + position_hint refactor

**Files:**
- Modify: `momentum_signal.py` (`compute_risk_tags`, `position_hint`, `evaluate_stock`)
- Test: `tests/test_momentum_signal.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_momentum_signal.py`:
```python
def test_compute_risk_tags_only_overheat_and_parabolic():
    s = {"ticker": "T", "rsi14": 82.0, "change_pct": 9.0,
         "close": 120.0, "ma20": 100.0,
         "dist_ema9_pct": 12.0}  # would have been EXTENDED in v1.0
    tags = ms.compute_risk_tags(s, "MOMENTUM_1")
    assert "OVERHEAT" in tags
    assert "PARABOLIC" in tags
    assert "EXTENDED" not in tags  # removed in v1.5
    assert "EARLY" not in tags     # removed in v1.5


def test_compute_risk_tags_no_legacy_early_emitted():
    s = {"ticker": "T", "rsi14": 62.0, "change_pct": 1.0,
         "close": 100.0, "ma20": 99.0}
    tags = ms.compute_risk_tags(s, "MOMENTUM_1")
    assert "EARLY" not in tags  # legacy tag never emitted


def test_position_hint_overheat_priority():
    assert ms.position_hint(maturity="EARLY",
                             risk_tags=["OVERHEAT"]) == "신중"


def test_position_hint_parabolic_after_overheat():
    assert ms.position_hint(maturity="MID",
                             risk_tags=["PARABOLIC"]) == "눌림"


def test_position_hint_maturity_extended_when_no_risk():
    assert ms.position_hint(maturity="EXTENDED",
                             risk_tags=[]) == "분할"


def test_position_hint_maturity_early_when_no_risk():
    assert ms.position_hint(maturity="EARLY",
                             risk_tags=[]) == "관찰"


def test_position_hint_active_when_mid_no_risk():
    assert ms.position_hint(maturity="MID",
                             risk_tags=[]) == "적극"


def test_position_hint_none_maturity_no_risk():
    assert ms.position_hint(maturity=None,
                             risk_tags=[]) == "적극"


def test_filter_legacy_tags_removes_early_extended():
    assert ms.filter_legacy_tags(["EARLY", "OVERHEAT", "EXTENDED"]) == ["OVERHEAT"]


def test_filter_legacy_tags_passes_through_modern():
    assert ms.filter_legacy_tags(["OVERHEAT", "PARABOLIC"]) == ["OVERHEAT", "PARABOLIC"]
```

- [ ] **Step 2: Run tests to verify failure**

```bash
python -m pytest tests/test_momentum_signal.py -v -k "risk_tags or position_hint or filter_legacy"
```
Expected: most FAIL (positon_hint signature different, filter_legacy not exists, EARLY/EXTENDED still emitted).

- [ ] **Step 3: Modify `momentum_signal.py`**

Replace existing `compute_risk_tags` function with:
```python
def compute_risk_tags(stock_data: dict, stage: str | None = None) -> list[str]:
    """
    Risk tag — v1.5 정리: OVERHEAT, PARABOLIC만 emit.

    EXTENDED / EARLY는 Maturity 차원으로 이동 (compute_risk_tags 미발행).
    `stage` 인자는 backwards-compat 시그니처 — 새 로직에서는 미사용.
    """
    tags: list[str] = []
    rsi = _safe_float(stock_data.get("rsi14"))
    chg = _safe_float(stock_data.get("change_pct"))

    if rsi is not None and rsi >= cfg.RISK_OVERHEAT_RSI:
        tags.append("OVERHEAT")
    if chg is not None and chg >= cfg.RISK_PARABOLIC_PCT:
        tags.append("PARABOLIC")
    return tags
```

Replace existing `position_hint` function with:
```python
def position_hint(maturity: str | None = None,
                  risk_tags: list[str] | None = None) -> str:
    """
    Position hint — Maturity (위치) + Risk Tag (위험) 2-axis 결합.

    Priority:
      OVERHEAT > PARABOLIC > Maturity=EXTENDED > Maturity=EARLY > 적극(MID/없음)
    """
    risk_tags = risk_tags or []
    if "OVERHEAT" in risk_tags:
        return cfg.POSITION_HINT["OVERHEAT"]
    if "PARABOLIC" in risk_tags:
        return cfg.POSITION_HINT["PARABOLIC"]
    if maturity == "EXTENDED":
        return cfg.POSITION_HINT["MAT_EXTENDED"]
    if maturity == "EARLY":
        return cfg.POSITION_HINT["MAT_EARLY"]
    return cfg.POSITION_HINT[None]
```

Add a new helper function:
```python
def filter_legacy_tags(risk_tags: list[str]) -> list[str]:
    """Remove legacy EARLY/EXTENDED risk tags (now Maturity dimension)."""
    if not risk_tags:
        return []
    return [t for t in risk_tags if t not in cfg.LEGACY_RISK_TAGS]
```

Modify `evaluate_stock` to use new `position_hint(maturity, risk_tags)` and emit `maturity` field. Replace function body of `evaluate_stock`:
```python
def evaluate_stock(stock_data: dict, sector_5d_return: float | None = None,
                   sector_top_rank: int | None = None) -> dict | None:
    """
    Evaluate stock — Tier(M+/EM) + Maturity + Risk Tags.

    Returns:
      None — no signal (no tier qualifies)
      dict — {ticker, stage(=tier), maturity, risk_tags, hint, rs_vs_sector,
              sector, sector_top_rank, price, rsi, ret_*, dist_ema9_pct}
    """
    tier = classify_tier(stock_data)
    if tier is None:
        return None

    risk_tags = compute_risk_tags(stock_data, tier)
    maturity = classify_maturity(stock_data)
    hint = position_hint(maturity=maturity, risk_tags=risk_tags)

    rs_vs_sector = None
    stock_5d = _safe_float(stock_data.get("ret_5d_pct"))
    if stock_5d is not None and sector_5d_return is not None:
        rs_vs_sector = stock_5d > sector_5d_return

    return {
        "ticker": stock_data.get("ticker"),
        "stage": tier,                   # backwards-compat: history reads "stage"
        "tier": tier,
        "maturity": maturity,
        "risk_tags": risk_tags,
        "hint": hint,
        "rs_vs_sector": rs_vs_sector,
        "sector": stock_data.get("sector"),
        "sector_top_rank": sector_top_rank,
        "price": _safe_float(stock_data.get("close")),
        "rsi": _safe_float(stock_data.get("rsi14")),
        "ret_1d_pct": _safe_float(stock_data.get("change_pct")),
        "ret_3d_pct": _safe_float(stock_data.get("ret_3d_pct")),
        "ret_5d_pct": stock_5d,
        "ret_20d_pct": _safe_float(stock_data.get("ret_20d_pct")),
        "dist_ema9_pct": _safe_float(stock_data.get("dist_ema9_pct")),
    }
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/test_momentum_signal.py -v
```
Expected: all PASS (existing M-classifier tests still pass since classify_stage unchanged).

- [ ] **Step 5: Commit**

```bash
git add momentum_signal.py tests/test_momentum_signal.py
git commit -m "$(cat <<'EOF'
feat(momentum): clean up Risk Tags (drop EARLY/EXTENDED) + 2-axis position_hint

- compute_risk_tags emits only OVERHEAT/PARABOLIC; legacy tags absorbed by Maturity
- position_hint(maturity, risk_tags) — OVERHEAT > PARABOLIC > MAT_EXTENDED > MAT_EARLY > 적극
- filter_legacy_tags utility for history read compat
- evaluate_stock now returns tier/maturity/sector_top_rank/dist_ema9_pct fields

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: momentum_history.py — RANK[EM]=0 + maturity field + schema v2 + legacy filter

**Files:**
- Modify: `momentum_history.py`
- Test: `tests/test_momentum_history.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_momentum_history.py`:
```python
def test_rank_includes_em_at_zero():
    import momentum_history as mh
    assert mh.RANK["EM"] == 0
    assert mh.RANK["MOMENTUM_1"] == 1
    assert mh.RANK["MOMENTUM_2"] == 2
    assert mh.RANK["MOMENTUM_3"] == 3


def test_em_to_m1_is_upgrade():
    """EM → MOMENTUM_1 should be UPGRADE (RANK 0 < 1) with streak +1."""
    import momentum_history as mh
    history = {"data": {"PLTR": {
        "2026-05-09": {"stage": "EM", "streak": 3, "change": "HOLD",
                        "entry_price": 22.0, "entry_date": "2026-05-07",
                        "time_in_stage": 3, "price": 23.5},
    }}}
    today_signals = [{
        "ticker": "PLTR", "stage": "MOMENTUM_1", "price": 24.0,
        "maturity": "MID", "sector": "Software", "sector_top_rank": None,
        "rsi": 62.0, "ret_1d_pct": 1.5, "ret_3d_pct": 5.0,
        "ret_5d_pct": 7.0, "ret_20d_pct": 12.0, "dist_ema9_pct": 4.5,
        "rs_vs_sector": True, "risk_tags": [], "name": "Palantir",
    }]
    out = mh.update_history(history, today_signals, today="2026-05-10")
    entry = out["data"]["PLTR"]["2026-05-10"]
    assert entry["stage"] == "MOMENTUM_1"
    assert entry["change"] == "UPGRADE"
    assert entry["streak"] == 4
    assert entry["prev_stage"] == "EM"
    assert entry["maturity"] == "MID"
    assert entry["sector_top_rank"] is None
    assert entry["dist_ema9_pct"] == 4.5
    assert entry["ret_20d_pct"] == 12.0


def test_em_new_entry_includes_maturity_and_dist_ema9():
    import momentum_history as mh
    history = {"data": {}}
    today_signals = [{
        "ticker": "DUOL", "stage": "EM", "price": 180.0,
        "maturity": "EARLY", "sector": "Education", "sector_top_rank": None,
        "rsi": 64.0, "ret_1d_pct": 1.2, "ret_3d_pct": 2.0,
        "ret_5d_pct": 4.5, "ret_20d_pct": 11.0, "dist_ema9_pct": 1.8,
        "rs_vs_sector": None, "risk_tags": [], "name": "Duolingo",
    }]
    out = mh.update_history(history, today_signals, today="2026-05-09")
    entry = out["data"]["DUOL"]["2026-05-09"]
    assert entry["change"] == "NEW"
    assert entry["streak"] == 1
    assert entry["stage"] == "EM"
    assert entry["maturity"] == "EARLY"
    assert entry["dist_ema9_pct"] == 1.8
    assert entry["sector_top_rank"] is None


def test_load_history_filters_legacy_risk_tags_on_active_entries():
    """Existing v1.0 entries with EARLY/EXTENDED tags — filtered on read."""
    import json, tempfile, os, momentum_history as mh
    raw = {
        "_meta": {"scanner": "momentum_us", "schema_version": 1,
                  "version": "Momentum v1.0", "last_updated": "2026-05-08"},
        "data": {"NVDA": {"2026-05-08": {
            "stage": "MOMENTUM_3", "streak": 5, "change": "HOLD",
            "risk_tags": ["EXTENDED", "OVERHEAT", "EARLY"],
            "price": 920.0,
        }}},
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(raw, f)
        path = f.name
    try:
        out = mh.load_history(path)
        tags = out["data"]["NVDA"]["2026-05-08"]["risk_tags"]
        assert "EARLY" not in tags
        assert "EXTENDED" not in tags
        assert "OVERHEAT" in tags
    finally:
        os.unlink(path)


def test_save_history_writes_schema_version_2():
    import json, tempfile, os, momentum_history as mh
    history = {"_meta": {}, "data": {}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        path = f.name
    try:
        mh.save_history(path, history)
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["_meta"]["schema_version"] == 2
        assert saved["_meta"]["version"] == "Momentum v1.5"
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
python -m pytest tests/test_momentum_history.py -v -k "em or schema_version or legacy"
```
Expected: 5 tests FAIL.

- [ ] **Step 3: Modify `momentum_history.py`**

Replace `RANK = {...}` line with:
```python
RANK = {"EM": 0, "MOMENTUM_1": 1, "MOMENTUM_2": 2, "MOMENTUM_3": 3}
```

Modify `load_history` to filter legacy risk tags. After `return json.loads(raw)` line, do not return directly — wrap in a post-process. Replace the body of `load_history` with:
```python
def load_history(path: str, scanner_name: str = "momentum_us") -> dict:
    """JSON history 파일 로드. 없으면 skeleton. Legacy EARLY/EXTENDED risk tags filtered."""
    if not os.path.exists(path):
        return _empty_skeleton(scanner_name)
    try:
        with open(path, "rb") as f:
            raw = f.read().rstrip(b" \t\n\r\x00").decode("utf-8")
        history = json.loads(raw)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[momentum_history] WARN corrupt history {path}: {e}")
        return _empty_skeleton(scanner_name)

    # Legacy tag filter on active entries (read-time)
    legacy = cfg.LEGACY_RISK_TAGS
    for ticker, dates in history.get("data", {}).items():
        for d, entry in dates.items():
            tags = entry.get("risk_tags")
            if isinstance(tags, list) and any(t in legacy for t in tags):
                entry["risk_tags"] = [t for t in tags if t not in legacy]
    return history


def _empty_skeleton(scanner_name: str) -> dict:
    return {
        "_meta": {
            "scanner": scanner_name,
            "schema_version": cfg.HISTORY_SCHEMA_VERSION,
            "version": cfg.VERSION,
            "last_updated": None,
        },
        "data": {},
    }
```

Modify `save_history` to bump schema_version + version:
```python
def save_history(path: str, history: dict):
    history.setdefault("_meta", {})
    history["_meta"]["last_updated"] = datetime.now(
        timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    history["_meta"]["schema_version"] = cfg.HISTORY_SCHEMA_VERSION
    history["_meta"]["version"] = cfg.VERSION
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
```

In `update_history`, modify the `entry = {...}` dict to include new fields. Replace the entry construction (`entry = {"stage": new_stage, ...}`) with:
```python
        entry = {
            "stage": new_stage,
            "streak": streak,
            "prev_stage": prev_stage,
            "change": change,
            "maturity": sig.get("maturity"),
            "risk_tags": sig.get("risk_tags", []),
            "price": sig.get("price"),
            "rsi": sig.get("rsi"),
            "ret_1d_pct": sig.get("ret_1d_pct"),
            "ret_3d_pct": sig.get("ret_3d_pct"),
            "ret_5d_pct": sig.get("ret_5d_pct"),
            "ret_20d_pct": sig.get("ret_20d_pct"),
            "dist_ema9_pct": sig.get("dist_ema9_pct"),
            "name": sig.get("name"),
            "sector": sig.get("sector"),
            "sector_top_rank": sig.get("sector_top_rank"),
            "rs_vs_sector": sig.get("rs_vs_sector"),
            "entry_price": entry_price,
            "entry_date": entry_date,
            "time_in_stage": time_in_stage,
            "entry_context": {
                "sector": sig.get("sector"),
                "streak": streak,
                "maturity": sig.get("maturity"),
                "risk_tags": sig.get("risk_tags", []),
            },
        }
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/test_momentum_history.py -v
```
Expected: all PASS (existing tests still green — RANK lookup uses 0 fallback, EM transitions natural).

- [ ] **Step 5: Commit**

```bash
git add momentum_history.py tests/test_momentum_history.py
git commit -m "$(cat <<'EOF'
feat(momentum): history v2 — RANK[EM]=0, maturity field, legacy tag filter

- RANK adds EM at 0 (EM → MOMENTUM_1 = natural UPGRADE)
- Entry schema adds maturity, sector_top_rank, dist_ema9_pct, ret_20d_pct
- entry_context tracks maturity for backtest context
- load_history filters legacy EARLY/EXTENDED risk tags on read
- save_history stamps schema_version=2 and version='Momentum v1.5'
- Existing v1.0 history files load cleanly (filtered) — no migration script needed

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: momentum_backtest.py — by_stage EM + transition_to_M1_pct

**Files:**
- Modify: `momentum_backtest.py:161-end` (`aggregate` function)
- Test: `tests/test_momentum_backtest.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_momentum_backtest.py`:
```python
def test_aggregate_includes_em_in_by_stage():
    import momentum_backtest as mb
    legs = [
        {"ticker": "X", "stage": "EM", "ret_3d_pct": 1.0, "ret_5d_pct": 2.0,
         "ret_10d_pct": 4.0, "max_ret_pct": 5.0, "min_ret_pct": -1.0,
         "mdd_pct": -1.5, "duration_days": 5, "exit_reason": "UPGRADE"},
        {"ticker": "Y", "stage": "EM", "ret_3d_pct": -0.5, "ret_5d_pct": -1.0,
         "ret_10d_pct": 0.0, "max_ret_pct": 1.0, "min_ret_pct": -2.0,
         "mdd_pct": -2.5, "duration_days": 7, "exit_reason": "EXIT"},
    ]
    agg = mb.aggregate(legs, as_of="2026-05-09")
    assert "EM" in agg["by_stage"]
    em = agg["by_stage"]["EM"]
    assert em["leg_count"] == 2
    # win rate 5d: 1 of 2 positive (2.0 > 0)
    assert em["win_rate_5d_pct"] == 50.0


def test_em_transition_to_m1_pct_calculated():
    """transition_to_M1_pct = % of EM legs whose exit_reason == UPGRADE."""
    import momentum_backtest as mb
    legs = [
        {"ticker": "A", "stage": "EM", "exit_reason": "UPGRADE",
         "ret_5d_pct": 3.0, "ret_3d_pct": 1.0, "ret_10d_pct": None,
         "max_ret_pct": None, "min_ret_pct": None, "mdd_pct": None,
         "duration_days": 4},
        {"ticker": "B", "stage": "EM", "exit_reason": "UPGRADE",
         "ret_5d_pct": 5.0, "ret_3d_pct": 2.0, "ret_10d_pct": None,
         "max_ret_pct": None, "min_ret_pct": None, "mdd_pct": None,
         "duration_days": 5},
        {"ticker": "C", "stage": "EM", "exit_reason": "EXIT",
         "ret_5d_pct": -1.0, "ret_3d_pct": 0.0, "ret_10d_pct": None,
         "max_ret_pct": None, "min_ret_pct": None, "mdd_pct": None,
         "duration_days": 6},
        {"ticker": "D", "stage": "EM", "exit_reason": "DOWNGRADE",
         "ret_5d_pct": -2.0, "ret_3d_pct": -1.0, "ret_10d_pct": None,
         "max_ret_pct": None, "min_ret_pct": None, "mdd_pct": None,
         "duration_days": 7},
    ]
    agg = mb.aggregate(legs, as_of="2026-05-09")
    em = agg["by_stage"]["EM"]
    # 2 of 4 UPGRADE → 50.0%
    assert em["transition_to_M1_pct"] == 50.0


def test_transition_pct_excludes_in_progress_legs():
    """In-progress legs (exit_reason None) shouldn't count in denominator."""
    import momentum_backtest as mb
    legs = [
        {"ticker": "A", "stage": "EM", "exit_reason": "UPGRADE",
         "ret_5d_pct": 3.0, "ret_3d_pct": 1.0, "ret_10d_pct": None,
         "max_ret_pct": None, "min_ret_pct": None, "mdd_pct": None,
         "duration_days": 4},
        {"ticker": "B", "stage": "EM", "exit_reason": None,
         "ret_5d_pct": None, "ret_3d_pct": None, "ret_10d_pct": None,
         "max_ret_pct": None, "min_ret_pct": None, "mdd_pct": None,
         "duration_days": 1},
    ]
    agg = mb.aggregate(legs, as_of="2026-05-09")
    em = agg["by_stage"]["EM"]
    # Only 1 closed leg, 1 UPGRADE → 100.0%
    assert em["transition_to_M1_pct"] == 100.0


def test_transition_pct_none_when_no_closed_em_legs():
    import momentum_backtest as mb
    legs = [
        {"ticker": "A", "stage": "EM", "exit_reason": None,
         "ret_5d_pct": None, "ret_3d_pct": None, "ret_10d_pct": None,
         "max_ret_pct": None, "min_ret_pct": None, "mdd_pct": None,
         "duration_days": 1},
    ]
    agg = mb.aggregate(legs, as_of="2026-05-09")
    em = agg["by_stage"]["EM"]
    assert em["transition_to_M1_pct"] is None
```

- [ ] **Step 2: Run tests to verify failure**

```bash
python -m pytest tests/test_momentum_backtest.py -v -k "em or transition"
```
Expected: 4 tests FAIL.

- [ ] **Step 3: Modify `aggregate` in `momentum_backtest.py`**

In the `aggregate` function, find the for-loop iterating over stages:
```python
    for stage in ("MOMENTUM_1", "MOMENTUM_2", "MOMENTUM_3"):
```
Replace with:
```python
    for stage in ("EM", "MOMENTUM_1", "MOMENTUM_2", "MOMENTUM_3"):
```

Inside that loop, after the existing `by_stage[stage] = {...}` dict construction, add EM-specific KPI:
```python
        if stage == "EM":
            closed = [L for L in s_legs if L.get("exit_reason") is not None]
            upgraded = [L for L in closed if L.get("exit_reason") == "UPGRADE"]
            if closed:
                by_stage[stage]["transition_to_M1_pct"] = round(
                    len(upgraded) / len(closed) * 100, 1)
            else:
                by_stage[stage]["transition_to_M1_pct"] = None
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/test_momentum_backtest.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add momentum_backtest.py tests/test_momentum_backtest.py
git commit -m "$(cat <<'EOF'
feat(momentum): backtest EM stage + transition_to_M1_pct KPI

- by_stage now aggregates EM legs alongside M1/M2/M3
- transition_to_M1_pct = % of closed EM legs whose exit_reason == UPGRADE
- Excludes in-progress legs (exit_reason None) from denominator
- None when no closed EM legs (early in backtest accumulation)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: momentum_scanner orchestration — Full IWB EM scan + sector annotation + rotation radar

**Files:**
- Modify: `momentum_scanner.py:145-251` (`_scan_market`)
- Test: `tests/test_momentum_scanner.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_momentum_scanner.py`:
```python
def test_scan_result_has_em_signal_list_and_rotation_radar(monkeypatch, tmp_path):
    """Scan emits signals['EM'] (list) and rotation_radar (list of [sector, count])."""
    import os, json, pandas as pd
    import momentum_scanner as msc, momentum_data as md, momentum_signal as msig

    # Two stocks: AAA = EM-passing, BBB = M1-passing
    n = 90
    aaa = [100 + i * 0.4 for i in range(n)]
    bbb = [100 + i * 0.6 for i in range(n)]
    closes = pd.DataFrame({"AAA": aaa, "BBB": bbb,
                            "XLK": aaa, "XLF": bbb,
                            "SPY": [100 + i * 0.05 for i in range(n)],
                            "QQQ": [100 + i * 0.05 for i in range(n)]})
    volumes = pd.DataFrame({k: [1_500_000] * n for k in closes.columns})

    monkeypatch.setattr(md, "fetch_yf_bulk",
                         lambda tickers, period="90d": (closes[tickers], volumes[tickers]))
    monkeypatch.setattr("momentum_universe.build_us_universe", lambda: ["AAA", "BBB"])
    monkeypatch.setattr(md, "get_us_sector_holdings", lambda: {})
    monkeypatch.setattr(md, "build_sector_mapping",
                         lambda holdings, market: {"AAA": "XLY", "BBB": "XLK"})

    proj = str(tmp_path)
    os.makedirs(os.path.join(proj, "history"), exist_ok=True)
    result = msc.scan_momentum_us(proj)

    assert "signals" in result
    assert "EM" in result["signals"]  # New tier list
    assert isinstance(result["signals"]["EM"], list)
    assert "rotation_radar" in result
    assert isinstance(result["rotation_radar"], list)


def test_em_scan_uses_full_universe_not_top_sectors(monkeypatch, tmp_path):
    """EM should evaluate stocks even if their sector isn't in top_sectors.

    Scenario: AAA's sector (XLY) is NOT a top sector (only XLK is).
    Without EM bypass, AAA would be excluded. With EM bypass, AAA still gets
    evaluated and may appear in signals['EM'] with sector_top_rank=None.
    """
    import os, pandas as pd
    import momentum_scanner as msc, momentum_data as md

    # synthetic data crafted so AAA satisfies EM gates
    n = 90
    aaa = [50.0] * 70 + [50.0 + i * 1.5 for i in range(20)]   # late inflection
    closes = pd.DataFrame({
        "AAA": aaa,
        "XLK": [100 + i * 0.6 for i in range(n)],   # strong sector
        "XLY": [100 + i * 0.05 for i in range(n)],  # weak sector
        "SPY": [100 + i * 0.05 for i in range(n)],
        "QQQ": [100 + i * 0.05 for i in range(n)],
    })
    volumes = pd.DataFrame({k: [2_000_000] * n for k in closes.columns})

    monkeypatch.setattr(md, "fetch_yf_bulk",
                         lambda tickers, period="90d": (closes[tickers], volumes[tickers]))
    monkeypatch.setattr("momentum_universe.build_us_universe", lambda: ["AAA"])
    monkeypatch.setattr(md, "get_us_sector_holdings", lambda: {})
    monkeypatch.setattr(md, "build_sector_mapping",
                         lambda holdings, market: {"AAA": "XLY"})

    proj = str(tmp_path)
    os.makedirs(os.path.join(proj, "history"), exist_ok=True)
    result = msc.scan_momentum_us(proj)

    # AAA's sector (XLY) is not top — but if AAA satisfies EM, it should be
    # in signals['EM'] with sector_top_rank=None
    em_tickers = [s["ticker"] for s in result["signals"].get("EM", [])]
    if em_tickers:
        for s in result["signals"]["EM"]:
            if s["ticker"] == "AAA":
                assert s.get("sector_top_rank") is None  # not top sector
                break


def test_signals_enriched_with_streak_after_history_update(monkeypatch, tmp_path):
    """Rendered signals include streak/change populated from history."""
    import os, pandas as pd
    import momentum_scanner as msc, momentum_data as md

    n = 90
    closes = pd.DataFrame({
        "AAA": [100 + i * 0.5 for i in range(n)],
        "XLK": [100 + i * 0.5 for i in range(n)],
        "SPY": [100 + i * 0.05 for i in range(n)],
        "QQQ": [100 + i * 0.05 for i in range(n)],
    })
    volumes = pd.DataFrame({k: [2_000_000] * n for k in closes.columns})
    monkeypatch.setattr(md, "fetch_yf_bulk",
                         lambda tickers, period="90d": (closes[tickers], volumes[tickers]))
    monkeypatch.setattr("momentum_universe.build_us_universe", lambda: ["AAA"])
    monkeypatch.setattr(md, "get_us_sector_holdings", lambda: {})
    monkeypatch.setattr(md, "build_sector_mapping",
                         lambda h, market: {"AAA": "XLK"})

    proj = str(tmp_path)
    os.makedirs(os.path.join(proj, "history"), exist_ok=True)
    result = msc.scan_momentum_us(proj)

    all_sigs = (result["signals"]["MOMENTUM_3"] + result["signals"]["MOMENTUM_2"]
                + result["signals"]["MOMENTUM_1"] + result["signals"].get("EM", []))
    if all_sigs:
        # First-day signal: streak=1, change="NEW"
        assert all_sigs[0].get("streak") == 1
        assert all_sigs[0].get("change") == "NEW"


def test_momentum_disable_em_env_skips_em_track(monkeypatch, tmp_path):
    """MOMENTUM_DISABLE_EM=1 → EM signals empty, rotation_radar empty."""
    import os, pandas as pd
    import momentum_scanner as msc, momentum_data as md

    n = 90
    closes = pd.DataFrame({
        "AAA": [100 + i * 0.5 for i in range(n)],
        "XLK": [100 + i * 0.5 for i in range(n)],
        "XLY": [100 + i * 0.05 for i in range(n)],
        "SPY": [100 + i * 0.05 for i in range(n)],
        "QQQ": [100 + i * 0.05 for i in range(n)],
    })
    volumes = pd.DataFrame({k: [2_000_000] * n for k in closes.columns})
    monkeypatch.setattr(md, "fetch_yf_bulk",
                         lambda tickers, period="90d": (closes[tickers], volumes[tickers]))
    monkeypatch.setattr("momentum_universe.build_us_universe", lambda: ["AAA"])
    monkeypatch.setattr(md, "get_us_sector_holdings", lambda: {})
    monkeypatch.setattr(md, "build_sector_mapping",
                         lambda h, market: {"AAA": "XLY"})  # not top sector

    monkeypatch.setenv("MOMENTUM_DISABLE_EM", "1")

    proj = str(tmp_path)
    os.makedirs(os.path.join(proj, "history"), exist_ok=True)
    result = msc.scan_momentum_us(proj)

    assert result["signals"].get("EM", []) == []
    assert result.get("rotation_radar", []) == []
```

- [ ] **Step 2: Run tests to verify failure**

```bash
python -m pytest tests/test_momentum_scanner.py -v -k "em_signal_list or full_universe"
```
Expected: FAIL.

- [ ] **Step 3: Modify `_scan_market` in `momentum_scanner.py`**

Update `_empty_result` first to include `EM` and `rotation_radar`:
```python
def _empty_result(market: str, status: str = "ok",
                  error_message: str | None = None) -> dict:
    return {
        "market": market,
        "version": cfg.VERSION,
        "as_of": _today_kst(),
        "scanned_count": 0,
        "top_sectors": [],
        "signals": {"MOMENTUM_3": [], "MOMENTUM_2": [], "MOMENTUM_1": [], "EM": []},
        "rotation_radar": [],
        "backtest_summary": None,
        "status": status,
        "error_message": error_message,
    }
```

Inside `_scan_market`, after `signals = {"MOMENTUM_3": [], "MOMENTUM_2": [], "MOMENTUM_1": []}` line, change to:
```python
        signals = {"MOMENTUM_3": [], "MOMENTUM_2": [], "MOMENTUM_1": [], "EM": []}
```

Build a sector_top_rank lookup (sector ETF → rank 1/2/3 if in top_sectors, else None) right after `top_sectors = msig.select_top_sectors(evaluated_sectors)`:
```python
        sector_top_rank_map: dict[str, int] = {
            s["ticker"]: idx + 1 for idx, s in enumerate(top_sectors)
        }
```

Now expand stock_data_map. **Replace** the existing block (`# bulk indicators` → `result["signals"] = signals`) with this block that scans Full IWB universe (US) plus existing sector-restricted universe for KR:

```python
        # MOMENTUM_DISABLE_EM=1 → fall back to v1.0 behavior (M+ only, no EM, no rotation radar).
        em_enabled = os.environ.get("MOMENTUM_DISABLE_EM", "").strip() not in ("1", "true", "yes")

        # Bulk indicators on the full evaluation universe
        if market == "US" and em_enabled:
            # M+ uses Top sectors only; EM uses Full IWB.
            # We fetch indicators for the union (full universe) once.
            eval_universe = list(set(top_tickers) | set(universe))
        else:
            eval_universe = list(top_tickers)
        stock_data_map = _fetch_indicators(eval_universe)

        # Pre-filter + evaluate per stock — both M+ and EM tracks
        today_signal_list: list[dict] = []
        for ticker, sd in stock_data_map.items():
            sector_etf = ticker_sector_map.get(ticker)
            sector_top_rank = sector_top_rank_map.get(sector_etf)
            in_top_sector = sector_top_rank is not None
            sector_5d = None
            if sector_etf and sector_etf in sector_data:
                sector_5d = sector_data[sector_etf].get("ret_5d_pct")
            sd["ticker"] = ticker
            sd["sector"] = sector_etf

            evaluation = None
            # Track 1 — M+ scan: only top-sector stocks (US) or all (KR), prefilter required
            if (in_top_sector or market == "KR") and msig.passes_prefilter(sd):
                evaluation = msig.evaluate_stock(
                    sd, sector_5d_return=sector_5d, sector_top_rank=sector_top_rank
                )
            # Track 2 — EM scan: full universe, no sector gate, lighter check (skip if disabled)
            if evaluation is None and em_enabled:
                if msig.classify_em(sd):
                    evaluation = msig.evaluate_stock(
                        sd, sector_5d_return=sector_5d, sector_top_rank=sector_top_rank
                    )

            if evaluation is None:
                continue
            evaluation["name"] = _lookup_name(ticker, market)
            stage = evaluation["stage"]
            if stage in signals:
                signals[stage].append(evaluation)
            today_signal_list.append(evaluation)

        result["signals"] = signals

        # Sector Rotation Radar — non-Top sectors with EM count >= 2
        from collections import Counter
        em_sector_counter: Counter = Counter()
        for s in signals.get("EM", []):
            if s.get("sector_top_rank") is None and s.get("sector"):
                em_sector_counter[s["sector"]] += 1
        rotation_radar = sorted(
            [(sector, count) for sector, count in em_sector_counter.items()
             if count >= 2],
            key=lambda x: -x[1]
        )[:5]
        result["rotation_radar"] = [list(item) for item in rotation_radar]
```

**After** the existing `history = mh.update_history(...)` and `mh.save_history(...)` lines (already present in `_scan_market`), add streak/change enrichment back into the in-memory `today_signal_list` so the rendered template sees it:
```python
        # Enrich signals with streak/change from the just-saved history
        # (signals share refs with result['signals'] entries — mutation propagates).
        for sig in today_signal_list:
            today_entry = (history.get("data", {}).get(sig["ticker"], {}) or {}).get(result["as_of"])
            if today_entry:
                sig["streak"] = today_entry.get("streak")
                sig["change"] = today_entry.get("change")
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/test_momentum_scanner.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add momentum_scanner.py tests/test_momentum_scanner.py
git commit -m "$(cat <<'EOF'
feat(momentum): orchestrate EM scan on Full IWB + rotation radar + streak enrich

- _scan_market now runs two tracks: M+ (top sectors, prefilter) and EM (full universe, classify_em)
- Stocks evaluated once; M+ wins (classify_tier handles precedence)
- sector_top_rank annotation flows through evaluate_stock to history
- rotation_radar: top 5 non-top sectors with >= 2 EM hits, count desc
- After history.update_history, signals enriched with streak/change for UI render
- MOMENTUM_DISABLE_EM=1 env var = safe rollback to v1.0 (EM track skipped, radar empty)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: templates/base_momentum.html — Two sections + Maturity column + Sector Rotation Radar

**Files:**
- Modify: `templates/base_momentum.html` (signal table + radar block + styles)
- Test: `tests/test_momentum_templates.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_momentum_templates.py`:
```python
def test_template_has_emerging_section_heading():
    src = open("templates/base_momentum.html", encoding="utf-8").read()
    assert "Momentum Leaders" in src
    assert "Emerging Momentum" in src


def test_template_has_rotation_radar_block():
    src = open("templates/base_momentum.html", encoding="utf-8").read()
    assert "rotation_radar" in src
    assert "Potential Sector Rotation" in src or "Sector Rotation" in src


def test_template_has_maturity_column():
    src = open("templates/base_momentum.html", encoding="utf-8").read()
    assert "Maturity" in src
    assert "maturity-early" in src
    assert "maturity-mid" in src
    assert "maturity-extended" in src


def test_template_has_dist_ema9_column():
    src = open("templates/base_momentum.html", encoding="utf-8").read()
    assert "dist_ema9" in src
    # column header
    assert "dist_ema9" in src.lower() or "dist EMA9" in src


def test_template_has_em_tier_class():
    src = open("templates/base_momentum.html", encoding="utf-8").read()
    assert ".tier-em" in src or ".EM" in src


def test_template_dropped_change_column_in_signals_table():
    """Change column was redundant with 1d/5d/20d returns."""
    src = open("templates/base_momentum.html", encoding="utf-8").read()
    # crude check: 'Change' as a <th> column header gone from signals tables
    # (still allowed elsewhere if e.g. a different feature uses it).
    assert "<th>Change</th>" not in src


def test_template_has_streak_column():
    src = open("templates/base_momentum.html", encoding="utf-8").read()
    assert "<th>Streak</th>" in src


def test_template_renders_em_signals(tmp_path):
    """Render template with EM signals and rotation radar — produces valid HTML."""
    import jinja2
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=True,
    )
    tmpl = env.get_template("base_momentum.html")
    result = {
        "as_of": "2026-05-09", "version": "Momentum v1.5",
        "scanned_count": 1003, "elapsed_s": 47.0, "status": "ok",
        "top_sectors": [],
        "signals": {
            "MOMENTUM_3": [], "MOMENTUM_2": [], "MOMENTUM_1": [],
            "EM": [{
                "ticker": "DUOL", "name": "Duolingo", "tier": "EM",
                "stage": "EM", "maturity": "EARLY",
                "sector": "Education", "sector_top_rank": None,
                "price": 180.0, "rsi": 64.0,
                "ret_1d_pct": 1.2, "ret_5d_pct": 4.5, "ret_20d_pct": 11.0,
                "dist_ema9_pct": 1.8, "streak": 3, "change": "HOLD",
                "rs_vs_sector": None, "risk_tags": [], "hint": "관찰",
            }],
        },
        "rotation_radar": [["Education", 4], ["Cybersecurity", 3]],
        "backtest_summary": None,
    }
    html = tmpl.render(market_label="US", result=result)
    assert "DUOL" in html
    assert "Duolingo" in html
    assert "EARLY" in html
    assert "Education" in html
    assert "1.8" in html      # dist_ema9
    assert "3d" in html        # streak rendered as "3d"
```

- [ ] **Step 2: Run tests to verify failure**

```bash
python -m pytest tests/test_momentum_templates.py -v
```
Expected: 7 tests FAIL (template still v1.0 layout).

- [ ] **Step 3: Replace `templates/base_momentum.html` with v1.5 layout**

Replace the body of `templates/base_momentum.html` with:
```html
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ market_label }} Momentum {{ result.as_of }}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #1a1a1a; color: #e0e0e0; font-family: 'Consolas', 'D2Coding', monospace;
         margin: 0; padding: 1.5em; line-height: 1.5; font-size: 14px; }
  .container { max-width: 1200px; margin: 0 auto; }
  h1 { color: #ffa500; font-size: 28px; font-weight: bold; margin-bottom: 0.5em; }
  h2 { color: #ffa500; font-size: 18px; font-weight: bold; margin: 1.5em 0 0.8em; border-bottom: 1px solid #444; padding-bottom: 0.4em; }
  h3 { color: #ffb84d; font-size: 15px; font-weight: bold; margin: 1em 0 0.6em; }
  p { margin: 0.5em 0; }
  table { border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 13px; }
  th, td { border: 1px solid #444; padding: 6px 8px; text-align: left; }
  th { background: #2a2a2a; color: #ffb84d; font-weight: bold; }
  tr:nth-child(even) { background: #222; }
  tr:nth-child(odd) { background: #1f1f1f; }
  a { color: #4db8ff; text-decoration: none; }
  a:hover { color: #99d9ff; }
  nav { margin-bottom: 1.5em; }
  nav a { margin-right: 16px; font-weight: bold; }
  nav a:first-child { color: #bbb; }
  nav a:hover { color: #ddd; }
  .info { background: #2a2a2a; border-left: 3px solid #ffa500; padding: 8px 12px; margin: 0.8em 0; font-size: 13px; }
  .alert { background: #3d2020; border-left: 3px solid #ff4444; padding: 8px 12px; margin: 1em 0; color: #ffb3b3; }
  .pos { color: #4caf50; font-weight: bold; }
  .neg { color: #ff6b6b; font-weight: bold; }
  .tier-MOMENTUM_3, .M3 { color: #ff5722; font-weight: bold; }
  .tier-MOMENTUM_2, .M2 { color: #ffa500; font-weight: bold; }
  .tier-MOMENTUM_1, .M1 { color: #ffeb3b; }
  .tier-em { background: #2a3540; color: #cbd5e1; padding: 2px 6px; border-radius: 3px; font-weight: bold; }
  .maturity-early    { color: #22c55e; font-weight: bold; }
  .maturity-mid      { color: #eab308; }
  .maturity-extended { color: #ef4444; font-weight: bold; }
  .badge { display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 12px; margin: 0 2px 2px 0; }
  .badge-OVERHEAT { background: #d32f2f; color: #fff; }
  .badge-PARABOLIC { background: #ff9800; color: #fff; }
  .empty-state { text-align: center; padding: 2em 0; color: #888; }
  .empty-state-icon { font-size: 48px; margin-bottom: 0.5em; }
  .footer { margin-top: 2em; padding-top: 1em; border-top: 1px dashed #444; font-size: 12px; color: #888; }
  .sector-leader { background: #242424; border-left: 4px solid #ffa500; padding: 0.8em; margin: 0.5em 0; }
  .sr-ticker { color: #4db8ff; font-weight: bold; font-size: 13px; }
  .sr-score { color: #ffb84d; }
  .rotation-radar { background: #1f2a35; border-left: 3px solid #4db8ff; padding: 0.8em 1em; margin: 0.8em 0; }
  .rotation-radar h4 { color: #99d9ff; font-size: 13px; margin-bottom: 0.4em; }
  .rotation-radar .row { color: #cfe8ff; font-size: 13px; margin: 2px 0; }
  .rotation-radar .row.strong { color: #ffeb3b; font-weight: bold; }
  .star-top { color: #ffd54f; }
  @media (max-width: 768px) {
    body { padding: 1em; }
    table { font-size: 12px; }
    th, td { padding: 4px 6px; }
  }
</style>
</head>
<body>
<div class="container">

<nav>{% block nav %}<a href="index.html">📊 Portfolio</a> | 🔥 Momentum Scanner{% endblock %}</nav>

<h1>🔥 {{ market_label }} Momentum — {{ result.as_of }}</h1>
<p style="color: #aaa;">Scanned: {{ result.scanned_count }} tickers · ⏱ {{ result.elapsed_s|default(0)|round(1) }}s · {{ result.version }}</p>

{% if result.status == "failed" %}
<div class="alert">⚠ Scan failed: {{ result.error_message }}</div>
{% else %}

{% set leaders_count = result.signals.MOMENTUM_3|length + result.signals.MOMENTUM_2|length + result.signals.MOMENTUM_1|length %}
{% set em_count = result.signals.get('EM', [])|length %}
<p style="margin: 1em 0; color: #ccc;">
  Leaders: <span class="M3">M3={{ result.signals.MOMENTUM_3|length }}</span> /
  <span class="M2">M2={{ result.signals.MOMENTUM_2|length }}</span> /
  <span class="M1">M1={{ result.signals.MOMENTUM_1|length }}</span>
  &nbsp;·&nbsp; Emerging: <span class="tier-em">{{ em_count }}</span>
</p>

<h2>Sector Leaders</h2>
{% if result.top_sectors %}
<div style="margin: 1em 0;">
  {% for s in result.top_sectors %}
  <div class="sector-leader">
    <span class="sr-ticker">{{ s.ticker }}</span>
    <span class="sr-score">Score: {{ s.score }}</span> |
    <span class="{{ 'pos' if (s.ret_5d_pct or 0) >= 0 else 'neg' }}">{{ "%.2f"|format(s.ret_5d_pct or 0) }}% (5d)</span> |
    RS: {{ s.rs_score|default(0) }}
  </div>
  {% endfor %}
</div>
{% else %}
<p style="color: #666;">— No sector qualifies for momentum today.</p>
{% endif %}

{# ── Section A — Momentum Leaders ────────────────────────── #}
<h2>🔥 Momentum Leaders (M1/M2/M3)</h2>
{% for stage_name, stage_label in [("MOMENTUM_3","M3"),("MOMENTUM_2","M2"),("MOMENTUM_1","M1")] %}
  {% set entries = result.signals[stage_name] %}
  <h3 class="{{ stage_label }}">{{ stage_label }} ({{ entries|length }})</h3>
  {% if entries %}
  <table>
    <thead>
      <tr>
        <th>Name</th>
        <th>Tier</th>
        <th>Maturity</th>
        <th>Streak</th>
        <th>Sector</th>
        <th>RSI</th>
        <th>dist_ema9</th>
        <th>1d %</th>
        <th>5d %</th>
        <th>20d %</th>
        <th>Sec_RS</th>
        <th>Risk Tags</th>
        <th>Hint</th>
      </tr>
    </thead>
    <tbody>
    {% for e in entries %}
      {% include '_momentum_row.html' ignore missing %}
      <tr>
        <td><a href="details/{{ e.ticker }}.html" title="{{ e.ticker }}">{{ e.name or e.ticker }}</a>{% if e.name and e.name != e.ticker %}<span style="color:#888;font-size:0.82em;margin-left:6px;">{{ e.ticker }}</span>{% endif %}</td>
        <td><span class="tier-{{ e.tier or e.stage }}">{{ stage_label }}</span></td>
        <td>{% if e.maturity %}<span class="maturity-{{ e.maturity|lower }}">{{ e.maturity }}</span>{% else %}—{% endif %}</td>
        <td>{% if e.streak %}{{ e.streak }}d{% else %}—{% endif %}</td>
        <td>{{ e.sector or "—" }}{% if e.sector_top_rank %} <span class="star-top">⭐</span>{% endif %}</td>
        <td>{{ "%.1f"|format(e.rsi or 0) }}</td>
        <td>{% if e.dist_ema9_pct is not none %}{{ "%+.1f"|format(e.dist_ema9_pct) }}%{% else %}—{% endif %}</td>
        <td class="{{ 'pos' if (e.ret_1d_pct or 0) >= 0 else 'neg' }}">{{ "%.2f"|format(e.ret_1d_pct or 0) }}%</td>
        <td class="{{ 'pos' if (e.ret_5d_pct or 0) >= 0 else 'neg' }}">{{ "%.2f"|format(e.ret_5d_pct or 0) }}%</td>
        <td class="{{ 'pos' if (e.ret_20d_pct or 0) >= 0 else 'neg' }}">{% if e.ret_20d_pct is not none %}{{ "%.2f"|format(e.ret_20d_pct) }}%{% else %}—{% endif %}</td>
        <td>{{ "✓" if e.rs_vs_sector else "—" }}</td>
        <td>{% for tag in e.risk_tags %}<span class="badge badge-{{ tag }}">{{ tag }}</span>{% endfor %}</td>
        <td>{{ e.hint }}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p style="color: #666;">— No {{ stage_label }} signals today.</p>
  {% endif %}
{% endfor %}

{# ── Section B — Emerging Momentum ───────────────────────── #}
<h2>🌱 Emerging Momentum (EM)</h2>
{% if result.rotation_radar %}
<div class="rotation-radar">
  <h4>Potential Sector Rotation</h4>
  {% for sector_count in result.rotation_radar %}
  <div class="row {{ 'strong' if sector_count[1] >= 3 else '' }}">
    {{ sector_count[0] }} ({{ sector_count[1] }} EM, 비-Top)
  </div>
  {% endfor %}
</div>
{% endif %}
{% set em_entries = result.signals.get('EM', []) %}
<h3 class="tier-em" style="display:inline-block;">EM ({{ em_entries|length }})</h3>
{% if em_entries %}
<table>
  <thead>
    <tr>
      <th>Name</th>
      <th>Tier</th>
      <th>Maturity</th>
      <th>Streak</th>
      <th>Sector</th>
      <th>RSI</th>
      <th>dist_ema9</th>
      <th>1d %</th>
      <th>5d %</th>
      <th>20d %</th>
      <th>Risk Tags</th>
      <th>Hint</th>
    </tr>
  </thead>
  <tbody>
  {% for e in em_entries %}
    <tr>
      <td><a href="details/{{ e.ticker }}.html" title="{{ e.ticker }}">{{ e.name or e.ticker }}</a>{% if e.name and e.name != e.ticker %}<span style="color:#888;font-size:0.82em;margin-left:6px;">{{ e.ticker }}</span>{% endif %}</td>
      <td><span class="tier-em">EM</span></td>
      <td>{% if e.maturity %}<span class="maturity-{{ e.maturity|lower }}">{{ e.maturity }}</span>{% else %}—{% endif %}</td>
      <td>{% if e.streak %}{{ e.streak }}d{% else %}—{% endif %}</td>
      <td>{{ e.sector or "—" }}{% if e.sector_top_rank %} <span class="star-top">⭐</span>{% endif %}</td>
      <td>{{ "%.1f"|format(e.rsi or 0) }}</td>
      <td>{% if e.dist_ema9_pct is not none %}{{ "%+.1f"|format(e.dist_ema9_pct) }}%{% else %}—{% endif %}</td>
      <td class="{{ 'pos' if (e.ret_1d_pct or 0) >= 0 else 'neg' }}">{{ "%.2f"|format(e.ret_1d_pct or 0) }}%</td>
      <td class="{{ 'pos' if (e.ret_5d_pct or 0) >= 0 else 'neg' }}">{{ "%.2f"|format(e.ret_5d_pct or 0) }}%</td>
      <td class="{{ 'pos' if (e.ret_20d_pct or 0) >= 0 else 'neg' }}">{% if e.ret_20d_pct is not none %}{{ "%.2f"|format(e.ret_20d_pct) }}%{% else %}—{% endif %}</td>
      <td>{% for tag in e.risk_tags %}<span class="badge badge-{{ tag }}">{{ tag }}</span>{% endfor %}</td>
      <td>{{ e.hint }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
<p style="color: #666;">— No emerging signals today.</p>
{% endif %}

{% if result.backtest_summary %}
<h2>Backtest Summary (Direct 90-day rolling)</h2>
{% set bs = result.backtest_summary %}
{% if bs.alerts and bs.alerts.consecutive_loss_warning %}
<div class="alert">⚠ 최근 5개 leg 중 {{ bs.alerts.recent_5_legs_loss_count }}개 손실 — 신호 신뢰도 점검 필요</div>
{% endif %}
<table>
  <thead>
    <tr>
      <th>Stage</th>
      <th>#legs</th>
      <th>Win 5d %</th>
      <th>Avg 3d %</th>
      <th>Avg 5d %</th>
      <th>Avg 10d %</th>
      <th>MDD %</th>
      <th>Avg dur (days)</th>
      <th>EM→M1 %</th>
    </tr>
  </thead>
  <tbody>
  {% for stage in ["MOMENTUM_3","MOMENTUM_2","MOMENTUM_1","EM"] %}
    {% if bs.by_stage and stage in bs.by_stage %}
    {% set st = bs.by_stage[stage] %}
    <tr>
      <td>{{ stage }}</td>
      <td>{{ st.leg_count }}</td>
      <td>{{ "%.1f"|format(st.win_rate_5d_pct or 0) }}%</td>
      <td>{{ "%.2f"|format(st.avg_ret_3d_pct or 0) }}%</td>
      <td>{{ "%.2f"|format(st.avg_ret_5d_pct or 0) }}%</td>
      <td>{{ "%.2f"|format(st.avg_ret_10d_pct or 0) }}%</td>
      <td class="neg">{{ "%.2f"|format(st.avg_mdd_pct or 0) }}%</td>
      <td>{{ "%.1f"|format(st.avg_duration_days or 0) }}</td>
      <td>{% if stage == "EM" and st.transition_to_M1_pct is not none %}{{ "%.1f"|format(st.transition_to_M1_pct) }}%{% else %}—{% endif %}</td>
    </tr>
    {% endif %}
  {% endfor %}
  </tbody>
</table>
{% if bs.by_streak and "3+" in bs.by_streak %}
<p style="margin-top: 1em; color: #4caf50;">🔥 <b>Edge:</b> M3 streak 3+ days → 5d avg {{ "%.1f"|format(bs.by_streak["3+"].avg_ret_5d or 0) }}%</p>
{% endif %}
{% else %}
<p style="color: #666;">백테스트 데이터 누적 중 (최소 90일 후 표시)</p>
{% endif %}

{% endif %}

<div class="footer">
{% block footer %}
<p>Universe: {{ result.scanned_count }} | Version: {{ result.version }}</p>
<p>⚠ Backtest assumes close entry — slippage expected in live trading</p>
{% endblock %}
</div>

</div>
</body>
</html>
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/test_momentum_templates.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/base_momentum.html tests/test_momentum_templates.py
git commit -m "$(cat <<'EOF'
feat(ui): two-section momentum template — Leaders / Emerging + Rotation Radar

- Top section: M1/M2/M3 grouped (Momentum Leaders)
- Bottom section: EM with Sector Rotation Radar block (non-Top sectors, count >= 2)
- New columns: Tier (badge), Maturity (color), dist_ema9 (Maturity rationale)
- Removed: Change column (redundant with 1d/5d/20d), Price column (de-prioritized)
- Backtest table adds EM→M1 % for EM row only
- Color: 🟢 EARLY / 🟡 MID / 🔴 EXTENDED

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: telegram_sender.py — EM count + Rotation Radar

**Files:**
- Modify: `telegram_sender.py` (find `_format_momentum_message`)
- Test: write a small inline format test (no existing telegram-format test)

- [ ] **Step 1: Locate the formatter**

```bash
python -m pytest --collect-only tests/ -q | grep -i telegram | head
```
Open `telegram_sender.py` and find `_format_momentum_message`.

- [ ] **Step 2: Write failing test**

Create `tests/test_momentum_telegram.py`:
```python
"""Telegram momentum brief formatter tests."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _fake_us_result():
    return {
        "as_of": "2026-05-09", "version": "Momentum v1.5",
        "status": "ok", "scanned_count": 1003,
        "top_sectors": [{"ticker": "XLK", "score": 90}],
        "signals": {
            "MOMENTUM_3": [{"ticker": "NVDA", "name": "NVDA",
                              "maturity": "EXTENDED", "risk_tags": ["OVERHEAT"]}],
            "MOMENTUM_2": [], "MOMENTUM_1": [],
            "EM": [
                {"ticker": "DUOL", "name": "Duolingo", "maturity": "EARLY",
                 "sector": "Education"},
                {"ticker": "HOOD", "name": "Hood", "maturity": "EARLY",
                 "sector": "Financial"},
            ],
        },
        "rotation_radar": [["Education", 4], ["Cybersecurity", 3]],
        "backtest_summary": {
            "by_stage": {
                "EM": {"leg_count": 89, "transition_to_M1_pct": 47.2,
                        "avg_ret_5d_pct": 2.3, "win_rate_5d_pct": 53.9}
            }
        },
    }


def test_momentum_message_includes_em_count_and_rotation():
    import telegram_sender as ts
    msg = ts._format_momentum_message(us=_fake_us_result(), kr=None)
    assert "Emerging" in msg or "🌱" in msg
    assert "DUOL" in msg
    assert "Education" in msg
    assert "Rotation" in msg or "회전" in msg


def test_momentum_message_includes_em_transition_kpi():
    import telegram_sender as ts
    msg = ts._format_momentum_message(us=_fake_us_result(), kr=None)
    assert "47.2" in msg or "transition" in msg.lower()


def test_momentum_message_under_3500_chars():
    import telegram_sender as ts
    big_us = _fake_us_result()
    big_us["signals"]["EM"] = [
        {"ticker": f"T{i}", "name": f"Ticker{i}", "maturity": "EARLY",
         "sector": f"Sector{i}"} for i in range(50)
    ]
    msg = ts._format_momentum_message(us=big_us, kr=big_us)
    assert len(msg) <= 3500
```

- [ ] **Step 3: Run tests to verify failure**

```bash
python -m pytest tests/test_momentum_telegram.py -v
```
Expected: FAIL.

- [ ] **Step 4: Modify `_format_momentum_message` in `telegram_sender.py`**

Locate `_format_momentum_message` (search for the function). Identify where it builds the per-market section. After the existing M3/M2/M1 lines, add EM listing and rotation block.

In the per-market formatter helper (likely an inner function or block keyed on `us` / `kr` arg), add:

```python
def _format_market_section(label_emoji: str, label: str, result: dict | None) -> str:
    if not result or result.get("status") != "ok":
        return ""
    sigs = result.get("signals", {})
    lines = [f"{label_emoji} {label}"]

    # Top sectors line — existing
    tops = result.get("top_sectors", [])
    if tops:
        lines.append("Top sectors: " + ", ".join(s.get("ticker", "?") for s in tops[:3]))

    # M3/M2/M1 — existing format kept brief
    for tier_key, short in [("MOMENTUM_3", "M3"), ("MOMENTUM_2", "M2"), ("MOMENTUM_1", "M1")]:
        items = sigs.get(tier_key, [])
        if items:
            preview = ", ".join(s.get("ticker", "?") for s in items[:5])
            extra = "" if len(items) <= 5 else f" (+{len(items)-5})"
            lines.append(f"{short} ({len(items)}): {preview}{extra}")

    # EM section
    em = sigs.get("EM", [])
    if em:
        preview = ", ".join(
            f"{s.get('ticker','?')}{_maturity_marker(s.get('maturity'))}"
            for s in em[:5]
        )
        extra = "" if len(em) <= 5 else f" (+{len(em)-5})"
        lines.append(f"🌱 Emerging ({len(em)}): {preview}{extra}")

    # Rotation Radar
    radar = result.get("rotation_radar") or []
    if radar:
        rotation_str = ", ".join(f"{name} ({cnt})" for name, cnt in radar[:5])
        lines.append(f"🔄 Sector Rotation Radar: {rotation_str}")

    return "\n".join(lines)


def _maturity_marker(maturity: str | None) -> str:
    return {
        "EARLY": "🟢", "MID": "🟡", "EXTENDED": "🔴"
    }.get(maturity, "")
```

Replace the existing market-section construction in `_format_momentum_message` to call `_format_market_section`. After both market sections, append the EM transition KPI line if present:

```python
    parts: list[str] = [f"🔥 Momentum Scanner — {as_of}"]
    us_section = _format_market_section("🇺🇸", "US", us)
    if us_section:
        parts.append(us_section)
    kr_section = _format_market_section("🇰🇷", "KR", kr)
    if kr_section:
        parts.append(kr_section)

    # EM transition KPI from US backtest (if available)
    bs = (us or {}).get("backtest_summary") or {}
    em_stats = (bs.get("by_stage") or {}).get("EM") or {}
    transition_pct = em_stats.get("transition_to_M1_pct")
    if transition_pct is not None:
        parts.append(f"🔥 Edge: EM transition to M1 = {transition_pct:.1f}% (90d)")

    # URL footer (existing — keep unchanged)
    # ... existing URL-building lines ...

    msg = "\n\n".join(parts)
    return msg[:3500]
```

When integrating, preserve any existing URL-footer logic. If the existing function builds messages differently, adapt the diff to match — the *behavior* required is: emit EM list line + rotation line + transition KPI, and stay ≤3500 chars.

- [ ] **Step 5: Run tests to verify pass**

```bash
python -m pytest tests/test_momentum_telegram.py -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add telegram_sender.py tests/test_momentum_telegram.py
git commit -m "$(cat <<'EOF'
feat(telegram): momentum brief — EM list + Sector Rotation Radar + transition KPI

- Per-market block lists EM with maturity emoji (🟢🟡🔴) — first 5 + count
- Rotation Radar line: top non-Top sectors with EM count >= 2
- Footer KPI: 'EM transition to M1 = X.X% (90d)' from US backtest
- 3500-char trim preserved

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Golden sample regression test

**Files:**
- Create: `tests/test_emerging_momentum_golden.py`
- Create: `tests/fixtures/em_golden_2026_05_09.json`

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/em_golden_2026_05_09.json`:
```json
{
  "_doc": "Golden sample for v1.5 — five canonical scenarios. Bumped on intentional logic change.",
  "stocks": [
    {
      "case": "EM_EARLY",
      "stock_data": {
        "ticker": "PLTR",
        "ema9": 22.6, "ema21": 22.0, "ema65": 20.5,
        "ema21_slope_3d_pct": 0.4,
        "close": 22.9, "ma20": 21.5, "ma50": 20.0,
        "rsi14": 64.0, "dist_ema9_pct": 1.3,
        "ret_3d_pct": 2.0, "ret_5d_pct": 4.5, "ret_20d_pct": 11.0,
        "volume_ratio": 1.10, "change_pct": 1.5,
        "high_52w": 25.0, "macd_hist_trend": "rising"
      },
      "expected_tier": "EM",
      "expected_maturity": "EARLY",
      "expected_risk_tags": []
    },
    {
      "case": "EM_MID",
      "stock_data": {
        "ticker": "PLTR_MID",
        "ema9": 23.5, "ema21": 22.0, "ema65": 20.5,
        "ema21_slope_3d_pct": 0.6,
        "close": 24.6, "ma20": 22.0,
        "rsi14": 70.0, "dist_ema9_pct": 4.7,
        "ret_3d_pct": 3.0, "ret_5d_pct": 6.0, "ret_20d_pct": 14.0,
        "volume_ratio": 1.15, "change_pct": 1.0,
        "high_52w": 25.0, "macd_hist_trend": "rising"
      },
      "expected_tier": "EM",
      "expected_maturity": "MID",
      "expected_risk_tags": []
    },
    {
      "case": "M1_EXTENDED_OVERHEAT",
      "stock_data": {
        "ticker": "NVDA",
        "ema9": 880.0, "ema21": 850.0, "ema65": 800.0,
        "ema21_slope_3d_pct": 0.8,
        "close": 970.0, "ma20": 870.0, "ma50": 800.0,
        "rsi14": 82.0, "dist_ema9_pct": 10.2,
        "ret_3d_pct": 11.0, "ret_5d_pct": 13.0, "ret_20d_pct": 22.0,
        "volume_ratio": 2.0, "change_pct": 5.0,
        "high_52w": 970.0, "macd_hist_trend": "rising"
      },
      "expected_tier": "MOMENTUM_1",
      "expected_maturity": "EXTENDED",
      "expected_risk_tags": ["OVERHEAT"]
    },
    {
      "case": "NO_SIGNAL",
      "stock_data": {
        "ticker": "FLAT",
        "ema9": 100.0, "ema21": 100.0, "ema65": 100.0,
        "ema21_slope_3d_pct": -0.1,
        "close": 99.5, "ma20": 100.0, "ma50": 100.0,
        "rsi14": 49.0, "dist_ema9_pct": -0.5,
        "ret_3d_pct": -1.0, "ret_5d_pct": -1.5, "ret_20d_pct": 0.5,
        "volume_ratio": 0.9, "change_pct": -0.3,
        "high_52w": 110.0, "macd_hist_trend": "falling"
      },
      "expected_tier": null,
      "expected_maturity": null,
      "expected_risk_tags": []
    },
    {
      "case": "EM_EXTENDED_BY_RSI",
      "stock_data": {
        "ticker": "EXT_RSI",
        "ema9": 50.0, "ema21": 48.0, "ema65": 46.0,
        "ema21_slope_3d_pct": 0.3,
        "close": 51.0, "ma20": 47.0,
        "rsi14": 76.0, "dist_ema9_pct": 2.0,
        "ret_3d_pct": 2.5, "ret_5d_pct": 5.0, "ret_20d_pct": 11.0,
        "volume_ratio": 1.10, "change_pct": 1.0,
        "high_52w": 55.0, "macd_hist_trend": "rising"
      },
      "expected_tier": null,
      "expected_maturity": "EXTENDED",
      "expected_risk_tags": []
    }
  ]
}
```

Note on case 5 (`EM_EXTENDED_BY_RSI`): RSI 76 fails EM gate (< 72 required), so tier is null even though structure passes. Maturity is computed independently from tier — still "EXTENDED" by the RSI≥75 rule. This documents the orthogonality of Tier and Maturity.

- [ ] **Step 2: Write the golden test**

Create `tests/test_emerging_momentum_golden.py`:
```python
"""Golden sample regression — bump fixture on intentional logic change only."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import momentum_signal as ms

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                        "em_golden_2026_05_09.json")


def test_em_golden_sample_stable():
    with open(FIXTURE, encoding="utf-8") as f:
        data = json.load(f)
    failures: list[str] = []
    for case in data["stocks"]:
        sd = case["stock_data"]
        actual_tier = ms.classify_tier(sd)
        actual_maturity = ms.classify_maturity(sd)
        actual_risk = ms.compute_risk_tags(sd, actual_tier or "")
        if actual_tier != case["expected_tier"]:
            failures.append(f"{case['case']}: tier {actual_tier} != "
                              f"{case['expected_tier']}")
        if actual_maturity != case["expected_maturity"]:
            failures.append(f"{case['case']}: maturity {actual_maturity} != "
                              f"{case['expected_maturity']}")
        if sorted(actual_risk) != sorted(case["expected_risk_tags"]):
            failures.append(f"{case['case']}: risk {actual_risk} != "
                              f"{case['expected_risk_tags']}")
    assert not failures, "\n".join(failures)
```

- [ ] **Step 3: Run test**

```bash
python -m pytest tests/test_emerging_momentum_golden.py -v
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_emerging_momentum_golden.py tests/fixtures/em_golden_2026_05_09.json
git commit -m "$(cat <<'EOF'
test(momentum): golden sample regression for v1.5 (EM + Maturity + Risk)

Five canonical cases:
- EM_EARLY: PLTR-like (EM + EARLY)
- EM_MID: late-EM + MID
- M1_EXTENDED_OVERHEAT: NVDA-like (MOMENTUM_1 + EXTENDED + OVERHEAT)
- NO_SIGNAL: stale flat tape
- EM_EXTENDED_BY_RSI: structure passes but RSI=76 fails EM gate; Maturity still EXTENDED (orthogonality docs)

Bump the fixture date on intentional logic change only.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: CLAUDE.md — Register the plan

**Files:**
- Modify: `CLAUDE.md` (under "진행 중인 계획")

- [ ] **Step 1: Add bullet under "진행 중인 계획"**

Open `CLAUDE.md` and find the "진행 중인 계획" section. Append this bullet (after the last existing bullet):
```markdown
- [Emerging Momentum + Maturity Classifier v1.5](docs/superpowers/plans/2026-05-09-emerging-momentum-maturity.md) — Pipeline Step 4c2 확장 · EM tier (Full IWB, Structural Inflection Discovery) · Maturity 분류기(EARLY/MID/EXTENDED, EMA9 거리+RSI 2축) · 두 섹션 분리 UI + Sector Rotation Radar · EMA9/21/65 글로벌 데이터(`fetch_market_data.py`) · Risk Tag 정리(EARLY/EXTENDED 삭제) · history schema 1→2 + transition_to_M1_pct KPI · 기존 v5.3/v1.0 시그널 무영향
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: register Emerging Momentum + Maturity v1.5 plan in CLAUDE.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: E2E smoke test (`MODE=momentum_only`)

**Files:**
- Create: `tests/test_e2e_emerging_smoke.py`

- [ ] **Step 1: Write the smoke test**

Create `tests/test_e2e_emerging_smoke.py`:
```python
"""End-to-end smoke for momentum v1.5 (mocked yfinance).

Verifies:
  - scan_momentum_us produces a result with 'EM' bucket
  - rotation_radar present
  - history file is written with schema_version=2
  - backtest summary structure present (may be sparse on first run)
"""
import os, sys, json, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_e2e_us_smoke(monkeypatch, tmp_path):
    import momentum_scanner as msc
    import momentum_data as md

    n = 90
    rising = [100 + i * 0.5 for i in range(n)]
    flat = [100.0] * n
    closes = pd.DataFrame({
        "AAA": rising, "BBB": rising,
        "XLK": rising, "XLF": flat,
        "SPY": [100 + i * 0.05 for i in range(n)],
        "QQQ": [100 + i * 0.05 for i in range(n)],
    })
    volumes = pd.DataFrame({k: [2_000_000] * n for k in closes.columns})

    monkeypatch.setattr(md, "fetch_yf_bulk",
                         lambda tickers, period="90d": (closes[tickers], volumes[tickers]))
    monkeypatch.setattr("momentum_universe.build_us_universe", lambda: ["AAA", "BBB"])
    monkeypatch.setattr(md, "get_us_sector_holdings", lambda: {})
    monkeypatch.setattr(md, "build_sector_mapping",
                         lambda h, market: {"AAA": "XLK", "BBB": "XLY"})

    proj = str(tmp_path)
    os.makedirs(os.path.join(proj, "history"), exist_ok=True)
    result = msc.scan_momentum_us(proj)

    assert result["status"] == "ok"
    assert "EM" in result["signals"]
    assert isinstance(result["rotation_radar"], list)
    # History was saved with schema_version 2
    hist_path = os.path.join(proj, "history", "scanner_momentum_us_history.json")
    assert os.path.exists(hist_path)
    with open(hist_path, encoding="utf-8") as f:
        hist = json.load(f)
    assert hist["_meta"]["schema_version"] == 2
    assert hist["_meta"]["version"] == "Momentum v1.5"
```

- [ ] **Step 2: Run test**

```bash
python -m pytest tests/test_e2e_emerging_smoke.py -v
```
Expected: PASS.

- [ ] **Step 3: Run the full momentum test suite**

```bash
python -m pytest tests/test_momentum_*.py tests/test_emerging_momentum_golden.py tests/test_e2e_emerging_smoke.py -v
```
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_emerging_smoke.py
git commit -m "$(cat <<'EOF'
test(momentum): E2E smoke for v1.5 — EM bucket + rotation radar + schema v2

Mocked yfinance bulk fetch; verifies scan_momentum_us emits EM signals,
rotation_radar list, and writes history with schema_version=2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: Detail page — Maturity line in CURRENT STATUS

**Files:**
- Modify: `templates/detail_template.html:294-307` (CURRENT STATUS block)
- Test: `tests/test_momentum_detail.py` (existing)

- [ ] **Step 1: Write failing test**

Append to `tests/test_momentum_detail.py`:
```python
def test_detail_template_renders_maturity_line():
    """CURRENT STATUS block shows Maturity + dist_ema9 when present in last entry."""
    import jinja2
    env = jinja2.Environment(loader=jinja2.FileSystemLoader("templates"), autoescape=True)
    tmpl = env.get_template("detail_template.html")
    momentum_data = {
        "last": {
            "stage": "EM", "time_in_stage": 3,
            "entry_price": 22.0, "price": 23.5,
            "maturity": "EARLY", "dist_ema9_pct": 1.8, "rsi": 64.0,
            "risk_tags": [],
        },
        "recent": [],
    }
    # Minimal context — feed only what the test exercises.
    html = tmpl.render(
        ticker="PLTR", name="Palantir", chart_path="charts/PLTR.png",
        is_kospi=False, signals=[], indicators={},
        momentum_data=momentum_data,
    )
    assert "Maturity" in html
    assert "EARLY" in html
    assert "1.8" in html  # dist_ema9 shown


def test_detail_template_omits_maturity_when_missing():
    """If maturity field absent (legacy entry), block doesn't crash."""
    import jinja2
    env = jinja2.Environment(loader=jinja2.FileSystemLoader("templates"), autoescape=True)
    tmpl = env.get_template("detail_template.html")
    momentum_data = {
        "last": {
            "stage": "MOMENTUM_1", "time_in_stage": 1,
            "entry_price": 100.0, "price": 102.0, "risk_tags": [],
            # no maturity / no dist_ema9_pct
        },
        "recent": [],
    }
    html = tmpl.render(
        ticker="X", name="X", chart_path="charts/X.png",
        is_kospi=False, signals=[], indicators={},
        momentum_data=momentum_data,
    )
    # No exception, page renders. Maturity line is conditional.
    assert "MOMENTUM_1" in html
```

- [ ] **Step 2: Run test to verify failure**

```bash
python -m pytest tests/test_momentum_detail.py -v -k maturity
```
Expected: FAIL.

- [ ] **Step 3: Modify CURRENT STATUS block in `templates/detail_template.html`**

Locate lines 296-300 (the `<p style="margin-bottom:0.8em;">` containing Stage/Entry/Now). After that paragraph closes (`</p>` on line 300), and before the existing `{% if md.last.risk_tags %}` block, insert:

```html
    {% if md.last.maturity %}
    <p style="margin-bottom:0.8em;">
      <strong>Maturity:</strong>
      <span class="maturity-{{ md.last.maturity|lower }}">{{ md.last.maturity }}</span>
      {% if md.last.dist_ema9_pct is not none %}
        (dist_ema9 {% if md.last.dist_ema9_pct >= 0 %}+{% endif %}{{ "%.1f"|format(md.last.dist_ema9_pct) }}%, RSI {{ "%.1f"|format(md.last.rsi or 0) }})
      {% endif %}
    </p>
    {% endif %}
```

If `detail_template.html` does not already have `.maturity-early/.maturity-mid/.maturity-extended` CSS classes in its `<style>` block, add them (search for an existing class definition like `.M3` and add nearby):
```css
.maturity-early    { color: #22c55e; font-weight: bold; }
.maturity-mid      { color: #eab308; }
.maturity-extended { color: #ef4444; font-weight: bold; }
```

- [ ] **Step 4: Run test to verify pass**

```bash
python -m pytest tests/test_momentum_detail.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/detail_template.html tests/test_momentum_detail.py
git commit -m "$(cat <<'EOF'
feat(detail): add Maturity line to CURRENT STATUS block

Shows 🟢/🟡/🔴 Maturity + dist_ema9 + RSI when last momentum entry has
the maturity field (v1.5+). Legacy entries without the field render normally.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Done — Summary

After all 16 tasks, the branch contains:

| Layer | Change |
|---|---|
| Data | EMA9/21/65 globally available via `fetch_market_data.py` + `momentum_data.compute_ema_fields` shared helper |
| Signal | `classify_maturity` (EARLY/MID/EXTENDED), `classify_em` (Full-IWB Structural Inflection), `classify_tier` (M+ over EM precedence). Risk Tags trimmed to OVERHEAT/PARABOLIC. `position_hint` 2-axis. |
| History | `RANK[EM]=0`, `maturity`/`sector_top_rank`/`dist_ema9_pct`/`ret_20d_pct` in entries, schema_version 2, legacy tag filter on read |
| Backtest | EM in `by_stage` aggregation, new `transition_to_M1_pct` KPI |
| Scanner | Two-track orchestration: M+ (top-sector + prefilter) and EM (full-universe `classify_em`). Sector annotation + rotation radar. Streak/change enrichment on rendered signals. `MOMENTUM_DISABLE_EM=1` rollback toggle. |
| UI | Two sections (Leaders / Emerging), Sector Rotation Radar, Tier/Maturity/Streak/dist_ema9 columns, Maturity color coding. Detail page Maturity line. |
| Telegram | EM list + rotation line + EM transition KPI |
| Tests | Augmented (config/signal/history/backtest/scanner/templates) + 3 new (golden, telegram, e2e) |
| Docs | CLAUDE.md plan bullet |

No new modules. No new package dependencies. Backwards-compatible with v1.0 history files (filter on read; bump on save).
