"""report_template.html에 모멘텀 링크 노출 검증."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from jinja2 import Environment, FileSystemLoader


def _render_with_momentum(has_us=True, has_kr=True):
    """Minimal render test for momentum nav links."""
    project_dir = os.path.join(os.path.dirname(__file__), "..")
    env = Environment(loader=FileSystemLoader(os.path.join(project_dir, "templates")))
    # Register all required filters
    env.filters["f0"] = lambda x: f"{x:.0f}" if isinstance(x, (int, float)) else str(x)
    env.filters["f1"] = lambda x: f"{x:.1f}" if isinstance(x, (int, float)) else str(x)
    env.filters["f2"] = lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else str(x)
    env.filters["f3"] = lambda x: f"{x:.3f}" if isinstance(x, (int, float)) else str(x)
    env.filters["f4"] = lambda x: f"{x:.4f}" if isinstance(x, (int, float)) else str(x)
    env.filters["comma"] = lambda x: f"{x:,.0f}" if isinstance(x, (int, float)) else str(x)
    env.filters["comma2"] = lambda x: f"{x:,.2f}" if isinstance(x, (int, float)) else str(x)
    env.filters["pct1"] = lambda x: f"{x:.1f}" if isinstance(x, (int, float)) else str(x)
    env.filters["pct2"] = lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else str(x)
    env.filters["sign_pct"] = lambda x: f"+{x:.1f}%" if x >= 0 else f"{x:.1f}%"
    env.filters["mcap"] = lambda x: str(x)
    env.filters["shares_fmt"] = lambda x: f"{x:.3f}" if x < 100 else f"{x:,.0f}"
    env.filters["badge_class"] = lambda x: ""
    env.filters["card_class"] = lambda x: ""
    return env.get_template("report_template.html").render(
        # Minimal context to satisfy template vars
        date="2026-05-06",
        date_ko="2026년 5월 6일",
        fetched_at="",
        market_status={"US": "closed", "KRX": "closed"},
        portfolio_source="portfolio.md",
        portfolio=[],
        holdings=[],
        signals={},
        prev_signals={},
        prev_signal_map={},
        history={},
        market_data={"_meta": {}, "_macro": {}},
        # Portfolio summary
        total_value=0,
        total_value_krw=0,
        cost_basis=0,
        cost_basis_krw=0,
        total_pnl=0,
        total_pnl_krw=0,
        total_pnl_pct=0,
        n_holdings=0,
        n_categories=0,
        cash_value=0,
        cash_value_krw=0,
        cash_pct=0,
        div_annual=0,
        div_annual_krw=0,
        div_monthly=0,
        div_monthly_krw=0,
        div_yield=0,
        div_top=[],
        n_tp2=0,
        n_tp1=0,
        n_buy=0,
        n_watch=0,
        n_hold=0,
        alert_msg="",
        tp2_signals=[],
        tp1_signals=[],
        buy_signals=[],
        bond_signals=[],
        watch_signals=[],
        all_signals=[],
        # Nav
        nav_portfolio="index.html",
        nav_scanner="scanner.html",
        nav_backtest="backtest.html",
        nav_trend="trend.html",
        active_nav="portfolio",
        # Momentum nav context
        has_momentum_us=has_us,
        has_momentum_kr=has_kr,
        momentum_us_url="momentum_us_2026-05-06.html" if has_us else "",
        momentum_kr_url="momentum_kr_2026-05-06.html" if has_kr else "",
    )


def test_nav_shows_us_link_when_available():
    html = _render_with_momentum(has_us=True, has_kr=True)
    assert "Momentum US" in html
    assert "momentum_us_2026-05-06.html" in html


def test_nav_shows_kr_link_when_available():
    html = _render_with_momentum(has_us=True, has_kr=True)
    assert "Momentum KR" in html
    assert "momentum_kr_2026-05-06.html" in html


def test_nav_hides_us_link_when_unavailable():
    html = _render_with_momentum(has_us=False, has_kr=True)
    assert "momentum_us_" not in html


def test_nav_hides_kr_link_when_unavailable():
    html = _render_with_momentum(has_us=True, has_kr=False)
    assert "momentum_kr_" not in html
