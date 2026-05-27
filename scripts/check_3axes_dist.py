"""consortium / competitor / trl 점수 분포 검증.

3축 모두 휴리스틱 기반이므로 실제 분포 확인 후
README에 기준점 적기 + 필요시 공식 개선.
"""
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
        for col in ["consortium_score", "competitor_score", "trl_score"]:
            cur.execute(f"""
                SELECT s.{col}, COUNT(*) AS n
                FROM announcement a
                JOIN score s ON s.announcement_id = a.id
                WHERE a.is_security = TRUE AND a.is_dismissed = FALSE
                  AND s.{col} IS NOT NULL
                GROUP BY 1
                ORDER BY 1 DESC
            """)
            print(f"\n=== {col} 분포 (활성 보안) ===")
            rows = cur.fetchall()
            total = sum(n for _, n in rows)
            unique = len(rows)
            print(f"  unique 값: {unique}개, 총: {total}건")
            for s, n in rows:
                pct = 100*n/total
                bar = "█" * min(40, int(pct/2))
                print(f"    {s:5.1f}점: {n:4d}건 ({pct:5.1f}%) {bar}")

        # 5축 평균
        cur.execute("""
            SELECT
              AVG(s.keyword_score), AVG(s.budget_score),
              AVG(s.consortium_score), AVG(s.competitor_score),
              AVG(s.trl_score), AVG(s.total_score)
            FROM announcement a
            JOIN score s ON s.announcement_id = a.id
            WHERE a.is_security = TRUE AND a.is_dismissed = FALSE
        """)
        row = cur.fetchone()
        print("\n=== 5축 평균 (활성 보안) ===")
        print(f"  keyword:    {row[0]:5.1f}")
        print(f"  budget:     {row[1]:5.1f}")
        print(f"  consortium: {row[2]:5.1f}  ← 점검 대상")
        print(f"  competitor: {row[3]:5.1f}  ← 점검 대상")
        print(f"  trl:        {row[4]:5.1f}  ← 점검 대상")
        print(f"  total:      {row[5]:5.1f}")


if __name__ == "__main__":
    main()
