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
