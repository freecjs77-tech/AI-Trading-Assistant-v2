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


# ─── Portfolio Stop Signal — risk summary ─────────────────

def _build_portfolio_risk_message(stop_me: dict | None,
                                  stop_wife: dict | None,
                                  base_url: str,
                                  date_str: str) -> str:
    from portfolio_stop_config import (
        TELEGRAM_MAX_EXIT_ITEMS, TELEGRAM_MAX_EXIT_READY_ITEMS,
        TELEGRAM_MAX_TIGHT_ITEMS,
    )

    def _by_signal(positions, sig):
        return [p for p in positions if p.get("display_signal") == sig]

    def _trim_list(items, max_n: int):
        if len(items) <= max_n:
            return items, 0
        return items[:max_n], len(items) - max_n

    def _line_full(p):
        c = p.get("below_stop_count", 0)
        suffix = f" ({c}d below stop)" if c else ""
        new_mark = " (new)" if p.get("is_new_position") else ""
        return f"  {p['ticker']}{new_mark} → {p.get('display_action','-')}{suffix}"

    def _section(title_fmt: str, positions, signal: str, max_n: int,
                  full=True):
        items = _by_signal(positions, signal)
        if not items:
            return ""
        kept, extra = _trim_list(items, max_n)
        title = title_fmt.format(n=len(items))
        if full:
            body = "\n".join(_line_full(p) for p in kept)
        else:
            body = "  " + ", ".join(p["ticker"] for p in kept)
        if extra:
            body += f"\n  + {extra} more — see report"
        return f"\n\n{title}\n{body}"

    def _owner_block(owner_label: str, result: dict) -> str:
        if not result or result.get("status") != "ok":
            return ""
        s = result.get("summary", {})
        positions = result.get("positions", [])
        head = (
            f"\n[{owner_label}]\n"
            f"🟢 HOLD ({s.get('HOLD',0)})  "
            f"🟡 TIGHT ({s.get('TIGHT',0)})  "
            f"🟠 EXIT_READY ({s.get('EXIT_READY',0)})  "
            f"🔴 EXIT ({s.get('EXIT',0)})"
        )
        body = ""
        body += _section("🔴 EXIT ({n}):", positions, "EXIT",
                          TELEGRAM_MAX_EXIT_ITEMS)
        body += _section("🟠 EXIT_READY ({n}):", positions, "EXIT_READY",
                          TELEGRAM_MAX_EXIT_READY_ITEMS)
        body += _section("🟡 TIGHT ({n}):", positions, "TIGHT",
                          TELEGRAM_MAX_TIGHT_ITEMS, full=False)
        return head + body

    parts = [f"🛡 Portfolio Risk Summary — {date_str}"]
    parts.append(_owner_block("me", stop_me))
    if stop_wife:
        parts.append(_owner_block("wife", stop_wife))

    base = base_url.rstrip("/")
    parts.append(f"\n\n📊 me:   {base}/portfolio_stops_{date_str}.html")
    if stop_wife:
        parts.append(f"📊 wife: {base}/portfolio_stops_wife_{date_str}.html")

    msg = "\n".join(p for p in parts if p)
    return msg[:3500]


def send_portfolio_risk_summary(stop_me: dict | None,
                                stop_wife: dict | None,
                                base_url: str,
                                date_str: str) -> bool:
    if not stop_me and not stop_wife:
        return False
    text = _build_portfolio_risk_message(stop_me, stop_wife, base_url, date_str)
    ok = _send_message(text)
    if ok:
        print("  [Telegram] Portfolio risk summary sent OK")
    else:
        print("  [Telegram] Portfolio risk summary send FAILED")
    return ok


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
            icons.append("\U0001f534")
        elif tag == "PARABOLIC":
            icons.append("\U0001f7e0")
    return f"{t} {''.join(icons)}".strip()


def _maturity_marker(maturity: str | None) -> str:
    """성숙도 → 색상 마커 (EARLY=녹색, MID=노랑, EXTENDED=빨강)."""
    return {
        "EARLY": "\U0001f7e2",
        "MID": "\U0001f7e1",
        "EXTENDED": "\U0001f534",
    }.get(maturity or "", "")


