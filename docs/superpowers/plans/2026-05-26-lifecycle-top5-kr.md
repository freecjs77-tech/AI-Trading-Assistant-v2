# Lifecycle KR Top 5 Buy Candidates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lifecycle KR 페이지에 "🎯 오늘의 매수 후보 (보유 추가 포함) — Top N/5" 섹션 추가. KR 전용 threshold 3.0 (US: 5.0) + ticker 옆 한글 종목명 표시.

**Architecture:** Python plumbing은 이미 KR을 지원 — universe-expansion 작업으로 `pipeline.py → generate_lifecycle_pages → _render("KR") → select_top5_buy_candidates`까지 완성됨. 변경 표면은 `lifecycle_report._render`의 작은 KR 분기(threshold + name attach) 2개와 `lifecycle_kr.html` 신규 섹션. 신규 모듈/시그니처 변경 없음.

**Tech Stack:** Python 3.10+, Jinja2, pytest (모두 기존 stack), 신규 의존성 없음.

**Spec:** [docs/superpowers/specs/2026-05-26-lifecycle-top5-kr-design.md](../specs/2026-05-26-lifecycle-top5-kr-design.md)

---

## File Structure

**Create:**
- (없음 — 모든 변경은 기존 파일 수정)

**Modify:**
- `lifecycle_report.py:297-365` — `_render` 내 `select_top5_buy_candidates` 호출에 `threshold` kwarg 추가 + KR 시장이면 candidates에 `name` attach
- `templates/lifecycle_kr.html:66-215` (두 번째 `<style>` 블록) — Top 5 섹션 CSS 추가
- `templates/lifecycle_kr.html:253-256` — summary-box 직후 `<section id="top5-buy-candidates">` 추가
- `tests/test_lifecycle_buy_candidates.py` — KR 전용 테스트 3개 추가
- `CLAUDE.md` (진행 중인 계획 리스트) — plan 한 줄 추가

**Out of scope:**
- Telegram brief KR 알림
- KR-specific scoring 가중치 변경
- US 페이지 / golden 출력 변경
- `select_top5_buy_candidates` 시그니처 변경 (threshold는 기존 kwarg 재사용)

---

## Task 1: `_render` — KR 전용 threshold 3.0 (TDD)

**Files:**
- Modify: `lifecycle_report.py:337-346` (`select_top5_buy_candidates` 호출 부분)
- Modify: `tests/test_lifecycle_buy_candidates.py`

`_render(market, ...)`가 KR이면 threshold=3.0, 그 외는 5.0 — 항상 explicit하게 전달.

- [ ] **Step 1: Write failing test**

Append to `tests/test_lifecycle_buy_candidates.py`:

```python
def test_render_uses_kr_threshold_3(monkeypatch, tmp_path):
    """_render('KR', ...) must call select_top5 with threshold=3.0."""
    import lifecycle_report as lr

    captured: dict = {}

    def fake_select(**kwargs):
        captured.update(kwargs)
        return {"candidates": [], "count": 0, "max": 5, "threshold": kwargs.get("threshold", 5.0)}

    monkeypatch.setattr(lr, "select_top5_buy_candidates", fake_select)

    from jinja2 import Template
    monkeypatch.setattr(Template, "render", lambda self, **ctx: "<html></html>")

    result = {
        "as_of": "2026-05-26", "market": "KR",
        "snapshots": {"005930": {"setup": "TREND_OK"}},
        "transitions": [], "skipped": [], "active_set_size": 1,
        "market_ret_5d_pct": 0.0,
        "momentum_history": {"data": {}},
        "engine_version": "score_v1",
    }
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    lr._render("KR", result, str(out_dir), template_dir=None,
                lifecycle_state={"tickers": {}, "transitions": []},
                portfolio_tickers=set())

    assert captured.get("threshold") == 3.0


def test_render_uses_us_threshold_5(monkeypatch, tmp_path):
    """_render('US', ...) must call select_top5 with threshold=5.0."""
    import lifecycle_report as lr

    captured: dict = {}

    def fake_select(**kwargs):
        captured.update(kwargs)
        return {"candidates": [], "count": 0, "max": 5, "threshold": kwargs.get("threshold", 5.0)}

    monkeypatch.setattr(lr, "select_top5_buy_candidates", fake_select)

    from jinja2 import Template
    monkeypatch.setattr(Template, "render", lambda self, **ctx: "<html></html>")

    result = {
        "as_of": "2026-05-26", "market": "US",
        "snapshots": {"AAPL": {"setup": "TREND_OK"}},
        "transitions": [], "skipped": [], "active_set_size": 1,
        "market_ret_5d_pct": 0.0,
        "momentum_history": {"data": {}},
        "engine_version": "score_v1",
    }
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    lr._render("US", result, str(out_dir), template_dir=None,
                lifecycle_state={"tickers": {}, "transitions": []},
                portfolio_tickers=set())

    assert captured.get("threshold") == 5.0
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_render_uses_kr_threshold_3 tests/test_lifecycle_buy_candidates.py::test_render_uses_us_threshold_5 -xvs
```

