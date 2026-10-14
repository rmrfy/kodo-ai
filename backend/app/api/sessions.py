"""Coding-task and persistent work-session endpoints."""
import json
import logging
import re
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .. import config
from ..coding_tasks import _git, _git_auth_env, _session_workspace_path
from ..db import SessionLocal
from ..integrations import github_request, installation_token
from ..models import AgentTask, PullRequest, Repository, WorkSession, WorkSessionPullRequest
from ..services.auth import _session
from ..services.access import _authorized_repo, _require_github_repo_write
from ..services.session_data import (
    _agent_task_response, _finding_key, _new_session_pull_request, _session_eligibility,
    _session_git_status, _session_title_from_instructions, _session_workspace,
    _valid_git_paths, _verify_session_pull_request, _work_session_response,
)
from ..services.job_queue import _queue_job

router = APIRouter()
log = logging.getLogger("kodo.sessions")

@router.get("/api/repos/{repo_id}/tasks")
async def list_agent_tasks(repo_id: int, request: Request):
    session = _session(request)
    db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session)
        rows = db.scalars(select(AgentTask).where(AgentTask.repository_id == repo_id).order_by(AgentTask.created_at.desc()).limit(50)).all()
        return [_agent_task_response(row) for row in rows]
    finally:
        db.close()

@router.get("/api/repos/{repo_id}/work-sessions")
async def list_work_sessions(repo_id: int, request: Request):
    session = _session(request)
    db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session)
        rows = db.scalars(select(WorkSession).where(WorkSession.repository_id == repo_id).order_by(WorkSession.updated_at.desc()).limit(50)).all()
        destinations = db.scalars(select(WorkSessionPullRequest).where(WorkSessionPullRequest.work_session_id.in_([row.id for row in rows]))).all() if rows else []
        eligibility = _session_eligibility(db.get(Repository, repo_id), rows, destinations)
        db.commit()
        return [_work_session_response(row, db, eligibility[row.id]) for row in rows]
    finally:
        db.close()

@router.get("/api/repos/{repo_id}/work-sessions/{work_session_id}")
async def get_work_session(repo_id: int, work_session_id: int, request: Request):
    session = _session(request)
    db = SessionLocal()
    try:
        repo = _authorized_repo(db, repo_id, session)
        work_session = db.scalar(select(WorkSession).where(
            WorkSession.id == work_session_id,
            WorkSession.repository_id == repo_id,
        ))
        if not work_session:
            raise HTTPException(404, "Work session not found")
        destinations = db.scalars(select(WorkSessionPullRequest).where(
            WorkSessionPullRequest.work_session_id == work_session_id,
        ).order_by(WorkSessionPullRequest.sequence)).all()
        eligibility = _session_eligibility(repo, [work_session], destinations)
        db.commit()
        return _work_session_response(work_session, db, eligibility[work_session.id])
    finally:
        db.close()

