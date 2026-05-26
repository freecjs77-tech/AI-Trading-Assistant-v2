# Lifecycle KR Top 5 Buy Candidates — Design

**Date:** 2026-05-26
**Status:** Approved (브레인스토밍 완료, plan 작성 대기)
**Related:**
- [Lifecycle Top 5 Buy Candidates (US)](2026-05-22-lifecycle-top5-buy-candidates-design.md)
- [Top 5 Universe Expansion](2026-05-22-top5-universe-expansion-design.md)

---

## Goal

`templates/lifecycle_kr.html`에 US와 평행한 "🎯 오늘의 매수 후보 (보유 추가 포함) — Top N/5" 섹션 추가. KR 시장 특성에 맞춘 threshold + 한글 종목명 표시를 포함.

## Background — Plumbing 이미 KR 지원 중

[2026-05-22-top5-universe-expansion-design.md](2026-05-22-top5-universe-expansion-design.md) 작업으로 Python 측 데이터 흐름은 이미 KR을 포함해 완성됨:

| 위치 | 상태 |
|------|------|
| `pipeline.py:667-677` `generate_lifecycle_pages(...)` 호출 | `momentum_today_kr=momentum_kr_result`, `market_data=market_data` 이미 전달 |
| `lifecycle_report.py:368-379` `generate_lifecycle_pages` | US/KR 분기 모두 `_render` 호출 |
| `lifecycle_report.py:297-365` `_render` | market 무관하게 동일 `select_top5_buy_candidates(...)` 호출 + ctx 주입 |
| `momentum_scanner.py:244` 스캐너 결과 shape | KR도 `signals = {"MOMENTUM_3", "MOMENTUM_2", "MOMENTUM_1", "EM"}` 동일 구조 |
| `momentum_scanner.py:273` `evaluation["name"]` | KR 스캐너 결과는 `_lookup_name(ticker, market)`로 한글명 이미 포함 |

즉 `_render("KR", ...)`은 이미 `ctx["top5_candidates"]`를 계산해 넘기지만, **`lifecycle_kr.html`이 그것을 렌더링하지 않을 뿐**.

## Scope

**In scope:**
- `lifecycle_report._render` 작은 KR 분기 (threshold + 한글명 attach)
- `templates/lifecycle_kr.html` Top 5 섹션 추가
- 단위/통합 테스트 3개
- `CLAUDE.md` 진행 중인 계획 리스트 한 줄 추가

**Out of scope:**
- Telegram brief 알림 (후속)
- KR 시장에 다른 점수 가중치/공식 (US와 동일 유지)
- 5-stage 파이프라인 / lifecycle history schema 변경
- `select_top5_buy_candidates` 자체 시그니처 변경 (threshold는 기존 kwarg 그대로 사용)

---

## Design Decisions

### Decision 1 — 종목명 표시: Ticker + 한글명

**Choice:** `005930 삼성전자` 형태로 ticker와 한글명을 함께 표시.

**Why:** KR ticker는 6자리 숫자라 식별이 어려움. `lifecycle_kr.html`의 다른 섹션(AVOID, stage chips 등)이 이미 `<span class="kr-name">{{ row.name }}</span>` 패턴으로 한글명 병기 → 일관성.

**How:** `_render`에서 `select_top5_buy_candidates` 호출 직후, KR 시장이면 각 candidate에 `name` 필드를 attach.

```python
if market == "KR":
    for c in top5["candidates"]:
        c["name"] = _lookup_ticker_name(c["ticker"], "KR")
```

이 방식은 active_set 종목 (lifecycle pool)과 `_scanner_only=True` 합성 snapshot 양쪽 모두 일관 처리. (스캐너 결과의 `name`을 이용하지 않는 이유: `compute_single_snapshot`은 `market_data_entry`에서만 raw를 빌드하고 이름을 떨궈낸다. 단일 lookup 경로가 더 깨끗.)

### Decision 2 — Threshold: KR 전용 3.0

**Choice:** `_render` 내부에서 `threshold = 3.0 if market == "KR" else 5.0`.

**Why:** KR universe 크기(`market_scanner.KOSPI_TICKERS` 50 + KOSDAQ 일부 ≈ ~100) 가 US (SP100 ∪ NDX100 = 169) 의 절반 수준 + 5-stage 파이프라인의 KR active_set 도 그에 비례해 작음. 같은 threshold 5.0이면 KR은 거의 항상 빈 후보 / 1-2개로 끝나 페이지가 무력해진다. 3.0은 base_score 단독으로도 후보를 노출할 수 있도록 낮춰 KR-친화적 운용을 가능하게 함.

