"""포트폴리오 데이터 기준일(as-of) 파싱 + 노후도 배지 로직 테스트."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from report_generator import (  # noqa: E402
    parse_portfolio_as_of,
    _staleness_ctx,
    PORTFOLIO_STALE_WARN_DAYS,
    PORTFOLIO_STALE_ALERT_DAYS,
)


# ── parse_portfolio_as_of ─────────────────────────────

def _write(tmp_path, text):
    p = tmp_path / "pf.md"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_parse_as_of_korean_header(tmp_path):
    path = _write(tmp_path,
                  "# Portfolio Holdings\n> 최종 업데이트: 2026-07-29 (스크린샷)\n")
    assert parse_portfolio_as_of(path) == "2026-07-29"


def test_parse_as_of_english_header(tmp_path):
    path = _write(tmp_path, "# Holdings\n> as-of: 2026-01-02\n")
    assert parse_portfolio_as_of(path) == "2026-01-02"


def test_parse_as_of_missing_date(tmp_path):
    path = _write(tmp_path, "# Holdings\n> 최종 업데이트: 미정\n")
    assert parse_portfolio_as_of(path) is None


def test_parse_as_of_missing_file():
    assert parse_portfolio_as_of("/no/such/file.md") is None
    assert parse_portfolio_as_of(None) is None


# ── _staleness_ctx ────────────────────────────────────

def test_staleness_none_when_no_asof():
    ctx = _staleness_ctx(None, "2026-11-24")
    assert ctx["portfolio_as_of"] is None
    assert ctx["portfolio_stale_days"] is None
    assert ctx["portfolio_stale_level"] is None


def test_staleness_ok_level():
    ctx = _staleness_ctx("2026-11-20", "2026-11-24")
    assert ctx["portfolio_stale_days"] == 4
    assert ctx["portfolio_stale_level"] == "ok"


def test_staleness_warn_boundary():
    # 정확히 WARN 임계값 → warn
    from datetime import datetime, timedelta
    ref = datetime(2026, 11, 24)
    asof = (ref - timedelta(days=PORTFOLIO_STALE_WARN_DAYS)).strftime("%Y-%m-%d")
    ctx = _staleness_ctx(asof, "2026-11-24")
    assert ctx["portfolio_stale_days"] == PORTFOLIO_STALE_WARN_DAYS
    assert ctx["portfolio_stale_level"] == "warn"


def test_staleness_alert_boundary():
    from datetime import datetime, timedelta
    ref = datetime(2026, 11, 24)
    asof = (ref - timedelta(days=PORTFOLIO_STALE_ALERT_DAYS)).strftime("%Y-%m-%d")
    ctx = _staleness_ctx(asof, "2026-11-24")
    assert ctx["portfolio_stale_days"] == PORTFOLIO_STALE_ALERT_DAYS
    assert ctx["portfolio_stale_level"] == "alert"


def test_staleness_four_months_is_alert():
    # me.md 실제 케이스: 2026-07-29 기준, 11-24 리포트 → alert
    ctx = _staleness_ctx("2026-07-29", "2026-11-24")
    assert ctx["portfolio_stale_level"] == "alert"
    assert ctx["portfolio_stale_days"] > PORTFOLIO_STALE_ALERT_DAYS


def test_staleness_future_asof_clamped_to_zero():
    ctx = _staleness_ctx("2026-12-01", "2026-11-24")
    assert ctx["portfolio_stale_days"] == 0
    assert ctx["portfolio_stale_level"] == "ok"


def test_staleness_bad_date_string():
    ctx = _staleness_ctx("not-a-date", "2026-11-24")
    assert ctx["portfolio_stale_days"] is None
    assert ctx["portfolio_stale_level"] is None
