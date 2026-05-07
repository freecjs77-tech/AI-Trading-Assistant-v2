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
import os, json, sys
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
