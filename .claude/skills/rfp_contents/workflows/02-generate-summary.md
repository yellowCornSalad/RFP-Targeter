# Workflow 02 — LLM 요약 생성

활성 보안 공고에 `ai_summary` 채움. Claude Haiku 4.5 호출.

## 실행

### 자동 (GitHub Actions)

```yaml
# .github/workflows/build_summaries.yml
on:
  schedule:
    - cron: '7 * * * *'   # 매시 7분 (crawl 5분 후 마진)
```

매시 cron 발화 → `--limit 50` 자동 적용 → 신규 ai_summary IS NULL 50건 처리.

### 수동 (한 번에 전체 처리)

```bash
# v1.0 브랜치 워크플로우로 수동 실행 (limit 없이 전체)
gh workflow run build_summaries.yml --ref main

# 또는 로컬에서 (ANTHROPIC_API_KEY 환경변수 필요)
export ANTHROPIC_API_KEY=...
python scripts/audit_contents.py
```

### 강제 재생성

```bash
# 이미 있는 ai_summary 도 새로 생성 (system 프롬프트 변경 시)
python scripts/audit_contents.py --force

# 또는 GitHub Actions inputs.force=true 로 dispatch
```

⚠️ `--force` 는 비용 늘림. `references/cost-policy.md` 참조.

## 동작 흐름 (코드)

```python
# 1. NULL 인 활성 보안 공고 조회 (body ≥ 300자)
rows = SELECT id, title, agency, body
       FROM announcement
       WHERE is_security AND NOT is_dismissed
         AND ai_summary IS NULL
         AND LENGTH(body) >= 300
         AND 활성_조건
       LIMIT N

# 2. 각 row 마다 Claude Haiku 호출
for r in rows:
    prompt = f"제목: {r.title}\n발주: {r.agency}\n본문(첨부 포함):\n{r.body[:6000]}"
    resp = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=200,
        system=SUMMARY_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    summary = resp.content[0].text.strip()

    # 160자 하드 컷
    if len(summary) > 160:
        summary = summary[:157] + "..."

    # 3. DB UPDATE
    UPDATE announcement SET ai_summary = ? WHERE id = ?

    # 4. Rate limit 보호
    time.sleep(0.2)
```

## 환경변수

| 변수 | 출처 | 용도 |
|------|------|------|
| `ANTHROPIC_API_KEY` | GitHub Secrets / 로컬 환경 | Claude API 인증 |
| `DATABASE_URL` | GitHub Secrets | Supabase 연결 |

로컬에 ANTHROPIC_API_KEY 가 없으면 스크립트가 안전하게 skip + 경고 로그.

## 트러블슈팅

### "ANTHROPIC_API_KEY 미설정 — 요약 생성 skip"
- 로컬: `export ANTHROPIC_API_KEY=...` 또는 secrets.yaml 의 `anthropic.api_key` 추가
- GitHub Actions: Settings > Secrets > Actions 에 `ANTHROPIC_API_KEY` 등록 확인

### "anthropic SDK 미설치"
```bash
pip install anthropic
```

### Rate limit error
- Haiku 4.5 분당 50 RPM 제한
- `time.sleep(0.2)` 가드가 있어서 정상 운영 시엔 안 닿음
- 만약 닿으면 `time.sleep(0.5)` 로 늘림

### 요약 품질 떨어짐
- `references/llm-prompt.md` 의 system 프롬프트 검토
- 본문이 boilerplate 위주면 요약도 boilerplate (예: "본 공고는 ... 자격요건...")
- 보안 필터의 `_filter_boilerplate` 가 키워드만 제거하지 본문 자체 정제 X — body 가 본문 후처리 거쳤는지 확인

## 결과 확인

```sql
-- 최근 생성된 요약 샘플
SELECT id, title, ai_summary
FROM announcement
WHERE ai_summary IS NOT NULL
  AND is_security AND NOT is_dismissed
ORDER BY posted_at DESC
LIMIT 5;
```

각 요약이 150자 이내 + 사업 본질 명시인지 spot check. 1-2건 검토하면 전체 품질 추정 가능.

## 자동화 한계

- system 프롬프트가 모든 공고 유형에 최적 X — 가끔 "본 공고는..." 같은 boilerplate 출력
- 본문 자체에 사업 정보가 부족하면 LLM 도 가짜 정보 만들 위험 (현 프롬프트의 "안내문구 제외" 가드는 부분적 효과)
- 매시 50건 제한은 백로그 빠르게 해소 가능하지만 대량 백필 (1000건+) 은 24시간 걸림 — 그땐 수동 dispatch 권장
