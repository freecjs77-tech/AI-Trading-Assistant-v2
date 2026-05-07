"""
telegram_sender.py -- Telegram Bot 알림 전송
AI Trading Assistant v3.0

파이프라인 완료 후 시그널 요약 텍스트 + 리포트 링크를 텔레그램으로 전송.
"""

import os
import sys
import json
import urllib.request
from datetime import date

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Telegram Bot 설정 ─────────────────────────────────
# 토큰/채팅 ID는 반드시 환경변수로만 공급. 하드코딩 금지 (토큰 유출 방지).
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""

REPORT_URL = "https://freecjs77-tech.github.io/AI-Trading-Assistant-v2/index.html"


def _master_icon(ms: str) -> str:
    return {"RED": "\U0001f534", "YELLOW": "\U0001f7e1", "GREEN": "\U0001f7e2"}.get(ms, "\u2753")


def _build_message(signals: dict, market_data: dict, portfolio: list) -> str:
    """텔레그램 전송용 간결 요약 텍스트 생성"""
    today = date.today().strftime("%Y-%m-%d")
    macro = market_data.get("_macro", {})
    data = market_data.get("data", {})

    ms = macro.get("master_switch", "UNKNOWN")
    vix = macro.get("VIX", 0)
    yield_30y = macro.get("yield_30Y", 0)
    usd_krw = macro.get("USD_KRW", 0)

    # 시그널 분류
    exit_tickers = []
    buy_tickers = []
    watch_count = 0
    hold_count = 0
    cash_count = 0

    for ticker, sig in signals.items():
        s = sig.get("signal", "")
        if s in ("TAKE_PROFIT_2", "TOP_SIGNAL", "TAKE_PROFIT_1"):
            exit_tickers.append(ticker)
        elif "BUY" in s and "BOND" not in s:
            buy_tickers.append(ticker)
        elif s in ("WATCH", "BOND_WATCH"):
            watch_count += 1
        elif s == "HOLD":
            hold_count += 1
        elif s == "CASH":
            cash_count += 1

    # 포트폴리오 원화 환산 (market_data 최신 시세 기준 — 리포트와 동일)
    from portfolio_data import is_korean_ticker
    krw_rate = usd_krw if usd_krw else 1300
    total_krw = 0
    total_cost_krw = 0
    for h in portfolio:
        t = h.get("ticker", "")
        shares = h.get("shares", 0)
        avg_cost = h.get("avg_cost", 0)
        price = data.get(t, {}).get("price", 0) or 0
        val = shares * price
        cost = shares * avg_cost
        if is_korean_ticker(t):
            total_krw += val
            total_cost_krw += cost
        else:
            total_krw += val * krw_rate
            total_cost_krw += cost * krw_rate
    pnl_pct = ((total_krw - total_cost_krw) / total_cost_krw * 100) if total_cost_krw > 0 else 0
    pnl_sign = "+" if pnl_pct >= 0 else ""
    total_krw_eok = total_krw / 100_000_000

    # 메시지 조립
    lines = []
    lines.append(f"\U0001f4ca AI Trading Report ({today})")
    lines.append("\u2501" * 20)
    lines.append(f"{_master_icon(ms)} {ms} | VIX {vix:.1f} | 30Y {yield_30y:.2f}% | USD/KRW {krw_rate:,.0f}")
    lines.append("")

    if exit_tickers:
        lines.append(f"\u26a0\ufe0f EXIT ({len(exit_tickers)}): {', '.join(exit_tickers)}")
    if buy_tickers:
        shown = buy_tickers[:3]
        extra = len(buy_tickers) - 3
        buy_str = ", ".join(shown)
        if extra > 0:
            buy_str += f" +{extra}"
        lines.append(f"\U0001f4b0 BUY ({len(buy_tickers)}): {buy_str}")

    parts = []
    if watch_count:
        parts.append(f"\U0001f440 WATCH {watch_count}")
    if hold_count:
        parts.append(f"\u2705 HOLD {hold_count}")
    if cash_count:
        parts.append(f"CASH {cash_count}")
    if parts:
        lines.append(" | ".join(parts))

    lines.append("")
    lines.append(f"\U0001f4cb \ud3ec\ud2b8\ud3f4\ub9ac\uc624: \u20a9{total_krw_eok:.2f}\uc5b5 ({pnl_sign}{pnl_pct:.1f}%)")
    lines.append("")
    lines.append(f"\U0001f517 {REPORT_URL}")
    lines.append("\u2501" * 20)

    return "\n".join(lines)


