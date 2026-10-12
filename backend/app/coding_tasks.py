"""Run repository tasks and publish results to a new or existing pull request."""
import os
import re
import logging
import requests
import subprocess
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from sqlalchemy import func, select

from . import config
from .coding_agents import CodingAgentRequest, CodingAgentSandbox, get_coding_agent_provider
from .db import SessionLocal
from .integrations import github_request, installation_token
from .maintainer_context import format_context, load_context
from .models import AgentTask, Repository, WorkSession, WorkSessionPullRequest

log = logging.getLogger("kodo.coding_tasks")


def _save_task(task_id: int, **fields):
    db = SessionLocal()
    try:
        task = db.get(AgentTask, task_id)
        if task:
            for name, value in fields.items():
                setattr(task, name, value)
            task.updated_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def _new_destination_in_db(db, work_session):
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


def _reroute_task_to_new_pr(task_id: int, destination_id: int, reason: str) -> dict:
    """Move a queued task to a fresh session PR when its selected PR became unsafe."""
    db = SessionLocal()
    try:
        task = db.get(AgentTask, task_id)
        old_destination = db.get(WorkSessionPullRequest, destination_id)
        work_session = db.get(WorkSession, task.work_session_id) if task else None
        if not task or not old_destination or not work_session:
            raise RuntimeError("The selected session PR is no longer available")
        old_destination.status = "ineligible"
        old_destination.error = reason
        old_destination.updated_at = datetime.utcnow()
        destination = _new_destination_in_db(db, work_session)
        task.work_session_pull_request_id = destination.id
        task.updated_at = datetime.utcnow()
        work_session.status, work_session.error = "active", ""
        work_session.updated_at = datetime.utcnow()
        db.commit()
        log.info("Session task moved to a new PR destination: task_id=%s previous_destination=%s destination=%s branch=%s", task_id, destination_id, destination.id, destination.branch)
        return {"id": destination.id, "branch": destination.branch}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _git(directory: Path, *args: str, env=None, timeout=120):
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *args],
        cwd=directory,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Git operation failed. Check repository access and branch permissions.")
    return result.stdout.strip()


def _agent_result_with_change_state(agent_result, workspace: Path):
    """Let orchestration use Git's workspace state as the reliable change signal."""
    return replace(agent_result, changes_made=bool(_git(workspace, "status", "--porcelain")))


def _execute_coding_agent(provider, request):
    """Execute any configured provider and enforce kodai's normalized result contract."""
    result = provider.execute(request)
    if not result.success:
        raise RuntimeError(result.error or "Coding agent failed without providing an error")
    return result


def _task_completion_summary(outcome: str, agent_response: str) -> str:
    details = agent_response.strip()
    return f"{outcome}\n\n{details}"[:1000] if details else outcome[:1000]


def _git_auth_env(token: str, askpass: Path):
    env = os.environ.copy()
    env.pop("GITHUB_TOKEN", None)
    env.pop("GH_TOKEN", None)
    env.update({
        "GIT_ASKPASS": str(askpass),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "KODO_GIT_TOKEN": token,
    })
    return env


