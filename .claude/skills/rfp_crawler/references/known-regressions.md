# 알려진 회귀 패턴

RFP-Targeter 운영 중 반복적으로 발생하는 크롤러 이슈와 대응 방법.
새 회귀가 발견되면 여기에 추가해서 다음 발생 시 즉시 진단 가능하게.

## IITP timeout 재발

**증상**: `crawl.yml` cron 이 30분 내 못 끝나서 cancelled. KISA·KOSA·NIPA·MSS 등 IITP 다음 어댑터들 도달 못 함.

**근본 원인**: IITP 어댑터의 `fetch_detail()` 가 첨부 hwpx/pdf 다운로드 + 텍스트 추출에서 정부 사이트 응답 지연. `max_per_source: 500` 일 때 평균 3초/건 × 500 = 25분.

**fix 이력**:
- 2026-05-26: `max_per_source 500 → 50` 으로 축소
- 효과: 평균 11.6초/사이클 (로컬 측정)
- 잔여 위험: GitHub Actions 환경에서 정부 사이트 응답 시간 변동으로 가끔 30분 임계 근접

**진단 SQL**:
```sql
SELECT source, COUNT(*) FILTER (WHERE finished_at IS NULL) AS unfinished
FROM fetch_log
WHERE started_at > NOW() - INTERVAL '6 hours'
GROUP BY source
ORDER BY unfinished DESC;
```

**추가 조치 옵션**:
1. `max_per_source` 50 → 30 추가 축소
2. IITP fetch_detail 분리 — 신규만 detail 가져오고 update 는 list 만
3. 첨부 다운로드 timeout 30 → 15 축소

## KISA/NIPA 첨부 본문 통합 누락

**증상**: 카드의 `matched_keywords` 가 빈약. KISA 평균 11.6개 / NIPA 평균 6.5개 (IITP·MSS 는 17~28개).

**근본 원인**: KISA/NIPA 어댑터의 `fetch_detail()` 가 사이트 HTML 본문만 추출하고 첨부 텍스트 추출 단계 누락. IITP/MSS 는 자체 로직으로 추출 중.

**fix 이력**:
- 2026-05-26: `base.enrich_body_with_attachments()` 공통 헬퍼 추가
- KISA fetch_detail / NIPA fetch_detail 끝에 헬퍼 호출
- 효과: NIPA 통합률 0% → 94.8%, 평균 매칭 6.5 → 14.2

**진단 SQL**:
```sql
SELECT source, COUNT(*) AS total,
       COUNT(*) FILTER (WHERE body LIKE '%[첨부 본문]%') AS with_attachments
FROM announcement
WHERE is_security AND NOT is_dismissed
GROUP BY source;
```

KISA/NIPA 통합률 < 60% 면 회귀 — `base.enrich_body_with_attachments()` 호출 누락 또는 PDF 추출 실패 다수.

## NIPA decompose 순서 버그

**증상**: NIPA 본문이 빈 채로 들어옴 (740자 미만), 매칭 키워드도 적음.

**근본 원인**: NIPA 페이지가 본문 `div.tbCont` 를 `<header><nav>` 안에 둠 (잘못된 시멘틱 HTML). 기존 코드가 decompose 먼저 호출 → 본문 통째로 삭제.

**fix 이력**:
- 2026-05-22: `nipa.fetch_detail()` 가 main 영역 추출을 decompose 보다 먼저 수행
- 잔여 위험: NIPA 사이트 구조 변경 시 재발

## KOICA OpenAPI 죽음

**증상**: `koica` source 데이터 0건. fetch_log 에 finished_at 정상이지만 new=0 upd=0.

**근본 원인**: 2026-05 이후 `data.go.kr/3039908` 및 `openapi.koica.go.kr` 모두 unreachable.

**현재 조치**: `settings.yaml` `sources.koica.enabled: false`. 모니터에서 의도된 무시.

**대안**:
1. `nebid.koica.go.kr` 직접 HTML 크롤러 작성
2. G2B (나라장터) 우회 — 단 활용신청 필요 (현재 401)

## G2B 401 Unauthorized

**증상**: G2B 어댑터 4개 endpoint 모두 401.

**근본 원인**: 기존 `data_go_kr.service_key` 가 G2B(1230000) 활용신청 미승인.

**조치 대기**: data.go.kr 에서 G2B BidPublicInfoService 활용신청 → 승인 후 `secrets.yaml` 의 `g2b.service_key` 추가 + `enabled: true`.

## 모니터 자체 회귀

이 스킬·워크플로우 자체에 회귀가 생기면:

1. `scripts/monitor_crawler.py --silent` 로컬 실행 결과 확인
2. GitHub Actions Run 페이지에서 monitor_crawler.yml 최근 실행 로그
3. exit code 1 인데 슬랙 알림 안 옴 → `SLACK_WEBHOOK_URL` secret 만료 확인
