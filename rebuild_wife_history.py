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
    ("BIL", 1000.0, (134_794_000 - 11_095_250) / 1000.0),
    ("QQQ", 50.492474, (46_814_854 - 8_408_183) / 50.492474),
    ("VOO", 32.660627, (30_731_527 - 2_362_586) / 32.660627),
    ("SCHD", 464.441909, (20_988_594 - 3_184_062) / 464.441909),
    ("AAPL", 45.950399, (17_529_050 - 3_177_975) / 45.950399),
    ("TSLA", 23.0, (12_449_854 - (-894_516)) / 23.0),
    ("TLT", 33.230424, (4_272_203 - 156_658) / 33.230424),
    # KR
    ("110990", 23_150.0, (518_560_000 - 225_812_154) / 23_150.0),
    ("005935", 120.0, (17_352_000 - 8_269_899) / 120.0),
    ("005930", 40.0, (8_440_000 - 5_104_200) / 40.0),
    ("011170", 17.0, (1_523_200 - (-1_894_746)) / 17.0),
    ("012330", 3.0, (1_246_500 - 307_911) / 3.0),
    ("014820", 47.0, (1_205_550 - (-5_196_747)) / 47.0),
    ("003475", 160.0, (695_200 - (-448_800)) / 160.0),
    ("446720", 1_885.0, (24_910_275 - (-86_305)) / 1_885.0),
    ("133690", 99.0, (16_706_250 - 1_583_845) / 99.0),
    ("360750", 566.0, (14_441_490 - 1_219_375) / 566.0),
    ("069500", 140.0, (12_973_100 - 1_655_500) / 140.0),
    ("381170", 242.0, (7_437_870 - 1_093_125) / 242.0),
    ("229200", 180.0, (3_494_700 - 74_200) / 180.0),
    ("0153K0", 260.0, (3_130_400 - (-43_730)) / 260.0),
    ("0154F0", 90.0, (1_332_000 - 50_650) / 90.0),
]
# USD 종목 (원화 환산 필요)
USD_TICKERS = {"BIL", "QQQ", "VOO", "SCHD", "AAPL", "TSLA", "TLT"}


def _symbol(ticker: str) -> str:
    return to_yfinance_symbol(ticker) if is_korean_ticker(ticker) else ticker


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
            "div_annual_krw": 0,
            "div_yield": 0,
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