**How:** Hardcode in `_render`. `lifecycle_buy_candidates` 자체는 default 5.0 유지 (US/일반 호출은 영향 없음). 필요 시 추후 `lifecycle_report.py` 모듈 상수 `_TOP5_THRESHOLD_KR = 3.0` 로 hoist.

**Tradeoff:** KR Top 5는 US보다 약한 신호도 노출됨. 사용자가 점수 표시(`final = base + momentum + RS`)로 강도를 직접 판단 가능하므로 허용 가능.

### Decision 3 — 다크 테마 스타일

**Choice:** US Top 5의 라이트 RGBA 색상이 KR 다크 테마와 충돌하므로, KR 섹션 CSS는 KR 템플릿의 CSS 변수(`var(--card)`, `var(--border)`, `var(--text)`, `var(--primary-c)`, `var(--muted)`)를 사용해 재작성.

**Why:** `lifecycle_kr.html`은 `html.dark` 기본에 `html.light` 토글 — Top 5 박스 배경/테두리/포인트 컬러를 변수 기반으로 작성해야 양쪽 테마에서 자연스럽게 보임.

### Decision 4 — 컬럼 구성: US와 동일

**Choice:** `# / Ticker / Decision / Setup / Score / RS / 키 지표 / 사이즈 hint` — US 7컬럼 그대로.

**Why:** KR 사용자도 동일 정보 요구. 다국어/뷰 차이 없음.

---

## Component Changes

### A. `lifecycle_report.py`

`_render(market, ...)` 함수의 `select_top5_buy_candidates(...)` 호출 부분을 다음과 같이 수정:

```python
# Top 5 Buy Candidates section
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
# KR display: attach 한글명 to each candidate
if market == "KR":
    for c in top5["candidates"]:
        c["name"] = _lookup_ticker_name(c["ticker"], "KR")
ctx["top5_candidates"] = top5["candidates"]
ctx["top5_count"]      = top5["count"]
ctx["top5_max"]        = top5["max"]
ctx["top5_threshold"]  = top5["threshold"]
```

`_lookup_ticker_name`은 같은 모듈에 이미 존재 (`build_page_context`이 사용 중).

### B. `templates/lifecycle_kr.html`

**삽입 위치:** L253 `</div>` (summary-box 닫는 태그) 직후, L256 `{% include "_lifecycle_pipeline.html" %}` 직전.

**스타일 블록 (head의 `<style>` 안에 추가):**

```css
.top5-section { margin: 20px 0 28px; padding: 18px 22px;
                 background: var(--card); border: 1px solid var(--border);
                 border-radius: 12px; }
.top5-section h2 { margin: 0 0 6px; font-size: 17px; color: var(--primary-c); }
.top5-section .partial-notice,
.top5-section .empty-state { color: var(--muted); font-size: 13px; margin: 6px 0 12px; }
.top5-table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; }
.top5-table th { color: var(--muted); font-weight: 500; font-size: 11px;
                  text-transform: uppercase; text-align: left;
                  padding: 6px 8px; border-bottom: 1px solid var(--border); }
.top5-table td { padding: 8px; border-bottom: 1px solid var(--border);
                  vertical-align: middle; color: var(--text); }
.top5-row.extended-row { background: rgba(239, 68, 68, 0.05); }
.top5-table .kr-name { font-weight: 400; color: var(--muted);
                         font-size: 12px; margin-left: 6px; }
.top5-table small { color: var(--muted); display: block; font-size: 11px; margin-top: 2px; }
.top5-section .disclaimer { color: var(--muted); font-size: 12px; margin-top: 10px; }
.badge.portfolio-badge { display: inline-block; padding: 1px 6px; margin-left: 4px;
                          border-radius: 3px; font-size: 11px; font-weight: 600;
                          background: rgba(34,197,94,0.18); color: #86efac; }
.badge.scanner-only-badge { display: inline-block; padding: 1px 6px; margin-left: 4px;
                              border-radius: 3px; font-size: 11px; font-weight: 600;
                              background: rgba(59,130,246,0.18); color: #93c5fd; }
.chip.overheat-chip { display: inline-block; padding: 1px 6px; margin-left: 4px;
                       border-radius: 3px; font-size: 11px; font-weight: 600;
                       background: rgba(239,68,68,0.18); color: #fca5a5; }
```

