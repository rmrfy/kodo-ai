"""Run coding turns in a persistent session workspace and publish sessions as PRs."""
import os
import re
import json
import logging
import requests
import subprocess
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from fastapi import HTTPException
from sqlalchemy import func, select

from . import config
from .coding_agents import CodingAgentRequest, CodingAgentSandbox, get_coding_agent_provider
from .coding_agents.interface import MAX_CODING_AGENT_RESPONSE_CHARS
from .db import SessionLocal
from .integrations import github_request, installation_token
from .maintainer_context import format_context, load_context
from .models import (AgentTask, AuthIdentity, Installation, Organization, OrganizationMembership, Repository,
                     WorkSession, WorkSessionPullRequest, Workspace)
from .services.access import _member_can_access_repo
from .services.auth import _user_github_request
from .services.security import _decrypt_token

log = logging.getLogger("kodo.coding_tasks")


def _save_task(task_id: int, **fields):
    db = SessionLocal()
    try:
        task = db.get(AgentTask, task_id)
        if task:
            if fields.get("state") in {"queued", "complete", "failed"}:
                fields.setdefault("progress_stage", "")
                fields.setdefault("progress_message", "")
            for name, value in fields.items():
                setattr(task, name, value)
            task.updated_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def _save_task_progress(task_id: int, progress):
    _save_task(
        task_id,
        progress_stage=progress.stage[:32],
        progress_message=progress.message[:500],
    )


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


def _reroute_task_to_new_branch(task_id: int, destination_id: int, reason: str) -> dict:
    """Start a new session branch generation after its published PR becomes terminal."""
    db = SessionLocal()
    try:
        task = db.get(AgentTask, task_id)
        old_destination = db.get(WorkSessionPullRequest, destination_id)
        work_session = db.get(WorkSession, task.work_session_id) if task else None
        if not task or not old_destination or not work_session:
            raise RuntimeError("The session branch is no longer available")
        old_destination.status = "ineligible"
        old_destination.error = reason
        old_destination.updated_at = datetime.utcnow()
        destination = _new_destination_in_db(db, work_session)
        task.work_session_pull_request_id = destination.id
        task.updated_at = datetime.utcnow()
        work_session.status, work_session.error = "active", ""
        work_session.updated_at = datetime.utcnow()
        db.commit()
        log.info("Session task moved to a new branch generation: task_id=%s previous_destination=%s destination=%s branch=%s", task_id, destination_id, destination.id, destination.branch)
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
        details = (result.stderr or result.stdout or "Git returned a non-zero exit status").strip()
        token = (env or {}).get("KODO_GIT_TOKEN") if env else None
        if token:
            details = details.replace(token, "[redacted]")
        raise RuntimeError(f"Git {' '.join(args[:2])} failed: {details[:500]}")
    # Preserve significant leading spaces from porcelain status records and
    # whitespace in filenames; callers split NUL-delimited output themselves.
    return result.stdout.rstrip("\r\n")


def _agent_result_with_change_state(agent_result, changes_json: str):
    """Use the turn snapshot so earlier uncommitted work is not mistaken for new edits."""
    try:
        changed = bool(json.loads(changes_json).get("files"))
    except (TypeError, ValueError):
        changed = False
    return replace(agent_result, changes_made=changed)


def _workspace_tree_snapshot(workspace: Path, index_path: Path) -> str:
    """Write worktree state into a temporary tree without touching the user's index."""
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = str(index_path)
    _git(workspace, "read-tree", "HEAD", env=env)
    _git(workspace, "add", "-A", "--", env=env)
    return _git(workspace, "write-tree", env=env)


def _workspace_turn_changes(workspace: Path, before_tree: str, after_tree: str) -> str:
    files, combined, truncated = [], 0, False
    names = _git(workspace, "diff", "--name-status", "--no-renames", before_tree, after_tree, "--")
    for line in names.splitlines():
        status, separator, path = line.partition("\t")
        if not separator or not path:
            continue
        patch = _git(workspace, "diff", "--no-ext-diff", "--no-color", "--unified=3", before_tree, after_tree, "--", path)
        remaining = max(0, config.MAX_DIFF_CHARS - combined)
        if len(patch) > remaining:
            patch, truncated = patch[:remaining], True
        combined += len(patch)
        files.append({"status": status, "path": path, "patch": patch})
    return json.dumps({"files": files, "diff": "\n".join(row["patch"] for row in files), "truncated": truncated})


