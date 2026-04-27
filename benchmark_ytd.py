"""YTD benchmark vs S&P 500 (KRW) — constant-portfolio backtest anchored at 2026-01-02.

See docs/superpowers/specs/2026-04-27-ytd-benchmark-design.md for design.
"""
from __future__ import annotations

import json
import os
from typing import Iterable

ANCHOR_DATE = "2026-01-02"
SPY_SYMBOL = "SPY"
USDKRW_SYMBOL = "KRW=X"
