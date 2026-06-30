"""게이트로 제외된 공고 전수 분류 — 거짓 음성(억울하게 빠진 것) 검증.

특히 의심군:
  · doc_type=rnd_project/service_bid 인데 biddable=false (응찰 가능 유형인데 제외)
  · 제목에 보안 키워드 있는데 relevance=none (보안인데 도메인 무관 판정)
"""
import json
import sys
from collections import Counter

sys.path.insert(0, "src")
from rfp_targeter.db.models import get_conn

SEC_KW = ["보안", "정보보호", "취약점", "침투", "해킹", "사이버", "암호", "인증",
          "관제", "위협", "악성", "ISMS", "보안관제", "개인정보", "디지털 신원"]

with get_conn() as conn:
    cur = conn.cursor()
    # 노출 대상이지만 게이트(relevance=none OR biddable=false)로 제외된 것
    cur.execute(
        """SELECT title, llm_assess_json FROM announcement
           WHERE is_security=TRUE AND is_dismissed=FALSE
             AND (deadline_at >= CURRENT_DATE::text
                  OR (deadline_at IS NULL AND posted_at >= (CURRENT_DATE - 60)::text))
             AND llm_assess_json IS NOT NULL
             AND llm_assess_json LIKE '%%biddable%%'
           ORDER BY posted_at DESC"""
    )
    rows = cur.fetchall()

excluded = []
for r in rows:
    j = json.loads(r["llm_assess_json"])
    rel = j.get("relevance")
    bd = j.get("biddable")
    if rel == "none" or bd is False:
        excluded.append((r["title"] or "", j.get("doc_type"), rel, bd,
                         (j.get("biddable_reason") or "")[:60]))

print(f"게이트 제외 공고: {len(excluded)}건\n")
dt = Counter(e[1] for e in excluded)
print(f"doc_type 분포: {dict(dt)}\n")

# 의심군 1: rnd_project / service_bid 인데 제외 (응찰 가능 유형)
print("=== 의심군 ① R&D·용역 유형인데 제외 (억울할 수 있음) ===")
susp = [e for e in excluded if e[1] in ("rnd_project", "service_bid")]
for title, d, rel, bd, why in susp:
    print(f"  [{d} rel={rel} bid={bd}] {title[:44]}")
    print(f"       └ {why}")

# 의심군 2: 제목에 보안 키워드 있는데 제외
print(f"\n=== 의심군 ② 제목에 보안 키워드 있는데 제외 ===")
for title, d, rel, bd, why in excluded:
    if any(k in title for k in SEC_KW):
        print(f"  [{d} rel={rel} bid={bd}] {title[:44]}")
        print(f"       └ {why}")

# 나머지(명백 노이즈)는 요약만
print(f"\n=== 나머지 제외 (award/hr/event/notice — 명백 노이즈) ===")
clear = [e for e in excluded if e[1] in ("award", "hr", "event", "notice", "other", None)]
print(f"  {len(clear)}건 (시상/인력/행사/공지)")
for title, d, rel, bd, why in clear[:12]:
    print(f"  [{d}] {title[:48]}")
