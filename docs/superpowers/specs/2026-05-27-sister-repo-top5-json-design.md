# Sister-Repo `top5` JSON Field — Design

**Date:** 2026-05-27
**Status:** Approved (사용자 결정 완료)
**Related:**
- [Lifecycle KR Top 5 Buy Candidates](2026-05-26-lifecycle-top5-kr-design.md)
- [Lifecycle Top 5 Buy Candidates (US)](2026-05-22-lifecycle-top5-buy-candidates-design.md)
- Sister-repo contract: existing `lifecycle_report._export_json` (lifecycle_report.py:266)

---

## Goal

`reports/lifecycle_{us,kr}_latest.json` (sister-repo가 폴링하는 stable contract) 에 `top5` 배열 필드를 추가해, Telegram bot 등 다운스트림 소비자가 67KB HTML을 파싱하지 않고 오늘의 Top 5 매수 후보를 알 수 있도록 한다.

## Background — 현재 JSON Contract

`lifecycle_report._export_json` (L266-294) 가 이미 출력하는 shape:

```json
{
  "schema_version": 1,
  "publish_complete": true,
  "generated_at": "2026-05-31T22:53:00-04:00",
  "market": "US",
  "as_of": "2026-05-29",
  "candidates": [
    {"ticker": "MSFT", "track": "drift", "institution_score": 5, "entry_badges": []},
    ...
  ]
}
```

`candidates`는 ENTER + PROBE 행 (~20개). **누락:** 5-stage 파이프라인 상단의 hybrid 점수 Top 5.

## Target Shape (사용자 확인된 Option B)

```json
{
  "schema_version": 1,
  "publish_complete": true,
  "generated_at": "2026-05-31T23:07:19-04:00",
  "market": "US",
  "as_of": "2026-05-29",
  "top5": [
    {"rank": 1, "ticker": "MU",   "decision": "AVOID", "score": 13.2, "badges": ["EXTENDED"], "held_note": null},
    {"rank": 2, "ticker": "AMD",  "decision": "PROBE", "score": 13.2, "badges": ["TREND_OK"], "held_note": null},
    {"rank": 3, "ticker": "MSFT", "decision": "PROBE", "score": 12.8, "badges": ["TREND_OK"], "held_note": "held"},
    {"rank": 4, "ticker": "ORCL", "decision": "AVOID", "score": 11.8, "badges": ["EXTENDED"], "held_note": null},
    {"rank": 5, "ticker": "WDC",  "decision": "PROBE", "score": 10.8, "badges": ["TREND_OK"], "held_note": null}
  ],
  "candidates": [ /* 기존 — 변경 없음 */ ]
}
```

## Field Mapping (`ctx["top5_candidates"]` → JSON)

| JSON 필드 | 소스 | 타입 |
|----------|------|------|
| `rank` | `enumerate(candidates, start=1)` | int (1-based) |
| `ticker` | `c["ticker"]` | string |
| `decision` | `c["snapshot"]["decision"]` | string (ENTER/PROBE/AVOID/WATCH/STAGING/ENTER_OK/EARLY/AVOID 등) |
| `score` | `round(c["final_score"], 1)` | float (소수 1자리) |
| `badges` | `[c["snapshot"]["setup"]]` | list[string] — 단일 setup |
| `held_note` | `"held" if c["is_portfolio"] else None` | string \| null |

### Design Decisions

**Decision 1 — badges = setup 단일 값**
사용자 확정: 예시와 100% 일치 위해 `_scanner_only`, EM tier, momentum bonus 등은 badge에 포함하지 않음. setup 값만 단일 원소 리스트로 노출. 향후 sister-repo가 다른 메타데이터를 요청하면 새 필드(예: `scanner_only: bool`)로 추가.

**Decision 2 — score 정밀도 = 소수 1자리**
HTML 페이지가 `'%.1f' % c.final_score`로 표시하므로 JSON도 동일 정밀도. `round(value, 1)`. 예: `13.2`, `12.8`.

