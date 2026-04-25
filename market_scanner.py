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

import yfinance as yf
import pandas as pd

_KST = timezone(timedelta(hours=9))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from signal_judge import (
    _check_entry_growth, _check_entry_etf, check_exit_simple, _BUY_SIGNALS,
    _build_entry_sections_growth, _build_entry_sections_etf, judge_all,
)
from portfolio_data import TICKER_META

# ── 미국 대형주 스캐너 — S&P 100 + NASDAQ 100 합집합 (~169종목) ─────
# 변수명은 호환성을 위해 SP100_TICKERS를 유지 (외부 호출부 영향 없음).
SP100_TICKERS = [
    "AAPL", "ABBV", "ABNB", "ABT", "ACN", "ADBE", "ADI", "ADP", "ADSK", "AEP",
    "AIG", "ALNY", "AMAT", "AMD", "AMGN", "AMZN", "APP", "ARM", "ASML", "AVGO",
    "AXON", "AXP", "BA", "BAC", "BK", "BKNG", "BKR", "BLK", "BMY", "BRK-B",
    "C", "CAT", "CCEP", "CDNS", "CEG", "CHTR", "CL", "CMCSA", "COF", "COP",
    "COST", "CPRT", "CRM", "CRWD", "CSCO", "CSGP", "CSX", "CTAS", "CTSH", "CVS",
    "CVX", "DASH", "DDOG", "DE", "DHR", "DIS", "DOW", "DUK", "DXCM", "EA",
    "EMR", "EXC", "F", "FANG", "FAST", "FDX", "FER", "FTNT", "GD", "GE",
    "GEHC", "GILD", "GM", "GOOG", "GOOGL", "GS", "HD", "HON", "IBM", "IDXX",
    "INSM", "INTC", "INTU", "ISRG", "JNJ", "JPM", "KDP", "KHC", "KLAC", "KO",
    "LIN", "LLY", "LMT", "LOW", "LRCX", "MA", "MAR", "MCD", "MCHP", "MDLZ",
    "MDT", "MELI", "MET", "META", "MMM", "MNST", "MO", "MPWR", "MRK", "MRVL",
    "MS", "MSFT", "MSTR", "MU", "NEE", "NFLX", "NKE", "NVDA", "NXPI", "ODFL",
    "ORCL", "ORLY", "PANW", "PAYX", "PCAR", "PDD", "PEP", "PFE", "PG", "PLTR",
    "PM", "PYPL", "QCOM", "REGN", "ROP", "ROST", "RTX", "SBUX", "SCHW", "SHOP",
    "SNDK", "SNPS", "SO", "SPG", "STX", "T", "TGT", "TMO", "TMUS", "TRI",
    "TSLA", "TTWO", "TXN", "UNH", "UNP", "UPS", "USB", "V", "VRSK", "VRTX",
    "VZ", "WBD", "WDAY", "WDC", "WFC", "WMT", "XEL", "XOM", "ZS",
]

