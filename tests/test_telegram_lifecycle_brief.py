"""Phase A — lifecycle Telegram brief format."""
from telegram_sender import _format_lifecycle_message


def _result(market, new_confirmed_tickers, enter_ok_count, early_count, failed_count):
    snaps = {}
    for tk in new_confirmed_tickers:
        snaps[tk] = {"setup": "PULLBACK", "trigger": "CONFIRMED_TRIGGER",
                       "decision": "ENTER", "raw": {"risk_tags": []}}
    return {
        "market": market, "as_of": "2026-05-08",
        "snapshots": snaps,
        "_brief_summary": {
            "new_confirmed": new_confirmed_tickers,
            "enter_ok": enter_ok_count,
            "early": early_count,
            "failed_breakout": failed_count,
        },
    }


def test_brief_contains_us_and_kr_sections():
    us = _result("US", ["NVDA", "PLTR"], enter_ok_count=7, early_count=12,
                  failed_count=2)
    kr = _result("KR", ["005930.KS"], enter_ok_count=4, early_count=6,
                  failed_count=0)
    msg = _format_lifecycle_message(us, kr,
                                       base_url="https://example.com/",
                                       date_str="2026-05-08")
    assert "🇺🇸 US" in msg
    assert "🇰🇷 KR" in msg
    assert "NVDA" in msg
    assert "005930.KS" in msg
    assert "https://example.com/lifecycle_us_2026-05-08.html" in msg
    assert "https://example.com/lifecycle_kr_2026-05-08.html" in msg


def test_brief_omits_zero_lines():
    us = _result("US", [], enter_ok_count=0, early_count=0, failed_count=0)
    kr = _result("KR", [], enter_ok_count=0, early_count=0, failed_count=0)
    msg = _format_lifecycle_message(us, kr, base_url="https://example.com/",
                                       date_str="2026-05-08")
    # Both empty — message must be empty (suppressed at send level).
    assert msg.strip() == ""


def test_brief_handles_one_market_only():
    us = _result("US", ["NVDA"], enter_ok_count=3, early_count=2, failed_count=1)
    msg = _format_lifecycle_message(us, None, base_url="https://example.com/",
                                       date_str="2026-05-08")
    assert "🇺🇸 US" in msg
    assert "🇰🇷 KR" not in msg
