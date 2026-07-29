"""Tests for portfolio_data user-category classifier."""
from __future__ import annotations

from portfolio_data import (
    USER_CATEGORIES,
    get_ticker_category,
    category_for_weight_key,
)


def test_user_categories_fixed_order():
    assert USER_CATEGORIES == ["지수", "배당주", "개별주", "현금"]


def test_index_tickers():
    for t in ["VOO", "SPY", "QQQ", "QLD", "102110", "069500", "232080", "229200"]:
        assert get_ticker_category(t) == "지수", t


def test_dividend_tickers():
    for t in ["SCHD", "JEPI", "O", "458730", "446720", "0153K0"]:
        assert get_ticker_category(t) == "배당주", t


def test_cash_ticker():
    assert get_ticker_category("BIL") == "현금"


def test_individual_and_default():
    for t in ["AAPL", "005930", "110990", "SOXL", "SOXX", "TLT", "396500", "UNKNOWN123"]:
        assert get_ticker_category(t) == "개별주", t


def test_qld_index_soxl_individual():
    assert get_ticker_category("QLD") == "지수"
    assert get_ticker_category("SOXL") == "개별주"


def test_category_for_weight_key_resolves_korean_name():
    assert category_for_weight_key("삼성전자") == "개별주"
    assert category_for_weight_key("디아이티") == "개별주"
    assert category_for_weight_key("TIGER 200") == "지수"
    assert category_for_weight_key("069500") == "지수"
    assert category_for_weight_key("005935") == "개별주"
    assert category_for_weight_key("SCHD") == "배당주"
    assert category_for_weight_key("BIL") == "현금"
