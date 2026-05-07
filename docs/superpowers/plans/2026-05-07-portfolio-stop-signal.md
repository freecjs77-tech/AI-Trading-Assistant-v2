# Portfolio Stop Signal System v1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 매일 me + wife 포트폴리오의 모든 보유 종목에 대해 종가 기준 trailing stop signal(HOLD/TIGHT/EXIT_READY/EXIT)을 자동 산출하고, 전용 페이지·기존 portfolio 페이지·Telegram 합산 알림으로 노출한다 (자동매매 ❌ / 매도 판단 보조 ✅).

**Architecture:** 단방향 의존 모듈 4개 (config → history → signal → report) + Jinja2 템플릿 1개. 기존 파이프라인 Step 4c3로 독립 삽입 (실패 격리). Market-derived 데이터(`atr14`)는 `fetch_market_data.py` 확장, position state(`highest_close`, `below_stop_count`)는 `portfolio_stops.json` 자체 관리. 4-state machine + display layer downgrade로 신규 진입 종목 노이즈 흡수.

**Tech Stack:** Python 3.10+, pandas, numpy, yfinance, Jinja2, pytest. 신규 패키지 없음.

**Spec 참조:** [`docs/superpowers/specs/2026-05-07-portfolio-stop-signal-design.md`](../specs/2026-05-07-portfolio-stop-signal-design.md)

---

## File Structure

### 신규 파일 (5개 + tests + 런타임 JSON)

| 파일 | 책임 |
|---|---|
| `portfolio_stop_config.py` | 모든 상수 (mode 매핑, override, keyword, multiplier, min/max%, 그레이스 일수, Telegram 한계 등) — 단일 진입점 |
| `portfolio_stop_history.py` | `portfolio_stops.json` I/O + bootstrap (yfinance YTD fetch on first run) + soft-archive(3일 grace) + `update_highest_close_safe` |
| `portfolio_stop_signal.py` | Stop 계산(`calculate_stop`) + 4-state 평가(`evaluate_signal` raw/display 분리) + entry point `generate_portfolio_stop_signals()` |
| `portfolio_stop_report.py` | `generate_portfolio_stop_page()` — Jinja2 렌더링 |
| `templates/portfolio_stops.html` | Hero / Summary Cards / Signal Changes / Main Table / Footer |
| `tests/test_portfolio_stop_config.py` | 상수/매핑 테스트 |
| `tests/test_portfolio_stop_history.py` | bootstrap / soft-archive / highest_close 갱신 테스트 |
| `tests/test_portfolio_stop_signal.py` | calculate_stop / evaluate_signal / state transitions / golden sample |

### 수정 파일 (5개)

| 파일 | 변경점 |
|---|---|
| `fetch_market_data.py` | `atr14`, `atr14_pct` 필드 추가 (NaN/Zero 안전장치) |
| `pipeline.py` | Step 4c3 (me) 삽입 + Step 5d secondary owner loop에 wife stop 통합 + Telegram 호출 |
| `report_generator.py` | `generate_report()`에 `portfolio_stop_result` 인자 + holdings에 `stop_*` 필드 주입 |
| `telegram_sender.py` | `send_portfolio_risk_summary(stop_me, stop_wife, base_url, date_str)` 추가 |
| `templates/report_template.html` | nav `🛡 Portfolio Risk` 링크 + holdings 테이블 Stop Signal 컬럼 |

### 신규 런타임 데이터

```
history/portfolio_stops.json           # me — Step 4c3 첫 실행 시 자동 생성
history/portfolio_stops_wife.json      # wife — Step 5d 처음 도달 시 자동 생성
reports/portfolio_stops_<DATE>.html         # me 페이지 — 일별
reports/portfolio_stops_wife_<DATE>.html    # wife 페이지 — 일별
```

### Workflow 수정

| 파일 | 변경점 |
|---|---|
| `.github/workflows/daily-report.yml` | 워크플로우 시작 시 `history/portfolio_stops*.json` 복원 패턴 추가 |
| `CLAUDE.md` | "진행 중인 계획" 섹션에 본 plan 등재 |

---

## Pre-requisites

- [ ] **Verify clean working tree**

```bash
git status -sb
# Expected: ## master...origin/master  (clean)
```

- [ ] **Create feature branch (or worktree)**

Option A — branch only:
```bash
git checkout -b feature/portfolio-stop-signal
```

Option B — isolated worktree (recommended):
```bash
git worktree add .worktrees/portfolio-stop-signal -b feature/portfolio-stop-signal
cd .worktrees/portfolio-stop-signal
```

- [ ] **Verify pytest works on existing tests**

```bash
pytest tests/test_portfolio_history_core.py -q
# Expected: PASS (used as smoke test for the test infra)
```

---

## Phase 1: Foundation — Market Data Extension

### Task 1: `fetch_market_data.py`에 `atr14`/`atr14_pct` 필드 추가

이 작업은 **소비자가 없는 단독 변경**으로, 첫 커밋이 안전하게 완료될 수 있도록 의도적으로 분리.

**Files:**
- Modify: `fetch_market_data.py:150-170` (calc_adx 근처) + `fetch_market_data.py:418-468` (출력 dict)

- [ ] **Step 1: Locate `calc_adx` and inspect TR computation**

Read `fetch_market_data.py` 라인 150-170. `calc_adx()`는 이미 `tr = pd.concat([...]).max(axis=1)` + `atr = tr.ewm(...).mean()`을 내부 계산 중. 이걸 별도 함수로 분리할 필요는 없음 — 새 `calc_atr` 헬퍼만 추가.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_fetch_market_data_atr.py
"""fetch_market_data.calc_atr smoke test (no yfinance call)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import numpy as np
from fetch_market_data import calc_atr


def test_calc_atr_basic():
    """간단한 OHLC로 ATR 14 계산 — 양수, 마지막 값 not NaN."""
    n = 30
    high = pd.Series([100 + i + (i % 3) for i in range(n)], dtype=float)
    low  = pd.Series([99  + i - (i % 3) for i in range(n)], dtype=float)
    close= pd.Series([100 + i           for i in range(n)], dtype=float)
    atr = calc_atr(high, low, close, period=14)
    last = float(atr.iloc[-1])
    assert last > 0
    assert not np.isnan(last)


def test_calc_atr_short_series_nan_safe():
    """기간보다 짧은 시리즈 — 마지막 값 NaN이어도 raise 없어야 함."""
    high = pd.Series([100, 101, 102], dtype=float)
    low  = pd.Series([99, 100, 101], dtype=float)
    close= pd.Series([100, 101, 102], dtype=float)
    atr = calc_atr(high, low, close, period=14)
    # 14일치 미만이면 마지막 값 NaN — 호출은 성공해야
    assert len(atr) == 3


if __name__ == "__main__":
    test_calc_atr_basic()
    test_calc_atr_short_series_nan_safe()
    print("[OK] calc_atr tests passed.")
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest tests/test_fetch_market_data_atr.py -v
# Expected: ImportError: cannot import name 'calc_atr' from 'fetch_market_data'
```

- [ ] **Step 4: Add `calc_atr` helper to `fetch_market_data.py`**

`calc_adx` 함수 **바로 위**(약 라인 150)에 추가:

```python
def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range (ATR) — Wilder smoothing (EWM with com=period-1).

    True Range = max(H-L, |H-Cprev|, |L-Cprev|)
    """
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_fetch_market_data_atr.py -v
# Expected: 2 passed
```

- [ ] **Step 6: Add `atr14`/`atr14_pct` to per-ticker output dict**

`fetch_market_data.py`에서 `def fetch_indicator_for(ticker, ...)` 내부 — `adx = calc_adx(...)` 라인 다음에 추가, 그리고 출력 dict에 두 필드 삽입:

지표 계산부 (대략 line 380 근처, `adx = calc_adx(high, low, close)` 직후):
```python
        atr14_series = calc_atr(high, low, close, period=14)
        atr14_val = (
            float(atr14_series.iloc[-1])
            if len(atr14_series) > 0
            and not pd.isna(atr14_series.iloc[-1])
            and np.isfinite(atr14_series.iloc[-1])
            else None
        )
```

출력 dict (line ~444 근처, `"adx": safe(adx),` 다음):
```python
            # ATR — trailing stop 시스템에서 사용
            "atr14":     round(atr14_val, 4) if atr14_val is not None else None,
            "atr14_pct": round((atr14_val / last_close) * 100, 2)
                         if atr14_val is not None and last_close > 0
                         else None,
```

- [ ] **Step 7: Smoke test — fetch one ticker locally**

```bash
python fetch_market_data.py NVDA --output /tmp/test_atr.json
# Expected: success — file written
python -c "import json; d=json.load(open('/tmp/test_atr.json')); print(d['data']['NVDA'].get('atr14'), d['data']['NVDA'].get('atr14_pct'))"
# Expected: numeric values like (15.2341, 1.65)
```

- [ ] **Step 8: Commit**

```bash
git add fetch_market_data.py tests/test_fetch_market_data_atr.py
git commit -m "$(cat <<'EOF'
feat(fetch): add atr14 and atr14_pct fields per ticker

Adds Wilder-smoothed ATR(14) absolute value and percentage of last
close to per-ticker output dict. Used by upcoming portfolio stop
signal system (Step 4c3). NaN/zero safe — returns None for short
series or zero-price anomalies.

Existing signal_judge.py and other consumers do not read these
fields — no behavioral change.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2: Configuration

### Task 2: `portfolio_stop_config.py` — 상수 단일 진입점

**Files:**
- Create: `portfolio_stop_config.py`
- Test: `tests/test_portfolio_stop_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_portfolio_stop_config.py
"""portfolio_stop_config 상수 정합성 테스트."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import portfolio_stop_config as cfg


def test_version_and_anchor():
    assert cfg.VERSION == "PortfolioStop v1.0"
    assert cfg.ANCHOR_DATE == "2026-01-02"


def test_modes_complete():
    """STOP_PARAMS는 4개 모드 모두 정의되어야."""
    for mode in ("CORE", "DEFENSIVE", "MOMENTUM", "HIGH_VOL"):
        assert mode in cfg.STOP_PARAMS


def test_pct_modes_no_atr_keys():
    """CORE/DEFENSIVE는 type='pct' + ratio 정의."""
    for mode in ("CORE", "DEFENSIVE"):
        p = cfg.STOP_PARAMS[mode]
        assert p["type"] == "pct"
        assert 0.85 <= p["ratio"] <= 0.95


def test_atr_modes_have_clamps():
    """MOMENTUM/HIGH_VOL은 multiplier + min_pct + max_pct 모두 정의."""
    for mode in ("MOMENTUM", "HIGH_VOL"):
        p = cfg.STOP_PARAMS[mode]
        assert p["type"] == "atr"
        assert p["multiplier"] >= 1
        assert 0 < p["min_pct"] < p["max_pct"] <= 0.5


def test_high_vol_stricter_than_momentum():
    """HIGH_VOL은 MOMENTUM보다 stop이 멀어야 (변동성 큼)."""
    m = cfg.STOP_PARAMS["MOMENTUM"]
    h = cfg.STOP_PARAMS["HIGH_VOL"]
    assert h["multiplier"] > m["multiplier"]
    assert h["min_pct"] > m["min_pct"]
    assert h["max_pct"] > m["max_pct"]


def test_category_to_mode_complete():
    """포트폴리오에 등장할 수 있는 모든 카테고리 매핑."""
    expected = {"ETF Core", "Bond", "Value/Dividend", "Growth",
                "KOSPI Stock", "KOSPI ETF", "Speculative", "Metal", "Other"}
    assert expected.issubset(set(cfg.CATEGORY_TO_MODE.keys()))


def test_kospi_etf_default_momentum():
    """KOSPI ETF 기본은 MOMENTUM. broad는 OVERRIDES로 CORE 승격."""
    assert cfg.CATEGORY_TO_MODE["KOSPI ETF"] == "MOMENTUM"


def test_overrides_broad_kr_etfs():
    for tk in ("102110", "458730", "379800", "379810"):
        assert cfg.MODE_OVERRIDES.get(tk) == "CORE", f"{tk} should be CORE"


def test_overrides_high_vol_individual():
    for tk in ("110990", "QLD", "ETHU", "SOXX", "IONQ", "CRCL"):
        assert cfg.MODE_OVERRIDES.get(tk) == "HIGH_VOL", f"{tk} should be HIGH_VOL"


def test_high_vol_keywords():
    assert "반도체" in cfg.HIGH_VOL_KEYWORDS
    assert "코스닥" in cfg.HIGH_VOL_KEYWORDS
    assert "조선" in cfg.HIGH_VOL_KEYWORDS
    assert "레버리지" in cfg.HIGH_VOL_KEYWORDS


def test_archive_grace_three_days():
    assert cfg.ARCHIVE_AFTER_DAYS_MISSING == 3


def test_max_daily_jump_pct():
    """40% 단일일 점프는 의심 (분할/bad tick 등)."""
    assert 0.30 <= cfg.MAX_DAILY_JUMP_PCT <= 0.50


def test_new_position_noise_calendar_days():
    """v1은 calendar days 기준."""
    assert cfg.NEW_POSITION_NOISE_DAYS == 14
    assert cfg.NEW_POSITION_DISPLAY_DOWNGRADE is True


def test_telegram_limits_descending():
    """심각도 높을수록 적게 (EXIT는 더 알리고 디테일 길어지므로 제한)."""
    assert cfg.TELEGRAM_MAX_EXIT_ITEMS <= cfg.TELEGRAM_MAX_EXIT_READY_ITEMS
    assert cfg.TELEGRAM_MAX_EXIT_READY_ITEMS <= cfg.TELEGRAM_MAX_TIGHT_ITEMS


def test_snapshot_retention_two_years():
    assert cfg.MAX_SNAPSHOT_DAYS == 730


if __name__ == "__main__":
    test_version_and_anchor()
    test_modes_complete()
    test_pct_modes_no_atr_keys()
    test_atr_modes_have_clamps()
    test_high_vol_stricter_than_momentum()
    test_category_to_mode_complete()
    test_kospi_etf_default_momentum()
    test_overrides_broad_kr_etfs()
    test_overrides_high_vol_individual()
    test_high_vol_keywords()
    test_archive_grace_three_days()
    test_max_daily_jump_pct()
    test_new_position_noise_calendar_days()
    test_telegram_limits_descending()
    test_snapshot_retention_two_years()
    print("[OK] portfolio_stop_config tests passed.")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_portfolio_stop_config.py -v
# Expected: ImportError: No module named 'portfolio_stop_config'
```

- [ ] **Step 3: Create `portfolio_stop_config.py`**

