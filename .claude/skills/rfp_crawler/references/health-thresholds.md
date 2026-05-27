# 헬스 임계값 정책

크롤러가 "정상 작동 중"이라고 판단하는 기준. `scripts/monitor_crawler.py` 의 상수와 1:1 매칭.

## 핵심 임계값

| 지표 | 임계 | 코드 상수 | 위반 시 조치 |
|------|------|---------|------------|
| 마지막 fetch_log `finished_at` 경과 시간 | **60분 초과** | `GAP_MINUTES_THRESHOLD = 60` | 슬랙 알림 (크롤러 정지) |
| 최근 5 run 중 cancelled 건수 | **2건 이상** | `CANCELLED_PATTERN_THRESHOLD = 2` | 슬랙 알림 (timeout 패턴) |
| 활성 보안 공고 중 score NULL | 1건 이상 | — | `backfill_scores.py` 권장 |
| 슬랙 누락 후보 (영업시간) | 1건 이상 | — | `dispatch_pending_alerts()` 자동 호출 |
| 만료 공고 (deadline < today) | 1건 이상 | — | `is_dismissed=TRUE` 자동 처리 |

## 영업시간 정의

- 평일 (월~금) 09:00 ~ 18:00 KST
- 외 시간: 점검·알림 skip, 단 **만료 dismiss 는 24/7 실행**
- 코드: `_is_business_hours(now)` — `now.weekday() < 5 and 9 <= now.hour <= 18`

## 임계값 조정 가이드

| 상황 | 권장 변경 |
|------|----------|
| 슬랙 알림 너무 많이 옴 (false positive) | `GAP_MINUTES_THRESHOLD` 60 → 90 |
| 크롤러 정지를 더 빨리 감지하고 싶음 | 60 → 45 (단 cancel 직후 false positive 가능) |
| cancel 패턴 임계 강화 | `CANCELLED_PATTERN_THRESHOLD` 2 → 3 (5건 중 3건+ 일 때만) |

변경 시 `scripts/monitor_crawler.py` 상수도 같이 업데이트.

## 활성 공고 정의 (Slack·UI 공통)

```sql
WHERE is_security = TRUE
  AND is_dismissed = FALSE
  AND source IN ('iitp','kisa','kosa','krit','nipa','mss','koica')
  AND (deadline_at >= CURRENT_DATE::text
       OR (deadline_at IS NULL
           AND posted_at >= (CURRENT_DATE - 60)::text))
```

비활성·만료는 모니터 점검 대상에서 제외 (의도된 무시).
