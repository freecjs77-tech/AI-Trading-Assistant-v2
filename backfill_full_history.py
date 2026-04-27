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
        """Forward-fill: find Close (or Adj Close) on or before date_str."""
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
            sub = s[s.index <= target]
            if len(sub) == 0:
                return None
            v = sub.iloc[-1]
            if pd.isna(v):
                return None
            return float(v)
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
        missing_dates = [d for d in spy_dates if d not in real_dates]

        baseline = load_or_build_baseline(holdings, owner, PROJECT_DIR)
        v0_krw, _ = compute_v0_total_krw(holdings, baseline)
        spy_v0_krw = baseline["spy_close_usd"] * baseline["usd_krw"]

        # Latest dividend values (constant for backfill)
        latest_date = max(existing_dates) if existing_dates else None
        latest_div_krw = daily.get(latest_date, {}).get("div_annual_krw", 0) if latest_date else 0
        latest_div_yield = daily.get(latest_date, {}).get("div_yield", 0) if latest_date else 0

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

            # cost_basis = v0_krw for synthetic snapshots (Jan 2 baseline as anchor)
            cost_basis_d = v0_krw
            pnl_krw_d = total_krw - cost_basis_d
            pnl_pct_d = (pnl_krw_d / cost_basis_d * 100) if cost_basis_d > 0 else 0

            snap = {
                "total_value_krw": round(total_krw),
                "cost_basis_krw": round(cost_basis_d),
                "pnl_krw": round(pnl_krw_d),
                "pnl_pct": round(pnl_pct_d, 1),
                "cash_value_krw": round(cash_krw),
                "cash_pct": round(cash_pct, 1),
                "div_annual_krw": round(latest_div_krw),
                "div_yield": round(latest_div_yield, 2),
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
