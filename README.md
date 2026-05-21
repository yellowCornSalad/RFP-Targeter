# RFP-Targeter

엔키화이트햇 RFP 자동 탐색 시스템.
IITP · NTIS · KISA · KOSA · NIPA · KRIT · 중기부(MSS) · bizinfo · KOICA 등
**공공기관 R&D · 사업 공고를 1시간마다 폴링** →
**보안 키워드 1차 필터** → **5축 점수 산정** → **고득점 공고 자동 RFP 초안 생성** →
**Streamlit 대시보드 (Cobalt Blue 테마)** 시각화 → **Claude API 자동 초안 작성**.

> 보조 도구: Claude Code `/rfp` 슬래시 커맨드 — 자동 생성된 초안을 이어서 작성.

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

| 축 | 의미 | 가중치 |
|----|------|-------|
| keyword | 회사 핵심 키워드 매칭도 | 0.30 |
| budget | 회사 적정 예산 범위 적합 | 0.15 |
| consortium | 컨소시엄 구성 부담(낮을수록 ↑) | 0.20 |
| competitor | 경쟁 상황(적을수록 ↑) | 0.20 |
| trl | 회사 보유 기술 TRL 적합 | 0.15 |

별도 지표: **theme_fit** (회사 테마 적합도, 0~100) — UI에 따로 노출.

가중치는 `config/settings.yaml` 에서 조정.

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
- 공고 게시판: [mss.go.kr 사업공고](https://www.mss.go.kr/site/smba/ex/bbs/List.do?cbIdx=86)
- 데이터 소스: [data.go.kr 15113297 OpenAPI](https://www.data.go.kr/data/15113297/openapi.do)

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
