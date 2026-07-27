"""와이프 포트폴리오의 자산 트렌드 히스토리를 과거 가격으로 재생성.

yfinance 레이트리밋 회피:
 - 단일 배치 다운로드 1회 (start/end 윈도우) → 네트워크 호출 최소화
 - 실패 시 티커별 단일 재시도 (지수 백오프)
 - FX(USD/KRW)도 한 번에 포함
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import yfinance as yf

from portfolio_data import to_yfinance_symbol, is_korean_ticker

ROOT = Path(__file__).parent
HIST_DIR = ROOT / "history"
ME_DAILY = HIST_DIR / "portfolio_daily.json"
WIFE_DAILY = HIST_DIR / "portfolio_daily_wife.json"

# 와이프 보유 (ticker, shares, avg_cost_krw) — portfolios/wife.md 에서 수동 추출
# avg_cost_krw = (평가금액 - 수익금액) / 보유수량 — 원 단위
HOLDINGS: list[tuple[str, float, float]] = [
    # ETF/해외
    ("QQQ", 104.144608, (105_213_652 - 9_229_688) / 104.144608),
    ("VOO", 74.254657, (74_458_857 - 3_500_422) / 74.254657),
    ("SCHD", 608.084445, (29_888_566 - 5_106_679) / 608.084445),
    ("AAPL", 45.950399, (22_593_994 - 8_242_260) / 45.950399),
    ("TLT", 33.230424, (4_084_617 - (-30_928)) / 33.230424),
    ("QLD", 23.080847, (2_828_534 - (-155_030)) / 23.080847),
    # KR
    ("110990", 21_510.0, (352_764_000 - 85_816_844) / 21_510.0),
    ("000660", 20.0, (35_180_000 - (-7_358_000)) / 20.0),
    ("005935", 120.0, (21_252_000 - 12_169_899) / 120.0),
    ("005930", 46.0, (11_477_000 - 6_174_200) / 46.0),
    ("005380", 16.0, (6_416_000 - (-3_804_000)) / 16.0),
    ("011170", 17.0, (1_038_700 - (-2_379_246)) / 17.0),
    ("014820", 47.0, (935_770 - (-5_466_527)) / 47.0),
    ("003475", 160.0, (675_200 - (-468_800)) / 160.0),
    ("012330", 1.0, (482_000 - 169_137) / 1.0),
    ("446720", 3_970.0, (55_659_400 - 1_816_285) / 3_970.0),
    ("069500", 400.0, (42_546_000 - (-2_100_287)) / 400.0),
    ("133690", 149.0, (27_468_895 - 2_991_480) / 149.0),
    ("360750", 832.0, (22_434_880 - 1_822_585) / 832.0),
    ("229200", 310.0, (3_878_100 - (-2_059_440)) / 310.0),
    ("381170", 124.0, (3_823_540 - 816_145) / 124.0),
    ("102110", 30.0, (3_192_750 - 37_150) / 30.0),
    ("0183J0", 300.0, (2_202_000 - (-2_798_600)) / 300.0),
]
# USD 종목 (원화 환산 필요)
USD_TICKERS = {"QQQ", "VOO", "SCHD", "AAPL", "TLT", "QLD"}


def _symbol(ticker: str) -> str:
    return to_yfinance_symbol(ticker) if is_korean_ticker(ticker) else ticker


def _compute_wife_div_fields(target_ts, holdings, usd_tickers, fx, divs_map, total_krw):
    """TTM 기반 배당 계산 (2026-04-28 하드코딩 0 제거)."""
    import portfolio_history_core as core
    total_div_krw = 0.0
    for ticker, shares, _ in holdings:
        if shares <= 0:
            continue
        ttm = core.compute_ttm_dividend(divs_map.get(ticker, pd.Series(dtype=float)), target_ts)
        if ttm <= 0:
            continue
        annual = ttm * shares
        total_div_krw += annual * fx if ticker in usd_tickers else annual
    return {
        "div_annual_krw": round(total_div_krw),
        "div_yield": round(total_div_krw / total_krw * 100, 2) if total_krw > 0 else 0.0,
    }


def main():
    # me의 날짜 범위 사용
    with open(ME_DAILY, encoding="utf-8") as f:
        me = json.load(f)
    dates = sorted([k for k in me.keys() if not k.startswith("_")])
    start_date = dates[0]
    end_date = dates[-1]
    print(f"[INFO] 재구성 기간: {start_date} ~ {end_date} ({len(dates)}일)")

    tickers = [(t, s, c) for t, s, c in HOLDINGS]
    symbols = list({_symbol(t) for t, _, _ in tickers}) + ["KRW=X"]
    print(f"[INFO] 심볼 수: {len(symbols)}")

    # 배당 시리즈 미리 fetch (TTM 계산용)
    import portfolio_history_core as core
    print(f"[INFO] 배당 히스토리 다운로드 중...")
    div_tickers = [t for t, _, _ in HOLDINGS]
    divs_map = core.fetch_all_dividends(div_tickers, logger=lambda msg: print(f"  {msg}"))

    # Ticker.history(period=) 직렬 요청 — yf.download보다 안정적
    start_dt = pd.Timestamp(start_date) - pd.Timedelta(days=7)
    end_dt = pd.Timestamp(end_date) + pd.Timedelta(days=2)
    # 기간: me 첫날부터 오늘까지 커버하도록 3mo~6mo 선택
    days_span = (pd.Timestamp.now() - start_dt).days
    if days_span <= 60:
        period = "3mo"
    elif days_span <= 120:
        period = "6mo"
    else:
        period = "1y"
    print(f"[INFO] 직렬 다운로드(period={period}): {len(symbols)}개 심볼")

    closes: dict[str, pd.Series] = {}
    for i, sym in enumerate(symbols, 1):
        for attempt in range(4):
            try:
                time.sleep(0.8)  # 레이트리밋 완화
                hist = yf.Ticker(sym).history(period=period, auto_adjust=False)
                if not hist.empty:
                    closes[sym] = hist["Close"].dropna()
                    print(f"  [{i:2}/{len(symbols)}] {sym}: {len(hist)} rows")
                    break
                else:
                    print(f"  [{i:2}/{len(symbols)}] {sym}: empty (try {attempt + 1})")
            except Exception as e:
                wait = 2 ** attempt
                print(f"  [{i:2}/{len(symbols)}] {sym}: {type(e).__name__} — {wait}s 대기")
                time.sleep(wait)
        else:
            print(f"  [{i:2}/{len(symbols)}] {sym}: FAILED")

    got = sum(1 for s in symbols if s in closes and not closes[s].empty)
    print(f"[INFO] 가격 확보: {got}/{len(symbols)} 심볼")

    # 각 영업일별 자산 계산
    fx_series = closes.get("KRW=X", pd.Series(dtype=float))
    if fx_series.empty:
        print("[ERROR] USD/KRW 환율 없음 — 종료")
        return
    fx_series.index = fx_series.index.tz_localize(None) if fx_series.index.tz else fx_series.index

    # 타임존 정규화
    for sym, s in list(closes.items()):
        if s.index.tz:
            closes[sym] = s.tz_localize(None)

    wife_daily = {}
    for date_str in dates:
        target = pd.Timestamp(date_str)
        # 당일 ≤ target 최근 영업일 가격 사용
        def _price_at(sym: str):
            s = closes.get(sym)
            if s is None or s.empty:
                return None
            s2 = s[s.index <= target]
            return float(s2.iloc[-1]) if not s2.empty else None

        fx_vals = fx_series[fx_series.index <= target]
        fx = float(fx_vals.iloc[-1]) if not fx_vals.empty else 0
        if fx <= 0:
            print(f"[SKIP] {date_str}: FX 누락")
            continue

        total_krw = 0.0
        cost_krw = 0.0
        weights_krw: dict[str, float] = {}
        missing_syms: list[str] = []
        for ticker, shares, avg_cost in HOLDINGS:
            sym = _symbol(ticker)
            px = _price_at(sym)
            if px is None:
                missing_syms.append(sym)
                continue
            if ticker in USD_TICKERS:
                val_krw = px * shares * fx
            else:
                val_krw = px * shares
            total_krw += val_krw
            cost_krw += avg_cost * shares
            weights_krw[ticker] = val_krw

        if total_krw <= 0:
            print(f"[SKIP] {date_str}: total 0 (missing={missing_syms})")
            continue

        pnl_krw = total_krw - cost_krw
        pnl_pct = round(pnl_krw / cost_krw * 100, 2) if cost_krw > 0 else 0
        weights_by_ticker = {
            t: round(v / total_krw * 100, 2) for t, v in weights_krw.items()
        }

        wife_daily[date_str] = {
            "total_value_krw": int(total_krw),
            "cost_basis_krw": int(cost_krw),
            "pnl_krw": int(pnl_krw),
            "pnl_pct": pnl_pct,
            "cash_value_krw": 0,
            "cash_pct": 0.0,
            # ─── 배당: TTM 기반으로 계산 (2026-04-28 하드코딩 0 제거) ───
            **_compute_wife_div_fields(pd.Timestamp(date_str), HOLDINGS, USD_TICKERS, fx, divs_map, total_krw),
            "usd_krw": round(fx, 2),
            "vix": None,
            "yield_30y": None,
            "master_switch": "UNKNOWN",
            "holdings_count": len(HOLDINGS) - len(missing_syms),
            "weights_by_category": {},
            "weights_by_ticker": weights_by_ticker,
        }
        if missing_syms:
            print(f"[{date_str}] 누락 {len(missing_syms)}: {missing_syms[:3]}...")

    # 기존 2026-04-15 데이터 보존 (공식 값)
    existing = {}
    if WIFE_DAILY.exists():
        with open(WIFE_DAILY, encoding="utf-8") as f:
            existing = json.load(f)
    # 마지막 날은 기존 값(수동 추출) 유지 (있으면)
    last = dates[-1]
    if last in existing:
        wife_daily[last] = existing[last]

    with open(WIFE_DAILY, "w", encoding="utf-8") as f:
        json.dump(wife_daily, f, ensure_ascii=False, indent=2)
    print(f"[DONE] {len(wife_daily)}일치 저장 → {WIFE_DAILY}")


if __name__ == "__main__":
    main()
