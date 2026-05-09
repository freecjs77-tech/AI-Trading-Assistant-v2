# Emerging Momentum + Maturity Classifier v1.5 — Design Spec

**Date**: 2026-05-09
**Status**: Brainstorming complete — pending user spec review
**Owner**: freecjs77@gmail.com
**Depends on**: [Momentum Scanner v1.0](2026-05-06-momentum-scanner-design.md)

## 0. Summary

기존 Momentum Scanner v1.0이 풀고 있는 문제를 한 단계 더 좁힌다. v1.0은 "이미 강한 종목"(Momentum Leaders)을 잘 찾지만, "곧 좋은 진입 타이밍이 만들어질 종목"은 잘 못 찾는다. v1.5는 두 가지 보완을 동시에 도입한다.

1. **Emerging Momentum (EM) tier 추가** — 사용자 표현으로 "Structural Inflection Discovery". M1보다 약한 5d/20d 수익률 + EMA 구조 형성 + 미과열 조건. Top 섹터 필터를 우회해 **다음 리더 섹터** 후보를 잡는다.
2. **Maturity 분류기 (EARLY/MID/EXTENDED) 추가** — 같은 M1 안에서도 "초입" / "건강한 추세" / "과열"을 구분. Strength × Maturity 직교 구조.

핵심 원칙:
- **Discovery 철학 분리** — Leaders는 Relative Strength, EM은 Structural Inflection. 같은 테이블에 섞지 않는다.
- **EM과 M+는 단일 tier 라벨** — 한 종목은 {M3, M2, M1, EM, none} 중 하나. M+가 EM보다 우선.
- **Maturity는 직교 차원** — Tier와 별개의 컬럼. 같은 EARLY 라벨도 M1+EARLY와 EM+EARLY는 의미 다름.
- **EMA는 글로벌 데이터** — `fetch_market_data.py`에 추가. Lifecycle(Phase 2), Detail page에서도 재사용.
- **시그널 로직 v5.3 영향 없음** — 기존 strategy 시그널과 v1.0 momentum 시그널 모두 무영향.

## 1. Goals & Non-goals

### Goals (v1.5)
- 매일 US/KR 모멘텀 스캔에 EM tier 추가 (Full IWB / KR base universe 평가)
- 모든 시그널 행에 Maturity (EARLY/MID/EXTENDED) 라벨 부착
- 두 섹션 분리 UI (`🔥 Momentum Leaders` / `🌱 Emerging Momentum`)
- EM 섹션에 Sector Rotation Radar (비-Top 섹터 EM 카운트)
- EM → M1 transition leg 추적 (backtest expectancy)
- Risk Tag 정리: EARLY/EXTENDED 삭제, OVERHEAT/PARABOLIC만 유지
- `fetch_market_data.py`에 EMA 필드 7개 추가 (글로벌)

### Non-goals (v1.5 제외)
- Phase 2 Lifecycle (PULLBACK → EARLY_TRIGGER → CONFIRMED_TRIGGER) — 별도 spec
- EM sub-tier (EM1/EM2 등) — 단일 tier 유지
- Tier 단일성 깨는 multi-label — 한 종목 한 tier 원칙
- 기존 v5.3 시그널 로직 변경
- 기존 v1.0 M1/M2/M3 임계값 변경
- 새 UI 색상 시스템 (기존 색상 유지, Maturity만 신규)

## 2. Architecture Overview

### 2.1 Pipeline 위치 — 기존 Step 4c2 내부 확장

```
Step 4c2  Momentum scanners (US, KR)
  ├─ Sector momentum (기존)
  ├─ Top 2~3 섹터 종목 → M1/M2/M3 분류 (기존)
  ├─ ★ Full IWB → EM 분류 (신규)
  ├─ ★ Maturity 분류 (모든 통과 종목, 신규)
  └─ History/backtest 업데이트 (기존 + EM RANK 0)
```

번호 변경 없음. v1.0과 동일 step에서 evaluate 단계만 확장.

### 2.2 모듈 변경 (단방향 의존 유지)

