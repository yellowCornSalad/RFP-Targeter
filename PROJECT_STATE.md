# 📌 RFP-Targeter 현재 상태 스냅샷

> 새 세션 시작 시 Claude 에게 첫 메시지로 보여주면 즉시 컨텍스트 복구.
> 마지막 업데이트: 2026-05-29

---

## 🔗 핵심 URL

| 항목 | URL |
|---|---|
| GitHub repo | https://github.com/yellowCornSalad/RFP-Targeter |
| 정적 사이트 | https://yellowcornsalad.github.io/RFP-Targeter/ |
| Skills_Claude | https://github.com/yellowCornSalad/Skills_Claude |

## 🚦 자동화 인프라 (모두 클라우드, PC 무관)

| 컴포넌트 | 상태 | 주기 |
|---|---|---|
| **cron-job.org** (외부 cron) | ✅ 등록됨 (RFP-Targeter Hourly Crawl) | **1시간 (안정 확정 5/29)** |
| GitHub Actions `crawl.yml` | ✅ schedule `0 * * * *` + workflow_dispatch | 매시 정각 (cron-job 도 호출) |
| GitHub Actions `build_static.yml` | ✅ 매시 5분 (v1.0 release branch) | 매시 1회 |
| GitHub Actions `monitor_crawler.yml` | ✅ 70분 정지 임계 + 자동 dispatch | 30분 (안전망, 평일 09~21 KST) |
| Supabase PostgreSQL | ✅ 클라우드 DB | 24/7 |
| Slack webhook | ✅ rfp bot | **평일 09~21 KST** (신규 + 크롤완료 통일) |

## 🛡 3중 안전망

1. **cron-job.org** — 매시 정각 100% 호출 (외부 서버)
2. **GitHub Actions schedule** — 자체 cron (가끔 누락)
3. **monitor 자동 dispatch** — 70분 임계 시 마지막 안전망

## 📊 점수 시스템 (5축, 각 0-100)

```
총점 = keyword 0.35 + budget 0.10 + eligibility 0.20 + competitor 0.20 + trl 0.15
       + theme_fit 보너스 (-10 ~ +20)
```

| 축 | 코드 | 정량 기준 |
|---|---|---|
| keyword | `scoring/keyword.py` v2 | baseline 30 + core×25 cap50 + pos×10 cap20 + log2(N+1)×7 cap35 + 동의어 dedupe |
| budget | `scoring/budget.py` v2 | NULL=35, <1억=25~50, 1~5억=70~95, 5~40억=100, 40~100억=90~100, 100억+=80~90 |
| eligibility | `scoring/eligibility.py` v2 (이전 consortium 대체) | baseline 60, 중소+20, 정보보호전문+20, 보안인력+15, 박사후/대기업 -40~50 |
| competitor | `scoring/competitor.py` v2 | baseline 50 + 본업×8 cap35 + 대기업×−10 cap30 + 발주기관(KISA+10, NIPA+5, IITP+5, 중기부+3) |
| trl | `scoring/trl.py` v2 | gap 0=95, gap 1=85, gap 2=70, gap 3=55, gap 4+=40 + 발주기관 default (KISA/NIPA=7, IITP=5, MSS=8) |

## 🏢 회사 자산 (profile.yaml, score 산정 근거)

- **이름**: 엔키화이트햇 (ENKI WhiteHat)
- **창업**: 2016 (10년차, 중소기업)
- **인증**: KISA 2026 정보보호 신기술 사업화 선정 (50개 중 1)
- **TRL**: 8-9 (사업화/상용화 단계, 5개 기술)
- **특허**: 38건 (등록 16 + 출원 22 + 국외 3)
- **표준**: 28건 (국내 21 + 국제 7)
- **컨소시엄 파트너 5곳**: KAIST·가천대·세종대 (대학) + 쏘마·엔플러스랩 (기업)
- **ecosystem 8곳**: SGA솔루션즈/프라이빗테크/NNSP/모니터랩/지니언스/이니텍/이글루/테이텀
- **경쟁사**: SafeBreach/AttackIQ/Cymulate (BAS), 안랩/SK쉴더스/시큐아이/윈스 (국내 SI)

## 🕷 크롤러 (5개 활성)

