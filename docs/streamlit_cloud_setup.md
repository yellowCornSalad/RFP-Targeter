# Streamlit Community Cloud 배포 가이드

GitHub Actions가 매시간 Supabase에 데이터를 쌓고, Streamlit Cloud가 그 데이터를 웹페이지로 띄움.
**PC를 꺼도 24/7 작동**, 어떤 기기·브라우저에서도 URL로 접속.

> 사전 조건
> 1. GitHub Actions 셋업 완료 — `docs/github_actions_setup.md` 참고
> 2. Supabase DB 활성 + DATABASE_URL 확보
> 3. `profile.yaml` base64 한 줄 (`scripts/encode_profile_for_github.py` 실행 결과)

---

## 📋 7단계 셋업 (약 10분)

### 1️⃣ Streamlit Cloud 가입
```
https://share.streamlit.io
```
- **"Sign in with GitHub"** 클릭 (가입 = 무료, 즉시 가능)
- 권한 승인 → 화면에 본인의 GitHub 레포 목록이 보임

### 2️⃣ 신규 앱 생성
- 우상단 **"Create app"** 버튼 → **"Yes, deploy a public app from GitHub"** 선택
  - (Private 가능하지만 무료 한도 1개 — public도 비밀번호 보호되어 있어 충분)
- 다음 정보 입력:

| 필드 | 값 |
|---|---|
| **Repository** | `yellowCornSalad/RFP-Targeter` |
| **Branch** | `main` |
| **Main file path** | `src/rfp_targeter/dashboard.py` |
| **App URL** | `enki-rfp` 같이 짧게 (전체 URL: `enki-rfp.streamlit.app`) |

### 3️⃣ Advanced settings → Python version
- **"Advanced settings"** 펼침
- **Python version**: `3.11` 선택 (또는 `runtime.txt` 자동 인식)

### 4️⃣ Secrets 등록 (가장 중요)

같은 Advanced settings 안에 **"Secrets"** 큰 텍스트 박스가 있음.
TOML 포맷으로 아래 내용 통째로 붙여넣기 (값은 본인 것으로 교체):

```toml
DATABASE_URL = "postgresql://postgres.pkencmbryzgtnwrxlksz:%40%40zmzm3354321%40%40@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"

DATA_GO_KR_KEY = "xcjmOs938MfzLWnUORs6dW..."

ANTHROPIC_API_KEY = "sk-ant-api03-..."

SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/..."

DASHBOARD_PASSWORD = "원하는비번"

PROFILE_YAML_B64 = "한줄짜리base64긴문자열..."
```

> 💡 `DASHBOARD_PASSWORD`만은 새로 정해야 함. 잊지 말 것.
> 💡 `SLACK_WEBHOOK_URL`은 지금 없어도 됨 (슬랙 권한 받은 뒤 추가).
> 💡 GitHub Secrets와 동일한 값들 — 그대로 복붙하면 됨.

### 5️⃣ Deploy 클릭
- **"Deploy!"** 버튼 클릭
- 1~3분 대기 → 빌드 로그가 우측에 흐름
- 완료되면 **`https://enki-rfp.streamlit.app`** (본인이 정한 슬러그)로 자동 이동

### 6️⃣ 첫 접속
- 화면에 🔒 **비밀번호 입력 페이지** 나타남 (정상)
- 4단계의 `DASHBOARD_PASSWORD` 값 입력 → **로그인**
- 대시보드 정상 표시 확인

### 7️⃣ 자동 배포 확인
- 로컬에서 `dashboard.py` 한 줄 수정 → `git push origin main`
- Streamlit Cloud 자동 감지 → 30초~2분 내 재빌드 → 새 코드 반영
- (Streamlit Cloud 상단에 "Rebooting..." 표시됨)

---

## 🔄 작동 흐름 (배포 후)

```
[GitHub Actions]                    [Streamlit Cloud]                [사용자]
매시 정각                            상시 가동                          언제든
  ↓                                    ↓                                ↓
8개 사이트 크롤링                   Supabase에서 SELECT              브라우저로
  ↓                                    ↓                            URL 접속
Supabase upsert  ←──── 데이터 ────→ 대시보드 렌더                    → 로그인
  ↓                                                                   → 조회
신규 발견 → 슬랙 webhook
```

