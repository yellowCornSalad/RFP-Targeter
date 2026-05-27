"""특정 공고의 competitor 점수 산정 과정 step-by-step 트레이스.

사용자 질문: NIPA '정보통신산업진흥원 통신 서비스 사업자 선정' 경쟁 50점 어떻게?
"""
import os, yaml, psycopg, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.scoring.competitor import (
    LOW_COMPETITION_KEYWORDS, HIGH_COMPETITION_KEYWORDS,
    AGENCY_BOOST, AGENCY_PENALTY, score_competitor,
)
from rfp_targeter.db.models import Announcement


def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        with open("config/secrets.yaml", encoding="utf-8") as f:
            sec = yaml.safe_load(f)
        db_url = sec["supabase"]["database_url"]
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgres://", 1)

    conn = psycopg.connect(db_url)
    with conn:
        cur = conn.cursor()
        # NIPA 통신 서비스 공고 찾기
        cur.execute("""
            SELECT id, source, external_id, title, agency, body
            FROM announcement
            WHERE source = 'nipa'
              AND title ILIKE '%통신 서비스%'
              AND is_dismissed = FALSE
            LIMIT 3
        """)
        rows = cur.fetchall()

    with open("config/profile.yaml", encoding="utf-8") as f:
        profile = yaml.safe_load(f)

    print(f"\n{'='*75}")
    print(f"competitor 점수 트레이스 — NIPA 통신 서비스 공고")
    print(f"{'='*75}\n")

    print(f"📋 사용 키워드 풀:")
    print(f"  LOW (회사 본업, +가점) {len(LOW_COMPETITION_KEYWORDS)}개")
    print(f"  HIGH (대기업 영역, -감점) {len(HIGH_COMPETITION_KEYWORDS)}개")
    print(f"  AGENCY_BOOST: {AGENCY_BOOST}")
    print(f"  AGENCY_PENALTY: {AGENCY_PENALTY}\n")

    for ann_id, source, ext_id, title, agency, body in rows:
        print(f"\n{'─'*75}")
        print(f"[{ann_id}] {title}")
        print(f"{'─'*75}")
        print(f"  source:  {source}")
        print(f"  agency:  '{agency}'")
        print(f"  body 길이: {len(body or '')} 자")

        blob = ((title or "") + " " + (body or "")).lower()

        # 1. 본업 매칭
        low_hits = [k for k in LOW_COMPETITION_KEYWORDS if k.lower() in blob]
        print(f"\n  Step 1. 회사 본업 키워드 (저경쟁 +가점, cap +35):")
        if low_hits:
            delta = min(35, len(low_hits) * 8)
            print(f"    매칭 {len(low_hits)}개: {low_hits}")
            print(f"    +{delta} (×8, cap 35)")
        else:
            print(f"    매칭 0개 → +0")

        # 2. 대기업 매칭
        high_hits = [k for k in HIGH_COMPETITION_KEYWORDS if k.lower() in blob]
        print(f"\n  Step 2. 대기업 영역 키워드 (-감점, cap -30):")
        if high_hits:
            delta = min(30, len(high_hits) * 10)
            print(f"    매칭 {len(high_hits)}개: {high_hits}")
            print(f"    -{delta} (×10, cap 30)")
        else:
            print(f"    매칭 0개 → 0")

        # 3. 발주기관
        print(f"\n  Step 3. 발주기관 가중치:")
        boost_hit = None
        for kw, b in AGENCY_BOOST.items():
            if kw in (agency or ""):
                boost_hit = (kw, b); break
        pen_hit = None
        for kw, pen in AGENCY_PENALTY.items():
            if kw in (agency or ""):
                pen_hit = (kw, pen); break
        if boost_hit:
            print(f"    BOOST 매칭: '{boost_hit[0]}' → +{boost_hit[1]}")
        if pen_hit:
            print(f"    PENALTY 매칭: '{pen_hit[0]}' → {pen_hit[1]}")
        if not boost_hit and not pen_hit:
            print(f"    매칭 없음 → 0 (agency='{agency}' 가 BOOST/PENALTY 키와 일치 X)")

        # 4. 본문 부족
        body_len = len(body or "")
        if body_len < 200:
            print(f"\n  Step 4. 본문 부족 ({body_len}자 < 200) → -5")

        # 5. 경쟁사
        rivals = [r for r in (profile.get("competitors") or []) if r.lower() in blob]
        if rivals:
            print(f"\n  Step 5. 경쟁사 본문 등장: {rivals} → -15")

        # 실제 호출
        a = Announcement(source=source, external_id=ext_id, title=title, url="", agency=agency, body=body)
        sc, why = score_competitor(a, profile)
        print(f"\n  📐 최종 점수: {sc}")
        for w in why:
            print(f"    {w}")


if __name__ == "__main__":
    main()
