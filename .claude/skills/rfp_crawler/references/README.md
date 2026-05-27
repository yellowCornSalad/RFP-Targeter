# rfp_crawler/references

크롤러 헬스 모니터링의 임계값·메시지 템플릿·알려진 회귀 패턴.

- 임계값 정책: `health-thresholds.md`
- 슬랙 메시지 포맷: `slack-message-format.md`
- 알려진 회귀 패턴: `known-regressions.md`

`SKILL.md` 의 점검 6단계를 실행할 때 위 문서를 참고한다. 임계값을 바꿔야 하면 `health-thresholds.md` 를 먼저 수정하고 `scripts/monitor_crawler.py` 의 상수를 일치시킨다.
