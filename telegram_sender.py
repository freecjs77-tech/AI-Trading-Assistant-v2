"""
telegram_sender.py -- Telegram Bot 알림 전송
AI Trading Assistant v3.0

파이프라인 완료 후 시그널 요약 텍스트 + HTML 리포트 파일을 텔레그램으로 전송.
"""

import os
import sys
import json
import urllib.request
import urllib.parse
from datetime import date

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Telegram Bot 설정 ─────────────────────────────────
BOT_TOKEN = "8627861470:AAHkv4tuLdJfmx-BqKfF_3bb0eYZu-yZGr4"
CHAT_ID = "8615904260"
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def _vix_label(vix: float) -> str:
    if vix >= 30:
        return "공포"
    if vix >= 20:
        return "불안"
    return "안정"


def _master_icon(ms: str) -> str:
    return {"RED": "\U0001f534", "YELLOW": "\U0001f7e1", "GREEN": "\U0001f7e2"}.get(ms, "\u2753")


def _build_message(signals: dict, market_data: dict, portfolio: list) -> str:
    """텔레그램 전송용 요약 텍스트 생성"""
    today = date.today().strftime("%Y-%m-%d")
    macro = market_data.get("_macro", {})
    data = market_data.get("data", {})

    # Master Switch
    ms = macro.get("master_switch", "UNKNOWN")

    # Macro
    vix = macro.get("VIX", 0)
    yield_30y = macro.get("yield_30Y", 0)
    usd_krw = macro.get("USD_KRW", 0)

    # Signal counts & categorize
    exit_list = []
    buy_list = []
    watch_list = []
    hold_count = 0
    cash_count = 0

    for ticker, sig in signals.items():
        s = sig.get("signal", "")
        note = sig.get("note", "")
        # 짧은 노트 (첫 번째 조건만)
        short_note = note.split(" + ")[0] if note else ""

        if s in ("TAKE_PROFIT_2", "TOP_SIGNAL"):
            label = "TP2" if s == "TAKE_PROFIT_2" else "TOP"
            exit_list.append(f"  {ticker} {label} -- {short_note}")
        elif s == "TAKE_PROFIT_1":
            exit_list.append(f"  {ticker} TP1 -- {short_note}")
        elif "BUY" in s and "BOND" not in s:
            buy_list.append(f"  {ticker} {s.replace('_', ' ')} -- {short_note}")
        elif s == "BOND_WATCH":
            watch_list.append(f"  {ticker} BOND -- {short_note}")
        elif s == "WATCH":
            watch_list.append(f"  {ticker} -- {short_note}")
        elif s == "HOLD":
            hold_count += 1
        elif s == "CASH":
            cash_count += 1

    # Portfolio summary
    total_value = sum(h.get("value", 0) for h in portfolio)
    total_pnl = sum(h.get("pnl", 0) for h in portfolio)
    pnl_pct = (total_pnl / (total_value - total_pnl) * 100) if total_value > total_pnl else 0
    pnl_sign = "+" if pnl_pct >= 0 else ""

    lines = []
    lines.append(f"\U0001f4ca AI Trading Report ({today})")
    lines.append("\u2501" * 20)
    lines.append(f"\U0001f6a6 Master Switch: {_master_icon(ms)} {ms}")
    lines.append("")

    # Macro
    lines.append("\U0001f4c8 Macro")
    lines.append(f"  VIX: {vix:.1f} ({_vix_label(vix)})")
    lines.append(f"  30Y: {yield_30y:.2f}%")
    if usd_krw:
        lines.append(f"  USD/KRW: {usd_krw:,.0f}")
    lines.append("")

    # EXIT signals
    if exit_list:
        lines.append(f"\u26a0\ufe0f EXIT ({len(exit_list)})")
        lines.extend(exit_list)
        lines.append("")

    # BUY signals
    if buy_list:
        lines.append(f"\U0001f4b0 BUY ({len(buy_list)})")
        lines.extend(buy_list)
        lines.append("")

    # WATCH signals
    if watch_list:
        lines.append(f"\U0001f440 WATCH ({len(watch_list)})")
        lines.extend(watch_list)
        lines.append("")

    # Summary line
    parts = []
    if hold_count:
        parts.append(f"HOLD {hold_count}")
    if cash_count:
        parts.append(f"CASH {cash_count}")
    if parts:
        lines.append(f"\u2705 {' / '.join(parts)}")

    lines.append(f"\U0001f4cb Portfolio: ${total_value:,.0f} ({pnl_sign}{pnl_pct:.1f}%)")
    lines.append("\u2501" * 20)

    return "\n".join(lines)


def _send_message(text: str) -> bool:
    """텍스트 메시지 전송"""
    url = f"{API_BASE}/sendMessage"
    payload = json.dumps({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("ok", False)
    except Exception as e:
        print(f"  [Telegram] sendMessage failed: {e}")
        return False


def _send_document(file_path: str, caption: str = "") -> bool:
    """파일 첨부 전송 (multipart/form-data)"""
    import mimetypes

    boundary = "----TelegramBotBoundary"
    filename = os.path.basename(file_path)
    mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

    with open(file_path, "rb") as f:
        file_data = f.read()

    body = bytearray()

    # chat_id field
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'.encode())
    body.extend(f"{CHAT_ID}\r\n".encode())

    # caption field
    if caption:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="caption"\r\n\r\n'.encode())
        body.extend(f"{caption}\r\n".encode())

    # document field
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'.encode())
    body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode())
    body.extend(file_data)
    body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode())

    url = f"{API_BASE}/sendDocument"
    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("ok", False)
    except Exception as e:
        print(f"  [Telegram] sendDocument failed: {e}")
        return False


def send_report(signals: dict, market_data: dict, portfolio: list, report_path: str) -> bool:
    """시그널 요약 텍스트 + HTML 리포트 파일을 텔레그램으로 전송"""
    # 1) 텍스트 메시지
    text = _build_message(signals, market_data, portfolio)
    msg_ok = _send_message(text)
    if msg_ok:
        print("  [Telegram] Message sent OK")
    else:
        print("  [Telegram] Message send FAILED")

    # 2) HTML 리포트 파일
    doc_ok = False
    if os.path.exists(report_path):
        doc_ok = _send_document(report_path, caption=f"Report {date.today().strftime('%Y-%m-%d')}")
        if doc_ok:
            print("  [Telegram] Report file sent OK")
        else:
            print("  [Telegram] Report file send FAILED")

    return msg_ok and doc_ok


if __name__ == "__main__":
    # 단독 테스트: 오늘 데이터로 전송
    project_dir = os.path.dirname(os.path.abspath(__file__))
    today = date.today().strftime("%Y-%m-%d")
    json_path = os.path.join(project_dir, "screenshots", f"market_data_{today}.json")
    report_path = os.path.join(project_dir, "reports", f"report_{today}.html")

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
    portfolio = _parse_portfolio_for_report(os.path.join(project_dir, "portfolio.md"))

    ok = send_report(signals, market_data, portfolio, report_path)
    print(f"\nResult: {'SUCCESS' if ok else 'PARTIAL/FAILED'}")
