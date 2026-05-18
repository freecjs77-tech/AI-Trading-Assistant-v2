# Momentum US Universe Swap (IWB → SP100∪NDX100) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** US momentum 스캐너의 base universe를 IWB Russell 1000 (~1007 ticker) → 기존 `market_scanner.SP100_TICKERS` (S&P 100 ∪ NASDAQ 100, 169 ticker)로 교체하여 (1) 리포트 생성 시간 단축, (2) BlackRock IWB CSV anti-bot 의존성 제거.

**Architecture:**
- `momentum_universe.build_us_universe()`가 `md.get_iwb_holdings()` 대신 `market_scanner.SP100_TICKERS`를 base로 사용. `get_weekly_top_liquidity` + `fetch_daily_movers_for` 합집합 로직은 그대로 유지 (이제 169 ticker 위에서 작동하니 자연스럽게 빨라짐).
- IWB fetch 코드 (`fetch_iwb_holdings`, `get_iwb_holdings`, `parse_ishares_csv`, `normalize_symbol`, `IWB_URL`, `ISHARES_TICKER_COLS`) 전부 제거 — D1 결정에 따라 IWB fallback 미보존. 향후 복원 필요 시 git history에서 회수.
- 시그널 로직 (M1/M2/M3, EM tier, Maturity 분류기), history schema, 캐시 키 모두 무변경. EM track의 universe coverage가 IWB → SP100∪NDX100로 좁아지는 점은 design tradeoff로 수용 (mid-cap structural inflection 노출 손실).
- gh-pages의 `data/iwb_holdings.json`은 코드에서 더 이상 읽히지 않지만 workflow의 `cp -r data` 패스스루로 deploy에 계속 carry-forward됨 — 무해. 별도 cleanup은 본 plan 범위 밖.

**Tech Stack:** Python 3.11+, pytest, yfinance, pandas. 신규 의존성 없음.

**Files affected:**
- Modify: `momentum_universe.py` (lines 4-8 docstring, 69-83 `build_us_universe`)
- Modify: `momentum_data.py` (lines 127-203 IWB 블록 전체 제거)
- Modify: `momentum_scanner.py` (line 227 주석 1줄)
- Modify: `tests/test_momentum_universe.py` (lines 21-72 — 3개 테스트)
- Modify: `tests/test_momentum_data.py` (lines 90-122, 331-334 — normalize_symbol + parse_ishares_csv 테스트 삭제)
- Delete: `tests/fixtures/iwb_sample.csv`
- Modify: `CLAUDE.md` ("진행 중인 계획" 섹션에 항목 추가)

---

## Task 1: Test `build_us_universe` uses `SP100_TICKERS` as base (TDD red)

**Files:**
- Modify: `tests/test_momentum_universe.py:21-44, 65-78`

Existing 3 tests mock `iwb_holdings` cache. Rewrite them to patch `market_scanner.SP100_TICKERS` instead — this defines the new contract.

- [ ] **Step 1: Replace 3 existing tests in `tests/test_momentum_universe.py`**

Open `tests/test_momentum_universe.py` and replace `test_build_us_universe_unions_sources`, `test_build_us_universe_caps_at_1500`, and `test_build_us_universe_dedup_preserves_order` (lines 21-44 and 65-78) with the versions below. Leave `test_build_kr_universe_uses_kospi_tickers` and `test_kr_movers_drops_all_when_volumes_empty` untouched.