```
fetch_market_data.py       ★ EMA 7필드 추가 (글로벌)
momentum_config.py         ★ Maturity / EM 임계값 상수 추가
momentum_data.py           ★ EMA 필드 매핑 (read-only — 계산은 fetch_market_data.py)
momentum_signal.py         ★ classify_maturity, classify_em, classify_tier 추가
momentum_history.py        ★ RANK[EM]=0 추가, schema_version 1 → 2
momentum_backtest.py       ★ EM stage by_stage 통계 + transition_to_M1_pct
templates/base_momentum.html  ★ 두 섹션 분리, Sector Rotation Radar
```

`momentum_signal.py`는 **EMA를 직접 계산하지 않는다**. fetch layer가 단일 진실의 원천. formula drift / pandas adjust mismatch 방지.

### 2.3 실패 격리 (v1.0과 동일)

EM 평가 실패는 v1.0 try/except 안에서 자연 흡수. EMA 필드 부재 시 EM 평가는 자동 skip하고 M1/M2/M3는 정상 진행 — graceful degradation.

## 3. Data Layer — `fetch_market_data.py` 확장

### 3.1 신규 EMA 필드 (글로벌)

```python
EMA_SPANS = (9, 21, 65)  # close 기준

ema9   = close.ewm(span=9,  adjust=False).mean()
ema21  = close.ewm(span=21, adjust=False).mean()
ema65  = close.ewm(span=65, adjust=False).mean()

ticker_data.update({
    "ema9":  safe(ema9),
    "ema21": safe(ema21),
    "ema65": safe(ema65),
    "dist_ema9_pct":  pct_distance(last_close, ema9),
    "dist_ema21_pct": pct_distance(last_close, ema21),
    "ema21_slope_3d_pct": slope_pct(ema21, lookback=3),
    "ema65_slope_5d_pct": slope_pct(ema65, lookback=5),
})
```

**유틸 함수**:
```python
def pct_distance(close: float, ema_series: pd.Series) -> float | None:
    val = safe(ema_series)
    if val is None or val == 0:
        return None
    return round((close - val) / val * 100, 2)

def slope_pct(ema_series: pd.Series, lookback: int) -> float | None:
    if len(ema_series) <= lookback:
        return None
    cur, prev = ema_series.iloc[-1], ema_series.iloc[-1 - lookback]
    if pd.isna(cur) or pd.isna(prev) or prev == 0:
        return None
    return round((cur - prev) / prev * 100, 2)
```

### 3.2 안전장치

- `len(close) < span` → `safe(ema)` returns None → 모든 파생 필드 None
- `pd.isna` / `ZeroDivision` 검사 (기존 `change_5d_pct` 패턴 재사용)
- 신규 필드는 모두 optional — 기존 코드는 참조 안 하므로 backwards-compatible

### 3.3 영향 분석

| 모듈 | 영향 |
|---|---|
| `signal_judge.py` | 무영향 — EMA 필드 미참조 |
| `report_generator.py` | 무영향 — 새 필드 자동 무시 |
| `history_manager.py` | 무영향 — dict-passthrough |
| 기존 `screenshots/market_data_*.json` | 새 키만 추가, 기존 키 유지 |
| 기존 시그널 backtest | 무영향 |

### 3.4 Phase 2 활용 예고

EMA 필드는 Lifecycle(PULLBACK 감지: ema21에서 -3~+3% 흡수) / Detail page 차트 / Portfolio Stop Signal(추세 끊김 보조)에서 재사용 — 글로벌 추가가 정당화되는 이유.

## 4. Signal Logic

### 4.1 Maturity 분류기 — 모든 시그널 종목에 부착

3단계 categorical. **EMA9 거리 + RSI 2축**.

| Maturity | 조건 | 색상 |
|---|---|---|
| 🔴 **EXTENDED** | `dist_ema9_pct ≥ 8% OR rsi14 ≥ 75` (둘 중 하나) | 빨강 |
| 🟢 **EARLY** | `dist_ema9_pct < 3% AND rsi14 < 68 AND ema9 > ema21` (셋 다) | 초록 |
| 🟡 **MID** | 그 외 | 노랑 |

`momentum_config.py`:
```python
MATURITY_EXT_DIST_PCT = 8.0
MATURITY_EXT_RSI      = 75.0
MATURITY_EARLY_DIST_PCT = 3.0
MATURITY_EARLY_RSI      = 68.0
```

**평가 순서**: EXTENDED 먼저 검사 (과열 우선) → 아니면 EARLY 검사 → 아니면 MID. EARLY와 EXTENDED 동시 충족은 정의상 불가능.