Expected: KR test FAIL — `captured.get("threshold")` is `None` (현재 `_render`는 threshold를 explicit하게 넘기지 않음). US test도 같은 이유로 FAIL.

- [ ] **Step 3: Modify `lifecycle_report.py::_render` — threshold 분기 추가**

`lifecycle_report.py`에서 `select_top5_buy_candidates(...)` 호출 직전에 threshold 결정 줄을 추가하고 kwarg로 전달:

Find (around L337-346):
```python
    # Top 5 Buy Candidates section
    top5 = select_top5_buy_candidates(
        snapshots=result.get("snapshots") or {},
        portfolio_tickers=portfolio_tickers or set(),
        momentum_history=result.get("momentum_history") or {"data": {}},
        today=result["as_of"],
        momentum_today=momentum_today,
        market_data=market_data,
        market_ret_5d_pct=result.get("market_ret_5d_pct"),
    )
```

Replace with:
```python
    # Top 5 Buy Candidates section — KR universe is smaller, lower threshold
    top5_threshold_for_market = 3.0 if market == "KR" else 5.0
    top5 = select_top5_buy_candidates(
        snapshots=result.get("snapshots") or {},
        portfolio_tickers=portfolio_tickers or set(),
        momentum_history=result.get("momentum_history") or {"data": {}},
        today=result["as_of"],
        momentum_today=momentum_today,
        market_data=market_data,
        market_ret_5d_pct=result.get("market_ret_5d_pct"),
        threshold=top5_threshold_for_market,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_render_uses_kr_threshold_3 tests/test_lifecycle_buy_candidates.py::test_render_uses_us_threshold_5 -xvs
```

Expected: PASS (2 tests).

- [ ] **Step 5: Run lifecycle test suite for regression**

```
python -m pytest tests/test_lifecycle_buy_candidates.py tests/test_lifecycle_report.py -x
```

Expected: All pass.

- [ ] **Step 6: Commit**

```
git add lifecycle_report.py tests/test_lifecycle_buy_candidates.py
git commit -m "feat(top5-kr): use threshold 3.0 for KR, 5.0 for US"
```

---

## Task 2: `_render` — KR 한글명 attach (TDD)

**Files:**
- Modify: `lifecycle_report.py:337-350` (Task 1에서 수정한 곳 직후)
- Modify: `tests/test_lifecycle_buy_candidates.py`