@router.get("/api/repos/{repo_id}/work-sessions/{work_session_id}/tasks/{task_id}/changes")
async def get_work_session_task_changes(repo_id: int, work_session_id: int, task_id: int, request: Request):
    """Return the files and patch produced by one coding turn."""
    session = _session(request)
    db = SessionLocal()
    try:
        repo = _authorized_repo(db, repo_id, session)
        work_session = db.scalar(select(WorkSession).where(
            WorkSession.id == work_session_id,
            WorkSession.repository_id == repo_id,
        ))
        task = db.scalar(select(AgentTask).where(
            AgentTask.id == task_id,
            AgentTask.repository_id == repo_id,
            AgentTask.work_session_id == work_session_id,
        ))
        if not work_session or not task:
            raise HTTPException(404, "Session task not found")
        if task.changes_json and task.changes_json != "{}":
            try:
                saved = json.loads(task.changes_json)
                return {"task_id": task.id, "commit_sha": task.commit_sha,
                        "files": saved.get("files", []), "diff": saved.get("diff", ""),
                        "truncated": bool(saved.get("truncated"))}
            except (TypeError, ValueError):
                log.warning("Invalid task change snapshot: task_id=%s", task_id)
        if not task.commit_sha or not re.fullmatch(r"[0-9a-f]{40,64}", task.commit_sha):
            raise HTTPException(409, "This task has no saved commit to review")
        destination = db.get(WorkSessionPullRequest, task.work_session_pull_request_id)
        if not destination or destination.work_session_id != work_session_id:
            raise HTTPException(404, "Session branch not found")

        workspace = _session_workspace_path(work_session_id, destination.id)
        files = []
        diff = ""
        truncated = False
        if workspace.is_dir() and (workspace / ".git").is_dir():
            try:
                _git(workspace, "cat-file", "-e", f"{task.commit_sha}^{{commit}}")
                names = _git(workspace, "show", "--format=", "--name-status", "--no-renames", task.commit_sha, "--")
                remaining = config.MAX_DIFF_CHARS
                for line in names.splitlines():
                    status, separator, path = line.partition("\t")
                    if separator and path:
                        patch = _git(workspace, "show", "--format=", "--no-ext-diff", "--no-color", "--unified=3", task.commit_sha, "--", path)
                        if len(patch) > remaining:
                            patch = patch[:remaining]
                            truncated = True
                        remaining = max(0, remaining - len(patch))
                        diff += ("\n" if diff else "") + patch
                        files.append({"status": status, "path": path, "patch": patch})
            except RuntimeError:
                if not destination.pull_request_number:
                    raise HTTPException(404, "The saved changes are no longer available in this workspace")

        if not files and destination.pull_request_number:
            try:
                token = installation_token(repo.installation_id)
                commit = github_request("GET", f"/repos/{repo.full_name}/commits/{task.commit_sha}", token)
                for item in commit.get("files") or []:
                    status = {"added": "A", "modified": "M", "removed": "D", "renamed": "R", "copied": "C"}.get(item.get("status"), "M")
                    patch = item.get("patch") or ""
                    if len(patch) > config.MAX_DIFF_CHARS - len(diff):
                        patch = patch[:max(0, config.MAX_DIFF_CHARS - len(diff))]
                        truncated = True
                    diff += ("\n" if diff else "") + patch
                    files.append({"status": status, "path": item.get("filename", ""), "patch": patch})
            except Exception as error:
                log.warning("Could not load task diff from GitHub: task_id=%s error=%s", task_id, error)
                if not files:
                    raise HTTPException(502, "Could not load this task’s changes from GitHub")

        return {"task_id": task.id, "commit_sha": task.commit_sha, "files": files,
                "diff": diff, "truncated": truncated}
    finally:
        db.close()

@router.get("/api/repos/{repo_id}/work-sessions/{work_session_id}/tasks/{task_id}/progress")
async def get_work_session_task_progress(repo_id: int, work_session_id: int, task_id: int, request: Request):
    """Return lightweight live execution state without reloading the full session."""
    session = _session(request)
    db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session)
        task = db.scalar(select(AgentTask).where(
            AgentTask.id == task_id,
            AgentTask.repository_id == repo_id,
            AgentTask.work_session_id == work_session_id,
        ))
        if not task:
            raise HTTPException(404, "Session task not found")
        return {
            "id": task.id,
            "state": task.state,
            "progress_stage": task.progress_stage,
            "progress_message": task.progress_message,
            "summary": task.summary,
            "error": task.error,
            "updated_at": task.updated_at.isoformat(),
        }
    finally:
        db.close()

