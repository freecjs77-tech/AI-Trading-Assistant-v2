"""
Market Momentum Scanner — Data access layer.

책임:
  1. yfinance bulk fetch (Task 4-7에서 추가)
  2. iShares CSV / KRX API 호출 (Task 4-5)
  3. 캐시 I/O 공통 (load/save/age + fallback helper) ← Task 2

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
import os, json, sys, io, csv, re, requests
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
# iShares CSV 파싱 (Task 4)
# ───────────────────────────────────────────────────────────────────────────────

IWB_URL = (
    "https://www.ishares.com/us/products/239707/ishares-russell-1000-etf/"
    "1467271812596.ajax?fileType=csv&fileName=IWB_holdings&dataType=fund"
)

# iShares CSV는 종종 컬럼명이 변경됨 — fallback 후보
ISHARES_TICKER_COLS = ["Ticker", "Ticker Symbol", "Issuer Ticker"]


def normalize_symbol(symbol: str) -> str | None:
    """
    iShares 심볼을 yfinance 호환 형식으로 정규화.

    Examples:
      'BRK.B' -> 'BRK-B'
      'AAPL'  -> 'AAPL'
      '-' / '' / '   ' -> None  (cash, 빈줄)
    """
    if not symbol:
        return None
    s = symbol.strip().upper()
    if not s or s == "-" or not re.match(r"^[A-Z0-9.\-]+$", s):
        return None
    return s.replace(".", "-")


def parse_ishares_csv(csv_bytes: bytes) -> list[str]:
    """
    iShares CSV 바이트 → 정규화된 ticker 리스트.

    CSV 헤더 행이 첫 줄이 아닐 수 있어 (앞에 메타 행들), 알려진 ticker 컬럼명을
    찾을 때까지 한 줄씩 스킵.
    """
    text = csv_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines()
    header_idx = -1
    for i, line in enumerate(lines):
        cols = next(csv.reader([line]), [])
        if any(c.strip() in ISHARES_TICKER_COLS for c in cols):
            header_idx = i
            break
    if header_idx < 0:
        raise ValueError(
            f"No known ticker column ({ISHARES_TICKER_COLS}) in CSV. "
            f"First 5 lines: {lines[:5]}"
        )
    reader = csv.DictReader(lines[header_idx:])
    ticker_col = next((c for c in ISHARES_TICKER_COLS if c in reader.fieldnames), None)
    tickers = []
    for row in reader:
        sym = normalize_symbol(row.get(ticker_col, ""))
        if sym:
            tickers.append(sym)
    return tickers


def fetch_iwb_holdings() -> list[str]:
    """IWB Russell 1000 ETF holdings CSV 다운로드 + 정규화."""
    resp = requests.get(IWB_URL, timeout=30,
                        headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return parse_ishares_csv(resp.content)


def get_iwb_holdings(force_refresh: bool = False) -> list[str]:
    """캐시 + fallback. TTL 7일."""
    from momentum_config import CACHE_TTL_DAYS
    name = "iwb_holdings"
    if not force_refresh and cache_age_days(name) < CACHE_TTL_DAYS:
        cache = load_cache(name)
        if cache and cache.get("fetch_status") in ("ok", "stale_fallback"):
            return cache["data"]
    return fetch_with_fallback(name, fetch_iwb_holdings, source="ishares")


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
        out.append(f"{code}.KS")
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