```python
def test_build_us_universe_unions_sources():
    """US universe = SP100∪NDX100 ∪ weekly_top100 ∪ daily_movers."""
    tmp = setup()
    try:
        fake_base = ["AAPL", "MSFT", "NVDA"]
        md.save_cache("weekly_liquidity_us", ["TSLA"], status="ok")
        with patch("market_scanner.SP100_TICKERS", fake_base), \
             patch("momentum_universe.fetch_daily_movers_for", return_value=["AMD"]):
            uni = mu.build_us_universe()
        assert set(uni) == {"AAPL", "MSFT", "NVDA", "TSLA", "AMD"}
    finally:
        teardown(tmp)


def test_build_us_universe_caps_at_1500():
    """V1.0 안전장치 — universe 1500개 초과 절대 금지. (현실에서는 169
    base + 작은 weekly/daily 보강이라 cap에 닿을 일이 없지만 안전장치 검증.)"""
    tmp = setup()
    try:
        big_base = [f"T{i}" for i in range(2000)]
        md.save_cache("weekly_liquidity_us", [], status="ok")
        with patch("market_scanner.SP100_TICKERS", big_base), \
             patch("momentum_universe.fetch_daily_movers_for", return_value=[]):
            uni = mu.build_us_universe()
        assert len(uni) <= 1500
    finally:
        teardown(tmp)


def test_build_us_universe_dedup_preserves_order():
    """중복 제거되지만 base가 먼저 등장한 순서를 유지."""
    tmp = setup()
    try:
        fake_base = ["AAPL", "MSFT"]
        md.save_cache("weekly_liquidity_us", ["MSFT", "TSLA"], status="ok")
        with patch("market_scanner.SP100_TICKERS", fake_base), \
             patch("momentum_universe.fetch_daily_movers_for", return_value=["AAPL"]):
            uni = mu.build_us_universe()
        assert uni.index("AAPL") < uni.index("MSFT") < uni.index("TSLA")
        assert uni.count("AAPL") == 1
        assert uni.count("MSFT") == 1
    finally:
        teardown(tmp)
```

- [ ] **Step 2: Run the updated tests to verify they fail**

Run:
```bash
python -m pytest tests/test_momentum_universe.py::test_build_us_universe_unions_sources tests/test_momentum_universe.py::test_build_us_universe_caps_at_1500 tests/test_momentum_universe.py::test_build_us_universe_dedup_preserves_order -v
```

Expected: all 3 FAIL. Failure reason: `build_us_universe` still reads `md.get_iwb_holdings()` cache (no `iwb_holdings` cache exists in the tmp dir, so it would try a fresh fetch and either fail or return empty), so the assertions won't match `{"AAPL", "MSFT", "NVDA", "TSLA", "AMD"}`.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_momentum_universe.py
git commit -m "test(momentum): SP100∪NDX100 base universe contract (failing)"
```

---

## Task 2: Swap base in `build_us_universe` (TDD green)

**Files:**
- Modify: `momentum_universe.py:4-8` (module docstring)
- Modify: `momentum_universe.py:69-83` (`build_us_universe`)

- [ ] **Step 1: Update module docstring and `build_us_universe`**

Replace lines 1-8 of `momentum_universe.py`:

```python
"""
Market Momentum Scanner — Universe 조립.

US: SP100∪NDX100 ∪ weekly_top100 ∪ daily_movers (≤ 1500 cap)
    Source: market_scanner.SP100_TICKERS (169 ticker, S&P 100 ∪ NASDAQ 100).
    이전 design (IWB Russell 1000)은 BlackRock anti-bot 차단 + universe
    과대로 인한 처리 시간 문제로 2026-05-18 폐기.
KR: KOSPI_TICKERS (market_scanner 101-ticker curated list)
    ∪ weekly_top100 ∪ daily_movers (잡주 필터: 거래대금 5일평균 ≥ 100억원만)
    Note: KRX public API requires auth since 2025 — using static list instead.
"""
```

Replace `build_us_universe` (lines 69-83 in original; line numbers will shift after docstring edit):

```python
def build_us_universe() -> list[str]:
    """
    US_BASE = SP100∪NDX100 (market_scanner.SP100_TICKERS, 169 ticker)
    US_WEEKLY = base 거래대금 5일 평균 Top100
    US_DAILY  = base 중 (1d ≥ +5% OR 3d ≥ +8%) AND close > MA20
    Return: 합집합 (≤ 1500 cap — 169 base에서는 사실상 cap 미적용)

    Note: 2026-05-18 이전에는 IWB Russell 1000 holdings (~1007 ticker)을
    base로 사용했으나, (a) BlackRock CSV endpoint의 anti-bot 차단, (b) ~1000
    ticker × yfinance 90d bulk fetch의 처리 시간 문제로 SP100∪NDX100 base로
    교체. EM tier의 mid-cap structural inflection 노출은 design tradeoff로
    수용 (Russell 1000 600~1000위 mid-cap 노출 손실).
    """
    try:
        from market_scanner import SP100_TICKERS
    except ImportError:
        print("[universe] WARN market_scanner.SP100_TICKERS unavailable")
        return []
    base = list(SP100_TICKERS)

    weekly = get_weekly_top_liquidity("weekly_liquidity_us", base, market="us")
    daily = fetch_daily_movers_for(base, market="us")
    uni = _dedup_preserve_order(base + list(weekly) + list(daily))
    if len(uni) > UNIVERSE_CAP:
        print(f"[universe] WARN US universe {len(uni)} > cap {UNIVERSE_CAP} — truncating")
        uni = uni[:UNIVERSE_CAP]
    return uni