**Decision 3 — held_note는 "held" 또는 null**
boolean이 아닌 string. 향후 "tighten" / "trim" 같은 다른 보유 상태도 표현 가능하도록 확장성 확보. 현재는 portfolio 보유 시 `"held"`, 미보유 시 `null`.

**Decision 4 — schema_version 유지 (1)**
필드 추가만 발생, 기존 필드 제거/변경 없음 → backward compatible → bump 불필요. sister-repo가 `top5` 부재 시 fallback할 수 있도록 (defensive).

**Decision 5 — `candidates` 무변경**
기존 ENTER/PROBE 행 list는 그대로 유지. 사용자 메시지의 `"candidates": [ /* Bot은 무시 */ ]` 표현 그대로 — sister-repo가 무시할 수 있도록 유지하되 호환성을 위해 삭제하지 않음.

**Decision 6 — KR도 동일 적용**
US와 KR 모두 `_export_json`을 거치므로 동일 코드 경로. KR 시장도 `top5` 필드 받음. KR ticker는 `005930.KS` 형식 그대로 (한글명 `name`은 JSON에 포함하지 않음 — sister-repo가 필요하면 자체 lookup).

## Component Changes

### `lifecycle_report.py`

`_export_json` 함수 (L266-294)에 `top5` 변환 로직 추가:

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
    # NEW: top5 export (2026-05-27 spec)
    top5 = []
    for rank, c in enumerate(ctx.get("top5_candidates") or [], start=1):
        snap = c.get("snapshot") or {}
        top5.append({
            "rank":       rank,
            "ticker":     c["ticker"],
            "decision":   snap.get("decision"),
            "score":      round(c.get("final_score") or 0.0, 1),
            "badges":     [snap.get("setup")] if snap.get("setup") else [],
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

핵심: `top5_candidates`가 없거나 빈 list → `top5: []` (empty list, never null). Sister-repo가 일관 처리 가능.

### Tests (`tests/test_lifecycle_buy_candidates.py`)

신규 테스트 3개:

1. **`test_export_json_includes_top5_array`** — `_export_json` 직접 호출, 출력 dict에 `top5` 키 + 올바른 구조 확인.
2. **`test_export_json_top5_held_note`** — `is_portfolio=True` → `held_note="held"`, False → `held_note=None` 검증.
3. **`test_export_json_empty_top5_when_no_candidates`** — `top5_candidates: []` → JSON `top5: []` (not null, not missing).

### Out of Scope

- `candidates` field schema 변경 (무변경)
- `schema_version` bump (backward-compatible 추가이므로 1 유지)
- 한글명 (`name`) JSON 포함 — sister-repo는 ticker 기반 lookup
- scanner_only / momentum bonus 정보 — 향후 필요 시 별도 필드
- 기존 sister-repo 코드 변경 (이 PR은 publisher만 업데이트)

## Risk & Mitigations

| 리스크 | 완화 |
|--------|------|
| sister-repo가 `top5` 없다고 가정한 구버전이면? | 새 필드 추가는 backward-compatible, sister-repo가 무시 가능 |
| `final_score`가 None일 때? | `c.get("final_score") or 0.0` fallback (방어적) |
| `setup`이 None일 때? | `[setup] if setup else []` 조건부 (빈 list) |
| `decision`이 missing일 때? | `snap.get("decision")` → null 가능 (sister-repo가 처리) |
| JSON 사이즈 증가? | top5는 최대 5행 × ~80B = ~400B 추가. 무시 가능. |

## Success Criteria

- `python pipeline.py` 실행 후 `reports/lifecycle_us_latest.json` + `lifecycle_kr_latest.json` 양쪽에 `top5` 배열 등장
- 각 top5 entry가 정확한 6개 필드 (`rank`, `ticker`, `decision`, `score`, `badges`, `held_note`) 포함
- portfolio 보유 종목이 Top 5에 들면 `held_note: "held"` 표시
- top5 후보 없을 때 `top5: []` (empty list)
- 기존 `candidates` 필드/JSON 구조 무변경
- 모든 lifecycle/buy_candidates 테스트 PASS
- sister-repo가 폴링 시 `top5` 필드 즉시 인지 가능
