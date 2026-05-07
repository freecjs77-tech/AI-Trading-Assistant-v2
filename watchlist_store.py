"""관심종목(watchlist.md) 로드/편집 헬퍼.

포맷: 한 줄에 한 티커, `#` 이후는 주석, 빈 줄 무시.
예:
    META    # Meta Platforms
    AMD
    AVGO    # Broadcom
"""

from __future__ import annotations

import os
import re
from typing import List, Tuple

WATCHLIST_FILENAME = "watchlist.md"


def watchlist_path(project_dir: str) -> str:
    return os.path.join(project_dir, WATCHLIST_FILENAME)


def _valid_ticker(t: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9][A-Z0-9\-\.]{0,9}", t))


def load_watchlist(project_dir: str) -> List[Tuple[str, str]]:
    """
    (ticker, comment) 리스트 반환. 파일이 없으면 빈 리스트.
    """
    path = watchlist_path(project_dir)
    entries: List[Tuple[str, str]] = []
    if not os.path.exists(path):
        return entries
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith(">"):
                continue
            # 마크다운 제목 등 스킵
            if stripped.startswith("-") or stripped.startswith("*"):
                stripped = stripped.lstrip("-* ").strip()
            if not stripped:
                continue
            # '#' 기준 주석 분리
            if "#" in stripped:
                ticker_part, _, comment = stripped.partition("#")
                ticker = ticker_part.strip().upper()
                comment = comment.strip()
            else:
                ticker = stripped.upper()
                comment = ""
            if _valid_ticker(ticker):
                entries.append((ticker, comment))
    return entries


def load_tickers(project_dir: str) -> List[str]:
    return [t for t, _ in load_watchlist(project_dir)]


def add_ticker(project_dir: str, ticker: str, comment: str = "") -> Tuple[bool, str]:
    """
    티커 추가. 성공 시 (True, 메시지). 이미 존재하면 (False, 메시지).
    파일이 없으면 새로 만든다.
    """
    ticker = ticker.strip().upper()
    if not _valid_ticker(ticker):
        return False, f"invalid ticker: {ticker}"
    path = watchlist_path(project_dir)
    existing = [t for t, _ in load_watchlist(project_dir)]
    if ticker in existing:
        return False, f"{ticker} already in watchlist"
    line = ticker
    if comment:
        line = f"{ticker}    # {comment}"
    with open(path, "a", encoding="utf-8") as f:
        if os.path.getsize(path) > 0:
            f.write("\n" if not _ends_with_newline(path) else "")
        f.write(line + "\n")
    return True, f"{ticker} added"


def _ends_with_newline(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            f.seek(-1, os.SEEK_END)
            return f.read(1) == b"\n"
    except (OSError, ValueError):
        return True  # empty or short file — treat as ok


def remove_ticker(project_dir: str, ticker: str) -> Tuple[bool, str]:
    """
    티커 제거. 성공 시 (True, 메시지). 없으면 (False, 메시지).
    주석 라인은 보존.
    """
    ticker = ticker.strip().upper()
    if not _valid_ticker(ticker):
        return False, f"invalid ticker: {ticker}"
    path = watchlist_path(project_dir)
    if not os.path.exists(path):
        return False, "watchlist.md not found"
    new_lines: List[str] = []
    removed = False
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith(">"):
                head = stripped.lstrip("-* ").strip()
                if "#" in head:
                    head, _, _ = head.partition("#")
                head_ticker = head.strip().upper()
                if head_ticker == ticker:
                    removed = True
                    continue
            new_lines.append(line)
    if not removed:
        return False, f"{ticker} not in watchlist"
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")
    return True, f"{ticker} removed"