`_render`가 KR이면 `select_top5` 호출 후 각 candidate에 `name = _lookup_ticker_name(ticker, "KR")`을 부여. US는 무변경.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_lifecycle_buy_candidates.py`:

```python
def test_render_kr_attaches_korean_name_to_top5(monkeypatch, tmp_path):
    """_render('KR', ...) attaches `name` to each top5 candidate."""
    import lifecycle_report as lr

    captured_ctx: dict = {}

    def fake_select(**kwargs):
        return {
            "candidates": [
                {"ticker": "005930", "is_portfolio": False,
                 "snapshot": {"setup": "TREND_OK", "decision": "ENTER",
                               "rs_delta_pct": 5.0,
                               "raw": {"close": 70000, "rsi14": 62,
                                       "dist_ema9_pct": 2.0,
                                       "volume_ratio": 1.1, "risk_tags": []}},
                 "base_score": 7.0, "momentum_bonus": 0, "rs_bonus": 1,
                 "final_score": 8.0, "size_hint_label": "신규 50%"},
            ],
            "count": 1, "max": 5, "threshold": 3.0,
        }

    monkeypatch.setattr(lr, "select_top5_buy_candidates", fake_select)
    # Force _lookup_ticker_name to return a known KR name
    monkeypatch.setattr(lr, "_lookup_ticker_name",
                          lambda t, m: "삼성전자" if t == "005930" else t)

    from jinja2 import Template

    def capture_render(self, **ctx):
        captured_ctx.update(ctx)
        return "<html></html>"

    monkeypatch.setattr(Template, "render", capture_render)

    result = {
        "as_of": "2026-05-26", "market": "KR",
        "snapshots": {"005930": {"setup": "TREND_OK"}},
        "transitions": [], "skipped": [], "active_set_size": 1,
        "market_ret_5d_pct": 0.0,
        "momentum_history": {"data": {}},
        "engine_version": "score_v1",
    }
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    lr._render("KR", result, str(out_dir), template_dir=None,
                lifecycle_state={"tickers": {}, "transitions": []},
                portfolio_tickers=set())

    candidates = captured_ctx.get("top5_candidates")
    assert candidates is not None
    assert len(candidates) == 1
    assert candidates[0]["name"] == "삼성전자"


def test_render_us_does_not_attach_name_to_top5(monkeypatch, tmp_path):
    """_render('US', ...) leaves candidates without `name` field."""
    import lifecycle_report as lr

    captured_ctx: dict = {}

    def fake_select(**kwargs):
        return {
            "candidates": [
                {"ticker": "AAPL", "is_portfolio": False,
                 "snapshot": {"setup": "TREND_OK", "decision": "ENTER",
                               "rs_delta_pct": 5.0,
                               "raw": {"close": 200, "rsi14": 60,
                                       "dist_ema9_pct": 1.0,
                                       "volume_ratio": 1.0, "risk_tags": []}},
                 "base_score": 7.0, "momentum_bonus": 0, "rs_bonus": 1,
                 "final_score": 8.0, "size_hint_label": "신규 50%"},
            ],
            "count": 1, "max": 5, "threshold": 5.0,
        }

    monkeypatch.setattr(lr, "select_top5_buy_candidates", fake_select)

    from jinja2 import Template

    def capture_render(self, **ctx):
        captured_ctx.update(ctx)
        return "<html></html>"

    monkeypatch.setattr(Template, "render", capture_render)

    result = {
        "as_of": "2026-05-26", "market": "US",
        "snapshots": {"AAPL": {"setup": "TREND_OK"}},
        "transitions": [], "skipped": [], "active_set_size": 1,
        "market_ret_5d_pct": 0.0,
        "momentum_history": {"data": {}},
        "engine_version": "score_v1",
    }
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    lr._render("US", result, str(out_dir), template_dir=None,
                lifecycle_state={"tickers": {}, "transitions": []},
                portfolio_tickers=set())

    candidates = captured_ctx.get("top5_candidates")
    assert candidates is not None
    assert len(candidates) == 1
    # US: no name attached
    assert "name" not in candidates[0]
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_render_kr_attaches_korean_name_to_top5 -xvs
```

Expected: FAIL — `candidates[0]["name"]` KeyError 또는 "삼성전자"가 아님.

- [ ] **Step 3: Modify `_render` to attach name for KR**

`lifecycle_report.py`의 Task 1에서 수정한 `select_top5_buy_candidates(...)` 호출 직후에 추가:

Find (Task 1 작업 후 상태, 호출 + ctx 주입 사이):
```python
    top5 = select_top5_buy_candidates(
        ...
        threshold=top5_threshold_for_market,
    )
    ctx["top5_candidates"] = top5["candidates"]
