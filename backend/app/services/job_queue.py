"""Persistent background-job enqueueing and deduplication."""
import json
import logging
from datetime import datetime

from fastapi import BackgroundTasks
from sqlalchemy import select

from ..background_jobs import run_background_job
from ..models import BackgroundJob

log = logging.getLogger("kodo.jobs")

def _queue_job(db, tasks: BackgroundTasks, kind: str, dedupe_key: str, payload: dict):
    row = db.scalar(select(BackgroundJob).where(BackgroundJob.kind == kind, BackgroundJob.dedupe_key == dedupe_key))
    requeueable = {"failed", "complete"} if kind == "coding_session" else {"failed"}
    if row and kind == "coding_session" and row.state == "running":
        data = json.loads(row.payload or "{}")
        data["rerun_requested"] = True
        row.payload = json.dumps(data)
        row.updated_at = datetime.utcnow()
        log.info("Coding session job has another queued task: job_id=%s", row.id)
        return row
    if row and row.state not in requeueable:
        log.info("Background job already exists: kind=%s job_id=%s state=%s dedupe_key=%s", kind, row.id, row.state, dedupe_key)
        return row
    if row:
        row.payload, row.state, row.attempts, row.last_error = json.dumps(payload), "queued", 0, ""
        row.updated_at = datetime.utcnow()
    else:
        row = BackgroundJob(kind=kind, dedupe_key=dedupe_key, payload=json.dumps(payload), state="queued")
        db.add(row)
    db.flush()
    tasks.add_task(run_background_job, row.id)
    log.info("Background job queued: kind=%s job_id=%s dedupe_key=%s", kind, row.id, dedupe_key)
    return row
