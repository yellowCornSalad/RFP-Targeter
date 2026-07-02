"""IRIS 화이트리스트 A옵션 — 어떤 키워드가 어디서 매칭됐는지 디버그."""
import logging
import sys

sys.path.insert(0, "src")
logging.basicConfig(level=logging.WARNING, format="%(message)s")

from rfp_targeter.crawlers.iris import (
    IRISCrawler, _matches_whitelist, IRIS_KEYWORD_WHITELIST, IRIS_BODY_WHITELIST,
)


def matched_kws(*texts, source=IRIS_KEYWORD_WHITELIST):
    hay = " ".join(t for t in texts if t).lower()
    return [kw for kw in source if kw.lower() in hay]


class CFG:
    base_url = "https://www.iris.go.kr"
    max_per_source = 60
    timeout = 30


c = IRISCrawler(CFG())

primary, recovered = [], []

for a in c.list_announcements():
    meta_kws = matched_kws(a.title, a.summary, a.agency)
    if meta_kws:
        primary.append((a.title, a.agency, meta_kws))
    else:
        # 본문매칭으로 회수 — IRIS_BODY_WHITELIST 만 사용
        body_kws = matched_kws(a.body, source=IRIS_BODY_WHITELIST)
        recovered.append((a.title, a.agency, body_kws))

print(f"\n=== A옵션 디버그 (총 {len(primary)+len(recovered)}건) ===")
print(f"1차 메타 통과: {len(primary)}건")
print(f"본문매칭 회수: {len(recovered)}건")

print("\n--- 1차 메타 통과 (어떤 키워드?) ---")
for title, agency, kws in primary:
    print(f"  + {title[:55]}")
    print(f"    매칭: {kws}")

print("\n--- 본문매칭 회수 (어떤 키워드?) ---")
for title, agency, kws in recovered[:10]:
    print(f"  ~ {title[:55]}")
    print(f"    매칭: {kws[:6]}")
