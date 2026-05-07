# portfolio_stop_history.py
"""
Portfolio Stop Signal -- Position state I/O + lifecycle.

책임:
1. portfolio_stops.json load/save (positions + snapshots 분리)
2. 첫 실행 bootstrap -- yfinance YTD high fetch
3. 일상 incremental update (highest_close 안전 갱신)
4. Lifecycle 관리 (신규 등장 / 매도 감지 grace / 재매수)

Market data vs Position state 분리 원칙:
- ATR 등 시장 데이터는 fetch_market_data.py
- highest_close 등 포지션 state는 이 모듈
"""

import os
import json
from datetime import date, datetime, timedelta

from portfolio_stop_config import (
    VERSION, ANCHOR_DATE, MAX_DAILY_JUMP_PCT,
    ARCHIVE_AFTER_DAYS_MISSING, MAX_SNAPSHOT_DAYS,
)


# --- JSON I/O ----------------------------------------------------------

def new_empty_state(owner: str) -> dict:
    """비어 있는 portfolio_stops 구조."""
    return {
        "_meta": {
            "schema_version": 1,
            "version": VERSION,
            "owner": owner,
            "anchor_date": ANCHOR_DATE,
            "last_updated": None,
        },
        "positions": {},
        "snapshots": {},
    }


def load_stop_history(path: str, owner: str = "me") -> dict:
    """파일이 없으면 빈 state, 있으면 로드."""
    if not os.path.exists(path):
        return new_empty_state(owner)
    try:
        with open(path, "rb") as f:
            raw = f.read()
        return json.loads(raw.rstrip(b" \t\n\r\x00").decode("utf-8"))
    except Exception as e:
        print(f"[stop_history] WARN load failed ({e}) -- using empty state")
        return new_empty_state(owner)


def save_stop_history(state: dict, path: str) -> None:
    """원자적 저장 (임시 파일 -> rename)."""
    state["_meta"]["last_updated"] = date.today().strftime("%Y-%m-%d")
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def get_position(state: dict, ticker: str) -> dict | None:
    return state.get("positions", {}).get(ticker)


# --- Highest close 안전 갱신 ------------------------------------------

def update_highest_close_safe(pos: dict, today_close: float,
                              prev_close: float | None,
                              today_str: str) -> bool:
    """비정상 점프(분할/bad tick) 방어. 갱신 시 True 반환."""
    if today_close is None or today_close <= 0:
        return False
    # Guard: 단일일 +40% 초과 -> 의심
    if prev_close and prev_close > 0:
        jump_ratio = today_close / prev_close
        if jump_ratio > (1.0 + MAX_DAILY_JUMP_PCT):
            print(
                f"[stop_history] WARN {pos.get('ticker', '?')}: "
                f"suspicious jump prev={prev_close:.4f} -> today={today_close:.4f} "
                f"({(jump_ratio - 1) * 100:.1f}%/1d) -- skip highest update"
            )
            return False
    if today_close > pos.get("highest_close", 0):
        pos["highest_close"] = today_close
        pos["highest_close_date"] = today_str
        return True
    return False


# --- Lifecycle (신규/유지/누락/매도/재매수) ------------------------------

def _days_diff(d1: str, d2: str) -> int:
    """d1 - d2 (calendar days)."""
    a = datetime.strptime(d1, "%Y-%m-%d").date()
    b = datetime.strptime(d2, "%Y-%m-%d").date()
    return (a - b).days


