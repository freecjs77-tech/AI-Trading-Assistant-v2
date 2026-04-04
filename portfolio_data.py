"""
portfolio_data.py — 종목 메타데이터 + 한글→Ticker 변환맵
AI Trading Assistant v3.0
"""

# ── 종목별 고정 메타데이터 ──────────────────────────────
TICKER_META = {
    "VOO":   {"name": "Vanguard S&P 500 ETF",           "cls": "ETF",    "cls_tag": "cls-etf"},
    "BIL":   {"name": "SPDR 1-3 Month T-Bill ETF",      "cls": "CASH",   "cls_tag": "cls-cash"},
    "QQQ":   {"name": "Invesco QQQ Trust ETF",           "cls": "ETF",    "cls_tag": "cls-etf"},
    "SCHD":  {"name": "Schwab US Dividend ETF",          "cls": "ETF",    "cls_tag": "cls-etf"},
    "AAPL":  {"name": "Apple Inc.",                      "cls": "Growth", "cls_tag": "cls-growth"},
    "O":     {"name": "Realty Income Corp",              "cls": "Value",  "cls_tag": "cls-value"},
    "JEPI":  {"name": "JPMorgan Equity Premium ETF",     "cls": "ETF",    "cls_tag": "cls-etf"},
    "SOXX":  {"name": "iShares Semiconductor ETF",       "cls": "ETF",    "cls_tag": "cls-etf"},
    "TSLA":  {"name": "Tesla Inc.",                      "cls": "Growth", "cls_tag": "cls-growth"},
    "TLT":   {"name": "iShares 20+ Year Treasury ETF",   "cls": "Bond",   "cls_tag": "cls-bond"},
    "NVDA":  {"name": "NVIDIA Corp.",                    "cls": "Growth", "cls_tag": "cls-growth"},
    "PLTR":  {"name": "Palantir Technologies",           "cls": "Growth", "cls_tag": "cls-growth"},
    "SPY":   {"name": "SPDR S&P 500 ETF",               "cls": "ETF",    "cls_tag": "cls-etf"},
    "UNH":   {"name": "UnitedHealth Group",              "cls": "Value",  "cls_tag": "cls-value"},
    "MSFT":  {"name": "Microsoft Corp.",                 "cls": "Growth", "cls_tag": "cls-growth"},
    "GOOGL": {"name": "Alphabet Inc. Class A",           "cls": "Growth", "cls_tag": "cls-growth"},
    "AMZN":  {"name": "Amazon.com Inc.",                 "cls": "Growth", "cls_tag": "cls-growth"},
    "SLV":   {"name": "iShares Silver Trust",            "cls": "Metal",  "cls_tag": "cls-metal"},
    # Speculative
    "QLD":   {"name": "ProShares Ultra QQQ",             "cls": "Speculative", "cls_tag": "cls-growth"},
    "SOXL":  {"name": "Direxion Semiconductor Bull 3X",  "cls": "Speculative", "cls_tag": "cls-growth"},
    "ETHU":  {"name": "ProShares Ultra Ether ETF",       "cls": "Speculative", "cls_tag": "cls-growth"},
    "CRCL":  {"name": "Circle Internet Group",           "cls": "Speculative", "cls_tag": "cls-growth"},
    "XLE":   {"name": "Energy Select Sector SPDR",       "cls": "ETF",    "cls_tag": "cls-etf"},
    "XLF":   {"name": "Financial Select Sector SPDR",    "cls": "ETF",    "cls_tag": "cls-etf"},
    "NKE":   {"name": "Nike Inc.",                       "cls": "Growth", "cls_tag": "cls-growth"},
    "BTDR":  {"name": "Bitdeer Technologies",            "cls": "Speculative", "cls_tag": "cls-growth"},
    # KOSPI 개별주식
    "110990": {"name": "디아이티",              "cls": "Growth", "cls_tag": "cls-growth"},
    "005930": {"name": "삼성전자",              "cls": "Growth", "cls_tag": "cls-growth"},
    "005380": {"name": "현대차",                "cls": "Value",  "cls_tag": "cls-value"},
    "000660": {"name": "SK하이닉스",            "cls": "Growth", "cls_tag": "cls-growth"},
    "006400": {"name": "삼성SDI",               "cls": "Growth", "cls_tag": "cls-growth"},
    "373220": {"name": "LG에너지솔루션",        "cls": "Growth", "cls_tag": "cls-growth"},
    # KOSPI ETF
    "102110": {"name": "TIGER 200",             "cls": "ETF",    "cls_tag": "cls-etf"},
    "458730": {"name": "TIGER 미국배당다우존스", "cls": "ETF",    "cls_tag": "cls-etf"},
    "379800": {"name": "KODEX 미국S&P500",      "cls": "ETF",    "cls_tag": "cls-etf"},
    "379810": {"name": "KODEX 미국나스닥100",    "cls": "ETF",    "cls_tag": "cls-etf"},
    "396500": {"name": "TIGER 반도체TOP10",     "cls": "ETF",    "cls_tag": "cls-etf"},
    "441640": {"name": "KODEX 주주환원고배당주", "cls": "ETF",    "cls_tag": "cls-etf"},
    "232080": {"name": "TIGER 코스닥150",       "cls": "ETF",    "cls_tag": "cls-etf"},
    "466920": {"name": "SOL 조선TOP3플러스",    "cls": "ETF",    "cls_tag": "cls-etf"},
}