**EARLY ≠ "좋다"**. "아직 덜 오름"일 뿐 — 진입 타이밍 판단은 Phase 2 Lifecycle 영역. UI에서 색상으로만 표시, position hint는 별도.

**필드 누락 시**: `dist_ema9_pct` 또는 `rsi14`가 None이면 Maturity = None. UI에서 "—" 표시.

### 4.2 Emerging Momentum (EM) tier

별도 함수 `classify_em(stock_data)`. M1/M2/M3 평가 후, M+가 None일 때만 호출.

**조건 (ALL met)**:
```python
# Structure (4 conditions)
ema9 > ema21 > ema65
AND ema21_slope_3d_pct > 0
AND close > ema21

# Momentum (OR — 5d 또는 20d 둘 중 하나)
ret_5d_pct >= 4.0  OR  ret_20d_pct >= 10.0

# Anti-overheat
rsi14 < 72.0
AND dist_ema9_pct < 8.0

# Participation
volume_ratio >= 1.05
```

`momentum_config.py`:
```python
EM_RET_5D_MIN_PCT  = 4.0
EM_RET_20D_MIN_PCT = 10.0
EM_RSI_MAX         = 72.0
EM_DIST_EMA9_MAX   = 8.0
EM_VOL_RATIO_MIN   = 1.05
EM_EMA21_SLOPE_MIN_PCT = 0.0   # rising = positive slope
```

**Universe**: Full IWB (US) / KR_BASE (KR). Sector momentum 게이트 우회. Top 섹터에 들어 있는지는 `sector_top_rank` 어노테이션으로만 표시.

**Pre-filter (속도)**: 1차 게이트로 `ema9 > ema21` AND `close > ema21` 만 검사 → 1000 → ~250~400. 그 다음 가중 검사.

### 4.3 Tier 우선순위 — `classify_tier`

```python
def classify_tier(stock_data: dict) -> str | None:
    """Returns 'MOMENTUM_3' | 'MOMENTUM_2' | 'MOMENTUM_1' | 'EM' | None.
    M+가 EM보다 우선. EM은 M+ None일 때만 평가."""
    stage = classify_stage(stock_data)  # 기존 v1.0 함수
    if stage is not None:
        return stage
    if classify_em(stock_data):
        return "EM"
    return None
```

같은 종목이 M1과 EM 둘 다 충족해도 tier = "MOMENTUM_1". EM은 본질적으로 "M+가 아닌데 곧 될 가능성"이라는 의미 — 강도 라벨 단일화.

### 4.4 Risk Tag 정리

`compute_risk_tags()` 변경:
```python
# 유지
🔴 OVERHEAT  : rsi14 ≥ 80
🟠 PARABOLIC : change_pct ≥ +8%

# 삭제 (Maturity 차원이 흡수)
~~⚪ EARLY~~        — Maturity = EARLY가 대체
~~🟡 EXTENDED~~     — Maturity = EXTENDED가 대체
```

`momentum_config.RISK_PRIORITY = ["OVERHEAT", "PARABOLIC"]` (4 → 2).
`momentum_config.POSITION_HINT`는 4 항목 유지하지만 "EARLY"/"EXTENDED" 키는 read 시 무시 (legacy):
```python
POSITION_HINT = {
    None:        "적극",
    "OVERHEAT":  "신중",
    "PARABOLIC": "눌림",
    # legacy keys (history compatibility, never written by new code):
    "EARLY":     "조기",
    "EXTENDED":  "분할",
}
```

**History 호환성**:
```python
LEGACY_RISK_TAGS = {"EARLY", "EXTENDED"}

def filter_legacy_tags(risk_tags: list[str]) -> list[str]:
    return [t for t in risk_tags if t not in LEGACY_RISK_TAGS]
```
History 읽을 때 legacy 태그 자동 제거. 새 entry 작성 시 새 태그 셋만 사용.

### 4.5 Position Hint — Maturity와 Risk Tag 결합

기존 단일 hint → **2축 hint**:

```python
def position_hint(maturity: str | None, risk_tags: list[str]) -> str:
    # 위험 우선
    if "OVERHEAT" in risk_tags:
        return "신중"
    if "PARABOLIC" in risk_tags:
        return "눌림"
    if maturity == "EXTENDED":
        return "분할"
    if maturity == "EARLY":
        return "관찰"      # 신규 — 진입보다 추적
    return "적극"           # MID + 위험 없음
```