```

- [ ] **Step 2: Run the 3 universe tests, verify they pass**

```bash
python -m pytest tests/test_momentum_universe.py::test_build_us_universe_unions_sources tests/test_momentum_universe.py::test_build_us_universe_caps_at_1500 tests/test_momentum_universe.py::test_build_us_universe_dedup_preserves_order -v
```

Expected: all 3 PASS.

- [ ] **Step 3: Run the full `test_momentum_universe.py` to ensure no regression in KR tests**

```bash
python -m pytest tests/test_momentum_universe.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 4: Commit implementation**

```bash
git add momentum_universe.py
git commit -m "feat(momentum): swap US base from IWB to SP100∪NDX100 (169 ticker)"
```

---

## Task 3: Remove dead IWB code from `momentum_data.py`

After Task 2, `get_iwb_holdings` has no callers. Together with its helpers (`fetch_iwb_holdings`, `parse_ishares_csv`, `normalize_symbol`, `IWB_URL`, `ISHARES_TICKER_COLS`) it forms a self-contained block at lines 127-203.

**Files:**
- Modify: `momentum_data.py:127-203` (delete lines)

- [ ] **Step 1: Verify no remaining callers**

```bash
grep -rn "get_iwb_holdings\|fetch_iwb_holdings\|parse_ishares_csv\|normalize_symbol\|IWB_URL\|ISHARES_TICKER_COLS" --include="*.py" .
```

