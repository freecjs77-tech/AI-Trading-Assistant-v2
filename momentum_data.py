"""
Market Momentum Scanner — Data access layer.

책임:
  1. yfinance bulk fetch (Task 4-7에서 추가)
  2. iShares CSV / KRX API 호출 (Task 4-5)
  3. 캐시 I/O 공통 (load/save/age + fallback helper) ← Task 2
  4. EMA 필드 계산 공통 헬퍼 (compute_ema_fields — EMA9/21/65 + dist + slope)

캐시 메타 스키마:
  {
    "last_updated": "2026-05-06T13:42:11+09:00",
    "source": "ishares" | "krx" | "yfinance" | "test",
    "fetch_status": "ok" | "stale_fallback" | "failed",
    "fallback_count": int,
    "row_count": int,
    "data": [...]
  }
"""
import os, json, sys, io, requests
from datetime import datetime, timezone, timedelta

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 모듈 레벨 데이터 디렉토리 — 테스트에서 set_data_dir로 override 가능
_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def set_data_dir(path: str):
    """테스트용 — 데이터 디렉토리 override."""
    global _DATA_DIR
    _DATA_DIR = path
    os.makedirs(_DATA_DIR, exist_ok=True)


def get_data_dir() -> str:
    os.makedirs(_DATA_DIR, exist_ok=True)
    return _DATA_DIR


def _cache_path(name: str) -> str:
    safe = name.replace("/", "_").replace("\\", "_")
    return os.path.join(get_data_dir(), f"{safe}.json")


