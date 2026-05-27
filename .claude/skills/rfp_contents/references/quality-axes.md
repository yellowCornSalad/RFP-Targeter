# 콘텐츠 품질 5축 기준

`scripts/audit_contents.py` 의 `audit_quality()` 가 측정하는 5가지 축. 각 축마다 임계 미만이면 회귀 의심.

## 1축: 예산·기간 정확성

**측정**:
```sql
SELECT
  COUNT(*) FILTER (WHERE budget_mw IS NOT NULL) AS has_budget,
  COUNT(*) FILTER (WHERE budget_period IS NOT NULL) AS has_period
FROM announcement WHERE 활성_보안_조건;
```

**임계**:
- 예산 추출률 ≥ **40%** (현실적 — 모든 공고에 예산 명시 X)
- 기간 추출률 ≥ **40%**

**위반 시**:
1. `budget_extract.py` 패턴 점검 (사업금액·기초가격·계약금액)
2. KISA/NIPA 첨부 본문 통합률 확인 — 첨부에 예산 명시되는데 본문 통합 안 되면 추출 실패
3. budget_excerpt 가 본문에 실제 존재하는지 검증 (hallucination 방지)

## 2축: 본문 가독성

**측정**:
```sql
SELECT
  COUNT(*) FILTER (WHERE LENGTH(body) >= 300) AS body_ge_300,
  COUNT(*) FILTER (WHERE body LIKE '%§§HEAD§§%') AS has_head_token
FROM announcement WHERE 활성_보안_조건;
```

**임계**:
- 본문 300자 이상 ≥ **80%** (의미 있는 본문 보유)
- 가독성 토큰(§§HEAD§§) — 정적 빌드 시점에 부여되므로 DB raw 에는 0% 가 정상

**위반 시 (body < 300자가 많음)**:
1. KOSA 어댑터 본문 추출 셀렉터 점검 (table.view / div.bv_cont)
2. NIPA decompose 순서 점검 (`known-regressions.md` 참조)

## 3축: 상세보기 가독성

**측정 없음 — 정적 사이트 코드 검증**

`build_static.make_readable()` 가 정부 공문 마커를 §§HEAD§§ / §§NOTE§§ 토큰으로 변환. `app.js renderBody()` 가 토큰 보고 `.body-head` / `.body-note` 클래스 입힘.

**임계**:
- `styles.css` 의 `.body-head` border-bottom 2px 유지
- `.body-note` 좌측 border 3px + 회색 배경 유지
- `.body-pre` line-height 1.85+ 유지

코드 변경 시 회귀 점검. UI 스크린샷 확인 권장.

## 4축: 키워드 매칭 정확성

**측정**:
```sql
SELECT source, COUNT(*) AS total,
       COUNT(*) FILTER (WHERE body LIKE '%[첨부 본문]%') AS att_in_body,
       AVG(jsonb_array_length(matched_keywords_json::jsonb)) AS avg_kw
FROM announcement WHERE 활성_보안_조건
GROUP BY source;
```

**임계 (source 별)**:

| source | 첨부 통합률 | 평균 매칭 키워드 |
|--------|------------|---------------|
| iitp | ≥ 80% | ≥ 15 |
| mss | ≥ 90% | ≥ 25 |
| kisa | ≥ 60% | ≥ 12 |
| nipa | ≥ 80% | ≥ 12 |
| kosa | (사이트 자체 첨부 적음 — 별도 임계 X) | ≥ 5 |
| krit | (분기별 데이터 적음) | ≥ 5 |
| koica | (어댑터 비활성) | — |

**위반 시**:
1. `base.enrich_body_with_attachments()` 호출 누락 확인 (해당 어댑터 fetch_detail 끝)
2. 첨부 다운로드 실패 다수 — 정부 사이트 SSL 또는 인증 변경
3. `extract_text` PDF/HWP 추출 라이브러리 점검

## 5축: 카드 LLM 요약 (ai_summary)

**측정**:
```sql
SELECT COUNT(*) FILTER (WHERE ai_summary IS NOT NULL) AS has_summary,
       COUNT(*) AS total
FROM announcement WHERE 활성_보안_조건;
```

**임계**: 보유율 ≥ **80%** (body ≥ 300자 인 row 중)

신규 공고는 매시 7분 cron (`build_summaries.yml`) 이 50건 제한으로 처리. 24시간 지나면 ~95% 도달이 정상.

**위반 시**:
1. `ANTHROPIC_API_KEY` GitHub Secret 만료 확인
2. `build_summaries.yml` 최근 run 상태 — fail 이면 로그
3. Anthropic API 잔액 / rate limit

## 종합 판정 (audit_quality 결과)

5축 중 2축 이상 임계 위반 → 콘텐츠 품질 회귀. 사용자에게 즉시 보고 + 어떤 축에서 회귀했는지 명시.

1축 위반은 일시적 (한 사이클 cron 실패) 일 수 있으니 다음 사이클 후 재측정.
