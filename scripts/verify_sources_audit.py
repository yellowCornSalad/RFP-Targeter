"""기관별 크롤링 출처 감사 — 각 source 가 정말 사업공고 가져오는지.

검증:
1. 기관별 활성 보안 공고 수
2. URL 패턴 — 사업공고/입찰공고 게시판 맞는지 (도메인+경로)
3. 최근 수집 공고 5건 샘플 (제목 + URL)
4. 크롤 사이클 안정성 (마지막 12h)
5. 기관별 최근 수집 시각

기존 verify_sources.py 는 '7개 source 누락 검증' 용이라 별도 파일.
"""
from __future__ import annotations
import os, yaml, psycopg
from datetime import datetime, timezone


EXPECTED_DOMAINS = {
    "kisa": ["kisa.or.kr"],
    "iitp": ["data.go.kr", "iitp.kr"],
    "mss":  ["mss.go.kr", "data.go.kr"],
    "nipa": ["nipa.kr"],
    "krit": ["krit.re.kr"],
}
EXPECTED_PATHS = {
    "kisa": ["/403", "/408"],
    "nipa": ["/home/2-2", "/home/2-3"],
    "mss":  ["cbIdx=310", "smba/ex/bbs", "mssBizService"],
    "krit": ["OINF_CtPrjNotiList", "vps"],
    "iitp": ["businessAnnouncMentList", "msitannouncementinfo"],
}


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

        # 1. 기관별 활성 공고 수
        cur.execute("""
            SELECT source, COUNT(*) AS n
            FROM announcement
            WHERE is_security = TRUE AND is_dismissed = FALSE
            GROUP BY source ORDER BY n DESC
        """)
        print("=" * 70)
        print("📊 기관별 활성 보안 공고 수")
        print("=" * 70)
        for src, n in cur.fetchall():
            print(f"  {src:8s}: {n:4d} 건")

        # 2. URL 패턴 검증
        print("\n" + "=" * 70)
        print("🔍 URL 패턴 검증 (사업공고/입찰공고 게시판 맞는지)")
        print("=" * 70)
        for source, expected_paths in EXPECTED_PATHS.items():
            cur.execute("""
                SELECT url FROM announcement
                WHERE source = %s AND is_security = TRUE AND is_dismissed = FALSE
                  AND url IS NOT NULL
                LIMIT 50
            """, (source,))
            urls = [r[0] for r in cur.fetchall() if r[0]]
            if not urls:
                print(f"\n  ⚠️ {source}: 활성 공고 0건 (스킵)")
                continue
            domains = EXPECTED_DOMAINS.get(source, [])
            domain_ok = sum(1 for u in urls if any(d in u for d in domains))
            path_ok = sum(1 for u in urls if any(p in u for p in expected_paths))
            domain_pct = 100 * domain_ok / len(urls)
            path_pct = 100 * path_ok / len(urls)
            domain_emoji = "✅" if domain_pct >= 95 else "⚠️"
            path_emoji = "✅" if path_pct >= 95 else "⚠️"
            print(f"\n  [{source.upper()}] ({len(urls)}건 샘플)")
            print(f"    {domain_emoji} 도메인: {domain_ok}/{len(urls)} ({domain_pct:.0f}%) — 예상 {', '.join(domains)}")
            print(f"    {path_emoji} 경로:  {path_ok}/{len(urls)} ({path_pct:.0f}%) — 예상 {', '.join(expected_paths)}")
            print(f"    샘플 URL: {urls[0][:95]}")

        # 3. 기관별 최근 5건
        print("\n" + "=" * 70)
        print("📰 기관별 최근 수집 공고 (각 5건)")
        print("=" * 70)
        for source in EXPECTED_DOMAINS.keys():
            cur.execute("""
                SELECT title, posted_at, url
                FROM announcement
                WHERE source = %s AND is_security = TRUE AND is_dismissed = FALSE
                ORDER BY posted_at DESC NULLS LAST
                LIMIT 5
            """, (source,))
            rows = cur.fetchall()
            if not rows:
                continue
            print(f"\n  [{source.upper()}]")
            for title, posted, url in rows:
                title_s = (title or "")[:65]
                print(f"    {posted or '?':<10} | {title_s}")

        # 4. 크롤 사이클
        print("\n" + "=" * 70)
        print("⏰ 크롤 사이클 안정성")
        print("=" * 70)
        cur.execute("""
            SELECT MAX(finished_at), COUNT(*)
            FROM fetch_log
            WHERE finished_at >= NOW() - INTERVAL '12 hours'
        """)
        last, n = cur.fetchone()
        print(f"  마지막 12h 정상 사이클: {n}회")
        if last:
            now_utc = datetime.now(timezone.utc)
            gap_min = (now_utc - last).total_seconds() / 60
            status = "✅ 정상" if gap_min < 35 else "⚠️ 35분 초과"
            print(f"  마지막 완료: {gap_min:.0f}분 전  {status}")


if __name__ == "__main__":
    main()