def evaluate_lifecycle(state: dict, portfolio_tickers: set,
                       today_str: str,
                       new_position_seed: dict | None = None) -> None:
    """매일 실행: positions 키와 portfolio_tickers를 비교해 라이프사이클 진행.

    - portfolio에 있으나 stops에 없음 -> 신규 등록 (today anchor)
    - portfolio에 있으나 stops엔 closed -> 재매수 (fresh bootstrap, today anchor)
    - portfolio에 있고 stops에 active -> missing_since 리셋
    - portfolio에 없으나 stops엔 active -> missing_since++; 3일 grace 후 closed
    - 이미 closed -> 그대로

    new_position_seed: {ticker: {"close": float, "shares": float, "mode": str}}
        신규/재매수 시 시작값. mode는 호출자가 미리 결정 (config.get_stop_mode 활용).
    """
    new_position_seed = new_position_seed or {}
    positions = state.setdefault("positions", {})

    # 1. portfolio 종목 처리
    for tk in portfolio_tickers:
        pos = positions.get(tk)
        seed = new_position_seed.get(tk, {})
        if pos is None:
            # 첫 등장 -- 신규 종목
            positions[tk] = {
                "status": "active",
                "mode": seed.get("mode", "MOMENTUM"),
                "entry_date": today_str,
                "highest_close": float(seed.get("close", 0.0)),
                "highest_close_date": today_str,
                "current_stop": None,
                "below_stop_count": 0,
                "shares": float(seed.get("shares", 0.0)),
                "last_size_change": today_str,
                "missing_since": None,
                "last_signal": None,
                "last_action": None,
                "last_evaluated": None,
            }
            continue
        if pos.get("status") == "closed":
            # 재매수 -- fresh bootstrap
            pos["status"] = "active"
            pos["entry_date"] = today_str
            pos["highest_close"] = float(seed.get("close", pos.get("highest_close", 0.0)))
            pos["highest_close_date"] = today_str
            pos["current_stop"] = None
            pos["below_stop_count"] = 0
            pos["shares"] = float(seed.get("shares", 0.0))
            pos["last_size_change"] = today_str
            pos["missing_since"] = None
            pos["reopened_date"] = today_str
            pos.pop("closed_date", None)
            continue
        # 정상 active -- missing 카운터 리셋
        pos["missing_since"] = None

    # 2. portfolio에 없는 active 종목 -> missing/archive 진행
    for tk, pos in list(positions.items()):
        if tk in portfolio_tickers:
            continue
        if pos.get("status") == "closed":
            continue
        if pos.get("missing_since") is None:
            pos["missing_since"] = today_str
        days_missing = _days_diff(today_str, pos["missing_since"])
        # missing_since is the FIRST absent day; days_missing=2 means 3 calendar days absent
        # (ARCHIVE_AFTER_DAYS_MISSING=3 means archive after 3rd absent day → days_diff >= 2)
        if days_missing >= ARCHIVE_AFTER_DAYS_MISSING - 1:
            pos["status"] = "closed"
            pos["closed_date"] = today_str
            # signal_history 대신 snapshots에 archive 이벤트 기록
            snapshots = state.setdefault("snapshots", {})
            day = snapshots.setdefault(today_str, {})
            day[tk] = {
                "signal": "CLOSED",
                "event": "removed_from_portfolio",
                "missing_since": pos["missing_since"],
            }


# --- Snapshot 누적 -------------------------------------------------------

def append_snapshot(state: dict, today_str: str, ticker: str, entry: dict) -> None:
    snapshots = state.setdefault("snapshots", {})
    day = snapshots.setdefault(today_str, {})
    day[ticker] = entry


def prune_old_snapshots(state: dict, today_str: str) -> int:
    """MAX_SNAPSHOT_DAYS 이전 스냅샷 제거. 제거 개수 반환."""
    snapshots = state.get("snapshots", {})
    if not snapshots:
        return 0
    cutoff = (datetime.strptime(today_str, "%Y-%m-%d").date()
              - timedelta(days=MAX_SNAPSHOT_DAYS))
    removed = 0
    for d in list(snapshots.keys()):
        try:
            if datetime.strptime(d, "%Y-%m-%d").date() < cutoff:
                snapshots.pop(d, None)
                removed += 1
        except ValueError:
            continue
    return removed


# --- Bootstrap (yfinance YTD fetch) -------------------------------------

def bootstrap_first_run(tickers: list, anchor_date: str = ANCHOR_DATE,
                        today_str: str | None = None) -> dict:
    """첫 실행 시 yfinance에서 anchor_date~today close 가져와 max 계산.

    반환: {ticker: {"highest_close": float, "highest_close_date": "YYYY-MM-DD"}}
    실패한 ticker는 dict에서 제외 -- 호출자가 fallback 처리 (today_close 사용).
    """
    import yfinance as yf
    import pandas as pd

    if today_str is None:
        today_str = date.today().strftime("%Y-%m-%d")
    end_date = (datetime.strptime(today_str, "%Y-%m-%d").date()
                + timedelta(days=1)).strftime("%Y-%m-%d")

    # KR ticker는 .KS/.KQ suffix 필요
    from portfolio_data import is_korean_ticker, to_yfinance_symbol
    yf_tickers = [to_yfinance_symbol(t) if is_korean_ticker(t) else t
                  for t in tickers]
    rev_map = dict(zip(yf_tickers, tickers))

    print(f"[stop_history] Bootstrap: yfinance fetch {len(tickers)} tickers "
          f"({anchor_date} ~ {today_str})")
    out = {}
    try:
        df = yf.download(yf_tickers, start=anchor_date, end=end_date,
                         progress=False, group_by="ticker", auto_adjust=False,
                         threads=True)
    except Exception as e:
        print(f"[stop_history] WARN bulk download failed: {e}")
        return out

    for yf_t, orig_t in rev_map.items():
        try:
            if isinstance(df.columns, pd.MultiIndex):
                close = df[yf_t]["Close"].dropna()
            else:
                close = df["Close"].dropna()
            if len(close) == 0:
                continue
            max_idx = close.idxmax()
            out[orig_t] = {
                "highest_close": float(close.loc[max_idx]),
                "highest_close_date": max_idx.strftime("%Y-%m-%d"),
            }
        except Exception as e:
            print(f"[stop_history] WARN bootstrap {orig_t}: {e}")
            continue
    print(f"[stop_history] Bootstrap done: {len(out)}/{len(tickers)} tickers ok")
    return out
