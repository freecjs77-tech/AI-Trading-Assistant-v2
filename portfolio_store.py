"""portfolio_store.py — 보유종목(portfolios/<owner>.md) 로드/편집 코어.

watchlist_store.py 와 동일한 철학: 마크다운을 파싱→변경→재작성 한다.
단, 보유종목 파일은 카테고리별 표 + 헤더 노트 + 제외 섹션 + footer Ticker
목록으로 구성되므로, 표(table)만 재생성하고 나머지 텍스트는 그대로 보존한다.

핵심 스키마 변경 (2026-11):
- 표에 `평균단가` 컬럼을 신규 추가한다.
- 파서는 `평균단가` 컬럼이 있으면 그 값을 우선 사용하고, 없으면 기존처럼
  (평가금액 − 수익금액) / 보유수량 으로 역산한다 (하위 호환).
- 사용자가 평균단가를 직접 입력/수정할 수 있게 하는 것이 목적.

이 모듈은 순수 파일 I/O + 문자열 처리만 수행한다 (yfinance/네트워크 없음).
"""

from __future__ import annotations

import os
import re
from datetime import date
from typing import List, Optional, Tuple

from portfolio_paths import discover_portfolios, portfolios_dir

try:
    from portfolio_data import is_korean_ticker, get_ticker_name
except Exception:  # pragma: no cover - 방어적
    def is_korean_ticker(t: str) -> bool:
        return bool(re.fullmatch(r"\d{6}", t or ""))

    def get_ticker_name(t: str) -> str:
        return t


# ── 컬럼 라벨 ─────────────────────────────────────────
COL_TICKER = "Ticker"
COL_NAME = "종목명"
COL_SHARES = "보유수량"
COL_AVGCOST = "평균단가"
COL_VALUE = "평가금액"
COL_PNL = "수익금액"
COL_PCT = "수익률"

# 재생성 시 사용하는 표준 컬럼 순서 (평균단가를 보유수량 뒤에 삽입)
OUTPUT_COLUMNS = [COL_TICKER, COL_NAME, COL_SHARES, COL_AVGCOST,
                  COL_VALUE, COL_PNL, COL_PCT]


# ── 검증 ──────────────────────────────────────────────
def _valid_ticker(t: str) -> bool:
    # 미국(영문) 또는 KOSPI(6자리 숫자) 심볼
    return bool(re.fullmatch(r"[A-Z0-9][A-Z0-9\-\.]{0,9}", (t or "").strip()))


def _norm_ticker(t: str) -> str:
    return (t or "").strip().upper()


# ── 숫자 포맷 ─────────────────────────────────────────
def _fmt_shares(shares: float) -> str:
    """보유수량 → '230.649125주' / '910주' / '64,359주'."""
    if shares == int(shares):
        return f"{int(shares):,}주"
    s = f"{shares:,.6f}".rstrip("0").rstrip(".")
    return f"{s}주"


def _fmt_money(amount: float, korean: bool, signed: bool = False) -> str:
    """금액 → '$156,702.42' / '₩948,651,660' (+부호 옵션)."""
    sym = "₩" if korean else "$"
    sign = ""
    val = amount
    if signed:
        sign = "+" if amount >= 0 else "-"
        val = abs(amount)
    if korean:
        body = f"{val:,.0f}"
    else:
        body = f"{val:,.2f}"
    return f"{sign}{sym}{body}"


def _parse_number(text: str) -> Optional[float]:
    """'$156,702.42' / '+₩24,222' / '230.649125주' 등에서 숫자만 추출."""
    if text is None:
        return None
    m = re.search(r"([+-]?)[\$₩]?\s*([\d,]+\.?\d*)", text.replace(" ", ""))
    if not m:
        return None
    sign = -1.0 if m.group(1) == "-" else 1.0
    try:
        return sign * float(m.group(2).replace(",", ""))
    except ValueError:
        return None


# ── 내부 모델 ─────────────────────────────────────────
class _Row:
    __slots__ = ("ticker", "name", "shares", "avg_cost",
                 "value_text", "pnl_text", "pct_text", "dirty")

    def __init__(self, ticker, name, shares, avg_cost,
                 value_text="", pnl_text="", pct_text="", dirty=False):
        self.ticker = ticker
        self.name = name
        self.shares = shares
        self.avg_cost = avg_cost  # None 이면 역산
        self.value_text = value_text
        self.pnl_text = pnl_text
        self.pct_text = pct_text
        self.dirty = dirty

    def effective_avg_cost(self) -> float:
        if self.avg_cost is not None:
            return self.avg_cost
        val = _parse_number(self.value_text)
        pnl = _parse_number(self.pnl_text)
        if val is not None and pnl is not None and self.shares > 0:
            return (val - pnl) / self.shares
        return 0.0