"조기" → "관찰"로 수정. 사용자 강조 포인트: EM+EARLY는 즉시 매수가 아닌 watchlist 후보.

### 4.6 신규 데이터 필드 요약

| 필드 | 위치 | 용도 |
|---|---|---|
| `ema9`, `ema21`, `ema65` | `fetch_market_data.py` | 글로벌 EMA |
| `dist_ema9_pct`, `dist_ema21_pct` | 동상 | 추세선 거리 |
| `ema21_slope_3d_pct`, `ema65_slope_5d_pct` | 동상 | numeric slope |
| `ret_20d_pct` | 동상 | EM momentum 검사 (v1.0에 이미 있음) |
| `maturity` | 신호 결과 | EARLY/MID/EXTENDED |
| `tier` | 신호 결과 | MOMENTUM_3/2/1/EM |
| `sector_top_rank` | 신호 결과 | Top 1~3 / null (annotation) |

## 5. History & Backtest

### 5.1 History 스키마 변경 — schema_version 1 → 2

`scanner_momentum_us_history.json` (KR 동일):

**RANK 확장**:
```python
RANK = {"EM": 0, "MOMENTUM_1": 1, "MOMENTUM_2": 2, "MOMENTUM_3": 3}
```

**일별 entry에 maturity 필드 추가**:
```json
"PLTR": {
  "2026-05-09": {
    "stage": "EM",
    "streak": 1,
    "prev_stage": null,
    "change": "NEW",
    "maturity": "EARLY",
    "risk_tags": [],
    "sector": "Software",
    "sector_top_rank": null,
    "price": 22.50,
    "rsi": 64.2,
    "dist_ema9_pct": 1.8,
    "ret_1d_pct": 1.5, "ret_3d_pct": 4.2, "ret_5d_pct": 6.1, "ret_20d_pct": 11.3,
    "rs_vs_sector": null,
    "entry_price": 22.50,
    "entry_date": "2026-05-09",
    "entry_context": {"sector": "Software", "streak": 1, "maturity": "EARLY", "risk_tags": []},
    "time_in_stage": 1
  },
  "2026-05-13": {
    "stage": "MOMENTUM_1",
    "streak": 4,
    "prev_stage": "EM",
    "change": "UPGRADE",
    "maturity": "MID",
    "entry_price": 24.10,
    "entry_date": "2026-05-13",
    "entry_context": {"prev_stage": "EM", "streak_at_em": 3, "sector": "Software", "maturity": "MID", "risk_tags": []},
    "time_in_stage": 1,
    "price": 24.10
  }
}
```

**Migration**: 기존 schema_version=1 파일은 그대로 읽기 가능. 새 entry부터 `maturity`, `sector_top_rank`, `dist_ema9_pct`, `ret_20d_pct` 추가. 누락 entry는 read 시 None default.

### 5.2 EM Streak/Change 계산

기존 `compute_streak_change` 그대로 작동. EM RANK=0 추가만으로:
- EM → M1: `RANK[M1] > RANK[EM]` → "UPGRADE" (streak 누적 +1)
- M1 → EM: `RANK[EM] < RANK[M1]` → "DOWNGRADE" (streak 1로 reset)
- EM → null: "EXIT"
- null → EM: "NEW"

EM stage에서도 streak 누적은 의미 있다 — "EM 상태 며칠째"가 곧 "구조 형성 진행도".

### 5.3 Leg Backtest — EM 통합

`momentum_backtest.py`의 by_stage 통계에 EM 추가:
```json
"by_stage": {
  "MOMENTUM_3": {...},
  "MOMENTUM_2": {...},
  "MOMENTUM_1": {...},
  "EM": {
    "leg_count": 89,
    "win_rate_5d_pct": 53.9,
    "avg_ret_3d_pct": 1.4,
    "avg_ret_5d_pct": 2.3,
    "avg_ret_10d_pct": 4.1,
    "avg_max_ret_pct": 6.8,
    "avg_mdd_pct": -3.4,
    "avg_duration_days": 6.1,
    "transition_to_M1_pct": 47.2     ★ 핵심 KPI
  }
}
```

**`transition_to_M1_pct`** = EM leg 중 M1 이상으로 UPGRADE된 비율. 50% 이상이면 EM 신호 신뢰도 검증. 30% 미만이면 EM 임계값 재검토 트리거.

