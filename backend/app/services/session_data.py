"""Work-session serialization, workspace validation, and PR eligibility."""
import hashlib
import json
import logging
import re
import requests
from datetime import datetime
from pathlib import Path
from sqlalchemy import func, select
from fastapi import HTTPException

from .. import config
from ..coding_tasks import _git, _session_workspace_path
from ..db import SessionLocal
from ..integrations import github_request, installation_token
from ..models import AgentTask, Repository, WorkSession, WorkSessionPullRequest
from .access import _authorized_repo

log = logging.getLogger("kodo.sessions")

def _agent_task_response(task: AgentTask, commit_published=False):
    return {
        "id": task.id, "repository_id": task.repository_id, "github_login": task.github_login,
        "instructions": task.instructions, "state": task.state,
        "progress_stage": task.progress_stage, "progress_message": task.progress_message,
        "source_pull_request_number": task.source_pull_request_number,
        "source_finding_key": task.source_finding_key,
        "work_session_id": task.work_session_id,
        "work_session_pull_request_id": task.work_session_pull_request_id,
        "commit_sha": task.commit_sha, "summary": task.summary, "error": task.error,
        "changes_available": task.changes_json not in {"", "{}"},
        "commit_published": bool(commit_published and task.commit_sha),
        "created_at": task.created_at.isoformat(), "updated_at": task.updated_at.isoformat(),
    }

