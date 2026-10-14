"""GitHub webhook endpoint and event routing."""
import hashlib
import hmac
import json
import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from sqlalchemy import select

from .. import config
from ..db import SessionLocal
from ..models import (
    AgentTask, BookDocument, Installation, PullRequest, RepoBookSection,
    RepoChatMessage, Repository, UsageRecord, WebhookDelivery, WorkSession,
    WorkSessionPullRequest,
)
from ..services.access import _remove_coding_workspaces
from ..services.job_queue import _queue_job

router = APIRouter()
log = logging.getLogger("kodo.webhooks")

@router.post("/github-webhook")
async def github_webhook(request: Request, tasks: BackgroundTasks):
    raw = await request.body()
    signature = request.headers.get("x-hub-signature-256", "")
    if not config.GITHUB_WEBHOOK_SECRET:
        raise HTTPException(503, "Webhook secret is not configured")
    expected = "sha256=" + hmac.new(config.GITHUB_WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "Invalid webhook signature")
    delivery = request.headers.get("x-github-delivery")
    event = request.headers.get("x-github-event", "")
    if not delivery:
        raise HTTPException(400, "Missing delivery ID")
    payload = json.loads(raw or b"{}")
    log.info("GitHub webhook received: event=%s delivery=%s action=%s", event, delivery, payload.get("action", ""))
    db = SessionLocal()
    try:
        if db.get(WebhookDelivery, delivery):
            log.info("Duplicate GitHub webhook ignored: event=%s delivery=%s", event, delivery)
            return {"success": True, "duplicate": True}
        db.add(WebhookDelivery(delivery_id=delivery))
        if event == "installation":
            install = payload.get("installation", {})
            action = payload.get("action")
            if action == "suspend":
                db.query(Installation).filter(Installation.id == install.get("id")).update({"suspended": True})
                db.query(Repository).filter(Repository.installation_id == install.get("id")).update({"enabled": False})
            elif action == "deleted":
                install_repos = db.scalars(select(Repository.id).where(Repository.installation_id == install.get("id"))).all()
                if install_repos:
                    _remove_coding_workspaces(db, install_repos)
                    db.query(PullRequest).filter(PullRequest.repository_id.in_(install_repos)).delete(synchronize_session=False)
                    db.query(BookDocument).filter(BookDocument.repository_id.in_(install_repos)).delete(synchronize_session=False)
                    db.query(RepoBookSection).filter(RepoBookSection.repository_id.in_(install_repos)).delete(synchronize_session=False)
                    db.query(RepoChatMessage).filter(RepoChatMessage.repository_id.in_(install_repos)).delete(synchronize_session=False)
                    db.query(AgentTask).filter(AgentTask.repository_id.in_(install_repos)).delete(synchronize_session=False)
                    db.query(WorkSession).filter(WorkSession.repository_id.in_(install_repos)).delete(synchronize_session=False)
                    db.query(UsageRecord).filter(UsageRecord.repository_id.in_(install_repos)).delete(synchronize_session=False)
                db.query(Repository).filter(Repository.installation_id == install.get("id")).delete()
                db.query(Installation).filter(Installation.id == install.get("id")).delete()
            elif action in {"created", "unsuspend", "new_permissions_accepted"}:
                account = install.get("account") or {}
                saved_installation = db.get(Installation, install["id"])
                if not saved_installation:
                    saved_installation = Installation(id=install["id"])
                    db.add(saved_installation)
                saved_installation.account = account.get("login", "")
                saved_installation.account_type = account.get("type", "User")
                saved_installation.suspended = False
                if (saved_installation.account_type or "").casefold() != "organization":
                    saved_installation.organization_id = None
                    db.query(Repository).filter(Repository.installation_id == install["id"]).update(
                        {"organization_id": None}, synchronize_session=False,
                    )
        elif event == "installation_repositories":
            install_data = payload.get("installation", {})
            install_id = install_data.get("id")
            account = install_data.get("account") or {}
            installation = db.get(Installation, install_id) if install_id else None
            if install_id and not installation:
                installation = Installation(
                    id=install_id,
                    account=account.get("login", ""),
                    account_type=account.get("type", "User"),
                    suspended=bool(install_data.get("suspended_at")),
                )
                db.add(installation)
                db.flush()
            mapped_org_id = (
                installation.organization_id
                if installation and (installation.account_type or "").casefold() == "organization"
                else None
            )
            for r in payload.get("repositories_added", []):
                saved_repo = db.get(Repository, r["id"])
                if saved_repo and saved_repo.organization_id and mapped_org_id and saved_repo.organization_id != mapped_org_id:
                    log.warning(
                        "GitHub repository addition skipped because it is linked to another kodai organization: repo_id=%s installation_id=%s",
                        r["id"], install_id,
                    )
                    continue
                if not saved_repo:
                    saved_repo = Repository(id=r["id"], installation_id=install_id, full_name=r["full_name"])
                    db.add(saved_repo)
                saved_repo.installation_id = install_id
                saved_repo.full_name = r["full_name"]
                saved_repo.private = r.get("private", True)
                saved_repo.enabled = True
                saved_repo.organization_id = mapped_org_id
            for r in payload.get("repositories_removed", []):
                _remove_coding_workspaces(db, [r["id"]])
                db.query(Repository).filter(Repository.id == r["id"]).delete()
                db.query(PullRequest).filter(PullRequest.repository_id == r["id"]).delete()
                db.query(BookDocument).filter(BookDocument.repository_id == r["id"]).delete()
                db.query(RepoBookSection).filter(RepoBookSection.repository_id == r["id"]).delete()
                db.query(RepoChatMessage).filter(RepoChatMessage.repository_id == r["id"]).delete()
                db.query(AgentTask).filter(AgentTask.repository_id == r["id"]).delete()
                db.query(WorkSession).filter(WorkSession.repository_id == r["id"]).delete()
                db.query(UsageRecord).filter(UsageRecord.repository_id == r["id"]).delete()
        elif event == "pull_request":
            pr = payload.get("pull_request", {})
            log.info("Pull request webhook: action=%s repo_id=%s pr=%s draft=%s", payload.get("action"), (payload.get("repository") or {}).get("id"), pr.get("number"), bool(pr.get("draft", False)))
            if payload.get("action") == "closed":
                repo = db.get(Repository, payload.get("repository", {}).get("id"))
                if repo:
                    saved = db.scalar(select(PullRequest).where(PullRequest.repository_id == repo.id, PullRequest.number == pr.get("number")))
                    if saved: saved.state = "closed"
                    destinations = db.scalars(select(WorkSessionPullRequest).where(WorkSessionPullRequest.repository_id == repo.id, WorkSessionPullRequest.pull_request_number == pr.get("number"))).all()
                    for destination in destinations:
                        destination.status = "closed"
                        destination.error = "The pull request is closed or merged. The next coding turn starts a new branch in this session."
                        destination.updated_at = datetime.utcnow()
                    log.info("Pull request closed: repo=%s pr=%s", repo.full_name, pr.get("number"))
            elif payload.get("action") in {"opened", "reopened", "synchronize", "ready_for_review"} and not pr.get("draft", False):
                repo = db.get(Repository, payload.get("repository", {}).get("id"))
                if repo and repo.enabled:
                    head_sha = (pr.get("head") or {}).get("sha", "unknown")
                    action = payload.get("action", "unknown")
                    saved = db.scalar(select(PullRequest).where(PullRequest.repository_id == repo.id, PullRequest.number == pr["number"]))
                    if not saved:
                        saved = PullRequest(repository_id=repo.id, number=pr["number"])
                        db.add(saved)
                    saved.title = pr.get("title", "")
                    saved.author = (pr.get("user") or {}).get("login", "")
                    saved.state = pr.get("state", "open")
                    saved.head_sha = head_sha
                    saved.url = pr.get("html_url", "")
                    saved.status = "pending"
                    saved.updated_at = datetime.utcnow()
                    _queue_job(db, tasks, "pull_request", f"{repo.id}:{pr['number']}:{head_sha}:{action}", {"repository_id": repo.id, "number": pr["number"], "event": payload})
                elif repo:
                    log.info("PR review not queued: repo=%s pr=%s reason=repository_disabled", repo.full_name, pr.get("number"))
            else:
                reason = "draft_pull_request" if pr.get("draft", False) else "unsupported_action"
                log.info("PR review not queued: repo_id=%s pr=%s action=%s reason=%s", (payload.get("repository") or {}).get("id"), pr.get("number"), payload.get("action"), reason)
        elif event == "push":
            repo_data = payload.get("repository", {})
            repo = db.get(Repository, repo_data.get("id"))
            if repo:
                db.query(BookDocument).filter(BookDocument.repository_id == repo.id).update({"stale": True})
                db.query(RepoBookSection).filter(RepoBookSection.repository_id == repo.id).update({"stale": True})
                if repo.enabled:
                    after = payload.get("after", "unknown")
                    _queue_job(db, tasks, "repo_book", f"push:{repo.id}:{after}", {"repository_id": repo.id})
        db.commit()
        return {"success": True}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
