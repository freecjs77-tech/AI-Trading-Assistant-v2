"""portfolio_history_core 단위 테스트."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import portfolio_history_core as core


def test_constants():
    assert core.START_DATE == "2026-01-02"
    assert core.MACRO_SYMBOLS["USD_KRW"] == "USDKRW=X"
    assert core.MAX_RETRIES == 3
