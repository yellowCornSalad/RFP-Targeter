# Workflow 03 — 이상 발견 시 대응

슬랙 [모니터] 알림이 왔거나 GitHub Actions Run 이 빨간불일 때 단계별 조치.

## 신호별 대응표

### 🚨 "크롤러 정지 — 마지막 정상 완료 N분 전"

**의미**: GitHub Actions cron 이 60분 이상 정상 완료 안 됨.

**원인 후보**:
1. crawl.yml cron 이 30분 timeout 으로 cancelled (IITP 어댑터 hang)
2. GitHub Actions 자체 장애 (드물지만 발생)
3. cron schedule 설정 변경 / 비활성화

**조치 순서**:

```bash
# 1. 최근 cron 상태 확인
gh run list --workflow=crawl.yml --limit 5

# 2. 가장 최근 cancelled run 로그 확인
gh run view <run-id> --log | tail -50

# 3. 수동 트리거 (즉시 1 사이클 실행)
gh workflow run crawl.yml --ref main

# 4. 5분 후 다시 확인
gh run list --workflow=crawl.yml --limit 2
```

**근본 fix** (재발 패턴이면):
- `config/settings.yaml` `sources.iitp.max_per_source` 50 → 30
- 또는 `references/known-regressions.md` 의 IITP timeout 섹션 참고

### ⚠ "최근 5 run 중 N건 cancelled (timeout 패턴 추정)"

**의미**: 일시적 hang 이 아니라 패턴화된 timeout. 어댑터 자체 문제.

**조치**:

```bash
# 1. cancelled 패턴의 공통점 확인 — 같은 어댑터에서 멈췄나?
for id in $(gh run list --workflow=crawl.yml --limit 5 --json databaseId -q '.[].databaseId'); do
  echo "=== $id ==="
  gh run view $id --log | grep -E "Run crawl pipeline" | tail -3
done

# 2. fetch_log 에서 finished_at NULL 인 source 통계
psql $DATABASE_URL -c "
  SELECT source, COUNT(*) FILTER (WHERE finished_at IS NULL) AS hung
  FROM fetch_log
  WHERE started_at > NOW() - INTERVAL '24 hours'
  GROUP BY source ORDER BY hung DESC;
"
```

→ 항상 IITP 가 hung 이면 `iitp.max_per_source` 추가 축소 또는 fetch_detail 분리.

### ⚠ "score NULL N건 — backfill_scores.py 권장"

**의미**: 활성 보안 공고 중 점수 계산이 안 된 row 가 있음. 보통 새 키워드 추가 또는 보안 필터 재평가 직후 발생.

**조치**:

```bash
# 1. 활성 score NULL 즉시 백필
python scripts/backfill_scores.py

# 2. 비활성도 한 번에 (회고용 데이터까지 보장 시)
python scripts/backfill_scores.py --all
```

자동 안전망 (`pipeline._backfill_missing_scores()`) 가 매 사이클 끝에 호출되므로 다음 cron 후엔 자동 해소. 단 cron 이 cancelled 되면 또 누적.

### 자동 dispatch (알림 없음)

슬랙 누락 후보 발견 시 알림 보내지 않고 즉시 `dispatch_pending_alerts()` 호출. 사용자는 알림 자체로 확인.

로그에 나타남:
```
[자동조치] 슬랙 누락 7건 dispatch — sent=True
```

## 사후 분석

이슈 해결 후 다음 정보 기록:

1. **발생 시각** — 슬랙 알림 시각
2. **근본 원인** — known-regressions.md 의 어떤 패턴인지 또는 새로운 회귀인지
3. **fix** — 임시 (수동 트리거) vs 근본 (코드 변경)
4. **재발 방지** — `references/known-regressions.md` 에 추가

새 회귀 패턴이면 `health-thresholds.md` 임계값 조정도 고려.

## 비상 — 모니터 자체 fail

`monitor_crawler.yml` 이 5분 timeout 으로 cancelled 또는 슬랙 알림이 안 옴:

1. `gh run list --workflow=monitor_crawler.yml --limit 3` 상태 확인
2. 마지막 success 시각 확인
3. `DATABASE_URL` / `SLACK_WEBHOOK_URL` secret 만료 검토
4. `scripts/monitor_crawler.py --silent` 로컬 실행해서 코드 자체 문제인지 분리

모니터가 죽으면 크롤러 문제를 발견 못 함 — 우선순위 높게.
