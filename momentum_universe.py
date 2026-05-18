"""
Market Momentum Scanner — Universe 조립.

US: SP100∪NDX100 ∪ weekly_top100 ∪ daily_movers (≤ 1500 cap)
    Source: market_scanner.SP100_TICKERS (169 ticker, S&P 100 ∪ NASDAQ 100).
    이전 design (IWB Russell 1000)은 BlackRock anti-bot 차단 + universe
    과대로 인한 처리 시간 문제로 2026-05-18 폐기.
KR: KOSPI_TICKERS (market_scanner 101-ticker curated list)
    ∪ weekly_top100 ∪ daily_movers (잡주 필터: 거래대금 5일평균 ≥ 100억원만)
    Note: KRX public API requires auth since 2025 — using static list instead.
"""
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import momentum_data as md
import momentum_config as cfg


UNIVERSE_CAP = 1500   # V1.0 안전장치 — yfinance rate limit


def _dedup_preserve_order(seq):
    seen, out = set(), []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def fetch_daily_movers_for(tickers: list[str], market: str = "us") -> list[str]:
    """
    주어진 ticker 리스트 대상으로 yfinance bulk fetch → daily movers 계산.
    KR은 거래대금 ≥ 100억원 필터 추가.
    If KR market and volumes are empty, return [] (conservative — no movers if data unreliable).
    """
    if not tickers:
        return []
    closes, volumes = md.fetch_yf_bulk(tickers, period="30d")
    if closes.empty:
        return []
    movers = md.compute_daily_movers(closes)
    if market == "kr":
        if volumes.empty:
            print(f"[universe] WARN KR movers: no volume data — dropping all "
                  f"({len(movers)} movers) to prevent penny-stock leakage")
            return []
        common = closes.columns.intersection(volumes.columns)
        dv = (closes[common].tail(5) * volumes[common].tail(5)).mean(axis=0)
        liquid = set(dv[dv >= cfg.KR_LIQUIDITY_MIN_KRW].index)
        movers = [t for t in movers if t in liquid]
    return movers


def get_weekly_top_liquidity(name: str, base: list[str], market: str = "us") -> list[str]:
    """캐시 우선 — 없거나 stale 이면 base에 대해 bulk fetch → top100 계산."""
    if md.cache_age_days(name) < cfg.CACHE_TTL_DAYS:
        cache = md.load_cache(name)
        if cache and cache.get("fetch_status") in ("ok", "stale_fallback"):
            return cache["data"]
    if not base:
        md.save_cache(name, [], source="yfinance", status="ok")
        return []
    closes, volumes = md.fetch_yf_bulk(base, period="14d")
    top = md.compute_weekly_top100(closes, volumes, n=100)
    md.save_cache(name, top, source="yfinance", status="ok")
    return top


def build_us_universe() -> list[str]:
    """
    US_BASE = SP100∪NDX100 (market_scanner.SP100_TICKERS, 169 ticker)
    US_WEEKLY = base 거래대금 5일 평균 Top100
    US_DAILY  = base 중 (1d ≥ +5% OR 3d ≥ +8%) AND close > MA20
    Return: 합집합 (≤ 1500 cap — 169 base에서는 사실상 cap 미적용)

    Note: 2026-05-18 이전에는 IWB Russell 1000 holdings (~1007 ticker)을
    base로 사용했으나, (a) BlackRock CSV endpoint의 anti-bot 차단, (b) ~1000
    ticker × yfinance 90d bulk fetch의 처리 시간 문제로 SP100∪NDX100 base로
    교체. EM tier의 mid-cap structural inflection 노출은 design tradeoff로
    수용 (Russell 1000 600~1000위 mid-cap 노출 손실).
    """
    try:
        from market_scanner import SP100_TICKERS
    except ImportError:
        print("[universe] WARN market_scanner.SP100_TICKERS unavailable")
        return []
    base = list(SP100_TICKERS)

    weekly = get_weekly_top_liquidity("weekly_liquidity_us", base, market="us")
    daily = fetch_daily_movers_for(base, market="us")
    uni = _dedup_preserve_order(base + list(weekly) + list(daily))
    if len(uni) > UNIVERSE_CAP:
        print(f"[universe] WARN US universe {len(uni)} > cap {UNIVERSE_CAP} — truncating")
        uni = uni[:UNIVERSE_CAP]
    return uni


def build_kr_universe() -> list[str]:
    """KR universe = KOSPI_TICKERS (curated KOSPI/KOSDAQ list from market_scanner)
    + daily movers within that base, capped at UNIVERSE_CAP.

    Note: Previously used KRX API for KODEX 200 / KOSDAQ 150 holdings, but
    the public endpoint now requires authentication (returns "LOGOUT" 400).
    pykrx also requires KRX_ID/KRX_PW env vars.

    Design tradeoff: KR has no public sector ETF holdings API, so we skip the
    sector momentum gate entirely (handled in _scan_market for market=="KR").
    The flat KOSPI_TICKERS base is the same 101-ticker universe used by
    scan_kospi in market_scanner.py, which remains unchanged.
    """
    try:
        from market_scanner import KOSPI_TICKERS
    except ImportError:
        print("[universe] WARN market_scanner.KOSPI_TICKERS unavailable")
        return []
    base = list(KOSPI_TICKERS)

    weekly = get_weekly_top_liquidity("weekly_liquidity_kr", base, market="kr")
    daily = fetch_daily_movers_for(base, market="kr")
    uni = _dedup_preserve_order(base + list(weekly) + list(daily))
    if len(uni) > UNIVERSE_CAP:
        print(f"[universe] WARN KR universe {len(uni)} > cap {UNIVERSE_CAP} — truncating")
        uni = uni[:UNIVERSE_CAP]
    return uni
