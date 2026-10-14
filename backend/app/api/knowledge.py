"""Pull-request insight, Handbook, repository chat, and usage endpoints."""
import asyncio
import json
import logging
import secrets
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from sqlalchemy import func, select

from .. import ai, config
from ..db import SessionLocal
from ..maintainer_context import format_context, load_context
from ..models import (
    AgentTask, BackgroundJob, BookDocument, Installation, OrganizationMembership,
    PullRequest, RepoBookSection, RepoChatMessage, Repository, UsageRecord,
    WorkSessionPullRequest,
)
from ..repo_chat import retrieve_book_context
from ..services.auth import _session
from ..services.access import (
    _authorized_repo, _member_can_access_repo, _repo_member, _section_visible_to_audience,
)
from ..services.serialization import _chat_message_json, _json_list, _section_for_retrieval
from ..services.session_data import _finding_key
from ..services.job_queue import _queue_job

router = APIRouter()
log = logging.getLogger("kodo.knowledge")

@router.get("/api/repos/{repo_id}/pulls")
async def pull_requests(repo_id: int, request: Request):
    session = _session(request); db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session)
        rows = db.scalars(select(PullRequest).where(PullRequest.repository_id == repo_id).order_by(PullRequest.updated_at.desc()).limit(50)).all()
        linked_tasks = db.scalars(select(AgentTask).where(
            AgentTask.repository_id == repo_id, AgentTask.source_pull_request_number.is_not(None),
        ).order_by(AgentTask.created_at.desc())).all()
        task_by_finding = {(task.source_pull_request_number, task.source_finding_key): task for task in linked_tasks}
        session_pull_requests = {item.id: item for item in db.scalars(select(WorkSessionPullRequest).where(WorkSessionPullRequest.repository_id == repo_id)).all()}
        result = []
        for row in rows:
            findings = json.loads(row.findings_json)
            for finding in findings:
                if isinstance(finding, dict):
                    task = task_by_finding.get((row.number, _finding_key(finding)))
                    if task:
                        target_pr = session_pull_requests.get(task.work_session_pull_request_id)
                        finding["task"] = {
                            "id": task.id, "state": task.state,
                            "created_at": task.created_at.isoformat(),
                            "pull_request_url": target_pr.pull_request_url if target_pr else "",
                        }
            result.append({"number": row.number, "title": row.title, "author": row.author, "state": row.state, "head_sha": row.head_sha, "url": row.url, "summary": row.summary, "findings": findings, "status": row.status, "updated_at": row.updated_at.isoformat()})
        return result
    finally: db.close()

@router.get("/api/repos/{repo_id}/book")
async def repo_book(repo_id: int, request: Request):
    session = _session(request); db = SessionLocal()
    try:
        repo = _authorized_repo(db, repo_id, session, access="knowledge")
        member = _repo_member(db, repo, session["user_id"])
        knowledge_only = member.role == "knowledge"
        docs_query = (
            select(BookDocument).where(BookDocument.repository_id == repo_id).order_by(BookDocument.kind, BookDocument.path)
            if not knowledge_only
            else select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind == "manifest")
        )
        docs = db.scalars(docs_query).all()
        manifest = next((doc for doc in docs if doc.kind == "manifest"), None)
        try:
            build_summary = json.loads(manifest.content) if manifest else None
            if build_summary is not None:
                build_summary["stale"] = manifest.stale
        except json.JSONDecodeError:
            build_summary = None
        sections = db.scalars(select(RepoBookSection).where(RepoBookSection.repository_id == repo_id).order_by(RepoBookSection.category, RepoBookSection.slug)).all()
        if knowledge_only:
            sections = [section for section in sections if _section_visible_to_audience(section, member.audience)]
        return {
            "sections": [{"id": s.id, "slug": s.slug, "title": s.title, "category": s.category,
                "audiences": _json_list(s.audiences_json), "summary": s.summary, "blocks": _json_list(s.blocks_json),
                "source_paths": _json_list(s.source_paths_json), "stale": s.stale, "updated_at": s.updated_at.isoformat()} for s in sections],
            "documents": [] if knowledge_only else [{"id": d.id, "kind": d.kind, "path": d.path, "title": d.title, "content": d.content, "stale": d.stale, "updated_at": d.updated_at.isoformat()} for d in docs if d.kind != "manifest"],
            "build_summary": None if knowledge_only else build_summary,
        }
    finally: db.close()

