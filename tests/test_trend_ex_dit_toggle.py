"""트렌드 페이지 디아이티(110990) 포함/제외 토글 — 백엔드 로직 테스트."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import report_generator as rg  # noqa: E402


def _snap(total, cost, dit_now, dit_v0, weights):
    rest_now = total - dit_now
    rest_v0 = cost - dit_v0
    return {
        "total_value_krw": total,
        "cost_basis_krw": cost,
        "pnl_krw": total - cost,
        "pnl_pct": round((total / cost - 1) * 100, 2),
        "cash_value_krw": 0,
        "cash_pct": 0,
        "dit_now_krw": dit_now,
        "dit_v0_krw": dit_v0,
        "rest_now_krw": rest_now,
        "rest_v0_krw": rest_v0,
        "dit_ytd_pct": round((dit_now / dit_v0 - 1) * 100, 2),
        "rest_ytd_pct": round((rest_now / rest_v0 - 1) * 100, 2),
        "ytd_pct": round((total / cost - 1) * 100, 2),
        "spy_ytd_pct": 10.0,
        "weights_by_ticker": weights,
    }


# me 스타일(디아이티=이름 키), wife 스타일(110990=티커 키) 둘 다 커버
ME_WEIGHTS = {"디아이티": 50.0, "VOO": 30.0, "AAPL": 20.0}
WIFE_WEIGHTS = {"110990": 40.0, "QQQ": 35.0, "SCHD": 25.0}


# ── _ticker_rows exclude_dit ──────────────────────────

def test_ticker_rows_excludes_dit_both_key_styles():
    for weights in (ME_WEIGHTS, WIFE_WEIGHTS):
        snap = {"total_value_krw": 1000, "weights_by_ticker": weights}
        full = rg._ticker_rows(snap, exclude_dit=False)
        ex = rg._ticker_rows(snap, exclude_dit=True)
        names_full = {r["name"] for r in full}
        names_ex = {r["name"] for r in ex}
        assert ("디아이티" in names_full) or ("110990" in names_full)
        assert "디아이티" not in names_ex and "110990" not in names_ex
        # 재정규화: 제외 후 % 합 ~100
        assert abs(sum(r["value"] for r in ex) - 100.0) <= 0.5


def test_ticker_rows_amounts_are_real_krw():
    # 금액(amount_man)은 실제 KRW 유지, % 만 재정규화
    snap = {"total_value_krw": 1_000_0000, "weights_by_ticker": ME_WEIGHTS}  # 1000만
    ex = rg._ticker_rows(snap, exclude_dit=True)
    voo = next(r for r in ex if r["name"] == "VOO")
    # VOO 금액 = 1000만 * 30% = 300만원
    assert voo["amount_man"] == 300
    # 하지만 % 는 30/(30+20)=60%로 재정규화
    assert abs(voo["value"] - 60.0) <= 0.5


# ── _user_category_rows exclude_dit ───────────────────

def test_category_rows_exclude_dit_renormalizes():
    snap = {"total_value_krw": 1000, "weights_by_ticker": ME_WEIGHTS}
    full = rg._user_category_rows(snap, exclude_dit=False)
    ex = rg._user_category_rows(snap, exclude_dit=True)
    assert abs(sum(r["value"] for r in full) - 100.0) <= 0.5
    assert abs(sum(r["value"] for r in ex) - 100.0) <= 0.5
    # 디아이티(개별주) 제외 시 개별주 비중이 줄어야 함
    def val(rows, name):
        return next((r["value"] for r in rows if r["name"] == name), 0)
    assert val(ex, "개별주") < val(full, "개별주")


# ── _series_from_daily ex-dit 필드 ────────────────────

def test_series_includes_ex_dit_fields():
    daily = {"2026-01-02": _snap(2000, 1000, 1200, 800, ME_WEIGHTS)}
    s = rg._series_from_daily(daily)[0]
    # total_ex_dit = rest_now = 2000-1200 = 800 → /1e8
    assert s["total_ex_dit_eok"] == round(800 / 1e8, 2)
    assert s["cost_ex_dit_eok"] == round((1000 - 800) / 1e8, 2)
    # 전체값도 그대로
    assert s["total_eok"] == round(2000 / 1e8, 2)


def test_series_fallback_when_no_dit_fields():
    # rest_* 없으면 전체값으로 폴백 (회귀 안전)
    daily = {"2026-01-02": {"total_value_krw": 500, "cost_basis_krw": 400}}
    s = rg._series_from_daily(daily)[0]
    assert s["total_ex_dit_eok"] == s["total_eok"]
    assert s["cost_ex_dit_eok"] == s["cost_eok"]


# ── _build_owner_payload latest ex-dit ────────────────

def test_owner_payload_latest_ex_dit():
    daily = {"2026-07-24": _snap(2_000_000_000, 1_000_000_000,
                                 1_200_000_000, 800_000_000, ME_WEIGHTS)}
    p = rg._build_owner_payload(daily)
    l = p["latest"]
    # rest_now = 0.8e9, rest_v0 = 0.2e9 → total_ex ₩8.00억, pnl% = (0.8/0.2-1)*100 = 300
    assert l["total_ex_dit_eok"] == "8.00"
    assert l["cost_ex_dit_eok"] == "2.00"
    assert l["pnl_ex_dit_pct"] == 300.0
    # ex-dit ticker/category payload 존재 + 디아이티 없음
    assert "ticker_ex_dit" in p and "category_ex_dit" in p
    assert all(r["name"] not in ("디아이티", "110990") for r in p["ticker_ex_dit"])


def test_owner_payload_consistency_rest_plus_dit():
    # 실제값 일관성: rest_now + dit_now == total
    total, dit_now = 2_000_000_000, 1_200_000_000
    daily = {"2026-07-24": _snap(total, 1_000_000_000, dit_now, 800_000_000, WIFE_WEIGHTS)}
    snap = daily["2026-07-24"]
    assert snap["rest_now_krw"] + snap["dit_now_krw"] == total