@router.get("/api/repos/{repo_id}/work-sessions/{work_session_id}/changes")
async def get_work_session_changes(repo_id: int, work_session_id: int, request: Request):
    """Return cumulative branch changes plus staged and unstaged file state."""
    user_session = _session(request)
    db = SessionLocal()
    try:
        repo, work_session, destination, workspace = _session_workspace(db, repo_id, work_session_id, user_session, allow_missing=True)
        if not workspace.is_dir() or not (workspace / ".git").is_dir():
            return {"branch": destination.branch, "pull_request_number": destination.pull_request_number,
                    "files": [], "truncated": False, "staged_count": 0, "unstaged_count": 0,
                    "commits_ahead": 0, "outgoing_files": [], "has_uncommitted_changes": False,
                    "pending_count": 0, "can_commit": False, "can_publish": False}
        base_branch = ""
        pull = None
        token = installation_token(repo.installation_id)
        if destination.pull_request_number:
            pull = github_request("GET", f"/repos/{repo.full_name}/pulls/{destination.pull_request_number}", token)
            base_branch = ((pull.get("base") or {}).get("ref") or "").strip()
        if not base_branch:
            metadata = github_request("GET", f"/repos/{repo.full_name}", token)
            base_branch = metadata.get("default_branch") or "main"
        if not re.fullmatch(r"[A-Za-z0-9._/-]{1,255}", base_branch) or ".." in base_branch.split("/"):
            raise HTTPException(502, "GitHub returned an invalid base branch")

        with tempfile.TemporaryDirectory(prefix=f"kodai-session-diff-{work_session_id}-") as temp:
            askpass = Path(temp) / "git-askpass"
            askpass.write_text(
                "#!/bin/sh\ncase \"$1\" in *sername*) printf '%s\\n' x-access-token;; *) printf '%s\\n' \"$KODO_GIT_TOKEN\";; esac\n",
                encoding="utf-8",
            )
            askpass.chmod(0o700)
            git_env = _git_auth_env(token, askpass)
            _git(workspace, "remote", "set-url", "origin", f"https://github.com/{repo.full_name}.git")
            _git(workspace, "fetch", "origin", f"refs/heads/{base_branch}:refs/remotes/origin/{base_branch}", env=git_env, timeout=180)
            if destination.pull_request_number:
                # Refresh the PR head's remote-tracking ref before calculating pending
                # commits. Otherwise it can keep pointing at the old pre-push SHA.
                _git(workspace, "fetch", "origin", f"refs/heads/{destination.branch}:refs/remotes/origin/{destination.branch}", env=git_env, timeout=180)

        base_ref = f"refs/remotes/origin/{base_branch}"
        status_by_path = _session_git_status(workspace)
        for path, status in status_by_path.items():
            if status["working_status"] == "??":
                _git(workspace, "add", "-N", "--", path)
        status_by_path = _session_git_status(workspace)
        names = _git(workspace, "diff", "--name-status", "--no-renames", base_ref, "--")
        files, combined_size, truncated = [], 0, False
        for line in names.splitlines():
            status, separator, path = line.partition("\t")
            if not separator or not path:
                continue
            patch = _git(workspace, "diff", "--no-ext-diff", "--no-color", "--unified=3", base_ref, "--", path)
            working = status_by_path.get(path, {})
            staged_patch = ""
            unstaged_patch = ""
            if working.get("staged"):
                staged_patch = _git(workspace, "diff", "--cached", "--no-ext-diff", "--no-color", "--unified=3", "HEAD", "--", path)
            if working.get("unstaged"):
                unstaged_patch = _git(workspace, "diff", "--no-ext-diff", "--no-color", "--unified=3", "--", path)
            remaining = max(0, config.MAX_DIFF_CHARS - combined_size)
            if len(patch) > remaining:
                patch, truncated = patch[:remaining], True
            combined_size += len(patch)
            files.append({"status": status, "path": path, "patch": patch,
                          "staged_patch": staged_patch, "unstaged_patch": unstaged_patch,
                          "staged": bool(working.get("staged")), "unstaged": bool(working.get("unstaged"))})
        if destination.pull_request_number:
            ahead_ref = f"refs/remotes/origin/{destination.branch}"
        else:
            try:
                upstream = _git(workspace, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
                ahead_ref = upstream
            except RuntimeError:
                ahead_ref = base_ref
        ahead = int(_git(workspace, "rev-list", "--count", f"{ahead_ref}..HEAD") or "0")
        outgoing_files = []
        if ahead:
            for line in _git(workspace, "diff", "--name-status", "--no-renames", f"{ahead_ref}..HEAD", "--").splitlines():
                status, separator, path = line.partition("\t")
                if separator and path:
                    outgoing_files.append({"status": status, "path": path})
        pending = db.scalar(select(func.count(AgentTask.id)).where(
            AgentTask.work_session_id == work_session_id, AgentTask.state.in_(["queued", "running"]),
        )) or 0
        dirty = bool(_git(workspace, "status", "--porcelain=v1", "--untracked-files=all"))
        return {
            "branch": destination.branch, "pull_request_number": destination.pull_request_number,
            "files": files, "truncated": truncated, "staged_count": sum(item["staged"] for item in status_by_path.values()),
            "unstaged_count": sum(item["unstaged"] for item in status_by_path.values()),
            "outgoing_files": outgoing_files,
            "commits_ahead": ahead, "has_uncommitted_changes": dirty,
            "pending_count": pending,
            "can_commit": not pending and any(item["staged"] for item in status_by_path.values()),
            "can_publish": not pending and not dirty and ahead > 0,
        }
    finally:
        db.close()

@router.post("/api/repos/{repo_id}/work-sessions/{work_session_id}/stage")
async def update_session_staging(repo_id: int, work_session_id: int, request: Request):
    user_session = _session(request)
    body = await request.json()
    action = body.get("action") if isinstance(body, dict) else None
    if action not in {"stage", "unstage"}:
        raise HTTPException(422, "Choose whether to stage or unstage files")
    paths = _valid_git_paths(body.get("paths") if isinstance(body, dict) else None)
    db = SessionLocal()
    try:
        repo, work_session, destination, workspace = _session_workspace(db, repo_id, work_session_id, user_session)
        pending = db.scalar(select(func.count(AgentTask.id)).where(
            AgentTask.work_session_id == work_session_id, AgentTask.state.in_(["queued", "running"]),
        )) or 0
        if pending:
            raise HTTPException(409, "Wait for session tasks to finish before changing staged files")
        changed_paths = set(_session_git_status(workspace))
        if any(path not in changed_paths for path in paths):
            raise HTTPException(422, "One or more selected files are no longer in the session workspace")
        for path in paths:
            if action == "stage":
                _git(workspace, "add", "--", path)
            else:
                _git(workspace, "reset", "-q", "HEAD", "--", path)
        work_session.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True}
    finally:
        db.close()

