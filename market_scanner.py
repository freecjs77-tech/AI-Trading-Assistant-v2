"""
market_scanner.py -- S&P 100 Market Scanner
AI Trading Assistant v3.0

S&P 100 시총 상위 기업을 스캔하여 Entry 시그널(1st/2nd/3rd BUY, WATCH) 종목을 탐색.
Growth v2.2 Entry 규칙을 통일 적용.
"""

import os
import sys
import json
import subprocess
from datetime import date, datetime, timezone, timedelta

_KST = timezone(timedelta(hours=9))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from signal_judge import (
    _check_entry_growth, _check_entry_etf, check_exit_simple, _BUY_SIGNALS,
    _build_entry_sections_growth, _build_entry_sections_etf,
)
from portfolio_data import TICKER_META

# ── S&P 100 종목 리스트 (OEX 구성종목, 2026년 기준) ─────
SP100_TICKERS = [
    "AAPL", "ABBV", "ABT", "ACN", "ADBE", "AIG", "AMD", "AMGN", "AMZN", "AVGO",
    "AXP", "BA", "BAC", "BK", "BKNG", "BLK", "BMY", "BRK-B", "C", "CAT",
    "CHTR", "CL", "CMCSA", "COF", "COP", "COST", "CRM", "CSCO", "CVS", "CVX",
    "DE", "DHR", "DIS", "DOW", "DUK", "EMR", "EXC", "F", "FDX", "GD",
    "GE", "GILD", "GM", "GOOG", "GOOGL", "GS", "HD", "HON", "IBM", "INTC",
    "INTU", "JNJ", "JPM", "KHC", "KO", "LIN", "LLY", "LMT", "LOW", "MA",
    "MCD", "MDLZ", "MDT", "MET", "META", "MMM", "MO", "MRK", "MS", "MSFT",
    "NEE", "NFLX", "NKE", "NVDA", "ORCL", "PEP", "PFE", "PG", "PM", "PYPL",
    "QCOM", "RTX", "SBUX", "SCHW", "SO", "SPG", "T", "TGT", "TMO", "TMUS",
    "TSLA", "TXN", "UNH", "UNP", "UPS", "USB", "V", "VZ", "WFC", "WMT",
    "XOM",
]

# 종목 이름 (스캐너 표시용)
SP100_NAMES = {
    "AAPL": "Apple", "ABBV": "AbbVie", "ABT": "Abbott Labs", "ACN": "Accenture",
    "ADBE": "Adobe", "AIG": "AIG", "AMD": "AMD", "AMGN": "Amgen",
    "AMZN": "Amazon", "AVGO": "Broadcom", "AXP": "American Express", "BA": "Boeing",
    "BAC": "Bank of America", "BK": "BNY Mellon", "BKNG": "Booking Holdings",
    "BLK": "BlackRock", "BMY": "Bristol-Myers", "BRK-B": "Berkshire Hathaway",
    "C": "Citigroup", "CAT": "Caterpillar", "CHTR": "Charter Comm", "CL": "Colgate",
    "CMCSA": "Comcast", "COF": "Capital One", "COP": "ConocoPhillips",
    "COST": "Costco", "CRM": "Salesforce", "CSCO": "Cisco", "CVS": "CVS Health",
    "CVX": "Chevron", "DE": "Deere", "DHR": "Danaher", "DIS": "Disney",
    "DOW": "Dow Inc", "DUK": "Duke Energy", "EMR": "Emerson", "EXC": "Exelon",
    "F": "Ford", "FDX": "FedEx", "GD": "General Dynamics", "GE": "GE Aerospace",
    "GILD": "Gilead", "GM": "GM", "GOOG": "Alphabet C", "GOOGL": "Alphabet A",
    "GS": "Goldman Sachs", "HD": "Home Depot", "HON": "Honeywell", "IBM": "IBM",
    "INTC": "Intel", "INTU": "Intuit", "JNJ": "J&J", "JPM": "JPMorgan",
    "KHC": "Kraft Heinz", "KO": "Coca-Cola", "LIN": "Linde", "LLY": "Eli Lilly",
    "LMT": "Lockheed Martin", "LOW": "Lowe's", "MA": "Mastercard", "MCD": "McDonald's",
    "MDLZ": "Mondelez", "MDT": "Medtronic", "MET": "MetLife", "META": "Meta",
    "MMM": "3M", "MO": "Altria", "MRK": "Merck", "MS": "Morgan Stanley",
    "MSFT": "Microsoft", "NEE": "NextEra Energy", "NFLX": "Netflix", "NKE": "Nike",
    "NVDA": "NVIDIA", "ORCL": "Oracle", "PEP": "PepsiCo", "PFE": "Pfizer",
    "PG": "Procter & Gamble", "PM": "Philip Morris", "PYPL": "PayPal",
    "QCOM": "Qualcomm", "RTX": "RTX Corp", "SBUX": "Starbucks", "SCHW": "Schwab",
    "SO": "Southern Co", "SPG": "Simon Property", "T": "AT&T", "TGT": "Target",
    "TMO": "Thermo Fisher", "TMUS": "T-Mobile", "TSLA": "Tesla", "TXN": "Texas Instruments",
    "UNH": "UnitedHealth", "UNP": "Union Pacific", "UPS": "UPS", "USB": "US Bancorp",
    "V": "Visa", "VZ": "Verizon", "WFC": "Wells Fargo", "WMT": "Walmart",
    "XOM": "ExxonMobil",
}