# ── 한국어 종목명 → Ticker 변환맵 (스크린샷 OCR용) ──────
KR_TO_TICKER = {
    # Growth
    "테슬라": "TSLA",
    "엔비디아": "NVDA",
    "팔란티어 테크놀로지스": "PLTR",
    "팔란티어": "PLTR",
    "애플": "AAPL",
    "마이크로소프트": "MSFT",
    "알파벳 Class A": "GOOGL",
    "알파벳": "GOOGL",
    "아마존닷컴": "AMZN",
    "아마존": "AMZN",
    # Value
    "리얼티 인컴": "O",
    "유나이티드헬스 그룹": "UNH",
    "유나이티드헬스": "UNH",
    # ETF (한국어명)
    "Vanguard S&P 500 ETF": "VOO",
    "SPDR 1-3 Month 미국 국채 ETF": "BIL",
    "SPDR 1-3 Month 국채 ETF": "BIL",
    "Invesco QQQ Trust ETF": "QQQ",
    "SCHD": "SCHD",
    "JEPI": "JEPI",
    "iShares Semiconductor ETF": "SOXX",
    "iShares 반도체 ETF": "SOXX",
    "SPDR S&P 500(소수)": "SPY",
    "SPDR S&P 500": "SPY",
    "Schwab US Dividend ETF": "SCHD",
    "JPMorgan Equity Premium ETF": "JEPI",
    # Bond / Metal
    "iShares 20+ Year 국채 ETF": "TLT",
    "iShares 은 ETF": "SLV",
    # Speculative
    "ProShares QQQ 2배 ETF": "QLD",
    "Direxion 미국 반도체 3X ETF": "SOXL",
    "이더리움 2X ETF": "ETHU",
    "써클 인터넷 그룹": "CRCL",
    "SPDR 에너지 ETF": "XLE",
    "SPDR 금융 ETF": "XLF",
    "나이키": "NKE",
    "비트마인 이머전 테크놀로지스": "BTDR",
}

# ── 종목 카테고리 분류 (시그널 판정 전략 그룹) ───────────
STRATEGY_GROUP = {
    "growth": ["NVDA", "TSLA", "PLTR", "AAPL", "MSFT", "GOOGL", "AMZN", "NKE",
               "QLD", "SOXL", "ETHU", "CRCL", "BTDR",
               "110990", "005930", "000660", "006400", "373220"],
    "etf":    ["VOO", "QQQ", "SCHD", "SOXX", "JEPI", "SPY", "XLE", "XLF",
               "102110", "458730", "379800", "379810", "396500", "441640", "232080", "466920"],
    "value":  ["O", "UNH", "005380"],
    "bond":   ["TLT"],
    "metal":  ["SLV"],
    "cash":   ["BIL"],
}

def is_kospi_ticker(ticker: str) -> bool:
    """KOSPI 종목 여부 판별 (숫자 6자리)"""
    return ticker.isdigit() and len(ticker) == 6


# ── KOSPI 종목 추가 가이드 ──────────────────────────────
# 국내 종목을 portfolio.md에 추가할 때:
# 1. TICKER_META에 {"name": "...", "cls": "Growth", "cls_tag": "cls-growth"} 등록
# 2. STRATEGY_GROUP의 적절한 카테고리에 티커 추가
# 3. portfolio.md 하단 Ticker 목록에도 추가
# 예: "005930": {"name": "Samsung Electronics", "cls": "Growth", "cls_tag": "cls-growth"}


def get_strategy_group(ticker: str) -> str:
    """종목의 전략 그룹 반환"""
    for group, tickers in STRATEGY_GROUP.items():
        if ticker in tickers:
            return group
    return "growth"  # 알 수 없는 종목은 growth 기본


def get_ticker_name(ticker: str) -> str:
    """종목의 영문 풀네임 반환"""
    meta = TICKER_META.get(ticker)
    return meta["name"] if meta else ticker


def get_ticker_class(ticker: str) -> str:
    """종목의 클래스(ETF/Growth/Value 등) 반환"""
    meta = TICKER_META.get(ticker)
    return meta["cls"] if meta else "Unknown"


def get_cls_tag(ticker: str) -> str:
    """종목의 CSS 클래스 태그 반환"""
    meta = TICKER_META.get(ticker)
    return meta["cls_tag"] if meta else "cls-growth"


def resolve_korean_name(korean_name: str) -> str | None:
    """한국어 종목명을 영문 ticker로 변환. 매칭 실패 시 None"""
    # 정확 매칭
    if korean_name in KR_TO_TICKER:
        return KR_TO_TICKER[korean_name]
    # 부분 매칭 (한국어명이 포함된 경우)
    for kr, ticker in KR_TO_TICKER.items():
        if kr in korean_name or korean_name in kr:
            return ticker
    # 영문 ticker 그대로인 경우
    if korean_name.upper() in TICKER_META:
        return korean_name.upper()
    return None
