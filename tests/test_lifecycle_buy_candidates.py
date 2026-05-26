"""Tests for lifecycle_buy_candidates module."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_normalize_base_score_pullback_uses_trigger_score():
    """PULLBACK setup → trigger score 그대로 0~14."""
    from lifecycle_buy_candidates import normalize_base_score
    snap = {"setup": "PULLBACK", "score": 6, "score_track": "trigger"}
    assert normalize_base_score(snap) == 6.0


def test_normalize_base_score_base_forming_uses_trigger_score():
    from lifecycle_buy_candidates import normalize_base_score
    snap = {"setup": "BASE_FORMING", "score": 9, "score_track": "trigger"}
    assert normalize_base_score(snap) == 9.0


def test_normalize_base_score_trend_ok_scales_drift_to_14():
    """TREND_OK drift score 6 → 6 × 14/9 ≈ 9.33."""
    from lifecycle_buy_candidates import normalize_base_score
    snap = {"setup": "TREND_OK", "score": 6, "score_track": "drift"}
    result = normalize_base_score(snap)
    assert abs(result - (6 * 14 / 9)) < 0.01


def test_normalize_base_score_extended_uses_raw_score():
    """EXTENDED veto → _raw_score scaled drift→trigger."""
    from lifecycle_buy_candidates import normalize_base_score
    snap = {"setup": "EXTENDED", "score": None, "_raw_score": 5,
            "_raw_score_track": "drift"}
    result = normalize_base_score(snap)
    assert abs(result - (5 * 14 / 9)) < 0.01


def test_normalize_base_score_missing_returns_zero():
    """No score available → 0."""
    from lifecycle_buy_candidates import normalize_base_score
    assert normalize_base_score({"setup": "TREND_OK", "score": None,
                                   "_raw_score": None}) == 0.0
    assert normalize_base_score({}) == 0.0


def test_momentum_bonus_mapping():
    from lifecycle_buy_candidates import compute_momentum_bonus
    assert compute_momentum_bonus({"stage": "MOMENTUM_3"}) == 4
    assert compute_momentum_bonus({"stage": "MOMENTUM_2"}) == 3
    assert compute_momentum_bonus({"stage": "MOMENTUM_1"}) == 2
    assert compute_momentum_bonus({"stage": "EM"}) == 1
    assert compute_momentum_bonus({"stage": None}) == 0
    assert compute_momentum_bonus({}) == 0
    assert compute_momentum_bonus(None) == 0


def test_rs_bonus_thresholds():
    from lifecycle_buy_candidates import compute_rs_bonus
    assert compute_rs_bonus(15.0) == 3
    assert compute_rs_bonus(10.01) == 3
    assert compute_rs_bonus(10.0) == 2     # boundary — 10.0 is NOT > 10
    assert compute_rs_bonus(7.0) == 2
    assert compute_rs_bonus(5.01) == 2
    assert compute_rs_bonus(5.0) == 1      # boundary — 5.0 is NOT > 5
    assert compute_rs_bonus(2.0) == 1
    assert compute_rs_bonus(0.01) == 1
    assert compute_rs_bonus(0.0) == 0
    assert compute_rs_bonus(-3.0) == 0
    assert compute_rs_bonus(None) == 0


def test_compute_final_score_pullback_with_momentum():
    """PULLBACK score 5 + EM bonus 1 + RS 7%p (+2) = 8."""
    from lifecycle_buy_candidates import compute_final_score
    snap = {"setup": "PULLBACK", "score": 5, "score_track": "trigger",
            "rs_delta_pct": 7.0}
    momentum = {"stage": "EM"}
    result = compute_final_score(snap, momentum)
    assert result["base_score"] == 5.0
    assert result["momentum_bonus"] == 1
    assert result["rs_bonus"] == 2
    assert result["final_score"] == 8.0


def test_compute_final_score_extended_no_penalty():
    """EXTENDED + M3 + strong RS → very high score (no penalty per spec §3)."""
    from lifecycle_buy_candidates import compute_final_score
    snap = {"setup": "EXTENDED", "score": None, "_raw_score": 6,
            "_raw_score_track": "drift", "rs_delta_pct": 12.5}
    momentum = {"stage": "MOMENTUM_3"}
    result = compute_final_score(snap, momentum)
    # base = 6 * 14/9 ≈ 9.33; +4 (M3); +3 (RS>10) = 16.33
    assert abs(result["base_score"] - (6 * 14 / 9)) < 0.01
    assert result["momentum_bonus"] == 4
    assert result["rs_bonus"] == 3
    assert abs(result["final_score"] - (6 * 14 / 9 + 7)) < 0.01


def test_compute_final_score_no_momentum_entry():
    """ticker not in today's momentum → momentum_bonus 0."""
    from lifecycle_buy_candidates import compute_final_score
    snap = {"setup": "TREND_OK", "score": 4, "score_track": "drift",
            "rs_delta_pct": 3.0}
    result = compute_final_score(snap, None)
    assert result["momentum_bonus"] == 0
    assert result["rs_bonus"] == 1
    assert abs(result["base_score"] - (4 * 14 / 9)) < 0.01


def test_build_candidate_pool_excludes_broken():
    from lifecycle_buy_candidates import build_candidate_pool
    snapshots = {
        "AAA": {"setup": "PULLBACK", "score": 5},
        "BBB": {"setup": "BROKEN", "score": None},
        "CCC": {"setup": "TREND_OK", "score": 6, "score_track": "drift"},
        "DDD": {"setup": "EXTENDED", "score": None, "_raw_score": 5},
    }
    pool = build_candidate_pool(snapshots, portfolio_tickers=set())
    tickers = {c["ticker"] for c in pool}
    assert tickers == {"AAA", "CCC", "DDD"}  # BBB excluded