@router.get("/api/repos/{repo_id}/chat")
async def repo_chat_history(repo_id: int, request: Request):
    session = _session(request); db = SessionLocal()
    try:
        repo = _authorized_repo(db, repo_id, session, access="knowledge")
        member = _repo_member(db, repo, session["user_id"])
        knowledge_only = member.role == "knowledge"
        docs = [] if knowledge_only else db.scalars(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind != "manifest")).all()
        sections = db.scalars(select(RepoBookSection).where(RepoBookSection.repository_id == repo_id)).all()
        if knowledge_only:
            sections = [section for section in sections if _section_visible_to_audience(section, member.audience)]
        rows = db.scalars(select(RepoChatMessage).where(
            RepoChatMessage.repository_id == repo_id,
            RepoChatMessage.user_id == session["user_id"],
        ).order_by(RepoChatMessage.created_at.desc(), RepoChatMessage.id.desc()).limit(60)).all()
        rows.reverse()
        book_is_mock = any("Mock Handbook" in doc.content or "mock mode" in doc.content.lower() for doc in docs) or any("AI is disabled" in section.summary for section in sections)
        return {"book_ready": bool(docs or sections), "book_is_mock": book_is_mock, "messages": [_chat_message_json(row) for row in rows]}
    finally:
        db.close()

@router.post("/api/repos/{repo_id}/chat")
async def ask_repo_chat(repo_id: int, request: Request):
    session = _session(request)
    body = await request.json()
    question = str(body.get("question", "")).strip()
    if not question:
        raise HTTPException(422, "Enter a question about this repository")
    if len(question) > 4000:
        raise HTTPException(422, "Questions must be 4,000 characters or fewer")

    db = SessionLocal()
    try:
        repo = _authorized_repo(db, repo_id, session, access="knowledge")
        member = _repo_member(db, repo, session["user_id"])
        knowledge_only = member.role == "knowledge"
        maintainer_context = "" if knowledge_only else format_context(*load_context(db, repo.installation_id, repo_id))
        documents = [] if knowledge_only else db.scalars(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind != "manifest").order_by(BookDocument.kind, BookDocument.path)).all()
        sections = db.scalars(select(RepoBookSection).where(RepoBookSection.repository_id == repo_id).order_by(RepoBookSection.slug)).all()
        if knowledge_only:
            sections = [section for section in sections if _section_visible_to_audience(section, member.audience)]
        if not documents and not sections:
            raise HTTPException(409, "Generate the Handbook before asking questions about this repository")
        if any("Mock Handbook" in doc.content or "mock mode" in doc.content.lower() for doc in documents) or any("AI is disabled" in section.summary for section in sections):
            raise HTTPException(409, "This Handbook contains mock summaries. Regenerate it with live AI before asking repository questions.")
        recent = db.scalars(select(RepoChatMessage).where(
            RepoChatMessage.repository_id == repo_id,
            RepoChatMessage.user_id == session["user_id"],
        ).order_by(RepoChatMessage.created_at.desc(), RepoChatMessage.id.desc()).limit(10)).all()
        recent.reverse()
        history = [{"role": row.role, "content": row.content} for row in recent]
        section_docs = [_section_for_retrieval(section) for section in sections]
        selected_sources = retrieve_book_context(question, [*section_docs, *documents])
        if not selected_sources:
            raise HTTPException(409, "The Handbook has no readable notes yet. Regenerate it, then try again.")
        user_message = RepoChatMessage(repository_id=repo_id, github_user_id=session.get("github_user_id"), user_id=session["user_id"], role="user", content=question)
        db.add(user_message)
        db.commit()
        db.refresh(user_message)
        user_message_json = _chat_message_json(user_message)
    finally:
        db.close()

    source_refs = [{
        "title": item["doc"].title, "path": item["doc"].path,
        "kind": item["doc"].kind, "stale": item["doc"].stale,
        "source_paths": _json_list(getattr(item["doc"], "source_paths_json", "[]")),
    } for item in selected_sources]
    try:
        result = await asyncio.to_thread(ai.answer_repo_question, repo.full_name, question, history, selected_sources, maintainer_context)
    except Exception as error:
        log.exception("Repository chat failed (%s)", type(error).__name__)
        raise HTTPException(502, "kodai could not answer this question. Check the backend logs and try again.")

    db = SessionLocal()
    try:
        assistant_message = RepoChatMessage(
            repository_id=repo_id, github_user_id=session.get("github_user_id"), user_id=session["user_id"], role="assistant",
            content=result["answer"], sources_json=json.dumps(source_refs),
        )
        db.add(assistant_message)
        db.add(UsageRecord(
            repository_id=repo_id, task="repo_chat", model=result["model"],
            input_tokens=result["input_tokens"], output_tokens=result["output_tokens"],
            estimated_cost_usd=result["cost"],
        ))
        db.commit()
        db.refresh(assistant_message)
        return {"user_message": user_message_json, "assistant_message": _chat_message_json(assistant_message)}
    finally:
        db.close()

