# Sister-Repo `top5` JSON Field — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `reports/lifecycle_{us,kr}_latest.json`에 `top5` 배열 필드 추가. Sister-repo (Telegram bot 등)가 HTML 파싱 없이 오늘의 Top 5 매수 후보를 폴링으로 받음.

**Architecture:** 변경 표면은 `lifecycle_report._export_json` 한 함수만. `ctx["top5_candidates"]` 가 이미 존재하므로 enumerate + 매핑 ~10줄 추가. schema_version 1 유지 (backward-compatible).

**Tech Stack:** Python 3.10+, pytest (기존), 신규 의존성 없음.

**Spec:** [docs/superpowers/specs/2026-05-27-sister-repo-top5-json-design.md](../specs/2026-05-27-sister-repo-top5-json-design.md)

---

## File Structure

**Modify:**
- `lifecycle_report.py:266-294` — `_export_json` 함수에 top5 변환 + payload에 `top5` 키 추가
- `tests/test_lifecycle_buy_candidates.py` — 3개 신규 테스트 append
- `CLAUDE.md` — 진행 중인 계획 리스트 한 줄 추가

**Out of scope:**
- `candidates` field 변경 (무변경)
- `schema_version` bump (1 유지)
- 한글명 / `_scanner_only` / `name` JSON 포함 (Decision 1: badges = setup only)
- Sister-repo 코드 변경 (이 PR은 publisher만)

---

## Task 1: `_export_json` top5 변환 + 테스트 (TDD)

**Files:**
- Modify: `lifecycle_report.py:266-294`
- Modify: `tests/test_lifecycle_buy_candidates.py` (append 3 tests)

`ctx["top5_candidates"]` → JSON top5 매핑 + payload에 추가.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_lifecycle_buy_candidates.py`:

```python
def test_export_json_includes_top5_array(tmp_path):
    """_export_json writes top5 array with rank/ticker/decision/score/badges/held_note."""
    import json
    import lifecycle_report as lr

    ctx = {
        "market": "US",
        "enter": [], "probe": [],
        "top5_candidates": [
            {
                "ticker": "MU", "is_portfolio": False,
                "snapshot": {"setup": "EXTENDED", "decision": "AVOID"},
                "final_score": 13.2,
            },
            {
                "ticker": "MSFT", "is_portfolio": True,
                "snapshot": {"setup": "TREND_OK", "decision": "PROBE"},
                "final_score": 12.8,
            },
        ],
    }
    result = {"as_of": "2026-05-29"}
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    lr._export_json(ctx, result, str(out_dir))

    json_path = out_dir / "lifecycle_us_2026-05-29.json"
    assert json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert "top5" in payload
    assert len(payload["top5"]) == 2

    first = payload["top5"][0]
    assert first["rank"] == 1
    assert first["ticker"] == "MU"
    assert first["decision"] == "AVOID"
    assert first["score"] == 13.2
    assert first["badges"] == ["EXTENDED"]
    assert first["held_note"] is None

    second = payload["top5"][1]
    assert second["rank"] == 2
    assert second["ticker"] == "MSFT"
    assert second["decision"] == "PROBE"
    assert second["score"] == 12.8
    assert second["badges"] == ["TREND_OK"]
    assert second["held_note"] == "held"


def test_export_json_top5_held_note_mapping(tmp_path):
    """held_note: 'held' when is_portfolio else None."""
    import json
    import lifecycle_report as lr

    ctx = {
        "market": "KR",
        "enter": [], "probe": [],
        "top5_candidates": [
            {"ticker": "005930.KS", "is_portfolio": True,
             "snapshot": {"setup": "TREND_OK", "decision": "PROBE"},
             "final_score": 8.0},
            {"ticker": "035720.KS", "is_portfolio": False,
             "snapshot": {"setup": "PULLBACK", "decision": "PROBE"},
             "final_score": 7.0},
        ],
    }
    result = {"as_of": "2026-05-29"}
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    lr._export_json(ctx, result, str(out_dir))
    payload = json.loads((out_dir / "lifecycle_kr_latest.json").read_text(encoding="utf-8"))

    held_notes = [c["held_note"] for c in payload["top5"]]
    assert held_notes == ["held", None]


