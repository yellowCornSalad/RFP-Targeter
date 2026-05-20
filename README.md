# RFP-Targeter

엔키화이트햇 RFP 자동 탐색 시스템.
IITP·NTIS·KISA·국방기술진흥연구소·bizinfo 등 공공기관 R&D 공고를 30분마다 폴링 →
**보안 키워드 1차 필터** → **5축 점수 산정** → **고득점 공고 자동 RFP 초안 생성** →
**Streamlit 대시보드** 시각화.

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
├── config/
│   ├── settings.yaml          # 폴링 주기, 점수 가중치
│   ├── keywords.yaml          # 보안 1차 필터 키워드
│   ├── profile.example.yaml   # 회사 프로필 템플릿
│   └── profile.yaml           # (gitignore) 실제 프로필
├── data/
│   ├── rfp.db                 # SQLite (gitignore)
│   └── attachments/           # 첨부 PDF
├── templates/                 # 기관별 RFP 양식 (예: templates/IITP/...)
├── drafts/                    # 자동 생성된 초안 (gitignore)
├── src/rfp_targeter/
│   ├── config.py
│   ├── pipeline.py            # 크롤 → 필터 → 점수 → 저장 오케스트레이션
│   ├── scheduler.py           # 30분 폴링
│   ├── dashboard.py           # Streamlit UI
│   ├── crawlers/              # 사이트별 어댑터
│   ├── filters/               # 보안 키워드 필터
│   ├── scoring/               # 5축 점수 + 테마 적합도
│   ├── profile/               # 회사 프로필 추출기
│   ├── drafter/               # RFP 초안 생성기
│   └── db/                    # SQLite 스키마 + 모델
└── scripts/                   # CLI 진입점
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

| 소스 | 상태 | 비고 |
|------|------|------|
| mock | ✅ 동작 | 샘플 데이터 5건 — 파이프라인 검증용 |
| iitp | ⚠️ 키 필요 | IITP 본 사이트는 robots.txt 전면 금지 — data.go.kr "과학기술정보통신부 사업공고" API 경유. [발급 가이드](https://www.data.go.kr/data/15074634/openapi.do) → `config/secrets.yaml` |
| ntis | ⏳ 미구현 | RSS / Open API 확인 필요 |
| kisa | ⏳ 미구현 | |
| krit | ⏳ 미구현 | |
| bizinfo | ⏳ 미구현 | HTML 구조 단순 — 빠르게 추가 가능 |

각 어댑터 작성 시: `src/rfp_targeter/crawlers/{name}.py` 에 `BaseCrawler` 구현 →
`crawlers/__init__.py` 의 `CRAWLERS` 레지스트리에 등록 → `settings.yaml` 에서 `enabled: true`.

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

- [ ] 실제 사이트 어댑터 5개 완성 (IITP, NTIS, KISA, KRIT, bizinfo)
- [ ] 첨부 PDF 자동 다운로드 + 본문 OCR
- [ ] 양식 폴더 → 공유 드라이브 동기화 (rclone 또는 OneDrive Sync)
- [ ] LLM 보강 점수 (Claude API) — 옵션
- [ ] Slack/Discord 웹훅 알림 (옵션)