```python
# portfolio_stop_config.py
"""
Portfolio Stop Signal — 상수 단일 진입점.

모든 mode/임계값/그레이스/한계는 여기서만 정의. 추후 튜닝 시 한 곳에서만 변경.
"""

VERSION = "PortfolioStop v1.0"

# YTD 앵커 — 첫 실행 시 모든 종목 highest_close 계산 시작점
ANCHOR_DATE = "2026-01-02"

# ── Mode 매핑 ──────────────────────────────────────────────
DEFAULT_MODE = "MOMENTUM"

CATEGORY_TO_MODE = {
    "ETF Core":        "CORE",
    "Bond":            "DEFENSIVE",
    "Value/Dividend":  "CORE",
    "Growth":          "MOMENTUM",
    "KOSPI Stock":     "MOMENTUM",
    "KOSPI ETF":       "MOMENTUM",   # broad ETF만 OVERRIDES로 CORE 승격
    "Speculative":     "HIGH_VOL",
    "Metal":           "HIGH_VOL",
    "Other":           "MOMENTUM",
}

# 종목명에 포함되면 HIGH_VOL 자동 승격 (테마/레버리지 자동 대응)
HIGH_VOL_KEYWORDS = [
    "반도체", "코스닥", "조선", "레버리지", "2X", "AI", "로봇", "양자",
]

# Explicit overrides (categry/keyword 룰을 깨고 싶은 종목만)
MODE_OVERRIDES = {
    # KR broad ETFs → CORE (KOSPI ETF 기본 MOMENTUM 깨고 CORE)
    "102110": "CORE",   # TIGER 200
    "458730": "CORE",   # TIGER 미국배당다우존스
    "379800": "CORE",   # KODEX 미국S&P500
    "379810": "CORE",   # KODEX 미국나스닥100
    # Individual overrides
    "110990": "HIGH_VOL",   # 디아이티 (소형주 변동성)
    "QLD":    "HIGH_VOL",   # 2x 레버리지
    "ETHU":   "HIGH_VOL",   # crypto leverage
    "SOXX":   "HIGH_VOL",   # 섹터 ETF
    "IONQ":   "HIGH_VOL",   # 양자컴 변동성
    "CRCL":   "HIGH_VOL",   # 신규 IPO 변동성
}

# ── Stop 계산 파라미터 ──────────────────────────────────────
# pct: 단순 percentage stop (CORE/DEFENSIVE)
# atr: ATR 기반 + min/max% 양방향 clamp (MOMENTUM/HIGH_VOL)
STOP_PARAMS = {
    "CORE":      {"type": "pct",  "ratio": 0.88, "min_pct": None, "max_pct": None},  # 12%
    "DEFENSIVE": {"type": "pct",  "ratio": 0.92, "min_pct": None, "max_pct": None},  # 8%
    "MOMENTUM":  {"type": "atr",  "multiplier": 3, "min_pct": 0.08, "max_pct": 0.20},
    "HIGH_VOL":  {"type": "atr",  "multiplier": 4, "min_pct": 0.12, "max_pct": 0.30},
}

# ── 시그널 임계값 ───────────────────────────────────────────
TIGHT_RATIO = 1.05   # close <= stop * 1.05 → TIGHT
EXIT_BELOW_STOP_DAYS = 2   # below_stop_count >= 2 → EXIT (이전은 EXIT_READY)

# ── 매도 감지 / 라이프사이클 ───────────────────────────────
ARCHIVE_AFTER_DAYS_MISSING = 3   # 1일 race condition 흡수 (Actions 동시성/fetch 실패)

# Highest close 업데이트 가드 — 데이터 이상치(분할/bad tick/환율) 방어
MAX_DAILY_JUMP_PCT = 0.40        # today_close > prev_close × 1.40 → 갱신 스킵 + WARN

# 신규 진입 종목 처리
NEW_POSITION_NOISE_DAYS = 14     # **calendar days** (≈ 10 trading days)
                                 # (today - entry_date).days 기준
NEW_POSITION_DISPLAY_DOWNGRADE = True  # 신규 종목의 EXIT_READY/EXIT는 display만 TIGHT로

# Snapshot 보존 (영구 보존하되 운영적 cap)
MAX_SNAPSHOT_DAYS = 730          # 2년 rolling

# ── Telegram 표시 한계 ──────────────────────────────────────
TELEGRAM_MAX_EXIT_ITEMS       = 5
TELEGRAM_MAX_EXIT_READY_ITEMS = 7
TELEGRAM_MAX_TIGHT_ITEMS      = 12

# ── Bootstrap (yfinance YTD fetch) ─────────────────────────
BOOTSTRAP_TIMEOUT_SEC = 600      # 첫 실행 yfinance bulk fetch 최대 시간
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_portfolio_stop_config.py -v
# Expected: 14 passed
```

- [ ] **Step 5: Commit**

```bash
git add portfolio_stop_config.py tests/test_portfolio_stop_config.py
git commit -m "$(cat <<'EOF'
feat(stop): add portfolio_stop_config.py with all constants

Single entry point for mode mappings (category/keyword/override),
stop parameters (CORE/DEFENSIVE/MOMENTUM/HIGH_VOL with min/max%
clamps), grace days, calendar-day noise window, telegram limits,
and snapshot retention.

Constants encode all design decisions from
docs/superpowers/specs/2026-05-07-portfolio-stop-signal-design.md.

No code consumers yet — pure data module.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3: State Management — `portfolio_stop_history.py`

### Task 3: `portfolio_stop_history.py` — load/save + bootstrap + soft-archive

이 모듈이 가장 복잡. 4개 책임:
1. JSON I/O (positions + snapshots 분리)
2. 첫 실행 bootstrap (yfinance bulk fetch YTD high)
3. 일상 incremental 갱신 + 안전 가드
4. 매도 감지 (3일 grace + missing_since)

**Files:**
- Create: `portfolio_stop_history.py`
- Test: `tests/test_portfolio_stop_history.py`

- [ ] **Step 1: Write failing tests (load/save round-trip)**

```python
# tests/test_portfolio_stop_history.py
"""portfolio_stop_history 라이프사이클 테스트."""
import sys, os, json, tempfile
from datetime import date, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import portfolio_stop_history as ph
from portfolio_stop_history import (
    load_stop_history, save_stop_history,
    update_highest_close_safe, evaluate_lifecycle,
    new_empty_state, get_position,
)


def _tmp_path():
    return os.path.join(tempfile.gettempdir(), f"stops_test_{os.getpid()}.json")


def test_load_returns_empty_when_missing():
    path = _tmp_path()
    if os.path.exists(path):
        os.remove(path)
    state = load_stop_history(path)
    assert state["_meta"]["schema_version"] == 1
    assert state["positions"] == {}
    assert state["snapshots"] == {}


def test_save_load_roundtrip():
    path = _tmp_path()
    state = new_empty_state(owner="me")
    state["positions"]["NVDA"] = {
        "status": "active", "mode": "MOMENTUM",
        "entry_date": "2026-01-02",
        "highest_close": 945.0, "highest_close_date": "2026-05-05",
        "current_stop": 874.0, "below_stop_count": 0,
        "shares": 50.0, "last_size_change": "2026-04-17",
        "missing_since": None, "last_signal": "HOLD",
        "last_action": "Hold", "last_evaluated": "2026-05-07",
    }
    save_stop_history(state, path)
    loaded = load_stop_history(path)
    assert loaded["positions"]["NVDA"]["highest_close"] == 945.0
    assert loaded["positions"]["NVDA"]["below_stop_count"] == 0
    os.remove(path)


def test_update_highest_close_basic_increment():
    pos = {"highest_close": 100.0, "highest_close_date": "2026-01-15", "ticker": "T"}
    update_highest_close_safe(pos, today_close=105.0, prev_close=104.0,
                              today_str="2026-02-01")
    assert pos["highest_close"] == 105.0
    assert pos["highest_close_date"] == "2026-02-01"


def test_update_highest_close_no_change_below():
    pos = {"highest_close": 100.0, "highest_close_date": "2026-01-15", "ticker": "T"}
    update_highest_close_safe(pos, today_close=95.0, prev_close=96.0,
                              today_str="2026-02-01")
    assert pos["highest_close"] == 100.0   # unchanged
    assert pos["highest_close_date"] == "2026-01-15"


def test_update_highest_close_jump_guard_skipped():
    """40% 초과 단일일 점프 → highest 갱신 스킵."""
    pos = {"highest_close": 100.0, "highest_close_date": "2026-01-15", "ticker": "T"}
    # prev=100, today=145 → +45% jump → 가드 발동
    update_highest_close_safe(pos, today_close=145.0, prev_close=100.0,
                              today_str="2026-02-01")
    assert pos["highest_close"] == 100.0   # unchanged due to guard


def test_update_highest_close_normal_jump_within_threshold():
    """30% 점프는 의심스럽지만 정상 범위 (earnings 등)."""
    pos = {"highest_close": 100.0, "highest_close_date": "2026-01-15", "ticker": "T"}
    update_highest_close_safe(pos, today_close=130.0, prev_close=100.0,
                              today_str="2026-02-01")
    assert pos["highest_close"] == 130.0


def test_evaluate_lifecycle_new_position_first_seen():
    """기존 stops에 없는 ticker → 신규 등록 (entry_date=today)."""
    state = new_empty_state(owner="me")
    evaluate_lifecycle(
        state, portfolio_tickers={"NVDA"}, today_str="2026-05-07",
        new_position_seed={"NVDA": {"close": 920.0, "shares": 50.0,
                                     "mode": "MOMENTUM"}},
    )
    pos = state["positions"]["NVDA"]
    assert pos["status"] == "active"
    assert pos["entry_date"] == "2026-05-07"
    assert pos["highest_close"] == 920.0
    assert pos["highest_close_date"] == "2026-05-07"


def test_evaluate_lifecycle_missing_grace_3days():
    """3일 부재 시에만 archive — 1일/2일은 active 유지."""
    state = new_empty_state(owner="me")
    state["positions"]["NVDA"] = {
        "status": "active", "mode": "MOMENTUM",
        "entry_date": "2026-01-02", "highest_close": 1.0,
        "missing_since": None, "shares": 50.0,
    }
    # Day 1 missing
    evaluate_lifecycle(state, portfolio_tickers=set(), today_str="2026-05-08",
                       new_position_seed={})
    assert state["positions"]["NVDA"]["status"] == "active"
    assert state["positions"]["NVDA"]["missing_since"] == "2026-05-08"
    # Day 2 missing
    evaluate_lifecycle(state, portfolio_tickers=set(), today_str="2026-05-09",
                       new_position_seed={})
    assert state["positions"]["NVDA"]["status"] == "active"
    # Day 3 missing
    evaluate_lifecycle(state, portfolio_tickers=set(), today_str="2026-05-10",
                       new_position_seed={})
    assert state["positions"]["NVDA"]["status"] == "closed"
    assert state["positions"]["NVDA"]["closed_date"] == "2026-05-10"


def test_evaluate_lifecycle_missing_recover_resets_counter():
    """1일 부재 후 재등장하면 missing_since 리셋."""
    state = new_empty_state(owner="me")
    state["positions"]["NVDA"] = {
        "status": "active", "mode": "MOMENTUM",
        "entry_date": "2026-01-02", "highest_close": 1.0,
        "missing_since": None, "shares": 50.0,
    }
    evaluate_lifecycle(state, portfolio_tickers=set(), today_str="2026-05-08",
                       new_position_seed={})
    assert state["positions"]["NVDA"]["missing_since"] == "2026-05-08"
    # Re-appears next day
    evaluate_lifecycle(state, portfolio_tickers={"NVDA"}, today_str="2026-05-09",
                       new_position_seed={})
    assert state["positions"]["NVDA"]["status"] == "active"
    assert state["positions"]["NVDA"]["missing_since"] is None


def test_evaluate_lifecycle_reopen_after_archive():
    """Archived 종목이 다시 portfolio에 등장 → fresh bootstrap."""
    state = new_empty_state(owner="me")
    state["positions"]["TSLA"] = {
        "status": "closed", "mode": "MOMENTUM",
        "entry_date": "2026-01-02", "highest_close": 410.0,
        "highest_close_date": "2026-02-15",
        "closed_date": "2026-04-30", "shares": 0.0,
    }
    evaluate_lifecycle(
        state, portfolio_tickers={"TSLA"}, today_str="2026-05-15",
        new_position_seed={"TSLA": {"close": 250.0, "shares": 30.0,
                                     "mode": "MOMENTUM"}},
    )
    pos = state["positions"]["TSLA"]
    assert pos["status"] == "active"
    assert pos["entry_date"] == "2026-05-15"  # fresh anchor
    assert pos["highest_close"] == 250.0       # reset to today
    assert pos.get("closed_date") is None or pos.get("reopened_date") == "2026-05-15"


if __name__ == "__main__":
    test_load_returns_empty_when_missing()
    test_save_load_roundtrip()
    test_update_highest_close_basic_increment()
    test_update_highest_close_no_change_below()
    test_update_highest_close_jump_guard_skipped()
    test_update_highest_close_normal_jump_within_threshold()
    test_evaluate_lifecycle_new_position_first_seen()
    test_evaluate_lifecycle_missing_grace_3days()
    test_evaluate_lifecycle_missing_recover_resets_counter()
    test_evaluate_lifecycle_reopen_after_archive()
    print("[OK] portfolio_stop_history tests passed.")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_portfolio_stop_history.py -v
# Expected: ImportError: No module named 'portfolio_stop_history'
```

- [ ] **Step 3: Create `portfolio_stop_history.py`**

```python
# portfolio_stop_history.py
"""
Portfolio Stop Signal — Position state I/O + lifecycle.

책임:
1. portfolio_stops.json load/save (positions + snapshots 분리)
2. 첫 실행 bootstrap — yfinance YTD high fetch
3. 일상 incremental update (highest_close 안전 갱신)
4. Lifecycle 관리 (신규 등장 / 매도 감지 grace / 재매수)

Market data vs Position state 분리 원칙:
- ATR 등 시장 데이터는 fetch_market_data.py
- highest_close 등 포지션 state는 이 모듈
"""

import os
import json
from datetime import date, datetime, timedelta

from portfolio_stop_config import (
    VERSION, ANCHOR_DATE, MAX_DAILY_JUMP_PCT,
    ARCHIVE_AFTER_DAYS_MISSING, MAX_SNAPSHOT_DAYS,
)


# ─── JSON I/O ──────────────────────────────────────────────

def new_empty_state(owner: str) -> dict:
    """비어 있는 portfolio_stops 구조."""
    return {
        "_meta": {
            "schema_version": 1,
            "version": VERSION,
            "owner": owner,
            "anchor_date": ANCHOR_DATE,
            "last_updated": None,
        },
        "positions": {},
        "snapshots": {},
    }


def load_stop_history(path: str, owner: str = "me") -> dict:
    """파일이 없으면 빈 state, 있으면 로드."""
    if not os.path.exists(path):
        return new_empty_state(owner)
    try:
        with open(path, "rb") as f:
            raw = f.read()
        return json.loads(raw.rstrip(b" \t\n\r\x00").decode("utf-8"))
    except Exception as e:
        print(f"[stop_history] WARN load failed ({e}) — using empty state")
        return new_empty_state(owner)


def save_stop_history(state: dict, path: str) -> None:
    """원자적 저장 (임시 파일 → rename)."""
    state["_meta"]["last_updated"] = date.today().strftime("%Y-%m-%d")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def get_position(state: dict, ticker: str) -> dict | None:
    return state.get("positions", {}).get(ticker)


# ─── Highest close 안전 갱신 ─────────────────────────────────