- **데이터 원천 1곳** (Supabase) — Actions가 쓰고, Streamlit이 읽음
- **로컬 PC 불필요** — 둘 다 클라우드에서 돌아감

---

## 💰 비용

| 자원 | 무료 한도 | 우리 예상 |
|---|---|---|
| Streamlit Community Cloud | Public app 무제한 | **무료** |
| Streamlit Cloud Private | 1개까지 무료 | 필요 시 1개 사용 가능 |
| Supabase | 500MB DB + 5GB 대역폭 | ~50MB / ~1GB → **무료** |
| GitHub Actions (Public repo) | 무제한 | **무료** |
| GitHub Actions (Private repo) | 월 2,000분 | 시간당 1회 = 한도 내 |
| Anthropic Claude | 후불 | 사용 시에만 |

전체 합계: **무료** (현재 사용량 기준)

---

## 🔍 모니터링

| 무엇을 보고 싶나 | 어디로 |
|---|---|
| 앱 라이브 로그 | `https://share.streamlit.io` → 본인 앱 → "Manage app" |
| 앱 빌드 실패 원인 | 같은 화면의 logs 탭 |
| 데이터가 들어오는지 | Supabase 대시보드 → Table Editor → `announcements` |
| 크롤링이 도는지 | `https://github.com/yellowCornSalad/RFP-Targeter/actions` |
| 슬랙 알림 | 등록한 슬랙 채널 |

---

## ⚠️ 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| 빌드 실패: `psycopg not found` | requirements.txt 누락 | 본 리포에 이미 포함 — 재배포 |
| 화면이 안 뜨고 흰 페이지 | secrets 미등록 | Manage app → Secrets 확인 |
| `DATABASE_URL 미설정` 에러 | Secrets TOML 문법 오류 | 값 양쪽에 따옴표(`"`) 필수 |
| 비번 입력 후에도 무한 로딩 | `DASHBOARD_PASSWORD` 값에 공백/줄바꿈 | 다시 등록 |
| 데이터 0건 | profile.yaml 디코딩 실패 | `PROFILE_YAML_B64` 재인코딩 (`scripts/encode_profile_for_github.py`) |
| 갑자기 sleep | 1주일 무접속 시 zzZ | 접속하면 ~10초 안에 깨어남 |
| 새 코드 반영 안 됨 | 캐시 문제 | Manage app → "Reboot app" 수동 클릭 |

---

## 🔐 보안

- **Secrets는 git에 절대 안 들어감** — Streamlit Cloud UI에만 저장
- **로그인 페이지**가 첫 관문 — `DASHBOARD_PASSWORD` 모르면 데이터 안 보임
- Supabase pooler URL의 비밀번호 부분 `%40%40zmzm3354321%40%40`은 URL 인코딩 결과
  (실제 비번 `@@zmzm3354321@@`을 `%40` 처리). 노출됐으므로 작업 완료 후 **Supabase에서 reset** 권장
- 비밀번호 변경 시: Secrets에서 `DASHBOARD_PASSWORD` 수정 → Reboot

---

## 🔁 코드/데이터/Secrets 업데이트 방법

| 무엇 | 방법 | 자동 반영 |
|---|---|---|
| 대시보드 코드 | `git push origin main` | ✅ 30초~2분 |
| 크롤러 코드 | `git push origin main` | ✅ 다음 시간 사이클에 반영 |
| profile.yaml 수정 | 로컬에서 수정 → base64 재인코딩 → GitHub Secrets & Streamlit Secrets 둘 다 업데이트 | ❌ 수동 |
| DATABASE_URL 변경 | 두 곳 모두 업데이트 | ❌ 수동 |
| 비밀번호 변경 | Streamlit Secrets만 수정 | ✅ Reboot |

---

## 📎 참고 링크

- Streamlit Cloud 대시보드: https://share.streamlit.io
- GitHub Actions: https://github.com/yellowCornSalad/RFP-Targeter/actions
- Supabase Dashboard: https://supabase.com/dashboard
- 본 리포: https://github.com/yellowCornSalad/RFP-Targeter
