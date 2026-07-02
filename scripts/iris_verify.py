"""IRIS 어댑터 자기검증 — DB 안 건드림, 메모리에서만.

검증 항목:
  1. 상세 페이지 fetch_detail — 본문/첨부/예산 추출
  2. 30건 풀 list — 모든 필드 결측치 없는지
  3. 보안 키워드 필터 — 회사 본업 매칭 비율
  4. IITP 와 중복 의심 — 같은 ancmTl 또는 ancmNo 비교
"""
from __future__ import annotations
import sys, logging, os, yaml, psycopg
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.crawlers.iris import IRISCrawler
from rfp_targeter.filters.security_filter import SecurityFilter
_sec = SecurityFilter()

logging.basicConfig(level=logging.WARNING)


def _get_db_url():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        with open("config/secrets.yaml", encoding="utf-8") as f:
            sec = yaml.safe_load(f)
        db_url = sec["supabase"]["database_url"]
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgres://", 1)
    return db_url


def main():
    c = IRISCrawler(base_url="https://www.iris.go.kr")
    c.max_per_source = 30
    print("=" * 75)
    print("IRIS 어댑터 자기검증 (30건 list + 1건 detail + 필터 시뮬 + 중복 의심)")
    print("=" * 75)

    # ── 단계 1: 30건 list ──
    print("\n[1/4] 30건 list 단계 — 결측치 검사")
    items = list(c.list_announcements())
    print(f"  수집: {len(items)}건")
    null_counts = Counter()
    for a in items:
        if not a.title: null_counts["title"] += 1
        if not a.external_id: null_counts["external_id"] += 1
        if not a.agency: null_counts["agency"] += 1
        if not a.posted_at: null_counts["posted_at"] += 1
        if not a.deadline_at: null_counts["deadline_at"] += 1
        if not a.url: null_counts["url"] += 1
    if null_counts:
        print(f"  ⚠ 결측치: {dict(null_counts)}")
    else:
        print(f"  ✅ 모든 핵심 필드 100% 채워짐")

    # 부처 분포
    govds = Counter()
    for a in items:
        g = (a.agency or "").split(" > ")[0]
        govds[g] += 1
    print(f"  📊 부처 분포 (top 6):")
    for g, n in govds.most_common(6):
        print(f"      {n:3d}건  {g}")

    # ── 단계 2: 보안 키워드 필터 통과율 ──
    print("\n[2/4] 보안 키워드 필터 시뮬 (회사 본업 매칭)")
    passed = []
    for a in items:
        res = _sec.check(a.title, a.summary or "", a.body or "", agency=a.agency)
        if res.passed:
            passed.append((a, res.matched))
    print(f"  통과: {len(passed)}/{len(items)}건 ({100*len(passed)/max(1,len(items)):.0f}%)")
    for a, kws in passed[:5]:
        print(f"    ✓ {a.title[:60]}")
        print(f"       매칭: {', '.join(kws[:5])}")

    # ── 단계 3: 1건 fetch_detail 검증 ──
    if items:
        target = items[0]
        print(f"\n[3/4] fetch_detail 1건 검증")
        print(f"  대상: {target.title[:60]}")
        try:
            target = c.fetch_detail(target)
            print(f"  ✅ fetch_detail 성공")
            print(f"     body 길이:     {len(target.body or '')} 자")
            print(f"     첨부:          {len(target.attachments or [])} 개")
            print(f"     budget_mw:     {target.budget_mw}")
            print(f"     duration_mo:   {target.duration_months}")
            print(f"     deadline_at:   {target.deadline_at}")
            if target.attachments:
                print(f"     첨부 샘플:")
                for at in (target.attachments or [])[:3]:
                    print(f"       · {at.get('name','?')[:50]} ({at.get('category')})")
            if target.body:
                print(f"     본문 head 200자:")
                print(f"       {target.body[:200]}")
        except Exception as e:
            print(f"  ❌ fetch_detail 실패: {e}")

    # ── 단계 4: IITP 와 중복 의심 ──
    print("\n[4/4] IITP DB 와 중복 의심 (제목 기준)")
    try:
        conn = psycopg.connect(_get_db_url())
        with conn:
            cur = conn.cursor()
            iris_titles = [a.title for a in items]
            # 제목 prefix 30자 기준으로 IITP 에서 검색
            dup_count = 0
            dup_samples = []
            for t in iris_titles[:30]:
                prefix = t[:30]
                cur.execute("""
                    SELECT title FROM announcement
                    WHERE source = 'iitp' AND is_dismissed = FALSE
                      AND title LIKE %s
                    LIMIT 1
                """, (prefix + "%",))
                row = cur.fetchone()
                if row:
                    dup_count += 1
                    if len(dup_samples) < 3:
                        dup_samples.append((t[:50], row[0][:50]))
        print(f"  IITP 중복 의심: {dup_count}/{len(iris_titles[:30])}건")
        if dup_samples:
            print(f"  샘플:")
            for iris_t, iitp_t in dup_samples:
                print(f"    IRIS:  {iris_t}")
                print(f"    IITP:  {iitp_t}\n")
    except Exception as e:
        print(f"  ⚠ DB 조회 실패 (스킵): {e}")

    print("\n" + "=" * 75)
    print("자기검증 완료")
    print("=" * 75)


if __name__ == "__main__":
    main()
