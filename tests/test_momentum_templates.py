"""모멘텀 페이지 렌더링 smoke test."""
import sys
import os
import tempfile
import shutil
from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _render(template_name: str, **ctx) -> str:
    project_dir = os.path.join(os.path.dirname(__file__), "..")
    env = Environment(loader=FileSystemLoader(os.path.join(project_dir, "templates")))
    return env.get_template(template_name).render(**ctx)


def _sample_result(market="US"):
    return {
        "market": market,
        "version": "Momentum v1.0",
        "as_of": "2026-05-06",
        "scanned_count": 312,
        "elapsed_s": 47.2,
        "top_sectors": [
            {"ticker": "XLK", "score": 98, "ret_5d_pct": 5.2, "rs_score": 11},
            {"ticker": "XLC", "score": 87, "ret_5d_pct": 4.1, "rs_score": 5},
        ],
        "signals": {
            "MOMENTUM_3": [{"ticker": "NVDA", "name": "NVIDIA", "stage": "MOMENTUM_3",
                            "tier": "MOMENTUM_3", "maturity": "EXTENDED",
                            "price": 920.0, "rsi": 78,
                            "ret_1d_pct": 1.2, "ret_5d_pct": 12.0, "ret_20d_pct": 28.5,
                            "dist_ema9_pct": 4.2, "streak": 5,
                            "sector": "XLK", "sector_top_rank": 1,
                            "rs_vs_sector": True,
                            "risk_tags": ["OVERHEAT", "PARABOLIC"], "hint": "신중"}],
            "MOMENTUM_2": [],
            "MOMENTUM_1": [],
            "EM": [],
        },
        "rotation_radar": [],
        "backtest_summary": {
            "as_of": "2026-05-06", "version": "Momentum v1.0",
            "by_stage": {
                "MOMENTUM_3": {"leg_count": 47, "win_rate_5d_pct": 68.1,
                               "avg_ret_3d_pct": 2.1, "avg_ret_5d_pct": 4.8,
                               "avg_ret_10d_pct": 7.2, "avg_mdd_pct": -3.1,
                               "avg_max_ret_pct": 9.5, "avg_min_ret_pct": -1.5,
                               "avg_duration_days": 5.2},
            },
            "by_streak": {"3+": {"avg_ret_5d": 5.7, "win_rate_pct": 73}},
            "alerts": {"consecutive_loss_warning": False, "recent_5_legs_loss_count": 1},
        },
        "status": "ok",
    }


def test_momentum_us_renders_signals():
    html = _render("momentum_us.html", result=_sample_result("US"), market_label="🇺🇸 US")
    assert "Momentum" in html
    assert "NVDA" in html
    assert "MOMENTUM_3" in html or "M3" in html
    assert "XLK" in html
    assert "신중" in html
    assert "OVERHEAT" in html


def test_momentum_us_renders_backtest_summary():
    html = _render("momentum_us.html", result=_sample_result("US"), market_label="🇺🇸 US")
    assert "47" in html       # leg_count
    assert "68" in html       # win_rate


def test_momentum_kr_renders():
    result = _sample_result("KR")
    result["signals"]["MOMENTUM_2"] = [{
        "ticker": "005930.KS", "name": None, "stage": "MOMENTUM_2",
        "tier": "MOMENTUM_2", "maturity": "MID",
        "price": 80000, "rsi": 62,
        "ret_1d_pct": 1.0, "ret_5d_pct": 7.0, "ret_20d_pct": 14.0,
        "dist_ema9_pct": 2.1, "streak": 2,
        "sector": "091160.KS", "sector_top_rank": None,
        "rs_vs_sector": False, "risk_tags": [], "hint": "적극",
    }]
    html = _render("momentum_kr.html", result=result, market_label="🇰🇷 KR")
    assert "005930.KS" in html
    assert "KR" in html or "🇰🇷" in html


def test_momentum_us_handles_empty_signals():
    result = _sample_result("US")
    result["signals"] = {"MOMENTUM_3": [], "MOMENTUM_2": [], "MOMENTUM_1": []}
    html = _render("momentum_us.html", result=result, market_label="🇺🇸 US")
    assert "Momentum" in html   # 빈 페이지여도 렌더 깨지면 안됨


def test_template_has_emerging_section_heading():
    src = open("templates/base_momentum.html", encoding="utf-8").read()
    assert "Momentum Leaders" in src
    assert "Emerging Momentum" in src


def test_template_has_rotation_radar_block():
    src = open("templates/base_momentum.html", encoding="utf-8").read()
    assert "rotation_radar" in src
    assert "Potential Sector Rotation" in src or "Sector Rotation" in src


def test_template_has_maturity_column():
    src = open("templates/base_momentum.html", encoding="utf-8").read()
    assert "Maturity" in src
    assert "maturity-early" in src
    assert "maturity-mid" in src
    assert "maturity-extended" in src


def test_template_has_dist_ema9_column():
    src = open("templates/base_momentum.html", encoding="utf-8").read()
    assert "dist_ema9" in src


def test_template_has_em_tier_class():
    src = open("templates/base_momentum.html", encoding="utf-8").read()
    assert ".tier-em" in src or ".EM" in src


def test_template_dropped_change_column_in_signals_table():
    """Change column was redundant with 1d/5d/20d returns."""
    src = open("templates/base_momentum.html", encoding="utf-8").read()
    assert "<th>Change</th>" not in src


def test_template_has_streak_column():
    src = open("templates/base_momentum.html", encoding="utf-8").read()
    assert "<th>Streak</th>" in src


def test_template_renders_em_signals(tmp_path):
    """Render template with EM signals and rotation radar — produces valid HTML."""
    import jinja2
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=True,
    )
    tmpl = env.get_template("base_momentum.html")
    result = {
        "as_of": "2026-05-09", "version": "Momentum v1.5",
        "scanned_count": 1003, "elapsed_s": 47.0, "status": "ok",
        "top_sectors": [],
        "signals": {
            "MOMENTUM_3": [], "MOMENTUM_2": [], "MOMENTUM_1": [],
            "EM": [{
                "ticker": "DUOL", "name": "Duolingo", "tier": "EM",
                "stage": "EM", "maturity": "EARLY",
                "sector": "Education", "sector_top_rank": None,
                "price": 180.0, "rsi": 64.0,
                "ret_1d_pct": 1.2, "ret_5d_pct": 4.5, "ret_20d_pct": 11.0,
                "dist_ema9_pct": 1.8, "streak": 3, "change": "HOLD",
                "rs_vs_sector": None, "risk_tags": [], "hint": "관찰",
            }],
        },
        "rotation_radar": [["Education", 4], ["Cybersecurity", 3]],
        "backtest_summary": None,
    }
    html = tmpl.render(market_label="US", result=result)
    assert "DUOL" in html
    assert "Duolingo" in html
    assert "EARLY" in html
    assert "Education" in html
    assert "1.8" in html      # dist_ema9
    assert "3d" in html        # streak rendered as "3d"
