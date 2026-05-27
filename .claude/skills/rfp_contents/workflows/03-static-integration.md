# Workflow 03 — 정적 사이트 통합

생성된 `ai_summary` 가 GitHub Pages 카드에 노출되도록 빌드 → 배포.

## 데이터 흐름

```
DB.announcement.ai_summary
       │
       ▼
build_static.fetch_data()
       │  SELECT a.ai_summary FROM ... → items[i].ai_summary
       ▼
site/data.json
       │  { "ai_summary": "이 사업은 KISA가...", ... }
       ▼
app.js renderCard()
       │  ${it.ai_summary ? `<p class="card-summary">...` : ""}
       ▼
카드 HTML — 제목 아래 회색 박스
```

## 빌드 트리거

### 자동 (paths 매칭)

`.github/workflows/build_static.yml` 의 paths 필터:
```yaml
paths:
  - 'scripts/build_static.py'
  - 'scripts/static_templates/**'
  - 'config/keywords.yaml'
  - 'src/rfp_targeter/filters/**'
  - 'src/rfp_targeter/scoring/**'
```

→ ai_summary 코드/CSS 변경 push 시 자동 발화.

### 자동 (cron)

```yaml
schedule:
  - cron: '5 * * * *'   # 매시 5분
```

매시 5분에 자동 빌드 — DB 의 최신 ai_summary 반영. crawl(매시 0분) + build_summaries(매시 7분) 와 살짝 어긋남 주의.

**시각표**:
```
HH:00  crawl.yml 시작
HH:05  build_static.yml 시작 (이 시점엔 build_summaries 미발화)
HH:07  build_summaries.yml 시작
HH:10  build_summaries 끝남 (50건 처리 가정)
       → 다음 build_static (HH+1:05) 에서 반영
```

→ 신규 ai_summary 는 다음 시간대 카드에 반영됨. 1시간 지연 정상.

### 수동 (즉시 반영)

```bash
gh workflow run build_static.yml --ref main
```

dispatch 후 약 1~2분 뒤 GitHub Pages 갱신.

## UI 위치 (app.js)

```js
return `
  <div class="card ${gradeCls}">
    ...
    <h3 class="card-title">${title}</h3>
    ${it.ai_summary ? `<p class="card-summary">${escapeHtml(it.ai_summary)}</p>` : ""}
    ${eligLine}
    ${metaBits.length > 0 ? `<div class="card-meta">...</div>` : ""}
    ...
  </div>
`;
```

- 카드 제목 바로 아래
- 자격 미달 라인 위
- ai_summary 없으면 (`it.ai_summary` falsy) 영역 자체 안 그림 (폴백 X)

## CSS (.card-summary)

```css
.card-summary {
  color: #444;
  font-size: 13.5px;
  line-height: 1.6;
  margin: 0 0 10px;
  padding: 10px 14px;
  background: #fafafa;
  border-left: 3px solid #bbb;
  border-radius: 2px;
  font-weight: 400;
  letter-spacing: -0.005em;
}
```

- 회색 배경 + 좌측 border → 본문 영역과 시각 분리
- 제목보다 작은 폰트 (13.5px) — 보조 정보임을 표시
- BMW 톤 일관 (회색 #fafafa, border #bbb)

## 폴백 동작

`ai_summary` 가 NULL 인 row:
- 카드에 `<p class="card-summary">` 영역 자체 안 그림
- 사용자는 그냥 제목 + 메타 + 키워드 칩만 봄
- ❌ body 미리보기 폴백 안 함 (이전 `body_preview` 는 raw text 라 가독성 X)

## 점검

새로고침 후:
1. 카드에 제목 아래 회색 박스 보이는지
2. 박스 안 텍스트가 150자 이내인지
3. boilerplate ("본 공고는 ... 모집합니다") 가 아닌 사업 본질 명시인지

대표 샘플 5건 정도 spot check 권장.

## 빌드 실패 시

`build_static.yml` Run 이 빨간불:
1. `gh run view <id> --log` — Python 에러 메시지 확인
2. 흔한 원인:
   - data.json 너무 큼 (10MB+) — GitHub Pages 1MB 제한 도달 위험
   - SQL 에러 — `ai_summary` 컬럼 누락 시 (마이그레이션 안 됐을 때)
3. fix 후 재 dispatch