def _format_market_section(label_emoji: str, label: str,
                            result: dict | None) -> str:
    """단일 마켓(US/KR)의 포맷 블록 생성."""
    if not result or result.get("status") != "ok":
        return ""
    sigs = result.get("signals", {})
    lines = [f"{label_emoji} {label}"]

    # Top sectors line
    tops = result.get("top_sectors", [])
    if tops:
        lines.append("Top sectors: " + ", ".join(s.get("ticker", "?") for s in tops[:3]))

    # M3/M2/M1 — brief
    for tier_key, short in [("MOMENTUM_3", "M3"), ("MOMENTUM_2", "M2"), ("MOMENTUM_1", "M1")]:
        items = sigs.get(tier_key, [])
        if items:
            preview = ", ".join(_format_ticker_with_tags(e) for e in items[:5])
            extra = "" if len(items) <= 5 else f" (+{len(items) - 5})"
            lines.append(f"{short} ({len(items)}): {preview}{extra}")

    # EM section
    em = sigs.get("EM", [])
    if em:
        preview = ", ".join(
            f"{s.get('ticker', '?')}{_maturity_marker(s.get('maturity'))}"
            for s in em[:5]
        )
        extra = "" if len(em) <= 5 else f" (+{len(em) - 5})"
        lines.append(f"\U0001f331 Emerging ({len(em)}): {preview}{extra}")

    # Rotation Radar
    radar = result.get("rotation_radar") or []
    if radar:
        rotation_str = ", ".join(f"{name} ({cnt})" for name, cnt in radar[:5])
        lines.append(f"\U0001f504 Sector Rotation Radar: {rotation_str}")

    return "\n".join(lines)


def _format_momentum_message(us: dict | None = None,
                              kr: dict | None = None,
                              backtest_summary: dict | None = None,
                              # Legacy positional compat: old callers pass (us_result, kr_result, as_of)
                              # but since as_of is now derived internally, we ignore the 3rd arg if str
                              **_kwargs) -> str:
    """모멘텀 결과 → Telegram 메시지 (≤3500자).

    New signature: _format_momentum_message(us=..., kr=..., backtest_summary=...)
    send_momentum_brief uses keyword args; legacy positional callers still work via
    the us/kr positional params.
    """
    as_of = (us or {}).get("as_of") or (kr or {}).get("as_of") or "—"
    parts: list[str] = [f"\U0001f525 Momentum Scanner — {as_of}"]

    us_section = _format_market_section("\U0001f1fa\U0001f1f8", "US", us)
    if us_section:
        parts.append(us_section)

    kr_section = _format_market_section("\U0001f1f0\U0001f1f7", "KR", kr)
    if kr_section:
        parts.append(kr_section)

    # EM transition KPI from US backtest (if available)
    bs = (us or {}).get("backtest_summary") or {}
    em_stats = (bs.get("by_stage") or {}).get("EM") or {}
    transition_pct = em_stats.get("transition_to_M1_pct")
    if transition_pct is not None:
        parts.append(f"\U0001f525 Edge: EM transition to M1 = {transition_pct:.1f}% (90d)")

    # Legacy Edge / Alert (by_streak) — preserve existing behaviour
    for result in (us, kr):
        if not result:
            continue
        b = result.get("backtest_summary") or {}
        edge = (b.get("by_streak") or {}).get("3+", {}).get("avg_ret_5d")
        if edge is not None:
            parts.append(f"\U0001f525 Edge: M3 streak 3+일 → 5d 평균 {edge:.1f}%")
            break
    for result in (us, kr):
        if not result:
            continue
        alerts = (result.get("backtest_summary") or {}).get("alerts") or {}
        if alerts.get("consecutive_loss_warning"):
            parts.append(
                f"⚠ 최근 5개 leg 중 "
                f"{alerts.get('recent_5_legs_loss_count', '?')}개 손실"
            )
            break

    msg = "\n\n".join(parts)
    return msg[:3500]


def send_momentum_brief(us_result: dict | None,
                         kr_result: dict | None) -> bool:
    """모멘텀 결과를 Telegram으로 전송. 둘 다 None이면 skip."""
    if not us_result and not kr_result:
        return False
    msg = _format_momentum_message(us=us_result, kr=kr_result)
    return _send_message(msg)