def update_highest_close_safe(pos: dict, today_close: float,
                              prev_close: float | None,
                              today_str: str) -> bool:
    """비정상 점프(분할/bad tick) 방어. 갱신 시 True 반환."""
    if today_close is None or today_close <= 0:
        return False
    # Guard: 단일일 +40% 초과 → 의심
    if prev_close and prev_close > 0:
        jump_ratio = today_close / prev_close
        if jump_ratio > (1.0 + MAX_DAILY_JUMP_PCT):
            print(
                f"[stop_history] WARN {pos.get('ticker', '?')}: "
                f"suspicious jump prev={prev_close:.4f} → today={today_close:.4f} "
                f"({(jump_ratio - 1) * 100:.1f}%/1d) — skip highest update"
            )
            return False
    if today_close > pos.get("highest_close", 0):
        pos["highest_close"] = today_close
        pos["highest_close_date"] = today_str
        return True
    return False


# ─── Lifecycle (신규/유지/누락/매도/재매수) ──────────────────

def _days_diff(d1: str, d2: str) -> int:
    """d1 - d2 (calendar days)."""
    a = datetime.strptime(d1, "%Y-%m-%d").date()
    b = datetime.strptime(d2, "%Y-%m-%d").date()
    return (a - b).days


def evaluate_lifecycle(state: dict, portfolio_tickers: set,
                       today_str: str,
                       new_position_seed: dict | None = None) -> None:
    """매일 실행: positions 키와 portfolio_tickers를 비교해 라이프사이클 진행.

    - portfolio에 있으나 stops에 없음 → 신규 등록 (today anchor)
    - portfolio에 있으나 stops엔 closed → 재매수 (fresh bootstrap, today anchor)
    - portfolio에 있고 stops에 active → missing_since 리셋
    - portfolio에 없으나 stops엔 active → missing_since++; 3일 grace 후 closed
    - 이미 closed → 그대로

    new_position_seed: {ticker: {"close": float, "shares": float, "mode": str}}
        신규/재매수 시 시작값. mode는 호출자가 미리 결정 (config.get_stop_mode 활용).
    """
    new_position_seed = new_position_seed or {}
    positions = state.setdefault("positions", {})

    # 1. portfolio 종목 처리
    for tk in portfolio_tickers:
        pos = positions.get(tk)
        seed = new_position_seed.get(tk, {})
        if pos is None:
            # 첫 등장 — 신규 종목
            positions[tk] = {
                "status": "active",
                "mode": seed.get("mode", "MOMENTUM"),
                "entry_date": today_str,
                "highest_close": float(seed.get("close", 0.0)),
                "highest_close_date": today_str,
                "current_stop": None,
                "below_stop_count": 0,
                "shares": float(seed.get("shares", 0.0)),
                "last_size_change": today_str,
                "missing_since": None,
                "last_signal": None,
                "last_action": None,
                "last_evaluated": None,
            }
            continue
        if pos.get("status") == "closed":
            # 재매수 — fresh bootstrap
            pos["status"] = "active"
            pos["entry_date"] = today_str
            pos["highest_close"] = float(seed.get("close", pos.get("highest_close", 0.0)))
            pos["highest_close_date"] = today_str
            pos["current_stop"] = None
            pos["below_stop_count"] = 0
            pos["shares"] = float(seed.get("shares", 0.0))
            pos["last_size_change"] = today_str
            pos["missing_since"] = None
            pos["reopened_date"] = today_str
            pos.pop("closed_date", None)
            continue
        # 정상 active — missing 카운터 리셋
        pos["missing_since"] = None

    # 2. portfolio에 없는 active 종목 → missing/archive 진행
    for tk, pos in list(positions.items()):
        if tk in portfolio_tickers:
            continue
        if pos.get("status") == "closed":
            continue
        if pos.get("missing_since") is None:
            pos["missing_since"] = today_str
        days_missing = _days_diff(today_str, pos["missing_since"])
        if days_missing >= ARCHIVE_AFTER_DAYS_MISSING:
            pos["status"] = "closed"
            pos["closed_date"] = today_str
            # signal_history 대신 snapshots에 archive 이벤트 기록
            snapshots = state.setdefault("snapshots", {})
            day = snapshots.setdefault(today_str, {})
            day[tk] = {
                "signal": "CLOSED",
                "event": "removed_from_portfolio",
                "missing_since": pos["missing_since"],
            }


# ─── Snapshot 누적 ──────────────────────────────────────────

def append_snapshot(state: dict, today_str: str, ticker: str, entry: dict) -> None:
    snapshots = state.setdefault("snapshots", {})
    day = snapshots.setdefault(today_str, {})
    day[ticker] = entry


def prune_old_snapshots(state: dict, today_str: str) -> int:
    """MAX_SNAPSHOT_DAYS 이전 스냅샷 제거. 제거 개수 반환."""
    snapshots = state.get("snapshots", {})
    if not snapshots:
        return 0
    cutoff = (datetime.strptime(today_str, "%Y-%m-%d").date()
              - timedelta(days=MAX_SNAPSHOT_DAYS))
    removed = 0
    for d in list(snapshots.keys()):
        try:
            if datetime.strptime(d, "%Y-%m-%d").date() < cutoff:
                snapshots.pop(d, None)
                removed += 1
        except ValueError:
            continue
    return removed


# ─── Bootstrap (yfinance YTD fetch) ─────────────────────────

def bootstrap_first_run(tickers: list, anchor_date: str = ANCHOR_DATE,
                        today_str: str | None = None) -> dict:
    """첫 실행 시 yfinance에서 anchor_date~today close 가져와 max 계산.

    반환: {ticker: {"highest_close": float, "highest_close_date": "YYYY-MM-DD"}}
    실패한 ticker는 dict에서 제외 — 호출자가 fallback 처리 (today_close 사용).
    """
    import yfinance as yf
    import pandas as pd

    if today_str is None:
        today_str = date.today().strftime("%Y-%m-%d")
    end_date = (datetime.strptime(today_str, "%Y-%m-%d").date()
                + timedelta(days=1)).strftime("%Y-%m-%d")

    # KR ticker는 .KS/.KQ suffix 필요
    from portfolio_data import is_korean_ticker, to_yfinance_symbol
    yf_tickers = [to_yfinance_symbol(t) if is_korean_ticker(t) else t
                  for t in tickers]
    rev_map = dict(zip(yf_tickers, tickers))

    print(f"[stop_history] Bootstrap: yfinance fetch {len(tickers)} tickers "
          f"({anchor_date} ~ {today_str})")
    out = {}
    try:
        df = yf.download(yf_tickers, start=anchor_date, end=end_date,
                         progress=False, group_by="ticker", auto_adjust=False,
                         threads=True)
    except Exception as e:
        print(f"[stop_history] WARN bulk download failed: {e}")
        return out

    for yf_t, orig_t in rev_map.items():
        try:
            if isinstance(df.columns, pd.MultiIndex):
                close = df[yf_t]["Close"].dropna()
            else:
                close = df["Close"].dropna()
            if len(close) == 0:
                continue
            max_idx = close.idxmax()
            out[orig_t] = {
                "highest_close": float(close.loc[max_idx]),
                "highest_close_date": max_idx.strftime("%Y-%m-%d"),
            }
        except Exception as e:
            print(f"[stop_history] WARN bootstrap {orig_t}: {e}")
            continue
    print(f"[stop_history] Bootstrap done: {len(out)}/{len(tickers)} tickers ok")
    return out
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_portfolio_stop_history.py -v
# Expected: 10 passed
```

- [ ] **Step 5: Commit**

```bash
git add portfolio_stop_history.py tests/test_portfolio_stop_history.py
git commit -m "$(cat <<'EOF'
feat(stop): add portfolio_stop_history.py — state I/O + lifecycle

JSON I/O for portfolio_stops.json (positions + snapshots split),
yfinance YTD bootstrap for first run, atomic save (tmp rename),
incremental highest_close update with 40% jump guard, 3-day grace
soft-archive with missing_since tracking, and reopen-after-close
handling with fresh bootstrap.

10 unit tests covering load/save round-trip, jump guard, lifecycle
transitions (new/missing/recover/reopen).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4: Signal Logic — `portfolio_stop_signal.py`

### Task 4: Stop calculation + signal evaluation (no entry point yet)

**Files:**
- Create: `portfolio_stop_signal.py` (calculation/evaluation only — entry point added in Task 5)
- Test: `tests/test_portfolio_stop_signal.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_portfolio_stop_signal.py
"""portfolio_stop_signal calculate_stop / evaluate_signal 테스트."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import portfolio_stop_signal as ps
from portfolio_stop_signal import (
    get_stop_mode, calculate_stop, round_stop,
    evaluate_signal, ACTION_MAP,
)


# ─── get_stop_mode 우선순위 ────────────────────────────────

def test_mode_explicit_override_wins():
    """OVERRIDES > keyword > category."""
    # 110990 디아이티는 KOSPI Stock 카테고리지만 HIGH_VOL override
    assert get_stop_mode("110990", "디아이티", "KOSPI Stock") == "HIGH_VOL"
    # 102110 TIGER 200 은 KOSPI ETF 기본 MOMENTUM이지만 CORE override
    assert get_stop_mode("102110", "TIGER 200", "KOSPI ETF") == "CORE"


def test_mode_keyword_auto():
    """KOSPI ETF 기본 MOMENTUM, '반도체'/'코스닥' 키워드 → HIGH_VOL."""
    assert get_stop_mode("396500", "TIGER 반도체TOP10", "KOSPI ETF") == "HIGH_VOL"
    assert get_stop_mode("232080", "TIGER 코스닥150", "KOSPI ETF") == "HIGH_VOL"
    assert get_stop_mode("466920", "SOL 조선TOP3플러스", "KOSPI ETF") == "HIGH_VOL"


def test_mode_category_default():
    assert get_stop_mode("VOO", "Vanguard S&P 500 ETF", "ETF Core") == "CORE"
    assert get_stop_mode("BIL", "SPDR 1-3M T-bill", "Bond") == "DEFENSIVE"
    assert get_stop_mode("AAPL", "Apple Inc", "Growth") == "MOMENTUM"
    assert get_stop_mode("SLV", "iShares Silver", "Metal") == "HIGH_VOL"


def test_mode_unknown_category_default():
    assert get_stop_mode("XYZ", "Unknown Co", "MadeUpCategory") == "MOMENTUM"


# ─── round_stop (시장별 호가) ───────────────────────────────

def test_round_stop_us_two_decimals():
    assert round_stop(874.32156, "NVDA") == 874.32


def test_round_stop_kr_integer():
    assert round_stop(71432.2831, "005930") == 71432.0
    assert round_stop(15000.7, "0153K0") == 15001.0


# ─── calculate_stop (모드별) ────────────────────────────────

def test_calculate_stop_core_pct():
    """CORE: highest × 0.88."""
    assert calculate_stop(100.0, atr14=2.0, mode="CORE", ticker="VOO") == 88.0


def test_calculate_stop_defensive_pct():
    """DEFENSIVE: highest × 0.92."""
    assert calculate_stop(100.0, atr14=0.5, mode="DEFENSIVE", ticker="BIL") == 92.0


def test_calculate_stop_momentum_atr_floor_applied():
    """ATR×3 < 8% min → min_pct floor 적용."""
    # ATR×3 = 6, min_pct=8 → distance = max(6, 8) = 8 → stop = 92
    assert calculate_stop(100.0, atr14=2.0, mode="MOMENTUM", ticker="AAPL") == 92.0


def test_calculate_stop_momentum_atr_in_range():
    """8% ≤ ATR×3 ≤ 20% → 그대로 적용."""
    # ATR×3 = 12 → distance = 12 → stop = 88
    assert calculate_stop(100.0, atr14=4.0, mode="MOMENTUM", ticker="NVDA") == 88.0


def test_calculate_stop_momentum_atr_ceiling_applied():
    """ATR×3 > 20% max → max_pct ceiling 적용."""
    # ATR×3 = 30 → distance = min(30, 20) = 20 → stop = 80
    assert calculate_stop(100.0, atr14=10.0, mode="MOMENTUM", ticker="TSLA") == 80.0


def test_calculate_stop_high_vol_atr_clamps():
    """HIGH_VOL: ATR×4, [12%, 30%]."""
    # ATR×4 = 8 < 12 min → 12 → stop = 88
    assert calculate_stop(100.0, atr14=2.0, mode="HIGH_VOL", ticker="QLD") == 88.0
    # ATR×4 = 80 > 30 max → 30 → stop = 70
    assert calculate_stop(100.0, atr14=20.0, mode="HIGH_VOL", ticker="QLD") == 70.0


def test_calculate_stop_atr_none_fallback():
    """ATR 없으면 min_pct로 fallback."""
    assert calculate_stop(100.0, atr14=None, mode="MOMENTUM", ticker="NVDA") == 92.0
    assert calculate_stop(100.0, atr14=None, mode="HIGH_VOL", ticker="QLD") == 88.0


def test_calculate_stop_kr_integer_rounding():
    """KR ticker → stop은 정수."""
    # 삼성전자 highest 78500, ATR 800 → MOMENTUM
    # ATR×3 = 2400 (3.06%), min 8% → 6280 → distance = 6280 → 72220
    assert calculate_stop(78500.0, atr14=800.0, mode="MOMENTUM", ticker="005930") == 72220.0


# ─── evaluate_signal 4-state machine ────────────────────────

def test_signal_hold():
    """close > stop × 1.05 → HOLD."""
    r = evaluate_signal(today_close=100.0, stop_price=90.0, prev_below_count=0,
                        is_new_position=False)
    assert r["raw_signal"] == "HOLD"
    assert r["display_signal"] == "HOLD"
    assert r["below_stop_count"] == 0


def test_signal_tight():
    """stop < close ≤ stop × 1.05 → TIGHT."""
    r = evaluate_signal(today_close=92.0, stop_price=90.0, prev_below_count=0,
                        is_new_position=False)
    assert r["raw_signal"] == "TIGHT"
    assert r["below_stop_count"] == 0


def test_signal_exit_ready_first_breach():
    """close ≤ stop AND below_count was 0 → EXIT_READY (count=1)."""
    r = evaluate_signal(today_close=89.0, stop_price=90.0, prev_below_count=0,
                        is_new_position=False)
    assert r["raw_signal"] == "EXIT_READY"
    assert r["below_stop_count"] == 1


def test_signal_exit_two_consecutive():
    """count was 1 + still below → EXIT (count=2)."""
    r = evaluate_signal(today_close=88.0, stop_price=90.0, prev_below_count=1,
                        is_new_position=False)
    assert r["raw_signal"] == "EXIT"
    assert r["below_stop_count"] == 2


def test_signal_recovery_resets_count():
    """count=1, recovery → HOLD/TIGHT, count=0."""
    r = evaluate_signal(today_close=100.0, stop_price=90.0, prev_below_count=1,
                        is_new_position=False)
    assert r["raw_signal"] == "HOLD"
    assert r["below_stop_count"] == 0


def test_signal_close_equals_stop_counted():
    """close == stop → 하회로 인정 (`<=` 사용)."""
    r = evaluate_signal(today_close=90.0, stop_price=90.0, prev_below_count=0,
                        is_new_position=False)
    assert r["raw_signal"] == "EXIT_READY"
    assert r["below_stop_count"] == 1


# ─── Display downgrade (신규 종목) ───────────────────────────

def test_display_downgrade_new_position_exit_ready():
    """신규 종목 + raw EXIT_READY → display TIGHT."""
    r = evaluate_signal(today_close=89.0, stop_price=90.0, prev_below_count=0,
                        is_new_position=True)
    assert r["raw_signal"] == "EXIT_READY"   # raw 보존
    assert r["display_signal"] == "TIGHT"   # display 다운그레이드
    assert r["display_downgraded"] is True


def test_display_downgrade_new_position_exit():
    r = evaluate_signal(today_close=88.0, stop_price=90.0, prev_below_count=1,
                        is_new_position=True)
    assert r["raw_signal"] == "EXIT"
    assert r["display_signal"] == "TIGHT"
    assert r["display_downgraded"] is True


def test_no_downgrade_for_old_position():
    r = evaluate_signal(today_close=89.0, stop_price=90.0, prev_below_count=0,
                        is_new_position=False)
    assert r["display_signal"] == "EXIT_READY"
    assert r["display_downgraded"] is False


# ─── Action 매핑 ────────────────────────────────────────────

def test_action_map_complete():
    for s in ("HOLD", "TIGHT", "EXIT_READY", "EXIT"):
        assert s in ACTION_MAP


if __name__ == "__main__":
    import inspect
    fns = [f for n, f in globals().items()
           if n.startswith("test_") and inspect.isfunction(f)]
    for f in fns:
        f()
    print(f"[OK] {len(fns)} portfolio_stop_signal tests passed.")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_portfolio_stop_signal.py -v
# Expected: ImportError: No module named 'portfolio_stop_signal'
```

