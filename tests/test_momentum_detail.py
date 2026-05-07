"""Detail page에 Momentum CURRENT STATUS + History 섹션 노출 검증."""
import sys, os, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def setup():
    return tempfile.mkdtemp(prefix="detail_test_")


def teardown(d):
    shutil.rmtree(d, ignore_errors=True)


def _hist():
    return {
        "data": {
            "NVDA": {
                "2026-05-02": {"stage": "MOMENTUM_2", "streak": 1, "change": "NEW",
                               "price": 850.0, "entry_price": 850.0,
                               "entry_date": "2026-05-02", "time_in_stage": 1,
                               "rsi": 60, "risk_tags": []},
                "2026-05-03": {"stage": "MOMENTUM_3", "streak": 2, "change": "UPGRADE",
                               "price": 875.0, "entry_price": 875.0,
                               "entry_date": "2026-05-03", "time_in_stage": 1,
                               "rsi": 68, "risk_tags": ["OVERHEAT"]},
                "2026-05-06": {"stage": "MOMENTUM_3", "streak": 5, "change": "HOLD",
                               "price": 920.0, "entry_price": 875.0,
                               "entry_date": "2026-05-03", "time_in_stage": 4,
                               "rsi": 78, "risk_tags": ["OVERHEAT", "PARABOLIC"]},
            }
        }
    }


def test_detail_renders_momentum_status_for_listed_ticker():
    from report_generator import generate_detail_pages
    tmp = setup()
    try:
        files = generate_detail_pages(
            market_data={"data": {"NVDA": {"price": 920.0, "rsi14": 78,
                                            "ma20": 850.0, "ma50": 800.0,
                                            "macd": 5.0, "signal": 4.0,
                                            "macd_hist": 1.0, "macd_hist_trend": "rising",
                                            "change_pct": 2.0, "change_3d_pct": 8.0,
                                            "high_20d": 925.0, "high_52w": 925.0,
                                            "volume_ratio": 1.5}}},
            portfolio=[{"ticker": "NVDA", "name": "NVIDIA", "shares": 100, "value_usd": 92000}],
            signals={"NVDA": {"action": "HOLD"}},
            history={},
            output_dir=tmp,
            momentum_us_history=_hist(),
            momentum_kr_history=None,
        )
        nvda_html_path = os.path.join(tmp, "NVDA.html")
        assert os.path.exists(nvda_html_path)
        with open(nvda_html_path, encoding="utf-8") as f:
            html = f.read()
        assert "Momentum" in html
        assert "MOMENTUM_3" in html or "M3" in html
        assert "OVERHEAT" in html
        assert "2026-05-06" in html
    finally:
        teardown(tmp)


def test_detail_skips_momentum_section_when_no_history():
    """ticker가 momentum history에 없으면 섹션 노출 안 됨."""
    from report_generator import generate_detail_pages
    tmp = setup()
    try:
        files = generate_detail_pages(
            market_data={"data": {"AAPL": {"price": 200.0, "rsi14": 60,
                                            "ma20": 195.0}}},
            portfolio=[{"ticker": "AAPL", "name": "Apple", "shares": 50, "value_usd": 10000}],
            signals={"AAPL": {"action": "HOLD"}},
            history={},
            output_dir=tmp,
            momentum_us_history=_hist(),  # NVDA만 있음
            momentum_kr_history=None,
        )
        aapl_path = os.path.join(tmp, "AAPL.html")
        assert os.path.exists(aapl_path)
        with open(aapl_path, encoding="utf-8") as f:
            html = f.read()
        # Momentum 섹션 미노출
        assert "🔥 Momentum History" not in html
    finally:
        teardown(tmp)


def test_detail_works_with_no_momentum_args_at_all():
    """기존 호출 패턴 (momentum 인자 없음) 깨지면 안 됨 — backward compat."""
    from report_generator import generate_detail_pages
    tmp = setup()
    try:
        files = generate_detail_pages(
            market_data={"data": {"AAPL": {"price": 200.0, "rsi14": 60,
                                            "ma20": 195.0}}},
            portfolio=[{"ticker": "AAPL", "name": "Apple", "shares": 50, "value_usd": 10000}],
            signals={"AAPL": {"action": "HOLD"}},
            history={},
            output_dir=tmp,
        )
        assert os.path.exists(os.path.join(tmp, "AAPL.html"))
    finally:
        teardown(tmp)
