"""portfolio_store.py — 보유종목 편집 코어 테스트."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import portfolio_store as ps  # noqa: E402


SAMPLE = """# Portfolio Holdings
> 최종 업데이트: 2026-07-29 (스크린샷 수동 추출)
> ⚠️ 참고 노트.

---

## Category 1: ETF (Core)

| Ticker | 종목명 | 보유수량 | 평가금액 | 수익금액 | 수익률 |
|--------|--------|---------|---------|---------|--------|
| VOO | Vanguard S&P 500 ETF | 100주 | $60,000.00 | +$10,000.00 | +20.0% |
| QQQ | Invesco QQQ | 50주 | $25,000.00 | -$5,000.00 | -16.67% |

## Category 5: KOSPI 개별주식

| Ticker | 종목명 | 보유수량 | 평가금액 | 수익금액 | 수익률 |
|--------|--------|---------|---------|---------|--------|
| 005930 | 삼성전자 | 100주 | ₩7,000,000 | +₩1,000,000 | +16.67% |

---

## 제외된 종목
- 참고: `PLTR` 전량 매도.

---

## Ticker 목록 (fetch_market_data.py 용)
```
VOO QQQ 005930
```
"""


def _mkproject(tmp_path):
    pdir = tmp_path / "portfolios"
    pdir.mkdir()
    (pdir / "me.md").write_text(SAMPLE, encoding="utf-8")
    return str(tmp_path)


# ── load / derive ─────────────────────────────────────

def test_load_derives_avg_cost(tmp_path):
    proj = _mkproject(tmp_path)
    h = ps.load_holdings(proj, "me")
    assert len(h) == 3
    voo = next(x for x in h if x["ticker"] == "VOO")
    # (60000 - 10000) / 100 = 500
    assert voo["avg_cost"] == 500.0
    assert voo["currency"] == "USD"
    assert voo["category"] == "Category 1: ETF (Core)"
    qqq = next(x for x in h if x["ticker"] == "QQQ")
    # (25000 - (-5000)) / 50 = 600
    assert qqq["avg_cost"] == 600.0
    sam = next(x for x in h if x["ticker"] == "005930")
    assert sam["currency"] == "KRW"
    assert sam["avg_cost"] == 60000.0  # (7,000,000 - 1,000,000)/100


def test_list_categories(tmp_path):
    proj = _mkproject(tmp_path)
    cats = ps.list_categories(proj, "me")
    assert cats == ["Category 1: ETF (Core)", "Category 5: KOSPI 개별주식"]


# ── add ───────────────────────────────────────────────

def test_add_new_ticker(tmp_path):
    proj = _mkproject(tmp_path)
    ok, msg = ps.add_holding(proj, "me", "AAPL", 10, 150.0,
                             category="Category 1: ETF (Core)")
    assert ok, msg
    h = ps.load_holdings(proj, "me")
    aapl = next(x for x in h if x["ticker"] == "AAPL")
    assert aapl["shares"] == 10.0
    assert aapl["avg_cost"] == 150.0
    assert aapl["category"] == "Category 1: ETF (Core)"


def test_add_duplicate_rejected(tmp_path):
    proj = _mkproject(tmp_path)
    ok, msg = ps.add_holding(proj, "me", "VOO", 1, 1.0,
                             category="Category 1: ETF (Core)")
    assert not ok
    assert "already" in msg


def test_add_invalid_ticker(tmp_path):
    proj = _mkproject(tmp_path)
    ok, _ = ps.add_holding(proj, "me", "not a ticker!", 1, 1.0)
    assert not ok


def test_add_bad_numbers(tmp_path):
    proj = _mkproject(tmp_path)
    ok, _ = ps.add_holding(proj, "me", "AMD", 0, 10.0,
                           category="Category 1: ETF (Core)")
    assert not ok
    ok, _ = ps.add_holding(proj, "me", "AMD", 5, -1.0,
                           category="Category 1: ETF (Core)")
    assert not ok


def test_add_new_category_creates_section(tmp_path):
    proj = _mkproject(tmp_path)
    ok, msg = ps.add_holding(proj, "me", "GLD", 3, 200.0,
                             category="Category 9: 신규")
    assert ok, msg
    assert "Category 9: 신규" in ps.list_categories(proj, "me")


# ── update ────────────────────────────────────────────

def test_update_avg_cost(tmp_path):
    proj = _mkproject(tmp_path)
    ok, msg = ps.update_holding(proj, "me", "VOO", avg_cost=555.5)
    assert ok, msg
    voo = next(x for x in ps.load_holdings(proj, "me") if x["ticker"] == "VOO")
    assert voo["avg_cost"] == 555.5


def test_update_shares(tmp_path):
    proj = _mkproject(tmp_path)
    ok, _ = ps.update_holding(proj, "me", "QQQ", shares=75)
    assert ok
    qqq = next(x for x in ps.load_holdings(proj, "me") if x["ticker"] == "QQQ")
    assert qqq["shares"] == 75.0


def test_update_missing_ticker(tmp_path):
    proj = _mkproject(tmp_path)
    ok, _ = ps.update_holding(proj, "me", "ZZZZ", shares=1)
    assert not ok


def test_update_nothing(tmp_path):
    proj = _mkproject(tmp_path)
    ok, _ = ps.update_holding(proj, "me", "VOO")
    assert not ok


# ── remove ────────────────────────────────────────────

def test_remove_ticker(tmp_path):
    proj = _mkproject(tmp_path)
    ok, _ = ps.remove_holding(proj, "me", "QQQ")
    assert ok
    tickers = [x["ticker"] for x in ps.load_holdings(proj, "me")]
    assert "QQQ" not in tickers and "VOO" in tickers


def test_remove_missing(tmp_path):
    proj = _mkproject(tmp_path)
    ok, _ = ps.remove_holding(proj, "me", "ZZZZ")
    assert not ok


# ── 구조 보존 + 컬럼 마이그레이션 + footer 재생성 ──────

def test_save_adds_avgcost_column_and_preserves_structure(tmp_path):
    proj = _mkproject(tmp_path)
    ps.update_holding(proj, "me", "VOO", avg_cost=500.0)
    text = (tmp_path / "portfolios" / "me.md").read_text(encoding="utf-8")
    # 평균단가 컬럼 추가
    assert "평균단가" in text
    # 헤더 노트 / 제외 섹션 보존
    assert "## 제외된 종목" in text
    assert "PLTR" in text
    # 날짜 라인 오늘로 갱신
    from datetime import date
    assert date.today().strftime("%Y-%m-%d") in text


def test_footer_ticker_list_regenerated(tmp_path):
    proj = _mkproject(tmp_path)
    ps.add_holding(proj, "me", "AAPL", 10, 150.0,
                   category="Category 1: ETF (Core)")
    ps.remove_holding(proj, "me", "QQQ")
    text = (tmp_path / "portfolios" / "me.md").read_text(encoding="utf-8")
    # 코드펜스 안의 목록에 AAPL 추가 / QQQ 제거
    fence = text.split("```")[1]
    assert "AAPL" in fence
    assert "QQQ" not in fence.split()


def test_roundtrip_preserves_untouched_values(tmp_path):
    proj = _mkproject(tmp_path)
    # 아무것도 편집하지 않은 종목(QQQ)의 평가금액/수익금액 텍스트가 보존되는지
    ps.update_holding(proj, "me", "VOO", avg_cost=500.0)
    text = (tmp_path / "portfolios" / "me.md").read_text(encoding="utf-8")
    assert "$25,000.00" in text  # QQQ 평가금액 보존
    assert "-$5,000.00" in text  # QQQ 수익금액 보존


def test_parse_holdings_from_path_reads_new_column(tmp_path):
    proj = _mkproject(tmp_path)
    # 평균단가 직접 입력 → 재파싱 시 그 값 사용(역산 아님)
    ps.update_holding(proj, "me", "VOO", avg_cost=123.45)
    path = str(tmp_path / "portfolios" / "me.md")
    rows = ps.parse_holdings_from_path(path)
    voo = next(r for r in rows if r["ticker"] == "VOO")
    assert round(voo["avg_cost"], 2) == 123.45
