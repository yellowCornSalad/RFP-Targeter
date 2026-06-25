"""소스 어댑터를 라이브 실행해서 게시일(posted_at)을 직접 확인.

DB를 거치지 않고 실제 정부 사이트/API를 지금 조회 → 어댑터가 파싱한 posted_at 출력.
오늘(KST) 게시된 공고가 정말 없는지, posted_at 파싱이 정확한지 교차검증용.

사용: python scripts/live_posted.py <source>   (iitp/kisa/nipa/mss/iris)
"""
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, "src")

from rfp_targeter.config import settings
from rfp_targeter.crawlers import CRAWLERS

src = sys.argv[1]
today_kst = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")

scfg = (settings().get("sources") or {}).get(src, {})
crawler = CRAWLERS[src](base_url=scfg.get("base_url"))

items = list(crawler.list_announcements())
items.sort(key=lambda a: (a.posted_at or ""), reverse=True)

today_items = [a for a in items if (a.posted_at or "").startswith(today_kst)]

print(f"=== {src.upper()} 라이브 ===")
print(f"오늘(KST)={today_kst}")
print(f"수집 {len(items)}건 / 오늘 게시 {len(today_items)}건")
print()
print("최신 12건 (posted_at desc):")
for a in items[:12]:
    mark = " <<< 오늘" if (a.posted_at or "").startswith(today_kst) else ""
    print(f"  {a.posted_at or '(none)'} | {a.external_id} | {(a.title or '')[:52]}{mark}")

# posted_at None 개수 (파싱 누락 신호)
none_cnt = sum(1 for a in items if not a.posted_at)
print()
print(f"posted_at 누락(None): {none_cnt}건")