- [ ] **Step 3: Create `portfolio_stop_signal.py` (calculation/eval only)**

```python
# portfolio_stop_signal.py
"""
Portfolio Stop Signal — Stop 계산 + 4-state 시그널 평가.

본 모듈은 순수 함수 위주. I/O는 portfolio_stop_history.py가 담당.
generate_portfolio_stop_signals() entry point는 Task 5에서 추가.
"""

from __future__ import annotations

from portfolio_stop_config import (
    DEFAULT_MODE, CATEGORY_TO_MODE, HIGH_VOL_KEYWORDS, MODE_OVERRIDES,
    STOP_PARAMS, TIGHT_RATIO, EXIT_BELOW_STOP_DAYS,
    NEW_POSITION_DISPLAY_DOWNGRADE,
)
from portfolio_data import is_korean_ticker


# ─── Mode 결정 (3-tier 우선순위) ──────────────────────────

def get_stop_mode(ticker: str, name: str | None, category: str | None) -> str:
    """Override > keyword > category → MOMENTUM default."""
    if ticker in MODE_OVERRIDES:
        return MODE_OVERRIDES[ticker]
    nm = name or ""
    for kw in HIGH_VOL_KEYWORDS:
        if kw in nm:
            return "HIGH_VOL"
    return CATEGORY_TO_MODE.get(category or "Other", DEFAULT_MODE)


# ─── 시장별 호가 단위 라운딩 ─────────────────────────────

def round_stop(price: float, ticker: str) -> float:
    """KR=정수, US=소수 2자리. portfolio_data.is_korean_ticker 재사용."""
    if is_korean_ticker(ticker):
        return float(round(price))
    return round(price, 2)


# ─── Stop 계산 ─────────────────────────────────────────────

def calculate_stop(highest_close: float, atr14: float | None,
                   mode: str, ticker: str) -> float:
    """4개 mode 공식 + min/max% 양방향 clamp + market-aware rounding."""
    p = STOP_PARAMS[mode]
    if p["type"] == "pct":
        return round_stop(highest_close * p["ratio"], ticker)
    # ATR 기반
    if atr14 is None or atr14 <= 0:
        # ATR fail → min_pct percentage fallback
        return round_stop(highest_close * (1.0 - p["min_pct"]), ticker)
    atr_distance = atr14 * p["multiplier"]
    min_distance = highest_close * p["min_pct"]
    max_distance = highest_close * p["max_pct"]
    distance = max(atr_distance, min_distance)
    distance = min(distance, max_distance)
    return round_stop(highest_close - distance, ticker)


# ─── 4-state 시그널 평가 ────────────────────────────────────

ACTION_MAP = {
    "HOLD":       "Hold",
    "TIGHT":      "Trim 10~15%",
    "EXIT_READY": "Trim 30~50%",
    "EXIT":       "Exit trading portion",
}


def _compute_raw_signal(today_close: float, stop_price: float,
                        new_below_count: int) -> str:
    """우선순위: EXIT > EXIT_READY > TIGHT > HOLD."""
    if new_below_count >= EXIT_BELOW_STOP_DAYS:
        return "EXIT"
    if new_below_count >= 1:
        return "EXIT_READY"
    if today_close <= stop_price * TIGHT_RATIO:
        return "TIGHT"
    return "HOLD"


def evaluate_signal(today_close: float, stop_price: float,
                    prev_below_count: int, is_new_position: bool) -> dict:
    """Daily 시그널 평가 — raw / display 분리.

    반환:
      raw_signal: 데이터 레이어 진실값 (positions/snapshots 저장용)
      display_signal: UI/Telegram 표시용 (신규 종목 다운그레이드 적용)
      display_downgraded: bool — 다운그레이드 여부 (분석/디버깅)
      below_stop_count: 갱신된 카운터
    """
    # `<=` — 정확히 stop 찍은 날도 하회 인정
    if today_close <= stop_price:
        new_count = prev_below_count + 1
    else:
        new_count = 0  # 회복 시 리셋 (비연속 누적 안 함)

    raw = _compute_raw_signal(today_close, stop_price, new_count)

    # Display 다운그레이드 — raw는 그대로, UI/Telegram만 톤 다운
    if (NEW_POSITION_DISPLAY_DOWNGRADE
            and is_new_position
            and raw in ("EXIT_READY", "EXIT")):
        display = "TIGHT"
        downgraded = True
    else:
        display = raw
        downgraded = False

    return {
        "raw_signal": raw,
        "display_signal": display,
        "display_downgraded": downgraded,
        "below_stop_count": new_count,
        "action": ACTION_MAP[raw],
        "display_action": ACTION_MAP[display],
    }
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_portfolio_stop_signal.py -v
# Expected: ~25 passed
```

- [ ] **Step 5: Commit**

```bash
git add portfolio_stop_signal.py tests/test_portfolio_stop_signal.py
git commit -m "$(cat <<'EOF'
feat(stop): add stop calculation and 4-state signal evaluation

Pure functions for:
- get_stop_mode: 3-tier priority (override > keyword > category)
- round_stop: market-aware (KR=integer, US=2 decimals) via existing
  is_korean_ticker helper
- calculate_stop: pct (CORE/DEFENSIVE) and atr (MOMENTUM/HIGH_VOL)
  modes with min/max% clamp on both sides
- evaluate_signal: 4-state machine (HOLD/TIGHT/EXIT_READY/EXIT)
  using `close <= stop` (inclusive) and 2-day consecutive rule
- Display downgrade for new positions: raw_signal preserved (audit
  layer), display_signal tones down EXIT_READY/EXIT to TIGHT (UI
  noise reduction)

25 unit tests covering mode priority, market rounding, stop floor/
ceiling clamps, all 4-state transitions, and display downgrade.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `generate_portfolio_stop_signals` entry point

이 함수가 Step 4c3에서 호출되는 단일 진입점. history load → bootstrap if needed → lifecycle → per-position evaluate → snapshot 누적 → save.

**Files:**
- Modify: `portfolio_stop_signal.py` (append entry function)
- Test: `tests/test_portfolio_stop_signal.py` (append integration test)

- [ ] **Step 1: Add integration test (mocked yfinance)**

`tests/test_portfolio_stop_signal.py` 끝에 추가:

```python


# ─── generate_portfolio_stop_signals integration ────────────

def test_generate_signals_first_run_uses_today_fallback(monkeypatch, tmp_path):
    """첫 실행: bootstrap_first_run mock해 today_close fallback 동작 확인."""
    import portfolio_stop_history as ph
    import portfolio_stop_signal as pss

    # bootstrap mock — empty (모든 ticker fail) → today_close가 highest로
    monkeypatch.setattr(ph, "bootstrap_first_run", lambda *a, **kw: {})

    market_data = {
        "data": {
            "NVDA": {"price": 920.0, "atr14": 15.0, "prev_close": 915.0},
            "BIL":  {"price": 91.5,  "atr14": 0.05, "prev_close": 91.5},
        }
    }
    portfolio = [
        {"ticker": "NVDA", "shares": 50.0},
        {"ticker": "BIL",  "shares": 900.0},
    ]
    history_path = str(tmp_path / "stops.json")
    out = pss.generate_portfolio_stop_signals(
        project_dir=str(tmp_path), owner="me",
        market_data=market_data, portfolio=portfolio,
        today="2026-05-07", history_path=history_path,
    )
    assert out["status"] == "ok"
    assert "summary" in out
    # 신규 종목 — display 다운그레이드로 EXIT/EXIT_READY 발동 안 됨
    assert out["summary"]["EXIT"] == 0