def load_cache(name: str) -> dict | None:
    """캐시 파일 로드. 없거나 손상되면 None."""
    path = _cache_path(name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            raw = f.read().rstrip(b" \t\n\r\x00").decode("utf-8")
        return json.loads(raw)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[momentum_data] WARN: corrupt cache {name}: {e}")
        return None


def save_cache(
    name: str,
    data: list | dict,
    source: str = "yfinance",
    status: str = "ok",
    fallback_count: int = 0,
):
    """캐시 파일 저장 (메타 포함)."""
    payload = {
        "last_updated": datetime.now(timezone(timedelta(hours=9))).isoformat(),
        "source": source,
        "fetch_status": status,
        "fallback_count": fallback_count,
        "row_count": len(data) if hasattr(data, "__len__") else 0,
        "data": data,
    }
    path = _cache_path(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def cache_age_days(name: str) -> float:
    """캐시 last_updated와 현재 시각의 차이(일). 없으면 inf."""
    cache = load_cache(name)
    if not cache or "last_updated" not in cache:
        return float("inf")
    try:
        ts = datetime.fromisoformat(cache["last_updated"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone(timedelta(hours=9)))
        delta = datetime.now(timezone.utc) - ts.astimezone(timezone.utc)
        return delta.total_seconds() / 86400.0
    except (ValueError, TypeError) as e:
        print(f"[momentum_data] WARN: cannot parse last_updated for {name}: {e}")
        return float("inf")


def fetch_with_fallback(name: str, fetch_fn, source: str = "yfinance"):
    """
    fetch_fn() 시도 → 성공 시 save_cache(status='ok', fallback_count=0).
    실패 시 직전 캐시 fallback (있으면), fallback_count += 1, status='stale_fallback'.
    캐시도 없으면 raise.

    fallback_count >= 3 → critical 로그 (운영자 조사 필요).
    """
    try:
        data = fetch_fn()
        save_cache(name, data, source=source, status="ok", fallback_count=0)
        return data
    except Exception as e:
        cache = load_cache(name)
        if cache and "data" in cache:
            new_count = cache.get("fallback_count", 0) + 1
            print(f"[momentum_data] WARN: {name} fetch failed ({e}); "
                  f"using stale cache (fallback_count={new_count}, "
                  f"age={cache_age_days(name):.1f}d)")
            if new_count >= 3:
                print(f"[momentum_data] CRITICAL: {name} has {new_count} consecutive "
                      f"fallbacks — investigate data source")
            save_cache(name, cache["data"], source=cache.get("source", source),
                       status="stale_fallback", fallback_count=new_count)
            return cache["data"]
        raise


# ───────────────────────────────────────────────────────────────────────────────
# KRX ETF 구성종목 (Task 5)
# ───────────────────────────────────────────────────────────────────────────────

# KRX 정보데이터시스템 — ETF PDF (Portfolio Deposit File) 조회
KRX_ETF_HOLDINGS_URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
KRX_ETF_BLD = "dbms/MDC/STAT/standard/MDCSTAT05201"


def _krx_full_code(short_code: str) -> str:
    """6자리 → 12자리 KRX 풀코드 (KR7 + 6자리 + 000)."""
    return f"KR7{short_code}000"


def fetch_krx_etf_holdings(etf_code: str) -> list[str]:
    """
    KRX 공개 API에서 ETF 구성종목(PDF) 조회.

    Args:
        etf_code: 6자리 KRX 단축코드 (예: '069500' = KODEX 200)

    Returns:
        yfinance 호환 ticker 리스트 (예: ['005930.KS', ...])
        빈 코드/형식 오류 종목은 스킵.
    """
    payload = {
        "bld": KRX_ETF_BLD,
        "locale": "ko_KR",
        "trdDd": datetime.now().strftime("%Y%m%d"),
        "isuCd": _krx_full_code(etf_code),
        "isuCd2": _krx_full_code(etf_code),
        "param1isuCd_finder_secuprodisu1_0": "ALL",
    }
    resp = requests.post(
        KRX_ETF_HOLDINGS_URL,
        data=payload,
        timeout=30,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://data.krx.co.kr/",
        },
    )
    resp.raise_for_status()
    rows = resp.json().get("output", [])
    out = []
    for row in rows:
        code = (row.get("ISU_SRT_CD") or "").strip()
        if not code or not code.isdigit() or len(code) != 6:
            continue
        from portfolio_data import to_yfinance_symbol
        out.append(to_yfinance_symbol(code))
    return out


def get_krx_etf_holdings(etf_code: str, force_refresh: bool = False) -> list[str]:
    """캐시 + fallback. TTL 7일."""
    from momentum_config import CACHE_TTL_DAYS
    name = f"krx_etf_{etf_code}_holdings"
    if not force_refresh and cache_age_days(name) < CACHE_TTL_DAYS:
        cache = load_cache(name)
        if cache and cache.get("fetch_status") in ("ok", "stale_fallback"):
            return cache["data"]
    return fetch_with_fallback(
        name, lambda: fetch_krx_etf_holdings(etf_code), source="krx"
    )


# ───────────────────────────────────────────────────────────────────────────────
# Sector ETF Mapping (Task 6)
# ───────────────────────────────────────────────────────────────────────────────

def build_sector_mapping(holdings_by_etf: dict[str, list[str]],
                         market: str = "us") -> dict[str, str]:
    """
    {etf_ticker: [stock_tickers]} → {stock_ticker: etf_ticker}.

    한 종목이 여러 ETF에 포함되면 dict에 먼저 등장한 etf_ticker가 우선
    (caller가 우선순위 ETF를 먼저 입력하도록 책임).
    """
    mapping: dict[str, str] = {}
    for etf, tickers in holdings_by_etf.items():
        for t in tickers:
            if t not in mapping:
                mapping[t] = etf
    return mapping


def get_us_sector_holdings(force_refresh: bool = False) -> dict[str, list[str]]:
    """US 섹터 ETF holdings 일괄 fetch + 캐시.

    yfinance Ticker.get_funds_data().top_holdings를 사용 (top 50 개씩).
    실패한 ETF는 빈 리스트.
    """
    from momentum_config import US_SECTOR_ETFS, CACHE_TTL_DAYS
    name = "sector_etf_holdings_us"
    if not force_refresh and cache_age_days(name) < CACHE_TTL_DAYS:
        cache = load_cache(name)
        if cache and cache.get("fetch_status") in ("ok", "stale_fallback"):
            return cache["data"]
    out: dict[str, list[str]] = {}
    for etf in US_SECTOR_ETFS:
        try:
            import yfinance as yf
            t = yf.Ticker(etf)
            holdings = t.get_funds_data().top_holdings
            if holdings is not None and len(holdings) > 0:
                out[etf] = holdings.index.tolist()[:50]
            else:
                out[etf] = []
        except Exception as e:
            print(f"[momentum_data] WARN {etf} holdings: {e}")
            out[etf] = []
    save_cache(name, out, source="yfinance", status="ok")
    return out


def get_kr_sector_holdings(force_refresh: bool = False) -> dict[str, list[str]]:
    """KR 섹터 ETF holdings — KRX API 호출 (KODEX 시리즈)."""
    from momentum_config import KR_SECTOR_ETFS, CACHE_TTL_DAYS
    name = "sector_etf_holdings_kr"
    if not force_refresh and cache_age_days(name) < CACHE_TTL_DAYS:
        cache = load_cache(name)
        if cache and cache.get("fetch_status") in ("ok", "stale_fallback"):
            return cache["data"]
    out: dict[str, list[str]] = {}
    for etf in KR_SECTOR_ETFS:
        code = etf.replace(".KS", "")
        try:
            out[etf] = fetch_krx_etf_holdings(code)
        except Exception as e:
            print(f"[momentum_data] WARN {etf} KRX holdings: {e}")
            out[etf] = []
    save_cache(name, out, source="krx", status="ok")
    return out


# ───────────────────────────────────────────────────────────────────────────────
# Daily Movers + Weekly Top100 (Task 7-8)
# ───────────────────────────────────────────────────────────────────────────────

def compute_daily_movers(closes) -> list[str]:
    """
    종가 DataFrame (columns=tickers, index=dates) → Daily Movers 통과 ticker.

    조건: (1d ≥ +5% OR 3d ≥ +8%) AND close > MA20
    """
    import pandas as pd
    from momentum_config import DAILY_MOVER_1D_PCT, DAILY_MOVER_3D_PCT
    movers: list[str] = []
    for t in closes.columns:
        s = closes[t].dropna()
        if len(s) < 21:
            continue
        last = float(s.iloc[-1])
        prev = float(s.iloc[-2])
        prev3 = float(s.iloc[-4]) if len(s) >= 4 else None
        ma20 = float(s.iloc[-20:].mean())
        if last <= ma20:
            continue
        if prev > 0:
            r1d = (last / prev - 1) * 100
            if r1d >= DAILY_MOVER_1D_PCT:
                movers.append(t)
                continue
        if prev3 and prev3 > 0:
            r3d = (last / prev3 - 1) * 100
            if r3d >= DAILY_MOVER_3D_PCT:
                movers.append(t)
    return movers


def compute_weekly_top100(closes, volumes, n: int = 100) -> list[str]:
    """
    종가 + 거래량 DF → 5일 평균 dollar_volume 상위 N개 ticker.
    dollar_volume = close * volume.
    """
    import pandas as pd
    common = closes.columns.intersection(volumes.columns)
    if len(common) == 0:
        return []
    dv = closes[common].tail(5) * volumes[common].tail(5)
    avg = dv.mean(axis=0).sort_values(ascending=False)
    return avg.head(n).index.tolist()


def fetch_yf_bulk(tickers: list[str], period: str = "30d") -> tuple:
    """
    yfinance bulk download. 너무 많은 ticker는 청크 분할.

    Returns:
        (closes_df, volumes_df) — 각각 DataFrame(columns=tickers, index=dates)
    """
    import yfinance as yf
    import pandas as pd
    if not tickers:
        return pd.DataFrame(), pd.DataFrame()
    chunk_size = 200
    all_close, all_vol = [], []
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        try:
            df = yf.download(chunk, period=period, progress=False,
                             auto_adjust=False, group_by="column", threads=True)
            if df is None or df.empty:
                continue
            close_df = df["Close"] if "Close" in df.columns.get_level_values(0) else pd.DataFrame()
            vol_df = df["Volume"] if "Volume" in df.columns.get_level_values(0) else pd.DataFrame()
            if isinstance(close_df, pd.Series):
                close_df = close_df.to_frame(chunk[0])
                vol_df = vol_df.to_frame(chunk[0])
            all_close.append(close_df)
            all_vol.append(vol_df)
        except Exception as e:
            print(f"[momentum_data] WARN bulk fetch chunk failed: {e}")
            continue
    if not all_close:
        return pd.DataFrame(), pd.DataFrame()
    return pd.concat(all_close, axis=1), pd.concat(all_vol, axis=1)


def compute_ema_fields(close: "pd.Series") -> dict:
    """
    Compute EMA9/21/65 + dist + slope fields from a close series.

    Single source of truth for EMA calculation. Called by both
    fetch_market_data.py (per-ticker) and momentum_scanner._fetch_indicators
    (in-memory bulk). momentum_signal.py must NOT compute EMAs.

    Returns dict with 7 keys; each value is float or None.
    """
    import pandas as pd

    out = {
        "ema9": None, "ema21": None, "ema65": None,
        "dist_ema9_pct": None, "dist_ema21_pct": None,
        "ema21_slope_3d_pct": None, "ema65_slope_5d_pct": None,
    }
    if close is None or len(close) == 0:
        return out
    s = close.dropna() if hasattr(close, "dropna") else pd.Series(close).dropna()
    if len(s) < 9:
        return out

    last = float(s.iloc[-1])

    def _last_or_none(series):
        try:
            v = float(series.iloc[-1])
            return v if v == v else None
        except (TypeError, ValueError, IndexError):
            return None

    def _slope_pct(series, lookback):
        if len(series) <= lookback:
            return None
        try:
            cur = float(series.iloc[-1])
            prev = float(series.iloc[-1 - lookback])
        except (TypeError, ValueError, IndexError):
            return None
        if cur != cur or prev != prev or prev == 0:
            return None
        return round((cur - prev) / prev * 100, 2)

    def _dist_pct(close_v, ema_v):
        if ema_v is None or ema_v == 0:
            return None
        return round((close_v - ema_v) / ema_v * 100, 2)

    # ema9 (always computed — len(s) >= 9 guaranteed by top guard)
    ema9 = s.ewm(span=9, adjust=False).mean()
    out["ema9"] = _last_or_none(ema9)
    out["dist_ema9_pct"] = _dist_pct(last, out["ema9"])

    if len(s) >= 21:
        ema21 = s.ewm(span=21, adjust=False).mean()
        out["ema21"] = _last_or_none(ema21)
        out["dist_ema21_pct"] = _dist_pct(last, out["ema21"])
        out["ema21_slope_3d_pct"] = _slope_pct(ema21, 3)

    if len(s) >= 65:
        ema65 = s.ewm(span=65, adjust=False).mean()
        out["ema65"] = _last_or_none(ema65)
        out["ema65_slope_5d_pct"] = _slope_pct(ema65, 5)

    return out
