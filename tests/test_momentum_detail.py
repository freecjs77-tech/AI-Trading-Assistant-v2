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


def _make_jinja_env():
    """Return a Jinja2 Environment with the custom filters needed by detail_template.html."""
    import jinja2
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=True,
    )
    env.filters["f4"] = lambda x: f"{x:.4f}" if isinstance(x, (int, float)) else str(x)
    env.filters["f3"] = lambda x: f"{x:.3f}" if isinstance(x, (int, float)) else str(x)
    env.filters["f2"] = lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else str(x)
    env.filters["f1"] = lambda x: f"{x:.1f}" if isinstance(x, (int, float)) else str(x)
    env.filters["f0"] = lambda x: f"{x:.0f}" if isinstance(x, (int, float)) else str(x)
    env.filters["comma"] = lambda x: f"{x:,.0f}" if isinstance(x, (int, float)) else str(x)
    env.filters["pct1"] = lambda x: f"{x:.1f}" if isinstance(x, (int, float)) else str(x)
    env.filters["sign_pct"] = lambda x: (f"+{x:.1f}%" if x >= 0 else f"{x:.1f}%") if isinstance(x, (int, float)) else str(x)
    env.filters["badge_class"] = lambda s: "badge-HOLD"
    env.filters["mcap"] = lambda v, currency="USD": ""
    env.filters["shares_fmt"] = lambda x: str(x)
    return env


def _base_ctx(**extra):
    """Return a minimal context dict that satisfies all unconditional variable references
    in detail_template.html, so tests can reach the momentum section."""
    ctx = {
        # header / price block
        "ticker": "TEST", "name": "Test", "cls": "", "market_cap": None,
        "currency": "USD", "date_ko": "2026-05-09", "is_kospi": False,
        "price": 100.0, "change_pct": 0.0,
        # signal badge
        "signal": "HOLD", "note": "", "buy_streak": 0, "buy_confirmed": False,
        # portfolio info (guarded by {% if shares %})
        "shares": 0, "avg_cost": 0.0, "value": 0.0, "pnl_pct": 0.0,
        # 52w range (guarded by {% if high_52w and low_52w %})
        "high_52w": None, "low_52w": None, "range_pct": 0.0,
        # metric cards (all guarded with is not none checks)
        "rsi": None, "macd_hist": None, "macd_hist_trend_ko": "",
        "adx": None, "bb_pct": None, "volume_ratio": None,
        "drawdown": None, "ma20": None, "ma200": None,
        # chart (guarded)
        "chart_exists": False,
        # signal section
        "signals": [], "indicators": {}, "judgment_sections": [], "history_rows": [],
        "hypo_return": None,
        # momentum
        "momentum_data": None,
    }
    ctx.update(extra)
    return ctx


def test_detail_template_renders_maturity_line():
    """CURRENT STATUS block shows Maturity + dist_ema9 when present in last entry."""
    env = _make_jinja_env()
    tmpl = env.get_template("detail_template.html")
    momentum_data = {
        "last": {
            "stage": "EM", "time_in_stage": 3,
            "entry_price": 22.0, "price": 23.5,
            "maturity": "EARLY", "dist_ema9_pct": 1.8, "rsi": 64.0,
            "risk_tags": [],
        },
        "recent": [],
    }
    html = tmpl.render(_base_ctx(
        ticker="PLTR", name="Palantir",
        momentum_data=momentum_data,
    ))
    assert "Maturity" in html
    assert "EARLY" in html
    assert "1.8" in html  # dist_ema9 shown


def test_detail_template_omits_maturity_when_missing():
    """If maturity field absent (legacy entry), block doesn't crash."""
    env = _make_jinja_env()
    tmpl = env.get_template("detail_template.html")
    momentum_data = {
        "last": {
            "stage": "MOMENTUM_1", "time_in_stage": 1,
            "entry_price": 100.0, "price": 102.0, "risk_tags": [],
            # no maturity / no dist_ema9_pct
        },
        "recent": [],
    }
    html = tmpl.render(_base_ctx(
        ticker="X", name="X",
        momentum_data=momentum_data,
    ))
    # No exception, page renders. Maturity line is conditional.
    assert "MOMENTUM_1" in html
