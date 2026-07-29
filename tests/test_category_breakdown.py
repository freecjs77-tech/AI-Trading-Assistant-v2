"""Tests for report_generator user-category breakdown aggregation."""
from __future__ import annotations

import json
import os

from portfolio_data import USER_CATEGORIES
from report_generator import (
    _user_category_rows,
    _build_owner_payload,
    _build_combined_payload,
)

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _latest(daily: dict) -> dict:
    return daily[max(k for k in daily if not k.startswith("_"))]


def _load(name: str) -> dict:
    p = os.path.join(PROJECT_DIR, "history", name)
    return json.load(open(p, encoding="utf-8"))


def test_rows_shape_and_order():
    me = _load("portfolio_daily.json")
    rows = _user_category_rows(_latest(me))
    assert [r["name"] for r in rows] == USER_CATEGORIES
    for r in rows:
        assert set(r.keys()) == {"name", "value", "amount_man"}
    assert 99.0 <= sum(r["value"] for r in rows) <= 101.0


def test_amount_matches_total():
    me = _load("portfolio_daily.json")
    snap = _latest(me)
    rows = _user_category_rows(snap)
    total_man = round((snap.get("total_value_krw", 0) or 0) / 1e4)
    assert abs(sum(r["amount_man"] for r in rows) - total_man) <= 4


def test_owner_payload_includes_category():
    me = _load("portfolio_daily.json")
    payload = _build_owner_payload(me)
    assert "category" in payload
    assert [r["name"] for r in payload["category"]] == USER_CATEGORIES


def test_combined_is_krw_sum_of_owners():
    me = _load("portfolio_daily.json")
    wife = _load("portfolio_daily_wife.json")
    me_rows = _user_category_rows(_latest(me))
    wife_rows = _user_category_rows(_latest(wife))
    comb = _build_combined_payload(me, {"wife": wife})["category"]

    def man(rows, cat):
        return next(r["amount_man"] for r in rows if r["name"] == cat)

    for cat in USER_CATEGORIES:
        assert abs(man(comb, cat) - (man(me_rows, cat) + man(wife_rows, cat))) <= 3
