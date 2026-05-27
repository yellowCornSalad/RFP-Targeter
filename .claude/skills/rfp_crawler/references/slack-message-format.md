# 슬랙 모니터 알림 메시지 포맷

`scripts/monitor_crawler.py` 의 `_send_slack_alert()` 가 발사하는 메시지 템플릿.

## 헤더

```
🚨 *[RFP-Targeter 모니터]* {YYYY-MM-DD HH:MM} KST
```

- 시작은 항상 🚨 이모지로 시각적 주의 환기
- `*굵게*` 헤더로 일반 슬랙 알림과 분리
- KST 시각 명시 (UTC 안 됨 — 사용자 혼란 방지)

## 본문 (이슈 목록)

```
• 🚨 크롤러 정지 — 마지막 정상 완료 87분 전 (12:43 KST)
• ⚠ GitHub Actions crawl.yml 최근 5 run 중 3건 cancelled (timeout 패턴 추정)
• ⚠ 활성 보안 공고 중 score NULL 7건 (backfill_scores.py 권장)
```

이슈마다 이모지:
- 🚨 — 즉시 조치 필요 (크롤러 정지)
- ⚠ — 주의 (패턴화된 이슈, 일시적일 수도)

## 푸터 (조치 권장)

```
조치 권장: `gh workflow run crawl.yml --ref main` (수동 트리거)
```

코드 백틱으로 명령어 강조. 사용자가 복사 실행 가능하게.

## 발송 빈도 제한

- monitor_crawler.yml 이 30분마다 발화 → 같은 이슈가 30분 마다 반복 알림
- 노이즈 우려 시 임계 통과한 이슈만 발사 (현재 그렇게 동작)
- 미래: `last_alert_at` 추적해서 30분 이내 동일 이슈는 skip 옵션 추가 고려

## 발송 채널

- `secrets.yaml` 의 `slack.webhook_url`
- GitHub Actions 환경에서는 `secrets.SLACK_WEBHOOK_URL` 자동 주입
- webhook 미설정 시 조용히 skip (로그만 남김)

## 자동 조치 (알림 대신)

다음 이슈는 슬랙 알림 없이 자동 fix:

| 이슈 | 자동 조치 |
|------|----------|
| 슬랙 누락 후보 (영업시간) | `dispatch_pending_alerts()` 즉시 호출 → 누락 알림 발사 |
| 만료 공고 (deadline < today) | `is_dismissed = TRUE` UPDATE |
| score NULL (활성 보안) | (자동 X — 알림만, `backfill_scores.py` 수동 실행 권장) |

자동 조치는 stdout 로그로 남김 — GitHub Actions Run 로그에서 확인.
