"""LLM 도메인 적합성 + TRL 맥락 평가 생성 → announcement.llm_assess_json 캐시.

[2026-06-01 사용자 요청] 키워드 단순 매칭 한계 보완 — 본문을 LLM(Haiku)이 읽고
(1) 실제 TRL 단계 (2) 회사 도메인 적합성(high/medium/low/none) 판단.

- build_summaries.yml 가 audit_contents.py 다음에 호출 (CI 에 ANTHROPIC_API_KEY).
- llm_assess_json IS NULL 인 활성 보안 공고만 평가 (--force 면 전체 재생성).
- 1건 ~$0.002 (Haiku). 결과는 DB 캐시 — 1회 생성 후 재사용.

실행:
    python scripts/assess_contents.py --limit 50      # NULL 만 (기본)
    python scripts/assess_contents.py --force          # 전체 재생성
    python scripts/assess_contents.py --limit 5 --dry-run   # 저장 없이 출력만
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.db.models import get_conn  # noqa: E402
from rfp_targeter.llm_assess import assess_announcement  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("assess_contents")


def _ensure_column() -> bool:
    """llm_assess_json 컬럼 '존재 확인'만 (verify-only).

    런타임 ALTER 는 announcement ACCESS EXCLUSIVE 락이 필요 → 크롤/빌드 동시
    접근(또는 누수 idle-in-transaction) 시 statement timeout 으로 실패. 그래서
    DDL 은 init_db/수동 1회로만 하고, 여기선 확인만 한다(락 무관). 없으면 명확히 에러."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name='announcement' AND column_name='llm_assess_json'"
                )
                ok = cur.fetchone() is not None
        if not ok:
            log.error("llm_assess_json 컬럼 없음 — init_db 또는 수동 마이그레이션 필요")
        return ok
    except Exception:
        log.exception("컬럼 확인 실패")
        return False


def run(limit: int, force: bool, dry: bool) -> int:
    if not _ensure_column():
        return 1
    # [2026-06-29] NULL 뿐 아니라 'biddable 키 없는 옛 형식' 캐시도 재평가 대상에 포함.
    #   biddable/doc_type 추가 전 코드로 평가된 캐시가 남아 게이트(biddable)가 못 거르던 빈틈.
    #   force 면 전체, 아니면 (NULL 또는 biddable 미포함) 만.
    where_extra = (
        "" if force
        else "AND (llm_assess_json IS NULL OR llm_assess_json NOT LIKE '%biddable%')"
    )
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT id, title, body FROM announcement
                    WHERE is_security = TRUE AND is_dismissed = FALSE
                      -- [2026-06-29] body>200 조건 제거 — 본문 짧은 공고도 제목으로 평가해야
                      -- '우수성과 50선 모집'(시상) 같은 노이즈가 '미평가'로 게이트를 통과 안 함.
                      AND (deadline_at >= CURRENT_DATE::text
                           OR (deadline_at IS NULL AND posted_at >= (CURRENT_DATE - 60)::text))
                      {where_extra}
                    ORDER BY posted_at DESC NULLS LAST
                    LIMIT %s""",
                (limit,),
            )
            rows = cur.fetchall()

    import time as _time
    log.info("평가 대상 %d건 (limit=%d, force=%s, dry=%s)", len(rows), limit, force, dry)
    ok, none_cnt = 0, 0
    for r in rows:
        res = assess_announcement(r["title"], r["body"])
        if res is None:
            # 일시 오류(레이트리밋·간헐 JSON 잘림) 대비 1회 재시도
            _time.sleep(1.0)
            res = assess_announcement(r["title"], r["body"])
        if res is None:
            none_cnt += 1
            log.warning("  assess None(재시도 후도) — %s", (r["title"] or "")[:42])
            continue
        log.info(
            "  [적합성 %-6s · trl %s] %s",
            res["relevance"], res["trl"], (r["title"] or "")[:45],
        )
        if not dry:
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE announcement SET llm_assess_json=%s WHERE id=%s",
                            (json.dumps(res, ensure_ascii=False), r["id"]),
                        )
                ok += 1
            except Exception:
                log.exception("  저장 실패 — %s", r["id"])
        _time.sleep(0.2)  # Haiku 레이트리밋 보호 (audit_contents 와 동일)

    log.info("완료 — 저장 %d건 / assess 실패(None) %d건", ok, none_cnt)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--force", action="store_true", help="llm_assess_json 있는 row 도 재생성")
    ap.add_argument("--dry-run", action="store_true", help="DB 저장 없이 출력만")
    a = ap.parse_args()
    return run(a.limit, a.force, a.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