class _Table:
    __slots__ = ("category", "labels", "rows")

    def __init__(self, category: str):
        self.category = category
        self.labels: List[str] = []
        self.rows: List[_Row] = []


class _Model:
    """파일 전체를 요소 리스트로 보존.

    elements: ("raw", [lines]) 또는 ("table", _Table) 튜플의 순서 리스트.
    표는 재생성, raw 는 그대로 출력(단 날짜 라인/Ticker 목록만 치환).
    """

    def __init__(self):
        self.elements: list = []

    def tables(self) -> List[_Table]:
        return [e[1] for e in self.elements if e[0] == "table"]

    def all_rows(self) -> List[Tuple[_Table, _Row]]:
        out = []
        for t in self.tables():
            for r in t.rows:
                out.append((t, r))
        return out

    def find(self, ticker: str) -> Optional[Tuple[_Table, _Row]]:
        tk = _norm_ticker(ticker)
        for t, r in self.all_rows():
            if _norm_ticker(r.ticker) == tk:
                return t, r
        return None


# ── 파싱 ──────────────────────────────────────────────
_HEADER_RE = re.compile(r"^\|\s*Ticker\s*\|", re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")


def _split_cells(line: str) -> List[str]:
    parts = line.split("|")
    # 양끝 빈 셀 제거
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [p.strip() for p in parts]


def _label_index(labels: List[str], name: str) -> int:
    for i, lab in enumerate(labels):
        if lab.replace(" ", "") == name.replace(" ", ""):
            return i
    return -1


def _parse(path: str) -> _Model:
    model = _Model()
    with open(path, "r", encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f]

    i = 0
    n = len(lines)
    raw_buf: List[str] = []
    last_heading = ""

    def flush_raw():
        if raw_buf:
            model.elements.append(("raw", list(raw_buf)))
            raw_buf.clear()

    while i < n:
        line = lines[i]
        hm = _HEADING_RE.match(line)
        if hm:
            last_heading = hm.group(1).strip()
        if _HEADER_RE.match(line):
            # 표 시작: 헤더 + 구분선 + 데이터행 소비
            flush_raw()
            tbl = _Table(category=last_heading)
            tbl.labels = _split_cells(line)
            i += 1
            # 구분선 (|---|)
            if i < n and re.match(r"^\|[\s\-:|]+\|?\s*$", lines[i]):
                i += 1
            ti = _label_index(tbl.labels, COL_TICKER)
            ni = _label_index(tbl.labels, COL_NAME)
            si = _label_index(tbl.labels, COL_SHARES)
            ai = _label_index(tbl.labels, COL_AVGCOST)
            vi = _label_index(tbl.labels, COL_VALUE)
            pi = _label_index(tbl.labels, COL_PNL)
            ci = _label_index(tbl.labels, COL_PCT)
            while i < n and lines[i].startswith("|"):
                cells = _split_cells(lines[i])
                if not cells or (ti >= 0 and ti < len(cells)
                                 and cells[ti] in ("", "Ticker")):
                    i += 1
                    continue

                def cell(idx):
                    return cells[idx] if 0 <= idx < len(cells) else ""

                ticker = cell(ti)
                if not ticker:
                    i += 1
                    continue
                shares = _parse_number(cell(si)) or 0.0
                avg_cost = _parse_number(cell(ai)) if ai >= 0 else None
                tbl.rows.append(_Row(
                    ticker=ticker,
                    name=cell(ni),
                    shares=shares,
                    avg_cost=avg_cost,
                    value_text=cell(vi),
                    pnl_text=cell(pi),
                    pct_text=cell(ci),
                ))
                i += 1
            model.elements.append(("table", tbl))
            continue
        raw_buf.append(line)
        i += 1
    flush_raw()
    return model


# ── 직렬화 ────────────────────────────────────────────
def _render_table(tbl: _Table) -> List[str]:
    out = []
    out.append("| " + " | ".join(OUTPUT_COLUMNS) + " |")
    out.append("|" + "|".join(["--------"] * len(OUTPUT_COLUMNS)) + "|")
    for r in tbl.rows:
        korean = is_korean_ticker(r.ticker)
        avg = r.effective_avg_cost()
        if r.dirty:
            # 편집/신규 행: 평가금액=취득원가, 손익=0 (실시간 반영 전 참고용)
            value_text = _fmt_money(r.shares * avg, korean)
            pnl_text = _fmt_money(0.0, korean, signed=True)
            pct_text = "+0.0%"
        else:
            value_text = r.value_text or _fmt_money(r.shares * avg, korean)
            pnl_text = r.pnl_text or _fmt_money(0.0, korean, signed=True)
            pct_text = r.pct_text or "+0.0%"
        name = r.name or get_ticker_name(r.ticker)
        cells = [
            r.ticker,
            name,
            _fmt_shares(r.shares),
            _fmt_money(avg, korean),
            value_text,
            pnl_text,
            pct_text,
        ]
        out.append("| " + " | ".join(cells) + " |")
    return out


def _render_ticker_fence(model: _Model) -> str:
    tickers = []
    for _t, r in model.all_rows():
        if r.ticker not in tickers:
            tickers.append(r.ticker)
    return " ".join(tickers)


def _serialize(model: _Model) -> str:
    today = date.today().strftime("%Y-%m-%d")
    out_lines: List[str] = []
    for kind, payload in model.elements:
        if kind == "table":
            out_lines.extend(_render_table(payload))
            continue
        # raw 블록: 날짜 라인 치환 + Ticker 목록 코드펜스 치환
        raw = list(payload)
        j = 0
        in_ticker_fence = False
        saw_ticker_header = False
        while j < len(raw):
            ln = raw[j]
            # 최종 업데이트 날짜 → 오늘로 갱신
            if re.search(r"(최종\s*업데이트)\s*[:：]?\s*\d{4}-\d{2}-\d{2}", ln):
                ln = re.sub(r"(최종\s*업데이트\s*[:：]?\s*)\d{4}-\d{2}-\d{2}",
                            rf"\g<1>{today}", ln)
                out_lines.append(ln)
                j += 1
                continue
            if "Ticker 목록" in ln:
                saw_ticker_header = True
                out_lines.append(ln)
                j += 1
                continue
            if saw_ticker_header and ln.strip().startswith("```"):
                if not in_ticker_fence:
                    # 펜스 시작 → 다음 줄들(기존 티커 목록)을 재생성 내용으로 교체
                    out_lines.append(ln)
                    out_lines.append(_render_ticker_fence(model))
                    # 기존 내용 스킵하여 닫는 펜스까지 이동
                    j += 1
                    while j < len(raw) and not raw[j].strip().startswith("```"):
                        j += 1
                    if j < len(raw):
                        out_lines.append(raw[j])  # 닫는 펜스
                    in_ticker_fence = True
                    saw_ticker_header = False
                    j += 1
                    continue
            out_lines.append(ln)
            j += 1
    text = "\n".join(out_lines)
    if not text.endswith("\n"):
        text += "\n"
    return text


# ── 경로 ──────────────────────────────────────────────
def _owner_path(project_dir: str, owner: str) -> Optional[str]:
    for o, p in discover_portfolios(project_dir):
        if o == owner:
            return p
    return None


def list_owners(project_dir: str) -> List[str]:
    return [o for o, _ in discover_portfolios(project_dir)]


# ── 공개 API ──────────────────────────────────────────
def load_holdings(project_dir: str, owner: str = "me") -> List[dict]:
    """owner 보유종목을 clean dict 리스트로 반환.

    키: ticker, name, category, shares, avg_cost, currency
    """
    path = _owner_path(project_dir, owner)
    if not path or not os.path.exists(path):
        return []
    model = _parse(path)
    out = []
    for tbl, r in model.all_rows():
        out.append({
            "ticker": r.ticker,
            "name": r.name or get_ticker_name(r.ticker),
            "category": tbl.category,
            "shares": r.shares,
            "avg_cost": round(r.effective_avg_cost(), 4),
            "currency": "KRW" if is_korean_ticker(r.ticker) else "USD",
        })
    return out


def parse_holdings_from_path(path: str) -> List[dict]:
    """경로 기반 파서 (owner 무관). pipeline 의 리포트 파서가 위임해 사용.

    반환 각 dict: ticker, shares, avg_cost, value, pnl
    - avg_cost: `평균단가` 컬럼이 있으면 그 값, 없으면 (평가금액-수익금액)/수량 역산.
    - value/pnl: md 표의 평가금액/수익금액 숫자 (리포트는 실시간가로 재계산하므로
      참고용이나, 기존 반환 스키마 호환을 위해 포함).
    """
    out: List[dict] = []
    if not path or not os.path.exists(path):
        return out
    model = _parse(path)
    for _tbl, r in model.all_rows():
        shares = r.shares
        avg_cost = r.effective_avg_cost()
        value = _parse_number(r.value_text)
        pnl = _parse_number(r.pnl_text)
        out.append({
            "ticker": r.ticker,
            "shares": shares,
            "avg_cost": avg_cost,
            "value": value if value is not None else (shares * avg_cost),
            "pnl": pnl if pnl is not None else 0.0,
        })
    return out


def list_categories(project_dir: str, owner: str = "me") -> List[str]:
    path = _owner_path(project_dir, owner)
    if not path or not os.path.exists(path):
        return []
    model = _parse(path)
    cats = []
    for t in model.tables():
        if t.category and t.category not in cats:
            cats.append(t.category)
    return cats


def _save(path: str, model: _Model) -> None:
    text = _serialize(model)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def add_holding(project_dir: str, owner: str, ticker: str,
                shares: float, avg_cost: float,
                category: Optional[str] = None,
                name: Optional[str] = None) -> Tuple[bool, str]:
    """신규 종목 추가. 성공 시 (True, msg)."""
    ticker = _norm_ticker(ticker)
    if not _valid_ticker(ticker):
        return False, f"invalid ticker: {ticker}"
    try:
        shares = float(shares)
        avg_cost = float(avg_cost)
    except (TypeError, ValueError):
        return False, "shares/avg_cost must be numeric"
    if shares <= 0 or avg_cost < 0:
        return False, "shares must be > 0 and avg_cost >= 0"
    path = _owner_path(project_dir, owner)
    if not path:
        return False, f"owner not found: {owner}"
    model = _parse(path)
    if model.find(ticker):
        return False, f"{ticker} already in portfolio ({owner})"

    tables = model.tables()
    target = None
    if category:
        for t in tables:
            if t.category.replace(" ", "") == category.replace(" ", ""):
                target = t
                break
        if target is None:
            # 새 카테고리 → 마지막 표 다음에 heading+table 삽입
            new_tbl = _Table(category=category)
            # 마지막 table element 위치 찾기
            last_tbl_idx = max(
                (idx for idx, (k, _) in enumerate(model.elements) if k == "table"),
                default=None,
            )
            heading_block = ("raw", ["", f"## {category}", ""])
            insert_at = (last_tbl_idx + 1) if last_tbl_idx is not None else len(model.elements)
            model.elements.insert(insert_at, ("table", new_tbl))
            model.elements.insert(insert_at, heading_block)
            target = new_tbl
    else:
        if not tables:
            return False, "no category table exists; specify category"
        target = tables[0]

    row = _Row(ticker=ticker, name=name or get_ticker_name(ticker),
               shares=shares, avg_cost=avg_cost, dirty=True)
    target.rows.append(row)
    _save(path, model)
    return True, f"{ticker} added to {owner} ({target.category})"


def remove_holding(project_dir: str, owner: str, ticker: str) -> Tuple[bool, str]:
    ticker = _norm_ticker(ticker)
    if not _valid_ticker(ticker):
        return False, f"invalid ticker: {ticker}"
    path = _owner_path(project_dir, owner)
    if not path:
        return False, f"owner not found: {owner}"
    model = _parse(path)
    found = model.find(ticker)
    if not found:
        return False, f"{ticker} not in portfolio ({owner})"
    tbl, row = found
    tbl.rows.remove(row)
    _save(path, model)
    return True, f"{ticker} removed from {owner}"


def update_holding(project_dir: str, owner: str, ticker: str,
                   shares: Optional[float] = None,
                   avg_cost: Optional[float] = None) -> Tuple[bool, str]:
    """수량/평균단가 수정. 둘 중 하나 이상 지정."""
    ticker = _norm_ticker(ticker)
    if not _valid_ticker(ticker):
        return False, f"invalid ticker: {ticker}"
    if shares is None and avg_cost is None:
        return False, "nothing to update (shares/avg_cost both None)"
    path = _owner_path(project_dir, owner)
    if not path:
        return False, f"owner not found: {owner}"
    model = _parse(path)
    found = model.find(ticker)
    if not found:
        return False, f"{ticker} not in portfolio ({owner})"
    _tbl, row = found
    if shares is not None:
        try:
            shares = float(shares)
        except (TypeError, ValueError):
            return False, "shares must be numeric"
        if shares <= 0:
            return False, "shares must be > 0"
        row.shares = shares
    if avg_cost is not None:
        try:
            avg_cost = float(avg_cost)
        except (TypeError, ValueError):
            return False, "avg_cost must be numeric"
        if avg_cost < 0:
            return False, "avg_cost must be >= 0"
        row.avg_cost = avg_cost
    row.dirty = True
    _save(path, model)
    return True, f"{ticker} updated ({owner})"
