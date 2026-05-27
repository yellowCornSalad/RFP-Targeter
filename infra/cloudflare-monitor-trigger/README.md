# Cloudflare Workers Monitor Trigger

GitHub Actions schedule cron 발화 불안정 우회용.  
매 5분마다 Cloudflare 외부에서 `monitor_crawler.yml` 워크플로우를 강제 dispatch.

## 작동 원리

```
Cloudflare cron (5분) ──POST──> GitHub Actions workflow_dispatch
                                    │
                                    ▼
                              monitor_crawler.yml 실행
                                    │
                       ┌────────────┴───────────┐
                       │                        │
              크롤러 정상 (< 60분)   크롤러 정지 (> 60분)
                       │                        │
                  점검 종료              [자동조치]
                                        gh workflow run crawl.yml
                                                │
                                                ▼
                                       크롤 실행 + 슬랙 알림
```

## 셋업 (15분)

### 1. GitHub Personal Access Token (PAT) 발급

1. https://github.com/settings/tokens 접속
2. "Generate new token (classic)" 클릭
3. 권한: **`workflow`** (Update GitHub Action workflows)
4. 만료: 90일 또는 No expiration
5. **토큰 복사** (한 번만 보임)

### 2. Cloudflare 계정 + Wrangler CLI

```bash
# 1. https://dash.cloudflare.com 에서 무료 계정 가입
# 2. wrangler 설치
npm install -g wrangler

# 3. 로그인
wrangler login
```

### 3. 배포

```bash
cd infra/cloudflare-monitor-trigger

# GitHub PAT 을 secret 으로 저장
wrangler secret put GH_PAT
# (프롬프트에 위에서 복사한 PAT 붙여넣기)

# (선택) 수동 trigger 용 토큰
wrangler secret put TRIGGER_TOKEN
# (랜덤 문자열 입력, 예: 32자 hex)

# 배포
wrangler deploy
```

### 4. 검증

배포 후:

```bash
# Cloudflare 대시보드 > Workers > rfp-monitor-trigger > Logs
# → 5분 이내 "Monitor dispatched OK" 로그 보여야 함

# GitHub > Actions > Monitor Crawler Health
# → 5분 안에 새 run 시작되어야 함 (workflow_dispatch 트리거)
```

수동 테스트:

```bash
curl -X POST https://rfp-monitor-trigger.{your-subdomain}.workers.dev \
  -H "X-Trigger-Token: {your-trigger-token}"

# → {"status":204,"message":"dispatched"} 응답
```

## 비용

| 항목 | 사용량 | 한도 (Free) |
|---|---|---|
| Workers requests | 5분×288회 = 288/일 | 100,000/일 |
| CPU time | 거의 0 | 10ms/요청 |
| Cron triggers | 288/일 | 무제한 (Free) |

→ **무료 충분** (실 사용량의 0.3%만 차지).

## 유지보수

### PAT 만료 시 (90일)

```bash
wrangler secret put GH_PAT
# 새 PAT 입력
```

### cron 주기 변경

`wrangler.toml` 의 `crons` 수정 후 `wrangler deploy`.

```toml
crons = ["*/3 * * * *"]   # 3분마다
crons = ["*/10 * * * *"]  # 10분마다
```

### 일시 비활성화

```bash
# Cloudflare 대시보드 > Workers > rfp-monitor-trigger > Triggers
# → "Pause" 클릭 또는 cron 삭제 후 redeploy
```

## 트러블슈팅

### "Monitor dispatch FAILED — status=401"

PAT 권한 부족. https://github.com/settings/tokens 에서 **`workflow`** 권한 다시 체크 + 재발급.

### "Monitor dispatch FAILED — status=404"

워크플로우 파일 경로 확인. `worker.js` 의 `WORKFLOW` 상수가 실제 파일명과 일치해야 함 (`monitor_crawler.yml`).

### "Monitor dispatch FAILED — status=422"

`ref: 'main'` 이 실제 존재하는 branch 인지 확인. `worker.js` 의 `REF` 상수.

## 대안 (Workers 안 쓰고 더 간단히)

**cron-job.org** 같은 무료 cron 서비스로 HTTP 요청만 보내도 동일 효과:

```
URL: https://api.github.com/repos/yellowCornSalad/RFP-Targeter/actions/workflows/monitor_crawler.yml/dispatches
Method: POST
Headers:
  Authorization: Bearer {GH_PAT}
  Accept: application/vnd.github+json
  X-GitHub-Api-Version: 2022-11-28
  User-Agent: cron-job-monitor-trigger
Body: {"ref":"main"}
Schedule: */5 * * * *
```

이게 더 빠르지만 Cloudflare Workers 는:
- 로깅 자체 대시보드 (실패 자동 알림 가능)
- 코드 버전 관리 (git)
- 수동 trigger HTTP endpoint 보너스

→ 두 가지 중 선택. 본 디렉터리는 Workers 방식.
