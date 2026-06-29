"""활성 공고 전수 — 응찰 불가 공지/안내성 노이즈 후보 스캔.

키워드만 통과하고 실제론 R&D 과제가 아닌 공고를 잡는다:
  · 사기/사칭/피해 주의 공지
  · 결과 발표·선정 결과 (이미 끝난 공고)
  · 휴무·정정·취소 안내
LLM relevance(있으면)도 같이 표시.
"""
import re
import sys

sys.path.insert(0, "src")
from rfp_targeter.config import keywords
from rfp_targeter.db.models import get_conn
from rfp_targeter.filters.security_filter import SecurityFilter

# 공지/안내성 신호 (제목 기준)
NOTICE_PATTERNS = [
    "사칭", "사기피해", "사기 예방", "예방 수칙", "피해 주의", "보이스피싱", "스미싱",
    "주의 안내", "유의 안내", "휴무", "공지사항", "정정 공고", "정정공고",
    "선정 결과", "선정결과", "결과 발표", "결과발표", "최종 선정", "합격자",
    "당첨자", "변경 안내", "연기 안내", "취소 안내",
]

sf = SecurityFilter()  # 새 exclude_strict 반영된 필터

with get_conn() as conn:
    cur = conn.cursor()
    cur.execute(
        """SELECT id, source, posted_at, title, body
           FROM announcement
           WHERE is_dismissed=FALSE AND is_security=TRUE
           ORDER BY posted_at DESC"""
    )
    rows = cur.fetchall()

print(f"활성 공고 {len(rows)}건 스캔\n")

# 1. 제목 공지 패턴 매칭
notice_hits = []
for r in rows:
    title = r["title"] or ""
    hits = [p for p in NOTICE_PATTERNS if p.replace(" ", "") in title.replace(" ", "")]
    if hits:
        notice_hits.append((r, hits))

print(f"=== 공지/안내성 제목 패턴 매칭: {len(notice_hits)}건 ===")
for r, hits in notice_hits:
    print(f"  [{r['source']}] {r['posted_at']} {r['title'][:50]}")
    print(f"      신호: {hits}")

# 2. 새 exclude_strict 가 이제 잡는 공고 (재크롤 시 탈락 예정)
print(f"\n=== 새 exclude_strict 로 탈락 예정 ===")
killed = 0
for r in rows:
    res = sf.check(r["title"], "", r["body"] or "")
    if not res.passed and res.excluded_by:
        print(f"  [{r['source']}] {r['posted_at']} {r['title'][:48]} | by={res.excluded_by}")
        killed += 1
print(f"  → {killed}건")