# 종목 이름 (스캐너 표시용)
SP100_NAMES = {
    # ── S&P 100 ─────
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
    # ── NASDAQ 100 전용 추가 ─────
    "ABNB": "Airbnb", "ADI": "Analog Devices", "ADP": "ADP", "ADSK": "Autodesk",
    "AEP": "American Electric Power", "ALNY": "Alnylam", "AMAT": "Applied Materials",
    "APP": "AppLovin", "ARM": "Arm Holdings", "ASML": "ASML", "AXON": "Axon",
    "BKR": "Baker Hughes", "CCEP": "Coca-Cola Europacific", "CDNS": "Cadence",
    "CEG": "Constellation Energy", "CPRT": "Copart", "CRWD": "CrowdStrike",
    "CSGP": "CoStar Group", "CSX": "CSX", "CTAS": "Cintas", "CTSH": "Cognizant",
    "DASH": "DoorDash", "DDOG": "Datadog", "DXCM": "DexCom", "EA": "Electronic Arts",
    "FANG": "Diamondback Energy", "FAST": "Fastenal", "FER": "Ferrovial",
    "FTNT": "Fortinet", "GEHC": "GE HealthCare", "IDXX": "IDEXX Labs",
    "INSM": "Insmed", "ISRG": "Intuitive Surgical", "KDP": "Keurig Dr Pepper",
    "KLAC": "KLA Corp", "LRCX": "Lam Research", "MAR": "Marriott",
    "MCHP": "Microchip", "MELI": "MercadoLibre", "MNST": "Monster Beverage",
    "MPWR": "Monolithic Power", "MRVL": "Marvell", "MSTR": "MicroStrategy",
    "MU": "Micron", "NXPI": "NXP Semi", "ODFL": "Old Dominion Freight",
    "ORLY": "O'Reilly Auto", "PANW": "Palo Alto Networks", "PAYX": "Paychex",
    "PCAR": "PACCAR", "PDD": "PDD Holdings", "PLTR": "Palantir",
    "REGN": "Regeneron", "ROP": "Roper", "ROST": "Ross Stores",
    "SHOP": "Shopify", "SNDK": "SanDisk", "SNPS": "Synopsys", "STX": "Seagate",
    "TRI": "Thomson Reuters", "TTWO": "Take-Two", "VRSK": "Verisk",
    "VRTX": "Vertex Pharma", "WBD": "Warner Bros Discovery", "WDAY": "Workday",
    "WDC": "Western Digital", "XEL": "Xcel Energy", "ZS": "Zscaler",
}