def test_generate_signals_returns_summary_shape(monkeypatch, tmp_path):
    import portfolio_stop_history as ph
    import portfolio_stop_signal as pss

    monkeypatch.setattr(ph, "bootstrap_first_run", lambda *a, **kw: {})

    market_data = {"data": {"NVDA": {"price": 920.0, "atr14": 15.0, "prev_close": 915.0}}}
    portfolio = [{"ticker": "NVDA", "shares": 50.0}]
    out = pss.generate_portfolio_stop_signals(
        project_dir=str(tmp_path), owner="me",
        market_data=market_data, portfolio=portfolio,
        today="2026-05-07", history_path=str(tmp_path / "stops.json"),
    )
    assert set(out.keys()) >= {"status", "owner", "date", "summary",
                                "positions", "changes"}
    assert set(out["summary"].keys()) >= {"HOLD", "TIGHT", "EXIT_READY", "EXIT"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_portfolio_stop_signal.py::test_generate_signals_returns_summary_shape -v
# Expected: AttributeError or ImportError — generate_portfolio_stop_signals 미정의
```

- [ ] **Step 3: Append `generate_portfolio_stop_signals` to `portfolio_stop_signal.py`**

`portfolio_stop_signal.py` 끝에 추가:

```python


# ─── Entry point — Pipeline Step 4c3에서 호출 ──────────────

import os
from datetime import datetime
from portfolio_stop_config import (
    ANCHOR_DATE, NEW_POSITION_NOISE_DAYS, MAX_SNAPSHOT_DAYS,
)
from portfolio_stop_history import (
    load_stop_history, save_stop_history,
    update_highest_close_safe, evaluate_lifecycle,
    bootstrap_first_run, append_snapshot, prune_old_snapshots,
)


def _is_new_position(entry_date: str, today_str: str) -> bool:
    """Calendar days 기준 — entry_date 후 NEW_POSITION_NOISE_DAYS 이내."""
    try:
        a = datetime.strptime(today_str, "%Y-%m-%d").date()
        b = datetime.strptime(entry_date, "%Y-%m-%d").date()
        return (a - b).days <= NEW_POSITION_NOISE_DAYS
    except Exception:
        return False


def _gap_pct(close: float, stop: float) -> float:
    if stop and stop > 0:
        return round((close - stop) / stop * 100, 2)
    return 0.0


def _resolve_history_path(project_dir: str, owner: str) -> str:
    fname = ("portfolio_stops.json" if owner == "me"
             else f"portfolio_stops_{owner}.json")
    return os.path.join(project_dir, "history", fname)


def generate_portfolio_stop_signals(
    project_dir: str, owner: str,
    market_data: dict, portfolio: list,
    today: str | None = None,
    history_path: str | None = None,
) -> dict:
    """Pipeline Step 4c3 entry point.

    인자:
      project_dir: 프로젝트 루트
      owner: "me" | "wife" | ...
      market_data: fetch_market_data 출력 (atr14 필요)
      portfolio: pipeline._parse_portfolio_for_report 결과
      today: "YYYY-MM-DD" (None이면 오늘)
      history_path: 기본은 project_dir/history/portfolio_stops_{owner}.json

    반환:
      {"status": "ok", "owner", "date", "summary": {...},
       "positions": [...], "changes": [...]}
    """
    from datetime import date as _date
    today_str = today or _date.today().strftime("%Y-%m-%d")
    history_path = history_path or _resolve_history_path(project_dir, owner)

    state = load_stop_history(history_path, owner=owner)
    is_first_run = not state["positions"]

    data = market_data.get("data", {})

    # 1. mode 결정 + new_position_seed 구성
    from portfolio_data import get_ticker_class, get_ticker_name
    portfolio_tickers = set()
    new_seed: dict = {}
    for p in portfolio:
        tk = p["ticker"]
        portfolio_tickers.add(tk)
        d = data.get(tk, {})
        close = d.get("price", 0) or 0
        if close <= 0:
            continue
        mode = get_stop_mode(tk, get_ticker_name(tk),
                              get_ticker_class(tk) or "Other")
        new_seed[tk] = {"close": float(close), "mode": mode,
                         "shares": float(p.get("shares", 0))}

    # 2. 첫 실행 → bootstrap (yfinance YTD high)
    if is_first_run:
        boot = bootstrap_first_run(list(portfolio_tickers),
                                   anchor_date=ANCHOR_DATE,
                                   today_str=today_str)
        for tk in portfolio_tickers:
            if tk in boot:
                # 첫 실행은 entry_date = ANCHOR_DATE 로 설정
                state["positions"][tk] = {
                    "status": "active",
                    "mode": new_seed[tk]["mode"],
                    "entry_date": ANCHOR_DATE,
                    "highest_close": boot[tk]["highest_close"],
                    "highest_close_date": boot[tk]["highest_close_date"],
                    "current_stop": None,
                    "below_stop_count": 0,
                    "shares": new_seed[tk]["shares"],
                    "last_size_change": today_str,
                    "missing_since": None,
                    "last_signal": None,
                    "last_action": None,
                    "last_evaluated": None,
                }
        # bootstrap 실패한 종목은 이후 lifecycle에서 신규 처리됨

    # 3. Lifecycle (신규/재매수/매도 grace)
    evaluate_lifecycle(state, portfolio_tickers, today_str, new_seed)

    # 4. 종목별 평가
    summary = {"HOLD": 0, "TIGHT": 0, "EXIT_READY": 0, "EXIT": 0, "CLOSED": 0}
    positions_out = []
    changes = []

    for tk in sorted(portfolio_tickers):
        pos = state["positions"].get(tk)
        if pos is None or pos.get("status") != "active":
            continue
        d = data.get(tk, {})
        today_close = d.get("price", 0) or 0
        prev_close = d.get("prev_close")
        atr14 = d.get("atr14")
        if today_close <= 0:
            continue

        # 4a. highest_close 안전 갱신
        pos["ticker"] = tk  # for WARN log
        update_highest_close_safe(pos, today_close, prev_close, today_str)
        # 4b. shares 갱신 (변경 시만 last_size_change 업데이트)
        new_shares = float(new_seed.get(tk, {}).get("shares", pos.get("shares", 0)))
        if abs(new_shares - pos.get("shares", 0)) > 1e-9:
            pos["shares"] = new_shares
            pos["last_size_change"] = today_str
        # 4c. stop 계산
        stop_price = calculate_stop(pos["highest_close"], atr14,
                                     pos["mode"], tk)
        pos["current_stop"] = stop_price
        # 4d. 시그널 평가
        is_new = _is_new_position(pos["entry_date"], today_str)
        prev_count = pos.get("below_stop_count", 0)
        ev = evaluate_signal(today_close, stop_price, prev_count, is_new)
        # 4e. 상태 갱신
        prev_signal = pos.get("last_signal")
        pos["below_stop_count"] = ev["below_stop_count"]
        pos["last_signal"] = ev["raw_signal"]   # raw 보존
        pos["last_action"] = ev["action"]
        pos["last_evaluated"] = today_str

        # 4f. snapshot 기록 (raw 사용)
        append_snapshot(state, today_str, tk, {
            "signal": ev["raw_signal"],
            "close": round(today_close, 4),
            "stop": stop_price,
            "gap_pct": _gap_pct(today_close, stop_price),
            "below_stop_count": ev["below_stop_count"],
            "is_new_position": is_new,
            "display_downgraded": ev["display_downgraded"],
        })

        summary[ev["raw_signal"]] = summary.get(ev["raw_signal"], 0) + 1

        if prev_signal and prev_signal != ev["raw_signal"]:
            changes.append({"ticker": tk, "from": prev_signal,
                             "to": ev["raw_signal"]})

        positions_out.append({
            "ticker": tk,
            "name": get_ticker_name(tk) or tk,
            "mode": pos["mode"],
            "highest_close": pos["highest_close"],
            "highest_close_date": pos["highest_close_date"],
            "current_close": round(today_close, 4),
            "stop_price": stop_price,
            "gap_pct": _gap_pct(today_close, stop_price),
            "raw_signal": ev["raw_signal"],
            "display_signal": ev["display_signal"],
            "display_downgraded": ev["display_downgraded"],
            "is_new_position": is_new,
            "below_stop_count": ev["below_stop_count"],
            "action": ev["action"],
            "display_action": ev["display_action"],
            "entry_date": pos["entry_date"],
        })

    # 5. closed 항목도 summary에 1회 카운트
    for tk, pos in state["positions"].items():
        if pos.get("status") == "closed" and pos.get("closed_date") == today_str:
            summary["CLOSED"] += 1

    # 6. 정렬: severity desc (EXIT > EXIT_READY > TIGHT > HOLD), 그 안에서 gap_pct asc
    SEV = {"EXIT": 0, "EXIT_READY": 1, "TIGHT": 2, "HOLD": 3}
    positions_out.sort(key=lambda r: (SEV.get(r["display_signal"], 9),
                                        r["gap_pct"], r["ticker"]))

    # 7. snapshot prune + save
    prune_old_snapshots(state, today_str)
    save_stop_history(state, history_path)

    return {
        "status": "ok",
        "owner": owner,
        "date": today_str,
        "summary": summary,
        "positions": positions_out,
        "changes": changes,
        "history_path": history_path,
    }
```

- [ ] **Step 4: Run all stop signal tests**

```bash
pytest tests/test_portfolio_stop_signal.py -v
# Expected: ~27 passed
```

- [ ] **Step 5: Commit**

```bash
git add portfolio_stop_signal.py tests/test_portfolio_stop_signal.py
git commit -m "$(cat <<'EOF'
feat(stop): add generate_portfolio_stop_signals entry point

Single function called by pipeline Step 4c3. Handles:
- First-run bootstrap (yfinance YTD high fetch with today_close
  fallback for failed tickers)
- Lifecycle evaluation (new positions, missing grace, reopen)
- Per-position highest_close safe update (40% jump guard)
- Stop calculation (mode-aware) + 4-state evaluation (raw/display)
- Snapshot append + 730-day rolling prune
- Atomic save

Returns structured summary for pipeline integration with positions
sorted by display_signal severity. Two integration tests added
(monkeypatched bootstrap).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 5: HTML Output

### Task 6: Jinja2 template `templates/portfolio_stops.html`

**Files:**
- Create: `templates/portfolio_stops.html`

- [ ] **Step 1: Examine existing template style**

```bash
ls templates/
# Expected: report_template.html, scanner_*.html, trend.html, etc.
```

Read `templates/report_template.html` 위쪽 100라인 확인 — CSS/nav 패턴 파악.

- [ ] **Step 2: Create `templates/portfolio_stops.html`**

```html
{# templates/portfolio_stops.html — Portfolio Stop Signal page (me/wife shared) #}
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>🛡 Portfolio Risk — {{ owner }} {{ date }}</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 1200px; margin: 0 auto; padding: 20px;
         background: #0f172a; color: #e2e8f0; }
  h1 { color: #fbbf24; margin: 0 0 10px; }
  .meta { color: #94a3b8; font-size: 13px; margin-bottom: 20px; }
  nav { margin: 10px 0 20px; }
  nav a { display: inline-block; margin-right: 8px; padding: 6px 12px;
          background: #1e293b; color: #e2e8f0; border-radius: 6px;
          text-decoration: none; font-size: 13px; }
  nav a.active { background: #fbbf24; color: #0f172a; }
  .cards { display: flex; gap: 12px; margin: 20px 0; flex-wrap: wrap; }
  .card { padding: 16px; border-radius: 10px; min-width: 140px; }
  .card.hold { background: #064e3b; }
  .card.tight { background: #78350f; }
  .card.exit-ready { background: #9a3412; }
  .card.exit { background: #991b1b; }
  .card .num { font-size: 32px; font-weight: 700; }
  .card .label { font-size: 13px; opacity: .85; }
  .changes { background: #1e293b; padding: 12px 16px; border-radius: 8px;
             margin-bottom: 16px; }
  .changes h3 { margin: 0 0 8px; font-size: 14px; color: #fbbf24; }
  .changes div { font-size: 13px; padding: 2px 0; }
  table { width: 100%; border-collapse: collapse; background: #1e293b;
          border-radius: 8px; overflow: hidden; font-size: 13px; }
  th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #334155; }
  th { background: #0f172a; color: #fbbf24; font-weight: 600; }
  tr:hover td { background: #334155; }
  .badge { padding: 3px 8px; border-radius: 12px; font-size: 11px;
           font-weight: 600; display: inline-block; }
  .badge.hold { background: #064e3b; color: #6ee7b7; }
  .badge.tight { background: #78350f; color: #fde68a; }
  .badge.exit-ready { background: #9a3412; color: #fdba74; }
  .badge.exit { background: #991b1b; color: #fecaca; }
  .badge.exit.deep2 { background: #7f1d1d; }
  .badge.exit.deep3 { background: #6b1414; }
  .gap.green-dark { color: #34d399; font-weight: 600; }
  .gap.green-light { color: #6ee7b7; }
  .gap.yellow { color: #fbbf24; }
  .gap.red { color: #f87171; font-weight: 600; }
  .new-mark { color: #93c5fd; font-size: 11px; margin-left: 4px; }
  .footer { color: #94a3b8; font-size: 12px; margin-top: 30px;
            padding: 16px; background: #1e293b; border-radius: 8px; }
  .footer p { margin: 4px 0; }
</style>
</head>
<body>

<h1>🛡 Portfolio Risk Dashboard — {{ owner }}</h1>
<div class="meta">
  Date: {{ date }} · Anchor: {{ anchor_date }} · Tracked:
  {{ summary.HOLD + summary.TIGHT + summary.EXIT_READY + summary.EXIT }} positions ·
  Mode: {{ version }}
</div>

<nav>
  <a href="report_{{ date }}.html">📊 Portfolio</a>
  {% if owner != "me" %}<a href="report_{{ owner }}_{{ date }}.html">📊 {{ owner }}</a>{% endif %}
  <a href="trend_{{ date }}.html">📈 Trend</a>
  <a class="active" href="#">🛡 Portfolio Risk</a>
</nav>

<div class="cards">
  <div class="card hold">
    <div class="num">{{ summary.HOLD }}</div>
    <div class="label">🟢 HOLD</div>
  </div>
  <div class="card tight">
    <div class="num">{{ summary.TIGHT }}</div>
    <div class="label">🟡 TIGHT</div>
  </div>
  <div class="card exit-ready">
    <div class="num">{{ summary.EXIT_READY }}</div>
    <div class="label">🟠 EXIT READY</div>
  </div>
  <div class="card exit">
    <div class="num">{{ summary.EXIT }}</div>
    <div class="label">🔴 EXIT</div>
  </div>
</div>

{% if changes %}
<div class="changes">
  <h3>Signal Changes (vs previous trading day)</h3>
  {% for c in changes %}
    <div>{{ c.ticker }}: {{ c.from }} → {{ c.to }}</div>
  {% endfor %}
</div>
{% endif %}

<table>
  <thead>
    <tr>
      <th>Ticker</th>
      <th>Mode</th>
      <th>Highest (date)</th>
      <th>Current</th>
      <th>Stop</th>
      <th>Stop Gap</th>
      <th>Signal</th>
      <th>Action</th>
    </tr>
  </thead>
  <tbody>
  {% for r in positions %}
    <tr>
      <td>
        <a href="details/{{ r.ticker }}.html" style="color:#fbbf24">{{ r.ticker }}</a>
        {% if r.is_new_position %}<span class="new-mark" title="신규 진입 종목 (entry_date 후 14일 이내)">ⓝ</span>{% endif %}
      </td>
      <td>{{ r.mode }}</td>
      <td>{{ r.highest_close | round(2) if r.is_us else r.highest_close | round(0) }}<br>
          <small style="color:#94a3b8">{{ r.highest_close_date }}</small></td>
      <td>{{ r.current_close | round(2) if r.is_us else r.current_close | round(0) }}</td>
      <td>{{ r.stop_price | round(2) if r.is_us else r.stop_price | round(0) }}</td>
      <td class="gap {{ r.gap_class }}">{{ '+' if r.gap_pct >= 0 else '' }}{{ r.gap_pct }}%</td>
      <td><span class="badge {{ r.badge_class }}">{{ r.display_label }}</span></td>
      <td>{{ r.display_action }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>

<div class="footer">
  <p>Anchor: {{ anchor_date }} · Bootstrap: yfinance YTD high · Mode: {{ version }}</p>
  <p>⚠ ⓝ 표시 종목은 신규 진입(entry_date 후 14 calendar days 이내)으로 highest_close 누적 부족 — 시그널 노이즈 가능. EXIT_READY/EXIT는 display 다운그레이드되어 TIGHT (new)로 표기.</p>
  <p>⚠ 자동 매도 아님 — 매도 판단 보조 reference 시스템</p>
  <p>Stop 공식: CORE 12% · DEFENSIVE 8% · MOMENTUM ATR×3 [8%,20%] · HIGH_VOL ATR×4 [12%,30%]</p>
</div>

</body>
</html>
```

- [ ] **Step 3: Commit**

```bash
git add templates/portfolio_stops.html
git commit -m "$(cat <<'EOF'
feat(stop): add portfolio_stops.html Jinja2 template

Hero, summary cards (4 states), signal changes, main table with
stop gap color gradient, footer with disclaimers. Owner-aware
nav links. Uses gap_class/badge_class/display_label/display_action
prepared by report module to keep template logic minimal.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: `portfolio_stop_report.py` — HTML rendering

**Files:**
- Create: `portfolio_stop_report.py`

- [ ] **Step 1: Add smoke test**

```python
# tests/test_portfolio_stop_report.py
"""portfolio_stop_report 렌더링 smoke 테스트."""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from portfolio_stop_report import generate_portfolio_stop_page


def _sample_result():
    return {
        "status": "ok",
        "owner": "me",
        "date": "2026-05-07",
        "summary": {"HOLD": 1, "TIGHT": 1, "EXIT_READY": 1, "EXIT": 0, "CLOSED": 0},
        "positions": [
            {"ticker": "TSLA", "name": "Tesla", "mode": "MOMENTUM",
             "highest_close": 410.0, "highest_close_date": "2026-02-15",
             "current_close": 358.5, "stop_price": 380.0, "gap_pct": -5.7,
             "raw_signal": "EXIT_READY", "display_signal": "EXIT_READY",
             "display_downgraded": False, "is_new_position": False,
             "below_stop_count": 1, "action": "Trim 30~50%",
             "display_action": "Trim 30~50%", "entry_date": "2026-01-02"},
            {"ticker": "NVDA", "name": "NVIDIA", "mode": "MOMENTUM",
             "highest_close": 945.0, "highest_close_date": "2026-05-05",
             "current_close": 920.0, "stop_price": 874.0, "gap_pct": 5.26,
             "raw_signal": "TIGHT", "display_signal": "TIGHT",
             "display_downgraded": False, "is_new_position": False,
             "below_stop_count": 0, "action": "Trim 10~15%",
             "display_action": "Trim 10~15%", "entry_date": "2026-01-02"},
            {"ticker": "VOO", "name": "Vanguard S&P 500", "mode": "CORE",
             "highest_close": 540.0, "highest_close_date": "2026-04-30",
             "current_close": 535.0, "stop_price": 475.2, "gap_pct": 12.6,
             "raw_signal": "HOLD", "display_signal": "HOLD",
             "display_downgraded": False, "is_new_position": False,
             "below_stop_count": 0, "action": "Hold",
             "display_action": "Hold", "entry_date": "2026-01-02"},
        ],
        "changes": [
            {"ticker": "TSLA", "from": "TIGHT", "to": "EXIT_READY"},
        ],
    }


def test_render_creates_html_file(tmp_path):
    out = generate_portfolio_stop_page(_sample_result(), str(tmp_path),
                                        anchor_date="2026-01-02")
    assert os.path.exists(out)
    text = open(out, encoding="utf-8").read()
    assert "Portfolio Risk Dashboard" in text
    assert "TSLA" in text and "NVDA" in text and "VOO" in text
    assert "🟠 EXIT READY" in text or "EXIT_READY" in text


if __name__ == "__main__":
    test_render_creates_html_file(tempfile.TemporaryDirectory().name)
    print("[OK] portfolio_stop_report tests passed.")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_portfolio_stop_report.py -v
# Expected: ImportError
```

- [ ] **Step 3: Create `portfolio_stop_report.py`**

```python
# portfolio_stop_report.py
"""
Portfolio Stop Signal — HTML page renderer.

Jinja2로 portfolio_stops.html 템플릿 렌더링. positions에 view-only
필드(badge_class, gap_class, display_label, is_us 등)를 주입.
"""

import os
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

from portfolio_stop_config import VERSION, ANCHOR_DATE
from portfolio_data import is_korean_ticker


_BADGE_MAP = {
    "HOLD":       "hold",
    "TIGHT":      "tight",
    "EXIT_READY": "exit-ready",
    "EXIT":       "exit",
}
_LABEL_MAP = {
    "HOLD":       "🟢 HOLD",
    "TIGHT":      "🟡 TIGHT",
    "EXIT_READY": "🟠 EXIT READY",
    "EXIT":       "🔴 EXIT",
}


def _gap_class(gap_pct: float) -> str:
    if gap_pct > 10:
        return "green-dark"
    if gap_pct > 3:
        return "green-light"
    if gap_pct >= 0:
        return "yellow"
    return "red"


def _badge_class(display_signal: str, below_count: int) -> str:
    base = _BADGE_MAP.get(display_signal, "hold")
    if display_signal == "EXIT" and below_count >= 4:
        return f"{base} deep3"
    if display_signal == "EXIT" and below_count >= 3:
        return f"{base} deep2"
    return base


def _display_label(display_signal: str, is_new: bool, below_count: int) -> str:
    base = _LABEL_MAP.get(display_signal, display_signal)
    if is_new and display_signal == "TIGHT":
        return f"{base} (new)"
    if display_signal in ("EXIT_READY", "EXIT") and below_count >= 1:
        return f"{base} ({below_count}d)"
    return base


def _enrich(positions: list) -> list:
    out = []
    for r in positions:
        is_us = not is_korean_ticker(r["ticker"])
        rr = dict(r)
        rr["is_us"] = is_us
        rr["gap_class"] = _gap_class(r.get("gap_pct", 0))
        rr["badge_class"] = _badge_class(r.get("display_signal", "HOLD"),
                                           r.get("below_stop_count", 0))
        rr["display_label"] = _display_label(
            r.get("display_signal", "HOLD"),
            r.get("is_new_position", False),
            r.get("below_stop_count", 0),
        )
        out.append(rr)
    return out


def generate_portfolio_stop_page(stop_result: dict, output_dir: str,
                                  anchor_date: str = ANCHOR_DATE,
                                  template_dir: str | None = None) -> str:
    """stop_result(generate_portfolio_stop_signals 반환) → HTML 파일.

    파일명:
      me  → portfolio_stops_<DATE>.html
      其他 → portfolio_stops_<owner>_<DATE>.html
    """
    if template_dir is None:
        template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)
    tmpl = env.get_template("portfolio_stops.html")

    owner = stop_result.get("owner", "me")
    date_str = stop_result.get("date", "")
    enriched = _enrich(stop_result.get("positions", []))

    html = tmpl.render(
        owner=owner,
        date=date_str,
        anchor_date=anchor_date,
        version=VERSION,
        summary=stop_result.get("summary", {}),
        changes=stop_result.get("changes", []),
        positions=enriched,
    )

    fname = ("portfolio_stops_{}.html".format(date_str) if owner == "me"
             else "portfolio_stops_{}_{}.html".format(owner, date_str))
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path
```

- [ ] **Step 4: Run test**

```bash
pytest tests/test_portfolio_stop_report.py -v
# Expected: 1 passed
```

- [ ] **Step 5: Commit**

```bash
git add portfolio_stop_report.py tests/test_portfolio_stop_report.py
git commit -m "$(cat <<'EOF'
feat(stop): add portfolio_stop_report.py — HTML page renderer

