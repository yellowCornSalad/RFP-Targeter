# GitHub Actions 24/7 자동 크롤링 셋업

PC 안 켜도 GitHub 서버에서 **매 시간 자동 크롤링 → Supabase 저장 → 슬랙 알림** 작동.

---

## 📋 5단계 셋업

### 1️⃣ profile.yaml 인코딩
```powershell
cd D:\RFP-Targeter
python scripts/encode_profile_for_github.py
```
출력된 **base64 한 줄** 복사 (긴 문자열).

### 2️⃣ GitHub Secrets 등록

브라우저로:
```
https://github.com/yellowCornSalad/RFP-Targeter/settings/secrets/actions
```
→ **`New repository secret`** 버튼 클릭, 아래 5개 등록:

| Secret 이름 | 값 |
|---|---|
| `DATABASE_URL` | `postgresql://postgres.pkencmbryzgtnwrxlksz:%40%40zmzm3354321%40%40@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres` |
| `DATA_GO_KR_KEY` | data.go.kr 마스터 키 (예: `xcjmOs938MfzLWnUORs6dW...`) |
| `ANTHROPIC_API_KEY` | `sk-ant-api03-...` (Anthropic 키, 옵션 — 크롤만 하면 불필요) |
| `SLACK_WEBHOOK_URL` | 슬랙 권한 받으면 `https://hooks.slack.com/services/...` |
| `PROFILE_YAML_B64` | 1단계에서 출력된 base64 한 줄 |

### 3️⃣ Workflow 활성화
```
https://github.com/yellowCornSalad/RFP-Targeter/actions
```
- 좌측 `Hourly Crawl` 클릭
- 페이지 우측 **`Enable workflow`** (Actions 기본 비활성 상태일 때만)

### 4️⃣ 첫 수동 실행 (테스트)
- 같은 페이지 우측 **`Run workflow`** 드롭다운 → `Run workflow` 버튼
- 1~5분 대기 → 실행 결과 ✅/❌ 확인
- 실패 시 로그 클릭해서 에러 확인

### 5️⃣ 매 시간 자동 동작 확인
- 정각마다 자동 트리거 (cron `0 * * * *`)
- Actions 탭에서 매 시간 실행 이력 확인
- 신규 보안 공고 발견 시 슬랙으로 알림

---

## ⏰ 작동 흐름 (배포 후)

```
매시 정각 (KST)
  ↓
GitHub Actions 컨테이너 spin-up (Python 3.11 우분투)
  ↓
pip install -e .  (psycopg, anthropic, ...)
  ↓
PROFILE_YAML_B64 → config/profile.yaml 디코드
  ↓
python scripts/run_once.py
  ├─ 8개 어댑터 (KISA / IITP / NTIS / KOSA / NIPA / KRIT / MSS / ...)
  ├─ 본문 추출 → 보안 필터 → 점수 산정 → 자격 검증
  ├─ Supabase에 upsert (PostgreSQL)
  └─ 신규 보안 공고 1+ → 슬랙 webhook 발송
  ↓
컨테이너 종료. 다음 시간까지 무비용.
```

---

## 💰 비용

| 자원 | 무료 한도 | 우리 예상 |
|---|---|---|
| GitHub Actions (Public repo) | 무제한 | OK |
| GitHub Actions (Private repo) | 월 2,000분 | 1회 5분 × 24시간 × 30일 = **3,600분 → 초과** |
| Supabase | 500MB / 5GB 대역폭 | 50MB / 1GB → OK |
| Anthropic Claude | 후불 | 사용자 클릭 시에만 |
| Slack Webhook | 무제한 | OK |

> **Private repo 비용 주의**: 매 시간이 너무 잦으면 한도 초과 가능. 옵션:
> - **2시간**으로 변경: `cron: '0 */2 * * *'` → 월 1,800분 (한도 내)
> - **업무 시간만**: `cron: '0 9-18 * * 1-5'` → 평일 낮만, 월 ~300분
> - public repo로 변경 (data·secrets는 보호되니 코드는 공개 OK)

---

## 🔍 모니터링

- **실행 이력**: https://github.com/yellowCornSalad/RFP-Targeter/actions
- **실시간 로그**: 실행 클릭 → `crawl` job → `Run crawl pipeline` step 펼침
- **실패 시 자동 알림**: GitHub 계정 이메일로 발송 (Settings → Notifications)
- **DB 상태**: Supabase 대시보드 → Table Editor

---

## ⚠️ 트러블슈팅

| 에러 | 원인 | 해결 |
|---|---|---|
| `DATABASE_URL 미설정` | secret 이름 오타 또는 미등록 | Settings → Secrets 확인 |
| `Tenant or user not found` | URL의 user/host 오타 | DATABASE_URL 형태 재확인 |
| `password authentication failed` | URL의 password 부분 오타 | Supabase Reset password로 재발급 |
| `psycopg.errors.DuplicatePreparedStatement` | pooler 호환 미설정 | 이미 처리됨 (`prepare_threshold=None`) |
| `Connection timeout` | Supabase 일시 sleep | 1주일 미사용 시 발생 — 자동 깨어남, 다음 사이클에 OK |
| Workflow 안 돌음 | 60일 무활동 시 자동 비활성화 | Actions 탭에서 수동 트리거로 재활성화 |
| 슬랙 알림 안 옴 | webhook 미설정 또는 신규 0건 | 신규 0건이면 정상 (조용 모드) |

---

## 🔄 로컬과 GitHub 둘 다 돌리는 경우

- 같은 Supabase DB 가리키므로 **데이터 충돌 없음**
- 로컬 스케줄러는 끄는 게 좋음 (이중 polling 낭비) — `taskkill /F /PID <pid>`
- 로컬 Streamlit 대시보드는 그대로 사용 (Supabase 데이터 읽기만)
