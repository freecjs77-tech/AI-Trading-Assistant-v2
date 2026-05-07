"""send_momentum_brief — message format + length safety."""
import sys, os
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _sample_us():
    return {
        "market": "US", "as_of": "2026-05-06", "status": "ok",
        "version": "Momentum v1.0",
        "top_sectors": [
            {"ticker": "XLK", "score": 95}, {"ticker": "XLC", "score": 87},
        ],
        "signals": {
            "MOMENTUM_3": [
                {"ticker": "NVDA", "stage": "MOMENTUM_3", "risk_tags": ["OVERHEAT"]},
                {"ticker": "AMD", "stage": "MOMENTUM_3", "risk_tags": []},
            ],
            "MOMENTUM_2": [
                {"ticker": "MU", "stage": "MOMENTUM_2", "risk_tags": ["EXTENDED"]},
            ],
            "MOMENTUM_1": [],
        },
        "backtest_summary": {
            "by_streak": {"3+": {"avg_ret_5d": 5.7}},
            "alerts": {"consecutive_loss_warning": False, "recent_5_legs_loss_count": 1},
        },
    }


def _sample_kr():
    return {
        "market": "KR", "as_of": "2026-05-06", "status": "ok",
        "version": "Momentum v1.0",
        "top_sectors": [{"ticker": "091160.KS", "score": 90}],
        "signals": {
            "MOMENTUM_3": [], "MOMENTUM_2": [], "MOMENTUM_1": [],
        },
        "backtest_summary": None,
    }


def test_format_momentum_message_includes_us_and_kr():
    from telegram_sender import _format_momentum_message
    msg = _format_momentum_message(_sample_us(), _sample_kr(), as_of="2026-05-06")
    assert "🇺🇸" in msg or "US" in msg
    assert "🇰🇷" in msg or "KR" in msg
    assert "NVDA" in msg
    assert "M3" in msg or "MOMENTUM_3" in msg


def test_format_momentum_message_truncates_to_3500():
    from telegram_sender import _format_momentum_message
    big_us = _sample_us()
    big_us["signals"]["MOMENTUM_1"] = [
        {"ticker": f"T{i}", "stage": "MOMENTUM_1", "risk_tags": []}
        for i in range(500)
    ]
    msg = _format_momentum_message(big_us, _sample_kr(), as_of="2026-05-06")
    assert len(msg) <= 3500


def test_send_momentum_brief_skips_when_both_none():
    from telegram_sender import send_momentum_brief
    with patch("telegram_sender._send_message") as mock_send:
        result = send_momentum_brief(None, None)
    assert result is False
    mock_send.assert_not_called()


def test_send_momentum_brief_calls_send_when_us_only():
    from telegram_sender import send_momentum_brief
    with patch("telegram_sender._send_message", return_value=True) as mock_send:
        result = send_momentum_brief(_sample_us(), None)
    assert result is True
    mock_send.assert_called_once()
    sent_msg = mock_send.call_args[0][0]
    assert "NVDA" in sent_msg
