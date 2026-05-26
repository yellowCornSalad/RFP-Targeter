# RFP-Targeter

**엔키화이트햇** 공공 R&D 공고 자동 탐색 시스템 — IITP·KISA·KOSA·KRIT·NIPA·MSS·KOICA 7개 기관 매시간 폴링 → 보안 키워드 매칭 → 5축 점수 → 정적 사이트 + 슬랙 알림.

🌐 **Live**: [https://yellowcornsalad.github.io/RFP-Targeter/](https://yellowcornsalad.github.io/RFP-Targeter/) (v1.0)

![RFP-Targeter Dashboard](docs/screenshots/dashboard.png)

---

## 인프라 (24/7, PC OFF 무관)

| 컴포넌트 | 위치 | 주기 |
|---|---|---|
| 크롤링 | GitHub Actions | 매시 정각 |
| DB | Supabase PostgreSQL | 클라우드 상주 |
| 대시보드 | GitHub Pages (정적 빌드) | 매시 자동 갱신 |
| 슬랙 알림 | Incoming Webhook | 평일 09~18 KST |
| 회귀 경보 | Slack | 첨부율 임계값 미만 시 |

---

## 빠른 시작

```powershell
# 0. 의존성
pip install -e .

# 1. 회사 프로필 추출 (enkiwhitehat.com → config/profile.yaml)
python scripts/init_profile.py
# → config/profile.yaml 열어서 ??? 표시된 항목 채우기

# 2. 크롤 1회 실행 (Mock 데이터로 파이프라인 검증)
python scripts/run_once.py

# 3. 대시보드
streamlit run src/rfp_targeter/dashboard.py

# 4. 백그라운드 폴링 (별도 터미널)
python -m rfp_targeter.scheduler
```

---

## 디렉터리 구조

```
RFP-Targeter/
├── .streamlit/
│   └── config.toml            # Cobalt Blue 네이티브 테마
├── config/
│   ├── settings.yaml          # 폴링 주기, 점수 가중치, 소스 enable
│   ├── keywords.yaml          # 보안 1차 필터 키워드
│   ├── secrets.example.yaml   # API 키 템플릿
│   ├── secrets.yaml           # (gitignore) 실제 키
│   ├── profile.example.yaml   # 회사 프로필 템플릿
│   └── profile.yaml           # (gitignore) 실제 프로필
├── data/
│   ├── rfp.db                 # SQLite (gitignore)
│   └── attachments/           # 첨부 파일 다운로드 (gitignore)
├── templates/                 # 기관별 RFP 양식 (gitignore, 자동 채워짐)
├── drafts/                    # 자동 생성된 초안 (gitignore)
├── assets/
│   ├── enki_logo.png          # 사이드바 로고
│   └── theme_previews/        # 후보 테마 6종 HTML mockup
├── src/rfp_targeter/
│   ├── config.py
│   ├── pipeline.py            # 크롤 → 필터 → 점수 → 저장 오케스트레이션
│   ├── scheduler.py           # 1시간 폴링 (APScheduler)
│   ├── dashboard.py           # Streamlit UI (Cobalt 테마 + production UX)
│   ├── crawlers/              # 사이트별 어댑터 (9종)
│   ├── filters/               # 보안 키워드 필터
│   ├── scoring/               # 5축 점수 + 테마 적합도
│   ├── attachments/           # 첨부 다운로더 + 텍스트 추출 + 자동 분류
│   ├── profile/               # 회사 프로필 추출기
│   ├── drafter/               # RFP 초안 생성기 (수동 + Claude API)
│   └── db/                    # SQLite 스키마 + 모델
└── scripts/
    ├── run_once.py            # 1회 크롤
    ├── verify_crawlers.py     # 어댑터 검증 (소스별 3건 샘플)
    ├── init_profile.py        # 회사 프로필 초기 추출
    ├── generate_drafts.py     # 초안 일괄 생성
    └── iitp_retry.py          # IITP 단독 재시도
```

---

## 점수 산정 (5축, 각 0~100)

총점 = 5축 가중합(0.35·0.10·0.20·0.20·0.15) + **theme_fit 보너스** (최대 ±20)

| 축 | 의미 | 가중치 | 데이터 신뢰도 |
|----|------|-------|--------------|
| **keyword** | 회사 핵심 키워드 매칭도 | **0.35** | ⭐⭐⭐ 본문 직접 매칭 |
| **budget** | 회사 적정 예산 범위 적합 | **0.10** | ⭐⭐ 본문 명시 시 / 없으면 35 폴백 |
| **consortium** | 컨소시엄 구성 부담(낮을수록 ↑) | **0.20** | ⭐⭐ 본문 키워드 휴리스틱 |
| **competitor** | 경쟁 상황(적을수록 ↑) | **0.20** | ⭐ **휴리스틱 추정만** ([한계 참조](#-경쟁-점수의-한계)) |
| **trl** | 회사 보유 기술 TRL 적합 | **0.15** | ⭐⭐⭐ 본문 TRL 패턴 추출 |

별도 지표: **theme_fit** (회사 테마 적합도, 0~100) — 총점에 보너스로 가산.

가중치는 `config/settings.yaml` 의 `scoring_weights` 에서 조정.

---

### 🔎 각 축 산정 공식 상세

#### 1. keyword (가중치 0.35) — `scoring/keyword.py`
회사 `profile.yaml` 의 키워드가 공고 제목·요약·본문에 등장하는지.

```
baseline = 30  (보안 필터 통과한 시점에서 회사 영역으로 인정)

+ core_keywords 매칭 1개당          +18
+ positioning_keywords 매칭 1개당    +12
+ 기타 보안 필터 매칭 1개당          +8
+ 보안 필터 매칭 ≥ 8개 풍부 보너스   +5
= 최종 (max 100)
```

> profile.yaml 의 `core_keywords` 미설정 시 → 중립 50점 폴백.

#### 2. budget (가중치 0.10) — `scoring/budget.py`
공고에 명시된 예산이 회사가 설정한 sweet spot 범위 안인지.

```
profile.yaml.budget_range = { min, max, sweet_spot_min, sweet_spot_max }

본문 예산 미명시              → 35점 (정보 부족 페널티)
sweet_spot_min ≤ 예산 ≤ sweet_spot_max  → 100점
회사 min 미만                 → 20점 (너무 작음)
회사 max 초과                 → 25점 (단독 수행 부담)
sweet spot 밖 + 회사 범위 내  → 60~99점 (선형 감점)
```

> 가중치 0.10으로 작게 — 본문에 예산 안 나오는 경우 다수라 신뢰도 낮춤.

#### 3. consortium (가중치 0.20) — `scoring/consortium.py`
공고가 컨소시엄 구성을 요구하는지, 회사가 그걸 만족할 수 있는지.

```
baseline = 100  (단독 수행 가능 가정)

본문에 "대학·산학·교수" 신호 발견:
  - 회사에 KAIST 등 대학 파트너 있음 (profile.yaml.consortium.university_partner_available=true)
    → −5  (활용 가능)
  - 대학 파트너 없음 → −35

본문에 "컨소시엄·공동연구·참여기관" 신호 발견:
  - 회사 max_partners ≥ 3 → −10
  - max_partners < 3 → −30

컨소시엄 신호 없음:
  - profile.yaml.consortium.solo_capable=true → 변동 없음 (단독 수행)
  - solo_capable 미설정 → −10
```

#### 4. competitor (가중치 0.20) — `scoring/competitor.py`
공고 본문의 키워드로 영역 난이도 추정.

```
baseline = 50  (정보 없으면 중간값)

대형 경쟁 키워드 (대기업 강한 영역):
  "통합 플랫폼", "관제", "SOC", "SIEM"
  → 매칭 1개당 −15 (최대 −35)

전문 영역 키워드 (경쟁 적음 추정):
  "양자내성", "PQC", "동형암호", "비밀계산",
  "AI 보안", "공격 시뮬레이션", "보안성 검증"
  → 매칭 1개당 +15 (최대 +40)

본문 200자 미만             → −5  (신뢰도 낮춤)
profile.competitors 회사명 본문 등장 → −15
```

##### ⚠️ 경쟁 점수의 한계

**우리 시스템은 실제 응찰자 수를 모릅니다.** 정부 입찰은 익명 진행이고, 응찰 정보는 낙찰 후에만 공개됩니다. 그래서 이 점수는:

- **본문 키워드 기반 영역 난이도 추정치** — 실제 경쟁자 수와 다를 수 있음
- **baseline 50인 경우 = "추정 불가, 중간값"** — 본문에 위 키워드가 하나도 안 잡혔다는 뜻
- KISA 사전규격공개 의견 접수는 비공개 이메일 채널 → 외부 수치화 불가
- 향후 G2B 낙찰결과 API 또는 발주기관별 통계로 강화 검토 (별도 트랙)

→ 카드 검토 시 **keyword·budget·TRL 축을 더 신뢰**하고, competitor는 **참고 지표**로만 보세요.

#### 5. trl (가중치 0.15) — `scoring/trl.py`
공고에서 요구되는 기술 성숙도(TRL 1~9)와 회사 보유 TRL의 갭.

```
본문에서 TRL 추정:
  "TRL 5~7" 패턴 직접 명시  → 5~7
  "기초연구·탐색연구" 등장   → TRL 3
  "실증·사업화·상용화"       → TRL 7
  "원천기술·응용연구"        → TRL 5
  추정 불가                  → 45점 (정보 부족)

회사 보유 TRL (profile.yaml.technologies[*].trl) 와의 갭:
  gap 0 (일치)    → 100점
  gap 1           →  85점
  gap 2           →  65점
  gap 3+ (큼)     →  40점
  회사 TRL 미설정 →  50점 (폴백)
```

---

### 🎯 theme_fit (별도 지표) — `scoring/keyword.score_theme_fit`

회사 본업·테마 직격도 종합 평가. **5축 외 별도 점수**, 단 **총점에 보너스로 가산**.

```
baseline = 25

+ 회사 보유 기술 매칭 1개당     +15  (최대 +40)
+ core_keywords 매칭 1개당      +4   (최대 +20)
+ positioning_keywords 1개당    +6   (최대 +15)
+ 보안 필터 매칭 ≥ 6개          +25
+ 보안 필터 매칭 ≥ 3개          +15
+ 본문 1500자 이상              +3
+ 발주 부서 티어 가산:
    tier1_security             +25  (보안 직격 부서)
    tier2_core                 +15  (회사 본업 핵심 부서)
    tier3_adjacent             +8   (인접 영역)
= 최종 (max 100)
```

**총점 보너스** (`engine.py`):
```
theme_fit ≥ 90  → 총점 +20
theme_fit ≥ 80  → 총점 +12
theme_fit ≥ 60  → 총점 +6
theme_fit < 30  → 총점 −10
```

---

### 📐 총점 산정 흐름 (사진 예시 검증)

사진의 카드 (키워드 100 / 예산 64 / 컨소시엄 100 / 경쟁 50 / TRL 45 / 테마 68):

```
가중합   = 100×0.35 + 64×0.10 + 100×0.20 + 50×0.20 + 45×0.15
       = 35.00 + 6.40 + 20.00 + 10.00 + 6.75
       = 78.15

theme_fit 68 → +6 보너스

총점    = 78.15 + 6 = 84.15  → 약 84점
```

---

### 🎚 등급 기준 (UI 표시)

| 등급 | 점수 | 의미 | 슬랙 알림 |
|------|------|------|----------|
| 🟠 **TOP** | 90+ | 즉시 검토, 본업 직격 | ✅ + 1억+ 시 |
| 🟢 **GOOD** | 80~89 | 검토 권장, 적합도 높음 | ✅ + 1억+ 시 |
| 🟡 **FAIR** | 60~79 | 검토 고려 | ❌ |
| ⚪ **검토** | <60 | 우선순위 낮음 | ❌ |

슬랙 알림 규칙: **총점 ≥ 80 AND budget_mw ≥ 100(1억) AND 활성 공고** (영업시간 09~18 KST 발사, 외 시간은 누적 → 다음 영업일 09시 묶음).

---

## 크롤러 현황

총 **9개 어댑터** 등록 (`mock` 제외). 현재 **DB 1,266건 수집 · 보안 통과 684건**.

| 소스 | 상태 | 데이터 경로 | 비고 |
|------|------|-------------|------|
| **iitp** | ✅ 동작 | data.go.kr OpenAPI (15074634) | 과기정통부 사업공고 — IITP 매칭만 필터 |
| **ntis** | ✅ 동작 | data.go.kr OpenAPI (15074634, IITP와 공유) | IITP 외 부처 흡수 — NIA·ETRI·KEIT·우주항공청·한국연구재단 등 |
| **kisa** | ✅ 동작 | HTML 크롤링 (`kisa.or.kr/403`, `/408`) | 입찰공고 + 위탁과제 |
| **kosa** | ✅ 동작 | HTML 크롤링 (`sw.or.kr` cbIdx=290) | robots 차단 → Googlebot UA 사용 |
| **nipa** | ✅ 동작 | HTML 크롤링 (`nipa.kr/home/2-2`, `/2-3`) | 사업공고 + 입찰공고 |
| **krit** | ✅ 동작 | HTML 크롤링 (`dtims.krit.re.kr`) | 국방 R&D, 보안 매칭률 낮음 |
| **mss** | ⚠️ 호출 한도 주의 | data.go.kr OpenAPI (15113297) | 중소벤처기업부 사업공고, 일 100회 한도 |
| **koica** | 🔴 서버 다운 | data.go.kr OpenAPI (3039908) | KOICA OpenAPI 서버 unreachable, `enabled=false` 보관 |
| **bizinfo** | ⏳ 미구현 | SPA (JavaScript 렌더링 필요) | Playwright 또는 NTIS API로 대체 검토 |

검증 스크립트: `python scripts/verify_crawlers.py` — 소스별 3건씩 받아서 핵심 필드 출력.

각 어댑터 작성 시: `src/rfp_targeter/crawlers/{name}.py` 에 `BaseCrawler` 구현 →
`crawlers/__init__.py` 의 `CRAWLERS` 레지스트리에 등록 → `settings.yaml` 에서 `enabled: true`.

---

## 📍 기관별 데이터 출처

각 기관의 **사업공고 게시판** (사람이 직접 보는 페이지) + 우리가 데이터를 가져오는 **소스 엔드포인트** 한눈에:

### 과학기술정보통신부 산하 (data.go.kr API 경유 — IITP + NTIS 어댑터)

| 기관 | 공고 게시판 (사람용) | 데이터 소스 (우리 어댑터) |
|------|---------------------|--------------------------|
| **IITP** 정보통신기획평가원 | [iitp.kr 공지사항](https://www.iitp.kr/kr/1/notice/notice/list.it) | [data.go.kr 15074634 OpenAPI](https://www.data.go.kr/data/15074634/openapi.do) |
| **NTIS** 국가과학기술지식정보서비스 | [ntis.go.kr 통합공고](https://www.ntis.go.kr/rndgate/eg/un/ra/mng.do) | 위 IITP와 동일 endpoint 공유 |
| 과기정통부 본 부처 | [msit.go.kr 사업공고](https://www.msit.go.kr/bbs/list.do?sCode=user&mPid=112&mId=113) | (NTIS 어댑터가 흡수) |

> ⚠️ **iitp.kr / ntis.go.kr 본 사이트는 `robots.txt`로 전면 크롤링 차단** — 공식 data.go.kr API 사용이 유일한 합법 경로.

### 한국인터넷진흥원 (KISA)
- 공고 게시판: [입찰공고](https://www.kisa.or.kr/403) · [위탁과제](https://www.kisa.or.kr/408)
- 데이터 소스: 동일 페이지 직접 HTML 크롤링 (robots.txt 허용)

### 한국SW산업협회 (KOSA)
- 공고 게시판: [정부지원사업](https://www.sw.or.kr/site/sw/ex/board/List.do?cbIdx=290) · [공지사항](https://www.sw.or.kr/site/sw/ex/board/List.do?cbIdx=292)
- 데이터 소스: 동일 페이지 HTML 크롤링 (robots.txt가 일반 UA 차단 → **Googlebot UA로 우회**, 정책상 허용)

### 정보통신산업진흥원 (NIPA)
- 공고 게시판: [사업공고](https://www.nipa.kr/home/2-2) · [입찰공고](https://www.nipa.kr/home/2-3)
- 데이터 소스: 동일 페이지 HTML 크롤링 (robots.txt 허용)

### 국방기술진흥연구소 (KRIT)
- 공고 게시판:
  - [KRIT 본 사이트](https://www.krit.re.kr/krit/contents.do?gotoMenuNo=02030000) (사업 소개)
  - [DTiMS 핵심기술 과제공고](https://dtims.krit.re.kr/vps/OINF_CtPrjNotiList.do) ← 실제 데이터 위치
- 데이터 소스: DTiMS HTML 크롤링

### 중소벤처기업부 (MSS)
- 공고 게시판: [mss.go.kr 사업공고](https://www.mss.go.kr/site/smba/ex/bbs/List.do?cbIdx=310) (cbIdx=310, **사업공고 — 검증 2026-05-26**)
  - ⚠️ cbIdx=86은 "보도자료" 게시판이라 R&D 사업공고 아님. 과거 README에 잘못 적혀 있어 수정함.
- 데이터 소스: [data.go.kr 15113297 OpenAPI](https://www.data.go.kr/data/15113297/openapi.do) (등록일은 mss.go.kr 사이트 직접 스크랩)

### 한국국제협력단 (KOICA)
- 공고 게시판: [nebid 원조조달 입찰공고](https://nebid.koica.go.kr/oep/bepb/beffatPblancList.do)
- 데이터 소스: [data.go.kr 3039908 OpenAPI](https://www.data.go.kr/data/3039908/openapi.do) — **현재 서버 unreachable, 대기**

### bizinfo (기업마당) — 미구현
- 공고 게시판: [bizinfo.go.kr](https://www.bizinfo.go.kr/web/index.do)
- 데이터 소스: 미정 (SPA라 정적 크롤링 불가) — Playwright 또는 NTIS API로 흡수 검토

---

### 💡 새 기관 추가하는 방법

1. data.go.kr에서 해당 기관 `사업공고` OpenAPI 검색 (가장 안정적)
2. 없으면 기관 사이트 `robots.txt` 확인 → 허용되면 HTML 크롤링
3. `src/rfp_targeter/crawlers/{name}.py` 에 `BaseCrawler` 상속해서 `list_announcements()` 구현
4. `crawlers/__init__.py` `CRAWLERS` 딕셔너리에 등록
5. `config/settings.yaml`에 `sources.{name}: enabled: true` 추가
6. `python scripts/verify_crawlers.py` 로 검증

---

## RFP 초안 → `/rfp` 슬래시 커맨드 연계

대시보드에서 "📝 초안 생성" 버튼 → `drafts/{공고ID}.md` 생성.
Claude Code 에서 :

```
/rfp drafts/iitp_MOCK-2026-001.md
```

→ `/rfp` 스킬이 브레인스토밍 단계부터 진입.

---

## 추후 작업

- [ ] **24/7 배포** (회사 사내 서버 / NAS / VPS) — 현재 PC 의존
- [ ] bizinfo SPA 대응 (Playwright) 또는 NTIS API로 대체
- [ ] MSS API 키 한도 분리 / 갱신 (현재 0건)
- [ ] KOICA OpenAPI 서버 복구 대기, 또는 nebid HTML fallback
- [ ] 첨부 PDF OCR (현재 텍스트 추출만)
- [ ] LLM 보강 점수 (Claude API로 본문 정성평가) — 옵션
- [ ] 슬랙·이메일 알림 (≥70점 신규 공고 발견 시)
- [ ] Slack/Discord 웹훅 알림 (옵션)