# ═══════════════════════════════════════════════════════
#  스캐너 BUY 연속일 관리  [v5.1b]
# ═══════════════════════════════════════════════════════

_SCANNER_HISTORY_DIR = "history"
_MIN_CONSECUTIVE_DAYS = 2


_SCANNER_HISTORY_KEEP_DAYS = 30


def _load_scanner_history(project_dir: str, scanner_name: str) -> dict:
    """스캐너 전용 시그널 이력 로드.
    날짜별 구조: {date_str: {ticker: {signal: ...}, ...}, ...}"""
    path = os.path.join(project_dir, _SCANNER_HISTORY_DIR, f"scanner_{scanner_name}_history.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 구버전(flat) → 신버전(date-keyed) 마이그레이션
        # 구버전 키는 티커명(e.g. "EFA"), 신버전 키는 날짜(e.g. "2026-04-03")
        import re
        date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        is_new_format = any(date_pattern.match(k) for k in data.keys())
        if data and not is_new_format:
            return _migrate_flat_history(data)
        # 신버전이지만 구버전 잔여 키가 섞여 있으면 정리
        if data:
            data = {k: v for k, v in data.items() if date_pattern.match(k)}
        return data
    except (json.JSONDecodeError, IOError):
        return {}


def _migrate_flat_history(old: dict) -> dict:
    """구버전 {ticker: {signal, streak, date}} → 신버전 {date: {ticker: {signal}}} 변환."""
    new = {}
    for ticker, info in old.items():
        dt = info.get("date", "")
        if not dt:
            continue
        if dt not in new:
            new[dt] = {}
        new[dt][ticker] = {"signal": info.get("signal", "")}
    return new


def _save_scanner_history(project_dir: str, scanner_name: str, history: dict):
    """스캐너 전용 시그널 이력 저장 (30일 이전 자동 정리)."""
    dir_path = os.path.join(project_dir, _SCANNER_HISTORY_DIR)
    os.makedirs(dir_path, exist_ok=True)
    # 30일 이전 데이터 정리
    from datetime import timedelta
    cutoff = (date.today() - timedelta(days=_SCANNER_HISTORY_KEEP_DAYS)).strftime("%Y-%m-%d")
    pruned = {k: v for k, v in history.items() if k >= cutoff}
    path = os.path.join(dir_path, f"scanner_{scanner_name}_history.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pruned, f, ensure_ascii=False, indent=2)


def _had_prior_buy(ticker: str, history: dict, today_str: str = "") -> bool:
    """전일(가장 최근 이력)이 BUY였는지 확인. 거래량 면제 재판정용."""
    dates = sorted([k for k in history.keys() if k != today_str], reverse=True)
    if not dates:
        return False
    prev_data = history.get(dates[0], {}).get(ticker, {})
    return prev_data.get("signal", "") in _BUY_SIGNALS


def _calc_scanner_streak(ticker: str, signal: str, history: dict, today_str: str = "") -> int:
    """스캐너 종목의 BUY 연속일 계산 (오늘 포함).
    날짜별 이력을 역순 탐색하여 실제 연속 BUY일만 카운트."""
    if signal not in _BUY_SIGNALS:
        return 0

    streak = 1  # 오늘 포함

    dates = sorted([k for k in history.keys() if k != today_str], reverse=True)
    for dt in dates:
        day_data = history.get(dt, {})
        ticker_data = day_data.get(ticker, {})
        prev_signal = ticker_data.get("signal", "")

        if prev_signal not in _BUY_SIGNALS:
            break
        streak += 1
        if streak >= 5:
            break

    return streak


def _calc_hypothetical_return(ticker: str, current_price: float, history: dict, today_str: str = "") -> dict:
    """BUY 연속 구간에서 1일차/2일차(확정) 매수 가상 수익률 계산.

    히스토리를 역순 탐색하여 현재 연속 BUY 구간의 시작일과 2일째를 찾고,
    해당 날짜의 가격 대비 현재 수익률을 계산한다.

    Returns:
        dict with keys: day1_price, day1_date, day1_return,
                        day2_price, day2_date, day2_return
        가격 데이터 없으면 해당 값은 None.
    """
    result = {
        "day1_price": None, "day1_date": None, "day1_return": None,
        "day2_price": None, "day2_date": None, "day2_return": None,
    }
    if not current_price or current_price <= 0:
        return result

    # 과거 날짜를 역순으로 정렬하여 연속 BUY 구간 추출
    dates = sorted([k for k in history.keys() if k != today_str], reverse=True)
    buy_dates = []  # 연속 BUY 날짜들 (최신→과거 순)
    for dt in dates:
        day_data = history.get(dt, {})
        ticker_data = day_data.get(ticker, {})
        if ticker_data.get("signal", "") in _BUY_SIGNALS:
            buy_dates.append((dt, ticker_data))
        else:
            break
        if len(buy_dates) >= 10:
            break

    if not buy_dates:
        return result

    # buy_dates는 최신→과거 순이므로 뒤집어서 과거→최신 순으로
    buy_dates.reverse()

    # 1일차 = 연속 구간 첫 번째 날
    day1_dt, day1_data = buy_dates[0]
    day1_price = day1_data.get("price")
    if day1_price and day1_price > 0:
        result["day1_price"] = day1_price
        result["day1_date"] = day1_dt
        result["day1_return"] = round((current_price - day1_price) / day1_price * 100, 2)

    # 2일차 = 연속 구간 두 번째 날 (확정 매수 시점)
    if len(buy_dates) >= 2:
        day2_dt, day2_data = buy_dates[1]
        day2_price = day2_data.get("price")
        if day2_price and day2_price > 0:
            result["day2_price"] = day2_price
            result["day2_date"] = day2_dt
            result["day2_return"] = round((current_price - day2_price) / day2_price * 100, 2)

    return result


def _apply_streak_to_entries(entries: list, history: dict, today_str: str = "") -> list:
    """BUY entry 리스트에 streak/confirmed + 가상 수익률 필드 추가."""
    for e in entries:
        streak = _calc_scanner_streak(e["ticker"], e["signal"], history, today_str)
        confirmed = streak >= _MIN_CONSECUTIVE_DAYS
        e["buy_streak"] = streak
        e["buy_confirmed"] = confirmed
        if confirmed:
            e["note"] = f"[확정 {streak}일 연속] {e['note']}"
        else:
            e["note"] = f"[확인 대기 {streak}/{_MIN_CONSECUTIVE_DAYS}일] {e['note']}"

        # 가상 수익률 계산
        hypo = _calc_hypothetical_return(
            e["ticker"], e.get("price", 0), history, today_str
        )
        e["hypo_return"] = hypo
    return entries


def _update_scanner_history(buy_lists: list, scanner_name: str, project_dir: str, history: dict, today_str: str = "") -> dict:
    """오늘 스캔 결과를 날짜별 history에 반영하여 저장."""
    if not today_str:
        today_str = date.today().strftime("%Y-%m-%d")
    today_entry = {}
    for entries in buy_lists:
        for e in entries:
            today_entry[e["ticker"]] = {
                "signal": e["signal"],
                "price": e.get("price"),
                "rsi": e.get("rsi"),
                "macd_hist": e.get("macd_hist"),
                "drawdown": e.get("drawdown"),
            }
    history[today_str] = today_entry
    _save_scanner_history(project_dir, scanner_name, history)
    return history


def _load_portfolio_tickers(project_dir: str) -> set:
    """현재 보유 종목 리스트 로드 (스캐너에서 제외용)"""
    import re
    portfolio_path = os.path.join(project_dir, "portfolio.md")
    tickers = set()
    try:
        with open(portfolio_path, "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\|\s*([A-Z]{1,6})\s*\|", line)
                if m and m.group(1) not in ("Ticker",):
                    tickers.add(m.group(1).strip())
    except FileNotFoundError:
        pass
    return tickers


def _fetch_scanner_data(project_dir: str, tickers: list, cache_name: str) -> dict:
    """종목 기술지표를 yfinance로 수집"""
    fetch_script = os.path.join(project_dir, "fetch_market_data.py")
    python_exe = sys.executable
    today = date.today().strftime("%Y-%m-%d")
    output_path = os.path.join(project_dir, "screenshots", f"{cache_name}_{today}.json")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    # 종목을 직접 인자로 전달
    cmd = [python_exe, fetch_script, "--output", output_path, "--quiet"] + tickers
    result = subprocess.run(
        cmd,
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=600,  # 100종목이므로 10분 타임아웃
        env=env,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        return {"error": result.stderr[:300]}

    with open(output_path, "rb") as f:
        raw = f.read()
    return json.loads(raw.rstrip(b" \t\n\r\x00").decode("utf-8"))


def scan_sp100(project_dir: str) -> dict:
    """
    S&P 100 스캔 실행.
    반환: {scan_date, scanned, buy_1st, buy_2nd, buy_3rd, watch_signals, scan_time}
    """
    today = date.today().strftime("%Y-%m-%d")
    cache_path = os.path.join(project_dir, "screenshots", f"scanner_{today}.json")

    # 보유 종목 포함 — S&P 100 전체 스캔
    scan_tickers = SP100_TICKERS[:]

    print(f"[Scanner] Scanning {len(scan_tickers)} tickers")

    # 데이터 수집 (당일 캐시 있으면 재사용)
    start_time = datetime.now()
    cache_name = "scanner_sp100"
    cache_path = os.path.join(project_dir, "screenshots", f"{cache_name}_{today}.json")

    market_data = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "rb") as f:
                raw = f.read()
            market_data = json.loads(raw.rstrip(b" \t\n\r\x00").decode("utf-8"))
        except Exception:
            market_data = {}
    if market_data.get("data"):
        print(f"[Scanner] Using cached data: {cache_path}")
    else:
        print(f"[Scanner] Fetching data for {len(scan_tickers)} tickers...")
        market_data = _fetch_scanner_data(project_dir, scan_tickers, cache_name)
        if "error" in market_data:
            return {"status": "error", "error": market_data["error"]}

    data = market_data.get("data", {})
    elapsed = (datetime.now() - start_time).total_seconds()

    # 실제 데이터가 있는 종목만 스캔 (캐시와 scan_tickers가 다를 수 있음)
    available_tickers = [t for t in scan_tickers if t in data] or list(data.keys())

    # Entry 판정 (Growth v2.2 통일 적용)
    buy_1st = []
    buy_2nd = []
    buy_3rd = []
    watch_signals = []

    # [v5.3] 거래량 면제 재판정용 history 로드
    history = _load_scanner_history(project_dir, "sp100")

    for ticker in available_tickers:
        d = data.get(ticker)
        if not d or "error" in d:
            continue

        # v5.1: Exit 체크 — Exit 시그널이면 Entry 스캔 제외
        if check_exit_simple(ticker, d):
            continue

        signal, conditions = _check_entry_growth(d)

        # [v5.3] 전일 BUY였는데 오늘 BUY 미발동 → 거래량 면제 재판정
        if signal not in _BUY_SIGNALS and _had_prior_buy(ticker, history, today):
            retry_sig, retry_conds = _check_entry_growth(d, skip_volume=True)
            if retry_sig in _BUY_SIGNALS:
                signal, conditions = retry_sig, retry_conds

        if not signal:
            continue

        market_cap = d.get("market_cap", 0) or 0
        entry = {
            "ticker": ticker,
            "name": SP100_NAMES.get(ticker, ticker),
            "signal": signal,
            "price": d.get("price"),
            "change_pct": d.get("change_pct", 0),
            "rsi": d.get("rsi14"),
            "macd_hist": d.get("macd_hist"),
            "macd_hist_trend": d.get("macd_hist_trend"),
            "adx": d.get("adx"),
            "bb_pct": d.get("bb_pct"),
            "drawdown": d.get("drawdown_20d_pct"),
            "drawdown_52w": d.get("drawdown_52w_pct"),
            "volume_ratio": d.get("volume_ratio"),
            "market_cap": market_cap,
            "ma20": d.get("ma20"),
            "ma50": d.get("ma50"),
            "ma200": d.get("ma200"),
            "high_52w": d.get("high_52w"),
            "low_52w": d.get("low_52w"),
            "macd": d.get("macd"),
            "macd_signal": d.get("macd_signal"),
            "change_3d_pct": d.get("change_3d_pct"),
            "note": _make_note(conditions),
            "conditions": conditions,
            "judgment_sections": _build_entry_sections_growth(d),
        }

        if signal == "1st_BUY":
            buy_1st.append(entry)
        elif signal == "2nd_BUY":
            buy_2nd.append(entry)
        elif signal == "3rd_BUY":
            buy_3rd.append(entry)
        elif signal == "WATCH":
            watch_signals.append(entry)

    # 시가총액 내림차순 정렬 (시총 상위가 먼저)
    for lst in [buy_1st, buy_2nd, buy_3rd, watch_signals]:
        lst.sort(key=lambda x: -(x.get("market_cap") or 0))

    # v5.1b: BUY 연속일 계산
    for lst in [buy_1st, buy_2nd, buy_3rd]:
        _apply_streak_to_entries(lst, history, today)
    _update_scanner_history([buy_1st, buy_2nd, buy_3rd], "sp100", project_dir, history, today)

    result = {
        "status": "ok",
        "scan_date": today,
        "scan_time": datetime.now(_KST).strftime("%Y-%m-%d %H:%M"),
        "scanned": len(scan_tickers),
        "elapsed_sec": round(elapsed, 1),
        "buy_1st": buy_1st,
        "buy_2nd": buy_2nd,
        "buy_3rd": buy_3rd,
        "watch_signals": watch_signals,
        "total_signals": len(buy_1st) + len(buy_2nd) + len(buy_3rd) + len(watch_signals),
    }

    print(f"[Scanner] Complete: {result['total_signals']} signals found "
          f"(1st:{len(buy_1st)} 2nd:{len(buy_2nd)} 3rd:{len(buy_3rd)} watch:{len(watch_signals)})")

    return result


def _make_note(conditions: list) -> str:
    ok_items = [c[1] for c in conditions if c[0] == "ok"]
    return " + ".join(ok_items[:3]) if ok_items else ""


# ═══════════════════════════════════════════════════════
#  ETF Scanner — 섹터/테마 ETF 20개
# ═══════════════════════════════════════════════════════

ETF_TICKERS = [
    # 섹터 ETF (Select Sector SPDRs)
    "XLK",   # Technology
    "XLF",   # Financials
    "XLE",   # Energy
    "XLV",   # Health Care
    "XLI",   # Industrials
    "XLY",   # Consumer Discretionary
    "XLP",   # Consumer Staples
    "XLU",   # Utilities
    "XLRE",  # Real Estate
    "XLB",   # Materials
    "XLC",   # Communication Services
    # 테마 ETF
    "SOXX",  # Semiconductors
    "ARKK",  # Innovation
    "TAN",   # Solar
    "KWEB",  # China Internet
    "IWM",   # Russell 2000 (Small Cap)
    "EFA",   # International Developed
    "EEM",   # Emerging Markets
    "GLD",   # Gold
    "HYG",   # High Yield Bonds
]

ETF_NAMES = {
    "XLK": "Technology Select", "XLF": "Financial Select", "XLE": "Energy Select",
    "XLV": "Health Care Select", "XLI": "Industrial Select", "XLY": "Consumer Disc.",
    "XLP": "Consumer Staples", "XLU": "Utilities Select", "XLRE": "Real Estate Select",
    "XLB": "Materials Select", "XLC": "Communication Svc",
    "SOXX": "Semiconductors", "ARKK": "ARK Innovation", "TAN": "Solar",
    "KWEB": "China Internet", "IWM": "Russell 2000", "EFA": "Intl Developed",
    "EEM": "Emerging Markets", "GLD": "Gold", "HYG": "High Yield Bond",
}


def scan_etf(project_dir: str) -> dict:
    """
    섹터/테마 ETF 스캔. ETF v2.4 규칙 적용.
    """
    today = date.today().strftime("%Y-%m-%d")
    scan_tickers = ETF_TICKERS[:]

    print(f"[ETF Scanner] Scanning {len(scan_tickers)} ETFs...")
    start_time = datetime.now()

    # 데이터 수집 (당일 캐시 있으면 재사용)
    cache_name = "scanner_etf"
    etf_cache = os.path.join(project_dir, "screenshots", f"{cache_name}_{today}.json")
    market_data = {}
    if os.path.exists(etf_cache):
        try:
            with open(etf_cache, "rb") as f:
                raw = f.read()
            market_data = json.loads(raw.rstrip(b" \t\n\r\x00").decode("utf-8"))
        except Exception:
            market_data = {}
    if market_data.get("data"):
        print(f"[ETF Scanner] Using cached data: {etf_cache}")
    else:
        market_data = _fetch_scanner_data(project_dir, scan_tickers, cache_name)
        if "error" in market_data:
            return {"status": "error", "error": market_data["error"]}

    data = market_data.get("data", {})
    elapsed = (datetime.now() - start_time).total_seconds()

    # ETF v2.4 Entry 판정
    available_etfs = [t for t in scan_tickers if t in data] or list(data.keys())

    buy_1st = []
    buy_2nd = []
    buy_3rd = []
    watch_signals = []

    for ticker in available_etfs:
        d = data.get(ticker)
        if not d or "error" in d:
            continue

        # v5.1: Exit 체크 — Exit 시그널이면 Entry 스캔 제외
        if check_exit_simple(ticker, d):
            continue

        signal, conditions = _check_entry_etf(d)
        if not signal:
            continue

        market_cap = d.get("market_cap", 0) or 0
        entry = {
            "ticker": ticker,
            "name": ETF_NAMES.get(ticker, ticker),
            "signal": signal,
            "price": d.get("price"),
            "change_pct": d.get("change_pct", 0),
            "rsi": d.get("rsi14"),
            "macd_hist": d.get("macd_hist"),
            "macd_hist_trend": d.get("macd_hist_trend"),
            "adx": d.get("adx"),
            "bb_pct": d.get("bb_pct"),
            "drawdown": d.get("drawdown_20d_pct"),
            "drawdown_52w": d.get("drawdown_52w_pct"),
            "volume_ratio": d.get("volume_ratio"),
            "market_cap": market_cap,
            "ma20": d.get("ma20"),
            "ma50": d.get("ma50"),
            "ma200": d.get("ma200"),
            "high_52w": d.get("high_52w"),
            "low_52w": d.get("low_52w"),
            "macd": d.get("macd"),
            "macd_signal": d.get("macd_signal"),
            "change_3d_pct": d.get("change_3d_pct"),
            "note": _make_note(conditions),
            "conditions": conditions,
            "judgment_sections": _build_entry_sections_etf(d),
        }

        if signal == "1st_BUY":
            buy_1st.append(entry)
        elif signal == "2nd_BUY":
            buy_2nd.append(entry)
        elif signal == "3rd_BUY":
            buy_3rd.append(entry)
        elif signal == "WATCH":
            watch_signals.append(entry)

    # 시가총액 내림차순 정렬
    for lst in [buy_1st, buy_2nd, buy_3rd, watch_signals]:
        lst.sort(key=lambda x: -(x.get("market_cap") or 0))

    # v5.1b: BUY 연속일 계산
    prev_hist_etf = _load_scanner_history(project_dir, "etf")
    for lst in [buy_1st, buy_2nd, buy_3rd]:
        _apply_streak_to_entries(lst, prev_hist_etf, today)
    _update_scanner_history([buy_1st, buy_2nd, buy_3rd], "etf", project_dir, prev_hist_etf, today)

    result = {
        "status": "ok",
        "scan_date": today,
        "scan_time": datetime.now(_KST).strftime("%Y-%m-%d %H:%M"),
        "scanned": len(scan_tickers),
        "elapsed_sec": round(elapsed, 1),
        "buy_1st": buy_1st,
        "buy_2nd": buy_2nd,
        "buy_3rd": buy_3rd,
        "watch_signals": watch_signals,
        "total_signals": len(buy_1st) + len(buy_2nd) + len(buy_3rd) + len(watch_signals),
    }

    print(f"[ETF Scanner] Complete: {result['total_signals']} signals "
          f"(1st:{len(buy_1st)} 2nd:{len(buy_2nd)} 3rd:{len(buy_3rd)} watch:{len(watch_signals)})")

    return result


# ═══════════════════════════════════════════════════════
#  KOSPI Scanner — 코스피 시총 상위 100종목
# ═══════════════════════════════════════════════════════

KOSPI_TICKERS = [
    # 반도체/IT
    "005930.KS",  # 삼성전자
    "000660.KS",  # SK하이닉스
    "009150.KS",  # 삼성전기
    "018260.KS",  # 삼성SDS
    "066570.KS",  # LG전자
    "017670.KS",  # SK텔레콤
    "030200.KS",  # KT
    "035420.KS",  # NAVER
    "035720.KS",  # 카카오
    "036570.KS",  # 엔씨소프트
    "251270.KS",  # 넷마블
    "083790.KS",  # 크래프톤
    # 배터리/에너지
    "373220.KS",  # LG에너지솔루션
    "006400.KS",  # 삼성SDI
    "051910.KS",  # LG화학
    "096770.KS",  # SK이노베이션
    "009830.KS",  # 한화솔루션
    "112610.KS",  # 씨에스윈드
    "241560.KS",  # 두산퓨얼셀
    # 자동차
    "005380.KS",  # 현대자동차
    "000270.KS",  # 기아
    "012330.KS",  # 현대모비스
    "018880.KS",  # 한온시스템
    "064350.KS",  # 현대로템
    # 철강/소재
    "005490.KS",  # POSCO홀딩스
    "004020.KS",  # 현대제철
    "010130.KS",  # 고려아연
    "002380.KS",  # KCC
    "011170.KS",  # 롯데케미칼
    "298040.KS",  # 효성티앤씨
    "004800.KS",  # 효성
    "006260.KS",  # LS Corp
    # 금융
    "105560.KS",  # KB금융
    "055550.KS",  # 신한지주
    "086790.KS",  # 하나금융지주
    "316140.KS",  # 우리금융지주
    "032830.KS",  # 삼성생명
    "000810.KS",  # 삼성화재
    "088350.KS",  # 한화생명
    "005940.KS",  # NH투자증권
    "006800.KS",  # 미래에셋증권
    "071050.KS",  # 한국금융지주
    "024110.KS",  # 기업은행
    # 바이오/제약
    "207940.KS",  # 삼성바이오로직스
    "068270.KS",  # 셀트리온
    "068760.KS",  # 셀트리온제약
    "128940.KS",  # 한미약품
    "000100.KS",  # 유한양행
    "326030.KS",  # SK바이오사이언스
    "140490.KS",  # 휴젤
    "069620.KS",  # 대웅제약
    "096530.KS",  # 씨젠
    # 건설/조선/중공업
    "000720.KS",  # 현대건설
    "034020.KS",  # 두산에너빌리티
    "329180.KS",  # 한국조선해양
    "010620.KS",  # 현대미포조선
    "042660.KS",  # 한화오션
    "010140.KS",  # 삼성중공업
    "047810.KS",  # 한국항공우주
    "006360.KS",  # GS건설
    "000150.KS",  # 두산
    "042670.KS",  # 두산밥캣
    # 유통/소비재/식품
    "139480.KS",  # 이마트
    "023530.KS",  # 롯데쇼핑
    "027410.KS",  # BGF리테일
    "007070.KS",  # GS리테일
    "097950.KS",  # CJ제일제당
    "271560.KS",  # 오리온
    "000080.KS",  # 하이트진로
    "033780.KS",  # KT&G
    "007310.KS",  # 오뚜기
    "009240.KS",  # 한샘
    "000120.KS",  # CJ대한통운
    # 지주/복합기업
    "003550.KS",  # LG
    "034730.KS",  # SK
    "028260.KS",  # 삼성물산
    "001040.KS",  # CJ
    "078930.KS",  # GS
    "004990.KS",  # 롯데지주
    "090430.KS",  # 아모레퍼시픽
    "002790.KS",  # 아모레G
    "021240.KS",  # 코웨이
    "030000.KS",  # 제일기획
    "035250.KS",  # 강원랜드
    "010060.KS",  # OCI홀딩스
    # 에너지/유틸리티/운송
    "010950.KS",  # S-Oil
    "015760.KS",  # 한국전력
    "003490.KS",  # 대한항공
    "011200.KS",  # HMM
    "047050.KS",  # 포스코인터내셔널
]

KOSPI_NAMES = {
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "009150.KS": "삼성전기",
    "018260.KS": "삼성SDS", "066570.KS": "LG전자", "017670.KS": "SK텔레콤",
    "030200.KS": "KT", "035420.KS": "NAVER", "035720.KS": "카카오",
    "036570.KS": "엔씨소프트", "251270.KS": "넷마블", "083790.KS": "크래프톤",
    "373220.KS": "LG에너지솔루션", "006400.KS": "삼성SDI", "051910.KS": "LG화학",
    "096770.KS": "SK이노베이션", "009830.KS": "한화솔루션", "112610.KS": "씨에스윈드",
    "241560.KS": "두산퓨얼셀", "005380.KS": "현대자동차", "000270.KS": "기아",
    "012330.KS": "현대모비스", "018880.KS": "한온시스템", "064350.KS": "현대로템",
    "005490.KS": "POSCO홀딩스", "004020.KS": "현대제철", "010130.KS": "고려아연",
    "002380.KS": "KCC", "011170.KS": "롯데케미칼", "298040.KS": "효성티앤씨",
    "004800.KS": "효성", "006260.KS": "LS Corp", "105560.KS": "KB금융",
    "055550.KS": "신한지주", "086790.KS": "하나금융지주", "316140.KS": "우리금융지주",
    "032830.KS": "삼성생명", "000810.KS": "삼성화재", "088350.KS": "한화생명",
    "005940.KS": "NH투자증권", "006800.KS": "미래에셋증권", "071050.KS": "한국금융지주",
    "024110.KS": "기업은행", "207940.KS": "삼성바이오로직스", "068270.KS": "셀트리온",
    "068760.KS": "셀트리온제약", "128940.KS": "한미약품", "000100.KS": "유한양행",
    "326030.KS": "SK바이오사이언스", "140490.KS": "휴젤", "069620.KS": "대웅제약",
    "096530.KS": "씨젠", "000720.KS": "현대건설", "034020.KS": "두산에너빌리티",
    "329180.KS": "한국조선해양", "010620.KS": "현대미포조선", "042660.KS": "한화오션",
    "010140.KS": "삼성중공업", "047810.KS": "한국항공우주", "006360.KS": "GS건설",
    "000150.KS": "두산", "042670.KS": "두산밥캣", "139480.KS": "이마트",
    "023530.KS": "롯데쇼핑", "027410.KS": "BGF리테일", "007070.KS": "GS리테일",
    "097950.KS": "CJ제일제당", "271560.KS": "오리온", "000080.KS": "하이트진로",
    "033780.KS": "KT&G", "007310.KS": "오뚜기", "009240.KS": "한샘",
    "000120.KS": "CJ대한통운", "003550.KS": "LG", "034730.KS": "SK",
    "028260.KS": "삼성물산", "001040.KS": "CJ", "078930.KS": "GS",
    "004990.KS": "롯데지주", "090430.KS": "아모레퍼시픽", "002790.KS": "아모레G",
    "021240.KS": "코웨이", "030000.KS": "제일기획", "035250.KS": "강원랜드",
    "010060.KS": "OCI홀딩스", "010950.KS": "S-Oil", "015760.KS": "한국전력",
    "003490.KS": "대한항공", "011200.KS": "HMM", "047050.KS": "포스코인터내셔널",
}


def _krw_mcap(v: float) -> str:
    """KRW 시가총액 포맷 (조/억 단위)"""
    if not v:
        return ""
    if v >= 1e12:
        return f"{v/1e12:.1f}조"
    if v >= 1e8:
        return f"{v/1e8:.0f}억"
    return f"{v:,.0f}원"


def scan_kospi(project_dir: str) -> dict:
    """
    코스피 시총 상위 100종목 스캔. Growth v2.2 Entry 규칙 통일 적용.
    가격/시총은 KRW 기준.
    """
    today = date.today().strftime("%Y-%m-%d")
    scan_tickers = KOSPI_TICKERS[:]

    print(f"[KOSPI Scanner] Scanning {len(scan_tickers)} tickers...")
    start_time = datetime.now()

    cache_name = "scanner_kospi"
    cache_path = os.path.join(project_dir, "screenshots", f"{cache_name}_{today}.json")

    market_data = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "rb") as f:
                raw = f.read()
            market_data = json.loads(raw.rstrip(b" \t\n\r\x00").decode("utf-8"))
        except Exception:
            market_data = {}
    if market_data.get("data"):
        print(f"[KOSPI Scanner] Using cached data: {cache_path}")
    else:
        print(f"[KOSPI Scanner] Fetching data for {len(scan_tickers)} tickers...")
        market_data = _fetch_scanner_data(project_dir, scan_tickers, cache_name)
        if "error" in market_data:
            return {"status": "error", "error": market_data["error"]}

    data = market_data.get("data", {})
    elapsed = (datetime.now() - start_time).total_seconds()

    available_tickers = [t for t in scan_tickers if t in data] or list(data.keys())

    buy_1st = []
    buy_2nd = []
    buy_3rd = []
    watch_signals = []

    # [v5.3] 거래량 면제 재판정용 history 로드
    kospi_history = _load_scanner_history(project_dir, "kospi")

    for ticker in available_tickers:
        d = data.get(ticker)
        if not d or "error" in d:
            continue

        # v5.1b: Exit 체크 — Exit 시그널이면 Entry 스캔 제외
        if check_exit_simple(ticker, d):
            continue

        # 티커 표시명: .KS 제거 (history 조회에도 사용)
        display_ticker = ticker.replace(".KS", "")

        signal, conditions = _check_entry_growth(d)

        # [v5.3] 전일 BUY였는데 오늘 BUY 미발동 → 거래량 면제 재판정
        if signal not in _BUY_SIGNALS and _had_prior_buy(display_ticker, kospi_history, today):
            retry_sig, retry_conds = _check_entry_growth(d, skip_volume=True)
            if retry_sig in _BUY_SIGNALS:
                signal, conditions = retry_sig, retry_conds

        if not signal:
            continue

        market_cap = d.get("market_cap", 0) or 0
        entry = {
            "ticker": display_ticker,
            "ticker_full": ticker,
            "name": KOSPI_NAMES.get(ticker, display_ticker),
            "signal": signal,
            "price": d.get("price"),
            "change_pct": d.get("change_pct", 0),
            "rsi": d.get("rsi14"),
            "macd_hist": d.get("macd_hist"),
            "macd_hist_trend": d.get("macd_hist_trend"),
            "adx": d.get("adx"),
            "bb_pct": d.get("bb_pct"),
            "drawdown": d.get("drawdown_20d_pct"),
            "drawdown_52w": d.get("drawdown_52w_pct"),
            "volume_ratio": d.get("volume_ratio"),
            "market_cap": market_cap,
            "market_cap_fmt": _krw_mcap(market_cap),
            "ma20": d.get("ma20"),
            "ma50": d.get("ma50"),
            "ma200": d.get("ma200"),
            "high_52w": d.get("high_52w"),
            "low_52w": d.get("low_52w"),
            "macd": d.get("macd"),
            "macd_signal": d.get("macd_signal"),
            "change_3d_pct": d.get("change_3d_pct"),
            "note": _make_note(conditions),
            "conditions": conditions,
            "judgment_sections": _build_entry_sections_growth(d),
            "currency": "KRW",
        }

        if signal == "1st_BUY":
            buy_1st.append(entry)
        elif signal == "2nd_BUY":
            buy_2nd.append(entry)
        elif signal == "3rd_BUY":
            buy_3rd.append(entry)
        elif signal == "WATCH":
            watch_signals.append(entry)

    for lst in [buy_1st, buy_2nd, buy_3rd, watch_signals]:
        lst.sort(key=lambda x: -(x.get("market_cap") or 0))

    # v5.1b: BUY 연속일 계산
    for lst in [buy_1st, buy_2nd, buy_3rd]:
        _apply_streak_to_entries(lst, kospi_history, today)
    _update_scanner_history([buy_1st, buy_2nd, buy_3rd], "kospi", project_dir, kospi_history, today)

    result = {
        "status": "ok",
        "scan_date": today,
        "scan_time": datetime.now(_KST).strftime("%Y-%m-%d %H:%M"),
        "scanned": len(scan_tickers),
        "elapsed_sec": round(elapsed, 1),
        "buy_1st": buy_1st,
        "buy_2nd": buy_2nd,
        "buy_3rd": buy_3rd,
        "watch_signals": watch_signals,
        "total_signals": len(buy_1st) + len(buy_2nd) + len(buy_3rd) + len(watch_signals),
    }

    print(f"[KOSPI Scanner] Complete: {result['total_signals']} signals "
          f"(1st:{len(buy_1st)} 2nd:{len(buy_2nd)} 3rd:{len(buy_3rd)} watch:{len(watch_signals)})")

    return result


# ── CLI 테스트 ──────────────────────────────────────────
if __name__ == "__main__":
    project_dir = os.path.dirname(os.path.abspath(__file__))
    result = scan_sp100(project_dir)
    if result.get("status") == "ok":
        print(f"\n=== Scan Results ({result['scan_date']}) ===")
        print(f"Scanned: {result['scanned']} | Signals: {result['total_signals']}")
        for label, key in [("1st BUY", "buy_1st"), ("2nd BUY", "buy_2nd"), ("3rd BUY", "buy_3rd"), ("WATCH", "watch_signals")]:
            items = result[key]
            if items:
                print(f"\n--- {label} ({len(items)}) ---")
                for e in items:
                    print(f"  {e['ticker']:<6} ${e['price']:>8.2f}  RSI:{e['rsi']:.1f}  {e['note'][:50]}")
    else:
        print(f"ERROR: {result.get('error')}")