def _execute_coding_agent(provider, request):
    """Execute any configured provider and enforce kodai's normalized result contract."""
    result = provider.execute(request)
    if not result.success:
        raise RuntimeError(result.error or "Coding agent failed without providing an error")
    return result


def _task_completion_summary(outcome: str, agent_response: str) -> str:
    details = agent_response.strip()
    summary = f"{outcome}\n\n{details}" if details else outcome
    return summary[:MAX_CODING_AGENT_RESPONSE_CHARS]


def _verify_task_requester_github_write(task_data: dict) -> None:
    """Recheck the requesting user's GitHub identity and write access at execution time."""
    db = SessionLocal()
    try:
        identity = db.scalar(select(AuthIdentity).where(
            AuthIdentity.user_id == task_data["requester_id"],
            AuthIdentity.provider == "github",
        ))
        if (
            not identity
            or identity.provider_user_id != str(task_data["github_user_id"])
            or not identity.access_token
        ):
            raise RuntimeError("The task requester’s GitHub account is no longer connected. Reconnect it and retry.")
        github_session = {
            "user_id": task_data["requester_id"],
            "github_user_id": task_data["github_user_id"],
            "github_login": identity.provider_username or task_data["github_login"],
            "token": _decrypt_token(identity.access_token),
        }
    finally:
        db.close()

    try:
        permission = _user_github_request(
            github_session,
            "GET",
            f"/repos/{task_data['full_name']}/collaborators/{quote(github_session['github_login'], safe='')}/permission",
        ).get("permission")
    except (HTTPException, requests.RequestException) as error:
        log.info("Coding task GitHub permission could not be confirmed: task_id=%s", task_data.get("task_id"))
        raise RuntimeError("The task requester’s GitHub access could not be confirmed. Reconnect GitHub and retry.") from error
    if permission not in {"admin", "write", "maintain"}:
        raise RuntimeError("The task requester no longer has GitHub write access to this repository.")


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


def _session_workspace_path(session_id: int, destination_id: int) -> Path:
    root = config.CODING_WORKSPACE_DIR.resolve()
    workspace = root / f"session-{session_id}" / f"branch-{destination_id}"
    workspace.parent.mkdir(parents=True, exist_ok=True)
    resolved = workspace.resolve()
    if os.path.commonpath((str(root), str(resolved))) != str(root):
        raise RuntimeError("The coding session workspace path is outside its configured directory")
    return resolved