def test_export_json_empty_top5_when_no_candidates(tmp_path):
    """top5_candidates empty → JSON top5: [] (list, not null, not missing)."""
    import json
    import lifecycle_report as lr

    ctx = {
        "market": "US",
        "enter": [], "probe": [],
        "top5_candidates": [],
    }
    result = {"as_of": "2026-05-29"}
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    lr._export_json(ctx, result, str(out_dir))
    payload = json.loads((out_dir / "lifecycle_us_latest.json").read_text(encoding="utf-8"))

    assert "top5" in payload
    assert payload["top5"] == []
    # Also confirm existing candidates field is preserved (empty here, but key exists)
    assert "candidates" in payload
    assert payload["schema_version"] == 1
```

- [ ] **Step 2: Run tests to verify FAIL**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_export_json_includes_top5_array tests/test_lifecycle_buy_candidates.py::test_export_json_top5_held_note_mapping tests/test_lifecycle_buy_candidates.py::test_export_json_empty_top5_when_no_candidates -xvs
```

Expected: 3 FAIL because `_export_json` doesn't produce `top5` key yet — KeyError on `payload["top5"]`.

- [ ] **Step 3: Modify `_export_json`**

In `lifecycle_report.py`, find the existing `_export_json` function (L266-294). Replace the entire function body with:

```python
def _export_json(ctx: dict, result: dict, output_dir: str) -> None:
    """Emit lifecycle_{market}_{as_of}.json + lifecycle_{market}_latest.json.

    Sister-repo contract: stable JSON of ENTER/PROBE candidates + today's
    Top 5 hybrid-scored buy candidates so consumers don't have to parse the
    67KB HTML page (template-drift sensitive).
    """
    market = ctx["market"].lower()
    as_of = result.get("as_of")
    generated_at = datetime.now(ZoneInfo("America/New_York")).isoformat()
    candidates = []
    for decision_key, track in (("enter", "trigger"), ("probe", "drift")):
        for row in ctx.get(decision_key, []):
            candidates.append({
                "ticker":            row["ticker"],
                "track":             track,
                "institution_score": row.get("score"),
                "entry_badges":      row.get("decision_badges") or [],
            })
    # Top 5 (2026-05-27 spec) — sister-repo consumes this to avoid HTML parsing
    top5 = []
    for rank, c in enumerate(ctx.get("top5_candidates") or [], start=1):
        snap = c.get("snapshot") or {}
        setup = snap.get("setup")
        top5.append({
            "rank":       rank,
            "ticker":     c["ticker"],
            "decision":   snap.get("decision"),
            "score":      round(c.get("final_score") or 0.0, 1),
            "badges":     [setup] if setup else [],
            "held_note":  "held" if c.get("is_portfolio") else None,
        })
    payload = {
        "schema_version":   1,
        "publish_complete": True,
        "generated_at":     generated_at,
        "market":           market.upper(),
        "as_of":            as_of,
        "top5":             top5,
        "candidates":       candidates,
    }
    for fname in (f"lifecycle_{market}_{as_of}.json", f"lifecycle_{market}_latest.json"):
        with open(os.path.join(output_dir, fname), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
```

Key points:
- `ctx.get("top5_candidates") or []` — handles both missing key and None
- `setup if setup` — empty list when setup None (defensive)
- `round(... or 0.0, 1)` — handles None final_score
- payload 키 순서: `top5`를 `candidates` 앞에 (spec 예시 순서 그대로)

- [ ] **Step 4: Run tests to verify PASS**

```
python -m pytest tests/test_lifecycle_buy_candidates.py::test_export_json_includes_top5_array tests/test_lifecycle_buy_candidates.py::test_export_json_top5_held_note_mapping tests/test_lifecycle_buy_candidates.py::test_export_json_empty_top5_when_no_candidates -xvs
```

Expected: 3 PASS.

- [ ] **Step 5: Run lifecycle suite for regression**

```
python -m pytest tests/test_lifecycle_buy_candidates.py tests/test_lifecycle_report.py tests/test_lifecycle_golden.py tests/test_lifecycle_e2e.py -x
```

Expected: All pass. `_export_json`은 기존에 별도 테스트 없었으므로 영향 없음. `test_lifecycle_golden.py`이 JSON 출력을 snapshot으로 잡고 있으면 fixture 업데이트 필요할 수 있음 — diff 검토 후 의도된 변경이면 fixture 갱신.

- [ ] **Step 6: Commit**