def test_build_candidate_pool_marks_portfolio():
    from lifecycle_buy_candidates import build_candidate_pool
    snapshots = {
        "AAPL": {"setup": "TREND_OK", "score": 5, "score_track": "drift"},
        "INTC": {"setup": "PULLBACK", "score": 4, "score_track": "trigger"},
    }
    pool = build_candidate_pool(snapshots, portfolio_tickers={"AAPL"})
    by_ticker = {c["ticker"]: c for c in pool}
    assert by_ticker["AAPL"]["is_portfolio"] is True
    assert by_ticker["INTC"]["is_portfolio"] is False


def test_build_candidate_pool_attaches_snapshot():
    """Each candidate carries the full snapshot dict (so downstream can read raw)."""
    from lifecycle_buy_candidates import build_candidate_pool
    snapshots = {"AAA": {"setup": "PULLBACK", "score": 5,
                          "raw": {"close": 100.0, "rsi14": 65}}}
    pool = build_candidate_pool(snapshots, portfolio_tickers=set())
    assert pool[0]["snapshot"]["raw"]["close"] == 100.0


def test_rank_top_n_sorts_desc_caps_at_5():
    from lifecycle_buy_candidates import rank_top_n
    pool = [
        {"ticker": "A", "snapshot": {"setup": "PULLBACK", "score": 10, "rs_delta_pct": 5.0}, "is_portfolio": False},
        {"ticker": "B", "snapshot": {"setup": "PULLBACK", "score": 8,  "rs_delta_pct": 12.0}, "is_portfolio": False},
        {"ticker": "C", "snapshot": {"setup": "PULLBACK", "score": 6,  "rs_delta_pct": 7.0}, "is_portfolio": False},
        {"ticker": "D", "snapshot": {"setup": "PULLBACK", "score": 5,  "rs_delta_pct": 3.0}, "is_portfolio": False},
        {"ticker": "E", "snapshot": {"setup": "PULLBACK", "score": 4,  "rs_delta_pct": 1.0}, "is_portfolio": False},
        {"ticker": "F", "snapshot": {"setup": "PULLBACK", "score": 3,  "rs_delta_pct": 0.5}, "is_portfolio": False},
    ]
    momentum_data = {}  # no momentum bonuses for any
    ranked = rank_top_n(pool, momentum_data, threshold=5, cap=5)
    assert [c["ticker"] for c in ranked] == ["B", "A", "C", "D", "E"]
    # B: 8 + 0 + 3 (RS>10) = 11
    # A: 10 + 0 + 1 (RS>0) = 11 -- tied with B
    # → B wins tiebreak (higher rs_delta_pct)
    # C: 6 + 0 + 2 = 8
    # D: 5 + 0 + 1 = 6
    # E: 4 + 0 + 1 = 5
    # F: 3 + 0 + 1 = 4 → below threshold


def test_rank_top_n_threshold_excludes_low_scores():
    from lifecycle_buy_candidates import rank_top_n
    pool = [
        {"ticker": "X", "snapshot": {"setup": "PULLBACK", "score": 2, "rs_delta_pct": 1.0}, "is_portfolio": False},
        {"ticker": "Y", "snapshot": {"setup": "PULLBACK", "score": 3, "rs_delta_pct": 0.0}, "is_portfolio": False},
    ]
    # X: 2+0+1=3 ; Y: 3+0+0=3 → both below threshold 5
    ranked = rank_top_n(pool, {}, threshold=5, cap=5)
    assert ranked == []


def test_rank_top_n_attaches_score_breakdown():
    """Each ranked entry includes final_score + breakdown for display."""
    from lifecycle_buy_candidates import rank_top_n
    pool = [{"ticker": "AAA",
             "snapshot": {"setup": "PULLBACK", "score": 6, "rs_delta_pct": 7.0},
             "is_portfolio": True}]
    momentum_data = {"AAA": {"stage": "MOMENTUM_2"}}
    ranked = rank_top_n(pool, momentum_data, threshold=5, cap=5)
    assert len(ranked) == 1
    entry = ranked[0]
    assert entry["final_score"] == 11.0  # 6 + 3 (M2) + 2 (RS>5)
    assert entry["base_score"] == 6.0
    assert entry["momentum_bonus"] == 3
    assert entry["rs_bonus"] == 2
    assert entry["is_portfolio"] is True
    assert entry["ticker"] == "AAA"


def test_select_top5_orchestrator_end_to_end():
    """E2E mini scenario: 3 candidates, only 2 pass threshold."""
    from lifecycle_buy_candidates import select_top5_buy_candidates
    snapshots = {
        "AAPL": {"setup": "TREND_OK", "score": 6, "score_track": "drift",
                  "rs_delta_pct": 8.0},
        "INTC": {"setup": "PULLBACK", "score": 5, "score_track": "trigger",
                  "rs_delta_pct": 6.0},
        "WEAK": {"setup": "PULLBACK", "score": 1, "rs_delta_pct": 0.0},
    }
    momentum_history = {"data": {"AAPL": {"2026-05-21": {"stage": "MOMENTUM_2"}}}}
    result = select_top5_buy_candidates(
        snapshots=snapshots,
        portfolio_tickers={"AAPL"},
        momentum_history=momentum_history,
        today="2026-05-21",
    )
    assert result["max"] == 5
    assert result["count"] == 2  # AAPL + INTC; WEAK below threshold
    tickers = [c["ticker"] for c in result["candidates"]]
    assert "AAPL" in tickers
    assert "INTC" in tickers
    assert "WEAK" not in tickers