# 종목 GICS 섹터 분류 (한국어 약어, 11개 섹터)
# Tech=정보기술, Comm=커뮤니케이션, 경기소비=Consumer Discretionary,
# 필수소비=Consumer Staples, 헬스케어=Health Care, 금융=Financials,
# 산업=Industrials, 에너지=Energy, 유틸=Utilities, 부동산=Real Estate, 소재=Materials
TICKER_SECTORS = {
    # ── Tech (정보기술) ─────
    "AAPL": "Tech", "ACN": "Tech", "ADBE": "Tech", "ADI": "Tech",
    "ADP": "Tech", "ADSK": "Tech", "AMAT": "Tech", "AMD": "Tech",
    "APP": "Tech", "ARM": "Tech", "ASML": "Tech", "AVGO": "Tech",
    "CDNS": "Tech", "CRM": "Tech", "CRWD": "Tech", "CSCO": "Tech",
    "CTSH": "Tech", "DDOG": "Tech", "FTNT": "Tech", "IBM": "Tech",
    "INTC": "Tech", "INTU": "Tech", "KLAC": "Tech", "LRCX": "Tech",
    "MCHP": "Tech", "MPWR": "Tech", "MSFT": "Tech", "MSTR": "Tech",
    "MRVL": "Tech", "MU": "Tech", "NVDA": "Tech", "NXPI": "Tech",
    "ORCL": "Tech", "PANW": "Tech", "PAYX": "Tech", "PLTR": "Tech",
    "QCOM": "Tech", "ROP": "Tech", "SNPS": "Tech", "STX": "Tech",
    "SNDK": "Tech", "TXN": "Tech", "WDAY": "Tech", "WDC": "Tech",
    "ZS": "Tech",
    # ── Comm (커뮤니케이션) ─────
    "CHTR": "Comm", "CMCSA": "Comm", "DIS": "Comm", "EA": "Comm",
    "GOOG": "Comm", "GOOGL": "Comm", "META": "Comm", "NFLX": "Comm",
    "T": "Comm", "TMUS": "Comm", "TTWO": "Comm", "VZ": "Comm",
    "WBD": "Comm",
    # ── 경기소비 (Consumer Discretionary) ─────
    "ABNB": "경기소비", "AMZN": "경기소비", "BKNG": "경기소비",
    "DASH": "경기소비", "F": "경기소비", "GM": "경기소비",
    "HD": "경기소비", "LOW": "경기소비", "MAR": "경기소비",
    "MCD": "경기소비", "MELI": "경기소비", "NKE": "경기소비",
    "ORLY": "경기소비", "PDD": "경기소비", "ROST": "경기소비",
    "SBUX": "경기소비", "SHOP": "경기소비", "TGT": "경기소비",
    "TSLA": "경기소비",
    # ── 필수소비 (Consumer Staples) ─────
    "CCEP": "필수소비", "CL": "필수소비", "COST": "필수소비",
    "KDP": "필수소비", "KHC": "필수소비", "KO": "필수소비",
    "MDLZ": "필수소비", "MNST": "필수소비", "MO": "필수소비",
    "PEP": "필수소비", "PG": "필수소비", "PM": "필수소비",
    "WMT": "필수소비",
    # ── 헬스케어 (Health Care) ─────
    "ABBV": "헬스케어", "ABT": "헬스케어", "ALNY": "헬스케어",
    "AMGN": "헬스케어", "BMY": "헬스케어", "CVS": "헬스케어",
    "DHR": "헬스케어", "DXCM": "헬스케어", "GEHC": "헬스케어",
    "GILD": "헬스케어", "IDXX": "헬스케어", "INSM": "헬스케어",
    "ISRG": "헬스케어", "JNJ": "헬스케어", "LLY": "헬스케어",
    "MDT": "헬스케어", "MRK": "헬스케어", "PFE": "헬스케어",
    "REGN": "헬스케어", "TMO": "헬스케어", "UNH": "헬스케어",
    "VRTX": "헬스케어",
    # ── 금융 (Financials) — V/MA/PYPL은 GICS 2023.3 재분류로 Financials ─────
    "AIG": "금융", "AXP": "금융", "BAC": "금융", "BK": "금융",
    "BLK": "금융", "BRK-B": "금융", "C": "금융", "COF": "금융",
    "GS": "금융", "JPM": "금융", "MA": "금융", "MET": "금융",
    "MS": "금융", "PYPL": "금융", "SCHW": "금융", "TRI": "금융",
    "USB": "금융", "V": "금융", "WFC": "금융",
    # ── 산업 (Industrials) ─────
    "AXON": "산업", "BA": "산업", "CAT": "산업", "CPRT": "산업",
    "CSX": "산업", "CTAS": "산업", "DE": "산업", "EMR": "산업",
    "FAST": "산업", "FDX": "산업", "FER": "산업", "GD": "산업",
    "GE": "산업", "HON": "산업", "LMT": "산업", "MMM": "산업",
    "ODFL": "산업", "PCAR": "산업", "RTX": "산업", "UNP": "산업",
    "UPS": "산업", "VRSK": "산업",
    # ── 에너지 (Energy) ─────
    "BKR": "에너지", "COP": "에너지", "CVX": "에너지",
    "FANG": "에너지", "XOM": "에너지",
    # ── 유틸 (Utilities) ─────
    "AEP": "유틸", "CEG": "유틸", "DUK": "유틸", "EXC": "유틸",
    "NEE": "유틸", "SO": "유틸", "XEL": "유틸",
    # ── 부동산 (Real Estate) ─────
    "CSGP": "부동산", "SPG": "부동산",
    # ── 소재 (Materials) ─────
    "DOW": "소재", "LIN": "소재",
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


def _extract_close(df, ticker: str, date_str: str, num_tickers: int):
    """yfinance DataFrame에서 특정 티커/날짜의 종가 추출."""
    try:
        dt = pd.Timestamp(date_str)
        if num_tickers == 1:
            if dt in df.index:
                return float(df.loc[dt, "Close"])
        else:
            if dt in df.index:
                val = df.loc[dt, ("Close", ticker)]
                if pd.notna(val):
                    return float(val)
        # 정확한 날짜 없으면 (주말/휴일) 이전 거래일 종가 사용
        prior = df[:dt]
        if not prior.empty:
            if num_tickers == 1:
                return float(prior["Close"].iloc[-1])
            else:
                val = prior[("Close", ticker)].dropna()
                if not val.empty:
                    return float(val.iloc[-1])
    except Exception:
        pass
    return None


def _backfill_missing_prices(history: dict, today_str: str = ""):
    """히스토리에서 과거 날짜의 price를 yfinance 실제 종가로 교정.

    장중 실행 시 현재가가 저장되므로, 오늘이 아닌 모든 과거 항목의
    가격을 실제 종가로 덮어쓴다.
    """
    missing = {}  # {ticker: [date1, date2, ...]}
    for dt, day_data in history.items():
        if dt == today_str:
            continue
        for ticker, info in day_data.items():
            # 과거 날짜는 모두 yfinance 종가로 교정 (장중가 → 종가)
            missing.setdefault(ticker, []).append(dt)

    if not missing:
        return

    all_dates = sorted(set(d for dates in missing.values() for d in dates))
    # 주말/공휴일 대비 시작일을 10일 앞으로 (이전 거래일 확보)
    start_date = (datetime.strptime(all_dates[0], "%Y-%m-%d") - timedelta(days=10)).strftime("%Y-%m-%d")
    end_date = (datetime.strptime(all_dates[-1], "%Y-%m-%d") + timedelta(days=5)).strftime("%Y-%m-%d")

    tickers_list = list(missing.keys())
    # KOSPI 종목은 .KS 접미사 필요
    yf_map = {}
    for t in tickers_list:
        if t.isdigit() and len(t) == 6:
            yf_map[t] = f"{t}.KS"
        else:
            yf_map[t] = t
    yf_tickers = list(yf_map.values())

    print(f"  [Backfill] yfinance로 {len(yf_tickers)}개 티커 실제 종가 조회 ({start_date}~{all_dates[-1]})")
    try:
        df = yf.download(yf_tickers, start=start_date, end=end_date,
                         auto_adjust=True, progress=False)
        if df is None or df.empty:
            print("  [Backfill] yfinance 데이터 없음, 스킵")
            return
    except Exception as ex:
        print(f"  [Backfill] yfinance 오류: {ex}")
        return

    filled = 0
    for ticker, dates in missing.items():
        yf_ticker = yf_map[ticker]
        for dt in dates:
            close_price = _extract_close(df, yf_ticker, dt, len(yf_tickers))
            if close_price is not None:
                # KRW 종목은 정수로 반올림
                if ticker.isdigit() and len(ticker) == 6:
                    close_price = round(close_price)
                else:
                    close_price = round(close_price, 2)
                history[dt][ticker]["price"] = close_price
                filled += 1

    print(f"  [Backfill] {filled}/{sum(len(v) for v in missing.values())}건 실제 종가 백필 완료")


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
    # yfinance에서 실제 종가로 과거 히스토리 백필
    _backfill_missing_prices(history, today_str)

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

    # yfinance에서 실제 종가로 과거 히스토리 백필 후 저장
    _backfill_missing_prices(history, today_str)
    _save_scanner_history(project_dir, scanner_name, history)
    return history


def _load_portfolio_tickers(project_dir: str) -> set:
    """현재 보유 종목 리스트 로드 (스캐너에서 제외용)"""
    import re
    from portfolio_paths import primary_portfolio_path
    portfolio_path = primary_portfolio_path(project_dir)
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


def _load_shared_scanner_cache(project_dir: str) -> dict:
    """pipeline이 pre-fetch로 저장한 scanner_shared_{date}.json을 로드.

    4개 스캐너가 공통으로 사용하기 위한 통합 캐시. 존재하지 않으면 {} 반환.
    """
    today = date.today().strftime("%Y-%m-%d")
    shared_path = os.path.join(project_dir, "screenshots", f"scanner_shared_{today}.json")
    if not os.path.exists(shared_path):
        return {}
    try:
        with open(shared_path, "rb") as f:
            raw = f.read()
        return json.loads(raw.rstrip(b" \t\n\r\x00").decode("utf-8"))
    except Exception:
        return {}


def _filter_from_shared(shared: dict, tickers: list) -> dict:
    """shared 캐시에서 주어진 tickers만 추출한 새 dict 반환."""
    if not shared or not shared.get("data"):
        return {}
    data = shared.get("data", {})
    subset = {t: data[t] for t in tickers if t in data}
    if not subset:
        return {}
    return {
        "_meta": shared.get("_meta", {}),
        "_macro": shared.get("_macro", {}),
        "data": subset,
    }


def _fetch_scanner_data(project_dir: str, tickers: list, cache_name: str) -> dict:
    """종목 기술지표를 yfinance로 수집.

    최적화: pipeline이 먼저 scanner_shared_{date}.json 으로 4개 스캐너 전체 종목을
    한 번에 수집해두면, 여기서는 subprocess 호출 없이 해당 subset만 추출해 저장한다.
    shared 캐시가 없으면 기존 방식(개별 subprocess)으로 폴백.
    """
    today = date.today().strftime("%Y-%m-%d")
    output_path = os.path.join(project_dir, "screenshots", f"{cache_name}_{today}.json")

    # 1) shared 캐시 우선 시도 — 공통 pre-fetch 결과에서 subset 추출
    shared = _load_shared_scanner_cache(project_dir)
    subset = _filter_from_shared(shared, tickers) if shared else {}
    if subset:
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(subset, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return subset

    # 2) 폴백: 기존 subprocess 호출
    fetch_script = os.path.join(project_dir, "fetch_market_data.py")
    python_exe = sys.executable

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

    # 비거래일 판별
    _sp_meta = market_data.get("_meta", {})
    is_trading_day = _sp_meta.get("is_trading_day", True)
    data_date = _sp_meta.get("date", today)
    if not is_trading_day:
        today = data_date

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
    if is_trading_day:
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
        "total_signals": len(buy_1st) + len(buy_2nd) + len(buy_3rd),
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
    # 주요 섹터 ETF (10개, 노이즈 감소)
    "XLK",   # Technology
    "XLF",   # Financials
    "XLE",   # Energy
    "XLV",   # Health Care
    "XLI",   # Industrials
    "SOXX",  # Semiconductors
    "IWM",   # Russell 2000 (Small Cap)
    "EFA",   # International Developed
    "EEM",   # Emerging Markets
    "GLD",   # Gold
]

ETF_NAMES = {
    "XLK": "Technology Select", "XLF": "Financial Select", "XLE": "Energy Select",
    "XLV": "Health Care Select", "XLI": "Industrial Select",
    "SOXX": "Semiconductors", "IWM": "Russell 2000", "EFA": "Intl Developed",
    "EEM": "Emerging Markets", "GLD": "Gold",
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

    # 비거래일 판별
    _etf_meta = market_data.get("_meta", {})
    is_trading_day = _etf_meta.get("is_trading_day", True)
    data_date = _etf_meta.get("date", today)
    if not is_trading_day:
        today = data_date

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
    if is_trading_day:
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
        "total_signals": len(buy_1st) + len(buy_2nd) + len(buy_3rd),
    }

    print(f"[ETF Scanner] Complete: {result['total_signals']} signals "
          f"(1st:{len(buy_1st)} 2nd:{len(buy_2nd)} 3rd:{len(buy_3rd)} watch:{len(watch_signals)})")

    return result


# ═══════════════════════════════════════════════════════
#  KOSPI Scanner — 코스피 시총 상위 20종목 (초대형주 집중)
# ═══════════════════════════════════════════════════════

KOSPI_TICKERS = [
    # 반도체/IT
    "005930.KS",  # 삼성전자
    "000660.KS",  # SK하이닉스
    "035420.KS",  # NAVER
    "035720.KS",  # 카카오
    # 배터리/에너지
    "373220.KS",  # LG에너지솔루션
    "006400.KS",  # 삼성SDI
    "051910.KS",  # LG화학
    # 자동차
    "005380.KS",  # 현대자동차
    "000270.KS",  # 기아
    # 철강/소재
    "005490.KS",  # POSCO홀딩스
    # 금융
    "105560.KS",  # KB금융
    "055550.KS",  # 신한지주
    # 바이오/제약
    "207940.KS",  # 삼성바이오로직스
    "068270.KS",  # 셀트리온
    # 조선/방산
    "329180.KS",  # HD한국조선해양
    "042660.KS",  # 한화오션
    "047810.KS",  # 한국항공우주
    # 지주/복합기업
    "034730.KS",  # SK
    "028260.KS",  # 삼성물산
    # 유틸리티
    "015760.KS",  # 한국전력
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
    코스피 시총 상위 20종목 스캔. Growth v2.2 Entry 규칙 통일 적용.
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

    # 비거래일 판별
    _kospi_meta = market_data.get("_meta", {})
    is_trading_day = _kospi_meta.get("is_trading_day", True)
    data_date = _kospi_meta.get("date", today)
    if not is_trading_day:
        today = data_date

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
    if is_trading_day:
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
        "total_signals": len(buy_1st) + len(buy_2nd) + len(buy_3rd),
    }

    print(f"[KOSPI Scanner] Complete: {result['total_signals']} signals "
          f"(1st:{len(buy_1st)} 2nd:{len(buy_2nd)} 3rd:{len(buy_3rd)} watch:{len(watch_signals)})")

    return result


# ═══════════════════════════════════════════════════════
#  Watchlist Scanner — 사용자 관심종목 (보유 X, 진입 후보)
# ═══════════════════════════════════════════════════════
# v1: ticker 리스트 하드코딩으로 동작 검증 (Step 4에서 watchlist.md 외부화)
WATCHLIST_TICKERS = [
    "META",   # Meta Platforms — Growth 카테고리 예시
    "AMD",    # AMD
    "AVGO",   # Broadcom
    "XLK",    # Technology ETF 예시
    "COIN",   # Coinbase
]

WATCHLIST_NAMES = {
    "META": "Meta Platforms", "AMD": "AMD", "AVGO": "Broadcom",
    "XLK": "Technology Select", "COIN": "Coinbase",
}


def _pick_entry_checker(ticker: str):
    """
    관심종목 티커의 전략 그룹을 판별해 적절한 Entry 판정 함수를 선택.
    - STRATEGY_GROUP.etf → ETF 규칙
    - 그 외 → Growth 규칙 (기본)
    Value/Bond/Metal은 관심종목 맥락에서 모두 Growth로 취급(진입 타이밍 보기).
    """
    from portfolio_data import get_strategy_group
    group = get_strategy_group(ticker) or "growth"
    if group == "etf":
        return _check_entry_etf, _build_entry_sections_etf
    return _check_entry_growth, _build_entry_sections_growth


def scan_watchlist(project_dir: str, tickers: list | None = None) -> dict:
    """
    관심종목 스캔. 포트폴리오 종목과 동일하게 judge_all을 거쳐 전체 시그널
    (1st/2nd/3rd BUY, WATCH, HOLD, TAKE_PROFIT_1/2, TOP_SIGNAL, BOND_WATCH, CASH)을
    모두 반환. 와치리스트는 포트폴리오처럼 추적되는 의사결정 대상이라 Exit/Hold까지
    가시화해야 한다는 사용자 요구사항에 따라 Entry-only 모드에서 확장되었다.

    반환 키:
      buy_1st/buy_2nd/buy_3rd/watch_signals — 기존 Entry 섹션 (하위호환)
      all_signals — 전체 종목에 대한 풀 judge 결과 (signal 필드로 분류)
    """
    today = date.today().strftime("%Y-%m-%d")
    if tickers is not None:
        scan_tickers = list(tickers)
    else:
        try:
            from watchlist_store import load_tickers as _load_wl
            _loaded = _load_wl(project_dir)
        except Exception:
            _loaded = []
        scan_tickers = _loaded if _loaded else WATCHLIST_TICKERS[:]
    if not scan_tickers:
        return {"status": "ok", "scan_date": today, "scanned": 0,
                "buy_1st": [], "buy_2nd": [], "buy_3rd": [], "watch_signals": [],
                "all_signals": [], "total_signals": 0, "elapsed_sec": 0}

    print(f"[Watchlist Scanner] Scanning {len(scan_tickers)} tickers...")
    start_time = datetime.now()

    # 데이터 수집 (당일 캐시 공유)
    cache_name = "scanner_watchlist"
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
        print(f"[Watchlist Scanner] Using cached data: {cache_path}")
    else:
        market_data = _fetch_scanner_data(project_dir, scan_tickers, cache_name)
        if "error" in market_data:
            return {"status": "error", "error": market_data["error"]}

    data = market_data.get("data", {})
    elapsed = (datetime.now() - start_time).total_seconds()

    _meta = market_data.get("_meta", {})
    is_trading_day = _meta.get("is_trading_day", True)
    data_date = _meta.get("date", today)
    if not is_trading_day:
        today = data_date

    available = [t for t in scan_tickers if t in data] or list(data.keys())

    # 별도 히스토리(watchlist) 기준으로 full-judge 수행
    prev_hist = _load_scanner_history(project_dir, "watchlist")
    # judge_all은 market_data의 data/_macro/_meta를 소비한다. available 티커로 한정한
    # 서브 market_data를 구성해 watchlist 티커만 판정.
    _wl_data = {t: data[t] for t in available if t in data}
    _wl_market = {**market_data, "data": _wl_data}
    judgments = judge_all(_wl_market, prev_hist)

    buy_1st, buy_2nd, buy_3rd, watch_signals = [], [], [], []
    all_signals = []  # 모든 시그널(포트폴리오 스타일)

    for ticker in available:
        d = data.get(ticker)
        if not d or "error" in d:
            continue
        sig_result = judgments.get(ticker, {})
        signal = sig_result.get("signal", "HOLD")
        conditions = sig_result.get("conditions", [])

        # 판정 섹션은 Entry 체커 기준(디테일 페이지 재사용)
        _, sections_fn = _pick_entry_checker(ticker)

        market_cap = d.get("market_cap", 0) or 0
        entry = {
            "ticker": ticker,
            "name": WATCHLIST_NAMES.get(ticker, ticker),
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
            "note": sig_result.get("note") or _make_note(conditions),
            "conditions": conditions,
            "judgment_sections": sig_result.get("judgment_sections") or sections_fn(d),
            # BUY 스트릭/가상수익률 (judge_all이 채워줌)
            "buy_streak": sig_result.get("buy_streak", 0),
            "buy_confirmed": sig_result.get("buy_confirmed", False),
            "hypo_return": sig_result.get("hypo_return"),
        }

        # 기존 Entry 섹션 (하위호환)
        if signal == "1st_BUY":
            buy_1st.append(entry)
        elif signal == "2nd_BUY":
            buy_2nd.append(entry)
        elif signal == "3rd_BUY":
            buy_3rd.append(entry)
        elif signal == "WATCH":
            watch_signals.append(entry)

        # 전체 시그널 (포트폴리오 스타일 렌더용)
        all_signals.append(entry)

    # 시가총액 내림차순
    for lst in (buy_1st, buy_2nd, buy_3rd, watch_signals):
        lst.sort(key=lambda x: -(x.get("market_cap") or 0))

    # all_signals: 신호 우선순위 → 시총 내림차순
    _SIG_ORDER = {
        "TOP_SIGNAL": 0, "TAKE_PROFIT_2": 1, "TAKE_PROFIT_1": 2,
        "1st_BUY": 3, "2nd_BUY": 4, "3rd_BUY": 5,
        "WATCH": 6, "BOND_WATCH": 7, "CASH": 8, "HOLD": 9, "ERROR": 10,
    }
    all_signals.sort(key=lambda x: (_SIG_ORDER.get(x["signal"], 99), -(x.get("market_cap") or 0)))

    # 히스토리 업데이트: judge_all이 이미 BUY 스트릭을 계산했으므로 save_today를 사용
    if is_trading_day:
        try:
            from history_manager import save_today, prune_old, save_history
            history_path = os.path.join(project_dir, "history", "scanner_watchlist_history.json")
            new_hist = save_today(prev_hist, today, judgments, _wl_market, "watchlist")
            new_hist = prune_old(new_hist)
            save_history(new_hist, history_path)
        except Exception as _hse:
            print(f"  [Watchlist] history save warn: {_hse}")

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
        "all_signals": all_signals,
        "total_signals": len(buy_1st) + len(buy_2nd) + len(buy_3rd),
    }

    # 시그널 카운트 로그
    _sc = {}
    for e in all_signals:
        _sc[e["signal"]] = _sc.get(e["signal"], 0) + 1
    print(f"[Watchlist Scanner] Complete: {len(all_signals)} judged "
          f"(1st:{len(buy_1st)} 2nd:{len(buy_2nd)} 3rd:{len(buy_3rd)} watch:{len(watch_signals)}) "
          f"full={_sc}")

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
