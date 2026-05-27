# Workflow 02 — 헬스 점검 6단계

크롤러가 정상 작동 중인지 검증. 평일 09~18 KST 영업시간에만 실행 (비주간은 skip).

## 0단계: 만료 dismiss (사전)

→ `workflows/01-dismiss-expired.md` 참조. 본 점검 시작 전 항상 실행.

## 1단계: 영업시간 확인

```python
now = datetime.now(ZoneInfo("Asia/Seoul"))
is_business = now.weekday() < 5 and 9 <= now.hour <= 18
if not is_business:
    return "skip — 비주간 시간"
```

비영업시간이면 점검·알림 모두 skip. 단 만료 dismiss(0단계)는 이미 실행됨.

## 2단계: 마지막 크롤 시각

```sql
SELECT MAX(finished_at) AS last_finished
FROM fetch_log
WHERE finished_at IS NOT NULL;
```

`last_finished` 는 UTC text. KST 변환 후 `now - last_finished` 계산.

**임계**: 60분 초과 → 슬랙 알림 (크롤러 정지)

```
🚨 크롤러 정지 — 마지막 정상 완료 87분 전 (12:43 KST)
```

## 3단계: GitHub Actions 최근 5 run conclusion

```bash
gh run list --workflow=crawl.yml --limit 5 \
  --json conclusion,createdAt,databaseId
```

각 run 의 `conclusion`:
- `success` — 정상
- `cancelled` — 30분 timeout 또는 동시 실행 충돌
- `failure` — 명시적 에러
- `null` — 진행 중

**임계**: cancelled ≥ 2 건 → 슬랙 알림 (timeout 패턴)

```
⚠ GitHub Actions crawl.yml 최근 5 run 중 3건 cancelled (timeout 패턴 추정)
```

## 4단계: score NULL (안전망)

```sql
SELECT COUNT(*) FROM announcement a
LEFT JOIN score s ON s.announcement_id = a.id
WHERE s.announcement_id IS NULL
  AND a.is_security = TRUE AND a.is_dismissed = FALSE
  AND (a.deadline_at >= CURRENT_DATE::text
       OR (a.deadline_at IS NULL
           AND a.posted_at >= (CURRENT_DATE - 60)::text));
```

활성 보안 공고 중 점수가 안 계산된 row.

**임계**: 1 건 이상 → 슬랙 알림 (`backfill_scores.py` 권장)

평소엔 0이어야 함 (pipeline 의 `_backfill_missing_scores()` 가 사이클 끝에 자동 보강).

## 5단계: 슬랙 누락 후보

```sql
SELECT COUNT(*) FROM announcement a
JOIN score s ON s.announcement_id = a.id
WHERE a.is_security = TRUE AND a.is_dismissed = FALSE
  AND a.source IN ('iitp','kisa','kosa','krit','nipa','mss','koica')
  AND s.total_score >= 80
  AND a.budget_mw IS NOT NULL AND a.budget_mw >= 100
  AND (a.deadline_at >= CURRENT_DATE::text
       OR (a.deadline_at IS NULL
           AND a.posted_at >= (CURRENT_DATE - 60)::text))
  AND a.alerted_at IS NULL;
```

총점 ≥ 80 AND 예산 ≥ 1억 AND 활성 AND 아직 알림 안 보낸 row.

**자동 조치**: 영업시간이면 `dispatch_pending_alerts()` 즉시 호출 → 슬랙 묶음 발송.
영업시간 외라면 누적 (다음 영업일 09시 첫 cron 이 처리).

## 종합 판정

이슈 1개 이상 발견 → exit code 1 + 슬랙 알림 발사
모두 통과 → exit code 0 + "✅ 모든 점검 통과" 로그

GitHub Actions Run 페이지에서 빨간색 / 녹색으로 한눈에 확인.

## 알림 발송 매트릭스

| 단계 | 임계 위반 시 | 자동 조치 |
|------|------------|----------|
| 1 | 영업시간 외 | skip — 알림 없음 |
| 2 | gap > 60분 | 슬랙 알림 |
| 3 | cancelled ≥ 2 | 슬랙 알림 |
| 4 | score NULL ≥ 1 | 슬랙 알림 (수동 backfill 권장) |
| 5 | pending ≥ 1 | **자동 dispatch_pending_alerts()** (알림 없음, 누락만 발사) |
