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
    assert "Emerging" in msg or "\U0001f331" in msg
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
