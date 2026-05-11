"""Backfill ytd_pct/spy_ytd_pct/alpha_pp into historical portfolio_daily snapshots.

For visualization purposes — populates the YTD comparison chart with a meaningful
time series. Uses:
  - SPY YTD: exact (yfinance historical SPY closes × per-date USD/KRW from snapshots)
  - Portfolio YTD: approximation using current v0_krw as denominator
    (assumes today's portfolio composition since 2026-01-02; limitation noted)

This is a one-time script. Future pipeline runs save these fields automatically.
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

from benchmark_ytd import (
    ANCHOR_DATE, SPY_SYMBOL, DIT_TICKER, load_or_build_baseline,
    compute_v0_total_krw, fetch_close_on, compute_dit_rest_decomposition,
)
from portfolio_paths import discover_portfolios
from pipeline import _parse_portfolio_for_report
import yfinance as yf
from datetime import datetime, timedelta
import pandas as pd


def fetch_spy_history(start_date: str, end_date: str) -> dict:
    """Fetch SPY Adj Close prices for date range. Returns {date_str: close_usd}.

    yfinance 429 rate limit에 대해 exponential backoff retry (1s, 3s, 9s).
    모든 재시도 실패 시 빈 dict 반환 (caller가 graceful skip하도록).
    """
    import time
    end = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=2)).strftime("%Y-%m-%d")
    print(f"Fetching SPY history {start_date} → {end} ...")
    delays = [0, 1, 3, 9]
    last_exc = None
    for attempt, delay in enumerate(delays):
        if delay > 0:
            print(f"  ⏳ retry after {delay}s (attempt {attempt}/{len(delays)-1})")
            time.sleep(delay)
        try:
            t = yf.Ticker(SPY_SYMBOL)
            df = t.history(start=start_date, end=end, auto_adjust=False)
            if df is None or df.empty:
                return {}
            out = {}
            for idx, row in df.iterrows():
                date_str = idx.strftime("%Y-%m-%d")
                adj = row.get("Adj Close")
                if pd.notna(adj) and adj > 0:
                    out[date_str] = float(adj)
            return out
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            if "rate limit" in msg or "too many requests" in msg or "429" in msg:
                continue   # transient — retry
            if "no data" in msg or "delisted" in msg:
                return {}  # permanent — give up
            continue       # network/transient — retry
    print(f"  WARN SPY history fetch failed after {len(delays)} attempts: {last_exc}")
    return {}


def find_nearest_spy(spy_history: dict, target_date: str) -> float | None:
    """Find SPY close on target_date, or fall back to most recent prior trading day."""
    if target_date in spy_history:
        return spy_history[target_date]
    # walk back up to 7 days
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    for back in range(1, 8):
        d = (dt - timedelta(days=back)).strftime("%Y-%m-%d")
        if d in spy_history:
            return spy_history[d]
    return None


def fetch_dit_history(start_date: str, end_date: str) -> dict:
    """Fetch 110990.KQ Close prices for date range. Returns {date_str: close_krw}.

    Same retry pattern as fetch_spy_history. Returns empty dict on failure.
    """
    import time
    end = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=2)).strftime("%Y-%m-%d")
    print(f"Fetching 110990.KQ history {start_date} → {end} ...")
    delays = [0, 1, 3, 9]
    last_exc = None
    for attempt, delay in enumerate(delays):
        if delay > 0:
            print(f"  ⏳ retry after {delay}s (attempt {attempt}/{len(delays)-1})")
            time.sleep(delay)
        try:
            t = yf.Ticker("110990.KQ")
            df = t.history(start=start_date, end=end, auto_adjust=False)
            if df is None or df.empty:
                return {}
            out = {}
            for idx, row in df.iterrows():
                date_str = idx.strftime("%Y-%m-%d")
                close = row.get("Close")
                if pd.notna(close) and close > 0:
                    out[date_str] = float(close)
            return out
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            if "rate limit" in msg or "too many requests" in msg or "429" in msg:
                continue
            if "no data" in msg or "delisted" in msg:
                return {}
            continue
    print(f"  WARN 110990.KQ history fetch failed after {len(delays)} attempts: {last_exc}")
    return {}


def find_nearest_dit(dit_history: dict, target_date: str) -> float | None:
    """Find 110990 close on target_date, or fall back to most recent prior trading day."""
    if target_date in dit_history:
        return dit_history[target_date]
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    for back in range(1, 8):
        d = (dt - timedelta(days=back)).strftime("%Y-%m-%d")
        if d in dit_history:
            return dit_history[d]
    return None


def _build_fx_lookup(daily_files: dict) -> dict:
    """Build {date: usd_krw} from all owners' daily files (uses any owner's non-zero rate)."""
    fx = {}
    for owner, (path, daily) in daily_files.items():
        for date_str, snap in daily.items():
            if date_str.startswith("_"):
                continue
            rate = snap.get("usd_krw")
            if rate and rate > 0 and date_str not in fx:
                fx[date_str] = float(rate)
    return fx


def _resolve_fx(date_str: str, snap: dict, fx_lookup: dict) -> float | None:
    """Try snap's own usd_krw, then cross-owner lookup for same date."""
    rate = snap.get("usd_krw")
    if rate and rate > 0:
        return float(rate)
    return fx_lookup.get(date_str)