Renders portfolio_stops.html template from generate_portfolio_stop_
signals() result. Enriches positions with view-only fields:
- gap_class (color gradient: green/yellow/red based on gap_pct)
- badge_class (with deep2/deep3 for EXIT count >= 3/4)
- display_label (with (Nd) suffix for breach count, (new) for fresh)
- is_us (drives KR=integer / US=2-decimal price formatting)

Owner-aware filename (portfolio_stops_<DATE>.html for me,
portfolio_stops_<owner>_<DATE>.html for others).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 6: Pipeline Integration

### Task 8: `pipeline.py` Step 4c3 (me) + Step 5d secondary owner stops

**Files:**
- Modify: `pipeline.py` (insert Step 4c3 after Step 4c, augment Step 5d)

- [ ] **Step 1: Read existing pipeline.py Step 4c (line ~289) for insertion point**

확인: `[Step 4c]` 끝나고 `[Step 4d]` 시작하는 사이에 4c3 삽입.

- [ ] **Step 2: Insert Step 4c3 in `pipeline.py`**

`# Step 4c: Politician Trades` 블록의 `except Exception as e: ...` 다음, `# Step 4d: YTD benchmark` 라인 직전에 다음 블록 추가:

```python
        # Step 4c3: Portfolio Stop Signals (me)
        # 자동매매 ❌ / 매도 판단 보조 ✅. 4c3로 번호 잡아 4c2(예정)와 4d 사이.
        skip_stops = os.environ.get("SKIP_STOPS", "").lower() in ("1", "true", "yes")
        stop_result_me = None
        if skip_stops:
            print("[Step 4c3] SKIP_STOPS=1 — 포트폴리오 stop 시그널 스킵")
        else:
            print("[Step 4c3] Portfolio stop signals (me)...")
            try:
                from portfolio_stop_signal import generate_portfolio_stop_signals
                stop_result_me = generate_portfolio_stop_signals(
                    project_dir=project_dir, owner="me",
                    market_data=market_data,
                    portfolio=_parse_portfolio_for_report(portfolio_path),
                    today=today,
                )
                if stop_result_me and stop_result_me.get("status") == "ok":
                    s = stop_result_me["summary"]
                    print(f"  OK [4c3] me: HOLD={s.get('HOLD',0)} "
                          f"TIGHT={s.get('TIGHT',0)} "
                          f"EXIT_READY={s.get('EXIT_READY',0)} "
                          f"EXIT={s.get('EXIT',0)}")
            except Exception as e:
                import traceback as _tbs
                _tbs.print_exc()
                print(f"  WARN [4c3] me stop signals failed: {e}")
                stop_result_me = None
```

- [ ] **Step 3: Build me stop page in Step 5 area**

`# Step 5: Report generation` 블록 안, `report_path = ...` 다음, `generate_report(...)` 호출 직전에 me stop 페이지 생성 추가:

```python
        # Step 5 (cont.): Stop signal page for me
        stop_page_path_me = None
        if stop_result_me and stop_result_me.get("status") == "ok":
            try:
                from portfolio_stop_report import generate_portfolio_stop_page
                stop_page_path_me = generate_portfolio_stop_page(
                    stop_result_me, output_dir=reports_dir,
                )
                print(f"  OK stop page (me) -> {stop_page_path_me}")
            except Exception as e:
                print(f"  WARN stop page (me) failed: {e}")
```

- [ ] **Step 4: Pass `portfolio_stop_result` to `generate_report` (me)**

`generate_report(...)` 호출에 인자 추가 (me 호출 부분, 약 line 394):

기존:
```python
        generate_report(
            market_data=market_data,
            portfolio=portfolio,
            ...
            benchmark_data=benchmark_by_owner.get("me"),
        )
```

변경:
```python
        generate_report(
            market_data=market_data,
            portfolio=portfolio,
            ...
            benchmark_data=benchmark_by_owner.get("me"),
            portfolio_stop_result=stop_result_me,
        )
```

(`generate_report`은 Task 9에서 인자 받도록 수정 — 지금은 `**kwargs` 무시 안 되므로 Task 9 먼저 끝낸 뒤 이 step 수행 권장. 안전하게 Task 9 다음에 통합 커밋.)

- [ ] **Step 5: Augment Step 5d wife loop**

`# Step 5d: 다른 포트폴리오 (wife 등) 리포트 생성` 블록의 `for _owner, _opath in _owners:` 루프 안, `_owner_report = ...` 직전에 wife stop signal 추가:

```python
            # Step 4c3 equivalent for secondary owner — independent state file
            owner_stop_result = None
            if not skip_stops:
                try:
                    from portfolio_stop_signal import generate_portfolio_stop_signals
                    owner_stop_result = generate_portfolio_stop_signals(
                        project_dir=project_dir, owner=_owner,
                        market_data=_owner_market,
                        portfolio=_owner_portfolio,
                        today=today,
                    )
                    if owner_stop_result and owner_stop_result.get("status") == "ok":
                        s = owner_stop_result["summary"]
                        print(f"  OK [4c3] {_owner}: HOLD={s.get('HOLD',0)} "
                              f"TIGHT={s.get('TIGHT',0)} "
                              f"EXIT_READY={s.get('EXIT_READY',0)} "
                              f"EXIT={s.get('EXIT',0)}")
                except Exception as e:
                    print(f"  WARN [4c3] {_owner} stop signals failed: {e}")
                    owner_stop_result = None
```

이어서 wife stop 페이지 생성 — `_sz = os.path.getsize(_owner_report)` 라인 다음에 추가:

```python
                # Stop signal page for secondary owner
                if owner_stop_result and owner_stop_result.get("status") == "ok":
                    try:
                        from portfolio_stop_report import generate_portfolio_stop_page
                        owner_stop_page = generate_portfolio_stop_page(
                            owner_stop_result, output_dir=reports_dir,
                        )
                        print(f"  OK stop page ({_owner}) -> {owner_stop_page}")
                    except Exception as e:
                        print(f"  WARN stop page ({_owner}) failed: {e}")
```

또한 같은 wife 루프의 `generate_report(...)` 호출에도 `portfolio_stop_result=owner_stop_result` 인자 추가.

- [ ] **Step 6: Smoke test pipeline (skip-fetch + skip-scanners — fast)**

```bash
SKIP_SCANNERS=1 python pipeline.py --skip-ocr --skip-fetch --auto
# Expected:
#   [Step 4c3] Portfolio stop signals (me)...
#     OK [4c3] me: HOLD=N TIGHT=N EXIT_READY=N EXIT=N
#     OK stop page (me) -> reports/portfolio_stops_<DATE>.html
#   ... wife loop ...
#     OK [4c3] wife: HOLD=N TIGHT=N EXIT_READY=N EXIT=N
#     OK stop page (wife) -> reports/portfolio_stops_wife_<DATE>.html
```

(첫 실행이라 yfinance bootstrap 호출됨 — 1~2분 소요. 두 번째부터 즉시 완료.)

- [ ] **Step 7: Verify generated files**

```bash
ls -la history/portfolio_stops*.json
ls -la reports/portfolio_stops_*.html
```

브라우저로 페이지 열어 카드 / 테이블 / 색상 / KR 정수 표기 / US 소수 표기 확인.

- [ ] **Step 8: Commit (depends on Task 9 done first)**

⚠ **이 커밋은 Task 9 완료 후 함께 실행.** (`generate_report`에 새 kwarg 받기 전에 먼저 호출하면 TypeError.)

```bash
git add pipeline.py
git commit -m "$(cat <<'EOF'
feat(stop): integrate Step 4c3 portfolio stop signals into pipeline

- Step 4c3 (me): generate_portfolio_stop_signals after Step 4c,
  before Step 4d. SKIP_STOPS=1 env to disable for fast regression.
- Step 5: stop page generation for me with fail-soft try/except.
- Step 5d: equivalent stop signal call + page generation per
  secondary owner (wife etc.). Each owner has independent
  history/portfolio_stops_<owner>.json file.
- generate_report calls extended with portfolio_stop_result kwarg
  (consumed by report_generator changes in companion commit).

Failures here never block downstream pipeline steps — UI hides
stop sections gracefully when result is None.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 7: Existing Portfolio Page Integration

### Task 9: `report_generator.py` — Stop Signal column in holdings table

**Files:**
- Modify: `report_generator.py:247-262` (generate_report signature) + `report_generator.py:119-168` (_build_holdings)

- [ ] **Step 1: Add `portfolio_stop_result` kwarg to `generate_report`**

`generate_report` 시그니처 (line ~247):

기존:
```python
def generate_report(
    market_data: dict,
    portfolio: list,
    signals: dict,
    history: dict,
    prev_signals: dict,
    output_path: str,
    template_dir: str | None = None,
    scanner_sp100: dict | None = None,
    scanner_etf: dict | None = None,
    scanner_kospi: dict | None = None,
    backtest_analysis: dict | None = None,
    nav_portfolio: str | None = None,
    active_nav: str = "portfolio",
    benchmark_data: dict | None = None,
) -> str:
```

변경:
```python
def generate_report(
    market_data: dict,
    portfolio: list,
    signals: dict,
    history: dict,
    prev_signals: dict,
    output_path: str,
    template_dir: str | None = None,
    scanner_sp100: dict | None = None,
    scanner_etf: dict | None = None,
    scanner_kospi: dict | None = None,
    backtest_analysis: dict | None = None,
    nav_portfolio: str | None = None,
    active_nav: str = "portfolio",
    benchmark_data: dict | None = None,
    portfolio_stop_result: dict | None = None,
) -> str:
```

- [ ] **Step 2: Build ticker → stop info map**

함수 본문 위쪽 (template 로드 이전), holdings 만들기 직전에 추가:

```python
    # Stop signal lookup (Task 9 통합)
    _stop_by_ticker: dict = {}
    if portfolio_stop_result and portfolio_stop_result.get("status") == "ok":
        for r in portfolio_stop_result.get("positions", []):
            _stop_by_ticker[r["ticker"]] = {
                "display_signal": r.get("display_signal"),
                "raw_signal": r.get("raw_signal"),
                "is_new_position": r.get("is_new_position", False),
                "below_stop_count": r.get("below_stop_count", 0),
                "stop_price": r.get("stop_price"),
                "gap_pct": r.get("gap_pct"),
                "mode": r.get("mode"),
            }
```

- [ ] **Step 3: Pass `_stop_by_ticker` to `_build_holdings` and inject fields**

`_build_holdings` 시그니처 변경 (line 119):

기존:
```python
def _build_holdings(portfolio: list, market_data: dict, signals: dict) -> list:
```

변경:
```python
def _build_holdings(portfolio: list, market_data: dict, signals: dict,
                    stop_by_ticker: dict | None = None) -> list:
```

함수 본문 마지막 holdings.append({...}) 안에 다음 필드 추가:

```python
            # Stop signal (Task 9)
            "stop_signal": (stop_by_ticker or {}).get(ticker, {}).get("display_signal"),
            "stop_is_new": (stop_by_ticker or {}).get(ticker, {}).get("is_new_position", False),
            "stop_below_count": (stop_by_ticker or {}).get(ticker, {}).get("below_stop_count", 0),
            "stop_price": (stop_by_ticker or {}).get(ticker, {}).get("stop_price"),
            "stop_gap_pct": (stop_by_ticker or {}).get(ticker, {}).get("gap_pct"),
            "stop_mode": (stop_by_ticker or {}).get(ticker, {}).get("mode"),
```

`generate_report` 함수 안의 호출부 변경:

기존:
```python
    holdings = _build_holdings(portfolio, market_data, signals)
```

변경:
```python
    holdings = _build_holdings(portfolio, market_data, signals, _stop_by_ticker)
```

- [ ] **Step 4: Render template with stop info**

`generate_report` 함수의 `template.render(...)` 호출에 다음 인자 추가:

```python
        portfolio_stop_summary=(
            portfolio_stop_result.get("summary")
            if portfolio_stop_result else None
        ),
        portfolio_stop_page=(
            f"portfolio_stops_{stop_by_owner_suffix}_{date_str}.html"
            if portfolio_stop_result and portfolio_stop_result.get("owner") != "me"
            else f"portfolio_stops_{date_str}.html"
        ) if portfolio_stop_result else None,