```

Replace with (호출과 ctx 주입 사이에 KR name 분기 삽입):
```python
    top5 = select_top5_buy_candidates(
        ...
        threshold=top5_threshold_for_market,
    )
    # KR display: attach 한글 종목명 for ticker rows (active_set + 스캐너 신규 모두 일관)
    if market == "KR":
        for c in top5["candidates"]:
            c["name"] = _lookup_ticker_name(c["ticker"], "KR")
    ctx["top5_candidates"] = top5["candidates"]
```

(`...`로 표시된 부분은 Task 1에서 작성한 그대로 — 시그니처 변경 없음.)

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_render_kr_attaches_korean_name_to_top5 tests/test_lifecycle_buy_candidates.py::test_render_us_does_not_attach_name_to_top5 -xvs
```

Expected: PASS (2 tests).

- [ ] **Step 5: Run full lifecycle suite**

```
python -m pytest tests/test_lifecycle_buy_candidates.py tests/test_lifecycle_report.py tests/test_lifecycle_signal.py tests/test_lifecycle_history.py -x
```

Expected: All pass.

- [ ] **Step 6: Commit**

```
git add lifecycle_report.py tests/test_lifecycle_buy_candidates.py
git commit -m "feat(top5-kr): attach Korean name to KR top5 candidates"
```

---

## Task 3: `lifecycle_kr.html` — Top 5 섹션 CSS + Markup (TDD)

**Files:**
- Modify: `templates/lifecycle_kr.html` (두 번째 `<style>` 블록 + body summary-box 직후)
- Modify: `tests/test_lifecycle_buy_candidates.py`

US 섹션을 KR 다크 테마 변수로 재작성, ticker 옆 `kr-name` 표시.

- [ ] **Step 1: Locate exact insertion points**

```
grep -n "summary-box\|_lifecycle_pipeline\|^</style>" templates/lifecycle_kr.html | head -20
```

확인된 위치 (current state):
- L19-48: 첫 번째 `<style>` (debug/filter) — 사용 안 함
- L66-215: 두 번째 `<style>` (페이지 chrome) — Top 5 CSS는 여기 닫는 `</style>` (L215) 직전에 append
- L253: summary-box `</div>` — Top 5 섹션은 이 다음 줄에 삽입
- L256: `{% include "_lifecycle_pipeline.html" %}`

- [ ] **Step 2: Write failing template render test**

Append to `tests/test_lifecycle_buy_candidates.py`:

```python
def test_template_renders_top5_section_kr(tmp_path):
    """lifecycle_kr.html renders Top 5 section with ticker + Korean name + badges."""
    import os
    from jinja2 import Environment, FileSystemLoader

    project_dir = os.path.join(os.path.dirname(__file__), "..")
    env = Environment(loader=FileSystemLoader(
        os.path.join(project_dir, "templates")), autoescape=True)
    env.filters["signed_pct"]      = lambda x: "—" if x is None else f"{x:+.1f}%"
    env.filters["x_fmt"]            = lambda x: "—" if x is None else f"{x:.1f}×"
    env.filters["trig_age_label"]   = lambda d: "—" if d is None else (
        "오늘" if d == 0 else "어제" if d == 1 else f"{d}일전")

    tmpl = env.get_template("lifecycle_kr.html")
    ctx = {
        "market": "KR", "as_of": "2026-05-26", "engine_version": "score_v1",
        "active_nav": "lifecycle_kr", "version": "v1",
        "snapshots_list": [], "transitions": [], "skipped": [],
        "active_set_size": 1, "summary": {"counts": {}}, "score_tier_bands": {},
        "lifecycle_thresholds": {"EXTENDED_DIST_FROM_EMA9": 0.10,
                                   "EXTENDED_RSI_MIN": 70,
                                   "RISK_OVERHEAT_RSI": 75},
        "verdict_summary": {"headline": "", "narration": "",
                              "action_hint": "", "avoid_line": ""},
        "enter": [], "probe": [], "watch": [], "trending": [], "avoid": [],
        "broken_table": [], "new_confirmed": [],
        "top5_candidates": [{
            "ticker": "005930", "name": "삼성전자", "is_portfolio": True,
            "snapshot": {"setup": "TREND_OK", "decision": "ENTER",
                          "raw": {"close": 70000, "rsi14": 62,
                                  "dist_ema9_pct": 2.0, "volume_ratio": 1.1,
                                  "risk_tags": []},
                          "rs_delta_pct": 5.0},
            "base_score": 7.0, "momentum_bonus": 0, "rs_bonus": 1,
            "final_score": 8.0, "size_hint_label": "추가 50%",
        }, {
            "ticker": "035720", "name": "카카오", "is_portfolio": False,
            "snapshot": {"setup": "PULLBACK", "decision": "PROBE",
                          "_scanner_only": True,
                          "raw": {"close": 50000, "rsi14": 50,
                                  "dist_ema9_pct": -1.0, "volume_ratio": 1.0,
                                  "risk_tags": []},
                          "rs_delta_pct": 2.0},
            "base_score": 4.0, "momentum_bonus": 2, "rs_bonus": 1,
            "final_score": 7.0, "size_hint_label": "신규 50%",
        }],
        "top5_count": 2, "top5_max": 5, "top5_threshold": 3.0,
    }
    html = tmpl.render(**ctx)
    assert "오늘의 매수 후보" in html
    assert "005930" in html
    assert "삼성전자" in html
    assert "035720" in html
    assert "카카오" in html
    assert "보유 중" in html or "🏦" in html
    assert "스캐너 신규" in html or "🚀" in html
    # partial-notice 노출 (2/5)
    assert "2/5" in html
```