| Source | URL | 상태 |
|---|---|---|
| KISA | kisa.or.kr/403, /408 | ✅ |
| IITP | data.go.kr/15074634 (OpenAPI) | ✅ |
| NIPA | nipa.kr/home/2-2, /2-3 | ✅ |
| MSS | data.go.kr/15113297 + mss.go.kr cbIdx=310 | ✅ |
| KRIT | pms.krit.re.kr (Nexacro SPA · Playwright) | ✅ 캐러셀 17건 → 군용 제외 → 5건 통과 |
| KOSA | sw.or.kr | ❌ 비활성 (영양가 0) |
| KOICA | apis.data.go.kr | ❌ 비활성 (API 사망) |
| NTIS | data.go.kr/15074634 | ❌ 비활성 (IITP 와 100% 중복) |
| G2B | apis.data.go.kr/1230000 | ❌ 비활성 (401 Unauthorized) |
| bizinfo | bizinfo.go.kr | ❌ 비활성 (SPA, JS 필요) |

## ⚙️ 주요 설정값 (config/settings.yaml)

```yaml
crawl:
  request_delay_seconds: 2
  timeout_seconds: 20         # hang 차단
  max_per_source: default
sources:
  iitp.max_per_source: 20
  nipa.max_per_source: 20
  krit.max_per_source: 30
  mss.max_per_source: 50
alert:
  slack_enabled: true
  dashboard_url: https://yellowcornsalad.github.io/RFP-Targeter/
  business_hours:
    start: 9
    end: 21                   # 2026-05-29: 18 → 21 확장
    weekdays_only: true       # dispatch_pending_alerts + notify_crawl_complete 둘 다 적용
                              # 2026-05-29: notify_crawl_complete 도 영업시간 가드로 통일
```

## 🐍 핵심 스크립트

| 파일 | 역할 |
|---|---|
| `scripts/run_once.py` | 1회 크롤 (GitHub Actions 가 호출) |
| `scripts/monitor_crawler.py` | 정지 감지 + 자동 dispatch (GAP 70분) |
| `scripts/build_static.py` | Supabase → site/data.json + HTML |
| `scripts/recompute_all_scores.py` | 점수 공식 수정 후 전체 재계산 |
| `scripts/backfill_budget.py` | budget_mw 재추출 백필 |
| `scripts/audit_contents.py` | LLM 150자 카드 요약 (Claude Haiku 4.5) |
| `scripts/verify_sources_audit.py` | 5개 source 출처·URL·count 검증 |
| `scripts/trace_competitor.py` | 특정 공고 competitor 점수 산정 트레이스 |
| `scripts/capture_dashboard.py` | Playwright 자동 캡쳐 → `docs/screenshots/dashboard.png` (README 미리보기) |

## 🎯 최근 주요 변경 (시간 역순)

