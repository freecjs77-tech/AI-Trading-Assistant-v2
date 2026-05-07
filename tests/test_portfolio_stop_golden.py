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