```
git add lifecycle_report.py tests/test_lifecycle_buy_candidates.py
git commit -m "feat(json): add top5 field to lifecycle latest.json for sister-repo"
```

---

## Task 2: Smoke pipeline run + visual verification

**Files:** 없음 (검증만)

실데이터로 JSON 출력이 올바른지 확인.

- [ ] **Step 1: Run pipeline**

```
python pipeline.py 2>&1 | tail -30
```

Expected: 깨끗한 종료, Step 4c4/4c5 (lifecycle US/KR) 성공.

- [ ] **Step 2: Inspect generated JSON**

US:
```
python -c "import json; p = json.load(open('reports/lifecycle_us_latest.json', encoding='utf-8')); print('schema_version:', p['schema_version']); print('top5 count:', len(p['top5'])); print('first top5:', json.dumps(p['top5'][0], indent=2, ensure_ascii=False) if p['top5'] else 'EMPTY')"
```

KR:
```
python -c "import json; p = json.load(open('reports/lifecycle_kr_latest.json', encoding='utf-8')); print('schema_version:', p['schema_version']); print('top5 count:', len(p['top5'])); print('first top5:', json.dumps(p['top5'][0], indent=2, ensure_ascii=False) if p['top5'] else 'EMPTY')"
```

Expected:
- `schema_version: 1`
- `top5 count`: ≤ 5
- 각 entry가 6 필드 (rank, ticker, decision, score, badges, held_note) 포함

- [ ] **Step 3: Verify backward compatibility**

```
python -c "import json; p = json.load(open('reports/lifecycle_us_latest.json', encoding='utf-8')); assert 'candidates' in p; assert isinstance(p['candidates'], list); print('candidates count:', len(p['candidates'])); print('candidates field OK')"
```

Expected: `candidates field OK`. 기존 sister-repo 코드가 `candidates`를 참조해도 깨지지 않음.

- [ ] **Step 4: No commit (검증 only)**

---

## Task 3: `CLAUDE.md` — 진행 중인 계획 리스트 업데이트

**Files:**
- Modify: `CLAUDE.md` (진행 중인 계획 section)

- [ ] **Step 1: Append entry**

`CLAUDE.md`의 "진행 중인 계획" 리스트 마지막에 한 줄 추가:

```markdown
- [Sister-Repo Top 5 JSON Field](docs/superpowers/plans/2026-05-27-sister-repo-top5-json.md) — `lifecycle_{us,kr}_latest.json`에 `top5` 배열 추가 (rank/ticker/decision/score/badges/held_note) · Telegram bot 등 sister-repo가 HTML 파싱 없이 폴링 가능 · `_export_json` 한 함수만 ~10줄 변경 · schema_version 1 유지 (backward-compatible) · 기존 `candidates` 필드 무변경
```

- [ ] **Step 2: Commit**

```
git add CLAUDE.md
git commit -m "docs(claude): add sister-repo top5 json plan to in-progress list"
```

---

## Final verification

- [ ] **Run full regression**

```
python -m pytest tests/test_lifecycle_buy_candidates.py tests/test_lifecycle_signal.py tests/test_lifecycle_history.py tests/test_lifecycle_report.py tests/test_lifecycle_golden.py tests/test_lifecycle_e2e.py -x
```

Expected: All PASS.

- [ ] **Smoke run pipeline + JSON sanity check** (Task 2 step 1-3)

- [ ] **PR / push to master**

Standard flow.

---

## Self-review notes

- **Backward compatibility:** `top5` 필드 추가만 발생. 기존 sister-repo 코드가 `candidates`만 읽어도 정상. 새 필드 인지하면 추가 기능 활성화.
- **`top5: []` vs missing:** empty list 사용. sister-repo가 `payload.get("top5", [])`로 일관 처리.
- **schema_version 1 유지:** spec에서 backward-compatible 추가이므로 bump 불필요. sister-repo가 schema_version 체크하더라도 통과.
- **Decision: badges = setup only:** 사용자 명시. 향후 `scanner_only`, EM tier 등은 별도 필드로 추가 가능 (이 PR 외).
- **score 정밀도:** `round(..., 1)`로 HTML과 일치 (예: 13.2 not 13.2147).
- **None safety:** `final_score`, `setup`, `decision` 모두 None 가능 → defensive default (`0.0`, `[]`, None 통과).
- **Side effects:** `_export_json`은 file write만. 다른 lifecycle state/history JSON과 무관.