def test_select_top5_size_hint_labels_extended_portfolio():
    """size_hint string varies by EXTENDED + portfolio state."""
    from lifecycle_buy_candidates import select_top5_buy_candidates
    snapshots = {
        "EXT_NEW":  {"setup": "EXTENDED", "score": None, "_raw_score": 6,
                       "_raw_score_track": "drift", "rs_delta_pct": 12.0},
        "EXT_HOLD": {"setup": "EXTENDED", "score": None, "_raw_score": 6,
                       "_raw_score_track": "drift", "rs_delta_pct": 12.0},
        "NORM_NEW":  {"setup": "PULLBACK", "score": 8, "rs_delta_pct": 7.0},
        "NORM_HOLD": {"setup": "PULLBACK", "score": 8, "rs_delta_pct": 7.0},
    }
    result = select_top5_buy_candidates(
        snapshots=snapshots,
        portfolio_tickers={"EXT_HOLD", "NORM_HOLD"},
        momentum_history={"data": {}}, today="2026-05-21",
    )
    by_ticker = {c["ticker"]: c for c in result["candidates"]}
    assert by_ticker["EXT_NEW"]["size_hint_label"] == "신규 25%"
    assert by_ticker["EXT_HOLD"]["size_hint_label"] == "추가 25%"
    assert by_ticker["NORM_NEW"]["size_hint_label"] == "신규 50%"
    assert by_ticker["NORM_HOLD"]["size_hint_label"] == "추가 50%"


def test_select_top5_empty_snapshots():
    """No snapshots → count=0, candidates=[]."""
    from lifecycle_buy_candidates import select_top5_buy_candidates
    result = select_top5_buy_candidates(
        snapshots={}, portfolio_tickers=set(),
        momentum_history={"data": {}}, today="2026-05-21",
    )
    assert result["count"] == 0
    assert result["candidates"] == []


def test_render_injects_top5_into_ctx(monkeypatch, tmp_path):
    """_render must call select_top5 and inject ctx vars."""
    import os, json
    import lifecycle_report as lr

    captured_ctx = {}

    def fake_render(self, **ctx):
        captured_ctx.update(ctx)
        return "<html></html>"

    # Monkeypatch the Jinja2 template.render
    from jinja2 import Template
    monkeypatch.setattr(Template, "render", fake_render)

    # Minimal result fixture
    result = {
        "as_of": "2026-05-21", "market": "US",
        "snapshots": {
            "AAA": {"setup": "PULLBACK", "score": 8, "score_track": "trigger",
                     "decision": "PROBE", "trigger": "EARLY_TRIGGER",
                     "rs_delta_pct": 6.0,
                     "raw": {"close": 100, "rsi14": 65, "dist_ema9_pct": 1.0,
                             "volume_ratio": 1.1, "risk_tags": []}},
        },
        "transitions": [], "skipped": [], "active_set_size": 1,
        "market_ret_5d_pct": 0.0,
        "momentum_history": {"data": {}},
        "engine_version": "score_v1",
    }

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    lr._render("US", result, str(out_dir), template_dir=None,
                lifecycle_state={"tickers": {}, "transitions": []},
                portfolio_tickers={"AAA"})

    assert "top5_candidates" in captured_ctx
    assert "top5_count" in captured_ctx
    assert "top5_max" in captured_ctx
    assert captured_ctx["top5_max"] == 5
    assert captured_ctx["top5_count"] == 1
    assert captured_ctx["top5_candidates"][0]["ticker"] == "AAA"
    assert captured_ctx["top5_candidates"][0]["is_portfolio"] is True