@router.post("/api/repos/{repo_id}/work-sessions/{work_session_id}/commit")
async def commit_session_changes(repo_id: int, work_session_id: int, request: Request):
    user_session = _session(request)
    body = await request.json()
    message = body.get("message", "") if isinstance(body, dict) else ""
    if not isinstance(message, str) or not message.strip() or len(message.strip()) > 200:
        raise HTTPException(422, "Enter a commit message up to 200 characters")
    db = SessionLocal()
    try:
        repo, work_session, destination, workspace = _session_workspace(db, repo_id, work_session_id, user_session)
        pending = db.scalar(select(func.count(AgentTask.id)).where(
            AgentTask.work_session_id == work_session_id, AgentTask.state.in_(["queued", "running"]),
        )) or 0
        if pending:
            raise HTTPException(409, "Wait for session tasks to finish before committing")
        status = _session_git_status(workspace)
        if not any(item["staged"] for item in status.values()):
            raise HTTPException(409, "Stage at least one changed file before committing")
        try:
            _git(workspace, "-c", "user.name=kodai", "-c", "user.email=bot@kodo.ai", "commit", "-m", message.strip())
        except RuntimeError as error:
            raise HTTPException(409, str(error))
        commit_sha = _git(workspace, "rev-parse", "HEAD")
        destination.status = "open" if destination.pull_request_number else "ready"
        destination.error = ""
        destination.updated_at = datetime.utcnow()
        work_session.updated_at = datetime.utcnow()
        db.commit()
        log.info("User committed staged session changes: session_id=%s branch=%s commit=%s", work_session_id, destination.branch, commit_sha[:12])
        return {"ok": True, "commit_sha": commit_sha}
    finally:
        db.close()

@router.post("/api/repos/{repo_id}/work-sessions/{work_session_id}/retry", status_code=202)
async def retry_work_session(repo_id: int, work_session_id: int, request: Request, background_tasks: BackgroundTasks):
    session = _session(request)
    db = SessionLocal()
    try:
        repo = _authorized_repo(db, repo_id, session)
        _require_github_repo_write(session, repo)
        work_session = db.scalar(select(WorkSession).where(WorkSession.id == work_session_id, WorkSession.repository_id == repo_id))
        if not work_session:
            raise HTTPException(404, "Work session not found")
        failed = db.scalar(select(AgentTask).where(AgentTask.work_session_id == work_session_id, AgentTask.state == "failed").order_by(AgentTask.created_at.desc()).limit(1))
        if not failed:
            raise HTTPException(409, "This session has no failed task to retry")
        failed.state, failed.error, failed.updated_at = "queued", "", datetime.utcnow()
        work_session.status, work_session.error, work_session.updated_at = "active", "", datetime.utcnow()
        _queue_job(db, background_tasks, "coding_session", f"agent-session:{work_session.id}", {"session_id": work_session.id})
        db.commit()
        destinations = db.scalars(select(WorkSessionPullRequest).where(
            WorkSessionPullRequest.work_session_id == work_session.id,
        ).order_by(WorkSessionPullRequest.sequence)).all()
        eligibility = _session_eligibility(db.get(Repository, repo_id), [work_session], destinations)
        db.commit()
        return _work_session_response(work_session, db, eligibility[work_session.id])
    finally:
        db.close()

