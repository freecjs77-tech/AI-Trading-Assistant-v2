"""Tests for benchmark_ytd module."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import benchmark_ytd


def test_constants_defined():
    assert benchmark_ytd.ANCHOR_DATE == "2026-01-02"
    assert benchmark_ytd.SPY_SYMBOL == "SPY"
    assert benchmark_ytd.USDKRW_SYMBOL == "KRW=X"
