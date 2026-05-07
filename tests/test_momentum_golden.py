"""Golden sample regression — freeze evaluate_stock outputs for known inputs."""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import momentum_signal as ms


def _load_fixture():
    path = os.path.join(os.path.dirname(__file__), "fixtures",
                         "golden_momentum_signals.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_evaluate_stock_matches_golden_outputs():
    """모든 케이스의 stage/risk_tags/hint/rs_vs_sector가 expected와 일치."""
    fixture = _load_fixture()
    failures = []
    for case in fixture["cases"]:
        result = ms.evaluate_stock(
            case["input"],
            sector_5d_return=case.get("sector_5d_return"),
        )
        expected = case["expected"]
        if expected is None:
            if result is not None:
                failures.append(f"{case['name']}: expected None, got {result}")
            continue
        if result is None:
            failures.append(f"{case['name']}: expected dict, got None")
            continue
        if result.get("stage") != expected["stage"]:
            failures.append(f"{case['name']} stage: "
                            f"expected {expected['stage']}, got {result.get('stage')}")
        if sorted(result.get("risk_tags") or []) != sorted(expected["risk_tags"]):
            failures.append(f"{case['name']} risk_tags: "
                            f"expected {expected['risk_tags']}, "
                            f"got {result.get('risk_tags')}")
        if result.get("hint") != expected["hint"]:
            failures.append(f"{case['name']} hint: "
                            f"expected {expected['hint']}, got {result.get('hint')}")
        if result.get("rs_vs_sector") != expected["rs_vs_sector"]:
            failures.append(f"{case['name']} rs_vs_sector: "
                            f"expected {expected['rs_vs_sector']}, "
                            f"got {result.get('rs_vs_sector')}")
    assert not failures, "Golden sample mismatches:\n" + "\n".join(failures)


def test_classify_stage_matches_golden_outputs():
    """classify_stage만 따로 검증 (evaluate_stock 회귀 외 isolated test)."""
    fixture = _load_fixture()
    failures = []
    for case in fixture["cases"]:
        stage = ms.classify_stage(case["input"])
        expected_stage = (case["expected"] or {}).get("stage") if case["expected"] else None
        if stage != expected_stage:
            failures.append(
                f"{case['name']}: classify_stage expected {expected_stage}, got {stage}"
            )
    assert not failures, "Stage classification mismatches:\n" + "\n".join(failures)