### 5.4 Sector Rotation Radar 데이터

매일 EM 결과 집계:
```python
em_by_sector = defaultdict(int)
for stock in em_results:
    if stock["sector_top_rank"] is None:  # 비-Top 섹터만
        em_by_sector[stock["sector"]] += 1

rotation_radar = sorted(em_by_sector.items(), key=lambda kv: -kv[1])[:5]
```
Top 5 비-Top 섹터를 EM 카운트 내림차순. 카운트 ≥ 3인 섹터는 UI에 강조 표시.

기록은 history `_meta.daily_rotation_radar`에 누적 (시계열 분석 v2 후보):
```json
"_meta": {
  "daily_rotation_radar": {
    "2026-05-09": [["Education", 4], ["Cybersecurity", 3]]
  }
}
```

## 6. Output / UI

### 6.1 페이지 레이아웃

```
┌─ Hero Summary ──────────────────────────────────────────┐
│ 🔥 Today's Momentum — US     2026-05-09                │
│ Leaders: M3=3 / M2=5 / M1=12   Emerging: 8             │
│ Scanned: 1003 tickers · ⏱ 52s · Momentum v1.5          │
└─────────────────────────────────────────────────────────┘

┌─ Sector Leaders (기존) ─────────────────────────────────┐
│ ① Tech          🔥🔥🔥  Score 98   5d +5.2%   RS +2.1pp │
│ ② Communication 🔥🔥    Score 87   5d +4.1%   RS +1.0pp │
│ ③ Semiconductor 🔥🔥    Score 82   5d +3.7%   RS +0.6pp │
└─────────────────────────────────────────────────────────┘

┌─ 🔥 Momentum Leaders (M1/M2/M3) ─────────────────────────────────────┐
│ Ticker  Tier  Maturity  Streak  Sector(⭐)    RSI   dist_ema9   5d/20d   RS  Risk      Hint │
│ NVDA    M3    🔴EXT     5d      Tech ⭐        78    +11.5%      +12/+18  ✓  🔴OH      신중 │
│ AMD     M3    🔴EXT     2d      Semis ⭐       73    +9.2%       +10/+15  ✓  -         분할 │
│ AVGO    M2    🟡MID     1d      Tech ⭐        66    +5.4%       +7/+9    -  -         적극 │
│ MU      M1    🟢EARLY   1d      Semis ⭐       63    +2.1%       +9/+5    -  -         관찰 │
└──────────────────────────────────────────────────────────────────────┘

┌─ 🌱 Emerging Momentum (EM) ──────────────────────────────────────────┐
│ ─── Potential Sector Rotation ───                                    │
│ Education (4 EM, 비-Top)                                             │
│ Cybersecurity (3 EM, 비-Top)                                         │
│ Healthcare (3 EM, 비-Top)                                            │
│ ────────────────────────────────                                     │
│ Ticker  Tier  Maturity  Streak  Sector(⭐)    RSI   dist_ema9   5d/20d   RS  Risk      Hint │
│ DUOL    EM    🟢EARLY   3d      Education     61    +1.8%       +4.2/+11  -  -         관찰 │
│ HOOD    EM    🟢EARLY   1d      Financial     59    +2.4%       +5.1/+13  -  -         관찰 │
│ PLTR    EM    🟡MID     2d      Software ⭐    66    +4.6%       +6.0/+14  -  -         관찰 │
└──────────────────────────────────────────────────────────────────────┘

┌─ Backtest Summary (직전 90일 누적) ─────────────────────┐
│ Tier    #legs  Win 5d   Avg 3d   Avg 5d   Avg 10d  MDD    transition_to_M1 │
│ M3      47     68%      +2.1%    +4.8%    +7.2%   -3.1%   —     │
│ M2      83     54%      +1.4%    +2.9%    +4.1%   -3.8%   —     │
│ M1      129    46%      +0.6%    +1.2%    +1.8%   -4.2%   —     │
│ EM      89     54%      +1.4%    +2.3%    +4.1%   -3.4%   47.2% │
└─────────────────────────────────────────────────────────┘

┌─ Footer ────────────────────────────────────────────────┐
│ IWB 1003종목 (cached 5d ago, fallback_count=0)          │
│ EMA9/21/65 글로벌 활성 — Maturity v1.5                  │
│ ⚠ 백테스트는 종가 진입 가정 — 실거래 시 슬리피지 발생   │
└─────────────────────────────────────────────────────────┘
```

