"""
report_generator.py — Jinja2 기반 HTML 리포트 생성
AI Trading Assistant v3.0

templates/report_template.html에 데이터를 주입하여 리포트 생성.
"""

import os
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

from portfolio_data import (
    TICKER_META, get_ticker_name, get_ticker_class, get_cls_tag,
    get_strategy_group, STRATEGY_GROUP, is_kospi_ticker,
)


# ── 요일 한국어 변환 ──────────────────────────────────
WEEKDAYS_KO = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]


def _date_ko(date_str: str) -> str:
    """YYYY-MM-DD → YYYY년 M월 D일 (요일)"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.year}년 {dt.month}월 {dt.day}일 ({WEEKDAYS_KO[dt.weekday()]})"
    except ValueError:
        return date_str


def _master_info(macro: dict, market_data: dict) -> dict:
    """Master switch 관련 정보 계산"""
    data = market_data.get("data", {})
    ms = macro.get("master_switch", "UNKNOWN")

    qqq = data.get("QQQ", {})
    spy = data.get("SPY", {})

    def _status(ticker_data):
        vs = ticker_data.get("price_vs_ma200", "N/A")
        if vs == "above":
            return "⬆️ Above"
        elif vs == "below":
            return "⬇️ Below"
        return "N/A"

    if ms == "RED":
        cls = ""
        icon = "🔴"
        label = f"{icon} MASTER SWITCH: RED"
    elif ms == "YELLOW":
        cls = "yellow"
        icon = "🟡"
        label = f"{icon} MASTER SWITCH: YELLOW"
    elif ms == "GREEN":
        cls = "green"
        icon = "🟢"
        label = f"{icon} MASTER SWITCH: GREEN"
    else:
        cls = ""
        icon = "⚪"
        label = f"{icon} MASTER SWITCH: {ms}"

    # QQQ/SPY 상세
    desc_parts = []
    if qqq:
        desc_parts.append(f"QQQ MA200 {'하회' if qqq.get('price_vs_ma200') == 'below' else '상회'}")
    if spy:
        desc_parts.append(f"SPY MA200 {'하회' if spy.get('price_vs_ma200') == 'below' else '상회'}")
    if desc_parts:
        label += " — " + ", ".join(desc_parts)

    return {
        "master_class": cls,
        "master_label": label,
        "qqq_price": f"${qqq.get('price', 'N/A')}" if qqq else "N/A",
        "qqq_ma200": f"${qqq.get('ma200', 'N/A')}" if qqq else "N/A",
        "qqq_status": _status(qqq),
        "spy_price": f"${spy.get('price', 'N/A')}" if spy else "N/A",
        "spy_ma200": f"${spy.get('ma200', 'N/A')}" if spy else "N/A",
        "spy_status": _status(spy),
    }


def _vix_note(vix: float | None) -> str:
    if vix is None:
        return "N/A"
    if vix >= 30:
        return f"공포 구간 (≥30)"
    elif vix >= 20:
        return f"불안 구간 (20~30)"
    else:
        return f"안정 구간 (<20)"


def _build_holdings(portfolio: list, market_data: dict, signals: dict) -> list:
    """Holdings 테이블 데이터 구성"""
    data = market_data.get("data", {})
    holdings = []

    for p in portfolio:
        ticker = p["ticker"]
        d = data.get(ticker, {})
        price = d.get("price", 0)
        shares = p.get("shares", 0)
        avg_cost = p.get("avg_cost", 0)
        value = shares * price if price else 0
        pnl_pct = ((price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0
        sig = signals.get(ticker, {})

        holdings.append({
            "ticker": ticker,
            "name": get_ticker_name(ticker),
            "cls": get_ticker_class(ticker),
            "cls_tag": get_cls_tag(ticker),
            "shares": shares,
            "avg_cost": avg_cost,
            "price": price,
            "value": value,
            "pnl_pct": pnl_pct,
            "signal": sig.get("signal", "HOLD"),
            "rsi": sig.get("rsi"),
            "drawdown": sig.get("drawdown"),
            "macd_hist": sig.get("macd_hist"),
            "adx": sig.get("adx"),
            "change_pct": sig.get("change_pct", 0),
            "note": sig.get("note", ""),
            "conditions": sig.get("conditions", []),
            "bb_pct": sig.get("bb_pct"),
            "macd_hist_3d": sig.get("macd_hist_3d", []),
            "buy_streak": sig.get("buy_streak", 0),
            "buy_confirmed": sig.get("buy_confirmed", False),
            "is_kospi": is_kospi_ticker(ticker),
        })

    holdings.sort(key=lambda x: -x["value"])
    return holdings


def _signal_counts(signals: dict) -> dict:
    counts = {"TP2": 0, "TP1": 0, "BUY": 0, "WATCH": 0, "HOLD": 0}
    for r in signals.values():
        sig = r.get("signal", "")
        if "TAKE_PROFIT_2" in sig or "TOP" in sig:
            counts["TP2"] += 1
        elif "TAKE_PROFIT_1" in sig:
            counts["TP1"] += 1
        elif "BUY" in sig:
            counts["BUY"] += 1
        elif "WATCH" in sig or "BOND_WATCH" in sig:
            counts["WATCH"] += 1
        else:
            counts["HOLD"] += 1
    return counts


def _badge_class(signal: str) -> str:
    if "TAKE_PROFIT_2" in signal or "TOP" in signal:
        return "badge-exit"
    elif "TAKE_PROFIT_1" in signal:
        return "badge-tp1"
    elif "BUY" in signal:
        return "badge-BUY"
    elif "WATCH" in signal:
        return "badge-WATCH"
    elif "BOND" in signal:
        return "badge-BOND"
    elif "CASH" in signal:
        return "badge-CASH"
    return "badge-HOLD"


def _card_class(signal: str) -> str:
    if "TAKE_PROFIT_2" in signal or "TOP" in signal:
        return "exit"
    elif "TAKE_PROFIT_1" in signal:
        return "tp1"
    elif "BUY" in signal:
        return "buy"
    elif "WATCH" in signal:
        return "watch"
    elif "BOND" in signal:
        return "bond"
    return "hold"


def _mcap(v, currency="USD"):
    """시가총액 포맷팅 (USD/KRW 지원)"""
    if not v: return ""
    v = float(v)
    if currency == "KRW":
        if v >= 1e12: return f"\u20a9{v/1e12:.0f}\uc870"
        if v >= 1e8: return f"\u20a9{v/1e8:.0f}\uc5b5"
        return f"\u20a9{v:,.0f}"
    if v >= 1e12: return f"${v/1e12:.1f}T"
    if v >= 1e9: return f"${v/1e9:.0f}B"
    if v >= 1e6: return f"${v/1e6:.0f}M"
    return f"${v:,.0f}"


def _div_top_contributors(dividends: dict) -> str:
    """배당 top 3 기여자 문자열"""
    per_ticker = dividends.get("per_ticker", {})
    if not per_ticker:
        return ""
    sorted_divs = sorted(per_ticker.items(), key=lambda x: -x[1].get("annual_income", 0))
    top3 = sorted_divs[:3]
    parts = [f"{t} ${d['annual_income']/12:.0f}/mo" for t, d in top3]
    return " · ".join(parts)


def generate_report(
    market_data: dict,
    portfolio: list,
    signals: dict,
    history: dict,
    prev_signals: dict,
    output_path: str,
    template_dir: str | None = None,
    scanner_sp100: dict | None = None,
    scanner_etf: dict | None = None,
    scanner_kospi: dict | None = None,
) -> str:
    """
    Jinja2 템플릿으로 HTML 리포트 생성.
    반환: 저장된 파일 경로
    """
    if template_dir is None:
        template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)

    # Register custom filters BEFORE loading template
    env.filters["badge_class"] = _badge_class
    env.filters["card_class"] = _card_class
    env.filters["comma"] = lambda x: f"{x:,.0f}" if isinstance(x, (int, float)) else str(x)
    env.filters["comma2"] = lambda x: f"{x:,.2f}" if isinstance(x, (int, float)) else str(x)
    env.filters["pct1"] = lambda x: f"{x:.1f}" if isinstance(x, (int, float)) else str(x)
    env.filters["pct2"] = lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else str(x)
    env.filters["sign_pct"] = lambda x: f"+{x:.1f}%" if x >= 0 else f"{x:.1f}%"
    env.filters["mcap"] = _mcap
    env.filters["f3"] = lambda x: f"{x:.3f}" if isinstance(x, (int, float)) else str(x)
    env.filters["f2"] = lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else str(x)
    env.filters["f1"] = lambda x: f"{x:.1f}" if isinstance(x, (int, float)) else str(x)
    env.filters["f4"] = lambda x: f"{x:.4f}" if isinstance(x, (int, float)) else str(x)
    env.filters["shares_fmt"] = lambda x: f"{x:.3f}" if x < 100 else f"{x:,.0f}"

    template = env.get_template("report_template.html")

    meta = market_data.get("_meta", {})
    macro = market_data.get("_macro", {})
    dividends = market_data.get("_dividends", {})
    date_str = meta.get("date", datetime.now().strftime("%Y-%m-%d"))

    holdings = _build_holdings(portfolio, market_data, signals)

    # VIX/금리/환율 (포트폴리오 계산에 필요하므로 먼저 로드)
    vix = macro.get("VIX")
    yield_30y = macro.get("yield_30Y")
    usd_krw = macro.get("USD_KRW", 0)

    # USD/KRW 분리 계산 (KOSPI 종목은 KRW, 나머지는 USD)
    us_holdings = [h for h in holdings if not h["is_kospi"]]
    kospi_holdings = [h for h in holdings if h["is_kospi"]]
    rate = usd_krw if usd_krw else 1

    us_value = sum(h["value"] for h in us_holdings)
    kospi_value = sum(h["value"] for h in kospi_holdings)
    us_cost = sum(h["shares"] * h["avg_cost"] for h in us_holdings)
    kospi_cost = sum(h["shares"] * h["avg_cost"] for h in kospi_holdings)

    # USD 기준 통합 (KOSPI KRW → USD 변환)
    total_value = us_value + (kospi_value / rate if rate > 1 else kospi_value)
    cost_basis = us_cost + (kospi_cost / rate if rate > 1 else kospi_cost)
    total_pnl = total_value - cost_basis
    total_pnl_pct = (total_pnl / cost_basis * 100) if cost_basis > 0 else 0

    # KRW 기준 통합 (US USD → KRW 변환)
    total_value_krw = us_value * rate + kospi_value
    cost_basis_krw = us_cost * rate + kospi_cost
    total_pnl_krw = total_value_krw - cost_basis_krw

    # 비중 계산 (KRW 통합 기준으로 통일)
    if total_value_krw > 0:
        for h in holdings:
            if h["is_kospi"]:
                h["weight"] = h["value"] / total_value_krw * 100
            else:
                h["weight"] = (h["value"] * rate) / total_value_krw * 100
    else:
        for h in holdings:
            h["weight"] = 0

    # BIL (현금) 정보
    bil = next((h for h in holdings if h["ticker"] == "BIL"), None)
    cash_value = bil["value"] if bil else 0
    cash_value_krw = cash_value * rate
    cash_pct = (cash_value / total_value * 100) if total_value > 0 else 0

    # 카테고리 수
    categories = set(h["cls"] for h in holdings)

    krw_equiv = total_value_krw

    # 시그널 분류
    counts = _signal_counts(signals)
    tp2_signals = [h for h in holdings if h["signal"] in ("TAKE_PROFIT_2", "TOP_SIGNAL")]
    tp1_signals = [h for h in holdings if h["signal"] == "TAKE_PROFIT_1"]
    buy_signals = [h for h in holdings if "BUY" in h["signal"] and "BOND" not in h["signal"]]
    bond_signals = [h for h in holdings if h["signal"] == "BOND_WATCH"]
    watch_signals = [h for h in holdings if h["signal"] == "WATCH"]

    # 배당 정보 (USD 기준, KRW 변환 포함)
    div_annual = dividends.get("total_annual", 0)
    div_monthly = dividends.get("monthly_avg", 0)
    div_yield = dividends.get("portfolio_yield", 0)
    div_top = _div_top_contributors(dividends)
    div_annual_krw = div_annual * rate
    div_monthly_krw = div_monthly * rate

    # 이전 시그널 맵 (어제 대비 변동 표시용)
    prev_signal_map = {}
    for ticker, pdata in prev_signals.items():
        prev_signal_map[ticker] = pdata.get("signal", "")

    # 경고 배너 (L3 다수 시)
    alert_msg = ""
    if counts["TP2"] >= len(holdings) * 0.5:
        alert_msg = f"⚠️ 익절 경보 — {len(holdings)}종목 중 {counts['TP2']}종목 TAKE_PROFIT"

    master = _master_info(macro, market_data)

    context = {
        # 기본
        "date": date_str,
        "date_ko": _date_ko(date_str),
        "fetched_at": meta.get("generated_at", ""),
        "portfolio_source": meta.get("ticker_source", "portfolio.md"),
        # 매크로
        **master,
        "vix": vix,
        "vix_note": _vix_note(vix),
        "yield_30y": yield_30y,
        "yield_note": f"{yield_30y:.3f}%" if yield_30y else "N/A",
        "usd_krw": f"{usd_krw:,.2f}" if usd_krw else "N/A",
        "usd_krw_raw": usd_krw or 0,
        "krw_equiv": f"≈ {krw_equiv/100000000:.2f}억원" if krw_equiv else "N/A",
        # 시그널 카운트
        "n_tp2": counts["TP2"],
        "n_tp1": counts["TP1"],
        "n_buy": counts["BUY"],
        "n_watch": counts["WATCH"],
        "n_hold": counts["HOLD"],
        # 포트폴리오 요약 (USD + KRW)
        "total_value": total_value,
        "total_value_krw": total_value_krw,
        "cost_basis": cost_basis,
        "cost_basis_krw": cost_basis_krw,
        "total_pnl": total_pnl,
        "total_pnl_krw": total_pnl_krw,
        "total_pnl_pct": total_pnl_pct,
        "n_holdings": len(holdings),
        "n_categories": len(categories),
        "cash_value": cash_value,
        "cash_value_krw": cash_value_krw,
        "cash_pct": cash_pct,
        # 배당
        "div_annual": div_annual,
        "div_annual_krw": div_annual_krw,
        "div_monthly": div_monthly,
        "div_monthly_krw": div_monthly_krw,
        "div_yield": div_yield,
        "div_top": div_top,
        # 데이터
        "holdings": holdings,
        "tp2_signals": tp2_signals,
        "tp1_signals": tp1_signals,
        "buy_signals": buy_signals,
        "bond_signals": bond_signals,
        "watch_signals": watch_signals,
        "all_signals": holdings,  # Judgment Details용
        "prev_signal_map": prev_signal_map,
        # 경고
        "alert_msg": alert_msg,
        # Jinja2 필터
        "badge_class": _badge_class,
        "card_class": _card_class,
        # S&P 100 Scanner 결과
        "sp100_buy_1st": (scanner_sp100 or {}).get("buy_1st", []),
        "sp100_buy_2nd": (scanner_sp100 or {}).get("buy_2nd", []),
        "sp100_buy_3rd": (scanner_sp100 or {}).get("buy_3rd", []),
        "sp100_watch": (scanner_sp100 or {}).get("watch_signals", []),
        "sp100_scanned": (scanner_sp100 or {}).get("scanned", 0),
        "sp100_scan_time": (scanner_sp100 or {}).get("scan_time", ""),
        # ETF Scanner 결과
        "etf_buy_1st": (scanner_etf or {}).get("buy_1st", []),
        "etf_buy_2nd": (scanner_etf or {}).get("buy_2nd", []),
        "etf_buy_3rd": (scanner_etf or {}).get("buy_3rd", []),
        "etf_watch": (scanner_etf or {}).get("watch_signals", []),
        "etf_scanned": (scanner_etf or {}).get("scanned", 0),
        "etf_scan_time": (scanner_etf or {}).get("scan_time", ""),
        # KOSPI Scanner 결과
        "kospi_buy_1st": (scanner_kospi or {}).get("buy_1st", []),
        "kospi_buy_2nd": (scanner_kospi or {}).get("buy_2nd", []),
        "kospi_buy_3rd": (scanner_kospi or {}).get("buy_3rd", []),
        "kospi_watch": (scanner_kospi or {}).get("watch_signals", []),
        "kospi_scanned": (scanner_kospi or {}).get("scanned", 0),
        "kospi_scan_time": (scanner_kospi or {}).get("scan_time", ""),
    }

    html = template.render(**context)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


def _sig_class(signal: str) -> str:
    """시그널 문자열 → 히스토리 테이블 CSS 클래스"""
    if "TAKE_PROFIT" in signal or "TOP" in signal:
        return "sig-exit"
    if "BUY" in signal:
        return "sig-buy"
    if "WATCH" in signal or "BOND" in signal:
        return "sig-watch"
    if "CASH" in signal:
        return "sig-cash"
    return "sig-hold"


def _macd_hist_trend_ko(trend: str | None) -> str:
    if trend == "increasing":
        return "상승 중"
    elif trend == "decreasing":
        return "하락 중"
    return "중립"


def _build_history_rows(ticker: str, history: dict) -> list[dict]:
    """히스토리에서 특정 종목의 최근 30일 시계열 추출"""
    rows = []
    dates = sorted(
        [d for d in history.keys() if not d.startswith("_")],
        reverse=True,
    )
    for d in dates[:30]:
        entry = history[d].get(ticker)
        if not entry:
            continue
        rows.append({
            "date": d,
            "signal": entry.get("signal", ""),
            "sig_class": _sig_class(entry.get("signal", "")),
            "price": entry.get("price", 0),
            "rsi": entry.get("rsi"),
            "macd_hist": entry.get("macd_hist"),
            "drawdown": entry.get("drawdown"),
        })
    return rows


def _collect_scanner_buy_entries(*scanners) -> list[dict]:
    """스캐너 결과에서 BUY 엔트리만 수집 (1st/2nd/3rd)"""
    entries = []
    for scanner in scanners:
        if not scanner:
            continue
        for key in ("buy_1st", "buy_2nd", "buy_3rd"):
            for e in scanner.get(key, []):
                entries.append(e)
    return entries


def generate_detail_pages(
    market_data: dict,
    portfolio: list,
    signals: dict,
    history: dict,
    output_dir: str,
    template_dir: str | None = None,
    scanner_sp100: dict | None = None,
    scanner_etf: dict | None = None,
    scanner_kospi: dict | None = None,
) -> list[str]:
    """
    포트폴리오 + 스캐너 BUY 종목별 상세 페이지 HTML 생성.
    반환: 생성된 파일 경로 목록
    """
    if template_dir is None:
        template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)

    # 공통 필터 등록 (generate_report와 동일)
    env.filters["badge_class"] = _badge_class
    env.filters["card_class"] = _card_class
    env.filters["comma"] = lambda x: f"{x:,.0f}" if isinstance(x, (int, float)) else str(x)
    env.filters["comma2"] = lambda x: f"{x:,.2f}" if isinstance(x, (int, float)) else str(x)
    env.filters["pct1"] = lambda x: f"{x:.1f}" if isinstance(x, (int, float)) else str(x)
    env.filters["pct2"] = lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else str(x)
    env.filters["sign_pct"] = lambda x: f"+{x:.1f}%" if x >= 0 else f"{x:.1f}%"
    env.filters["mcap"] = _mcap
    env.filters["f0"] = lambda x: f"{x:.0f}" if isinstance(x, (int, float)) else str(x)
    env.filters["f1"] = lambda x: f"{x:.1f}" if isinstance(x, (int, float)) else str(x)
    env.filters["f2"] = lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else str(x)
    env.filters["f3"] = lambda x: f"{x:.3f}" if isinstance(x, (int, float)) else str(x)
    env.filters["f4"] = lambda x: f"{x:.4f}" if isinstance(x, (int, float)) else str(x)
    env.filters["shares_fmt"] = lambda x: f"{x:.3f}" if x < 100 else f"{x:,.0f}"

    template = env.get_template("detail_template.html")

    data = market_data.get("data", {})
    meta = market_data.get("_meta", {})
    date_str = meta.get("date", datetime.now().strftime("%Y-%m-%d"))

    os.makedirs(output_dir, exist_ok=True)
    generated = []

    for p in portfolio:
        ticker = p["ticker"]
        d = data.get(ticker, {})
        sig = signals.get(ticker, {})
        price = d.get("price", 0)
        shares = p.get("shares", 0)
        avg_cost = p.get("avg_cost", 0)
        value = shares * price if price else 0
        pnl_pct = ((price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0

        # 52주 레인지 계산
        high_52w = d.get("high_52w")
        drawdown_52w = d.get("drawdown_52w_pct", 0)
        low_52w = None
        range_pct = 50
        if high_52w and high_52w > 0:
            # low_52w는 직접 계산 (52주 최저가는 데이터에 없으므로 근사)
            # drawdown_52w = (price - high_52w) / high_52w * 100 이므로
            # 52주 범위에서의 위치를 계산
            low_52w = d.get("low_52w") or high_52w * 0.7  # fallback
            if high_52w > low_52w:
                range_pct = max(0, min(100, (price - low_52w) / (high_52w - low_52w) * 100))

        # MACD hist trend 한글화
        macd_hist_trend = sig.get("macd_hist_trend") or d.get("macd_hist_trend", "")

        history_rows = _build_history_rows(ticker, history)

        context = {
            "ticker": ticker,
            "name": get_ticker_name(ticker),
            "cls": get_ticker_class(ticker),
            "cls_tag": get_cls_tag(ticker),
            "signal": sig.get("signal", "HOLD"),
            "note": sig.get("note", ""),
            "conditions": sig.get("conditions", []),
            "buy_streak": sig.get("buy_streak", 0),
            "buy_confirmed": sig.get("buy_confirmed", False),
            # 가격
            "price": price,
            "change_pct": sig.get("change_pct", d.get("change_pct", 0)),
            "change_3d_pct": d.get("change_3d_pct", 0),
            # 포트폴리오
            "shares": shares,
            "avg_cost": avg_cost,
            "value": value,
            "pnl_pct": pnl_pct,
            # 기술 지표
            "rsi": sig.get("rsi") or d.get("rsi14"),
            "macd_hist": sig.get("macd_hist") or d.get("macd_hist"),
            "macd": d.get("macd"),
            "macd_signal": d.get("macd_signal"),
            "macd_hist_trend_ko": _macd_hist_trend_ko(macd_hist_trend),
            "adx": sig.get("adx") or d.get("adx"),
            "bb_pct": sig.get("bb_pct") or d.get("bb_pct"),
            "volume_ratio": d.get("volume_ratio"),
            "drawdown": sig.get("drawdown") or d.get("drawdown_20d_pct"),
            "drawdown_52w": drawdown_52w,
            "ma20": d.get("ma20"),
            "ma50": d.get("ma50"),
            "ma200": d.get("ma200"),
            "high_52w": high_52w,
            "low_52w": low_52w,
            "range_pct": range_pct,
            "market_cap": d.get("market_cap", 0),
            "is_kospi": is_kospi_ticker(ticker),
            "currency": "KRW" if is_kospi_ticker(ticker) else "USD",
            # 이력
            "history_rows": history_rows,
            # 메타
            "date": date_str,
            "date_ko": _date_ko(date_str),
            # 차트
            "chart_exists": os.path.exists(os.path.join(output_dir, "charts", f"{ticker}.png")),
        }

        html = template.render(**context)
        out_path = os.path.join(output_dir, f"{ticker}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        generated.append(out_path)

    # ── 스캐너 BUY 종목 상세 페이지 ──
    portfolio_tickers = {p["ticker"] for p in portfolio}
    scanner_entries = _collect_scanner_buy_entries(scanner_sp100, scanner_etf, scanner_kospi)
    seen = set(portfolio_tickers)

    for e in scanner_entries:
        ticker = e.get("ticker", "")
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)

        # 스캐너 엔트리에서 직접 데이터 사용 (market_data에 없을 수 있음)
        d = data.get(ticker, {})
        price = e.get("price", d.get("price", 0))

        # 52주 레인지
        high_52w = d.get("high_52w")
        low_52w = d.get("low_52w")
        range_pct = 50
        if high_52w and high_52w > 0:
            low_52w = low_52w or high_52w * 0.7
            if high_52w > low_52w:
                range_pct = max(0, min(100, (price - low_52w) / (high_52w - low_52w) * 100))

        macd_hist_trend = e.get("macd_hist_trend") or d.get("macd_hist_trend", "")

        # 파일명용 ticker (KOSPI 숫자 ticker는 그대로 사용)
        ticker_for_file = ticker.replace(".KS", "_KS") if ".KS" in ticker else ticker

        context = {
            "ticker": ticker,
            "name": e.get("name", ticker),
            "cls": e.get("cls", get_ticker_class(ticker) or "Scanner"),
            "cls_tag": get_cls_tag(ticker) or "cls-growth",
            "signal": e.get("signal", ""),
            "note": e.get("note", ""),
            "conditions": e.get("conditions", []),
            "buy_streak": e.get("buy_streak", 0),
            "buy_confirmed": e.get("buy_confirmed", False),
            # 가격
            "price": price,
            "change_pct": e.get("change_pct", 0),
            "change_3d_pct": d.get("change_3d_pct", 0),
            # 포트폴리오 (스캐너 종목은 미보유)
            "shares": 0,
            "avg_cost": 0,
            "value": 0,
            "pnl_pct": 0,
            # 기술 지표
            "rsi": e.get("rsi"),
            "macd_hist": e.get("macd_hist"),
            "macd": d.get("macd"),
            "macd_signal": d.get("macd_signal"),
            "macd_hist_trend_ko": _macd_hist_trend_ko(macd_hist_trend),
            "adx": e.get("adx"),
            "bb_pct": e.get("bb_pct"),
            "volume_ratio": e.get("volume_ratio", d.get("volume_ratio")),
            "drawdown": e.get("drawdown", d.get("drawdown_20d_pct")),
            "drawdown_52w": e.get("drawdown_52w", d.get("drawdown_52w_pct", 0)),
            "ma20": d.get("ma20"),
            "ma50": d.get("ma50"),
            "ma200": d.get("ma200"),
            "high_52w": high_52w,
            "low_52w": low_52w,
            "range_pct": range_pct,
            "market_cap": e.get("market_cap", d.get("market_cap", 0)),
            # 이력 (스캐너 종목은 포트폴리오 히스토리 없음)
            "history_rows": [],
            # 메타
            "date": date_str,
            "date_ko": _date_ko(date_str),
            # 차트
            "chart_exists": os.path.exists(os.path.join(output_dir, "charts", f"{ticker_for_file}.png")),
        }

        html = template.render(**context)
        out_path = os.path.join(output_dir, f"{ticker_for_file}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        generated.append(out_path)

    return generated
