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
