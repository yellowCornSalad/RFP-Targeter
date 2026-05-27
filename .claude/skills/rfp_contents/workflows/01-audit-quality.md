# Workflow 01 — 5축 품질 점검

LLM 호출 전 먼저 콘텐츠 품질을 SQL 통계로 측정. 임계 미만 축이 있으면 보고.

## 실행

```bash
python scripts/audit_contents.py --audit-only
```

`--audit-only` 옵션 = LLM 호출 안 함, 통계만 출력.

## 출력 예시

```
=== rfp_contents 콘텐츠 점검 + LLM 요약 ===

[활성 보안 공고] 총 321건
  · ai_summary 보유율:  87% (279)
  · 예산 추출률:        45% (143)
  · 기간 추출률:        45% (143)
  · 본문 300자 이상:    93% (297)
  · 가독성 토큰(HEAD):  0% (0)
  · 첨부 본문 통합률:   79% (252)

[source별 통계]
  src     total  첨부통합  평균본문  평균매칭
  kisa       53   62.3%     8889자   16.4
  nipa       90   94.4%     4595자   14.1
  mss        40   95.0%    13548자   28.2
  iitp      110   87.3%     7082자   17.7
  kosa       28    0.0%      907자    7.1
```

## 해석 가이드

각 수치를 `references/quality-axes.md` 의 임계값과 비교:

### 정상 범위

- ai_summary 보유율 80%+ → ✅
- 예산·기간 추출률 40%+ → ✅
- 본문 300자 80%+ → ✅
- 첨부 통합률 (source별 임계 참조)

### 회귀 신호

- 보유율 갑자기 떨어짐 → `build_summaries.yml` cron 실패 또는 API key 만료
- 평균 매칭 < 10 → 첨부 통합 실패 또는 보안 필터 키워드 누락
- kosa·krit 평균 본문 < 1000자 → 사이트 자체 데이터 적음 (정상, 무시)

## 점검 후 조치

| 발견 | 다음 워크플로우 |
|------|--------------|
| ai_summary 보유율 < 80% | `02-generate-summary.md` 실행 |
| 첨부 통합률 < 임계 | RFP-Targeter `base.enrich_body_with_attachments` 점검 |
| 평균 매칭 < 10 | `keywords.yaml` 키워드 누락 또는 `security_filter.py` 버그 |
| budget 추출률 < 40% | `budget_extract.py` 패턴 + KISA budget_mw 백필 (task #70) |

## 점검 빈도

- 수동: 사용자 요청 시 또는 큰 변경 후
- 자동: 없음 (audit_quality 자체는 가벼우니 매번 generate_summaries 호출 전에 표시)

## SQL 직접 호출 (참고)

```sql
SELECT
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE ai_summary IS NOT NULL) AS has_summary,
  COUNT(*) FILTER (WHERE budget_mw IS NOT NULL) AS has_budget,
  COUNT(*) FILTER (WHERE budget_period IS NOT NULL) AS has_period,
  COUNT(*) FILTER (WHERE LENGTH(COALESCE(body,'')) >= 300) AS body_ge_300,
  COUNT(*) FILTER (WHERE body LIKE '%[첨부 본문]%') AS att_in_body
FROM announcement
WHERE is_security=TRUE AND is_dismissed=FALSE
  AND source IN ('iitp','kisa','kosa','krit','nipa','mss','koica')
  AND (deadline_at >= CURRENT_DATE::text
       OR (deadline_at IS NULL
           AND posted_at >= (CURRENT_DATE - 60)::text));
```

특정 axis 만 빠르게 확인하고 싶을 때 직접 실행.