def _is_ancestor(directory: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=directory, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError("Could not compare the session workspace with its pull request branch")
    return result.returncode == 0


def _ensure_session_workspace(workspace: Path, repo_full_name: str, branch: str, base_branch: str,
                              branch_exists: bool, git_env: dict, target_pr_head_sha: str = ""):
    remote_url = f"https://github.com/{repo_full_name}.git"
    if not workspace.exists():
        if branch_exists:
            clone_branch = branch
        else:
            clone_branch = base_branch
        _git(workspace.parent, "clone", "--depth", "1", "--single-branch", "--branch", clone_branch,
             remote_url, str(workspace), env=git_env, timeout=180)
        if not branch_exists:
            _git(workspace, "checkout", "-b", branch)
    else:
        if not (workspace / ".git").is_dir():
            raise RuntimeError("The saved session workspace is incomplete; inspect its workspace directory before retrying")
        actual_remote = _git(workspace, "remote", "get-url", "origin").rstrip("/").removesuffix(".git").casefold()
        expected_remote = remote_url.removesuffix(".git").casefold()
        if actual_remote != expected_remote:
            raise RuntimeError("The saved session workspace points to a different repository")
        if _git(workspace, "branch", "--show-current") != branch:
            raise RuntimeError("The saved session workspace is on a different branch; no changes were made")

    _git(workspace, "remote", "set-url", "origin", remote_url)
    if target_pr_head_sha:
        # Fetch into the exact remote-tracking ref read below. Passing only the
        # branch name can update FETCH_HEAD without creating origin/<branch>.
        branch_ref = f"refs/heads/{branch}:refs/remotes/origin/{branch}"
        _git(workspace, "fetch", "origin", branch_ref, env=git_env, timeout=180)
        remote_ref = f"refs/remotes/origin/{branch}"
        remote_sha = _git(workspace, "rev-parse", remote_ref)
        if remote_sha != target_pr_head_sha:
            raise RuntimeError("The pull request branch changed while the session was loading. Refresh and retry.")
        local_sha = _git(workspace, "rev-parse", "HEAD")
        if local_sha != remote_sha:
            if _is_ancestor(workspace, remote_sha, local_sha):
                # A previous push may have failed after the local session commit succeeded.
                pass
            elif _is_ancestor(workspace, local_sha, remote_sha) and not _git(workspace, "status", "--porcelain"):
                _git(workspace, "reset", "--hard", remote_ref)
            else:
                raise RuntimeError("The session workspace and pull request branch have conflicting changes")


def process_coding_task(task_id: int) -> bool:
    """Run one coding turn in the session's saved workspace."""
    task_data = {}
    snapshot_index_path = None
    turn_changes_json = "{}"
    db = SessionLocal()
    try:
        task = db.get(AgentTask, task_id)
        if not task or task.state in {"complete", "failed"}:
            return True
        work_session = db.get(WorkSession, task.work_session_id)
        destination = db.get(WorkSessionPullRequest, task.work_session_pull_request_id)
        repo = db.get(Repository, task.repository_id)
        if not repo:
            raise RuntimeError("Repository is no longer connected")
        installation = db.get(Installation, repo.installation_id)
        workspace = db.get(Workspace, repo.workspace_id) if repo.workspace_id else None
        valid_connection = bool(
            repo.connected and installation and not installation.suspended and workspace
            and installation.workspace_id == workspace.id
        )
        requester_id = task.user_id or (work_session.user_id if work_session else None)
        valid_requester = bool(requester_id and work_session and destination)
        if task.user_id and work_session and work_session.user_id and task.user_id != work_session.user_id:
            valid_requester = False
        if work_session and work_session.repository_id != repo.id:
            valid_requester = False
        if destination and destination.repository_id != repo.id:
            valid_requester = False
        if requester_id and workspace and workspace.kind == "personal":
            valid_requester = valid_requester and workspace.owner_user_id == requester_id
        elif requester_id and workspace and workspace.kind == "organization":
            organization = db.scalar(select(Organization).where(Organization.workspace_id == workspace.id))
            member = db.scalar(select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization.id if organization else False,
                OrganizationMembership.user_id == requester_id,
            )) if organization else None
            valid_requester = valid_requester and bool(member and member.role in {"owner", "admin", "developer"} and _member_can_access_repo(member, repo.id))
        if not valid_connection or not valid_requester:
            task.state = "failed"
            task.error = "Repository access changed before this task could start."
            task.progress_stage = ""
            task.progress_message = ""
            task.updated_at = datetime.utcnow()
            db.commit()
            log.info("Coding task blocked by workspace access check: task_id=%s repository_id=%s", task_id, repo.id)
            return True
        task.state = "running"
        task.progress_stage = "preparing"
        task.progress_message = "Preparing the repository workspace…"
        task.error = ""
        task.updated_at = datetime.utcnow()
        db.commit()
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
            f"- {(item.summary or item.instructions).replace(chr(10), ' ')[:400]}"
            for item in reversed(prior_tasks)
        )
        task_data = {
            "task_id": task.id,
            "requester_id": requester_id,
            "github_user_id": task.github_user_id,
            "github_login": task.github_login,
            "instructions": task.instructions,
            "repository_id": task.repository_id,
            "installation_id": repo.installation_id,
            "full_name": repo.full_name,
            "maintainer_context": format_context(*load_context(db, repo.installation_id, repo.id)),
            "work_session_id": work_session.id,
            "destination_id": destination.id,
            "destination_branch": destination.branch,
            "destination_status": destination.status,
            "pull_request_number": destination.pull_request_number,
            "session_history": session_history,
        }
        log.info("Coding task started: task_id=%s repo=%s session_id=%s", task_id, repo.full_name, task_data["work_session_id"])
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    try:
        if not config.CODING_TASKS_ENABLED:
            raise RuntimeError("Coding tasks are disabled by KODO_CODING_TASKS_ENABLED")
        _verify_task_requester_github_write(task_data)
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
                    reroute_reason = "The session PR is no longer available. This turn is starting a new branch in the same session."
                else:
                    raise
            if target_pr:
                head = target_pr.get("head") or {}
                head_repo = (head.get("repo") or {}).get("full_name") or ""
                if target_pr.get("state") != "open":
                    reroute_reason = "The session PR was closed. This turn is starting a new branch in the same session."
                elif head_repo.casefold() != task_data["full_name"].casefold():
                    reroute_reason = "The session PR uses a fork branch kodai cannot update. This turn is starting a new branch in the same session."
                elif task_data["destination_branch"] and head.get("ref") != task_data["destination_branch"]:
                    reroute_reason = "The session PR branch changed. This turn is starting a new branch in the same session."
                else:
                    branch = head.get("ref") or ""
                    target_pr_head_sha = (head.get("sha") or "").strip()
                    if not branch or not target_pr_head_sha:
                        raise RuntimeError("GitHub did not provide the pull request branch and head commit")
            if reroute_reason:
                moved = _reroute_task_to_new_branch(task_id, task_data["destination_id"], reroute_reason)
                task_data["destination_id"] = moved["id"]
                task_data["destination_branch"] = moved["branch"]
                task_data["destination_status"] = "planned"
                task_data["pull_request_number"] = None
                branch = moved["branch"]
                target_pr = None
                log.info("Session PR became ineligible; continuing on a new session branch: task_id=%s reason=%s", task_id, reroute_reason)
        workspace = _session_workspace_path(task_data["work_session_id"], task_data["destination_id"])
        branch_exists = bool(target_pr)
        if not workspace.exists() and not target_pr:
            try:
                github_request("GET", f"/repos/{task_data['full_name']}/branches/{quote(branch, safe='')}", token)
                branch_exists = True
            except requests.HTTPError as error:
                if error.response is None or error.response.status_code != 404:
                    raise
        if not workspace.exists() and task_data["destination_status"] == "ready" and not branch_exists:
            raise RuntimeError("This session's unpublished workspace is missing and its changes cannot be recovered from GitHub")
        log.info("Coding task workspace: task_id=%s repo=%s session_id=%s branch=%s base=%s published_pr=%s path=%s", task_id, task_data["full_name"], task_data["work_session_id"], branch, base_branch, task_data["pull_request_number"], workspace)
        with tempfile.TemporaryDirectory(prefix=f"kodai-git-auth-{task_id}-") as temp:
            temp_path = Path(temp)
            askpass = temp_path / "git-askpass"
            askpass.write_text(
                "#!/bin/sh\ncase \"$1\" in *sername*) printf '%s\\n' x-access-token;; *) printf '%s\\n' \"$KODO_GIT_TOKEN\";; esac\n",
                encoding="utf-8",
            )
            askpass.chmod(0o700)
            git_env = _git_auth_env(token, askpass)
            _ensure_session_workspace(
                workspace, task_data["full_name"], branch, base_branch,
                branch_exists, git_env, target_pr_head_sha,
            )
            snapshot_index_path = temp_path / "turn-snapshot.index"
            task_data["snapshot_before_tree"] = _workspace_tree_snapshot(workspace, snapshot_index_path)

            def report_progress(progress):
                _save_task_progress(task_id, progress)
                log.info(
                    "Coding agent progress: task_id=%s provider=%s stage=%s message=%s",
                    task_id, provider.name, progress.stage, progress.message,
                )

            agent_request = CodingAgentRequest(
                workspace=workspace,
                repository=task_data["full_name"],
                instructions=task_data["instructions"],
                project_context=task_data["maintainer_context"],
                previous_work=task_data["session_history"],
                branch=branch,
                continue_existing_pr=bool(target_pr),
                timeout_seconds=config.CODING_TASK_TIMEOUT_SECONDS,
                sandbox=CodingAgentSandbox(workspace_write=True, network_access=False),
                on_progress=report_progress,
            )
            log.info("Coding agent started: task_id=%s provider=%s repo=%s timeout_seconds=%s", task_id, provider.name, task_data["full_name"], agent_request.timeout_seconds)
            agent_result = _execute_coding_agent(provider, agent_request)
            after_tree = _workspace_tree_snapshot(workspace, snapshot_index_path)
            turn_changes_json = _workspace_turn_changes(workspace, task_data["snapshot_before_tree"], after_tree)
            agent_message = agent_result.final_response
            log.info("Coding agent finished: task_id=%s provider=%s response_chars=%s", task_id, provider.name, len(agent_message))

            if _git(workspace, "branch", "--show-current") != branch:
                raise RuntimeError("The coding agent switched away from the session branch; no changes were saved")
            agent_result = _agent_result_with_change_state(agent_result, turn_changes_json)
            if agent_result.blocked:
                raise RuntimeError(agent_message or "The coding agent could not complete the request")
            if not agent_result.changes_made:
                if not agent_message.strip():
                    raise RuntimeError("The coding agent returned no answer and made no repository changes")
                log.info("Coding task answered without edits: task_id=%s", task_id)
                _save_task(
                    task_id, state="complete", commit_sha="", changes_json=turn_changes_json,
                    summary=agent_message[:MAX_CODING_AGENT_RESPONSE_CHARS], error="",
                )
                return True
            # Leave all edits in the session worktree so the user can review and
            # choose what to stage, commit, and publish from the session UI.
            log.info("Coding task changes left for review: task_id=%s branch=%s", task_id, branch)
            if target_pr:
                latest_pr = github_request("GET", f"/repos/{task_data['full_name']}/pulls/{task_data['pull_request_number']}", token)
                latest_head = latest_pr.get("head") or {}
                if latest_pr.get("state") != "open" or latest_head.get("ref") != branch:
                    raise RuntimeError("The pull request changed or closed while the coding agent was working. No changes were pushed; retry against the current PR.")
                if latest_head.get("sha") != target_pr_head_sha:
                    raise RuntimeError("The pull request branch received new commits while the coding agent was working. No changes were pushed; retry against the current PR.")
            _save_destination(task_data["destination_id"], branch=branch, status="open" if target_pr else "ready", error="")

        if target_pr:
            _save_destination(task_data["destination_id"], branch=branch, status="open", pull_request_number=target_pr["number"], pull_request_url=target_pr["html_url"], error="")
            _save_task(
                task_id, state="complete", commit_sha="", changes_json=turn_changes_json,
                summary=_task_completion_summary(
                    f"Ready for review · pull request #{target_pr['number']}",
                    agent_message,
                ), error="",
            )
            log.info("Coding task completed with unpublished edits for existing PR: task_id=%s pr=%s", task_id, target_pr["number"])
            return True

        _save_task(
            task_id, state="complete", commit_sha="", changes_json=turn_changes_json,
            summary=_task_completion_summary(
                f"Ready for review on `{branch}`",
                agent_message,
            ), error="",
        )
        _save_destination(task_data["destination_id"], branch=branch, status="ready", error="")
        log.info("Coding task completed in unpublished session workspace: task_id=%s repo=%s branch=%s", task_id, task_data["full_name"], branch)
        return True
    except Exception as error:
        if task_data.get("snapshot_before_tree") and workspace and workspace.is_dir():
            try:
                with tempfile.TemporaryDirectory(prefix=f"kodai-failed-snapshot-{task_id}-") as snapshot_temp:
                    current_tree = _workspace_tree_snapshot(workspace, Path(snapshot_temp) / "turn-snapshot.index")
                    turn_changes_json = _workspace_turn_changes(workspace, task_data["snapshot_before_tree"], current_tree)
            except Exception:
                log.exception("Could not snapshot failed task changes: task_id=%s", task_id)
        _save_task(task_id, state="failed", changes_json=turn_changes_json, error=str(error)[:1000])
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
    """Run queued turns in order and leave the session ready for another prompt."""
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
                session.status = "ready"
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