```

(주: `date_str`/`stop_by_owner_suffix`는 generate_report 안에 이미 정의된 변수가 아닐 수 있음 — 호출 시점의 값으로. 안전하게 결정:
```python
        portfolio_stop_page=(
            f"portfolio_stops_{portfolio_stop_result['date']}.html"
            if portfolio_stop_result and portfolio_stop_result.get("owner") == "me"
            else f"portfolio_stops_{portfolio_stop_result['owner']}_{portfolio_stop_result['date']}.html"
            if portfolio_stop_result else None
        ),
```
)

- [ ] **Step 5: Smoke test — generate_report standalone**

기존 호출이 깨지지 않는지 (`portfolio_stop_result` 미지정 시 None default):

```bash
python -c "
from report_generator import generate_report
import inspect
sig = inspect.signature(generate_report)
assert 'portfolio_stop_result' in sig.parameters
assert sig.parameters['portfolio_stop_result'].default is None
print('OK')
"
```

- [ ] **Step 6: Commit (combined with Task 8 since they depend on each other)**

```bash
git add report_generator.py pipeline.py
git commit -m "$(cat <<'EOF'
feat(stop): wire Step 4c3 stop signals into report_generator

generate_report() takes new portfolio_stop_result kwarg (default
None — backwards compatible). Builds ticker→stop lookup, passes
into _build_holdings to inject six stop_* fields (signal, is_new,
below_count, price, gap_pct, mode). Template gets stop summary
and page link for nav.

This commit is paired with the pipeline Step 4c3 integration
because both must land together — pipeline passes the new kwarg.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: `templates/report_template.html` — Stop column + nav

**Files:**
- Modify: `templates/report_template.html` (nav section + holdings table)

- [ ] **Step 1: Locate nav section**

```bash
grep -n 'class="nav-link"\|<nav' templates/report_template.html | head -5
```

- [ ] **Step 2: Add nav link**

기존 nav 항목들 사이 (`📊 Portfolio` 다음, `🧪 Backtest` 이전쯤) 추가:

```html
{% if portfolio_stop_summary %}
  <a class="nav-link {% if active_nav == 'stop' %}active{% endif %}"
     href="{{ portfolio_stop_page }}">🛡 Portfolio Risk</a>
{% endif %}
```

- [ ] **Step 3: Add Stop Signal column header to holdings table**

기존 holdings 테이블 `<thead>` 안, 기존 시그널 컬럼 다음에:

```html
<th>Stop Signal</th>
```

- [ ] **Step 4: Add Stop Signal cell to holdings rows**

기존 holdings 테이블 `<tbody>` 안의 `{% for h in holdings %}` 루프, 시그널 cell 다음에:

```html
<td class="stop-cell">
  {% if h.stop_signal %}
    {% set badge = {'HOLD':'hold','TIGHT':'tight','EXIT_READY':'exit-ready','EXIT':'exit'}[h.stop_signal] %}
    {% set label = {'HOLD':'🟢 HOLD','TIGHT':'🟡 TIGHT','EXIT_READY':'🟠 EXIT READY','EXIT':'🔴 EXIT'}[h.stop_signal] %}
    <span class="stop-badge stop-{{ badge }}">{{ label }}{% if h.stop_is_new %} (new){% endif %}{% if h.stop_below_count %} ({{ h.stop_below_count }}d){% endif %}</span>
  {% else %}
    <span class="stop-badge stop-none">—</span>
  {% endif %}
</td>
```

- [ ] **Step 5: Add CSS (in same template `<style>` block, end)**

```css
.stop-cell { white-space: nowrap; }
.stop-badge { padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }
.stop-badge.stop-hold { background: #064e3b; color: #6ee7b7; }
.stop-badge.stop-tight { background: #78350f; color: #fde68a; }
.stop-badge.stop-exit-ready { background: #9a3412; color: #fdba74; }
.stop-badge.stop-exit { background: #991b1b; color: #fecaca; }
.stop-badge.stop-none { background: #334155; color: #94a3b8; }
```

- [ ] **Step 6: Smoke test — render report and view**

```bash
SKIP_SCANNERS=1 python pipeline.py --skip-ocr --skip-fetch --auto
# 브라우저로 reports/report_<DATE>.html 열어 holdings 테이블에
# "Stop Signal" 컬럼 + 색상 배지 + (new) 표시 확인.
# nav에 "🛡 Portfolio Risk" 링크 표시 확인 → 클릭 시 stop 페이지 이동.
```

- [ ] **Step 7: Commit**

```bash
git add templates/report_template.html
git commit -m "$(cat <<'EOF'
feat(stop): add Stop Signal column + nav link to portfolio template

Holdings table gets a new "Stop Signal" cell rendering one of four
state badges with optional (new) marker and (Nd) breach count.
Nav adds 🛡 Portfolio Risk link to the corresponding owner's stop
page. Both elements are conditional on portfolio_stop_summary
being present — gracefully hidden when stop signals fail.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 8: Telegram Integration

### Task 11: `telegram_sender.py` — `send_portfolio_risk_summary`

**Files:**
- Modify: `telegram_sender.py` (add new function + invoke from pipeline)
- Test: `tests/test_telegram_portfolio_risk.py`

- [ ] **Step 1: Write failing tests (build only, no actual send)**

```python
# tests/test_telegram_portfolio_risk.py
"""telegram_sender.send_portfolio_risk_summary build_message 테스트."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from telegram_sender import _build_portfolio_risk_message


def _result(owner, hold=0, tight=0, ready=0, exit_=0, items=None):
    return {
        "status": "ok", "owner": owner, "date": "2026-05-07",
        "summary": {"HOLD": hold, "TIGHT": tight,
                     "EXIT_READY": ready, "EXIT": exit_},
        "positions": items or [],
        "changes": [],
    }


def _pos(ticker, signal, **kw):
    return {
        "ticker": ticker, "name": ticker, "display_signal": signal,
        "below_stop_count": kw.get("count", 0),
        "is_new_position": kw.get("is_new", False),
        "display_action": {"HOLD": "Hold", "TIGHT": "Trim 10~15%",
                            "EXIT_READY": "Trim 30~50%",
                            "EXIT": "Exit trading portion"}[signal],
    }


def test_message_basic_two_owners():
    me = _result("me", hold=10, tight=2, ready=1, exit_=0,
                  items=[_pos("AAPL", "TIGHT"), _pos("MSFT", "TIGHT"),
                         _pos("PLTR", "EXIT_READY", count=1)])
    wife = _result("wife", hold=5, tight=1, ready=0, exit_=0,
                    items=[_pos("SCHD", "TIGHT")])
    msg = _build_portfolio_risk_message(me, wife,
                                          base_url="https://example.com",
                                          date_str="2026-05-07")
    assert "Portfolio Risk Summary" in msg
    assert "[me]" in msg and "[wife]" in msg
    assert "AAPL" in msg or "MSFT" in msg
    assert "PLTR" in msg
    assert "SCHD" in msg
    assert len(msg) <= 3500


def test_message_overflow_truncation():
    """EXIT가 8개일 때 5만 표시 + '+N more'."""
    items = [_pos(f"T{i:02d}", "EXIT", count=2) for i in range(8)]
    me = _result("me", hold=0, tight=0, ready=0, exit_=8, items=items)
    msg = _build_portfolio_risk_message(me, None, base_url="https://x",
                                          date_str="2026-05-07")
    assert "+ 3 more" in msg or "more" in msg.lower()
    # 5개는 모두 노출
    for i in range(5):
        assert f"T{i:02d}" in msg


def test_message_wife_optional():
    me = _result("me", hold=1)
    msg = _build_portfolio_risk_message(me, None, base_url="x",
                                          date_str="2026-05-07")
    assert "[me]" in msg
    assert "[wife]" not in msg


def test_message_zero_alerts():
    """모두 HOLD면 EXIT/EXIT_READY/TIGHT 섹션 없음 (간결)."""
    me = _result("me", hold=20, tight=0, ready=0, exit_=0)
    msg = _build_portfolio_risk_message(me, None, base_url="x",
                                          date_str="2026-05-07")
    assert "🟢 HOLD (20)" in msg
    assert "🔴 EXIT" not in msg or "🔴 EXIT (0)" in msg


if __name__ == "__main__":
    test_message_basic_two_owners()
    test_message_overflow_truncation()
    test_message_wife_optional()
    test_message_zero_alerts()
    print("[OK] telegram_portfolio_risk tests passed.")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_telegram_portfolio_risk.py -v
# Expected: ImportError: cannot import name '_build_portfolio_risk_message'
```

- [ ] **Step 3: Add `_build_portfolio_risk_message` and `send_portfolio_risk_summary` to `telegram_sender.py`**

`def send_report(...)` 직전에 추가:

```python
# ─── Portfolio Stop Signal — risk summary ─────────────────

def _build_portfolio_risk_message(stop_me: dict | None,
                                  stop_wife: dict | None,
                                  base_url: str,
                                  date_str: str) -> str:
    from portfolio_stop_config import (
        TELEGRAM_MAX_EXIT_ITEMS, TELEGRAM_MAX_EXIT_READY_ITEMS,
        TELEGRAM_MAX_TIGHT_ITEMS,
    )

    def _by_signal(positions, sig):
        return [p for p in positions if p.get("display_signal") == sig]

    def _trim_list(items, max_n: int):
        if len(items) <= max_n:
            return items, 0
        return items[:max_n], len(items) - max_n

    def _line_full(p):
        c = p.get("below_stop_count", 0)
        suffix = f" ({c}d below stop)" if c else ""
        new_mark = " (new)" if p.get("is_new_position") else ""
        return f"  {p['ticker']}{new_mark} → {p.get('display_action','-')}{suffix}"

    def _section(title_fmt: str, positions, signal: str, max_n: int,
                  full=True):
        items = _by_signal(positions, signal)
        if not items:
            return ""
        kept, extra = _trim_list(items, max_n)
        title = title_fmt.format(n=len(items))
        if full:
            body = "\n".join(_line_full(p) for p in kept)
        else:
            body = "  " + ", ".join(p["ticker"] for p in kept)
        if extra:
            body += f"\n  + {extra} more — see report"
        return f"\n\n{title}\n{body}"

    def _owner_block(owner_label: str, result: dict) -> str:
        if not result or result.get("status") != "ok":
            return ""
        s = result.get("summary", {})
        positions = result.get("positions", [])
        head = (
            f"\n[{owner_label}]\n"
            f"🟢 HOLD ({s.get('HOLD',0)})  "
            f"🟡 TIGHT ({s.get('TIGHT',0)})  "
            f"🟠 EXIT_READY ({s.get('EXIT_READY',0)})  "
            f"🔴 EXIT ({s.get('EXIT',0)})"
        )
        body = ""
        body += _section("🔴 EXIT ({n}):", positions, "EXIT",
                          TELEGRAM_MAX_EXIT_ITEMS)
        body += _section("🟠 EXIT_READY ({n}):", positions, "EXIT_READY",
                          TELEGRAM_MAX_EXIT_READY_ITEMS)
        body += _section("🟡 TIGHT ({n}):", positions, "TIGHT",
                          TELEGRAM_MAX_TIGHT_ITEMS, full=False)
        return head + body

    parts = [f"🛡 Portfolio Risk Summary — {date_str}"]
    parts.append(_owner_block("me", stop_me))
    if stop_wife:
        parts.append(_owner_block("wife", stop_wife))

    base = base_url.rstrip("/")
    parts.append(f"\n\n📊 me:   {base}/portfolio_stops_{date_str}.html")
    if stop_wife:
        parts.append(f"📊 wife: {base}/portfolio_stops_wife_{date_str}.html")

    msg = "\n".join(p for p in parts if p)
    return msg[:3500]


def send_portfolio_risk_summary(stop_me: dict | None,
                                stop_wife: dict | None,
                                base_url: str,
                                date_str: str) -> bool:
    if not stop_me and not stop_wife:
        return False
    text = _build_portfolio_risk_message(stop_me, stop_wife, base_url, date_str)
    ok = _send_message(text)
    if ok:
        print("  [Telegram] Portfolio risk summary sent OK")
    else:
        print("  [Telegram] Portfolio risk summary send FAILED")
    return ok
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_telegram_portfolio_risk.py -v
# Expected: 4 passed
```

- [ ] **Step 5: Invoke `send_portfolio_risk_summary` from pipeline.py Step 5b**

`pipeline.py` Step 5b (`from telegram_sender import send_report as tg_send` 호출 다음, `except` 직전)에 추가:

```python
            # Portfolio Stop Signal summary (me + wife 합산)
            try:
                from telegram_sender import send_portfolio_risk_summary
                _base_url = os.environ.get(
                    "REPORT_BASE_URL",
                    "https://freecjs77-tech.github.io/AI-Trading-Assistant-v2",
                )
                # wife 결과는 Step 5d 끝나야 가능 — 여기선 me만 임시 처리?
                # 단순화: Step 5d 끝까지 wife 처리 후 _wife_stop_results를 모은 뒤,
                # Step 5d 종료 직후에 호출하도록 별도 위치(Section ② 참고).
            except Exception:
                pass
```

⚠ wife 결과는 Step 5d에서 만들어지므로 텔레그램 호출은 Step 5d **이후**가 자연스러움. Step 5d 루프 안에 `_wife_stop_results = {}` 모으고, Step 5d 종료 직후 (즉 Step 6 직전)에 다음 블록 추가:

```python
        # Portfolio Risk Telegram (Step 5d 끝난 후 wife 결과 합산해서 1회 발송)
        try:
            from telegram_sender import send_portfolio_risk_summary
            _base_url = os.environ.get(
                "REPORT_BASE_URL",
                "https://freecjs77-tech.github.io/AI-Trading-Assistant-v2",
            )
            # Step 5d 루프 안에서 owner_stop_result를 _wife_stop_results[_owner]로 저장해뒀다고 가정
            _wife_stop = (_wife_stop_results or {}).get("wife")
            send_portfolio_risk_summary(
                stop_me=stop_result_me,
                stop_wife=_wife_stop,
                base_url=_base_url,
                date_str=today,
            )
        except Exception as e:
            print(f"  WARN portfolio risk telegram failed: {e} (pipeline continues)")
```

⚠ 이를 위해 Step 5d 루프 시작 전에 `_wife_stop_results: dict = {}` 초기화하고, 루프 안 `owner_stop_result` 계산 후 `_wife_stop_results[_owner] = owner_stop_result` 저장.

- [ ] **Step 6: Smoke test pipeline**

```bash
SKIP_SCANNERS=1 python pipeline.py --skip-ocr --skip-fetch --auto
# Expected: Telegram 메시지에 "Portfolio risk summary sent OK"
```

- [ ] **Step 7: Commit**

```bash
git add telegram_sender.py pipeline.py tests/test_telegram_portfolio_risk.py
git commit -m "$(cat <<'EOF'
feat(stop): add send_portfolio_risk_summary telegram

Combined me/wife message with per-category truncation
(EXIT≤5, EXIT_READY≤7, TIGHT≤12) and "+N more" overflow marker.
3500-char safety trim. Display layer signals (TIGHT (new) for
new positions) preserved from generate_portfolio_stop_signals.

Pipeline invokes after Step 5d secondary owners loop completes,
so single message covers both owners.

4 unit tests cover basic format, overflow truncation,
optional wife, and quiet-mode (all HOLD).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 9: Operations

### Task 12: GitHub Actions workflow — gh-pages history restore

**Files:**
- Modify: `.github/workflows/daily-report.yml`

- [ ] **Step 1: Locate gh-pages restore section**

```bash
grep -n "gh-pages\|history" .github/workflows/daily-report.yml | head -20
```

- [ ] **Step 2: Add `portfolio_stops*.json` to restore list**

기존 `git checkout gh-pages -- history/...` 라인에 새 파일 추가:

```yaml
      - name: Restore history files from gh-pages
        run: |
          git fetch origin gh-pages --depth=1 || true
          git checkout origin/gh-pages -- history/signals_history.json \
                                            history/signals_history_wife.json \
                                            history/scanner_*_history.json \
                                            history/portfolio_daily*.json \
                                            history/outcomes.json \
                                            history/backtest_analysis.json \
                                            history/portfolio_stops.json \
                                            history/portfolio_stops_wife.json \
                                            || true
```

(워크플로우의 실제 들여쓰기/명령 형식은 기존 패턴에 맞춰 유지.)

- [ ] **Step 3: Verify gh-pages push includes new files**

`git add history/` 가 이미 있으면 자동 포함. 명시 add 패턴이라면 `history/portfolio_stops*.json` 추가:

```yaml
          git add history/signals_history*.json history/scanner_*.json \
                   history/portfolio_daily*.json history/outcomes.json \
                   history/backtest_analysis.json \
                   history/portfolio_stops*.json
```

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/daily-report.yml
git commit -m "$(cat <<'EOF'
ci: persist portfolio_stops*.json across gh-pages runs

Adds history/portfolio_stops.json + history/portfolio_stops_wife.json
to the workflow restore (start) and push (end) steps so trailing
stop state survives between daily Actions runs. Without this, every
run would re-bootstrap from yfinance YTD high — losing accumulated
below_stop_count, signal_history, and missing_since.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: Smoke test integration — `smoke_test.py`

**Files:**
- Modify: `smoke_test.py` (add stop signal sanity check)

- [ ] **Step 1: Locate smoke_test patterns**

```bash
grep -n "def check_\|def run_smoke" smoke_test.py | head
```

- [ ] **Step 2: Add stop signal check**

`smoke_test.py`에 신규 함수 추가:

```python
def check_portfolio_stop_signals(project_dir: str, today: str) -> dict:
    """Stop signal 산출물 존재 검증 (선택 — 파일 없어도 critical 아님)."""
    issues = []
    me_json = os.path.join(project_dir, "history", "portfolio_stops.json")
    me_html = os.path.join(project_dir, "reports",
                            f"portfolio_stops_{today}.html")
    if os.path.exists(me_json):
        # 페이지도 같이 있어야
        if not os.path.exists(me_html):
            issues.append({
                "severity": "warning",
                "msg": f"portfolio_stops.json 있는데 {today} 페이지 없음",
            })
    # wife는 선택 — 파일 부재는 정상
    return {"name": "portfolio_stop_signals", "issues": issues}
```

`run_smoke_test()` 안 체크 리스트에 추가:

```python
    checks.append(check_portfolio_stop_signals(project_dir, today))
```

- [ ] **Step 3: Commit**

```bash
git add smoke_test.py
git commit -m "$(cat <<'EOF'
feat(smoke): warn when stop history JSON exists but page missing

Catches the case where Step 4c3 ran (state file written) but page
generation step failed silently — would otherwise be invisible
until next run. Wife stop file absence remains acceptable.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 14: Golden sample test (regression protection)

**Files:**
- Create: `tests/fixtures/portfolio_stop_golden.json`
- Create: `tests/test_portfolio_stop_golden.py`

- [ ] **Step 1: Define golden fixture**

```bash
mkdir -p tests/fixtures
```

`tests/fixtures/portfolio_stop_golden.json`:

```json
{
  "_doc": "Golden sample for portfolio_stop_signal regression. Fixed inputs → fixed outputs.",
  "today": "2026-05-07",
  "tickers": {
    "NVDA": {
      "category": "Growth", "name": "NVIDIA Corp",
      "highest_close": 945.0, "atr14": 15.2, "today_close": 920.0,
      "prev_close": 915.0, "prev_below_count": 0, "is_new": false,
      "expected_mode": "MOMENTUM",
      "expected_stop": 899.4,
      "expected_raw": "TIGHT",
      "expected_display": "TIGHT"
    },
    "디아이티": {
      "ticker": "110990",
      "category": "KOSPI Stock", "name": "디아이티",
      "highest_close": 28000.0, "atr14": 1500.0, "today_close": 23200.0,
      "prev_close": 23500.0, "prev_below_count": 0, "is_new": false,
      "expected_mode": "HIGH_VOL",
      "expected_stop": 19600.0,
      "expected_raw": "HOLD",
      "expected_display": "HOLD"
    },
    "VOO": {
      "category": "ETF Core", "name": "Vanguard S&P 500 ETF",
      "highest_close": 540.0, "atr14": 5.0, "today_close": 470.0,
      "prev_close": 478.0, "prev_below_count": 1, "is_new": false,
      "expected_mode": "CORE",
      "expected_stop": 475.2,
      "expected_raw": "EXIT",
      "expected_display": "EXIT"
    },
    "CRCL": {
      "category": "Speculative", "name": "Circle Internet Group",
      "highest_close": 112.5, "atr14": 6.0, "today_close": 95.0,
      "prev_close": 96.0, "prev_below_count": 0, "is_new": true,
      "expected_mode": "HIGH_VOL",
      "expected_stop": 88.5,
      "expected_raw": "TIGHT",
      "expected_display": "TIGHT"
    }
  }
}
```

(주: 각 expected_* 값은 실제 공식으로 검증해 채움 — 1회 수동 계산:
- NVDA MOMENTUM: ATR×3 = 45.6 / min 8% = 75.6 / max 20% = 189 → distance=75.6 → stop=945-75.6=869.4? 어 — 이건 계산 mismatch — 실제 공식 다시 검토. ATR=15.2, multiplier=3 → atr_dist=45.6. min_dist=945*0.08=75.6. max_dist=945*0.20=189. distance=max(45.6,75.6)=75.6. min(75.6,189)=75.6. stop=945-75.6=869.4. round 2 = 869.40. → expected_stop을 869.40으로 수정.)

⚠ **테스트 작성자 주의**: golden fixture의 `expected_stop` 값은 step 2의 `calculate_stop` 함수 호출 결과로 직접 산출. 코드 작성 후 한 번 실행해 실제 결과를 fixture에 박는 게 안전.

- [ ] **Step 2: Write golden test (data-driven)**

```python
# tests/test_portfolio_stop_golden.py
"""Golden sample regression — 시그널 로직 변경 시 불변량 검증."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from portfolio_stop_signal import (
    get_stop_mode, calculate_stop, evaluate_signal,
)