Expected: matches only in `momentum_data.py` (definitions) and `tests/test_momentum_data.py` (which we'll clean in Task 4). No callers in `momentum_universe.py` (we just removed them) or anywhere else.

- [ ] **Step 2: Delete the IWB block in `momentum_data.py`**

Delete the entire block from line 127 (the comment `# ─...iShares CSV 파싱`) through line 203 (the closing of `get_iwb_holdings`). That includes:

```python
# ───────────────────────────────────────────────────────────────────────────────
# iShares CSV 파싱 (Task 4)
# ───────────────────────────────────────────────────────────────────────────────

IWB_URL = (
    "https://www.ishares.com/us/products/239707/ishares-russell-1000-etf/"
    "1467271812596.ajax?fileType=csv&fileName=IWB_holdings&dataType=fund"
)

# iShares CSV는 종종 컬럼명이 변경됨 — fallback 후보
ISHARES_TICKER_COLS = ["Ticker", "Ticker Symbol", "Issuer Ticker"]


def normalize_symbol(symbol: str) -> str | None:
    ...


def parse_ishares_csv(csv_bytes: bytes) -> list[str]:
    ...


def fetch_iwb_holdings() -> list[str]:
    ...


def get_iwb_holdings(force_refresh: bool = False) -> list[str]:
    ...
```

After deletion, the file should jump from the `fetch_with_fallback` block straight to the next section comment (`# KRX ETF 구성종목 (Task 5)` at original line 206).

Also remove the now-unused `import csv` and `import re` imports if they were only used by these functions. Check by:

```bash
grep -n "^import csv\|^import re\|csv\.\|re\." momentum_data.py | head -20
```

If `csv` is only referenced inside the deleted block, remove its top-level `import csv`. Same for `re`. If they're used elsewhere in the file, leave them.

- [ ] **Step 3: Sanity check — module still imports**

```bash
python -c "import momentum_data; print('ok')"
```

Expected: `ok` (no `ImportError`, no `NameError`).

- [ ] **Step 4: Run full momentum_data test file (will still fail on IWB tests — that's Task 4)**

```bash
python -m pytest tests/test_momentum_data.py -v
```

Expected: tests for `normalize_symbol`, `parse_iwb_csv_*` FAIL with `AttributeError` (functions no longer exist). All other tests in the file PASS.

- [ ] **Step 5: Commit dead code removal**

```bash
git add momentum_data.py
git commit -m "refactor(momentum): drop IWB CSV fetch — no longer used after base swap"
```

---

## Task 4: Remove orphaned IWB tests from `test_momentum_data.py`

**Files:**
- Modify: `tests/test_momentum_data.py:90-122, 331-334` (delete 4 tests + the `__main__` calls)
- Delete: `tests/fixtures/iwb_sample.csv`

- [ ] **Step 1: Delete `test_normalize_symbol` (lines 90-97 in original)**

Delete the function:

```python
def test_normalize_symbol():
    """normalize_symbol — 심볼 정규화 및 캐시/빈값 필터링."""
    assert md.normalize_symbol("AAPL") == "AAPL"
    assert md.normalize_symbol("BRK.B") == "BRK-B"
    assert md.normalize_symbol("BF.B") == "BF-B"
    assert md.normalize_symbol("-") is None    # cash row
    assert md.normalize_symbol("") is None
    assert md.normalize_symbol("   ") is None
```

- [ ] **Step 2: Delete the 3 `parse_iwb_csv_*` tests (lines 100-122 in original)**

Delete all of:

```python
def test_parse_iwb_csv_with_known_column():
    ...


def test_parse_iwb_csv_with_alternative_column():
    ...


def test_parse_iwb_csv_unknown_column_raises():
    ...
```

- [ ] **Step 3: Remove the 4 entries from the `__main__` block (lines 331-334)**

In the bottom `if __name__ == "__main__":` block, remove these 4 lines:

```python
test_normalize_symbol()
test_parse_iwb_csv_with_known_column()
test_parse_iwb_csv_with_alternative_column()
test_parse_iwb_csv_unknown_column_raises()
```

- [ ] **Step 4: Delete the fixture file**

```bash
git rm tests/fixtures/iwb_sample.csv
```

- [ ] **Step 5: Run the full test file**

```bash
python -m pytest tests/test_momentum_data.py -v
```

Expected: all remaining tests PASS, no `AttributeError`.

- [ ] **Step 6: Commit test cleanup**

```bash
git add tests/test_momentum_data.py tests/fixtures/iwb_sample.csv
git commit -m "test(momentum): drop IWB parser tests + fixture (orphaned after base swap)"
```

---

## Task 5: Update stale IWB comment in `momentum_scanner.py`

**Files:**
- Modify: `momentum_scanner.py:227`

- [ ] **Step 1: Update the comment**

Find line 227:
```python
            # M+ uses Top sectors only; EM uses Full IWB.
```

Replace with:
```python
            # M+ uses Top sectors only; EM uses Full base (SP100∪NDX100).
```

- [ ] **Step 2: Sanity check — module still imports**

```bash
python -c "import momentum_scanner; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add momentum_scanner.py
git commit -m "docs(momentum): update EM-scope comment to reflect new base"
```

---

## Task 6: Add plan entry to `CLAUDE.md` "진행 중인 계획"

**Files:**
- Modify: `CLAUDE.md` (the bulleted "진행 중인 계획" list)

- [ ] **Step 1: Add a new bullet at the top of the "진행 중인 계획" section**

Open `CLAUDE.md`. Find the `## 진행 중인 계획` heading. Right after it, insert this bullet as the FIRST item in the list:

```markdown
- [Momentum US Universe Swap (IWB→SP100∪NDX100)](docs/superpowers/plans/2026-05-18-momentum-us-universe-swap-to-sp100ndx.md) — Pipeline Step 4c2 base 교체 · `momentum_universe.build_us_universe` base를 IWB Russell 1000 (~1007) → `market_scanner.SP100_TICKERS` (169) · BlackRock anti-bot 의존성 제거 · IWB fetch/parse 코드 + 테스트 + fixture 삭제 · M1/M2/M3/EM 시그널 로직·history·캐시키 모두 무변경 · EM tier의 mid-cap 노출 손실은 design tradeoff
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add IWB→SP100∪NDX100 swap plan to progress list"
```

---

## Task 7: End-to-end smoke run (US momentum no longer fails)

Locally re-run the momentum_only pipeline to confirm US momentum now succeeds (whereas it previously CRITICAL-failed on IWB fetch). KR should be unchanged.

- [ ] **Step 1: Run pipeline in momentum_only mode (US should now succeed)**

```bash
export MODE=momentum_only PYTHONIOENCODING=utf-8
start=$(date +%s)
python pipeline.py 2>&1 | tee momentum_smoke_after.log
end=$(date +%s)
echo "===== Elapsed: $((end-start))s ====="
```

Expected log lines:
```
[Step 4c2] Momentum scanners (US + KR)...
  OK [Step 4c2] Momentum US: M3=<n> M2=<n> M1=<n>
  OK [Step 4c2] Momentum KR: M3=<n> M2=<n> M1=<n>
```

CRITICAL: must NOT see `CRITICAL US scan failed: No known ticker column` anymore. The IWB CSV download is no longer attempted.

- [ ] **Step 2: Confirm universe size in log (sanity check)**

```bash
grep -E "universe|scanning|tickers" momentum_smoke_after.log | head -20
```

Expected: any universe count reported for US should be ≤200 (169 base + small weekly/daily addition).

- [ ] **Step 3: Run the full momentum test suite as a final regression gate**

```bash
python -m pytest tests/test_momentum_universe.py tests/test_momentum_data.py tests/test_momentum_scanner.py tests/test_momentum_signal.py tests/test_momentum_history.py tests/test_momentum_backtest.py tests/test_momentum_change_fields.py tests/test_momentum_templates.py tests/test_momentum_nav.py tests/test_momentum_telegram.py tests/test_e2e_momentum_smoke.py tests/test_pipeline_momentum_step.py tests/test_pipeline_momentum_wiring.py -v
```

Expected: ALL PASS (no failures, no errors).

- [ ] **Step 4: Stage the smoke log for review (do not commit it — it's just evidence for the reviewer)**

```bash
ls -la momentum_smoke_after.log
echo "Smoke log retained for review; not committed (transient)."
```

- [ ] **Step 5: Confirm clean git status**

```bash
git status
```

Expected: working tree clean except `momentum_smoke_after.log` and `momentum_em_off_run.log` (the earlier debug log) listed as untracked. Both are local-only smoke evidence — leave them untracked. No staged changes.

---

## Self-Review Checklist

- **Spec coverage:** Every requirement covered?
  - ✅ Base swap to SP100_TICKERS: Task 2
  - ✅ IWB code removed: Task 3
  - ✅ Orphaned tests/fixtures removed: Task 4
  - ✅ Stale comment fix: Task 5
  - ✅ Plan registered in CLAUDE.md: Task 6
  - ✅ Smoke validation: Task 7
  - ✅ TDD red→green discipline: Task 1→2

- **Placeholder scan:** No TBD/TODO/fill-in. All code shown in full. ✅

- **Type consistency:** `SP100_TICKERS` referenced consistently. Cache key `weekly_liquidity_us` unchanged. Universe assembly function signature unchanged. ✅

- **Files-that-change-together:** `momentum_universe.py` change in Task 2 makes IWB code in `momentum_data.py` dead — both files in same logical "remove IWB dependency" change, but split into 2 commits for atomicity (Task 2 = swap, Task 3 = cleanup). Tests split similarly (Task 1 = contract update, Task 4 = orphan cleanup). ✅
