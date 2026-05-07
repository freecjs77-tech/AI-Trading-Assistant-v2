"""portfolio_stop_report 렌더링 smoke 테스트."""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from portfolio_stop_report import generate_portfolio_stop_page


def _sample_result():
    return {
        "status": "ok",
        "owner": "me",
        "date": "2026-05-07",
        "summary": {"HOLD": 1, "TIGHT": 1, "EXIT_READY": 1, "EXIT": 0, "CLOSED": 0},
        "positions": [
            {"ticker": "TSLA", "name": "Tesla", "mode": "MOMENTUM",
             "highest_close": 410.0, "highest_close_date": "2026-02-15",
             "current_close": 358.5, "stop_price": 380.0, "gap_pct": -5.7,
             "raw_signal": "EXIT_READY", "display_signal": "EXIT_READY",
             "display_downgraded": False, "is_new_position": False,
             "below_stop_count": 1, "action": "Trim 30~50%",
             "display_action": "Trim 30~50%", "entry_date": "2026-01-02"},
            {"ticker": "NVDA", "name": "NVIDIA", "mode": "MOMENTUM",
             "highest_close": 945.0, "highest_close_date": "2026-05-05",
             "current_close": 920.0, "stop_price": 874.0, "gap_pct": 5.26,
             "raw_signal": "TIGHT", "display_signal": "TIGHT",
             "display_downgraded": False, "is_new_position": False,
             "below_stop_count": 0, "action": "Trim 10~15%",
             "display_action": "Trim 10~15%", "entry_date": "2026-01-02"},
            {"ticker": "VOO", "name": "Vanguard S&P 500", "mode": "CORE",
             "highest_close": 540.0, "highest_close_date": "2026-04-30",
             "current_close": 535.0, "stop_price": 475.2, "gap_pct": 12.6,
             "raw_signal": "HOLD", "display_signal": "HOLD",
             "display_downgraded": False, "is_new_position": False,
             "below_stop_count": 0, "action": "Hold",
             "display_action": "Hold", "entry_date": "2026-01-02"},
        ],
        "changes": [
            {"ticker": "TSLA", "from": "TIGHT", "to": "EXIT_READY"},
        ],
    }


def test_render_creates_html_file(tmp_path):
    out = generate_portfolio_stop_page(_sample_result(), str(tmp_path),
                                        anchor_date="2026-01-02")
    assert os.path.exists(out)
    text = open(out, encoding="utf-8").read()
    assert "Portfolio Risk Dashboard" in text
    assert "TSLA" in text and "NVDA" in text and "VOO" in text
    assert "🟠 EXIT READY" in text or "EXIT_READY" in text


if __name__ == "__main__":
    test_render_creates_html_file(tempfile.TemporaryDirectory().name)
    print("[OK] portfolio_stop_report tests passed.")
