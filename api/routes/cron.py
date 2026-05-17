"""
Short Vercel Cron endpoints (must complete within 10s).
Heavy jobs (settlement, spreads, emails) run in GitHub Actions.
"""
import os
from fastapi import APIRouter, Header, HTTPException
from api.lib import db

router = APIRouter()

VERCEL_CRON_SECRET = os.environ.get("CRON_SECRET", "")


def _verify(authorization: str | None):
    if VERCEL_CRON_SECRET and authorization != f"Bearer {VERCEL_CRON_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/lock-and-reveal")
async def lock_picks(authorization: str | None = Header(default=None)):
    """Saturday 11:59am — lock all picks whose games have kicked off."""
    _verify(authorization)
    season = int(os.environ.get("CURRENT_SEASON", 2026))
    from api.lib.db import get_client
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    # Lock any pick whose game has kicked off and isn't locked yet
    get_client().rpc("lock_kicked_off_picks", {"as_of": now}).execute()
    return {"status": "ok"}


@router.get("/detect-cancellations")
async def detect_cancellations(authorization: str | None = Header(default=None)):
    """Hourly — placeholder; real detection runs in GitHub Actions."""
    _verify(authorization)
    return {"status": "ok", "note": "Full detection runs in GitHub Actions"}