def process_coding_task(task_id: int) -> bool:
    """Create an isolated clone, run the configured agent, then publish a task branch and PR."""
    task_data = {}
    db = SessionLocal()
    try:
        task = db.get(AgentTask, task_id)
        if not task or task.state in {"complete", "failed"}:
            return True
        repo = db.get(Repository, task.repository_id)
        if not repo:
            raise RuntimeError("Repository is no longer connected")
        task.state = "running"
        task.error = ""
        task.updated_at = datetime.utcnow()
        db.commit()
        work_session = db.get(WorkSession, task.work_session_id)
        destination = db.get(WorkSessionPullRequest, task.work_session_pull_request_id)
        if not work_session or not destination:
            raise RuntimeError("The task is missing its session or PR destination")
        if work_session and work_session.status == "paused":
            return True
        prior_tasks = db.scalars(select(AgentTask).where(
            AgentTask.work_session_id == work_session.id,
            AgentTask.id != task.id,
            AgentTask.state == "complete",
        ).order_by(AgentTask.created_at.desc()).limit(10)).all()
        session_history = "\n".join(
            f"- {item.title}: {(item.summary or 'Completed.').replace(chr(10), ' ')[:400]}"
            for item in reversed(prior_tasks)
        )
        task_data = {
            "title": task.title,
            "instructions": task.instructions,
            "repository_id": task.repository_id,
            "installation_id": repo.installation_id,
            "full_name": repo.full_name,
            "maintainer_context": format_context(*load_context(db, repo.installation_id, repo.id)),
            "work_session_id": work_session.id,
            "destination_id": destination.id,
            "destination_branch": destination.branch,
            "pull_request_number": destination.pull_request_number,
            "session_history": session_history,
        }
        log.info("Coding task started: task_id=%s repo=%s session_id=%s title=%r", task_id, repo.full_name, task_data["work_session_id"], task.title)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    try:
        if not config.CODING_TASKS_ENABLED:
            raise RuntimeError("Coding tasks are disabled by KODO_CODING_TASKS_ENABLED")
        provider = get_coding_agent_provider()
        token = installation_token(task_data["installation_id"])
        metadata = github_request("GET", f"/repos/{task_data['full_name']}", token)
        base_branch = metadata.get("default_branch") or "main"
        target_pr = None
        target_pr_head_sha = ""
        branch = task_data["destination_branch"]
        if task_data["pull_request_number"]:
            reroute_reason = ""
            try:
                target_pr = github_request("GET", f"/repos/{task_data['full_name']}/pulls/{task_data['pull_request_number']}", token)
            except requests.HTTPError as error:
                if error.response is not None and error.response.status_code == 404:
                    reroute_reason = "The selected PR is no longer available. This task is opening a new PR in the same session."
                else:
                    raise
            if target_pr:
                head = target_pr.get("head") or {}
                head_repo = (head.get("repo") or {}).get("full_name") or ""
                if target_pr.get("state") != "open":
                    reroute_reason = "The selected PR was closed. This task is opening a new PR in the same session."
                elif head_repo.casefold() != task_data["full_name"].casefold():
                    reroute_reason = "The selected PR uses a fork branch kodai cannot update. This task is opening a new PR in the same session."
                elif task_data["destination_branch"] and head.get("ref") != task_data["destination_branch"]:
                    reroute_reason = "The selected PR branch changed. This task is opening a new PR in the same session."
                else:
                    branch = head.get("ref") or ""
                    target_pr_head_sha = (head.get("sha") or "").strip()
                    if not branch or not target_pr_head_sha:
                        raise RuntimeError("GitHub did not provide the pull request branch and head commit")
            if reroute_reason:
                moved = _reroute_task_to_new_pr(task_id, task_data["destination_id"], reroute_reason)
                task_data["destination_id"] = moved["id"]
                task_data["destination_branch"] = moved["branch"]
                task_data["pull_request_number"] = None
                branch = moved["branch"]
                target_pr = None
                log.info("Session PR became ineligible; continuing task on a new session PR: task_id=%s reason=%s", task_id, reroute_reason)
        branch_exists = False
        if not target_pr:
            try:
                github_request("GET", f"/repos/{task_data['full_name']}/branches/{quote(branch, safe='')}", token)
                branch_exists = True
            except requests.HTTPError as error:
                if error.response is None or error.response.status_code != 404:
                    raise
        log.info("Coding task checkout: task_id=%s repo=%s branch=%s base=%s session_pr=%s", task_id, task_data["full_name"], branch, base_branch, task_data["pull_request_number"])
        with tempfile.TemporaryDirectory(prefix=f"kodo-task-{task_id}-") as temp:
            temp_path = Path(temp)
            workspace = temp_path / "workspace"
            askpass = temp_path / "git-askpass"
            askpass.write_text(
                "#!/bin/sh\ncase \"$1\" in *sername*) printf '%s\\n' x-access-token;; *) printf '%s\\n' \"$KODO_GIT_TOKEN\";; esac\n",
                encoding="utf-8",
            )
            askpass.chmod(0o700)
            git_env = _git_auth_env(token, askpass)
            clone_existing_branch = bool(target_pr or branch_exists)
            clone_branch = branch if clone_existing_branch else base_branch
            _git(temp_path, "clone", "--depth", "1", "--single-branch", "--branch", clone_branch,
                 f"https://github.com/{task_data['full_name']}.git", str(workspace), env=git_env, timeout=180)
            if not clone_existing_branch:
                _git(workspace, "checkout", "-b", branch)

            agent_request = CodingAgentRequest(
                workspace=workspace,
                repository=task_data["full_name"],
                task_title=task_data["title"],
                instructions=task_data["instructions"],
                project_context=task_data["maintainer_context"],
                previous_work=task_data["session_history"],
                branch=branch,
                continue_existing_pr=bool(target_pr),
                timeout_seconds=config.CODING_TASK_TIMEOUT_SECONDS,
                sandbox=CodingAgentSandbox(workspace_write=True, network_access=False),
                on_progress=lambda progress: log.info(
                    "Coding agent progress: task_id=%s provider=%s stage=%s message=%s",
                    task_id, provider.name, progress.stage, progress.message,
                ),
            )
            log.info("Coding agent started: task_id=%s provider=%s repo=%s timeout_seconds=%s", task_id, provider.name, task_data["full_name"], agent_request.timeout_seconds)
            agent_result = _execute_coding_agent(provider, agent_request)
            agent_message = agent_result.final_response
            log.info("Coding agent finished: task_id=%s provider=%s response_chars=%s", task_id, provider.name, len(agent_message))

            if _git(workspace, "branch", "--show-current") != branch:
                raise RuntimeError("The coding agent switched away from the task branch; no changes were pushed")
            agent_result = _agent_result_with_change_state(agent_result, workspace)
            if not agent_result.changes_made:
                if agent_result.no_changes_needed:
                    log.info("Coding task completed without edits: task_id=%s reason=already_implemented", task_id)
                    _save_task(
                        task_id, state="complete", commit_sha="",
                        summary=f"No changes needed. {agent_message}"[:1000], error="",
                    )
                    return True
                detail = f" Agent response: {agent_message}" if agent_message else " The agent exited successfully but provided no final explanation."
                raise RuntimeError(f"Coding agent finished without making repository changes.{detail}")
            _git(workspace, "add", "--all")
            _git(workspace, "-c", "user.name=kodai", "-c", "user.email=bot@kodo.ai",
                 "commit", "-m", f"{task_data['title']} (via kodai)")
            commit_sha = _git(workspace, "rev-parse", "HEAD")
            log.info("Coding task changes committed: task_id=%s branch=%s commit=%s", task_id, branch, commit_sha[:12])
            if target_pr:
                latest_pr = github_request("GET", f"/repos/{task_data['full_name']}/pulls/{task_data['pull_request_number']}", token)
                latest_head = latest_pr.get("head") or {}
                if latest_pr.get("state") != "open" or latest_head.get("ref") != branch:
                    raise RuntimeError("The pull request changed or closed while the coding agent was working. No changes were pushed; retry against the current PR.")
                if latest_head.get("sha") != target_pr_head_sha:
                    raise RuntimeError("The pull request branch received new commits while the coding agent was working. No changes were pushed; retry against the current PR.")
            _git(workspace, "remote", "set-url", "origin", f"https://github.com/{task_data['full_name']}.git")
            _git(workspace, "push", "--set-upstream", "origin", branch, env=git_env, timeout=180)
            log.info("Coding task branch pushed: task_id=%s repo=%s branch=%s", task_id, task_data["full_name"], branch)
            _save_task(task_id, commit_sha=commit_sha)
            _save_destination(task_data["destination_id"], branch=branch)

        if target_pr:
            _save_destination(task_data["destination_id"], branch=branch, status="open", pull_request_number=target_pr["number"], pull_request_url=target_pr["html_url"], error="")
            _save_task(
                task_id, state="complete", commit_sha=commit_sha,
                summary=_task_completion_summary(
                    f"Changes pushed to the source branch of pull request #{target_pr['number']}.",
                    agent_message,
                ), error="",
            )
            log.info("Coding task updated existing PR: task_id=%s pr=%s url=%s", task_id, target_pr["number"], target_pr["html_url"])
            return True

        pr = github_request("POST", f"/repos/{task_data['full_name']}/pulls", token, json={
            "title": task_data["title"],
            "head": branch,
            "base": base_branch,
            "body": f"## kodai task\n\n{task_data['instructions']}\n\n_Changes generated by kodai. Please review before merging._",
            "draft": True,
        })
        _save_task(
            task_id, state="complete", commit_sha=commit_sha,
            summary=_task_completion_summary(
                "Changes pushed to a new branch and opened as a draft pull request.",
                agent_message,
            ), error="",
        )
        _save_destination(task_data["destination_id"], branch=branch, status="open", pull_request_number=pr["number"], pull_request_url=pr["html_url"], error="")
        log.info("Coding task draft PR opened: task_id=%s repo=%s pr=%s url=%s", task_id, task_data["full_name"], pr["number"], pr["html_url"])
        return True
    except Exception as error:
        _save_task(task_id, state="failed", error=str(error)[:1000])
        if task_data.get("work_session_id"):
            _save_session(task_data["work_session_id"], status="paused", error=str(error)[:1000])
        log.exception("Coding task failed: task_id=%s error=%s", task_id, error)
        return False


def _save_destination(destination_id: int, **fields):
    db = SessionLocal()
    try:
        row = db.get(WorkSessionPullRequest, destination_id)
        if row:
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def _save_session(session_id: int, **fields):
    db = SessionLocal()
    try:
        row = db.get(WorkSession, session_id)
        if row:
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def process_coding_session(session_id: int) -> bool:
    """Run queued tasks for a session in order, pausing after its first failure."""
    while True:
        db = SessionLocal()
        try:
            session = db.get(WorkSession, session_id)
            if not session or session.status == "paused":
                return True
            task = db.scalar(
                select(AgentTask)
                .where(AgentTask.work_session_id == session_id, AgentTask.state == "queued")
                .order_by(AgentTask.created_at, AgentTask.id).limit(1)
            )
            if not task:
                session.status = "complete"
                session.updated_at = datetime.utcnow()
                db.commit()
                return True
            task_id = task.id
            session.status = "active"
            db.commit()
        finally:
            db.close()
        if not process_coding_task(task_id):
            return False
