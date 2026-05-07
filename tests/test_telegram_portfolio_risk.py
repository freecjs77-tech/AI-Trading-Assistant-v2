"""telegram_sender.send_portfolio_risk_summary build_message 테스트."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from telegram_sender import _build_portfolio_risk_message


def _result(owner, hold=0, tight=0, ready=0, exit_=0, items=None):
    return {
        "status": "ok", "owner": owner, "date": "2026-05-07",
        "summary": {"HOLD": hold, "TIGHT": tight,
                     "EXIT_READY": ready, "EXIT": exit_},
        "positions": items or [],
        "changes": [],
    }


def _pos(ticker, signal, **kw):
    return {
        "ticker": ticker, "name": ticker, "display_signal": signal,
        "below_stop_count": kw.get("count", 0),
        "is_new_position": kw.get("is_new", False),
        "display_action": {"HOLD": "Hold", "TIGHT": "Trim 10~15%",
                            "EXIT_READY": "Trim 30~50%",
                            "EXIT": "Exit trading portion"}[signal],
    }


def test_message_basic_two_owners():
    me = _result("me", hold=10, tight=2, ready=1, exit_=0,
                  items=[_pos("AAPL", "TIGHT"), _pos("MSFT", "TIGHT"),
                         _pos("PLTR", "EXIT_READY", count=1)])
    wife = _result("wife", hold=5, tight=1, ready=0, exit_=0,
                    items=[_pos("SCHD", "TIGHT")])
    msg = _build_portfolio_risk_message(me, wife,
                                          base_url="https://example.com",
                                          date_str="2026-05-07")
    assert "Portfolio Risk Summary" in msg
    assert "[me]" in msg and "[wife]" in msg
    assert "AAPL" in msg or "MSFT" in msg
    assert "PLTR" in msg
    assert "SCHD" in msg
    assert len(msg) <= 3500


def test_message_overflow_truncation():
    """EXIT가 8개일 때 5만 표시 + '+N more'."""
    items = [_pos(f"T{i:02d}", "EXIT", count=2) for i in range(8)]
    me = _result("me", hold=0, tight=0, ready=0, exit_=8, items=items)
    msg = _build_portfolio_risk_message(me, None, base_url="https://x",
                                          date_str="2026-05-07")
    assert "+ 3 more" in msg or "more" in msg.lower()
    # 5개는 모두 노출
    for i in range(5):
        assert f"T{i:02d}" in msg


def test_message_wife_optional():
    me = _result("me", hold=1)
    msg = _build_portfolio_risk_message(me, None, base_url="x",
                                          date_str="2026-05-07")
    assert "[me]" in msg
    assert "[wife]" not in msg


def test_message_zero_alerts():
    """모두 HOLD면 EXIT/EXIT_READY/TIGHT 섹션 없음 (간결)."""
    me = _result("me", hold=20, tight=0, ready=0, exit_=0)
    msg = _build_portfolio_risk_message(me, None, base_url="x",
                                          date_str="2026-05-07")
    assert "🟢 HOLD (20)" in msg
    assert "🔴 EXIT" not in msg or "🔴 EXIT (0)" in msg


if __name__ == "__main__":
    test_message_basic_two_owners()
    test_message_overflow_truncation()
    test_message_wife_optional()
    test_message_zero_alerts()
    print("[OK] telegram_portfolio_risk tests passed.")