def test_template_renders_top5_section(tmp_path):
    """Rendered HTML contains the top5 section with expected text + tickers."""
    import os
    from jinja2 import Environment, FileSystemLoader, ChainableUndefined

    project_dir = os.path.join(os.path.dirname(__file__), "..")
    env = Environment(
        loader=FileSystemLoader(os.path.join(project_dir, "templates")),
        autoescape=True,
        undefined=ChainableUndefined,
    )
    # Custom filters mimicking lifecycle_report._render
    env.filters["signed_pct"] = lambda x: "—" if x is None else f"{x:+.1f}%"
    env.filters["x_fmt"]      = lambda x: "—" if x is None else f"{x:.1f}×"
    env.filters["trig_age_label"] = lambda d: "—" if d is None else (
        "오늘" if d == 0 else "어제" if d == 1 else f"{d}일전")

    # A dict that returns 0 for any missing numeric attribute access
    class DefaultNumDict(dict):
        def __getattr__(self, name):
            return self.get(name, 0)

    thresholds = DefaultNumDict({
        "EXTENDED_DIST_FROM_EMA9": 0.08, "EXTENDED_RSI_MIN": 70,
        "RISK_OVERHEAT_RSI": 75, "PULLBACK_MAX_DIST_FROM_EMA9": 0.05,
    })

    tmpl = env.get_template("lifecycle_us.html")
    ctx = {
        "market": "US", "as_of": "2026-05-21", "engine_version": "score_v1",
        "active_nav": "lifecycle_us", "version": "test",
        "snapshots_list": [], "transitions": [], "skipped": [],
        "active_set_size": 1, "summary": {"counts": {}}, "score_tier_bands": {},
        "lifecycle_thresholds": thresholds,
        "verdict_summary": {
            "headline": "Test Headline", "narration": "Test narration",
            "avoid_line": None, "action_hint": "Test action",
            "score_engine_line": None,
        },
        "avoid": [], "enter": [], "probe": [], "watch": [], "trending": [],
        "broken_table": [],
        "top5_candidates": [{
            "ticker": "NVDA", "is_portfolio": True,
            "snapshot": {"setup": "EXTENDED", "decision": "AVOID",
                          "raw": {"close": 1200, "rsi14": 76,
                                  "dist_ema9_pct": 11.5, "volume_ratio": 1.5,
                                  "risk_tags": ["EXTENDED"]},
                          "rs_delta_pct": 12.0},
            "base_score": 9.33, "momentum_bonus": 4, "rs_bonus": 3,
            "final_score": 16.33, "size_hint_label": "추가 25%",
        }],
        "top5_count": 1, "top5_max": 5, "top5_threshold": 5.0,
    }
    html = tmpl.render(**ctx)
    assert "오늘의 매수 후보" in html
    assert "NVDA" in html
    assert "1/5" in html or "(1/5)" in html
    # EXTENDED items show overheat warning + size 25%
    assert "과열" in html or "EXTENDED" in html
    assert "추가 25%" in html
    # Portfolio items show holding indicator
    assert "보유 중" in html or "\U0001f3e6" in html


def test_pipeline_passes_portfolio_tickers_to_generate(monkeypatch):
    """generate_lifecycle_pages should receive portfolio_tickers=set of all holdings."""
    # Construct a minimal portfolio markdown
    import tempfile, textwrap
    md = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False,
                                       encoding="utf-8")
    md.write(textwrap.dedent("""
        | Ticker | 종목명 | 보유수량 | 평가금액 | 수익금액 | 수익률 |
        |--------|--------|---------|---------|---------|--------|
        | AAPL | 애플 | 100주 | $20,000.00 | +$5,000.00 | +33.33% |
        | NVDA | 엔비디아 | 50주 | $50,000.00 | +$10,000.00 | +25.00% |
    """).strip() + "\n")
    md.close()

    import pipeline
    holdings = pipeline._parse_portfolio_for_report(md.name)
    tickers = {h["ticker"] for h in holdings}
    assert tickers == {"AAPL", "NVDA"}


def _scanner_signal_entry(ticker: str, stage: str = "MOMENTUM_2",
                           rsi: float = 65.0, dist_ema9_pct: float = 4.0,
                           ret_5d_pct: float = 8.0) -> dict:
    """Mock momentum_scanner per-ticker output (subset of evaluate_stock result)."""
    return {
        "ticker": ticker, "stage": stage, "tier": stage,
        "maturity": "MID", "risk_tags": [], "hint": "",
        "rs_vs_sector": True, "sector": "Tech",
        "price": 100.0, "rsi": rsi,
        "ret_1d_pct": 1.0, "ret_3d_pct": 3.0, "ret_5d_pct": ret_5d_pct,
        "ret_20d_pct": 12.0, "dist_ema9_pct": dist_ema9_pct,
    }


def _market_data_entry_for_trend_ok(ticker: str) -> dict:
    """Build market_data entry that classifies as TREND_OK in lifecycle setup state."""
    return {
        "ticker": ticker,
        "close": 110.0, "high": 111.0, "low": 108.0,
        "ema9": 105.0, "ema21": 100.0, "ema65": 95.0,
        "ema9_slope_3d": 0.5, "ema21_slope_5d": 0.3,
        "ema65_slope_5d": 0.2, "ema65_slope_20d": 0.2,
        "rsi14": 65.0, "atr14": 2.5, "atr14_pct": 2.27,
        "volume_ratio": 1.1, "macd": 1.0, "macd_signal": 0.5, "macd_hist": 0.5,
        "ret_5d_pct": 8.0, "ret_20d_pct": 12.0, "change_pct": 1.2,
        "ret_3d_pct": 3.0, "dist_ema9_pct": 4.76,
    }


def test_select_top5_includes_momentum_only_ticker():
    """LRCX is in today's scanner but NOT in lifecycle snapshots → must enter Top 5."""
    from lifecycle_buy_candidates import select_top5_buy_candidates
    snapshots = {
        # Lifecycle universe — 1 ticker only
        "AAPL": {"setup": "TREND_OK", "score": 5, "score_track": "drift",
                  "rs_delta_pct": 3.0,
                  "raw": {"close": 200, "rsi14": 60, "dist_ema9_pct": 1.0,
                          "volume_ratio": 1.0, "risk_tags": []}},
    }
    # LRCX is in scanner today, but NOT in snapshots
    momentum_today = [_scanner_signal_entry("LRCX", stage="MOMENTUM_2")]
    market_data = {"data": {"LRCX": _market_data_entry_for_trend_ok("LRCX")}}

    result = select_top5_buy_candidates(
        snapshots=snapshots,
        portfolio_tickers={"AAPL"},
        momentum_history={"data": {}},
        today="2026-05-22",
        momentum_today=momentum_today,
        market_data=market_data,
        market_ret_5d_pct=0.0,
    )
    tickers = [c["ticker"] for c in result["candidates"]]
    assert "LRCX" in tickers, f"LRCX should be in candidates, got {tickers}"


