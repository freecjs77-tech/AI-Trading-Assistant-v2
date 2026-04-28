#!/usr/bin/env python3
"""rebuild_portfolio_history.py — me + wife portfolio_daily 재생성 (2026-01-02~).

사용:
  python rebuild_portfolio_history.py                         # me + wife 모두
  python rebuild_portfolio_history.py --owner me --dry-run    # me만 검증
  python rebuild_portfolio_history.py --start-date 2026-01-02 --end-date 2026-04-28

원칙:
  - 현재 보유 동결 → 과거로 가격 replay
  - 배당은 TTM (compute_ttm_dividend), 하드코딩 없음
  - 기존 파일은 *.bak.<today>-rebuild로 백업 후 덮어쓰기
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))

import pandas as pd

import portfolio_history_core as core
from portfolio_data import is_kospi_ticker, to_yfinance_symbol
from portfolio_paths import primary_portfolio_path

# regenerate_history.py calls argparse.parse_args() at module level.
# Guard against it consuming our sys.argv by temporarily replacing argv.
_saved_argv = sys.argv[:]
sys.argv = [sys.argv[0]]
from regenerate_history import parse_portfolio_holdings
sys.argv = _saved_argv

from rebuild_wife_history import HOLDINGS as WIFE_HOLDINGS, USD_TICKERS as WIFE_USD_TICKERS

ME_DAILY = PROJECT_DIR / "history" / "portfolio_daily.json"
WIFE_DAILY = PROJECT_DIR / "history" / "portfolio_daily_wife.json"


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d")
    bak = path.with_suffix(path.suffix + f".bak.{stamp}-rebuild")
    shutil.copy2(path, bak)
    return bak


def _collect_symbols(me_holdings, wife_holdings) -> tuple[list[str], dict[str, str]]:
    """me + wife + 매크로 + SPY 심볼 집합."""
    yf_map: dict[str, str] = {}
    for p in me_holdings:
        yf_map[p["ticker"]] = to_yfinance_symbol(p["ticker"])
    for t, _, _ in wife_holdings:
        yf_map.setdefault(t, to_yfinance_symbol(t))

    syms = set(yf_map.values())
    syms.update(core.MACRO_SYMBOLS.values())
    syms.add("SPY")
    syms.add("QQQ")
    yf_map.setdefault("SPY", "SPY")
    yf_map.setdefault("QQQ", "QQQ")
    return sorted(syms), yf_map


def _div_tickers(me_holdings, wife_holdings) -> list[str]:
    s = {p["ticker"] for p in me_holdings}
    s.update(t for t, _, _ in wife_holdings)
    return sorted(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", choices=["me", "wife", "both"], default="both")
    ap.add_argument("--start-date", default=core.START_DATE)
    ap.add_argument("--end-date", default=None, help="기본: SPY 마지막 인덱스")
    ap.add_argument("--dry-run", action="store_true", help="저장 없이 결과만 출력")
    args = ap.parse_args()

    print(f"\n{'='*64}")
    print(f"  Portfolio history rebuild (start={args.start_date}, owner={args.owner})")
    print(f"{'='*64}")

    me_path = primary_portfolio_path(str(PROJECT_DIR))
    me_holdings = parse_portfolio_holdings(me_path)
    print(f"  me holdings: {len(me_holdings)} (from {me_path})")
    print(f"  wife holdings: {len(WIFE_HOLDINGS)} (from rebuild_wife_history.HOLDINGS)")

    syms, yf_map = _collect_symbols(me_holdings, WIFE_HOLDINGS)
    print(f"  unique symbols: {len(syms)}")

    print(f"\n  -- 1) Yahoo v8 chart 다운로드 --")
    dfs = core.download_all(syms, range_str="1y")
    if "SPY" not in dfs:
        print("  ERROR: SPY 데이터 없음 — 거래일 판별 불가")
        sys.exit(1)

    trading = core.trading_dates_from(dfs["SPY"], args.start_date)
    if args.end_date:
        trading = trading[trading <= pd.Timestamp(args.end_date)]
    if len(trading) == 0:
        print(f"  ERROR: 거래일 0일 (start={args.start_date})")
        sys.exit(1)
    print(f"  거래일 {len(trading)}일: {trading[0].date()} ~ {trading[-1].date()}")

    print(f"\n  -- 2) 배당 히스토리 다운로드 --")
    div_tickers = _div_tickers(me_holdings, WIFE_HOLDINGS)
    divs_map = core.fetch_all_dividends(div_tickers)

    me_daily: dict[str, dict] = {}
    wife_daily: dict[str, dict] = {}

    print(f"\n  -- 3) 일별 스냅샷 생성 --")
    for ts in trading:
        ds = ts.strftime("%Y-%m-%d")
        if args.owner in ("me", "both"):
            snap = core.build_me_snapshot(ts, me_holdings, yf_map, dfs, divs_map)
            if snap is not None:
                me_daily[ds] = snap
        if args.owner in ("wife", "both"):
            snap_w = core.build_wife_snapshot(
                ts, WIFE_HOLDINGS, WIFE_USD_TICKERS, yf_map, dfs, divs_map
            )
            if snap_w is not None:
                wife_daily[ds] = snap_w

    # 출력 요약
    if me_daily:
        first, last = min(me_daily), max(me_daily)
        print(f"  me  : {len(me_daily)}일 ({first} ~ {last}) "
              f"first total {me_daily[first]['total_value_krw']:,} -> "
              f"last {me_daily[last]['total_value_krw']:,}")
    elif args.owner in ("me", "both"):
        print(f"  me  : WARN — 0 snapshots built (요청됐으나 모두 None)")
    if wife_daily:
        first, last = min(wife_daily), max(wife_daily)
        print(f"  wife: {len(wife_daily)}일 ({first} ~ {last}) "
              f"first total {wife_daily[first]['total_value_krw']:,} -> "
              f"last {wife_daily[last]['total_value_krw']:,}")
    elif args.owner in ("wife", "both"):
        print(f"  wife: WARN — 0 snapshots built (요청됐으나 모두 None)")

    if args.dry_run:
        print("\n  [DRY-RUN] 저장 생략")
        return

    print(f"\n  -- 4) 백업 + 저장 --")
    if args.owner in ("me", "both") and me_daily:
        bak = _backup(ME_DAILY)
        if bak:
            print(f"  backup: {bak}")
        with open(ME_DAILY, "w", encoding="utf-8") as f:
            json.dump(me_daily, f, ensure_ascii=False, indent=2)
        print(f"  saved : {ME_DAILY} ({len(me_daily)}일)")
    if args.owner in ("wife", "both") and wife_daily:
        bak = _backup(WIFE_DAILY)
        if bak:
            print(f"  backup: {bak}")
        with open(WIFE_DAILY, "w", encoding="utf-8") as f:
            json.dump(wife_daily, f, ensure_ascii=False, indent=2)
        print(f"  saved : {WIFE_DAILY} ({len(wife_daily)}일)")

    print(f"\n{'='*64}\n  완료\n{'='*64}\n")


if __name__ == "__main__":
    main()