def main():
    # Step 1: discover owners + load their baselines and current v0
    owner_baselines = {}
    owner_current_v0 = {}
    for owner, ppath in discover_portfolios(PROJECT_DIR):
        holdings = _parse_portfolio_for_report(ppath)
        baseline = load_or_build_baseline(holdings, owner, PROJECT_DIR)
        v0_krw, _excluded = compute_v0_total_krw(holdings, baseline)
        owner_baselines[owner] = baseline
        owner_current_v0[owner] = v0_krw
        spy_v0_krw = baseline["spy_close_usd"] * baseline["usd_krw"]
        print(f"  {owner}: current v0_krw={v0_krw:,.0f}, spy_v0_krw={spy_v0_krw:,.2f} (Jan 2: SPY ${baseline['spy_close_usd']:.2f}, USD/KRW {baseline['usd_krw']:.2f})")
    print()

    # Cache per-owner holdings for DIT/rest decomposition
    owner_holdings = {}
    for owner, ppath in discover_portfolios(PROJECT_DIR):
        owner_holdings[owner] = _parse_portfolio_for_report(ppath)

    # Step 2: collect all historical dates across all daily files
    all_dates = set()
    daily_files = {}
    for owner in owner_baselines:
        fname = "portfolio_daily.json" if owner == "me" else f"portfolio_daily_{owner}.json"
        path = os.path.join(PROJECT_DIR, "history", fname)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            daily = json.load(f)
        daily_files[owner] = (path, daily)
        for d in daily.keys():
            if not d.startswith("_"):
                all_dates.add(d)

    if not all_dates:
        print("No historical snapshots found. Nothing to backfill.")
        return

    sorted_dates = sorted(all_dates)
    print(f"Historical dates: {sorted_dates[0]} → {sorted_dates[-1]} ({len(sorted_dates)} dates)")

    # Step 3: fetch SPY history for the full range (one bulk call)
    spy_history = fetch_spy_history(ANCHOR_DATE, sorted_dates[-1])
    print(f"  Fetched {len(spy_history)} SPY trading days\n")
    if not spy_history:
        print("  WARN SPY history empty — skipping backfill (will retry on next run)")
        return  # graceful exit, exit code 0

    dit_history = fetch_dit_history(ANCHOR_DATE, sorted_dates[-1])
    print(f"  Fetched {len(dit_history)} 110990.KQ trading days\n")
    # Note: DIT history may be empty for owners not holding 110990 — that's OK,
    # decomposition will return None fields for those owners.

    # Cross-owner FX fallback table (in case one owner's snapshot has usd_krw=0)
    fx_lookup = _build_fx_lookup(daily_files)
    print(f"  Built FX fallback table: {len(fx_lookup)} dates with usd_krw\n")

    # Step 4: backfill each daily file
    for owner, (path, daily) in daily_files.items():
        baseline = owner_baselines[owner]
        current_v0 = owner_current_v0[owner]
        spy_v0_krw = baseline["spy_close_usd"] * baseline["usd_krw"]

        added = 0
        updated = 0  # snapshots that already had None ytd_pct → re-filled
        skipped_existing = 0
        skipped_no_data = 0
        for date_str in sorted([k for k in daily.keys() if not k.startswith("_")]):
            snap = daily[date_str]
            # If all 3 fields exist AND non-None → skip (already valid).
            # If all 3 keys exist but values are None → reprocess (previous backfill failed).
            existing_ok = (
                all(k in snap for k in ("ytd_pct", "spy_ytd_pct", "alpha_pp"))
                and snap.get("ytd_pct") is not None
            )
            if existing_ok:
                skipped_existing += 1
                continue
            is_update = "ytd_pct" in snap  # already has the key but value is None

            usd_krw_d = _resolve_fx(date_str, snap, fx_lookup)
            total_krw_d = snap.get("total_value_krw")
            if not usd_krw_d or not total_krw_d:
                skipped_no_data += 1
                continue

            spy_d_usd = find_nearest_spy(spy_history, date_str)
            if spy_d_usd is None:
                skipped_no_data += 1
                continue

            spy_now_krw = spy_d_usd * usd_krw_d
            spy_ytd_pct = round((spy_now_krw / spy_v0_krw - 1) * 100, 2) if spy_v0_krw > 0 else None
            ytd_pct = round((total_krw_d / current_v0 - 1) * 100, 2) if current_v0 > 0 else None
            alpha_pp = round(ytd_pct - spy_ytd_pct, 2) if ytd_pct is not None and spy_ytd_pct is not None else None

            snap["ytd_pct"] = ytd_pct
            snap["spy_ytd_pct"] = spy_ytd_pct
            snap["alpha_pp"] = alpha_pp
            # v0_krw 와 spy_v0_krw 도 채워서 합산 뷰가 작동하도록
            if snap.get("v0_krw") is None:
                snap["v0_krw"] = round(current_v0)
            if snap.get("spy_v0_krw") is None:
                snap["spy_v0_krw"] = round(spy_v0_krw, 2)
            # DIT/rest decomposition (110990 보유 owner만)
            holdings_for_owner = owner_holdings.get(owner, [])
            dit_close_d = find_nearest_dit(dit_history, date_str)
            if dit_close_d is not None and holdings_for_owner:
                today_prices_d = {DIT_TICKER: dit_close_d}
                decomp = compute_dit_rest_decomposition(
                    holdings_for_owner,
                    today_prices_d,
                    usd_krw_d,
                    baseline,
                    float(current_v0),
                    float(total_krw_d),
                )
                if decomp["dit_ytd_pct"] is not None:
                    snap["dit_ytd_pct"] = round(decomp["dit_ytd_pct"], 2)
                if decomp["rest_ytd_pct"] is not None:
                    snap["rest_ytd_pct"] = round(decomp["rest_ytd_pct"], 2)
                if decomp["dit_v0_krw"] is not None:
                    snap["dit_v0_krw"] = round(decomp["dit_v0_krw"])
                if decomp["dit_now_krw"] is not None:
                    snap["dit_now_krw"] = round(decomp["dit_now_krw"])
                if decomp["rest_v0_krw"] is not None:
                    snap["rest_v0_krw"] = round(decomp["rest_v0_krw"])
                if decomp["rest_now_krw"] is not None:
                    snap["rest_now_krw"] = round(decomp["rest_now_krw"])
            if is_update:
                updated += 1
            else:
                added += 1

        # Write back
        if added > 0 or updated > 0:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(daily, f, ensure_ascii=False, indent=2)
        print(f"  {owner}: added={added}, updated={updated}, skipped_existing={skipped_existing}, skipped_no_data={skipped_no_data}")

    print("\nBackfill complete.")
    print("Note: portfolio ytd_pct uses 'today\\'s composition since Jan 2' approximation.")
    print("      If positions changed materially over the year, historical points are approximate.")
    print("      SPY ytd_pct is exact (per-date SPY × per-date USD/KRW vs Jan 2 baseline).")


if __name__ == "__main__":
    main()
