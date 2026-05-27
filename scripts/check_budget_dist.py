"""사이트 data.json + DB 의 budget_score / budget_mw 분포 검증."""
import os, yaml, psycopg
from collections import Counter

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

        # ── 1. budget_mw 분포 (활성 보안) ──
        cur.execute("""
            SELECT
              CASE
                WHEN a.budget_mw IS NULL THEN '0_NULL'
                WHEN a.budget_mw < 200 THEN '1_<200(2억미만)'
                WHEN a.budget_mw < 500 THEN '2_200~499(2~5억)'
                WHEN a.budget_mw <= 4000 THEN '3_500~4000(5~40억 SWEET)'
                WHEN a.budget_mw <= 10000 THEN '4_4001~10000(40~100억)'
                ELSE '5_>10000(100억+)'
              END AS bucket,
              COUNT(*) AS n
            FROM announcement a
            WHERE a.is_security = TRUE AND a.is_dismissed = FALSE
            GROUP BY 1 ORDER BY 1
        """)
        print("=== budget_mw 분포 (활성 보안) ===")
        total = 0
        for b, n in cur.fetchall():
            print(f"  {b:35s}: {n:4d}건")
            total += n
        print(f"  {'합계':35s}: {total}건")

        # ── 2. budget_score 분포 ──
        cur.execute("""
            SELECT s.budget_score, COUNT(*) AS n
            FROM announcement a
            JOIN score s ON s.announcement_id = a.id
            WHERE a.is_security = TRUE AND a.is_dismissed = FALSE
              AND s.budget_score IS NOT NULL
            GROUP BY 1 ORDER BY 1 DESC
        """)
        print("\n=== budget_score 분포 ===")
        for s, n in cur.fetchall():
            print(f"  {s:5.1f}점: {n:4d}건")

        # ── 3. budget_mw 가 있는 공고 샘플 ──
        cur.execute("""
            SELECT a.title, a.agency, a.budget_mw, a.budget_period, s.budget_score
            FROM announcement a
            JOIN score s ON s.announcement_id = a.id
            WHERE a.is_security = TRUE AND a.is_dismissed = FALSE
              AND a.budget_mw IS NOT NULL
            ORDER BY a.budget_mw DESC
            LIMIT 10
        """)
        print("\n=== 예산 큰 공고 top 10 ===")
        for title, agency, mw, period, bs in cur.fetchall():
            wonk = mw / 100  # 백만원 → 억
            print(f"  {wonk:6.1f}억 ({mw:6d}백만원) | bs={bs:5.1f} | {period or '-':<8} | [{agency}] {title[:50]}")


if __name__ == "__main__":
    main()
