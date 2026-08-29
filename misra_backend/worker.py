"""Run MISRA's OCR and grading worker.

Windows uses an in-process worker with RQ's timer-based timeout because the
standard isolated Worker is a Unix process model. Linux keeps process isolation.
Run this in a separate terminal from Uvicorn.
"""

from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv
from rq import Queue, SimpleWorker, Worker
from rq.serializers import JSONSerializer
from rq.timeouts import TimerDeathPenalty

from services.job_queue_service import redis_connection
from database import SessionLocal
from services.audit_service import purge_expired_audit_logs
from services.job_recovery_service import recover_orphaned_jobs


class WindowsSimpleWorker(SimpleWorker):
    """RQ's documented Windows worker with a non-signal timeout mechanism."""

    death_penalty_class = TimerDeathPenalty


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MISRA background workers")
    parser.add_argument("--burst", action="store_true", help="Exit when queues are empty")
    parser.add_argument("--recover-only", action="store_true", help="Recover stale jobs and exit")
    args = parser.parse_args()
    load_dotenv()

    with SessionLocal() as db:
        recovery = recover_orphaned_jobs(db)
        removed_logs = purge_expired_audit_logs(db)
    print(
        "Job recovery: "
        f"checked={recovery['checked']} requeued={recovery['requeued']} "
        f"failed={recovery['failed_at_limit']} dispatch_failed={recovery['dispatch_failed']} "
        f"retained_logs_removed={removed_logs}"
    )
    if args.recover_only:
        return 0

    connection = redis_connection()
    queues = [
        Queue("ocr", connection=connection, serializer=JSONSerializer),
        Queue("grading", connection=connection, serializer=JSONSerializer),
    ]
    worker_class = WindowsSimpleWorker if os.name == "nt" else Worker
    worker = worker_class(
        queues,
        connection=connection,
        serializer=JSONSerializer,
    )
    worker.work(with_scheduler=True, burst=args.burst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
