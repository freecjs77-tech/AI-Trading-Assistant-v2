"""smoke_test.check_signal_distribution — 시그널 배지 인식 회귀 테스트.

현재 템플릿은 <span class="sig sig-XXX">LABEL</span> 로 렌더한다. 과거 스모크
regex가 구 'badge badge-XXX' 만 찾아 매 실행마다 오탐 CRITICAL("시그널 배지를
찾을 수 없음")을 냈고, 배포 게이트 도입 후 이 오탐이 배포를 막았다. 이 테스트는
현재 마크업을 스모크가 올바로 인식하는지 고정한다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from smoke_test import check_signal_distribution  # noqa: E402


CURRENT_MARKUP = """<html><body>
<table>
<tr><td><span class="sig sig-top">TOP</span></td></tr>
<tr><td><span class="sig sig-buy1">1st_BUY</span></td></tr>
<tr><td><span class="sig sig-buy3">3rd_BUY</span></td></tr>
<tr><td><span class="sig sig-watch">WATCH</span></td></tr>
<tr><td><span class="sig sig-hold">HOLD</span></td></tr>
<tr><td><span class="sig sig-tp2">PROFIT_2</span></td></tr>
<tr><td><span class="sig sig-cash">CASH</span></td></tr>
</body></html>"""

LEGACY_MARKUP = """<html><body>
<span class="badge badge-BUY">BUY</span>
<span class="badge badge-HOLD">HOLD</span>
<span class="badge badge-WATCH">WATCH</span>
<span class="badge badge-L3">L3</span>
<span class="badge badge-CASH">CASH</span>
<span class="badge badge-BUY">BUY</span>
</body></html>"""


def _write_report(tmp_path, html, today="2026-11-25"):
    rdir = tmp_path / "reports"
    rdir.mkdir()
    (rdir / f"report_{today}.html").write_text(html, encoding="utf-8")
    return str(rdir), today


def test_current_sig_markup_no_critical(tmp_path):
    rdir, today = _write_report(tmp_path, CURRENT_MARKUP)
    errors = check_signal_distribution(rdir, today)
    joined = " ".join(errors)
    assert "[CRITICAL]" not in joined, f"unexpected critical: {errors}"
    assert "시그널 배지를 찾을 수 없음" not in joined
    # 7개 배지 → '0개' 경고도 없어야 함
    assert "배지 0개" not in joined


def test_legacy_badge_markup_still_recognized(tmp_path):
    rdir, today = _write_report(tmp_path, LEGACY_MARKUP)
    errors = check_signal_distribution(rdir, today)
    assert "[CRITICAL]" not in " ".join(errors)


def test_truly_empty_report_still_flags_critical(tmp_path):
    rdir, today = _write_report(tmp_path, "<html><body>no signals here</body></html>")
    errors = check_signal_distribution(rdir, today)
    assert any("[CRITICAL]" in e for e in errors)
