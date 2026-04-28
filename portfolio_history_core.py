"""포트폴리오 히스토리 재계산 코어.

Yahoo Finance v8 chart API 직접 호출 + 배당 TTM 일별 합산 + me/wife 공통 스냅샷 빌더.
rebuild_portfolio_history.py / rebuild_trend_data.py / rebuild_wife_history.py 모두
이 모듈로 위임한다 (DRY, 단일 진실의 원천).

설계: docs/superpowers/plans/2026-04-28-portfolio-history-rebuild.md
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import pandas as pd
import requests

START_DATE = "2026-01-02"
TICKER_DELAY = 0.7  # rate limit 회피
MAX_RETRIES = 3
MACRO_SYMBOLS = {
    "VIX": "^VIX",
    "yield_30Y": "^TYX",
    "USD_KRW": "USDKRW=X",
}
