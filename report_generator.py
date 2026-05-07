"""
report_generator.py — Jinja2 기반 HTML 리포트 생성
AI Trading Assistant v3.0

templates/report_template.html에 데이터를 주입하여 리포트 생성.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

from portfolio_data import (
    TICKER_META, get_ticker_name, get_ticker_class, get_cls_tag,
    get_strategy_group, STRATEGY_GROUP, is_kospi_ticker,
)


# ── Owner(와이프 등) 네비게이션 링크 빌더 ──────────────
def _owner_nav_links(date_str: str, project_dir: str | None = None) -> dict:
    """
    portfolios/ 에 존재하는 non-me 포트별 report_{owner}_{date}.html 링크를 만든다.
    현재는 wife만 지원하지만 owner가 늘어나도 자동 확장.
    """
    if project_dir is None:
        project_dir = os.path.dirname(os.path.abspath(__file__))
    links: dict = {"nav_wife": ""}
    try:
        from portfolio_paths import discover_portfolios, PRIMARY_OWNER
        for owner, _ in discover_portfolios(project_dir):
            if owner == PRIMARY_OWNER:
                continue
            links[f"nav_{owner}"] = f"report_{owner}_{date_str}.html"
    except Exception:
        pass
    return links


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
    div_per_ticker = market_data.get("_dividends", {}).get("per_ticker", {})
    usd_krw = market_data.get("_macro", {}).get("USD_KRW", 1) or 1
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
        div_info = div_per_ticker.get(ticker, {})

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
            "hypo_return": sig.get("hypo_return"),
            "is_kospi": is_kospi_ticker(ticker),
            "judgment_sections": sig.get("judgment_sections", []),
            "div_annual": div_info.get("annual_income", 0),
            "div_annual_krw": round(div_info.get("annual_income", 0) * usd_krw) if is_kospi_ticker(ticker) else 0,
            "div_yield": div_info.get("div_yield", 0),
        })

    holdings.sort(key=lambda x: -x["value"])
    return holdings


def _signal_counts(signals: dict) -> dict:
    counts = {"TP2": 0, "TP1": 0, "BUY": 0, "WATCH": 0, "HOLD": 0}
    for r in signals.values():
        sig = r.get("signal", "")
        # 분류 정책: EXIT = TOP_SIGNAL만 / TRIM = TAKE_PROFIT_1, TAKE_PROFIT_2 모두.
        # (사용자 정책 결정 — 익절은 모두 TRIM, 과열 경보(TOP)만 EXIT.)
        if "TOP" in sig:
            counts["TP2"] += 1
        elif "TAKE_PROFIT" in sig:
            counts["TP1"] += 1
        elif "BUY" in sig:
            counts["BUY"] += 1
        elif "WATCH" in sig or "BOND_WATCH" in sig:
            counts["WATCH"] += 1
        else:
            counts["HOLD"] += 1
    return counts


def _badge_class(signal: str) -> str:
    # 정책: EXIT = TOP_SIGNAL만, TRIM = TAKE_PROFIT_1/2 모두.
    if "TOP" in signal:
        return "badge-exit"
    elif "TAKE_PROFIT" in signal:
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
    # 정책: EXIT = TOP_SIGNAL만, TRIM = TAKE_PROFIT_1/2 모두.
    if "TOP" in signal:
        return "exit"
    elif "TAKE_PROFIT" in signal:
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
    backtest_analysis: dict | None = None,
    nav_portfolio: str | None = None,
    active_nav: str = "portfolio",
    benchmark_data: dict | None = None,
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

    # nav_portfolio 기본값: 오늘 날짜의 me 리포트 (로컬/원격 모두 동작)
    if nav_portfolio is None:
        nav_portfolio = f"report_{date_str}.html"

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

    # 시그널 분류 — 보유종목만 카운트 (signals dict는 SPY/QQQ 등 macro/benchmark 티커도
    # 포함하므로 holdings.ticker로 필터해야 화면 표시(EXIT/TRIM/BUY/WATCH/HOLD)와
    # per-row 배지가 일치함).
    _holding_tickers = {h["ticker"] for h in holdings}
    counts = _signal_counts({t: s for t, s in signals.items() if t in _holding_tickers})
    # 정책: EXIT = TOP_SIGNAL만, TRIM = TAKE_PROFIT_1/2 모두.
    tp2_signals = [h for h in holdings if h["signal"] == "TOP_SIGNAL"]
    tp1_signals = [h for h in holdings if h["signal"] in ("TAKE_PROFIT_1", "TAKE_PROFIT_2")]
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
        "market_status": meta.get("market_status"),
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
        # 네비게이션 링크
        "nav_portfolio": nav_portfolio,
        "active_nav": active_nav,
        "nav_scanner": f"scanner_{date_str}.html",
        "nav_backtest": f"backtest_{date_str}.html",
        "nav_trend": f"trend_{date_str}.html",
        **_owner_nav_links(date_str),
    }

    # Benchmark data (YTD vs S&P KRW)
    if benchmark_data and benchmark_data.get("status") == "ok":
        context["benchmark_status"] = "ok"
        context["ytd_pct"] = benchmark_data.get("ytd_pct")
        context["spy_ytd_pct"] = benchmark_data.get("spy_ytd_pct")
        context["alpha_pp"] = benchmark_data.get("alpha_pp")
        context["benchmark_anchor_date"] = benchmark_data.get("anchor_date", "2026-01-02")
        context["benchmark_excluded"] = benchmark_data.get("excluded_tickers", [])
        context["benchmark_error"] = None
    else:
        context["benchmark_status"] = "error"
        context["ytd_pct"] = None
        context["spy_ytd_pct"] = None
        context["alpha_pp"] = None
        context["benchmark_anchor_date"] = "2026-01-02"
        context["benchmark_excluded"] = []
        context["benchmark_error"] = (
            benchmark_data.get("error_message", "unknown") if benchmark_data else None
        )

    html = template.render(**context)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


# ── 스캐너 Reference HTML (각 스캐너별 판정 조건 테이블) ──

_REF_SP100 = """
<h2>📖 Signal Reference — Growth v5.3b Entry</h2>
<div class="ref-section">
<p style="font-size:12px;color:#888;margin-bottom:10px;">대상: S&P 100 대형주. 바닥 확인 후 분할매수 전략.</p>
<table class="ref-table"><thead><tr><th class="signal-col">시그널</th><th class="action-col">액션</th><th>판정 조건</th></tr></thead><tbody>
<tr><td><span class="badge badge-BUY">1st_BUY</span></td><td>목표금액의<br><b>20%</b></td><td><b>[필수 4개 ALL]</b> RSI≤45 + 가격&lt;MA20 + MACD hist 2일↑ + DD_52w≤-15%<br><b>[거부]</b> RSI&gt;55 / 당일-5%급락</td></tr>
<tr><td><span class="badge" style="background:#2563eb;color:#fff;">2nd_BUY</span></td><td>목표금액의<br><b>30%</b></td><td><b>4개 ALL</b>: 이중바닥(≤3%) + RSI&gt;35 + MACD골든크로스 + 거래량≥1.2x</td></tr>
<tr><td><span class="badge" style="background:#1e40af;color:#fff;">3rd_BUY</span></td><td>목표금액의<br><b>50%</b></td><td><b>4개 ALL</b>: 가격&gt;MA20 + MACD&gt;0&amp;Signal + 거래량≥1.3x + RSI&gt;55<br><b>[거부]</b> RSI&gt;75</td></tr>
</tbody></table>
<p style="font-size:11px;color:#94a3b8;margin-top:8px;">※ BUY 시그널은 2일 연속 발생 시 확정됩니다.</p>
</div>"""

_REF_ETF = """
<h2>📖 Signal Reference — ETF v5.3b Entry</h2>
<div class="ref-section">
<p style="font-size:12px;color:#888;margin-bottom:10px;">대상: 섹터/테마 ETF. v5.3b 통합 규칙 적용.</p>
<table class="ref-table"><thead><tr><th class="signal-col">시그널</th><th class="action-col">액션</th><th>판정 조건</th></tr></thead><tbody>
<tr><td><span class="badge badge-BUY">1st_BUY</span></td><td>목표금액의<br><b>20%</b></td><td><b>[필수 4개 ALL]</b> RSI≤45 + 가격&lt;MA20 + MACD hist 2일↑ + DD_52w≤-15%<br><b>[거부]</b> RSI&gt;70</td></tr>
<tr><td><span class="badge" style="background:#2563eb;color:#fff;">2nd_BUY</span></td><td>목표금액의<br><b>30%</b></td><td><b>Pick 3/4</b>: RSI&gt;42 + MACD골든크로스 + 가격&gt;MA20 + Higher Low</td></tr>
<tr><td><span class="badge" style="background:#1e40af;color:#fff;">3rd_BUY</span></td><td>목표금액의<br><b>50%</b></td><td><b>3개 ALL</b>: 가격&gt;MA20 + RSI&gt;55 + MACD&gt;0&amp;Signal</td></tr>
</tbody></table>
<p style="font-size:11px;color:#94a3b8;margin-top:8px;">※ BUY 시그널은 2일 연속 발생 시 확정됩니다.</p>
</div>"""

_REF_KOSPI = """
<h2>📖 Signal Reference — KOSPI Growth v5.3b Entry</h2>
<div class="ref-section">
<p style="font-size:12px;color:#888;margin-bottom:10px;">대상: 코스피 시총 상위 100. S&P 100과 동일한 규칙. 가격 KRW 기준.</p>
<table class="ref-table"><thead><tr><th class="signal-col">시그널</th><th class="action-col">액션</th><th>판정 조건</th></tr></thead><tbody>
<tr><td><span class="badge badge-BUY">1st_BUY</span></td><td>목표금액의<br><b>20%</b></td><td><b>[필수 4개 ALL]</b> RSI≤45 + 가격&lt;MA20 + MACD hist 2일↑ + DD_52w≤-15%<br><b>[거부]</b> RSI&gt;55 / 당일-5%급락</td></tr>
<tr><td><span class="badge" style="background:#2563eb;color:#fff;">2nd_BUY</span></td><td>목표금액의<br><b>30%</b></td><td><b>4개 ALL</b>: 이중바닥(≤3%) + RSI&gt;35 + MACD골든크로스 + 거래량≥1.2x</td></tr>
<tr><td><span class="badge" style="background:#1e40af;color:#fff;">3rd_BUY</span></td><td>목표금액의<br><b>50%</b></td><td><b>4개 ALL</b>: 가격&gt;MA20 + MACD&gt;0&amp;Signal + 거래량≥1.3x + RSI&gt;55<br><b>[거부]</b> RSI&gt;75</td></tr>
</tbody></table>
<p style="font-size:11px;color:#94a3b8;margin-top:8px;">※ BUY 시그널은 2일 연속 발생 시 확정됩니다.</p>
</div>"""


def generate_scanner_pages(
    market_data: dict,
    scanner_sp100: dict | None,
    scanner_etf: dict | None,
    scanner_kospi: dict | None,
    output_dir: str,
    template_dir: str | None = None,
    scanner_watchlist: dict | None = None,
) -> list:
    """스캐너별 독립 HTML 페이지 생성. 반환: 생성된 파일 경로 리스트"""
    if template_dir is None:
        template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)
    env.filters["f1"] = lambda x: f"{x:.1f}" if isinstance(x, (int, float)) else str(x)
    env.filters["f2"] = lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else str(x)
    env.filters["f4"] = lambda x: f"{x:.4f}" if isinstance(x, (int, float)) else str(x)
    env.filters["comma"] = lambda x: f"{x:,.0f}" if isinstance(x, (int, float)) else str(x)
    env.filters["mcap"] = _mcap
    env.filters["badge_class"] = _badge_class

    template = env.get_template("scanner_unified_template.html")

    meta = market_data.get("_meta", {})
    date_str = meta.get("date", datetime.now().strftime("%Y-%m-%d"))
    fetched_at = meta.get("generated_at", "")

    nav = {
        "nav_portfolio": f"report_{date_str}.html",
        "nav_scanner": f"scanner_{date_str}.html",
        "nav_backtest": f"backtest_{date_str}.html",
        "nav_trend": f"trend_{date_str}.html",
        **_owner_nav_links(date_str),
    }

    sp100 = scanner_sp100 or {}
    etf = scanner_etf or {}
    kospi = scanner_kospi or {}
    watchlist = scanner_watchlist or {}

    # Politician Watchlist (Capitol Trades) — V2c optional section. Graceful if file missing/stale.
    politician_watchlist: list = []
    politician_meta: dict = {}
    politician_updated_at: str | None = None
    politician_mode: str = "consensus"
    politician_filter_names: list = []
    politician_trades_list: list = []
    _pt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history", "politician_trades.json")
    if os.path.exists(_pt_path):
        try:
            with open(_pt_path, encoding="utf-8") as _f:
                _pt = json.load(_f)
            politician_watchlist = _pt.get("watchlist", []) or []
            politician_meta = _pt.get("meta", {}) or {}
            politician_updated_at = _pt.get("updated_at")
            politician_mode = _pt.get("mode", "consensus") or "consensus"
            politician_filter_names = _pt.get("filter_politicians", []) or []
            politician_trades_list = _pt.get("trades", []) or []
        except (OSError, json.JSONDecodeError):
            pass  # stale/missing is fine — section just won't render

    politician_buy_cards = [e for e in politician_watchlist if e.get("color_bias") == "buy"]
    politician_sell_cards = [e for e in politician_watchlist if e.get("color_bias") == "sell"]

    context = {
        **nav,
        "date": date_str,
        "date_ko": _date_ko(date_str),
        "fetched_at": fetched_at,
        # Politician Watchlist (V2c)
        "politician_buy_cards": politician_buy_cards,
        "politician_sell_cards": politician_sell_cards,
        "politician_meta": politician_meta,
        "politician_updated_at": politician_updated_at,
        "politician_mode": politician_mode,
        "politician_filter_names": politician_filter_names,
        "politician_trades_list": politician_trades_list,
        # S&P 100
        "sp100_buy_1st": sp100.get("buy_1st", []),
        "sp100_buy_2nd": sp100.get("buy_2nd", []),
        "sp100_buy_3rd": sp100.get("buy_3rd", []),
        "sp100_scanned": sp100.get("scanned", 0),
        "sp100_total": sp100.get("total_signals", 0),
        # ETF
        "etf_buy_1st": etf.get("buy_1st", []),
        "etf_buy_2nd": etf.get("buy_2nd", []),
        "etf_buy_3rd": etf.get("buy_3rd", []),
        "etf_scanned": etf.get("scanned", 0),
        "etf_total": etf.get("total_signals", 0),
        # KOSPI
        "kospi_buy_1st": kospi.get("buy_1st", []),
        "kospi_buy_2nd": kospi.get("buy_2nd", []),
        "kospi_buy_3rd": kospi.get("buy_3rd", []),
        "kospi_scanned": kospi.get("scanned", 0),
        "kospi_total": kospi.get("total_signals", 0),
        # Watchlist (관심종목)
        "watchlist_buy_1st": watchlist.get("buy_1st", []),
        "watchlist_buy_2nd": watchlist.get("buy_2nd", []),
        "watchlist_buy_3rd": watchlist.get("buy_3rd", []),
        "watchlist_watch": watchlist.get("watch_signals", []),
        # 와치리스트는 포트폴리오처럼 전체 시그널(HOLD/EXIT/TP/TOP 포함) 노출
        "watchlist_all": watchlist.get("all_signals", []),
        "watchlist_scanned": watchlist.get("scanned", 0),
        "watchlist_total": watchlist.get("total_signals", 0),
    }

    html = template.render(**context)

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"scanner_{date_str}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    return [out_path]


def generate_momentum_pages(
    momentum_us: dict | None,
    momentum_kr: dict | None,
    output_dir: str,
    template_dir: str | None = None,
) -> list[str]:
    """모멘텀 스캐너 결과 → momentum_us_<DATE>.html / momentum_kr_<DATE>.html 페이지.

    Args:
        momentum_us: scan_momentum_us() 결과 dict 또는 None
        momentum_kr: scan_momentum_kr() 결과 dict 또는 None
        output_dir: 페이지 출력 디렉토리
        template_dir: Jinja2 템플릿 디렉토리 (기본: ./templates)

    Returns:
        생성된 파일 경로 리스트 (None 결과는 스킵).
    """
    if template_dir is None:
        template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)
    env.filters["f1"] = lambda x: f"{x:.1f}" if isinstance(x, (int, float)) else str(x)
    env.filters["f2"] = lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else str(x)

    pairs = [
        ("US", momentum_us, "momentum_us.html", "🇺🇸 US"),
        ("KR", momentum_kr, "momentum_kr.html", "🇰🇷 KR"),
    ]
    output: list[str] = []
    for market, result, tmpl, label in pairs:
        if result is None:
            continue
        as_of = result.get("as_of", "unknown")
        path = os.path.join(output_dir, f"momentum_{market.lower()}_{as_of}.html")
        try:
            html = env.get_template(tmpl).render(result=result, market_label=label)
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
            output.append(path)
        except Exception as e:
            print(f"[report_generator] WARN momentum {market} render failed: {e}")
    return output


def _series_from_daily(daily: dict) -> list:
    """portfolio_daily 스냅샷 → 트렌드 시계열 dict 리스트 (date/total_eok/pnl_eok 등)."""
    out = []
    for d in sorted([k for k in daily.keys() if not k.startswith("_")]):
        snap = daily[d]
        out.append({
            "date": d,
            "total_eok": round(snap.get("total_value_krw", 0) / 1e8, 2),
            "cost_eok": round(snap.get("cost_basis_krw", 0) / 1e8, 2),
            "pnl_eok": round(snap.get("pnl_krw", 0) / 1e8, 2),
            "pnl_pct": snap.get("pnl_pct", 0),
            "div_annual_man": round(snap.get("div_annual_krw", 0) / 1e4),
            "div_yield": snap.get("div_yield", 0),
            "ytd_pct": snap.get("ytd_pct"),
            "spy_ytd_pct": snap.get("spy_ytd_pct"),
            "alpha_pp": snap.get("alpha_pp"),
        })
    return out


def _build_owner_payload(daily: dict) -> dict:
    """단일 포트 daily 스냅샷 → {latest, trend, ticker} 페이로드 (트렌드 페이지용)."""
    sorted_dates = sorted([k for k in daily.keys() if not k.startswith("_")])
    latest_snap = daily.get(sorted_dates[-1], {}) if sorted_dates else {}
    latest_total = latest_snap.get("total_value_krw", 0) or 0
    latest_cost = latest_snap.get("cost_basis_krw", 0) or 0
    latest_pnl = latest_snap.get("pnl_krw", 0) or 0
    latest = {
        "total_eok": f"{latest_total / 1e8:.2f}",
        "cost_eok": f"{latest_cost / 1e8:.2f}",
        "pnl_krw": latest_pnl,
        "pnl_eok": f"{latest_pnl / 1e8:.2f}",
        "pnl_pct": latest_snap.get("pnl_pct", 0),
        "cash_eok": f"{(latest_snap.get('cash_value_krw', 0) or 0) / 1e8:.2f}",
        "cash_pct": latest_snap.get("cash_pct", 0),
        "div_annual_man": f"{(latest_snap.get('div_annual_krw', 0) or 0) / 1e4:,.0f}",
        "div_yield": latest_snap.get("div_yield", 0),
        "ytd_pct": latest_snap.get("ytd_pct"),
        "spy_ytd_pct": latest_snap.get("spy_ytd_pct"),
        "alpha_pp": latest_snap.get("alpha_pp"),
    }
    ticker_weights = latest_snap.get("weights_by_ticker", {}) or {}
    sorted_tickers = sorted(ticker_weights.items(), key=lambda x: -x[1])
    ticker_data = []
    others = 0
    others_krw = 0
    for i, (name, weight) in enumerate(sorted_tickers):
        amt_krw = round(latest_total * weight / 100)
        if i < 10:
            ticker_data.append({"name": name, "value": round(weight, 1), "amount_man": round(amt_krw / 1e4)})
        else:
            others += weight
            others_krw += amt_krw
    if others > 0:
        ticker_data.append({"name": "기타", "value": round(others, 1), "amount_man": round(others_krw / 1e4)})
    return {"latest": latest, "trend": _series_from_daily(daily), "ticker": ticker_data}


def _build_combined_payload(me_daily: dict, others_daily: dict) -> dict:
    """me + 타 owner의 daily를 date-union 합산하여 combined 페이로드 생성."""
    all_daily = [me_daily] + list((others_daily or {}).values())
    all_dates = set()
    for d in all_daily:
        all_dates.update(k for k in d.keys() if not k.startswith("_"))
    sorted_dates = sorted(all_dates)
    # 날짜별 합산 스냅샷 구성
    combined_daily = {}
    for date in sorted_dates:
        tot = 0.0
        cost = 0.0
        pnl = 0.0
        cash = 0.0
        div_annual = 0.0
        v0_sum = 0.0
        v0_complete = True  # v0_krw가 모든 owner에 있어야 합산 ytd 계산 가능
        spy_ytd_pct = None
        # 티커별 krw 누적
        ticker_krw = {}
        for d in all_daily:
            snap = d.get(date)
            if not snap:
                continue
            t = snap.get("total_value_krw", 0) or 0
            tot += t
            cost += snap.get("cost_basis_krw", 0) or 0
            pnl += snap.get("pnl_krw", 0) or 0
            cash += snap.get("cash_value_krw", 0) or 0
            div_annual += snap.get("div_annual_krw", 0) or 0
            for name, w in (snap.get("weights_by_ticker", {}) or {}).items():
                ticker_krw[name] = ticker_krw.get(name, 0) + t * w / 100
            # v0_krw / spy_ytd_pct 집계 (모든 owner에 있을 때만 유효)
            v0 = snap.get("v0_krw")
            if v0 is None:
                v0_complete = False
            else:
                v0_sum += v0
            if spy_ytd_pct is None and snap.get("spy_ytd_pct") is not None:
                spy_ytd_pct = snap.get("spy_ytd_pct")  # 모든 owner 동일하므로 첫 값 사용
        weights_by_ticker = {name: (v / tot * 100) for name, v in ticker_krw.items()} if tot > 0 else {}
        pnl_pct = round((pnl / cost * 100), 2) if cost > 0 else 0
        div_yield = round((div_annual / tot * 100), 2) if tot > 0 else 0
        cash_pct = round((cash / tot * 100), 1) if tot > 0 else 0
        # 합산 YTD: v0_krw 합산이 완전할 때만 계산
        ytd_pct_combined = None
        alpha_pp_combined = None
        if v0_complete and v0_sum > 0:
            ytd_pct_combined = round((tot / v0_sum - 1) * 100, 2)
            if spy_ytd_pct is not None:
                alpha_pp_combined = round(ytd_pct_combined - spy_ytd_pct, 2)
        combined_daily[date] = {
            "total_value_krw": tot,
            "cost_basis_krw": cost,
            "pnl_krw": pnl,
            "pnl_pct": pnl_pct,
            "cash_value_krw": cash,
            "cash_pct": cash_pct,
            "div_annual_krw": div_annual,
            "div_yield": div_yield,
            "weights_by_ticker": weights_by_ticker,
            "v0_krw": v0_sum if v0_complete else None,
            "ytd_pct": ytd_pct_combined,
            "spy_ytd_pct": spy_ytd_pct,
            "alpha_pp": alpha_pp_combined,
        }
    return _build_owner_payload(combined_daily)


TREND_START_DATE = "2026-01-02"  # 트렌드 차트 시작일 (= YTD anchor; 1월 2일부터 풀 히스토리)


def _filter_trend_daily(daily: dict) -> dict:
    """TREND_START_DATE 이후 날짜만 남긴 daily dict 반환. _meta 등 특수키는 유지."""
    if not daily:
        return daily
    return {
        k: v for k, v in daily.items()
        if k.startswith("_") or k >= TREND_START_DATE
    }


def generate_trend_page(
    portfolio_daily: dict,
    output_dir: str,
    template_dir: str | None = None,
    date_str: str | None = None,
    owner_daily: dict | None = None,
) -> str:
    """자산 트렌드 대시보드 HTML 페이지 생성. 반환: 저장된 파일 경로"""
    import json as _json
    if template_dir is None:
        template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # 트렌드 차트는 TREND_START_DATE 이후만 표시
    portfolio_daily = _filter_trend_daily(portfolio_daily)
    if owner_daily:
        owner_daily = {k: _filter_trend_daily(v) for k, v in owner_daily.items()}

    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)

    template = env.get_template("trend_template.html")

    # 날짜순 정렬
    sorted_dates = sorted([k for k in portfolio_daily.keys() if not k.startswith("_")])
    data_days = len(sorted_dates)

    # 트렌드 시계열 데이터
    trend_data = []
    for d in sorted_dates:
        snap = portfolio_daily[d]
        total_krw = snap.get("total_value_krw", 0)
        cost_krw = snap.get("cost_basis_krw", 0)
        pnl_krw = snap.get("pnl_krw", 0)
        trend_data.append({
            "date": d,
            "total_eok": round(total_krw / 1e8, 2),
            "cost_eok": round(cost_krw / 1e8, 2),
            "pnl_eok": round(pnl_krw / 1e8, 2),
            "pnl_pct": snap.get("pnl_pct", 0),
            "div_annual_man": round(snap.get("div_annual_krw", 0) / 1e4),
            "div_yield": snap.get("div_yield", 0),
            "vix": snap.get("vix"),
            "yield_30y": snap.get("yield_30y"),
            "usd_krw": snap.get("usd_krw", 0),
            "ytd_pct": snap.get("ytd_pct"),
            "spy_ytd_pct": snap.get("spy_ytd_pct"),
            "alpha_pp": snap.get("alpha_pp"),
        })

    # 최신 스냅샷 (Summary Cards)
    latest_snap = portfolio_daily.get(sorted_dates[-1], {}) if sorted_dates else {}
    latest_total = latest_snap.get("total_value_krw", 0)
    latest_cost = latest_snap.get("cost_basis_krw", 0)
    latest_pnl = latest_snap.get("pnl_krw", 0)
    latest = {
        "total_eok": f"{latest_total / 1e8:.2f}",
        "cost_eok": f"{latest_cost / 1e8:.2f}",
        "pnl_krw": latest_pnl,
        "pnl_eok": f"{latest_pnl / 1e8:.2f}",
        "pnl_pct": latest_snap.get("pnl_pct", 0),
        "cash_eok": f"{latest_snap.get('cash_value_krw', 0) / 1e8:.2f}",
        "cash_pct": latest_snap.get("cash_pct", 0),
        "div_annual_man": f"{latest_snap.get('div_annual_krw', 0) / 1e4:,.0f}",
        "div_yield": latest_snap.get("div_yield", 0),
        "ytd_pct": latest_snap.get("ytd_pct"),
        "spy_ytd_pct": latest_snap.get("spy_ytd_pct"),
        "alpha_pp": latest_snap.get("alpha_pp"),
    }

    # 카테고리별 비중 + 금액
    cat_weights = latest_snap.get("weights_by_category", {})
    _cat_total_krw = latest_snap.get("total_value_krw", 0)
    category_data = [
        {"name": k, "value": v, "amount_man": round(_cat_total_krw * v / 100 / 1e4)}
        for k, v in sorted(cat_weights.items(), key=lambda x: -x[1])
    ]

    # 종목별 비중 (상위 10 + 기타) — 금액 포함
    ticker_weights = latest_snap.get("weights_by_ticker", {})
    sorted_tickers = sorted(ticker_weights.items(), key=lambda x: -x[1])
    ticker_data = []
    others = 0
    others_krw = 0
    total_krw_val = latest_snap.get("total_value_krw", 0)
    for i, (name, weight) in enumerate(sorted_tickers):
        amt_krw = round(total_krw_val * weight / 100)
        if i < 10:
            ticker_data.append({"name": name, "value": round(weight, 1), "amount_man": round(amt_krw / 1e4)})
        else:
            others += weight
            others_krw += amt_krw
    if others > 0:
        ticker_data.append({"name": "기타", "value": round(others, 1), "amount_man": round(others_krw / 1e4)})

    context = {
        # Nav
        "nav_portfolio": f"report_{date_str}.html",
        "nav_scanner": f"scanner_{date_str}.html",
        "nav_backtest": f"backtest_{date_str}.html",
        "nav_trend": f"trend_{date_str}.html",
        **_owner_nav_links(date_str),
        # Meta
        "date": date_str,
        "date_ko": _date_ko(date_str),
        "data_days": data_days,
        # Summary
        "latest": latest,
        # Chart data (JSON injection)
        "trend_json": _json.dumps(trend_data, ensure_ascii=False),
        "category_json": _json.dumps(category_data, ensure_ascii=False),
        "ticker_json": _json.dumps(ticker_data, ensure_ascii=False),
        # Owner 시계열 (me는 trend_json에 이미 있음, 여기선 wife 등 non-me만)
        "owner_series_json": _json.dumps(
            {
                owner: _series_from_daily(d)
                for owner, d in (owner_daily or {}).items()
            },
            ensure_ascii=False,
        ),
        # Owner별 풀 페이로드 (latest/trend/ticker) — JS가 토글 시 전체 페이지 갱신
        "owners_payload_json": _json.dumps(
            {
                "me": _build_owner_payload(portfolio_daily),
                **{owner: _build_owner_payload(d) for owner, d in (owner_daily or {}).items()},
                **(
                    {"combined": _build_combined_payload(portfolio_daily, owner_daily)}
                    if owner_daily else {}
                ),
            },
            ensure_ascii=False,
        ),
        "has_multi_owner": bool(owner_daily),
    }

    html = template.render(**context)

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"trend_{date_str}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    return out_path


def generate_backtest_page(
    backtest_analysis: dict,
    outcomes: dict,
    pending_signals: list,
    output_dir: str,
    template_dir: str | None = None,
    date_str: str | None = None,
) -> str:
    """백테스트 대시보드 HTML 페이지 생성. 반환: 저장된 파일 경로"""
    if template_dir is None:
        template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)
    env.filters["f1"] = lambda x: f"{x:.1f}" if isinstance(x, (int, float)) else str(x)
    env.filters["f2"] = lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else str(x)
    env.filters["comma"] = lambda x: f"{x:,.0f}" if isinstance(x, (int, float)) else str(x)
    env.filters["badge_class"] = _badge_class

    template = env.get_template("backtest_template.html")

    ba = backtest_analysis or {}
    by_signal = ba.get("by_signal", {})
    benchmark = ba.get("benchmark", {})

    # Overall BUY win rate (5d)
    buy_signals_stats = {k: v for k, v in by_signal.items() if "BUY" in k}
    total_buy_samples = sum(s.get("samples_5d", 0) for s in buy_signals_stats.values())
    total_buy_wins = sum(
        round(s.get("win_rate_5d", 0) * s.get("samples_5d", 0))
        for s in buy_signals_stats.values()
    )
    overall_buy_wr = round(total_buy_wins / total_buy_samples, 3) if total_buy_samples > 0 else None

    # Overall reach rate
    buy_with_reach = [s for s in buy_signals_stats.values() if "reach_rate_10d" in s]
    overall_reach_rate = None
    if buy_with_reach:
        total_reach_samples = sum(s.get("count", 0) for s in buy_with_reach)
        total_reached = sum(round(s.get("reach_rate_10d", 0) * s.get("count", 0)) for s in buy_with_reach)
        if total_reach_samples > 0:
            overall_reach_rate = round(total_reached / total_reach_samples, 3)

    # Alpha (5d)
    alpha = benchmark.get("5d", {}).get("alpha") if benchmark else None

    context = {
        # Nav
        "nav_portfolio": f"report_{date_str}.html",
        "nav_scanner": f"scanner_{date_str}.html",
        "nav_backtest": f"backtest_{date_str}.html",
        "nav_trend": f"trend_{date_str}.html",
        **_owner_nav_links(date_str),
        # Meta
        "date": date_str,
        "date_ko": _date_ko(date_str),
        # Overview
        "total_records": ba.get("total_records", 0),
        "period": ba.get("period"),
        "data_status": ba.get("data_status", "insufficient"),
        "overall_buy_wr": overall_buy_wr,
        "overall_reach_rate": overall_reach_rate,
        "alpha": alpha,
        "win_threshold": 3.0,
        "max_eval_days": 10,
        # Data
        "by_signal": by_signal,
        "by_source": ba.get("by_source", {}),
        "by_condition": ba.get("by_condition", {}),
        "benchmark": benchmark,
        "records": outcomes.get("records", []),
        "recommendations": ba.get("recommendations", []),
    }

    html = template.render(**context)

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"backtest_{date_str}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    return out_path


def _sig_class(signal: str) -> str:
    """시그널 문자열 → 히스토리 테이블 CSS 클래스.

    정책: EXIT = TOP_SIGNAL만, TRIM = TAKE_PROFIT_1/2 모두.
    """
    if "TOP" in signal:
        return "sig-exit"
    if "TAKE_PROFIT" in signal:
        return "sig-tp1"
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
    scanner_watchlist: dict | None = None,
    scanner_sp100_history: dict | None = None,
    scanner_etf_history: dict | None = None,
    scanner_kospi_history: dict | None = None,
    scanner_watchlist_history: dict | None = None,
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

    # 상세 페이지 공통 네비게이션 — deploy 루트 기준 상대경로 (../)
    nav_ctx = {
        "nav_portfolio": f"../report_{date_str}.html",
        "nav_scanner": f"../scanner_{date_str}.html",
        "nav_backtest": f"../backtest_{date_str}.html",
        "nav_trend": f"../trend_{date_str}.html",
        "nav_archive": "../archive.html",
    }
    # wife 리포트가 존재하면 네비에 포함
    try:
        wife_rpt = os.path.join(os.path.dirname(os.path.abspath(output_dir)), f"report_wife_{date_str}.html")
        if os.path.exists(wife_rpt):
            nav_ctx["nav_wife"] = f"../report_wife_{date_str}.html"
    except Exception:
        pass

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
            "judgment_sections": sig.get("judgment_sections", []),
            "buy_streak": sig.get("buy_streak", 0),
            "buy_confirmed": sig.get("buy_confirmed", False),
            "hypo_return": sig.get("hypo_return", {}),
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
            "ticker_for_file": ticker,
            "chart_exists": os.path.exists(os.path.join(output_dir, "charts", f"{ticker}.png")),
            # 네비게이션 (사이드바용)
            **nav_ctx,
        }

        html = template.render(**context)
        out_path = os.path.join(output_dir, f"{ticker}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        generated.append(out_path)

    # ── 스캐너 BUY 종목 상세 페이지 ──
    # Watchlist는 BUY뿐 아니라 HOLD/WATCH 등 all_signals 전체를 상세 페이지로 생성
    # (포트폴리오처럼 추적되는 의사결정 대상이므로)
    portfolio_tickers = {p["ticker"] for p in portfolio}
    scanner_entries = _collect_scanner_buy_entries(scanner_sp100, scanner_etf, scanner_kospi)
    if scanner_watchlist:
        scanner_entries += list(scanner_watchlist.get("all_signals", []))
    seen = set(portfolio_tickers)

    # 스캐너별 티커 셋 구성 (히스토리 소스 결정용)
    def _scanner_tickers(sc):
        tickers = set()
        if sc:
            for key in ("buy_1st", "buy_2nd", "buy_3rd"):
                for entry in sc.get(key, []):
                    tickers.add(entry.get("ticker", ""))
        return tickers

    sp100_tickers = _scanner_tickers(scanner_sp100)
    etf_tickers = _scanner_tickers(scanner_etf)
    kospi_tickers = _scanner_tickers(scanner_kospi)
    watchlist_tickers = set()
    if scanner_watchlist:
        for entry in scanner_watchlist.get("all_signals", []):
            watchlist_tickers.add(entry.get("ticker", ""))

    for e in scanner_entries:
        ticker = e.get("ticker", "")
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)

        # 스캐너 엔트리에서 직접 데이터 사용 (market_data에 없을 수 있음)
        d = data.get(ticker, {})
        price = e.get("price", d.get("price", 0))

        # 52주 레인지 — 스캐너 전용 티커는 d가 비어있을 수 있어 entry(e)에서 우선 조회
        high_52w = e.get("high_52w") or d.get("high_52w")
        low_52w = e.get("low_52w") or d.get("low_52w")
        range_pct = 50
        if high_52w and high_52w > 0:
            low_52w = low_52w or high_52w * 0.7
            if high_52w > low_52w:
                range_pct = max(0, min(100, (price - low_52w) / (high_52w - low_52w) * 100))

        macd_hist_trend = e.get("macd_hist_trend") or d.get("macd_hist_trend", "")

        # 파일명용 ticker (KOSPI 숫자 ticker는 그대로 사용)
        ticker_for_file = ticker.replace(".KS", "_KS") if ".KS" in ticker else ticker

        is_kospi = e.get("currency") == "KRW" or is_kospi_ticker(ticker)

        context = {
            "ticker": ticker,
            "name": e.get("name", ticker),
            "cls": e.get("cls", get_ticker_class(ticker) or "Scanner"),
            "cls_tag": get_cls_tag(ticker) or "cls-growth",
            "signal": e.get("signal", ""),
            "note": e.get("note", ""),
            "conditions": e.get("conditions", []),
            "judgment_sections": e.get("judgment_sections", []),
            "buy_streak": e.get("buy_streak", 0),
            "buy_confirmed": e.get("buy_confirmed", False),
            "hypo_return": e.get("hypo_return", {}),
            # 가격
            "price": price,
            "change_pct": e.get("change_pct", 0),
            "change_3d_pct": e.get("change_3d_pct", d.get("change_3d_pct", 0)),
            # 포트폴리오 (스캐너 종목은 미보유)
            "shares": 0,
            "avg_cost": 0,
            "value": 0,
            "pnl_pct": 0,
            # 기술 지표
            "rsi": e.get("rsi"),
            "macd_hist": e.get("macd_hist"),
            "macd": e.get("macd", d.get("macd")),
            "macd_signal": e.get("macd_signal", d.get("macd_signal")),
            "macd_hist_trend_ko": _macd_hist_trend_ko(macd_hist_trend),
            "adx": e.get("adx"),
            "bb_pct": e.get("bb_pct"),
            "volume_ratio": e.get("volume_ratio", d.get("volume_ratio")),
            "drawdown": e.get("drawdown", d.get("drawdown_20d_pct")),
            "drawdown_52w": e.get("drawdown_52w", d.get("drawdown_52w_pct", 0)),
            "ma20": e.get("ma20", d.get("ma20")),
            "ma50": e.get("ma50", d.get("ma50")),
            "ma200": e.get("ma200", d.get("ma200")),
            "high_52w": e.get("high_52w", high_52w),
            "low_52w": e.get("low_52w", low_52w),
            "range_pct": range_pct,
            "market_cap": e.get("market_cap", d.get("market_cap", 0)),
            # KOSPI/통화
            "is_kospi": is_kospi,
            "currency": "KRW" if is_kospi else "USD",
            # 이력 (스캐너 종목별 히스토리 소스 선택)
            "history_rows": _build_history_rows(
                ticker,
                scanner_sp100_history if ticker in sp100_tickers
                else scanner_etf_history if ticker in etf_tickers
                else scanner_kospi_history if ticker in kospi_tickers
                else scanner_watchlist_history if ticker in watchlist_tickers
                else {}
            ) if (scanner_sp100_history or scanner_etf_history or scanner_kospi_history or scanner_watchlist_history) else [],
            # 메타
            "date": date_str,
            "date_ko": _date_ko(date_str),
            # 차트
            "ticker_for_file": ticker_for_file,
            "chart_exists": os.path.exists(os.path.join(output_dir, "charts", f"{ticker_for_file}.png")),
            # 네비게이션 (사이드바용)
            **nav_ctx,
        }

        html = template.render(**context)
        out_path = os.path.join(output_dir, f"{ticker_for_file}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        generated.append(out_path)

    return generated