**섹션 markup:**

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

### C. 테스트 (`tests/test_lifecycle_buy_candidates.py` 신규 케이스)

1. **`test_render_uses_kr_threshold_3`**
   `_render("KR", ...)` 호출 시 `select_top5_buy_candidates`에 `threshold=3.0` 전달되는지 monkeypatch로 검증.

2. **`test_render_attaches_kr_name_to_top5`**
   KR snapshot이 있을 때 `_render("KR", ...)` 후 ctx의 `top5_candidates`에 `name` 필드가 부여되는지. US는 `name`이 부여되지 않는지.

3. **`test_template_renders_top5_section_kr`**
   `lifecycle_kr.html`을 직접 렌더해 "🎯 오늘의 매수 후보", ticker, KR 한글명, partial-notice/empty-state 변형이 모두 노출되는지.

추가 regression: `tests/test_lifecycle_report.py`, `tests/test_lifecycle_golden.py`, `tests/test_lifecycle_e2e.py` 모두 PASS 유지 — KR 섹션 추가가 US/KR golden을 깨지 않아야 함.

### D. `CLAUDE.md`

진행 중인 계획 리스트에 한 줄 추가:

```markdown
- [Lifecycle KR Top 5 Buy Candidates](docs/superpowers/plans/2026-05-26-lifecycle-top5-kr.md) — `lifecycle_kr.html`에 "🎯 오늘의 매수 후보 — Top N/5" 섹션 추가 · KR 전용 threshold 3.0 (US: 5.0) · 종목명 한글 표시 (`_lookup_ticker_name`) · 스캐너 신규/보유 중/과열 배지 US와 동일 · plumbing 100% 재사용 (Python 변경 표면 = `_render` 분기만)
```

---

## Architecture Diagram

```
pipeline.py
   │
   │ momentum_us_result, momentum_kr_result, market_data
   ▼
generate_lifecycle_pages(us_result, kr_result,
                          momentum_today_us, momentum_today_kr,
                          market_data, portfolio_tickers, ...)
   │
   ├──> _render("US", ...) ──> select_top5(threshold=5.0)
   │                              └─> ctx["top5_*"] (no .name attach)
   │                              └─> lifecycle_us.html
   │
   └──> _render("KR", ...) ──> select_top5(threshold=3.0)
                                  └─> attach c["name"] via _lookup_ticker_name
                                  └─> ctx["top5_*"]
                                  └─> lifecycle_kr.html ★ NEW SECTION
```

별표가 이번 PR에서 신규로 활성화되는 경로.

---

## Risks & Mitigations

| 리스크 | 완화 |
|--------|------|
| KR universe 작음 → 빈 후보 빈도 높음 | threshold 3.0 + 기존 partial-notice/empty-state UX로 대응 |
| `_lookup_ticker_name`이 KR ticker 없을 때 ticker 자체 반환 | template에서 `c.name != c.ticker` 가드로 중복 표시 방지 |
| US Top 5 의도치 않은 회귀 | US 분기는 100% 무변경, golden 테스트가 안전망 |
| 다크 테마 깨짐 | KR CSS 변수 사용 + light/dark 양쪽 시각 점검 (smoke test) |
| KR scanner의 한글명 무시하고 별도 lookup하는 게 낭비? | lookup은 캐시되어 비용 무시 가능. 단일 경로가 코드 명료성 우선. |

---

## Success Criteria

- `python pipeline.py` 실행 후 `deploy/lifecycle_kr_<today>.html`에 "🎯 오늘의 매수 후보" 섹션이 렌더링됨
- KR active_set 종목과 momentum 스캐너 신규 종목이 score 3.0 이상이면 Top 5에 노출
- 각 행이 ticker + 한글명, `🏦 보유 중` (보유 시) / `🚀 스캐너 신규` (scanner-only 시) / `⚠️ 과열` (EXTENDED 시) 배지를 정확히 표시
- US 페이지(`lifecycle_us_<today>.html`)는 변경 전과 동일 (diff 없음, golden 테스트 PASS)
- 모든 lifecycle/buy_candidates/momentum 테스트 스위트 PASS
