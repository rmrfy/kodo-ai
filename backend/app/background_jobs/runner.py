"""Durable background-job claiming, retries, and completion state."""
import json
import logging
import threading
import time
from datetime import datetime

from sqlalchemy import update

from ..coding_tasks import process_coding_task, process_coding_session
from ..db import SessionLocal
from ..models import BackgroundJob
from .handbook import build_repo_book
from .pull_requests import process_pull_request

log = logging.getLogger("kodo.jobs")

def run_background_job(job_id: int):
    """Claim a persisted job and retry transient failures, surviving process restarts."""
    rerun_requested = False
    db = SessionLocal()
    try:
        claimed = db.execute(update(BackgroundJob).where(BackgroundJob.id == job_id, BackgroundJob.state == "queued").values(state="running", updated_at=datetime.utcnow()))
        db.commit()
        if not claimed.rowcount:
            return
        job = db.get(BackgroundJob, job_id)
        kind, payload = job.kind, json.loads(job.payload)
        log.info("Background job claimed: job_id=%s kind=%s", job_id, kind)
    finally:
        db.close()
    succeeded, last_error = False, ""

    def save_progress(progress):
        progress_db = SessionLocal()
        try:
            row = progress_db.get(BackgroundJob, job_id)
            if row:
                data = json.loads(row.payload or "{}")
                data["progress"] = progress
                row.payload = json.dumps(data)
                row.updated_at = datetime.utcnow()
                progress_db.commit()
                payload["progress"] = progress
        finally:
            progress_db.close()

    max_attempts = 1 if kind in {"coding_task", "coding_session"} else 3
    for attempt in range(1, max_attempts + 1):
        db = SessionLocal()
        try:
            row = db.get(BackgroundJob, job_id)
            if not row:
                return
            row.attempts = attempt
            row.updated_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()
        try:
            log.info("Background job attempt started: job_id=%s kind=%s attempt=%s/%s", job_id, kind, attempt, max_attempts)
            if kind == "pull_request":
                succeeded = process_pull_request(payload["repository_id"], payload["number"], payload["event"])
            elif kind == "repo_book":
                succeeded = build_repo_book(payload["repository_id"], progress_callback=save_progress)
            elif kind == "coding_task":
                succeeded = process_coding_task(payload["task_id"])
            elif kind == "coding_session":
                succeeded = process_coding_session(payload["session_id"])
            else:
                last_error = "Unknown background job kind"
                break
            if succeeded:
                log.info("Background job attempt succeeded: job_id=%s kind=%s attempt=%s", job_id, kind, attempt)
                break
            last_error = "Job failed; retrying"
            log.warning("Background job attempt failed: job_id=%s kind=%s attempt=%s", job_id, kind, attempt)
        except Exception as error:
            last_error = type(error).__name__
            log.exception("Background job raised an exception: job_id=%s kind=%s attempt=%s error=%s", job_id, kind, attempt, error)
            if kind == "repo_book":
                progress = payload.get("progress", {})
                progress.update({"phase": "retrying", "message": f"Temporary failure ({last_error}); resuming saved batches", "updated_at": datetime.utcnow().isoformat()})
                save_progress(progress)
                payload["progress"] = progress
        if attempt < max_attempts:
            import time
            time.sleep(attempt * 2)
    db = SessionLocal()
    try:
        row = db.get(BackgroundJob, job_id)
        if row:
            final_payload = json.loads(row.payload or "{}")
            rerun_requested = kind == "coding_session" and bool(final_payload.pop("rerun_requested", False))
            row.payload = json.dumps(final_payload)
            row.state = "queued" if rerun_requested else "complete" if succeeded else "failed"
            row.last_error = "" if succeeded else last_error
            if not succeeded and kind == "repo_book":
                progress = json.loads(row.payload or "{}").get("progress", {})
                progress.update({"phase": "failed", "message": f"Failed after retries ({last_error})", "updated_at": datetime.utcnow().isoformat()})
                data = json.loads(row.payload or "{}")
                data["progress"] = progress
                row.payload = json.dumps(data)
            row.updated_at = datetime.utcnow()
            db.commit()
            log.info("Background job finished: job_id=%s kind=%s state=%s attempts=%s", job_id, kind, row.state, row.attempts)
    finally:
        db.close()
    if rerun_requested:
        threading.Thread(target=run_background_job, args=(job_id,), daemon=True).start()