def _send_message(text: str) -> bool:
    """텍스트 메시지 전송"""
    if not BOT_TOKEN or not CHAT_ID:
        print("  [Telegram] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 미설정 — 전송 skip")
        return False
    url = f"{API_BASE}/sendMessage"
    payload = json.dumps({
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": False,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("ok", False)
    except Exception as e:
        print(f"  [Telegram] sendMessage failed: {e}")
        return False


def send_report(signals: dict, market_data: dict, portfolio: list, report_path: str) -> bool:
    """시그널 요약 텍스트 + 리포트 링크를 텔레그램으로 전송"""
    text = _build_message(signals, market_data, portfolio)
    ok = _send_message(text)
    if ok:
        print("  [Telegram] Message sent OK")
    else:
        print("  [Telegram] Message send FAILED")
    return ok


def _format_ticker_with_tags(entry: dict) -> str:
    """틱커 + 리스크 태그 아이콘 포매팅"""
    t = entry.get("ticker", "?")
    tags = entry.get("risk_tags") or []
    icons = []
    for tag in tags:
        if tag == "OVERHEAT":
            icons.append("🔴")
        elif tag == "PARABOLIC":
            icons.append("🟠")
        elif tag == "EXTENDED":
            icons.append("🟡")
    return f"{t} {''.join(icons)}".strip()


def _format_momentum_message(us_result: dict | None,
                              kr_result: dict | None,
                              as_of: str) -> str:
    """모멘텀 결과 → Telegram 메시지 (≤3500자)."""
    lines = [f"🔥 Momentum Scanner — {as_of}", ""]
    for label, result, flag in [("US", us_result, "🇺🇸"), ("KR", kr_result, "🇰🇷")]:
        if not result or result.get("status") != "ok":
            continue
        sigs = result.get("signals", {})
        m3 = sigs.get("MOMENTUM_3", [])
        m2 = sigs.get("MOMENTUM_2", [])
        m1 = sigs.get("MOMENTUM_1", [])
        top_secs = result.get("top_sectors", [])
        sec_str = ", ".join(s.get("ticker", "?") for s in top_secs[:3])
        lines.append(f"{flag} {label}  Top: {sec_str}")
        if m3:
            tickers_str = ", ".join(
                _format_ticker_with_tags(e) for e in m3[:5]
            )
            lines.append(f"M3 ({len(m3)}): {tickers_str}")
        if m2:
            tickers_str = ", ".join(
                _format_ticker_with_tags(e) for e in m2[:5]
            )
            lines.append(f"M2 ({len(m2)}): {tickers_str}")
        if m1:
            lines.append(f"M1 ({len(m1)}): see report")
        lines.append("")

    # Edge / Alert
    for result in (us_result, kr_result):
        if not result:
            continue
        bs = result.get("backtest_summary") or {}
        edge = (bs.get("by_streak") or {}).get("3+", {}).get("avg_ret_5d")
        if edge is not None:
            lines.append(f"🔥 Edge: M3 streak 3+일 → 5d 평균 {edge:.1f}%")
            break
    for result in (us_result, kr_result):
        if not result:
            continue
        alerts = (result.get("backtest_summary") or {}).get("alerts") or {}
        if alerts.get("consecutive_loss_warning"):
            lines.append(
                f"⚠ 최근 5개 leg 중 {alerts.get('recent_5_legs_loss_count', '?')}개 손실"
            )
            break

    msg = "\n".join(lines)
    return msg[:3500]


def send_momentum_brief(us_result: dict | None,
                         kr_result: dict | None) -> bool:
    """모멘텀 결과를 Telegram으로 전송. 둘 다 None이면 skip."""
    if not us_result and not kr_result:
        return False
    as_of = (us_result or kr_result or {}).get("as_of", "unknown")
    msg = _format_momentum_message(us_result, kr_result, as_of)
    return _send_message(msg)


if __name__ == "__main__":
    project_dir = os.path.dirname(os.path.abspath(__file__))
    today = date.today().strftime("%Y-%m-%d")
    json_path = os.path.join(project_dir, "screenshots", f"market_data_{today}.json")

    if not os.path.exists(json_path):
        print(f"No market data for {today}")
        sys.exit(1)

    with open(json_path, "rb") as f:
        raw = f.read()
    market_data = json.loads(raw.rstrip(b" \t\n\r\x00").decode("utf-8"))

    from signal_judge import judge_all
    from history_manager import load_history
    from pipeline import _parse_portfolio_for_report

    history_path = os.path.join(project_dir, "history", "signals_history.json")
    history = load_history(history_path)
    signals = judge_all(market_data, history)
    from portfolio_paths import primary_portfolio_path
    portfolio = _parse_portfolio_for_report(primary_portfolio_path(project_dir))

    # 미리보기
    print(_build_message(signals, market_data, portfolio))
    print("\n--- Sending... ---")
    ok = send_report(signals, market_data, portfolio, "")
    print(f"Result: {'SUCCESS' if ok else 'FAILED'}")