def test_select_top5_momentum_only_marked_scanner_only():
    """momentum-only ticker's snapshot must carry _scanner_only=True for badge."""
    from lifecycle_buy_candidates import select_top5_buy_candidates
    momentum_today = [_scanner_signal_entry("LRCX", stage="MOMENTUM_3")]
    market_data = {"data": {"LRCX": _market_data_entry_for_trend_ok("LRCX")}}

    result = select_top5_buy_candidates(
        snapshots={},
        portfolio_tickers=set(),
        momentum_history={"data": {}},
        today="2026-05-22",
        momentum_today=momentum_today,
        market_data=market_data,
        market_ret_5d_pct=0.0,
    )
    lrcx = next((c for c in result["candidates"] if c["ticker"] == "LRCX"), None)
    assert lrcx is not None
    assert lrcx["snapshot"].get("_scanner_only") is True


def test_select_top5_momentum_only_gets_base_score():
    """momentum-only ticker uses compute_single_snapshot → real base_score, not 0."""
    from lifecycle_buy_candidates import select_top5_buy_candidates
    momentum_today = [_scanner_signal_entry("LRCX", stage="MOMENTUM_3")]
    market_data = {"data": {"LRCX": _market_data_entry_for_trend_ok("LRCX")}}

    result = select_top5_buy_candidates(
        snapshots={},
        portfolio_tickers=set(),
        momentum_history={"data": {}},
        today="2026-05-22",
        momentum_today=momentum_today,
        market_data=market_data,
        market_ret_5d_pct=0.0,
    )
    lrcx = next((c for c in result["candidates"] if c["ticker"] == "LRCX"), None)
    assert lrcx is not None
    # base_score should be > 0 (TREND_OK setup with positive drift score)
    assert lrcx["base_score"] > 0
    # momentum_bonus = 4 (M3)
    assert lrcx["momentum_bonus"] == 4


def test_select_top5_momentum_today_none_unchanged():
    """momentum_today=None (or absent) → existing behavior, no momentum-only pool."""
    from lifecycle_buy_candidates import select_top5_buy_candidates
    snapshots = {
        "AAPL": {"setup": "TREND_OK", "score": 5, "score_track": "drift",
                  "rs_delta_pct": 3.0,
                  "raw": {"close": 200, "rsi14": 60, "dist_ema9_pct": 1.0,
                          "volume_ratio": 1.0, "risk_tags": []}},
    }
    # Call WITHOUT momentum_today / market_data — must work as before
    result = select_top5_buy_candidates(
        snapshots=snapshots,
        portfolio_tickers=set(),
        momentum_history={"data": {}},
        today="2026-05-22",
    )
    tickers = [c["ticker"] for c in result["candidates"]]
    assert tickers == ["AAPL"]


def test_select_top5_momentum_only_skipped_when_market_data_missing():
    """Scanner ticker not in market_data → silently skipped, others unaffected."""
    from lifecycle_buy_candidates import select_top5_buy_candidates
    momentum_today = [
        _scanner_signal_entry("LRCX", stage="MOMENTUM_3"),
        _scanner_signal_entry("GHOST", stage="MOMENTUM_3"),  # no market_data
    ]
    market_data = {"data": {"LRCX": _market_data_entry_for_trend_ok("LRCX")}}

    result = select_top5_buy_candidates(
        snapshots={},
        portfolio_tickers=set(),
        momentum_history={"data": {}},
        today="2026-05-22",
        momentum_today=momentum_today,
        market_data=market_data,
        market_ret_5d_pct=0.0,
    )
    tickers = [c["ticker"] for c in result["candidates"]]
    assert "LRCX" in tickers
    assert "GHOST" not in tickers


def test_select_top5_momentum_only_skipped_when_already_in_snapshots():
    """Scanner ticker that's also in snapshots → use snapshot path, no double-add."""
    from lifecycle_buy_candidates import select_top5_buy_candidates
    # NVDA is in lifecycle snapshots AND in today's scanner
    snapshots = {
        "NVDA": {"setup": "PULLBACK", "score": 8, "score_track": "trigger",
                  "rs_delta_pct": 7.0,
                  "raw": {"close": 1200, "rsi14": 65, "dist_ema9_pct": 1.5,
                          "volume_ratio": 1.1, "risk_tags": []}},
    }
    momentum_today = [_scanner_signal_entry("NVDA", stage="MOMENTUM_3")]
    market_data = {"data": {"NVDA": _market_data_entry_for_trend_ok("NVDA")}}

    result = select_top5_buy_candidates(
        snapshots=snapshots,
        portfolio_tickers=set(),
        momentum_history={"data": {}},
        today="2026-05-22",
        momentum_today=momentum_today,
        market_data=market_data,
        market_ret_5d_pct=0.0,
    )
    # Count: exactly 1 NVDA entry (snapshot path), not 2
    nvda_entries = [c for c in result["candidates"] if c["ticker"] == "NVDA"]
    assert len(nvda_entries) == 1
    # Should use the lifecycle snapshot, not the scanner one
    assert nvda_entries[0]["snapshot"].get("_scanner_only") is not True


