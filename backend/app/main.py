"""FastAPI application assembly and process lifecycle."""
import asyncio
import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from . import config
from .db import SessionLocal
from .models import BackgroundJob
from .jobs import run_background_job

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("kodo")
app = FastAPI(title="kodai", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)

def _app_routes_disabled() -> bool:
    return config.DISABLE_APP_ROUTES

@app.middleware("http")
async def global_route_gate(request: Request, call_next):
    """Apply the environment-controlled route gate while keeping public APIs available."""
    if request.method == "OPTIONS":
        return await call_next(request)
    if request.method == "GET" and request.url.path == "/api/public-config":
        return await call_next(request)
    if request.method == "POST" and request.url.path == "/api/waitlist":
        return await call_next(request)
    if _app_routes_disabled():
        return JSONResponse(status_code=404, content={"detail": "kodai is not open yet"})
    return await call_next(request)

@app.on_event("startup")
async def resume_background_jobs():
    db = SessionLocal()
    try:
        rows = db.scalars(select(BackgroundJob).where(BackgroundJob.state.in_(["queued", "running"]))).all()
        job_ids = [row.id for row in rows]
        for row in rows:
            row.state = "queued"
        db.commit()
    finally:
        db.close()
    for job_id in job_ids:
        log.info("Resuming persisted background job: job_id=%s", job_id)
        asyncio.create_task(asyncio.to_thread(run_background_job, job_id))

from .api.auth import router as auth_router
from .api.health import router as health_router
from .api.knowledge import router as knowledge_router
from .api.organizations import router as organizations_router
from .api.public import router as public_router
from .api.repositories import router as repositories_router
from .api.sessions import router as sessions_router
from .api.webhooks import router as webhooks_router

app.include_router(public_router)
app.include_router(auth_router)
app.include_router(organizations_router)
app.include_router(repositories_router)
app.include_router(sessions_router)
app.include_router(knowledge_router)
app.include_router(webhooks_router)
app.include_router(health_router)
