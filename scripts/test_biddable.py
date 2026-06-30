"""biddable/doc_type 판정 테스트 — 노이즈 + 정상 공고 샘플."""
import sys

sys.path.insert(0, "src")
from rfp_targeter.db.models import get_conn
from rfp_targeter.llm_assess import assess_announcement

# 노이즈(award/hr/service)와 정상(rnd) 섞은 샘플 제목 패턴
SAMPLES = [
    "%유공 표창%", "%사이버전문사관%후보생%", "%실태조사 용역%",
    "%정책연구용역%", "%침투%", "%취약점%", "%AI 지역확산%성과분석%",
]

with get_conn() as conn:
    cur = conn.cursor()
    seen = set()
    for pat in SAMPLES:
        cur.execute(
            "SELECT id, title, body FROM announcement "
            "WHERE title LIKE %s AND body IS NOT NULL AND length(body) > 200 "
            "AND is_dismissed=FALSE ORDER BY posted_at DESC LIMIT 1",
            (pat,),
        )
        r = cur.fetchone()
        if not r or r["id"] in seen:
            continue
        seen.add(r["id"])
        res = assess_announcement(r["title"], r["body"])
        if res is None:
            print(f"[None] {(r['title'] or '')[:45]}  (API키 없거나 평가실패)")
            continue
        bd = res.get("biddable")
        flag = "응찰가능" if bd is True else ("응찰불가" if bd is False else "미판정")
        print(f"[{res.get('doc_type'):11s} | {flag} | rel={res.get('relevance')}] {(r['title'] or '')[:42]}")
        print(f"     사유: {res.get('biddable_reason')}")
