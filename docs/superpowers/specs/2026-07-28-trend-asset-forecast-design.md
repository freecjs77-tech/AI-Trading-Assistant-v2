# Trend Page 20년 자산 예측 그래프 Design

## 개요

트렌드 페이지에 현재 포트폴리오(합산 총자산)를 시작점으로 향후 20년간의 자산 변화를
복리 시뮬레이션으로 예측하는 인터랙티브 그래프를 추가한다. 사용자가 연 수익률을
슬라이더로 조절하면 예측 라인이 실시간으로 재계산된다.

## 확정된 요구사항

1. **계산 방식**: 단순 복리 (고정 연 수익률). `value = start × (1 + r)^year`
2. **추가 납입**: 없음 (순수 복리만). 시작 자산이 그대로 복리 증식.
3. **연 수익률**: 슬라이더로 조절 (인터랙티브, JS 클라이언트 사이드).
4. **시작값**: 합산(전체) 총자산 고정.
5. **표시 조건**: **합산 토글 선택 시에만** 섹션 표시. 내 포트/와이프 선택 시 숨김.
6. **예측 기간**: 20년.
7. **배치**: 트렌드 페이지 (`templates/trend_template.html`).

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

섹션 전체는 **합산 토글 선택 시에만** 보이도록 한다. 합산 토글은 멀티 owner 환경에만
존재하므로 섹션을 `{% if has_multi_owner %}` 로 감싸고, 초기 상태는 `hidden` 클래스로
숨긴다 (기본 선택 owner는 `me`). 이후 owner 토글 클릭 시 JS가 표시/숨김을 제어한다.
`id="forecastSection"` 로 감싸 JS가 접근한다.

섹션 구성:
- 제목: `📈 향후 20년 자산 예측 (복리 시뮬레이션)` — 기존 `<h2>` 헤딩 패턴 재사용
- 연 수익률 슬라이더: `<input type="range">` 범위 **1~15%, step 0.5**, 기본 **7%**
- 현재 수익률 라벨: 슬라이더 옆에 `연 7.0%` 형태로 표시
- 예측 라인 차트: `<canvas id="forecastChart">`
- 요약 readout: **5년 / 10년 / 15년 / 20년 후** 예상 자산 (억원) 4개 카드.
  `grid-template-columns:repeat(auto-fit,minmax(130px,1fr))` 로 좁은 화면에서 2×2 줄바꿈.
  각 카드에 연도 라벨(예: `2031`) 병기.

### 2. 계산 로직 (JS)

```js
// 섹션은 합산 토글 전용이므로 ownersPayload.combined는 항상 존재
const startEok = ownersPayload.combined.latest.total_eok;  // 합산 총자산 (억원)
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
  갱신 → `chart.update()` → 라벨(`연 X.X%`)과 4개 readout 카드(5/10/15/20년) 갱신
- readout 포맷: `startEok × (1+r)^n` (n = 5,10,15,20) 를 억원으로 표시 (소수점 1자리)
- 마일스톤 연도 라벨 = `baseYear + n`

### 4. 표시 조건 & 시작값 정책 (합산 전용)

이 차트는 **합산 토글이 선택됐을 때만** 보인다. 시작값은 항상 합산 총자산
`ownersPayload.combined.latest.total_eok` 로 페이지 로드 시 한 번 확정하고 변경하지 않는다.

기존 owner 토글 핸들러(`#ownerToggle .owner-btn` 클릭 리스너)에서 선택된 owner에 따라
`#forecastSection` 의 `hidden` 클래스를 토글한다:
- `owner === 'combined'` → `hidden` 제거 (표시) + 최초 표시 시 차트가 아직 생성 안 됐으면 lazy init
- 그 외(`me`/`wife`) → `hidden` 추가 (숨김)

초기 로드는 `me`가 기본 선택이므로 섹션은 `hidden` 상태로 시작한다.
Chart.js는 `display:none` 컨테이너에서 크기 측정이 부정확할 수 있으므로,
차트 인스턴스는 **합산이 처음 선택되어 섹션이 보이게 된 시점에 lazy 생성**한다.

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
  - `#fxChart` 섹션 다음에 예측 섹션 HTML 추가 (`{% if has_multi_owner %}`,
    `id="forecastSection"`, 초기 `hidden`, 슬라이더 + canvas + readout)
  - `<script>` 하단에 `forecastChart` lazy 생성 + 슬라이더 이벤트 핸들러 추가
  - 기존 owner 토글 클릭 리스너에 `#forecastSection` 표시/숨김 로직 추가
  - `{% if data_days >= 1 %}` 블록 안에 배치

**변경 없음:** `report_generator.py`, `pipeline.py`, 모든 히스토리/데이터 파일.

## 검증 계획

- 로컬에서 트렌드 페이지 렌더 후 브라우저 프리뷰로 확인:
  - 초기 로드(me 선택)에서 예측 섹션이 숨겨져 있는가
  - 합산 토글 선택 시 예측 섹션이 나타나고 차트가 정상 렌더되는가
  - 다시 내 포트/와이프 선택 시 섹션이 숨겨지는가
  - 슬라이더 이동 시 라인·라벨·4개 readout 카드가 실시간 갱신되는가
  - 기본 7%에서 20년 후 값이 `start × 1.07^20 ≈ start × 3.87` 와 일치하는가
    (합산 29.2억 기준: 5년 41.0억 / 10년 57.4억 / 15년 80.6억 / 20년 113.0억)
  - 다크/라이트 테마 전환 시 정상 표시되는가