### 6.2 컬럼 명세 (양 섹션 공통)

| 컬럼 | 데이터 | 비고 |
|---|---|---|
| Ticker | 클릭 시 detail 페이지 | |
| **Tier** | M3 / M2 / M1 / EM | 색상 배지 |
| **Maturity** | 🔴EXT / 🟡MID / 🟢EARLY | 색상 강조 (필수) |
| Streak | "3d" | EM도 streak 누적 |
| Sector(⭐) | "Tech ⭐" / "Education" | ⭐ = Top 3 안 |
| RSI | rsi14 | |
| **dist_ema9** | "+1.8%" / "+11.5%" | Maturity 근거 시각화 (필수) |
| 5d/20d | ret_5d_pct / ret_20d_pct | Price 컬럼 대체 |
| RS | ✓ / — | 섹터 대비 (M+ 행만, EM은 —) |
| Risk | 🔴OH / 🟠PB / — | 2개 태그만 |
| Hint | "적극" / "관찰" / "분할" / "눌림" / "신중" | |

**제거된 컬럼**: Change (1d/5d/20d와 정보 중복), Price (구조 위치보다 후순위)

### 6.3 Sector Rotation Radar 블록

EM 섹션 상단. 비-Top 섹터(섹터 momentum Top 3 안에 들지 않은 섹터)에서 EM 신호가 ≥ 2개 발생한 경우만 표시.

```
─── Potential Sector Rotation ───
Education (4 EM, 비-Top)
Cybersecurity (3 EM, 비-Top)
Healthcare (3 EM, 비-Top)
────────────────────────────────
```

count ≥ 3인 줄은 strong 강조 (bold + 색상). 비-Top EM이 0이면 블록 자체 숨김.

### 6.4 Detail 페이지

기존 `🔥 CURRENT STATUS` + `🔥 Momentum History` 섹션이 자동 EM 표시. Maturity 추가 라인 1줄:

```
Stage: EM (3일째)
Maturity: 🟢 EARLY  (dist_ema9 +1.8%, RSI 64)
Entry: $22.50 → Now $23.05 (+2.4%, MDD -0.5%)
Hint: 관찰
```

### 6.5 Telegram 메시지 — EM 추가

```
🔥 Momentum Scanner — 2026-05-09

🇺🇸 US  Top sectors: Tech, Comm Svcs
M3 (3): NVDA 🔴 5d, AMD 🔴 2d, AVGO 1d
M2 (5): MU 🟢, QCOM, KLAC, GOOGL, ...
M1 (12): see report

🌱 Emerging (8): DUOL🟢, HOOD🟢, PLTR🟡, ...
🔄 Sector Rotation Radar:
  Education (4), Cybersecurity (3), Healthcare (3)

🇰🇷 KR  Top: 반도체, 2차전지
M3 (2): SK하이닉스, 한미반도체 🟠
M2 (4): 에코프로 🟡, 삼성SDI, ...
🌱 Emerging (3): ...

🔥 Edge: EM transition to M1 = 47.2% (직전 90일)

📊 US: https://.../momentum_us_2026-05-09.html
📊 KR: https://.../momentum_kr_2026-05-09.html
```

3500자 제한은 기존과 동일.

### 6.6 색상 시스템

```css
/* Maturity */
.maturity-early    { color: #22c55e; }  /* 🟢 */
.maturity-mid      { color: #eab308; }  /* 🟡 */
.maturity-extended { color: #ef4444; }  /* 🔴 */

/* Tier */
.tier-em   { background: #f1f5f9; color: #0f172a; border: 1px solid #cbd5e1; }
.tier-m1   { /* 기존 */ }
.tier-m2   { /* 기존 */ }
.tier-m3   { /* 기존 */ }

/* Risk */
.risk-overheat  { /* 기존 */ }
.risk-parabolic { /* 기존 */ }
```

EM tier는 시각적으로 가장 약한 강조 (회색 톤) — Leaders가 시각 우선이지만 두 섹션이 분리돼 있어 위계 명확.

## 7. Operations & Integration

### 7.1 파일 변경 정리

