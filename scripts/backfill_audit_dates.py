"""날짜 전수 감사(2026-06-25) 불일치 8건 교정.

각 공고의 원본 상세 페이지를 직접 fetch해 확인한 실제 게시일로 posted_at 을 교정.
근거: docs/audit / data/raw/audit/*_result.json (워크플로우 audit-all-dates).

사용: python scripts/backfill_audit_dates.py [--apply]
"""
import sys

sys.path.insert(0, "src")

from rfp_targeter.db.models import get_conn

# (id, 정답 posted_at, 근거)
CORRECTIONS = [
    # NIPA — 사업공고(board 2-2) 신청시작일 오집 / 연도 오염 잔여분
    ("nipa:nipa-122-16814", "2026-06-15", "NIPA 작성일 (신청시작 06-16 오집, -1)"),
    ("nipa:nipa-122-16115", "2025-05-19", "NIPA 2025 오픈소스대회 작성일 (392일 미래 오염)"),
    ("nipa:nipa-122-16596", "2026-03-23", "NIPA 작성일 (신청시작 03-24 오집, -1)"),
    ("nipa:nipa-122-16675", "2026-04-06", "NIPA 작성일 (신청시작 03-10 오집, +27)"),
    # MSS — reg_dt 부재로 applicationStartDate 근사 → 본문 등록일로 교정
    ("mss:1068800", "2026-06-05", "MSS 등록일 (신청시작일 근사 +17)"),
    ("mss:1068626", "2026-05-28", "MSS 등록일 (+14)"),
    ("mss:1068619", "2026-05-27", "MSS 등록일 (+13)"),
    ("mss:1068590", "2026-05-26", "MSS 등록일 (+1)"),
]

APPLY = "--apply" in sys.argv

with get_conn() as conn:
    cur = conn.cursor()
    fixed = 0
    for cid, correct, note in CORRECTIONS:
        cur.execute("SELECT posted_at, title FROM announcement WHERE id=%s", (cid,))
        row = cur.fetchone()
        if not row:
            print(f"  SKIP (DB 없음): {cid}")
            continue
        old = row["posted_at"]
        title = (row["title"] or "")[:38]
        if old == correct:
            print(f"  이미 정확: {cid} = {correct}")
            continue
        print(f"  {cid}: {old} -> {correct} | {note} | {title}")
        if APPLY:
            cur.execute("UPDATE announcement SET posted_at=%s WHERE id=%s", (correct, cid))
            fixed += 1
    if APPLY:
        conn.commit()
        print(f"\n APPLIED {fixed}건")
    else:
        print("\n DRY-RUN — --apply 로 실제 교정")