@router.patch("/api/repos/{repo_id}/work-sessions/{work_session_id}")
async def rename_work_session(repo_id: int, work_session_id: int, request: Request):
    user_session = _session(request)
    body = await request.json()
    title = body.get("title", "") if isinstance(body, dict) else ""
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
        raise HTTPException(422, "Enter a session title up to 200 characters")
    db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, user_session)
        work_session = db.scalar(select(WorkSession).where(
            WorkSession.id == work_session_id,
            WorkSession.repository_id == repo_id,
            WorkSession.user_id == user_session["user_id"],
        ).with_for_update())
        if not work_session:
            raise HTTPException(404, "Work session not found")
        work_session.title = title.strip()
        work_session.updated_at = datetime.utcnow()
        db.commit()
        destinations = db.scalars(select(WorkSessionPullRequest).where(
            WorkSessionPullRequest.work_session_id == work_session.id,
        ).order_by(WorkSessionPullRequest.sequence)).all()
        eligibility = _session_eligibility(db.get(Repository, repo_id), [work_session], destinations)
        return _work_session_response(work_session, db, eligibility[work_session.id])
    finally:
        db.close()

@router.post("/api/repos/{repo_id}/work-sessions/{work_session_id}/publish")
async def publish_work_session(repo_id: int, work_session_id: int, request: Request):
    """Push the session branch and create one draft PR when the user is ready."""
    session = _session(request)
    body_input = await request.json()
    requested_title = body_input.get("title", "") if isinstance(body_input, dict) else ""
    requested_body = body_input.get("body", "") if isinstance(body_input, dict) else ""
    if not isinstance(requested_title, str) or len(requested_title.strip()) > 200:
        raise HTTPException(422, "Pull request title must be 200 characters or fewer")
    if not isinstance(requested_body, str) or len(requested_body.strip()) > 6000:
        raise HTTPException(422, "Pull request description must be 6,000 characters or fewer")
    db = SessionLocal()
    try:
        repo = _authorized_repo(db, repo_id, session)
        _require_github_repo_write(session, repo)
        work_session = db.scalar(select(WorkSession).where(
            WorkSession.id == work_session_id,
            WorkSession.repository_id == repo_id,
        ).with_for_update())
        if not work_session:
            raise HTTPException(404, "Work session not found")
        if work_session.status == "paused":
            raise HTTPException(409, "Retry the failed task before publishing this session")
        pending = db.scalar(select(func.count(AgentTask.id)).where(
            AgentTask.work_session_id == work_session_id,
            AgentTask.state.in_(["queued", "running"]),
        )) or 0
        if pending:
            raise HTTPException(409, "Wait for the current session tasks to finish before publishing")

        destinations = db.scalars(select(WorkSessionPullRequest).where(
            WorkSessionPullRequest.work_session_id == work_session_id,
        ).order_by(WorkSessionPullRequest.sequence.desc())).all()
        destination = destinations[0] if destinations else None
        if not destination:
            raise HTTPException(409, "This session does not have a working branch yet")
        existing_pull = None
        if destination.pull_request_number:
            if not _verify_session_pull_request(repo, destination):
                db.commit()
                raise HTTPException(409, "This session's pull request is closed. Continue in a new session to start another change.")
            existing_pull = github_request("GET", f"/repos/{repo.full_name}/pulls/{destination.pull_request_number}", installation_token(repo.installation_id))
        if destination.status not in {"ready", "open"}:
            raise HTTPException(409, "There are no completed changes to publish yet")

        token = installation_token(repo.installation_id)
        metadata = github_request("GET", f"/repos/{repo.full_name}", token)
        base_branch = (((existing_pull or {}).get("base") or {}).get("ref")
                       or metadata.get("default_branch") or "main")
        workspace = _session_workspace_path(work_session.id, destination.id)
        if not workspace.is_dir() or not (workspace / ".git").is_dir():
            raise HTTPException(409, "The saved session workspace is unavailable, so its unpublished changes cannot be pushed")
        if _git(workspace, "branch", "--show-current") != destination.branch:
            raise HTTPException(409, "The saved session workspace is on a different branch")
        if _git(workspace, "status", "--porcelain=v1", "--untracked-files=all"):
            raise HTTPException(409, "Stage and commit the reviewed session changes before publishing")

        with tempfile.TemporaryDirectory(prefix=f"kodai-publish-{work_session.id}-") as temp:
            askpass = Path(temp) / "git-askpass"
            askpass.write_text(
                "#!/bin/sh\ncase \"$1\" in *sername*) printf '%s\\n' x-access-token;; *) printf '%s\\n' \"$KODO_GIT_TOKEN\";; esac\n",
                encoding="utf-8",
            )
            askpass.chmod(0o700)
            git_env = _git_auth_env(token, askpass)
            _git(workspace, "remote", "set-url", "origin", f"https://github.com/{repo.full_name}.git")
            _git(workspace, "push", "--set-upstream", "origin", destination.branch, env=git_env, timeout=180)

        owner = repo.full_name.split("/", 1)[0]
        existing_prs = github_request("GET", f"/repos/{repo.full_name}/pulls", token, params={
            "state": "open", "head": f"{owner}:{destination.branch}", "base": base_branch, "per_page": 100,
        }) or []
        if existing_prs:
            pull = existing_prs[0]
        else:
            comparison = github_request(
                "GET",
                f"/repos/{repo.full_name}/compare/{quote(base_branch, safe='')}...{quote(destination.branch, safe='')}",
                token,
            )
            if not comparison.get("ahead_by"):
                raise HTTPException(409, "This session branch has no commits ahead of the default branch")
            completed = db.scalars(select(AgentTask).where(
                AgentTask.work_session_id == work_session.id,
                AgentTask.state == "complete",
            ).order_by(AgentTask.created_at)).all()
            task_list = "\n".join(
                f"- {(item.summary or item.instructions).replace(chr(10), ' ')[:300]}"
                for item in completed
            )
            generated_body = (
                f"## kodai session\n\nThis draft pull request gathers the changes from the **{work_session.title}** session.\n\n"
                f"### Session work\n{task_list or '- Session changes'}\n\n"
                "_Opened by kodai. Review the changes and checks before merging._"
            )[:6000]
            pull = github_request("POST", f"/repos/{repo.full_name}/pulls", token, json={
                "title": requested_title.strip() or work_session.title,
                "head": destination.branch,
                "base": base_branch,
                "body": requested_body.strip() or generated_body,
                "draft": True,
            })

        destination.status = "open"
        destination.pull_request_number = pull["number"]
        destination.pull_request_url = pull["html_url"]
        destination.error = ""
        destination.updated_at = datetime.utcnow()
        work_session.status = "ready"
        work_session.updated_at = datetime.utcnow()
        db.commit()
        log.info("Session published as draft PR: session_id=%s repo=%s branch=%s pr=%s", work_session.id, repo.full_name, destination.branch, pull["number"])
        destinations = db.scalars(select(WorkSessionPullRequest).where(
            WorkSessionPullRequest.work_session_id == work_session_id,
        ).order_by(WorkSessionPullRequest.sequence)).all()
        eligibility = _session_eligibility(repo, [work_session], destinations)
        db.commit()
        return _work_session_response(work_session, db, eligibility[work_session.id])
    except HTTPException:
        db.rollback()
        raise
    except Exception as error:
        db.rollback()
        log.exception("Could not publish session: session_id=%s error=%s", work_session_id, error)
        raise HTTPException(502, "Could not publish this session to GitHub. Check repository access and try again.")
    finally:
        db.close()

