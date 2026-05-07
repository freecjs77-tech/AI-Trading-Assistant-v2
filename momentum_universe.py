"""
Market Momentum Scanner — Universe 조립.

US: IWB ∪ weekly_top100 ∪ daily_movers (≤ 1500 cap)
KR: KODEX 200 ∪ KOSDAQ 150 ∪ sector_ETF_holdings ∪ weekly_top100 ∪ daily_movers
    (잡주 필터: KR은 거래대금 5일평균 ≥ 100억원만)
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
    """
    if not tickers:
        return []
    closes, volumes = md.fetch_yf_bulk(tickers, period="30d")
    if closes.empty:
        return []
    movers = md.compute_daily_movers(closes)
    if market == "kr" and not volumes.empty:
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
    US_BASE = IWB
    US_WEEKLY = IWB 거래대금 5일 평균 Top100
    US_DAILY  = IWB 중 (1d ≥ +5% OR 3d ≥ +8%) AND close > MA20
    Return: 합집합 (≤ 1500 cap)
    """
    iwb = md.get_iwb_holdings()
    weekly = get_weekly_top_liquidity("weekly_liquidity_us", iwb, market="us")
    daily = fetch_daily_movers_for(iwb, market="us")
    uni = _dedup_preserve_order(list(iwb) + list(weekly) + list(daily))
    if len(uni) > UNIVERSE_CAP:
        print(f"[universe] WARN US universe {len(uni)} > cap {UNIVERSE_CAP} — truncating")
        uni = uni[:UNIVERSE_CAP]
    return uni


def build_kr_universe() -> list[str]:
    """KR_BASE = KODEX 200 ∪ KOSDAQ 150
    KR_SECTOR_ETF holdings (universe + 매핑 둘 다)
    KR_WEEKLY = KR_BASE 거래대금 5일 평균 Top100
    KR_DAILY  = KR_BASE 중 daily movers (잡주 필터 적용)
    Return: 합집합 (≤ 1500 cap)
    """
    kodex200 = md.get_krx_etf_holdings("069500")
    kosdaq150 = md.get_krx_etf_holdings("229200")
    base = _dedup_preserve_order(list(kodex200) + list(kosdaq150))

    sector_holdings = md.load_cache("sector_etf_holdings_kr")
    sector_tickers: list[str] = []
    if sector_holdings and isinstance(sector_holdings.get("data"), dict):
        for arr in sector_holdings["data"].values():
            sector_tickers.extend(arr or [])

    weekly = get_weekly_top_liquidity("weekly_liquidity_kr", base, market="kr")
    daily = fetch_daily_movers_for(base, market="kr")
    uni = _dedup_preserve_order(base + sector_tickers + list(weekly) + list(daily))
    if len(uni) > UNIVERSE_CAP:
        print(f"[universe] WARN KR universe {len(uni)} > cap {UNIVERSE_CAP} — truncating")
        uni = uni[:UNIVERSE_CAP]
    return uni
