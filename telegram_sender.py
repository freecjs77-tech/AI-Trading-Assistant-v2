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
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8627861470:AAHkv4tuLdJfmx-BqKfF_3bb0eYZu-yZGr4")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8615904260")
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"




def _vix_label(vix: float) -> str:
    if vix >= 30:
        return "공포"
    if vix >= 20:
        return "불안"
    return "안정"




def _master_icon(ms: str) -> str:
    return {"RED": "\U0001f534", "YELLOW": "\U0001f7e1", "GREEN": "\U0001f7e2"}.get(ms, "\u2753")



