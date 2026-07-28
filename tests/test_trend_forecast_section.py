"""Tests for the 20-year asset forecast section in trend_template.html.

Renders the real trend page via generate_trend_page and asserts the forecast
section HTML/JS is present for multi-owner (합산 토글 존재) and absent for
single-owner. No backend logic to test — this guards the template wiring.
"""
from __future__ import annotations

import json
import os
import tempfile

from report_generator import generate_trend_page

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_daily():
    me_path = os.path.join(PROJECT_DIR, "history", "portfolio_daily.json")
    wife_path = os.path.join(PROJECT_DIR, "history", "portfolio_daily_wife.json")
    me = json.load(open(me_path, encoding="utf-8"))
    wife = json.load(open(wife_path, encoding="utf-8"))
    return me, wife


def _render(owner_daily):
    me, _ = _load_daily()
    with tempfile.TemporaryDirectory() as d:
        path = generate_trend_page(me, d, owner_daily=owner_daily, date_str="2026-07-28")
        with open(path, encoding="utf-8") as f:
            return f.read()


def test_forecast_section_present_multi_owner():
    _, wife = _load_daily()
    html = _render({"wife": wife})
    assert 'id="forecastSection"' in html
    assert 'id="forecastChart"' in html
    assert 'id="forecastRate"' in html
    assert "_toggleForecast" in html
    assert "_ensureForecastChart" in html
    assert "_fcSeries" in html
    assert "_toggleForecast(btn.dataset.owner)" in html


def test_forecast_section_absent_single_owner():
    html = _render(None)
    assert 'id="forecastSection"' not in html
