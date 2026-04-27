"""Full historical backfill from 2026-01-02 → today.

Reconstructs synthetic portfolio_daily snapshots for missing trading days using
TODAY'S holdings priced at historical close prices. Bulk-fetches all needed
tickers + macro indicators (SPY, KRW=X, ^VIX, ^TYX) in one yfinance call.

Honest limitation: pre-Mar 5 snapshots assume today's portfolio composition.
Each backfilled snapshot is marked with `"_synthetic": True`.

Usage: python backfill_full_history.py
"""
import json
import os
import sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

import yfinance as yf
import pandas as pd

from benchmark_ytd import (
    ANCHOR_DATE, SPY_SYMBOL, USDKRW_SYMBOL,
    load_or_build_baseline, compute_v0_total_krw, resolve_yf_symbol,
)
from portfolio_paths import discover_portfolios
from pipeline import _parse_portfolio_for_report
from portfolio_data import (
    is_korean_ticker, get_ticker_name, get_ticker_class,
)

VIX_SYMBOL = "^VIX"
YIELD_30Y_SYMBOL = "^TYX"


def main():
    # Step 1: discover owners + holdings
    owners = {}  # owner -> list of holdings
    for owner, ppath in discover_portfolios(PROJECT_DIR):
        owners[owner] = _parse_portfolio_for_report(ppath)
    print(f"Owners: {list(owners.keys())}")

    # Step 2: collect all unique tickers
    all_tickers = set()
    for holdings in owners.values():
        for h in holdings:
            all_tickers.add(h["ticker"])
    print(f"Total unique tickers: {len(all_tickers)}")

    # Build yf symbol map
    yf_symbol_of = {t: resolve_yf_symbol(t) for t in all_tickers}
    download_symbols = list(set(yf_symbol_of.values())) + [SPY_SYMBOL, USDKRW_SYMBOL, VIX_SYMBOL, YIELD_30Y_SYMBOL]
    download_symbols = sorted(set(download_symbols))
    print(f"Bulk-fetching {len(download_symbols)} symbols from yfinance...")

    end_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    df = yf.download(
        download_symbols, start=ANCHOR_DATE, end=end_date,
        auto_adjust=False, progress=False, group_by="ticker", threads=True,
    )
    if df is None or df.empty:
        print("ERROR: yfinance download returned empty")
        return

    def get_close(symbol: str, date_str: str, use_adj_close: bool = False) -> float | None:
        """Forward-fill: find Close (or Adj Close) on or before date_str.

        Drops NaN values before picking the last one — handles the case where
        intraday today's data exists in the row but the close hasn't been reported
        yet (e.g., US market still open, or KR market data not yet posted)."""
        col = "Adj Close" if use_adj_close else "Close"
        try:
            if isinstance(df.columns, pd.MultiIndex):
                s = df[symbol][col]
            else:
                s = df[col]
            target = pd.Timestamp(date_str)
            idx = s.index
            if hasattr(idx, "tz") and idx.tz is not None:
                idx = idx.tz_localize(None)
                s.index = idx
            sub = s[s.index <= target].dropna()
            if len(sub) == 0:
                return None
            return float(sub.iloc[-1])
        except (KeyError, IndexError):
            return None

    # SPY trading dates = canonical calendar
    try:
        spy_idx = df[SPY_SYMBOL].index if isinstance(df.columns, pd.MultiIndex) else df.index
    except KeyError:
        print("ERROR: SPY data missing in download")
        return
    if hasattr(spy_idx, "tz") and spy_idx.tz is not None:
        spy_idx = spy_idx.tz_localize(None)
    spy_dates = [d.strftime("%Y-%m-%d") for d in spy_idx]
    print(f"SPY trading days in range: {len(spy_dates)} ({spy_dates[0]} → {spy_dates[-1]})")

    # Step 3: per-owner backfill
    for owner, holdings in owners.items():
        fname = "portfolio_daily.json" if owner == "me" else f"portfolio_daily_{owner}.json"
        path = os.path.join(PROJECT_DIR, "history", fname)
        if not os.path.exists(path):
            print(f"  {owner}: {fname} not found, skipping")
            continue
        with open(path, "r", encoding="utf-8") as f:
            daily = json.load(f)

        existing_dates = set(k for k in daily.keys() if not k.startswith("_"))
        # Real snapshots (non-synthetic) are protected. Synthetic ones get reprocessed
        # to allow methodology fixes (e.g., switching SPY Adj Close vs Close).
        real_dates = {k for k in existing_dates if not daily.get(k, {}).get("_synthetic")}
        # Exclude today's date — pipeline generates it after market close.
        # Synthetic for today would use partial intraday data (US market still open).
        today_str = datetime.now().strftime("%Y-%m-%d")
        missing_dates = [d for d in spy_dates if d not in real_dates and d != today_str]
        # Also delete any pre-existing synthetic snapshot for today (from prior backfill)
        if today_str in daily and daily[today_str].get("_synthetic"):
            del daily[today_str]
            print(f"  {owner}: removed stale synthetic snapshot for today ({today_str})")

        baseline = load_or_build_baseline(holdings, owner, PROJECT_DIR)
        v0_krw, _ = compute_v0_total_krw(holdings, baseline)
        spy_v0_krw = baseline["spy_close_usd"] * baseline["usd_krw"]

        # Forward-fill div_annual from nearest preceding real snapshot.
        # Synthetic dates inherit the most recent real div value, smoothing transitions
        # across mixed real/synthetic regions (e.g., when user skipped pipeline runs).
        sorted_real = sorted(real_dates)
        oldest_real_div = daily.get(sorted_real[0], {}).get("div_annual_krw", 0) if sorted_real else 0

        def synth_div_for(date_str: str) -> float:
            # Most recent real snapshot on/before date_str. Fall back to oldest if date_str is before all real.
            for rd in reversed(sorted_real):
                if rd <= date_str:
                    return daily[rd].get("div_annual_krw", 0) or 0
            return oldest_real_div

        # LATEST real cost basis → smooth Investment Principal line (real cost is stable)
        latest_real = max(real_dates) if real_dates else None
        latest_cost_basis = daily.get(latest_real, {}).get("cost_basis_krw") if latest_real else None
        if latest_cost_basis is None or latest_cost_basis <= 0:
            latest_cost_basis = v0_krw  # fallback if no real snapshots

        added = 0
        skipped = 0
        for date_str in missing_dates:
            fx_d = get_close(USDKRW_SYMBOL, date_str)
            if fx_d is None or fx_d <= 0:
                skipped += 1
                continue

            # Per-ticker value at this date
            total_krw = 0.0
            ticker_value_krw = {}
            for h in holdings:
                t = h["ticker"]
                yf_sym = yf_symbol_of[t]
                price_d = get_close(yf_sym, date_str)
                if price_d is None or price_d <= 0:
                    continue
                shares = h["shares"]
                if is_korean_ticker(t):
                    val = shares * price_d
                else:
                    val = shares * price_d * fx_d
                ticker_value_krw[t] = val
                total_krw += val

            if total_krw <= 0:
                skipped += 1
                continue

            # Weights
            weights_by_ticker = {}
            weights_by_category = {}
            for t, v in ticker_value_krw.items():
                w = v / total_krw * 100
                nm = (get_ticker_name(t) or t) if is_korean_ticker(t) else t
                weights_by_ticker[nm] = round(w, 1)
                cls = get_ticker_class(t) or "Other"
                weights_by_category[cls] = weights_by_category.get(cls, 0) + w
            weights_by_category = {k: round(v, 1) for k, v in weights_by_category.items()}

            # Cash from BIL
            bil_h = next((h for h in holdings if h["ticker"] == "BIL"), None)
            cash_krw = 0.0
            if bil_h:
                bil_price_d = get_close(yf_symbol_of.get("BIL", "BIL"), date_str)
                if bil_price_d:
                    cash_krw = bil_h["shares"] * bil_price_d * fx_d
            cash_pct = (cash_krw / total_krw * 100) if total_krw > 0 else 0

            # SPY YTD (Adj Close for consistency with baseline)
            spy_d = get_close(SPY_SYMBOL, date_str, use_adj_close=True)
            if spy_d and spy_v0_krw > 0:
                spy_now_krw = spy_d * fx_d
                spy_ytd_pct = round((spy_now_krw / spy_v0_krw - 1) * 100, 2)
            else:
                spy_ytd_pct = None

            # Portfolio YTD
            ytd_pct = round((total_krw / v0_krw - 1) * 100, 2) if v0_krw > 0 else None
            alpha_pp = round(ytd_pct - spy_ytd_pct, 2) if (ytd_pct is not None and spy_ytd_pct is not None) else None

            # Macro
            vix_d = get_close(VIX_SYMBOL, date_str)
            yield_30y_d = get_close(YIELD_30Y_SYMBOL, date_str)

            # cost_basis = latest real cost (smooth Investment Principal line across boundary)
            cost_basis_d = latest_cost_basis
            pnl_krw_d = total_krw - cost_basis_d
            pnl_pct_d = (pnl_krw_d / cost_basis_d * 100) if cost_basis_d > 0 else 0

            snap = {
                "total_value_krw": round(total_krw),
                "cost_basis_krw": round(cost_basis_d),
                "pnl_krw": round(pnl_krw_d),
                "pnl_pct": round(pnl_pct_d, 1),
                "cash_value_krw": round(cash_krw),
                "cash_pct": round(cash_pct, 1),
                "div_annual_krw": round(synth_div_for(date_str)),
                # Recompute yield from synthetic total — accurate per-day
                "div_yield": round((synth_div_for(date_str) / total_krw * 100), 2) if total_krw > 0 else 0,
                "usd_krw": round(fx_d, 2),
                "vix": round(vix_d, 2) if vix_d else None,
                "yield_30y": round(yield_30y_d, 3) if yield_30y_d else None,
                "master_switch": "UNKNOWN",
                "holdings_count": len(holdings),
                "weights_by_category": weights_by_category,
                "weights_by_ticker": weights_by_ticker,
                "ytd_pct": ytd_pct,
                "spy_ytd_pct": spy_ytd_pct,
                "alpha_pp": alpha_pp,
                "v0_krw": round(v0_krw),
                "spy_v0_krw": round(spy_v0_krw, 2),
                "_synthetic": True,
            }
            daily[date_str] = snap
            added += 1

        if added > 0:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(daily, f, ensure_ascii=False, indent=2)
        print(f"  {owner}: backfilled {added} synthetic dates, skipped {skipped} (missing data)")

    print("\nFull backfill complete.")
    print("Note: synthetic snapshots use TODAY'S holdings × historical prices.")
    print("      cost_basis_krw set to v0_krw (Jan 2 baseline) for synthetic dates.")
    print("      div_annual_krw uses latest known value as constant.")


if __name__ == "__main__":
    main()
