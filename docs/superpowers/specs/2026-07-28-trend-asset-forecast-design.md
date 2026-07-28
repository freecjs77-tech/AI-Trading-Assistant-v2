# Trend Page 20년 자산 예측 그래프 Design

## 개요

트렌드 페이지에 현재 포트폴리오(합산 총자산)를 시작점으로 향후 20년간의 자산 변화를
복리 시뮬레이션으로 예측하는 인터랙티브 그래프를 추가한다. 사용자가 연 수익률을
슬라이더로 조절하면 예측 라인이 실시간으로 재계산된다.

## 확정된 요구사항

1. **계산 방식**: 단순 복리 (고정 연 수익률). `value = start × (1 + r)^year`
2. **추가 납입**: 없음 (순수 복리만). 시작 자산이 그대로 복리 증식.
3. **연 수익률**: 슬라이더로 조절 (인터랙티브, JS 클라이언트 사이드).
4. **시작값**: 합산(전체) 총자산 고정. owner 토글과 무관하게 항상 합산 기준.
5. **예측 기간**: 20년.
6. **배치**: 트렌드 페이지 (`templates/trend_template.html`).

## 접근 방식: 순수 클라이언트 사이드 (Approach A)

슬라이더·계산·차트를 전부 JS로 처리한다. 계산이 `start × (1+r)^y` 로 단순하므로
클라이언트에서 즉시 재계산 가능하다. 시작값은 이미 템플릿에 주입된
`ownersPayload`/`latest` 컨텍스트에서 읽으므로 **백엔드를 전혀 건드리지 않는다**.

**기각된 대안:**
- **B. 백엔드 예측 시리즈 생성**: 슬라이더 실시간 조절에 어차피 JS 재계산이 필요하므로
  백엔드 계산은 중복. 비효율.
- **C. 실제 히스토리 + 예측 연결**: 실제 데이터(6개월)와 예측(20년)의 X축 스케일이
  심하게 달라 시각적 왜곡. 별도 차트로 분리하는 것이 나음.

## 상세 설계

### 1. 배치 & DOM 구조

트렌드 페이지 최하단 매크로 차트(USD/KRW 환율 `#fxChart`) **다음**, 푸터 주석 **앞**,
`{% if data_days >= 1 %}` 블록 안에 새 섹션을 추가한다 (시작값이 `latest`에 의존하므로
히스토리가 있을 때만 표시).

섹션 구성:
- 제목: `📈 향후 20년 자산 예측 (복리 시뮬레이션)` — 기존 `<h2>` 헤딩 패턴 재사용
- 연 수익률 슬라이더: `<input type="range">` 범위 **1~15%, step 0.5**, 기본 **7%**
- 현재 수익률 라벨: 슬라이더 옆에 `연 7.0%` 형태로 표시
- 예측 라인 차트: `<canvas id="forecastChart">`
- 요약 readout: **10년 후 / 20년 후** 예상 자산 (억원) 두 개 값

### 2. 계산 로직 (JS)

```js
const startEok = (ownersPayload.combined && ownersPayload.combined.latest.total_eok)
               ?? {{ latest.total_eok }};   // 합산 총자산 (억원), 폴백: me latest
const HORIZON = 20;
const baseYear = parseInt("{{ date }}".slice(0, 4), 10);  // 2026

function forecastSeries(ratePct) {
  const r = ratePct / 100;
  const out = [];
  for (let y = 0; y <= HORIZON; y++) {
    out.push(startEok * Math.pow(1 + r, y));
  }
  return out;  // [현재, +1년, …, +20년], 억원 단위
}
```

- X축 라벨: 실제 연도 `baseYear … baseYear+20` (2026 … 2046)
- 단일 데이터셋, 점선 라인 (예측임을 시각적으로 표현)
- 색상: secondary 계열 `#00E5BC`, `borderDash:[6,4]`

### 3. 인터랙션

- 슬라이더 `input` 이벤트 → `forecastSeries(rate)` 재계산 → `forecastChart.data.datasets[0].data`
  갱신 → `chart.update()` → 라벨(`연 X.X%`)과 readout(10년/20년 값) 갱신
- readout 포맷: `startEok × (1+r)^10`, `× (1+r)^20` 를 억원으로 표시 (소수점 1자리)

### 4. 시작값 정책 (합산 고정)

owner 토글(내 포트/와이프/합산)을 움직여도 이 차트는 **항상 합산 총자산** 기준으로 고정한다.
즉 `_applyOwner()` 함수의 재렌더 대상에 **포함하지 않는다**. 시작값은 페이지 로드 시
`ownersPayload.combined.latest.total_eok` 로 한 번 확정하고 이후 변경하지 않는다.
`combined`가 없는 단일 포트 환경에서는 `{{ latest.total_eok }}` (me 합산)로 폴백.

### 5. 백엔드 영향

**없음.** 변경 파일은 `templates/trend_template.html` 단 하나.
`report_generator.py`, `pipeline.py`, 히스토리 JSON, 데이터 스키마 전부 무변경.

### 6. 테마/스타일

- 기존 차트들과 동일한 Chart.js 옵션·색상 변수(`dso`, `isDark`, `Chart.defaults`) 재사용
- 슬라이더는 Tailwind 유틸리티로 스타일 (`accent-primary` 등)
- 다크/라이트 테마 모두 기존 변수로 자동 대응

## 파일 변경 요약

**Modify:**
- `templates/trend_template.html`
  - `#fxChart` 섹션 다음에 예측 섹션 HTML 추가 (슬라이더 + canvas + readout)
  - `<script>` 하단에 `forecastChart` 생성 + 슬라이더 이벤트 핸들러 추가
  - `{% if data_days >= 1 %}` 블록 안에 배치

**변경 없음:** `report_generator.py`, `pipeline.py`, 모든 히스토리/데이터 파일.

## 검증 계획

- 로컬에서 트렌드 페이지 렌더 후 브라우저 프리뷰로 확인:
  - 슬라이더 이동 시 라인·라벨·readout이 실시간 갱신되는가
  - 기본 7%에서 20년 후 값이 `start × 1.07^20 ≈ start × 3.87` 와 일치하는가
  - owner 토글을 움직여도 예측 차트가 합산 기준으로 고정되는가
  - 다크/라이트 테마 전환 시 정상 표시되는가