def test_golden_sample():
    fixture_path = os.path.join(os.path.dirname(__file__),
                                  "fixtures", "portfolio_stop_golden.json")
    with open(fixture_path, encoding="utf-8") as f:
        gold = json.load(f)

    for label, t in gold["tickers"].items():
        ticker = t.get("ticker", label)
        mode = get_stop_mode(ticker, t["name"], t["category"])
        assert mode == t["expected_mode"], f"{label}: mode {mode} != {t['expected_mode']}"
        stop = calculate_stop(t["highest_close"], t["atr14"], mode, ticker)
        assert abs(stop - t["expected_stop"]) < 0.01, \
            f"{label}: stop {stop} != {t['expected_stop']}"
        ev = evaluate_signal(t["today_close"], stop, t["prev_below_count"],
                              t["is_new"])
        assert ev["raw_signal"] == t["expected_raw"], \
            f"{label}: raw {ev['raw_signal']} != {t['expected_raw']}"
        assert ev["display_signal"] == t["expected_display"], \
            f"{label}: display {ev['display_signal']} != {t['expected_display']}"


if __name__ == "__main__":
    test_golden_sample()
    print("[OK] golden sample passed.")
```

- [ ] **Step 3: Refine fixture by running once and capturing actual values**

```bash
pytest tests/test_portfolio_stop_golden.py -v
# 만약 실패하면, 실패 메시지에서 실제 stop 값을 확인하고 fixture 업데이트.
# 1회 실행으로 fixture 정합성 확정.
```

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/portfolio_stop_golden.json tests/test_portfolio_stop_golden.py
git commit -m "$(cat <<'EOF'
test(stop): add golden sample regression test

Four diverse fixtures (NVDA MOMENTUM mid-range, 디아이티 HIGH_VOL
KR, VOO CORE 2-day breach EXIT, CRCL HIGH_VOL new-position
display downgrade) lock in calculate_stop and evaluate_signal
results. Future logic changes that alter any of these break the
test loudly.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 15: CLAUDE.md 등재

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add entry under "## 진행 중인 계획"**

기존 진행 중인 계획 섹션 끝에 추가:

```markdown
- [Portfolio Stop Signal System v1.0](docs/superpowers/plans/2026-05-07-portfolio-stop-signal.md) — Pipeline Step 4c3 신규 · 4-state trailing stop (HOLD/TIGHT/EXIT_READY/EXIT) · me/wife 양쪽 적용 · 종가 기준 2-consecutive-close-breach EXIT · positions/snapshots 분리 schema · 신규 진입 종목 display downgrade · MOMENTUM/HIGH_VOL ATR 기반 + min/max% clamp · `fetch_market_data.py`에 `atr14`/`atr14_pct` 추가 · Telegram 합산 알림 · 자동매매 ❌ / 매도 판단 보조 ✅
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: register portfolio-stop-signal plan in CLAUDE.md

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 10: Final Verification

### Task 16: End-to-end smoke test + first deploy preparation

- [ ] **Step 1: Full pipeline run from clean state**

```bash
# 기존 상태 백업
cp history/portfolio_stops.json{,.bak} 2>/dev/null
cp history/portfolio_stops_wife.json{,.bak} 2>/dev/null

# 클린 상태에서 첫 실행 (yfinance bootstrap 동작 검증)
rm -f history/portfolio_stops*.json
python pipeline.py --skip-ocr --auto
# Expected: bootstrap 실행 (~2분), Step 4c3 me + wife 모두 OK,
#           reports/portfolio_stops_*.html 생성, Telegram 발송
```

- [ ] **Step 2: Verify outputs**

```bash
# JSON 무결성
python -c "import json; d=json.load(open('history/portfolio_stops.json')); \
  print('me positions:', len(d['positions']), \
        'snapshots:', len(d['snapshots']))"
python -c "import json; d=json.load(open('history/portfolio_stops_wife.json')); \
  print('wife positions:', len(d['positions']), \
        'snapshots:', len(d['snapshots']))"

# HTML 무결성 — DOCTYPE 시작, table 존재
grep -q "<!DOCTYPE html>" reports/portfolio_stops_*.html && echo OK || echo FAIL
grep -q "Stop Gap" reports/portfolio_stops_*.html && echo OK || echo FAIL
```

- [ ] **Step 3: Visual review (browser)**

브라우저로 다음 페이지 열어 확인:
- `reports/report_<DATE>.html`: holdings 테이블에 Stop Signal 컬럼 표시 + nav 🛡 Portfolio Risk 링크
- `reports/portfolio_stops_<DATE>.html`: hero, 4 cards, table, footer 정상
- `reports/portfolio_stops_wife_<DATE>.html`: 동일 (wife)
- KR 종목 stop은 정수 표기, US는 소수 2자리
- 신규 진입 종목 (entry_date 후 14일 이내) → ⓝ 표시, EXIT/EXIT_READY인 경우 TIGHT (new)로 다운그레이드

- [ ] **Step 4: Run full test suite**

```bash
pytest tests/test_portfolio_stop*.py tests/test_fetch_market_data_atr.py \
        tests/test_telegram_portfolio_risk.py -v
# Expected: all green
```

- [ ] **Step 5: Run pipeline smoke test for backwards compat**

```bash
pytest tests/test_portfolio_history_core.py tests/test_benchmark_ytd.py \
        tests/test_scanner_data.py -v
# Expected: still green (no regressions)
```

- [ ] **Step 6: Day-2 idempotency test**

```bash
# 첫 실행 후 다시 실행 — bootstrap 안 일어나야 (~수 초)
time python pipeline.py --skip-ocr --skip-fetch --auto
# Expected: <30s. "[stop_history] Bootstrap" 로그 없음.
# positions['NVDA'].highest_close 동일 / below_stop_count 정상 추적.
```

- [ ] **Step 7: Restore backup and commit only the registration**

```bash
# 테스트가 history 파일을 변경했을 수 있으니 백업 복원 (의도적 운영 데이터 보존)
cp history/portfolio_stops.json.bak history/portfolio_stops.json 2>/dev/null
cp history/portfolio_stops_wife.json.bak history/portfolio_stops_wife.json 2>/dev/null
rm -f history/portfolio_stops.json.bak history/portfolio_stops_wife.json.bak

# 첫 운영은 GitHub Actions에서 자연 시작 — 로컬 history 커밋 불필요
git status
# Expected: clean (코드는 이미 위 단계에서 커밋됨)
```

- [ ] **Step 8: Push & open PR (or merge)**

```bash
git push -u origin feature/portfolio-stop-signal
# 또는 직접 master 머지 (정책에 따라)
```

---

## Self-Review Checklist (작성자 점검용)

이 plan이 spec을 모두 커버하는지 작성 후 점검:

- [x] §0 Summary / 핵심 철학 → Task 1~16 전반에 반영
- [x] §1 Goals / Non-goals → v1 scope (auto-trade 제외, intraday 제외) 명시
- [x] §2 Architecture (Step 4c3, 4 modules, market vs state 분리) → Task 1, 2, 3, 4, 5
- [x] §3 Mode System → Task 2 (config) + Task 4 (get_stop_mode)
- [x] §3.3 calculate_stop with min/max clamp + KR rounding → Task 4
- [x] §4 Signal Logic (4-state machine, below_stop_count `<=`, display downgrade) → Task 4
- [x] §5 Bootstrap & Lifecycle (2026-01-02 anchor, 3-day grace, missing_since) → Task 3, 5
- [x] §6 Schema (positions + snapshots split, 730-day prune) → Task 3
- [x] §7 UI (전용 페이지, KR=정수/US=소수, ⓝ 표시) → Task 6, 7
- [x] §8 Telegram (per-category limits, +N more) → Task 11
- [x] §9 Pipeline integration → Task 8 (Step 4c3 + 5d), Task 9 (report_generator)
- [x] §10 Tests (단위/lifecycle/golden) → Task 4 (signal), Task 3 (history), Task 14 (golden)
- [x] §11 Risks → Task 1 (atr14 NaN safe), Task 3 (jump guard, soft-archive)
- [x] §12 v1.1/v2 (제외) → 본 plan 미포함
- [x] §13 Q&A → 본 plan에서 결정한 패턴 반영

✅ Spec 누락 없음.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-07-portfolio-stop-signal.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Fresh subagent per task with two-stage review between tasks; fastest iteration, isolated context.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`; batch execution with checkpoints for review.

Which approach?