def _summarize_lifecycle(result: dict | None) -> dict:
    if not result or not result.get("snapshots"):
        return {"new_confirmed": [], "enter_ok": 0, "early": 0, "failed_breakout": 0,
                "drift_probes": [], "probe_strong": []}
    snaps = result["snapshots"]
    nc, ok, early, fb = [], 0, 0, 0
    drift_probes, probe_strong = [], []
    state = result.get("state") or {}
    for tk, s in snaps.items():
        if s["decision"] == "ENTER":
            ok += 1
            y = ((state.get("tickers") or {}).get(tk) or {}).get("snapshots", [])
            had_prior_confirmed = any(x.get("trigger") == "CONFIRMED_TRIGGER"
                                         for x in y[:-1])
            if not had_prior_confirmed and s["trigger"] == "CONFIRMED_TRIGGER":
                nc.append((tk, s.get("score")))  # NEW: include score
        elif s["decision"] == "PROBE":
            early += 1
            # NEW: drift-track PROBEs
            if s.get("score_track") == "drift":
                drift_probes.append((tk, s.get("score")))
            if "PROBE_STRONG" in (s.get("decision_badges") or []):
                probe_strong.append((tk, s.get("score")))
        if "FAILED_BREAKOUT" in (s.get("raw") or {}).get("risk_tags", []):
            fb += 1
    return {
        "new_confirmed": nc, "enter_ok": ok, "early": early,
        "failed_breakout": fb,
        "drift_probes": drift_probes, "probe_strong": probe_strong,
    }


def _format_lifecycle_section(result: dict | None, flag: str, market: str,
                                  base_url: str, date_str: str) -> str:
    if not result or not result.get("snapshots"):
        return ""
    summary = result.get("_brief_summary") or _summarize_lifecycle(result)
    lines = [f"{flag} {market}"]
    if summary["new_confirmed"]:
        items = summary["new_confirmed"][:5]
        # items may be tuple (ticker, score) under score_v1; backwards-compat string under legacy
        formatted = []
        for it in items:
            if isinstance(it, tuple):
                tk, sc = it
                formatted.append(f"{tk} (s{sc})" if sc is not None else tk)
            else:
                formatted.append(str(it))
        nc = " / ".join(formatted)
        more = "" if len(summary["new_confirmed"]) <= 5 else f" (+{len(summary['new_confirmed']) - 5})"
        lines.append(f"\U0001f195 New 본 진입 ({len(summary['new_confirmed'])}): {nc}{more}")
    if summary["enter_ok"]:
        lines.append(f"\U0001f7e2 본 진입 total: {summary['enter_ok']}")
    if summary["early"]:
        lines.append(f"\U0001f7e1 분할 진입: {summary['early']}")
    # NEW: drift events
    if summary.get("drift_probes"):
        dp = summary["drift_probes"][:3]
        formatted = ", ".join(f"{tk}" + (f" (drift {s})" if s else "") for tk, s in dp)
        lines.append(f"\U0001f30a Drift PROBE ({len(summary['drift_probes'])}): {formatted}")
    if summary.get("probe_strong"):
        ps = summary["probe_strong"][:3]
        formatted = ", ".join(f"{tk}" for tk, s in ps)
        lines.append(f"⚡ PROBE_STRONG: {formatted}")
    if summary["failed_breakout"]:
        lines.append(f"\U0001f534 FAILED_BREAKOUT: {summary['failed_breakout']}")
    base = base_url.rstrip("/") + "/" if base_url else ""
    lines.append(f"\U0001f517 {base}lifecycle_{market.lower()}_{date_str}.html")
    return "\n".join(lines)


def _format_lifecycle_message(us_result: dict | None, kr_result: dict | None,
                                  base_url: str, date_str: str) -> str:
    parts: list[str] = []
    us_section = _format_lifecycle_section(us_result, "\U0001f1fa\U0001f1f8", "US", base_url, date_str)
    kr_section = _format_lifecycle_section(kr_result, "\U0001f1f0\U0001f1f7", "KR", base_url, date_str)
    if us_section:
        parts.append(us_section)
    if kr_section:
        parts.append(kr_section)
    if not parts:
        return ""
    return f"[Lifecycle Brief — {date_str}]\n\n" + "\n\n".join(parts)


def send_lifecycle_brief(us_result: dict | None, kr_result: dict | None,
                            base_url: str, date_str: str) -> bool:
    msg = _format_lifecycle_message(us_result, kr_result, base_url, date_str)
    if not msg.strip():
        return False
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
