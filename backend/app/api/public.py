"""Public endpoints used by the landing page."""
import re
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .. import config
from ..db import SessionLocal
from ..models import WaitlistSignup

router = APIRouter()

def _app_routes_disabled() -> bool:
    return config.DISABLE_APP_ROUTES

@router.post("/api/waitlist")
async def join_waitlist(request: Request):
    """Persist a launch-notification email without requiring an account."""
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "Send a valid JSON body")
    email = str(payload.get("email", "") if isinstance(payload, dict) else "").strip().lower()
    if len(email) > 320 or not re.fullmatch(r"[^@\s]{1,64}@[^@\s.]+(?:\.[^@\s.]+)+", email):
        raise HTTPException(422, "Enter a valid email address")

    db = SessionLocal()
    try:
        existing = db.scalar(select(WaitlistSignup.id).where(WaitlistSignup.email == email))
        if existing is None:
            db.add(WaitlistSignup(email=email))
            try:
                db.commit()
            except IntegrityError:
                # A concurrent duplicate submission is still an idempotent success.
                db.rollback()
                if db.scalar(select(WaitlistSignup.id).where(WaitlistSignup.email == email)) is None:
                    raise
        return {"ok": True}
    finally:
        db.close()

@router.get("/api/public-config")
async def get_public_config(response: Response):
    """Expose the public route-availability flag so the SPA can gate deep links."""
    response.headers["Cache-Control"] = "no-store"
    return {"disable_app_routes": _app_routes_disabled()}
