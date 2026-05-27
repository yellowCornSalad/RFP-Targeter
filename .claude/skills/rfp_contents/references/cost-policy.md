# LLM 비용 가드 정책

Claude Haiku 4.5 호출이 늘어나면 월 비용 증가. 다음 가드로 비용 안정 유지.

## 가드 1: NULL 만 처리 (idempotent)

```sql
SELECT ... FROM announcement
WHERE ai_summary IS NULL    -- 이미 있는 row 는 호출 X
  AND is_security AND NOT is_dismissed
  AND ...
```

한 번 생성된 요약은 재호출 안 함. 본문이 변경되어도 마찬가지 (수동 `--force` 옵션 필요).

## 가드 2: 활성 보안 공고만

```sql
AND source IN ('iitp','kisa','kosa','krit','nipa','mss','koica')
AND (deadline_at >= CURRENT_DATE::text
     OR (deadline_at IS NULL AND posted_at >= (CURRENT_DATE - 60)::text))
```

만료·비활성 공고는 사이트·슬랙 노출 X → 요약도 불필요. 비용 절감.

## 가드 3: 본문 ≥ 300자

```sql
AND LENGTH(COALESCE(body, '')) >= 300
```

본문이 너무 짧으면 요약 의미 X — 카드 제목으로 충분. LLM 호출 안 함.

## 가드 4: 매시 50건 제한 (자동 cron)

`.github/workflows/build_summaries.yml` 의 schedule cron 은 `--limit 50` 자동 적용.

```yaml
if [ "${{ github.event_name }}" = "schedule" ]; then
  ARGS="--limit 50"
fi
```

매시 최대 50건만 처리 → 일 최대 1200건. 신규 보안 공고는 보통 10건 이하/시 라서 50건이면 백로그도 매시 빠르게 해소.

## 가드 5: --force 옵션 인증

`audit_contents.py --force` 는 ai_summary 있는 row 도 재생성. 활성 321건 × $0.0003 = 약 $0.1. 사용자가 명시적으로 실행해야만 발동.

스크립트 안에 자동 `--force` 없음 — 안전.

## 비용 추정 (월간)

### 정상 운영 (스케줄만)

- 매시 신규 보안 공고: 평균 5건 / 시
- ai_summary 생성: 매시 ~5건 (50건 제한 안에 들어옴)
- 일: ~120건 × $0.0003 = $0.036
- **월: 약 $1.08 (약 1,400원)**

### 백필 1회 (대규모 누락)

- 활성 보안 321건 한 번에: $0.1 (130원)
- 사용자 명시 --force 일 때만

### 대규모 회귀 (모든 row body 변경 등)

- 활성 1000건 × $0.0003 = $0.3 (400원)
- 분기에 1번 정도 발생할까 말까

**연간 총 비용**: 약 15,000~20,000원 추정. 단일 카드 가치 (사용자 검토 시간 절감) 대비 매우 저렴.

## 비용 모니터링

Anthropic Console (https://console.anthropic.com) 에서:
1. Usage > 일별 비용 그래프
2. 갑자기 jump 하면 monitor — `--force` 실수 또는 코드 무한 루프

## 임계 초과 시 옵션

월 5,000원 초과하면:

1. 매시 cron 빈도 줄임 (`*/2` 매 2시간 또는 `0 9,15 * * *` 하루 2번)
2. `--limit 30` 으로 더 엄격
3. body 길이 임계 300 → 500 자 (짧은 공고 더 많이 제외)

현재 5,000원 미만이라 가드 변경 불필요.