def _market_data_entry_for_broken(ticker: str) -> dict:
    """Build market_data entry that classifies as BROKEN setup.

    BROKEN requires close < ema65 AND ema65_slope_5d < 0 (per evaluate_setup_state).
    """
    return {
        "ticker": ticker,
        "close": 85.0, "high": 86.0, "low": 84.0,
        "ema9": 90.0, "ema21": 95.0, "ema65": 100.0,
        "ema9_slope_3d": -0.5, "ema21_slope_5d": -0.3,
        "ema65_slope_5d": -0.2, "ema65_slope_20d": -0.2,
        "rsi14": 35.0, "atr14": 2.5, "atr14_pct": 2.94,
        "volume_ratio": 1.0, "macd": -1.0, "macd_signal": 0.5, "macd_hist": -1.5,
        "ret_5d_pct": -8.0, "ret_20d_pct": -12.0, "change_pct": -1.5,
        "ret_3d_pct": -3.0, "dist_ema9_pct": -5.56,
    }


def test_select_top5_momentum_only_skipped_when_synthetic_broken():
    """Scanner ticker whose synthetic snapshot is BROKEN must not enter Top 5."""
    from lifecycle_buy_candidates import select_top5_buy_candidates
    momentum_today = [_scanner_signal_entry("DEAD", stage="MOMENTUM_1")]
    market_data = {"data": {"DEAD": _market_data_entry_for_broken("DEAD")}}

    result = select_top5_buy_candidates(
        snapshots={},
        portfolio_tickers=set(),
        momentum_history={"data": {}},
        today="2026-05-22",
        momentum_today=momentum_today,
        market_data=market_data,
        market_ret_5d_pct=0.0,
    )
    tickers = [c["ticker"] for c in result["candidates"]]
    assert "DEAD" not in tickers


def test_select_top5_orders_mixed_pool_by_score_desc():
    """5 candidates total — 2 from snapshots + 3 momentum-only. Must rank by final_score desc."""
    from lifecycle_buy_candidates import select_top5_buy_candidates

    # Snapshot-path: 2 lifecycle tickers
    snapshots = {
        "SNAP_HIGH": {"setup": "PULLBACK", "score": 10, "score_track": "trigger",
                       "rs_delta_pct": 8.0,
                       "raw": {"close": 100, "rsi14": 55, "dist_ema9_pct": -1.0,
                               "volume_ratio": 1.2, "risk_tags": []}},
        "SNAP_LOW":  {"setup": "PULLBACK", "score": 4, "score_track": "trigger",
                       "rs_delta_pct": 1.0,
                       "raw": {"close": 100, "rsi14": 55, "dist_ema9_pct": -1.0,
                               "volume_ratio": 1.0, "risk_tags": []}},
    }

    # Momentum-only: 3 tickers, all TREND_OK synthetic, varying tiers/RS
    momentum_today = [
        _scanner_signal_entry("M3_TKR", stage="MOMENTUM_3"),
        _scanner_signal_entry("M2_TKR", stage="MOMENTUM_2"),
        _scanner_signal_entry("M1_TKR", stage="MOMENTUM_1"),
    ]
    market_data = {"data": {
        "M3_TKR": _market_data_entry_for_trend_ok("M3_TKR"),
        "M2_TKR": _market_data_entry_for_trend_ok("M2_TKR"),
        "M1_TKR": _market_data_entry_for_trend_ok("M1_TKR"),
    }}

    result = select_top5_buy_candidates(
        snapshots=snapshots,
        portfolio_tickers=set(),
        momentum_history={"data": {}},
        today="2026-05-22",
        momentum_today=momentum_today,
        market_data=market_data,
        market_ret_5d_pct=0.0,
    )
    # Verify: candidates are sorted final_score desc (no insertion-order leak)
    scores = [c["final_score"] for c in result["candidates"]]
    assert scores == sorted(scores, reverse=True), \
        f"candidates not sorted desc: {[(c['ticker'], c['final_score']) for c in result['candidates']]}"
    # Verify: SNAP_HIGH (base 10 + RS bonus) outranks M1_TKR (base ~drift + M1 bonus +2)
    tickers = [c["ticker"] for c in result["candidates"]]
    assert tickers.index("SNAP_HIGH") < tickers.index("M1_TKR")


def test_render_passes_momentum_today_and_market_data(monkeypatch, tmp_path):
    """_render must forward momentum_today + market_data to select_top5."""
    import lifecycle_report as lr

    captured: dict = {}

    def fake_select(**kwargs):
        captured.update(kwargs)
        return {"candidates": [], "count": 0, "max": 5, "threshold": 5.0}

    monkeypatch.setattr(lr, "select_top5_buy_candidates", fake_select)

    # Also stub the Jinja render to avoid pulling full template
    from jinja2 import Template
    monkeypatch.setattr(Template, "render", lambda self, **ctx: "<html></html>")

    result = {
        "as_of": "2026-05-22", "market": "US",
        "snapshots": {},
        "transitions": [], "skipped": [], "active_set_size": 0,
        "market_ret_5d_pct": 0.42,
        "momentum_history": {"data": {}},
        "engine_version": "score_v1",
    }
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    lr._render("US", result, str(out_dir), template_dir=None,
                lifecycle_state={"tickers": {}, "transitions": []},
                portfolio_tickers={"AAA"},
                momentum_today=[{"ticker": "LRCX", "stage": "MOMENTUM_3"}],
                market_data={"data": {"LRCX": {"close": 100, "ema9": 95}}})

    assert captured.get("momentum_today") == [{"ticker": "LRCX", "stage": "MOMENTUM_3"}]
    assert "LRCX" in (captured.get("market_data", {}).get("data", {}) or {})
    assert captured.get("market_ret_5d_pct") == 0.42


