# 외부 cron 트리거 셋업 (cron-job.org)

GitHub Actions free plan 의 schedule cron 누락 우회 — 매시 정각 100% 발화 보장.

## 동작 흐름

```
cron-job.org (매시 정각) ──POST──> GitHub API workflow_dispatch
                                    ↓
                            crawl.yml 강제 실행
                                    ↓
                          크롤 → 슬랙 [완료] 알림
```

PC OFF 와 완전 무관. 365일 작동.

---

## 1단계: GitHub Personal Access Token (PAT) 발급 (2분)

1. https://github.com/settings/tokens 접속 (GitHub 로그인 필요)
2. **"Generate new token (classic)"** 클릭
3. 설정:
   - **Note**: `cron-job.org for RFP-Targeter`
   - **Expiration**: `90 days` (또는 No expiration)
   - **Select scopes**: ✅ **`workflow`** 만 체크 (다른 권한 X)
4. 하단 **"Generate token"** 클릭
5. **토큰 복사** — `ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxx` 형태
   ⚠️ **이 화면 떠난 후 다시는 안 보임** — 안전한 곳에 메모

---

## 2단계: cron-job.org 회원가입 (1분)

1. https://cron-job.org 접속
2. **"Sign up free"** 클릭
3. 이메일 + 비밀번호 입력 → 이메일 인증
4. 로그인

---

## 3단계: Cron Job 생성 (2분)

1. 좌측 메뉴 **"Cronjobs"** → **"Create cronjob"** 버튼
2. 다음 정보 입력:

### Common

| 필드 | 값 |
|---|---|
| **Title** | `RFP-Targeter Hourly Crawl` |
| **URL** | `https://api.github.com/repos/yellowCornSalad/RFP-Targeter/actions/workflows/crawl.yml/dispatches` |

### Schedule

- **Schedule** → "Custom" 선택
- 또는 좌측 정시 옵션: `Every hour at minute 00`
- Cron expression: `0 * * * *` (매시 정각)

### Advanced (중요!)

**Request method**: `POST`

**Request headers** (3줄 추가, 각 줄마다 "Add header" 클릭):

| Name | Value |
|---|---|
| `Authorization` | `Bearer ghp_xxxxxxxx여기에_PAT_붙여넣기` |
| `Accept` | `application/vnd.github+json` |
| `X-GitHub-Api-Version` | `2022-11-28` |

**Request body** (옵션, 일부 UI는 raw body 입력 가능):
```json
{"ref":"main"}
```
※ body 입력 칸 없으면 빈칸 두고 진행 (GitHub API 가 default `ref=main` 처리)

### Save

**"Create cronjob"** 클릭

---

## 4단계: 즉시 테스트 (30초)

1. 방금 만든 cronjob 행에서 **"Test run"** 또는 ▶ 버튼 클릭
2. 5초 후 cron-job.org 의 **"History"** 탭 확인:
   - Status `204 No Content` → ✅ **성공** (GitHub workflow_dispatch 정상 응답)
   - Status `401` → ❌ PAT 잘못됨 (workflow 권한 체크 + 복붙 다시)
   - Status `404` → ❌ URL 오타 (대소문자 정확히)
3. https://github.com/yellowCornSalad/RFP-Targeter/actions 들어가서 **"Hourly Crawl"** 새 run 시작됐는지 확인 (1~3초 안)

---

## 5단계: 모니터링

- cron-job.org **History** 탭: 매 실행 결과 (200/204 = OK, 다른 코드 = 문제)
- 알림: cron-job.org Notifications → "Email me on failure" 체크 권장
- 매시 정각 ± 1분 안에 GitHub Actions 새 run 시작되면 정상

---

## 비용

| 항목 | 한도 (Free) | 사용 |
|---|---|---|
| Cron jobs | 50개 | 1개 (RFP-Targeter Crawl) |
| Executions/day | 무제한 | 24회/일 |
| Notifications | 무제한 | 실패 시 이메일 |

→ **완전 무료**.

---

## PAT 만료 시 (90일 후)

1. 새 PAT 발급 (위 1단계 반복)
2. cron-job.org → 본 job 편집 → Authorization 헤더 값 교체 → Save

---

## 문제 해결

### "401 Unauthorized"
- PAT 권한에 `workflow` 누락 → 새 PAT 발급
- `Bearer ` 앞 공백 또는 토큰 복사 오타 — 다시 확인

### "404 Not Found"
- URL 오타. 정확히: `https://api.github.com/repos/yellowCornSalad/RFP-Targeter/actions/workflows/crawl.yml/dispatches`
- 워크플로우 파일명 `crawl.yml` 맞는지 (대소문자 정확)

### "422 Unprocessable Entity"
- `{"ref":"main"}` body 또는 main branch 존재 확인

### GitHub Actions 에서 run 안 시작
- cron-job.org History 가 `204` 인데 GitHub Actions 에 새 run 없음
- → 잠시 후 (최대 1분) 다시 확인. workflow_dispatch 는 비동기

---

## 부가 효과 — 기존 schedule cron 도 그대로 유지

GitHub Actions `crawl.yml` 의 `schedule: '0 * * * *'` 는 그대로 두세요:
- 둘 다 매시 정각 발화 시도
- GitHub schedule 이 누락해도 cron-job.org 가 보완
- 같은 시각에 둘 다 발화하면 `concurrency: cancel-in-progress: false` 로 한 번만 실행 (안전)

→ **이중 안전망**.

---

## 적용 후

매시 정각 (10:00, 11:00, 12:00, ...) ± 1분 안에:
1. cron-job.org 가 GitHub API 호출 → 204 응답
2. GitHub Actions Hourly Crawl run 시작
3. 18~22분 후 완료
4. 슬랙 [크롤 완료] 알림 도착

**누락 0건 보장**. PC OFF / 주말 / 한밤중 무관.