@router.post("/api/repos/{repo_id}/tasks", status_code=202)
async def create_agent_task(repo_id: int, request: Request, background_tasks: BackgroundTasks):
    if not config.CODING_TASKS_ENABLED:
        raise HTTPException(503, "Coding tasks are disabled by backend configuration")
    session = _session(request)
    body = await request.json()
    session_title = body.get("session_title", "") if isinstance(body, dict) else ""
    instructions = body.get("instructions", "") if isinstance(body, dict) else ""
    source_pr_number = body.get("source_pull_request_number") if isinstance(body, dict) else None
    source_finding = body.get("source_finding") if isinstance(body, dict) else None
    work_session_id = body.get("work_session_id") if isinstance(body, dict) else None
    if not isinstance(session_title, str) or len(session_title.strip()) > 200:
        raise HTTPException(422, "Session title must be up to 200 characters")
    if not isinstance(instructions, str) or len(instructions.strip()) < 10 or len(instructions) > 8000:
        raise HTTPException(422, "Describe the task in 10 to 8,000 characters")
    if source_pr_number is None and source_finding is not None:
        raise HTTPException(422, "A source pull request is required for a finding task")
    if source_pr_number is not None and (not isinstance(source_pr_number, int) or isinstance(source_pr_number, bool) or source_pr_number <= 0 or not isinstance(source_finding, dict)):
        raise HTTPException(422, "Invalid source finding")
    db = SessionLocal()
    try:
        repo = _authorized_repo(db, repo_id, session)
        _require_github_repo_write(session, repo)
        source_key = ""
        if source_pr_number is not None:
            source_pr = db.scalar(select(PullRequest).where(PullRequest.repository_id == repo_id, PullRequest.number == source_pr_number))
            valid_findings = json.loads(source_pr.findings_json) if source_pr else []
            source_key = _finding_key(source_finding)
            if not any(_finding_key(item) == source_key for item in valid_findings if isinstance(item, dict)):
                raise HTTPException(422, "That finding is no longer available on the pull request. Refresh and try again.")
            existing = db.scalar(select(AgentTask).where(
                AgentTask.repository_id == repo_id,
                AgentTask.source_pull_request_number == source_pr_number,
                AgentTask.source_finding_key == source_key,
            ).order_by(AgentTask.created_at.desc()))
            if existing:
                return _agent_task_response(existing)
        work_session = None
        repo = db.get(Repository, repo_id)
        if work_session_id is not None:
            if not isinstance(work_session_id, int) or isinstance(work_session_id, bool):
                raise HTTPException(422, "Invalid work session")
            work_session = db.scalar(select(WorkSession).where(WorkSession.id == work_session_id, WorkSession.repository_id == repo_id).with_for_update())
            if not work_session:
                raise HTTPException(404, "Work session not found")
            if work_session.status == "paused":
                raise HTTPException(409, "This session is paused after a failed task. Retry the failed task before continuing.")
        if not work_session:
            work_session = WorkSession(
                repository_id=repo_id, github_user_id=session["github_user_id"], user_id=session["user_id"],
                title=session_title.strip() or _session_title_from_instructions(instructions),
                status="active",
            )
            db.add(work_session)
            db.flush()
        elif not work_session.title:
            work_session.title = session_title.strip() or _session_title_from_instructions(instructions)
        destinations = db.scalars(select(WorkSessionPullRequest).where(
            WorkSessionPullRequest.work_session_id == work_session.id,
        ).order_by(WorkSessionPullRequest.sequence.desc())).all()
        destination = destinations[0] if destinations else None
        if destination and not _verify_session_pull_request(repo, destination):
            log.info("Session branch is no longer eligible; creating a new branch generation: session_id=%s destination_id=%s", work_session.id, destination.id)
            destination = None
        if destination is None:
            destination = _new_session_pull_request(db, work_session)
        work_session.status, work_session.error = "active", ""
        work_session.updated_at = datetime.utcnow()
        task = AgentTask(
            repository_id=repo_id, github_user_id=session["github_user_id"], user_id=session["user_id"], github_login=session["github_login"],
            instructions=instructions.strip(), state="queued",
            source_pull_request_number=source_pr_number, source_finding_key=source_key,
            work_session_id=work_session.id,
            work_session_pull_request_id=destination.id,
        )
        try:
            db.add(task)
            db.flush()
            _queue_job(db, background_tasks, "coding_session", f"agent-session:{work_session.id}", {"session_id": work_session.id})
            db.commit()
            log.info("Session task accepted: task_id=%s session_id=%s repo_id=%s requested_by=%s", task.id, work_session.id, repo_id, session["login"])
        except IntegrityError:
            db.rollback()
            if source_pr_number is not None:
                existing = db.scalar(select(AgentTask).where(
                    AgentTask.repository_id == repo_id,
                    AgentTask.source_pull_request_number == source_pr_number,
                    AgentTask.source_finding_key == source_key,
                ).order_by(AgentTask.created_at.desc()))
                if existing:
                    return _agent_task_response(existing)
            raise HTTPException(409, "This task was created at the same time by another request")
        db.refresh(task)
        return _agent_task_response(task)
    finally:
        db.close()