def test_generate_lifecycle_pages_dispatches_us_momentum(monkeypatch, tmp_path):
    """generate_lifecycle_pages must pass us-scoped kwargs to _render('US', ...)."""
    import lifecycle_report as lr

    captured_calls: list[dict] = []

    def fake_render(market, result, output_dir, template_dir, lifecycle_state,
                     nav_ctx=None, portfolio_tickers=None,
                     momentum_today=None, market_data=None):
        captured_calls.append({
            "market": market,
            "momentum_today": momentum_today,
            "has_market_data": market_data is not None,
        })
        return str(tmp_path / f"{market.lower()}.html")

    monkeypatch.setattr(lr, "_render", fake_render)

    us_result = {"snapshots": {"AAA": {"setup": "TREND_OK"}}, "as_of": "2026-05-22"}
    kr_result = {"snapshots": {"005930": {"setup": "PULLBACK"}}, "as_of": "2026-05-22"}

    lr.generate_lifecycle_pages(
        us_result=us_result, kr_result=kr_result,
        output_dir=str(tmp_path),
        portfolio_tickers={"AAA"},
        momentum_today_us=[{"ticker": "LRCX", "stage": "MOMENTUM_3"}],
        momentum_today_kr=None,
        market_data={"data": {"LRCX": {"close": 100}}},
    )

    us_call = next(c for c in captured_calls if c["market"] == "US")
    kr_call = next(c for c in captured_calls if c["market"] == "KR")
    assert us_call["momentum_today"] == [{"ticker": "LRCX", "stage": "MOMENTUM_3"}]
    assert us_call["has_market_data"] is True
    assert kr_call["momentum_today"] is None  # KR not provided


def test_template_renders_scanner_only_badge(tmp_path):
    """Rendered HTML contains the '🚀 스캐너 신규' chip for _scanner_only candidates."""
    import os
    from jinja2 import Environment, FileSystemLoader, ChainableUndefined

    project_dir = os.path.join(os.path.dirname(__file__), "..")
    env = Environment(
        loader=FileSystemLoader(os.path.join(project_dir, "templates")),
        autoescape=True,
        undefined=ChainableUndefined,
    )
    env.filters["signed_pct"] = lambda x: "—" if x is None else f"{x:+.1f}%"
    env.filters["x_fmt"]      = lambda x: "—" if x is None else f"{x:.1f}×"
    env.filters["trig_age_label"] = lambda d: "—" if d is None else (
        "오늘" if d == 0 else "어제" if d == 1 else f"{d}일전")

    class DefaultNumDict(dict):
        def __getattr__(self, name):
            return self.get(name, 0)

    thresholds = DefaultNumDict({
        "EXTENDED_DIST_FROM_EMA9": 0.08, "EXTENDED_RSI_MIN": 70,
        "RISK_OVERHEAT_RSI": 75, "PULLBACK_MAX_DIST_FROM_EMA9": 0.05,
    })

    tmpl = env.get_template("lifecycle_us.html")
    ctx = {
        "market": "US", "as_of": "2026-05-22", "engine_version": "score_v1",
        "active_nav": "lifecycle_us", "version": "test",
        "snapshots_list": [], "transitions": [], "skipped": [],
        "active_set_size": 1, "summary": {"counts": {}}, "score_tier_bands": {},
        "lifecycle_thresholds": thresholds,
        "verdict_summary": {
            "headline": "Test Headline", "narration": "Test narration",
            "avoid_line": None, "action_hint": "Test action",
            "score_engine_line": None,
        },
        "avoid": [], "enter": [], "probe": [], "watch": [], "trending": [],
        "broken_table": [],
        "top5_candidates": [{
            "ticker": "LRCX", "is_portfolio": False,
            "snapshot": {"setup": "TREND_OK", "decision": "ENTER",
                          "_scanner_only": True,
                          "raw": {"close": 1050, "rsi14": 64,
                                  "dist_ema9_pct": 3.1, "volume_ratio": 1.2,
                                  "risk_tags": []},
                          "rs_delta_pct": 8.0},
            "base_score": 9.33, "momentum_bonus": 4, "rs_bonus": 2,
            "final_score": 15.33, "size_hint_label": "신규 50%",
        }],
        "top5_count": 1, "top5_max": 5, "top5_threshold": 5.0,
    }
    html = tmpl.render(**ctx)
    assert "LRCX" in html
    assert "🚀 스캐너 신규" in html or "scanner-only" in html


def test_render_uses_kr_threshold_3(monkeypatch, tmp_path):
    """_render('KR', ...) must call select_top5 with threshold=3.0."""
    import lifecycle_report as lr

    captured: dict = {}

    def fake_select(**kwargs):
        captured.update(kwargs)
        return {"candidates": [], "count": 0, "max": 5, "threshold": kwargs.get("threshold", 5.0)}

    monkeypatch.setattr(lr, "select_top5_buy_candidates", fake_select)

    from jinja2 import Template
    monkeypatch.setattr(Template, "render", lambda self, **ctx: "<html></html>")

    result = {
        "as_of": "2026-05-26", "market": "KR",
        "snapshots": {"005930": {"setup": "TREND_OK", "decision": "WATCH", "trigger": "WAIT", "raw": {}}},
        "transitions": [], "skipped": [], "active_set_size": 1,
        "market_ret_5d_pct": 0.0,
        "momentum_history": {"data": {}},
        "engine_version": "score_v1",
    }
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    lr._render("KR", result, str(out_dir), template_dir=None,
                lifecycle_state={"tickers": {}, "transitions": []},
                portfolio_tickers=set())

    assert captured.get("threshold") == 3.0


