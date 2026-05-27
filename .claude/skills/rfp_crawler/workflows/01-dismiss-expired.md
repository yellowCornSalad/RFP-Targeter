# Workflow 01 — 만료 공고 자동 dismiss

신청기한 지난 공고를 `is_dismissed=TRUE` 로 soft delete. 24/7 실행 (영업시간 제한 X).

## 목적

마감 지난 공고는:
- 사용자가 신청 불가 = 노이즈
- 슬랙 알림으로 가면 안 됨 (사용자 시간 낭비)
- 정적 사이트 카드에도 노출 X
- 단 DB 에는 보존 (회고·통계·과거 매칭 키워드 가치)

## 실행 단계

### 1. 만료 공고 식별

```sql
SELECT COUNT(*) FROM announcement
WHERE is_dismissed = FALSE
  AND deadline_at IS NOT NULL
  AND deadline_at != ''
  AND deadline_at < CURRENT_DATE::text;
```

### 2. 일괄 dismiss

```sql
UPDATE announcement
SET is_dismissed = TRUE
WHERE is_dismissed = FALSE
  AND deadline_at IS NOT NULL
  AND deadline_at != ''
  AND deadline_at < CURRENT_DATE::text;
```

→ `rowcount` 가 dismiss 된 건수.

### 3. 결과 로그

```
[자동조치] 만료 공고 N건 dismiss (soft delete, deadline < today)
```

stdout 출력 — GitHub Actions Run 로그에서 확인 가능.

## 자동 연쇄 효과

dismiss 된 row 는 다음 SQL 들에서 자동 제외:

| 시스템 | 필터 조건 |
|--------|---------|
| 슬랙 dispatch | `is_dismissed = FALSE` |
| 정적 사이트 build | `is_dismissed = FALSE` |
| 모니터 헬스 점검 (score NULL, 누락 슬랙 등) | `is_dismissed = FALSE` |

dismiss 단계 직후 모든 후속 SQL 이 깨끗한 활성 공고만 봄.

## 복구 (실수 시)

```sql
-- 특정 id 복구
UPDATE announcement SET is_dismissed = FALSE WHERE id = 'kisa:403-10670';

-- 전체 복구 (위험 — 정말 만료 공고가 다시 활성으로 잘못 들어옴)
-- 권장 X. 사용자 명시 요청 시에만.
UPDATE announcement SET is_dismissed = FALSE WHERE deadline_at < CURRENT_DATE::text;
```

## 호출 시점

- `scripts/monitor_crawler.py main()` 시작 시 무조건 호출
- GitHub Actions monitor_crawler.yml — 평일 09:15~18:45 매 30분 발화
- 비영업시간 (점검·알림 skip) 에도 dismiss 는 실행 (24/7)

## 비고

- `deadline_at IS NULL` 인 공고는 dismiss 안 함 (등록 60일 컷오프로 활성 필터에서 자연스럽게 제외)
- `deadline_at = ''` (빈 문자열) 도 dismiss 안 함 — IS NOT NULL 만으로 부족, `!= ''` 가드
- 시간대: PostgreSQL `CURRENT_DATE` 는 서버 시각 (UTC). 자정 직후 1시간 정도 KST 와 어긋날 수 있음 (무시 가능 범위)