@router.delete("/api/repos/{repo_id}/chat")
async def clear_repo_chat(repo_id: int, request: Request):
    session = _session(request); db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session, access="knowledge")
        db.query(RepoChatMessage).filter(
            RepoChatMessage.repository_id == repo_id,
            RepoChatMessage.user_id == session["user_id"],
        ).delete(synchronize_session=False)
        db.commit()
        return {"ok": True}
    finally:
        db.close()

@router.post("/api/repos/{repo_id}/book/rebuild")
async def rebuild_book(repo_id: int, request: Request, tasks: BackgroundTasks):
    session = _session(request); db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session)
        queued_jobs = db.scalars(select(BackgroundJob).where(
            BackgroundJob.kind == "repo_book", BackgroundJob.state == "queued",
        )).all()
        for queued in queued_jobs:
            try:
                belongs_to_repo = json.loads(queued.payload).get("repository_id") == repo_id
            except (TypeError, ValueError):
                belongs_to_repo = False
            if belongs_to_repo:
                queued.state = "failed"
                queued.last_error = "Superseded by a manual Handbook regeneration"
                queued.updated_at = datetime.utcnow()
        # Regeneration replaces generated Handbook material while retaining usage history.
        db.query(BookDocument).filter(BookDocument.repository_id == repo_id).delete(synchronize_session=False)
        db.query(RepoBookSection).filter(RepoBookSection.repository_id == repo_id).delete(synchronize_session=False)
        db.query(RepoChatMessage).filter(
            RepoChatMessage.repository_id == repo_id,
            RepoChatMessage.user_id == session["user_id"],
        ).delete(synchronize_session=False)
        job = _queue_job(db, tasks, "repo_book", f"manual:{repo_id}:{secrets.token_urlsafe(8)}", {"repository_id": repo_id})
        db.commit()
        return {"status": job.state, "job_id": job.id}
    finally:
        db.close()

@router.get("/api/repos/{repo_id}/book/rebuild/{job_id}")
async def book_rebuild_status(repo_id: int, job_id: int, request: Request):
    session = _session(request); db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session)
        job = db.get(BackgroundJob, job_id)
        if not job or job.kind != "repo_book" or json.loads(job.payload).get("repository_id") != repo_id:
            raise HTTPException(404, "Handbook job not found")
        payload = json.loads(job.payload or "{}")
        return {"state": job.state, "attempts": job.attempts, "error": job.last_error if job.state == "failed" else "", "progress": payload.get("progress")}
    finally:
        db.close()

@router.get("/api/usage")
async def usage(request: Request):
    session = _session(request); db = SessionLocal()
    try:
        memberships = db.scalars(select(OrganizationMembership).where(
            OrganizationMembership.user_id == session["user_id"], OrganizationMembership.organization_id == session.get("organization_id"),
            OrganizationMembership.role.in_(["owner", "admin", "developer"]),
        )).all()
        repo_ids = [repo_id for membership in memberships for repo_id in db.scalars(
            select(Repository.id).join(Installation, Installation.id == Repository.installation_id).where(
                Repository.organization_id == membership.organization_id,
                Installation.organization_id == membership.organization_id,
                Installation.account_type.ilike("organization"),
            )
        ).all() if _member_can_access_repo(membership, repo_id)]
        if not repo_ids:
            return []
        rows = db.execute(select(UsageRecord.task, UsageRecord.model, func.sum(UsageRecord.input_tokens), func.sum(UsageRecord.output_tokens), func.sum(UsageRecord.estimated_cost_usd)).where(UsageRecord.repository_id.in_(repo_ids)).group_by(UsageRecord.task, UsageRecord.model)).all()
        return [{"task": x[0], "model": x[1], "input_tokens": x[2] or 0, "output_tokens": x[3] or 0, "estimated_cost_usd": round(x[4] or 0, 6)} for x in rows]
    finally: db.close()