- [ ] **Step 3: Run test to verify it fails**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_template_renders_top5_section_kr -xvs
```

Expected: FAIL — "오늘의 매수 후보" 또는 "삼성전자" not in HTML.

- [ ] **Step 4: Append Top 5 CSS to second `<style>` block in `lifecycle_kr.html`**

`templates/lifecycle_kr.html`에서 L215의 두 번째 `</style>` 직전 (L211-214의 `@media (max-width: 768px)` 다음, `</style>` 앞)에 다음 CSS 추가:

```css
  /* ── Top 5 Buy Candidates (2026-05-26 spec) ── */
  .top5-section { margin: 20px 0 28px; padding: 18px 22px;
                   background: var(--card); border: 1px solid var(--border);
                   border-radius: 12px; }
  .top5-section h2 { margin: 0 0 6px; font-size: 17px; color: var(--primary-c);
                      display: flex; align-items: center; gap: 8px; }
  .top5-section .partial-notice,
  .top5-section .empty-state { color: var(--muted); font-size: 13px;
                                 margin: 6px 0 12px; }
  .top5-table { width: 100%; border-collapse: collapse; margin-top: 10px;
                 font-size: 13px; }
  .top5-table th { color: var(--muted); font-weight: 500; font-size: 11px;
                    text-transform: uppercase; text-align: left;
                    padding: 6px 8px; border-bottom: 1px solid var(--border); }
  .top5-table td { padding: 8px; border-bottom: 1px solid var(--border);
                    vertical-align: middle; color: var(--text); }
  .top5-row.extended-row { background: rgba(239, 68, 68, 0.05); }
  .top5-table .kr-name { font-weight: 400; color: var(--muted);
                          font-size: 12px; margin-left: 6px; }
  .top5-table small { color: var(--muted); display: block; font-size: 11px;
                       margin-top: 2px; }
  .top5-section .disclaimer { color: var(--muted); font-size: 12px;
                                margin-top: 10px; }
  .badge.portfolio-badge { display: inline-block; padding: 1px 6px;
                            margin-left: 4px; border-radius: 3px;
                            font-size: 11px; font-weight: 600;
                            background: rgba(34,197,94,0.18); color: #86efac; }
  .badge.scanner-only-badge { display: inline-block; padding: 1px 6px;
                                margin-left: 4px; border-radius: 3px;
                                font-size: 11px; font-weight: 600;
                                background: rgba(59,130,246,0.18); color: #93c5fd; }
  .chip.overheat-chip { display: inline-block; padding: 1px 6px;
                         margin-left: 4px; border-radius: 3px;
                         font-size: 11px; font-weight: 600;
                         background: rgba(239,68,68,0.18); color: #fca5a5; }
```

- [ ] **Step 5: Insert Top 5 `<section>` between summary-box and pipeline include**

`templates/lifecycle_kr.html`에서 L253의 `</div>` (summary-box 닫는 태그) 직후, L256의 `{% include "_lifecycle_pipeline.html" %}` 직전 (L254 빈 줄 자리)에 다음 markup 추가:

```html

    {# ── Top 5 Buy Candidates (2026-05-26 spec) ─────────────────── #}
    <section id="top5-buy-candidates" class="top5-section">
      <h2>🎯 오늘의 매수 후보 (보유 추가 포함) — Top {{ top5_count }}/{{ top5_max }}</h2>

      {% if top5_count == 0 %}
        <p class="empty-state">
          오늘 매수 후보 없음 — 모든 종목 score &lt; {{ top5_threshold }}
          (시장이 약하거나 강한 setup 부족)
        </p>
      {% else %}
        {% if top5_count < top5_max %}
          <p class="partial-notice">
            오늘은 {{ top5_count }}/{{ top5_max }} — 시장이 약하거나 강한 setup 부족
          </p>
        {% endif %}

        <table class="top5-table">
          <thead>
            <tr>
              <th>#</th><th>Ticker</th><th>Decision</th><th>Setup</th>
              <th>Score</th><th>RS</th><th>키 지표</th><th>사이즈 hint</th>
            </tr>
          </thead>
          <tbody>
          {% for c in top5_candidates %}
            <tr class="top5-row{% if c.snapshot.setup == 'EXTENDED' %} extended-row{% endif %}">
              <td>{{ loop.index }}</td>
              <td>
                <strong>{{ c.ticker }}</strong>
                {% if c.name and c.name != c.ticker %}<span class="kr-name">{{ c.name }}</span>{% endif %}
                {% if c.is_portfolio %}<span class="badge portfolio-badge">🏦 보유 중</span>{% endif %}
                {% if c.snapshot._scanner_only %}<span class="badge scanner-only-badge">🚀 스캐너 신규</span>{% endif %}
              </td>
              <td>{{ c.snapshot.decision }}</td>
              <td>
                {{ c.snapshot.setup }}
                {% if c.snapshot.setup == 'EXTENDED' %}<span class="chip overheat-chip">⚠️ 과열</span>{% endif %}
              </td>
              <td>
                <strong>{{ '%.1f' % c.final_score }}</strong>
                <small>= {{ '%.1f' % c.base_score }} + {{ c.momentum_bonus }} + {{ c.rs_bonus }}</small>
              </td>
              <td>{{ c.snapshot.rs_delta_pct | signed_pct }}</td>
              <td>
                RSI {{ '%.0f' % c.snapshot.raw.rsi14 }} ·
                EMA9 {{ c.snapshot.raw.dist_ema9_pct | signed_pct }} ·
                Vol {{ c.snapshot.raw.volume_ratio | x_fmt }}
              </td>
              <td>{{ c.size_hint_label }}</td>
            </tr>
          {% endfor %}
          </tbody>
        </table>
        <p class="disclaimer">
          <small>⚠️ 자동매매 아님 — display only. 매수 결정은 사용자 판단. 사이즈는 권장치이며 강제 아님.</small>
        </p>
      {% endif %}
    </section>
```

- [ ] **Step 6: Run test to verify it passes**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_template_renders_top5_section_kr -xvs
```

Expected: PASS.

- [ ] **Step 7: Run lifecycle template/golden tests for regression**

```
python -m pytest tests/test_lifecycle_buy_candidates.py tests/test_lifecycle_report.py tests/test_lifecycle_golden.py tests/test_generate_site_lifecycle.py tests/test_lifecycle_report_nav.py -x
```

Expected: All pass. 만약 `test_lifecycle_golden.py`가 KR 출력 snapshot diff을 보고하면, KR golden fixture를 새 섹션 포함 출력으로 업데이트 (project convention 따름 — fixture 파일 직접 edit 또는 `--golden-update` 옵션).

- [ ] **Step 8: Commit**

```
git add templates/lifecycle_kr.html tests/test_lifecycle_buy_candidates.py
git commit -m "feat(top5-kr): add Top 5 Buy Candidates section to lifecycle_kr.html"
```

---

## Task 4: Full regression suite

**Files:** 없음 (실행만)

End-to-end 검증 — lifecycle/momentum/pipeline 전체 무결성 확인.

- [ ] **Step 1: Run full lifecycle + buy_candidates + momentum + pipeline suite**

```
python -m pytest tests/test_lifecycle_buy_candidates.py tests/test_lifecycle_signal.py tests/test_lifecycle_history.py tests/test_lifecycle_report.py tests/test_lifecycle_golden.py tests/test_lifecycle_e2e.py tests/test_lifecycle_report_nav.py tests/test_generate_site_lifecycle.py tests/test_momentum_scanner.py tests/test_momentum_signal.py tests/test_momentum_history.py tests/test_compute_single_snapshot.py tests/test_pipeline_momentum_step.py tests/test_pipeline_momentum_wiring.py -x
```

Expected: All pass.

- [ ] **Step 2: 실패 시 — 어떤 테스트가 깨졌는지 진단**

만약 golden snapshot 차이로 fail이면, diff 검토 → KR 섹션 추가만이 변경 원인인지 확인 → fixture 업데이트 commit. 다른 종류의 실패면 Task 1-3 변경을 의심 (특히 `_render` ctx 키 추가 영향).

- [ ] **Step 3: No commit (실행 검증 only)**

---

## Task 5: Smoke pipeline run

**Files:** 없음 (실행 검증)

실제 데이터로 KR Top 5가 렌더링되는지 확인. (momentum scanner를 거쳐야 하므로 `SKIP_SCANNERS=1` 사용 불가.)

- [ ] **Step 1: Run pipeline locally**

```
python pipeline.py 2>&1 | tail -40
```

PowerShell:
```
python pipeline.py 2>&1 | Select-Object -Last 40
```

Expected: 깨끗한 종료, lifecycle KR step 성공 로그.

- [ ] **Step 2: Inspect generated KR lifecycle output**

```
grep -c "top5-buy-candidates\|오늘의 매수 후보" deploy/lifecycle_kr_*.html
```

PowerShell:
```
Select-String -Path "deploy/lifecycle_kr_*.html" -Pattern "top5-buy-candidates|오늘의 매수 후보" | Measure-Object | % Count
```

Expected: ≥ 2 (header + section id 양쪽 매치).

- [ ] **Step 3: Verify US 페이지 unchanged**

```
grep -c "top5-buy-candidates" deploy/lifecycle_us_*.html
```

Expected: ≥ 1 (US도 이전부터 섹션이 있었으므로 동일하게 매치).

비교용으로 가능하면 (diff 도구가 있다면):
```
git stash; python pipeline.py; cp deploy/lifecycle_us_*.html /tmp/us_before.html
git stash pop; python pipeline.py
diff /tmp/us_before.html deploy/lifecycle_us_*.html  # KR 변경만이면 US diff 없음
```

(이 step은 informational — golden 테스트가 이미 안전망 역할.)

- [ ] **Step 4: Visual sanity (optional)**

`deploy/lifecycle_kr_<today>.html`을 브라우저로 열어 다크/라이트 양쪽에서 Top 5 섹션의 배경/테두리/한글명 표시가 자연스러운지 시각 확인.

- [ ] **Step 5: No commit (실행 검증 only)**

---

## Task 6: `CLAUDE.md` — 진행 중인 계획 리스트 업데이트

**Files:**
- Modify: `CLAUDE.md` (진행 중인 계획 section)

기존 plans 리스트 패턴 따라 한 줄 추가.

- [ ] **Step 1: Verify section location**

```
grep -n "진행 중인 계획" CLAUDE.md
```

Expected: section header 라인 번호 (예: L5).

- [ ] **Step 2: Append entry in "진행 중인 계획" section**

리스트 마지막 (가장 최근 항목 — "Lifecycle Top 5 Universe Expansion") 직후에 한 줄 추가:

```markdown
- [Lifecycle KR Top 5 Buy Candidates](docs/superpowers/plans/2026-05-26-lifecycle-top5-kr.md) — `lifecycle_kr.html`에 "🎯 오늘의 매수 후보 — Top N/5" 섹션 추가 · KR 전용 threshold 3.0 (US: 5.0) · 종목명 한글 표시 (`_lookup_ticker_name`) · 🏦 보유 중/🚀 스캐너 신규/⚠️ 과열 배지 US와 동일 · Python plumbing 100% 재사용 (변경 표면 = `_render` 분기만)
```

- [ ] **Step 3: Commit**

```
git add CLAUDE.md
git commit -m "docs(claude): add lifecycle KR top5 plan to in-progress list"
```

---

## Final verification

- [ ] **Run complete regression suite one more time**

```
python -m pytest tests/test_lifecycle_buy_candidates.py tests/test_lifecycle_signal.py tests/test_lifecycle_history.py tests/test_lifecycle_report.py tests/test_lifecycle_golden.py tests/test_lifecycle_e2e.py tests/test_lifecycle_report_nav.py tests/test_generate_site_lifecycle.py tests/test_momentum_scanner.py tests/test_momentum_signal.py tests/test_momentum_history.py tests/test_compute_single_snapshot.py tests/test_pipeline_momentum_step.py tests/test_pipeline_momentum_wiring.py -x
```

Expected: 모든 테스트 PASS.

- [ ] **One more smoke run**

```
python pipeline.py
```

Inspect:
```
ls deploy/lifecycle_kr_*.html
grep "오늘의 매수 후보" deploy/lifecycle_kr_*.html | head -2
```

Expected:
- KR 페이지 생성됨
- "오늘의 매수 후보" 헤딩 노출
- 후보 ≥ 1 — 또는 빈 후보면 empty-state 메시지 출력 (둘 다 정상)

- [ ] **PR / merge to master**

표준 PR 흐름 (recent commit history 참고).

---

## Self-review notes (for the executing engineer)

- **No autotrading**: display only. `size_hint_label`을 주문 placement에 연결하지 말 것.
- **Threshold 3.0**: `_render` 내부 hardcode. 추후 KR 데이터 보고 tuning 필요하면 `lifecycle_report.py` 모듈 상수 `_TOP5_THRESHOLD_KR = 3.0`로 hoist (env var는 surface 늘리니 보류).
- **`_lookup_ticker_name`**: 이미 `lifecycle_report.py:28-41`에 존재. KR이면 `market_scanner.KOSPI_NAMES.get(ticker, ticker)`, US는 ticker 그대로 반환. KR Top 5는 이 fallback 덕분에 KOSPI_NAMES 누락 ticker도 안전 (name == ticker → template `c.name != c.ticker` 가드로 중복 표시 방지).
- **US 무변경 보증**: Task 1에서 US도 threshold=5.0을 explicit하게 전달하지만 이는 default와 동일 → behavioral parity. Task 2의 name attach는 KR 조건문 안에만 — US ctx는 이전과 byte-identical.
- **Scanner-only KR 종목 한글명**: `compute_single_snapshot`이 만드는 합성 snapshot에는 name이 없음. `_render`의 `if market == "KR": for c in top5["candidates"]: c["name"] = _lookup_ticker_name(...)`이 active_set + scanner-only 모두에 일관 적용 → 누락 없음.
- **Golden 테스트**: KR 섹션 추가가 KR golden HTML snapshot diff을 유발 가능. 변경 의도된 것이므로 fixture 업데이트로 처리. US golden은 변경 없어야 함 (있으면 회귀 의심).
- **History persistence**: 이번 PR은 `result["snapshots"]` 또는 lifecycle history JSON에 일절 쓰지 않음. Top 5는 페이지 렌더 시점에만 계산.
