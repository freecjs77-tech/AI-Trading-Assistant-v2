"""generate_momentum_pages — produces HTML files."""
import sys, os, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def setup():
    return tempfile.mkdtemp(prefix="report_test_")


def teardown(d):
    shutil.rmtree(d, ignore_errors=True)


def _sample(market="US", status="ok"):
    return {
        "market": market, "version": "Momentum v1.0", "as_of": "2026-05-06",
        "scanned_count": 100, "elapsed_s": 30.0,
        "top_sectors": [], "signals": {"MOMENTUM_3": [], "MOMENTUM_2": [], "MOMENTUM_1": []},
        "backtest_summary": None, "status": status, "error_message": None,
    }


def test_generate_momentum_pages_writes_us_and_kr():
    from report_generator import generate_momentum_pages
    tmp = setup()
    try:
        files = generate_momentum_pages(
            momentum_us=_sample("US"),
            momentum_kr=_sample("KR"),
            output_dir=tmp,
        )
        assert len(files) == 2
        us_path = os.path.join(tmp, "momentum_us_2026-05-06.html")
        kr_path = os.path.join(tmp, "momentum_kr_2026-05-06.html")
        assert os.path.exists(us_path)
        assert os.path.exists(kr_path)
        with open(us_path, encoding="utf-8") as f:
            assert "🇺🇸" in f.read() or "US Momentum" in f.read()
    finally:
        teardown(tmp)


def test_generate_momentum_pages_skips_none_results():
    """momentum_us=None → US 페이지 생성 안 됨, KR만 생성."""
    from report_generator import generate_momentum_pages
    tmp = setup()
    try:
        files = generate_momentum_pages(
            momentum_us=None,
            momentum_kr=_sample("KR"),
            output_dir=tmp,
        )
        assert len(files) == 1
        assert "momentum_kr" in files[0]
        assert not os.path.exists(os.path.join(tmp, "momentum_us_2026-05-06.html"))
    finally:
        teardown(tmp)


def test_generate_momentum_pages_returns_empty_when_both_none():
    from report_generator import generate_momentum_pages
    tmp = setup()
    try:
        files = generate_momentum_pages(momentum_us=None, momentum_kr=None,
                                         output_dir=tmp)
        assert files == []
    finally:
        teardown(tmp)


def test_generate_momentum_pages_skips_failed_status():
    """status='failed' 결과는 페이지 생성 skip (orphan 방지)."""
    from report_generator import generate_momentum_pages
    tmp = setup()
    try:
        result = _sample("US", status="failed")
        result["error_message"] = "network down"
        files = generate_momentum_pages(momentum_us=result, momentum_kr=None,
                                         output_dir=tmp)
        assert files == []
    finally:
        teardown(tmp)