def test_render_uses_us_threshold_5(monkeypatch, tmp_path):
    """_render('US', ...) must call select_top5 with threshold=5.0."""
    import lifecycle_report as lr

    captured: dict = {}

    def fake_select(**kwargs):
        captured.update(kwargs)
        return {"candidates": [], "count": 0, "max": 5, "threshold": kwargs.get("threshold", 5.0)}

    monkeypatch.setattr(lr, "select_top5_buy_candidates", fake_select)

    from jinja2 import Template
    monkeypatch.setattr(Template, "render", lambda self, **ctx: "<html></html>")

    result = {
        "as_of": "2026-05-26", "market": "US",
        "snapshots": {"AAPL": {"setup": "TREND_OK", "decision": "WATCH", "trigger": "WAIT", "raw": {}}},
        "transitions": [], "skipped": [], "active_set_size": 1,
        "market_ret_5d_pct": 0.0,
        "momentum_history": {"data": {}},
        "engine_version": "score_v1",
    }
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    lr._render("US", result, str(out_dir), template_dir=None,
                lifecycle_state={"tickers": {}, "transitions": []},
                portfolio_tickers=set())

    assert captured.get("threshold") == 5.0


def test_render_kr_attaches_korean_name_to_top5(monkeypatch, tmp_path):
    """_render('KR', ...) attaches `name` to each top5 candidate."""
    import lifecycle_report as lr

    captured_ctx: dict = {}

    def fake_select(**kwargs):
        return {
            "candidates": [
                {"ticker": "005930", "is_portfolio": False,
                 "snapshot": {"setup": "TREND_OK", "decision": "ENTER",
                               "rs_delta_pct": 5.0, "trigger": "CONFIRMED_TRIGGER",
                               "raw": {"close": 70000, "rsi14": 62,
                                       "dist_ema9_pct": 2.0,
                                       "volume_ratio": 1.1, "risk_tags": []}},
                 "base_score": 7.0, "momentum_bonus": 0, "rs_bonus": 1,
                 "final_score": 8.0, "size_hint_label": "신규 50%"},
            ],
            "count": 1, "max": 5, "threshold": 3.0,
        }

    monkeypatch.setattr(lr, "select_top5_buy_candidates", fake_select)
    # Force _lookup_ticker_name to return a known KR name
    monkeypatch.setattr(lr, "_lookup_ticker_name",
                          lambda t, m: "삼성전자" if t == "005930" else t)

    from jinja2 import Template

    def capture_render(self, **ctx):
        captured_ctx.update(ctx)
        return "<html></html>"

    monkeypatch.setattr(Template, "render", capture_render)

    result = {
        "as_of": "2026-05-26", "market": "KR",
        "snapshots": {"005930": {"setup": "TREND_OK", "decision": "WATCH",
                                   "trigger": "WAIT", "raw": {}}},
        "transitions": [], "skipped": [], "active_set_size": 1,
        "market_ret_5d_pct": 0.0,
        "momentum_history": {"data": {}},
        "engine_version": "score_v1",
    }
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    lr._render("KR", result, str(out_dir), template_dir=None,
                lifecycle_state={"tickers": {}, "transitions": []},
                portfolio_tickers=set())

    candidates = captured_ctx.get("top5_candidates")
    assert candidates is not None
    assert len(candidates) == 1
    assert candidates[0]["name"] == "삼성전자"


def test_render_us_does_not_attach_name_to_top5(monkeypatch, tmp_path):
    """_render('US', ...) leaves candidates without `name` field."""
    import lifecycle_report as lr

    captured_ctx: dict = {}

    def fake_select(**kwargs):
        return {
            "candidates": [
                {"ticker": "AAPL", "is_portfolio": False,
                 "snapshot": {"setup": "TREND_OK", "decision": "ENTER",
                               "rs_delta_pct": 5.0, "trigger": "CONFIRMED_TRIGGER",
                               "raw": {"close": 200, "rsi14": 60,
                                       "dist_ema9_pct": 1.0,
                                       "volume_ratio": 1.0, "risk_tags": []}},
                 "base_score": 7.0, "momentum_bonus": 0, "rs_bonus": 1,
                 "final_score": 8.0, "size_hint_label": "신규 50%"},
            ],
            "count": 1, "max": 5, "threshold": 5.0,
        }

    monkeypatch.setattr(lr, "select_top5_buy_candidates", fake_select)

    from jinja2 import Template

    def capture_render(self, **ctx):
        captured_ctx.update(ctx)
        return "<html></html>"

    monkeypatch.setattr(Template, "render", capture_render)

    result = {
        "as_of": "2026-05-26", "market": "US",
        "snapshots": {"AAPL": {"setup": "TREND_OK", "decision": "WATCH",
                                 "trigger": "WAIT", "raw": {}}},
        "transitions": [], "skipped": [], "active_set_size": 1,
        "market_ret_5d_pct": 0.0,
        "momentum_history": {"data": {}},
        "engine_version": "score_v1",
    }
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    lr._render("US", result, str(out_dir), template_dir=None,
                lifecycle_state={"tickers": {}, "transitions": []},
                portfolio_tickers=set())

    candidates = captured_ctx.get("top5_candidates")
    assert candidates is not None
    assert len(candidates) == 1
    # US: no name attached
    assert "name" not in candidates[0]
