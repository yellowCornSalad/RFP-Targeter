"""백그라운드 스케줄러. settings.crawl.interval_minutes 마다 파이프라인 실행."""
from __future__ import annotations

import logging
import signal
import sys
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from rfp_targeter.config import settings
from rfp_targeter.pipeline import run_once

log = logging.getLogger(__name__)


def _job() -> None:
    log.info("=== 크롤 사이클 시작 [%s] ===", datetime.now().isoformat(timespec="seconds"))
    try:
        stats = run_once()
        total_new = sum(s.new for s in stats)
        total_fil = sum(s.filtered_in for s in stats)
        log.info("=== 완료 — 신규 %d, 보안 통과 %d ===", total_new, total_fil)
    except Exception:
        log.exception("크롤 사이클 실패")


def run_forever() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    interval = settings()["crawl"]["interval_minutes"]
    sched = BlockingScheduler()
    sched.add_job(_job, IntervalTrigger(minutes=interval), id="crawl", next_run_time=datetime.now())

    def _shutdown(signum, frame):  # noqa: ARG001
        log.info("종료 신호 수신 — 스케줄러 정지")
        sched.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    log.info("스케줄러 시작 — %d분 간격, Ctrl+C 로 종료", interval)
    sched.start()


if __name__ == "__main__":
    run_forever()