1. **2026-05-29** — KRIT 전용 군용 제외 — 무기 고유어(탄약/지뢰/유도무기/극초음속/무기체계/부품국산화/터빈/개방형표준화·MOSS) 포함 제목을 수집 단계(`_make_announcement`)에서 탈락. [사용자 결정] "군용말고 사이버/AI/자동화는 확실히 포함". 크롤러 내부에서만 적용 → 다른 6개 소스 키워드 시스템 영향 0. 결과: 17건 → 군용 11건 제외 → 6건 수집 → 보안필터 5건 통과 (AI 3건: 인공지능 지휘통제·AI 전술통신·LLM 자율전투 AI에이전트 + 국방 R&D 공모/실증 2건)
2. **2026-05-29** — KRIT 캐러셀 5페이지 전체 순회 (**4건 → 17건**) — `_click_next` 가 실제 next 버튼을 못 찾아 1페이지(4건)에서 멈추던 문제. probe 로 버튼이 `.portal_mtab_next` 임을 확정. Nexacro 가 JS `element.click()` 무시 → `page.mouse.click(좌표)` 실제 마우스 이벤트. page indicator(cur/total)로 마지막 페이지 자동 감지
3. **2026-05-29** — README 에 대시보드 첫 페이지 스크린샷 추가 (`docs/screenshots/dashboard.png`) + `scripts/capture_dashboard.py` (Playwright 자동 캡쳐 — 비밀번호 게이트 통과 후 viewport 저장)
4. **2026-05-29** — 회사 강점 표현 톤다운 (hallucination 완화) — 단정형 → 권유형으로 변경. 제목 "💼 강조할 자산" → "💡 검토해볼 만한 방향 (자동 추천)". disclaimer 박스 추가. 각 항목 reason 권유형 ("~ 매칭" → "~ 언급 — 관련 영역이면 어필 가능해 보임" 등)
5. **2026-05-29** — 회사 강점 폴백 매핑 패턴 8개 확장 — 인증·전자서명·암호·인공지능·디지털전환·클라우드·빅데이터·신기술·실증 단독 키워드도 회사 라인업으로 매핑
6. **2026-05-29** — 회사 강점 자동 추출 폴백 로직 추가 — `matched_keywords` (보안 필터 통과 키워드) → 회사 라인업 15개 패턴 매핑 (`renderStrengths()` 9번 분기). 기존 본문 substring 매칭이 회사-specific 영문 약어와 정부 RFP 본문 사이에서 매칭률 낮은 문제 보완
7. **2026-05-29** — `build_static.yml` 에 `PROFILE_YAML_B64` 복원 단계 추가 — 정적 빌드 시 `config/profile.yaml` 부재로 `profile.example.yaml` (mojibake) 폴백되던 문제 해결. crawl.yml 의 동일 단계 미러링
8. **2026-05-29** — cron-job.org 1시간 주기 안정성 확인 → **확정** (30분 테스트 종료, 사용자 결정)
9. **2026-05-29** — 슬랙 영업시간 09~18 → **09~21 KST 통일** (신규 + 크롤완료 모두) — `notify_crawl_complete` 영업시간 가드 재도입, 모니터 헬스체크도 09~21 확장
10. **2026-05-29** — 카드 메타 행에 마감일 표시 — "마감 D-N **(YYYY.MM.DD)**" — 우측 패널과 톤 통일
11. **2026-05-28** — KISA 사업기간 추출 fallback (body 전체) — 27건 신규 추출
12. **2026-05-28** — cron-job.org 셋업 가이드 + 사용자 셋업 완료
13. **2026-05-28** — 크롤 완료 슬랙 알림 24/7 (영업시간 가드 풀음) — *5/29 영업시간 가드 재도입으로 supersede*
14. **2026-05-28** — crawl cron 30분→1시간 복귀 (사용자 결정)
15. **2026-05-27** — 예산 1억 기준 3-mode 필터 UI + KPI 동적 갱신
16. **2026-05-27** — 카드 상세 재구성: 응찰 체크리스트 + 회사 매칭 강점 (5축 점수 분해 컴팩트)
17. **2026-05-27** — consortium → eligibility_fit 교체 (변별력 확보)
18. **2026-05-27** — competitor 발주기관 가산 fix (NIPA/IITP 약자 매칭)
19. **2026-05-27** — competitor·trl v2 + README 정량 기준
20. **2026-05-27** — keyword·budget v2 + 동의어 dedupe + 100점 인플레이션 해결
21. **2026-05-27** — KOICA 카드 제거, KRIT 라벨 "필터 통과 0"
22. **2026-05-27** — crawl hang fix (timeout 20s, retry 2, max 20)

## 🔍 새 세션 시작 시 한 줄

> "RFP-Targeter 프로젝트 이어서 작업해줘. PROJECT_STATE.md 확인하고."

또는 더 구체적으로:

> "RFP-Targeter 이어서. 어제 작업한 ___ 후속으로 ___ 하려고 해."

---

## 🛡 컨텍스트 한계 대비 권장

1. **이 파일 (PROJECT_STATE.md) 을 주기적으로 업데이트** — 새 fix/변경 추가
2. **큰 task 끝나면 commit + 의미 있는 메시지** — git log 가 곧 작업 이력
3. **세션 길어지면 `/compact` 명령** — Claude 가 자동 요약 (디테일 일부 손실 가능)
4. **새 세션 시작 시 이 파일 + MEMORY.md 첨부** — 즉시 복구
5. **TaskList 사용** — 진행 중인 작업 추적 (TaskCreate/Update)
