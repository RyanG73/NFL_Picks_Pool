"""
Short Vercel Cron endpoints (must complete within 10s).
Heavy jobs (settlement, spreads, emails) run in GitHub Actions.
"""
import os
from datetime import datetime, timezone
from fastapi import APIRouter, Header, HTTPException
from api.lib import db
from api.lib.timewall import saturday_noon_et

router = APIRouter()

VERCEL_CRON_SECRET = os.environ.get("CRON_SECRET", "")


def _verify(authorization: str | None):
    if VERCEL_CRON_SECRET and authorization != f"Bearer {VERCEL_CRON_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/lock-and-reveal")
async def lock_picks(authorization: str | None = Header(default=None)):
    """Runs every 5 minutes — locks picks at kickoff or Saturday noon."""
    _verify(authorization)
    season = int(os.environ.get("CURRENT_SEASON", 2026))
    now = datetime.now(timezone.utc)
    week = db.detect_current_week(season)
    games = db.get_games(season, week)
    sat_noon = saturday_noon_et(games)

    params: dict = {"as_of": now.isoformat()}
    if now >= sat_noon:
        params["sat_noon"] = sat_noon.isoformat()

    db.get_client().rpc("lock_kicked_off_picks", params).execute()
    return {"status": "ok", "sat_noon_passed": now >= sat_noon}


@router.get("/detect-cancellations")
async def detect_cancellations(authorization: str | None = Header(default=None)):
    """Hourly — placeholder; real detection runs in GitHub Actions."""
    _verify(authorization)
    return {"status": "ok", "note": "Full detection runs in GitHub Actions"}
