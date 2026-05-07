"""
v5.2 검증 테스트
- Exit 익절 전용 재설계 (TAKE_PROFIT_1/2)
- 고점 영역 게이트 (DD > -5%)
- Drawdown 손절 삭제, MACD<0 삭제
"""
import json, os, sys

sys.stdout.reconfigure(encoding="utf-8")
project_dir = os.path.dirname(os.path.abspath(__file__))

# ── 데이터 로드 ──
json_path = os.path.join(project_dir, "screenshots", "market_data_2026-04-02.json")
with open(json_path, "rb") as f:
    market_data = json.loads(f.read().rstrip(b" \t\n\r\x00").decode("utf-8"))

history_path = os.path.join(project_dir, "history", "signals_history.json")
with open(history_path, "r", encoding="utf-8") as f:
    history = json.load(f)

from signal_judge import (
    _check_top_signal, _check_take_profit_2, _check_take_profit_1,
    _is_profit_zone, _get_prev_day_data, judge_all, check_exit_simple,
)

data = market_data["data"]
macro = market_data["_macro"]

print("=" * 70)
print("  TEST 1: 고점 영역 게이트 (DD > -5%)")
print("=" * 70)
for ticker in sorted(data.keys()):
    d = data[ticker]
    dd = d.get("drawdown_20d_pct", 0)
    gate = _is_profit_zone(d)
    marker = "PASS" if gate else "BLOCK"
    print(f"  {ticker:<6} DD={dd:>6.1f}%  gate={marker}")

print()
print("=" * 70)
print("  TEST 2: 전체 판정 결과 (v5.2)")
print("=" * 70)
new_results = judge_all(market_data, history)
old_results = history.get("2026-04-02", {})

print(f"{'Ticker':<6} {'기존':<18} {'v5.2':<18} {'변경?':^6} {'비고'}")
print("-" * 70)
changed = []
for ticker in sorted(new_results.keys()):
    old_sig = old_results.get(ticker, {}).get("signal", "N/A")
    new = new_results[ticker]
    new_sig = new["signal"]
    diff = "***" if old_sig != new_sig else ""
    note = new.get("note", "")[:40]
    print(f"{ticker:<6} {old_sig:<18} {new_sig:<18} {diff:^6} {note}")
    if old_sig != new_sig:
        changed.append((ticker, old_sig, new_sig))

print()
if changed:
    print(f"변경된 종목: {len(changed)}개")
    for ticker, old, new in changed:
        conds = new_results[ticker].get("conditions", [])
        ok_conds = [c[1] for c in conds if c[0] == "ok"]
        print(f"  {ticker}: {old} -> {new}")
        for c in ok_conds:
            print(f"    - {c}")
else:
    print("변경된 종목 없음")

# ── L3/L2 잔재 확인 ──
print()
print("=" * 70)
print("  TEST 3: L3/L2 잔재 확인 (없어야 정상)")
print("=" * 70)
l3l2_found = False
for ticker, r in new_results.items():
    sig = r.get("signal", "")
    if "L3" in sig or "L2" in sig:
        print(f"  !! {ticker}: {sig}")
        l3l2_found = True
print("  L3/L2 잔재 없음 ✅" if not l3l2_found else "  !! L3/L2 잔재 발견 ❌")

# ── 엣지 케이스 ──
print()
print("=" * 70)
print("  TEST 4: 엣지 케이스 시뮬레이션")
print("=" * 70)

# Case A: 고점 근처 (DD=-2%) + TP2 조건 충족
print("\n[Case A] DD=-2% (게이트 통과) + MACD 데스크로스 + hist 감소")
fake_a = {
    "price": 98, "rsi14": 55, "drawdown_20d_pct": -2,
    "macd": -1, "macd_signal": -0.5, "macd_hist_trend": "decreasing_3d",
    "price_vs_ma20": "below",
    "double_bottom": {"detected": False}
}
gate = _is_profit_zone(fake_a)
hit, conds = _check_take_profit_2(fake_a, None)
print(f"  게이트: {'통과' if gate else '차단'}, TP2: {hit}")
for s, t in conds:
    print(f"  [{s}] {t}")

# Case B: 하락장 (DD=-8%) + 동일 조건 → 게이트 차단
print("\n[Case B] DD=-8% (게이트 차단) + 동일 조건 → HOLD")
fake_b = dict(fake_a, drawdown_20d_pct=-8)
gate = _is_profit_zone(fake_b)
print(f"  게이트: {'통과' if gate else '차단'} → TP 체크 안 함 → HOLD")

# Case C: 고점 근처 + hist recovering → 면제
print("\n[Case C] DD=-3% (게이트 통과) + hist recovering → 면제")
fake_c = dict(fake_a, drawdown_20d_pct=-3, macd_hist_trend="increasing_2d")
gate = _is_profit_zone(fake_c)
hit, conds = _check_take_profit_2(fake_c, None)
print(f"  게이트: {'통과' if gate else '차단'}, TP2: {hit}")
for s, t in conds:
    print(f"  [{s}] {t}")

# Case D: MACD 데스크로스 — MACD < 0 불필요 (v5.2)
print("\n[Case D] MACD=0.5 > 0, signal=1.0 → 데스크로스 + hist 감소")
fake_d = {
    "price": 98, "rsi14": 55, "drawdown_20d_pct": -2,
    "macd": 0.5, "macd_signal": 1.0, "macd_hist_trend": "decreasing_3d",
    "price_vs_ma20": "below",
    "double_bottom": {"detected": False}
}
hit, conds = _check_take_profit_2(fake_d, None)
macd_cond = [c for c in conds if "MACD" in c[1] and "데스크로스" in c[1]]
if macd_cond:
    print(f"  [{macd_cond[0][0]}] {macd_cond[0][1]}")
print(f"  => TP2 발동: {hit} (기대: True — MACD>0이어도 데스크로스면 발동)")

# Case E: TP1 — hist recovering 면제
print("\n[Case E] TP1 + hist recovering → 면제")
fake_e = {
    "rsi14": 55, "macd": -1, "macd_signal": -0.5,
    "macd_hist_trend": "increasing_2d", "price_vs_ma20": "below",
}
hit_e, conds_e = _check_take_profit_1(fake_e, {"rsi": 60})
for s, t in conds_e:
    print(f"  [{s}] {t}")
print(f"  => TP1 발동: {hit_e} (기대: False)")

# Case F: 스캐너 check_exit_simple — 게이트 적용
print("\n[Case F] 스캐너 exit — DD=-8% → None (게이트 차단)")
res_f = check_exit_simple("TEST", fake_b)
print(f"  => {res_f} (기대: None)")

print("\n[Case G] 스캐너 exit — DD=-2% + 데스크로스 → TP2")
res_g = check_exit_simple("TEST", fake_a)
print(f"  => {res_g.get('signal') if res_g else None} (기대: TAKE_PROFIT_2)")

print("\n" + "=" * 70)
print("  테스트 완료")
print("=" * 70)