def _session_git_status(workspace: Path):
    """Return per-file staging state from Git's NUL-delimited porcelain output."""
    raw = _git(workspace, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = {}
    parts = raw.split("\0") if raw else []
    index = 0
    while index < len(parts):
        record = parts[index]
        index += 1
        if len(record) < 4:
            continue
        code, path = record[:2], record[3:]
        entry = {
            "staged": code[0] not in {" ", "?"},
            "unstaged": code[1] not in {" ", "?"} or code == "??",
            "working_status": code,
        }
        entries[path] = entry
        if code[0] in {"R", "C"} and index < len(parts):
            entries[parts[index]] = entry
            index += 1
    return entries

def _valid_git_paths(paths):
    if not isinstance(paths, list) or not paths or len(paths) > 200:
        raise HTTPException(422, "Select one or more changed files")
    normalized = []
    for path in paths:
        if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path or "\x00" in path or any(part == ".." for part in path.split("/")):
            raise HTTPException(422, "One or more file paths are invalid")
        normalized.append(path)
    return list(dict.fromkeys(normalized))

def _session_workspace(db, repo_id: int, work_session_id: int, user_session: dict, allow_missing=False):
    repo = _authorized_repo(db, repo_id, user_session)
    work_session = db.scalar(select(WorkSession).where(
        WorkSession.id == work_session_id, WorkSession.repository_id == repo_id,
    ))
    if not work_session:
        raise HTTPException(404, "Work session not found")
    destination = db.scalar(select(WorkSessionPullRequest).where(
        WorkSessionPullRequest.work_session_id == work_session_id,
    ).order_by(WorkSessionPullRequest.sequence.desc()).limit(1))
    if not destination:
        raise HTTPException(409, "This session does not have a working branch yet")
    workspace = _session_workspace_path(work_session_id, destination.id)
    if not workspace.is_dir() or not (workspace / ".git").is_dir():
        if allow_missing and destination.status == "planned":
            return repo, work_session, destination, workspace
        raise HTTPException(409, "The saved session workspace is unavailable")
    if _git(workspace, "branch", "--show-current") != destination.branch:
        raise HTTPException(409, "The saved session workspace is on a different branch")
    return repo, work_session, destination, workspace

def _work_session_response(row, db, eligibility=None):
    tasks = db.scalars(select(AgentTask).where(AgentTask.work_session_id == row.id).order_by(AgentTask.created_at)).all()
    destinations = db.scalars(select(WorkSessionPullRequest).where(WorkSessionPullRequest.work_session_id == row.id).order_by(WorkSessionPullRequest.sequence)).all()
    eligibility = eligibility or {"can_continue": row.status != "paused", "can_retry": row.status == "paused", "reason": row.error, "pull_requests": {}}
    task_groups = {}
    for task in tasks:
        task_groups.setdefault(task.work_session_pull_request_id, []).append(task)
    destination_by_id = {destination.id: destination for destination in destinations}

    def task_response(task):
        destination = destination_by_id.get(task.work_session_pull_request_id)
        return _agent_task_response(task, commit_published=bool(destination and destination.pull_request_number))

    # Session order is authoritative: a terminal latest PR starts a new branch generation
    # on the next prompt instead of silently switching back to an older branch.
    active_destination = destinations[-1] if destinations else None
    active_eligibility = eligibility.get("pull_requests", {}).get(active_destination.id, {}) if active_destination else {}
    active_pull_request = None
    if active_destination and active_destination.pull_request_number:
        active_pull_request = {
            "number": active_destination.pull_request_number,
            "url": active_destination.pull_request_url,
            "status": active_destination.status,
        }
    normalized_status = "ready" if row.status == "complete" else row.status
    has_pending_task = any(item.state in {"queued", "running"} for item in tasks)
    return {
        "id": row.id, "title": row.title or "New work session", "status": normalized_status,
        "updated_at": row.updated_at.isoformat(),
        "error": row.error, "task_count": len(tasks), "queued_count": sum(item.state == "queued" for item in tasks),
        "tasks": [task_response(item) for item in tasks],
        "branch": active_destination.branch if active_destination else "",
        "active_destination_id": active_destination.id if active_destination else None,
        "active_destination": ({
            "id": active_destination.id, "sequence": active_destination.sequence,
            "branch": active_destination.branch, "status": active_destination.status,
            "pull_request_number": active_destination.pull_request_number,
            "pull_request_url": active_destination.pull_request_url,
            "error": active_destination.error,
            "can_continue": active_eligibility.get("can_continue", active_destination.status in {"planned", "ready", "open"}),
            "reason": active_eligibility.get("reason", active_destination.error),
        } if active_destination else None),
        "pull_request": active_pull_request,
        "can_publish": bool(active_destination
            and active_destination.status in {"ready", "open"}
            and not has_pending_task and normalized_status != "paused"),
        "pull_requests": [{
            "id": destination.id, "sequence": destination.sequence,
            "status": destination.status, "branch": destination.branch,
            "pull_request_number": destination.pull_request_number,
            "pull_request_url": destination.pull_request_url, "error": destination.error,
            "task_count": len(task_groups.get(destination.id, [])),
            "tasks": [task_response(item) for item in task_groups.get(destination.id, [])],
            "can_continue": eligibility.get("pull_requests", {}).get(destination.id, {}).get("can_continue", destination.status in {"planned", "ready", "open"}),
            "reason": eligibility.get("pull_requests", {}).get(destination.id, {}).get("reason", destination.error),
        } for destination in destinations],
        "can_continue": eligibility["can_continue"], "can_retry": eligibility["can_retry"],
        "can_start_new_pr": eligibility.get("can_start_new_pr", True),
        "reason": eligibility["reason"],
    }

def _verify_session_pull_request(repo, destination):
    """Return whether a destination still points at the same writable open PR."""
    if not destination.pull_request_number:
        return destination.status in {"planned", "ready"}
    try:
        token = installation_token(repo.installation_id)
        pull = github_request("GET", f"/repos/{repo.full_name}/pulls/{destination.pull_request_number}", token)
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else 0
        if status == 404:
            destination.status = "unavailable"
            destination.error = "This pull request is no longer available. The next coding turn will start a new session branch."
            return False
        raise HTTPException(503, "kodai could not verify the pull request. Try again shortly.")
    if pull.get("state") != "open":
        destination.status = "closed"
        destination.error = "This pull request is closed or merged. The next coding turn will start a new session branch."
        return False
    head = pull.get("head") or {}
    head_repo = (head.get("repo") or {}).get("full_name", "")
    if head_repo.casefold() != repo.full_name.casefold():
        destination.status = "ineligible"
        destination.error = "This PR uses a fork branch kodai cannot update. The next coding turn will start a new session branch."
        return False
    if destination.branch and head.get("ref") != destination.branch:
        destination.status = "ineligible"
        destination.error = "The PR branch changed. The next coding turn will start a new session branch."
        return False
    destination.status, destination.error = "open", ""
    return True

def _session_eligibility(repo, sessions, destinations):
    """Check PR destinations in one GitHub request; sessions may start another PR."""
    result = {row.id: {"can_continue": row.status != "paused", "can_retry": row.status == "paused", "can_start_new_pr": True, "reason": row.error, "pull_requests": {}} for row in sessions}
    active_destinations = [row for row in destinations if row.pull_request_number]
    open_prs = None
    lookup_error = ""
    if active_destinations:
        try:
            token = installation_token(repo.installation_id)
            open_prs = github_request("GET", f"/repos/{repo.full_name}/pulls", token, params={"state": "open", "per_page": 100}) or []
        except Exception:
            lookup_error = "kodai could not verify this pull request. Try refreshing in a moment."
    open_by_number = {pull.get("number"): pull for pull in (open_prs or [])}
    for destination in destinations:
        reason = ""
        target_valid = not destination.pull_request_number and destination.status in {"planned", "ready"}
        if destination.pull_request_number:
            pull = open_by_number.get(destination.pull_request_number)
            if lookup_error:
                target_valid, reason = False, lookup_error
            elif not pull:
                target_valid = False
                reason = "This PR is closed or unavailable. The next coding turn starts a new branch in this session."
                destination.status, destination.error, destination.updated_at = "closed", reason, datetime.utcnow()
            else:
                head = pull.get("head") or {}
                head_repo = (head.get("repo") or {}).get("full_name", "")
                if head_repo.casefold() != repo.full_name.casefold():
                    target_valid = False
                    reason = "This PR uses a fork branch kodai cannot update. The next coding turn starts a new branch in this session."
                    destination.status, destination.error = "ineligible", reason
                elif destination.branch and head.get("ref") != destination.branch:
                    target_valid = False
                    reason = "The PR branch changed. The next coding turn starts a new branch in this session."
                    destination.status, destination.error = "ineligible", reason
                else:
                    target_valid = True
                    destination.status, destination.error = "open", ""
        result[destination.work_session_id]["pull_requests"][destination.id] = {"can_continue": target_valid, "reason": reason}
    return result

def _new_session_pull_request(db, work_session):
    sequence = db.scalar(select(func.max(WorkSessionPullRequest.sequence)).where(
        WorkSessionPullRequest.work_session_id == work_session.id,
    )) or 0
    sequence += 1
    slug = re.sub(r"[^a-z0-9-]+", "-", work_session.title.lower()).strip("-")[:40] or "work"
    destination = WorkSessionPullRequest(
        work_session_id=work_session.id, repository_id=work_session.repository_id,
        sequence=sequence,
        branch=f"kodo/{slug}-{work_session.id}" + (f"-{sequence}" if sequence > 1 else ""),
        status="planned",
    )
    db.add(destination)
    db.flush()
    return destination

def _finding_key(finding: dict) -> str:
    canonical = {key: finding.get(key) for key in ("title", "path", "line", "severity", "body")}
    return hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

def _session_title_from_instructions(instructions: str) -> str:
    first_line = next((line.strip() for line in instructions.splitlines() if line.strip()), "New work session")
    return re.sub(r"^#+\s*", "", first_line)[:200] or "New work session"
