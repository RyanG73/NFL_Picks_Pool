import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from api.lib import db

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))

SEASON = int(os.environ.get("CURRENT_SEASON", 2026))


def _current_week() -> int:
    """Return the highest week that has any game rows."""
    from api.lib.db import get_client
    res = get_client().table("games").select("week").eq("season", SEASON).order("week", desc=True).limit(1).execute()
    return res.data[0]["week"] if res.data else 1


# ── Leaderboard (home) ─────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    week = _current_week()
    standings = db.get_standings(SEASON, week)
    games = db.get_games(SEASON, week)
    banner = db.get_active_banner()
    return templates.TemplateResponse("leaderboard.html", {
        "request": request,
        "standings": standings,
        "week": week,
        "season": SEASON,
        "games": games,
        "banner": banner,
        "is_fragment": False,
    })


@router.get("/leaderboard-fragment", response_class=HTMLResponse)
async def leaderboard_fragment(request: Request):
    """htmx polling target — returns only the table rows."""
    week = _current_week()
    standings = db.get_standings(SEASON, week)
    return templates.TemplateResponse("fragments/standings_rows.html", {
        "request": request,
        "standings": standings,
        "week": week,
    })


# ── Week view (picks reveal + heatmap) ────────────────────────────────────

@router.get("/week/{week}", response_class=HTMLResponse)
async def week_view(request: Request, week: int):
    picks = db.get_week_picks_reveal(SEASON, week)
    game_totals = db.get_game_pick_totals(SEASON, week)
    games = db.get_games(SEASON, week)
    banner = db.get_active_banner()

    # Pivot picks into per-player rows for the table
    players_picks: dict[str, dict] = {}
    for pick in picks:
        pid = pick["player_id"]
        if pid not in players_picks:
            players_picks[pid] = {
                "player_name": pick["player_name"],
                "picks": [],
            }
        players_picks[pid]["picks"].append(pick)

    return templates.TemplateResponse("week_view.html", {
        "request": request,
        "week": week,
        "season": SEASON,
        "players_picks": list(players_picks.values()),
        "game_totals": game_totals,
        "games": games,
        "banner": banner,
    })


# ── Player profile ─────────────────────────────────────────────────────────

@router.get("/player/{player_id}", response_class=HTMLResponse)
async def player_profile(request: Request, player_id: str):
    players = db.get_all_players()
    player = next((p for p in players if p["id"] == player_id), None)
    if not player:
        return HTMLResponse("Player not found", status_code=404)
    week_log = db.get_week_log(player_id, SEASON)
    penalties = db.get_penalties(player_id, SEASON)
    return templates.TemplateResponse("player_profile.html", {
        "request": request,
        "player": player,
        "week_log": week_log,
        "penalties": penalties,
        "season": SEASON,
    })