**수정 (8개)**:
- `fetch_market_data.py` — EMA 7필드 + 유틸 함수 추가
- `momentum_config.py` — Maturity / EM 임계값 + RANK 변경
- `momentum_data.py` — EMA 필드 매핑 (read-through, 계산 안 함)
- `momentum_signal.py` — `classify_em`, `classify_maturity`, `classify_tier`, Risk Tag 정리
- `momentum_history.py` — RANK 확장, schema_version 2, legacy_tag filter
- `momentum_backtest.py` — by_stage에 EM 추가, transition_to_M1_pct
- `templates/base_momentum.html` — 두 섹션 분리, Sector Rotation Radar
- `telegram_sender.py` — `_format_momentum_message`에 EM/Rotation 추가

**신규 (0개)** — 모듈 추가 없음. 모두 기존 모듈 확장.

**테스트 신규**:
- `tests/test_momentum_maturity.py` — boundary (dist_ema9 7.99 vs 8.00, RSI 67.99 vs 68 등)
- `tests/test_momentum_em.py` — EM 조건 boundary + EM↔M1 우선순위
- `tests/test_momentum_history_v2.py` — schema 1→2 migration, legacy tag filter, EM RANK
- `tests/test_em_transition_backtest.py` — transition_to_M1_pct 계산
- `tests/fixtures/golden_em_<date>.json` — 회귀 방지 fixture

### 7.2 history 마이그레이션 — 무중단

기존 v1.0 history JSON은 schema_version=1로 그대로 read 가능. 새 entry 작성 시 schema_version=2로 자동 갱신.

기존 entry에 `maturity` / `sector_top_rank` / `dist_ema9_pct` / `ret_20d_pct` 누락은 read 시 None default. UI는 None을 "—"로 표시.

기존 entry의 `risk_tags`에 "EARLY" / "EXTENDED" 잔존 시 read 시 자동 필터.

### 7.3 GitHub Actions

`.github/workflows/daily-report.yml` 변경 없음. 기존 history 파일을 schema_version 2로 갱신하므로 신규 파일 추가 없음.

### 7.4 환경변수

`MODE=momentum_only` (기존) — EM 평가 포함되어 자동 작동.

신규 `MOMENTUM_DISABLE_EM=1` (선택) — EM 평가만 끄고 v1.0 동작 — 회귀 시 안전 토글. 기본값은 활성.

### 7.5 테스트 / 검증 전략

**Unit 테스트**:
- `classify_maturity`: dist_ema9 ∈ {2.99, 3.00, 7.99, 8.00}, RSI ∈ {67.99, 68.00, 74.99, 75.00} 8개 boundary
- `classify_em`: structure 4조건 ALL, momentum OR (5d 4% / 20d 10%), RSI 71.99/72.00
- `classify_tier`: M1과 EM 동시 통과 시 M1 우선 검증
- `filter_legacy_tags`: 기존 ["EARLY", "OVERHEAT"] → ["OVERHEAT"]

**Golden sample**:
- 고정 데이터로 매일 같은 결과 보장 — DUOL, HOOD, NVDA 시나리오
- EM → M1 transition 시나리오 fixture 1개 (5일 simulation)

**통합 테스트**:
- `MODE=momentum_only` E2E — 페이지 생성 + Telegram + history 기록
- `MOMENTUM_DISABLE_EM=1` 회귀 — EM 평가만 빠지고 v1.0 결과 동일
- EMA 필드 부재 (예: 신규 IPO 65일 미만) → EM 평가 자동 skip

### 7.6 배포 체크리스트

- [ ] `requirements.txt` 변경 없음 (pandas EMA는 기존 의존성)
- [ ] schema_version 2 마이그레이션 첫 실행 검증
- [ ] EM 결과 페이지 첫 노출 검증 (deploy)
- [ ] Telegram 메시지 길이 ≤ 3500
- [ ] 백테스트 데이터 누적 90일 미만 시 "—" 표시
- [ ] Sector Rotation Radar 0개일 때 블록 자동 숨김
- [ ] CLAUDE.md "진행 중인 계획" 섹션 등재
- [ ] Detail 페이지 Maturity 라인 노출 검증

### 7.7 리스크 / 완화책

| 항목 | 리스크 | 완화책 |
|---|---|---|
| EMA9 데이터 부족 (신규 IPO) | EM 평가 불가 | None 처리 → tier=None, 기존 M+ 평가는 별도로 정상 |
| Full IWB 1000개 EM 평가 비용 | yfinance rate limit | Pre-filter (ema9>ema21 + close>ema21) 1차 게이트로 ~250 압축, 가중 검사는 그 다음 |
| EM false positive (잡주 펌프) | 신호 품질 저하 | RSI<72 + dist_ema9<8% + vol_ratio≥1.05 anti-overheat. 추가로 transition_to_M1_pct로 신호 품질 monitor |
| EM ↔ M1 진동 | history streak/change 흔들림 | M+ 우선 + EM RANK=0으로 자연 UPGRADE 처리. DOWNGRADE도 가능 |
| Maturity 임계값 부정확 | EARLY/EXTENDED 분류 오해 | 6개월 후 backtest 결과 기반 재튜닝 (v1.5.1) |
| Risk Tag 마이그레이션 | 기존 history 호환 | filter_legacy_tags 자동 처리, 새 작성은 새 셋 |

## 8. v1.5 Scope vs Future

### v1.5 (이번 작업 범위)

**필수**:
- EMA9/21/65 + 5 derived 글로벌 필드 (`fetch_market_data.py`)
- Maturity 분류기 (EARLY/MID/EXTENDED)
- EM tier (Full IWB universe, 단일 tier)
- Tier 우선순위 (M+ > EM)
- Risk Tag 정리 (EARLY/EXTENDED 삭제)
- 두 섹션 분리 UI + Sector Rotation Radar
- EM history 통합 (RANK 0) + transition_to_M1_pct backtest
- Position hint 2축 결합
- 마이그레이션 (schema_version 1 → 2)

### Phase 2 (별도 spec — Lifecycle)

- TREND_OK / PULLBACK / EARLY_TRIGGER / CONFIRMED_TRIGGER 상태머신
- EMA21 흡수 감지 (PULLBACK)
- Volume confirmation transition (CONFIRMED)
- 시간축 진입 타이밍 표시 — "지금 들어가도 되는가" 판단

### Phase 3 (Roadmap)

- Sector Rotation Radar 시계열 누적 → "X 섹터 7일 연속 EM 카운트 증가" 알림
- EM expectancy를 활용한 dynamic threshold (transition_to_M1_pct < 30% 시 임계값 자동 강화)
- Maturity calibration backtest (실제 EARLY 진입의 5d expectancy vs MID/EXTENDED)
- Multi-tier display (Tier × Maturity × Lifecycle 매트릭스 뷰)

## 9. 결정 요약 (Q&A 기록)

| # | 질문 | 결정 |
|---|---|---|
| Q1 | Phase 1 스코프 | B — Emerging + Maturity 통합, Lifecycle은 Phase 2 |
| Q2 | Maturity 분류기 임계값 | B+ — EXTENDED(dist_ema9≥8% OR RSI≥75), EARLY(dist_ema9<3% AND RSI<68 AND ema9>ema21) |
| Q3 | EM universe 및 조건 | B — Full IWB, 단일 tier, sector annotation only. ema21 rising 3d + 5d≥4% OR 20d≥10% + vol≥1.05 |
| Q4-1 | Risk Tag 정리 | A — EARLY/EXTENDED 삭제 (Maturity가 흡수), OVERHEAT/PARABOLIC만 유지 |
| Q4-2 | EMA 필드 위치 | A — 글로벌 (fetch_market_data.py). slope는 numeric (categorical 아님). 계산 책임 fetch layer 단일화 |
| Q5-1 | M vs EM 우선순위 | A — M+ 우선. tier는 단일 라벨 |
| Q5-2 | EM history/backtest | A — 통합 history (RANK 0), transition_to_M1_pct가 핵심 KPI |
| Q5-3 | UI 레이아웃 | A — 두 섹션 분리. Sector Rotation Radar 블록 추가. Change/Price 컬럼 제거, dist_ema9 필수 유지. Maturity 색상 강조 |

**철학 정리**:
- Discovery: Leaders(Relative Strength) + Emerging(Structural Inflection) — 별도 트랙
- Timing: Maturity (EARLY/MID/EXTENDED) — Phase 2 Lifecycle로 정밀화
- Risk: OVERHEAT/PARABOLIC + Portfolio Stop Signal v1.0 — 별도 레이어
- 가장 가치 있는 조합: **EM + EARLY** (구조 형성 + 미과열 + sector rotation 단서)
