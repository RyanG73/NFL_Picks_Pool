import os
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from api.lib import db
from api.lib.auth import validate_magic_token

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))

SEASON = int(os.environ.get("CURRENT_SEASON", 2026))


def _current_week() -> int:
    from api.lib.db import get_client
    res = get_client().table("games").select("week").eq("season", SEASON).order("week", desc=True).limit(1).execute()
    return res.data[0]["week"] if res.data else 1


def _available_points(player_id: str, week: int) -> int:
    """Player's starting points for the current week from week_log."""
    from api.lib.db import get_client
    res = (
        get_client()
        .table("week_log")
        .select("start_points")
        .eq("player_id", player_id)
        .eq("season", SEASON)
        .eq("week", week)
        .single()
        .execute()
    )
    return res.data["start_points"] if res.data else 25_000


def _validate_picks(
    game_ids: list[str],
    sides: list[str],
    amounts: list[int],
    games_by_id: dict,
    available: int,
) -> list[str]:
    """Return a list of validation error messages (empty = valid)."""
    errors = []
    total = 0
    used_games = set()
    for gid, side, amount in zip(game_ids, sides, amounts):
        if not gid:
            continue
        if gid in used_games:
            errors.append("You picked the same game twice.")
            continue
        used_games.add(gid)
        game = games_by_id.get(gid)
        if not game:
            errors.append(f"Unknown game ID {gid}.")
            continue
        if game["status"] != "scheduled":
            errors.append(f"Game {game['favorite_team']} vs {game['underdog_team']} is already locked or voided.")
            continue
        if datetime.now(timezone.utc) >= datetime.fromisoformat(game["kickoff_at"]):
            errors.append(f"Game {game['favorite_team']} vs {game['underdog_team']} has already kicked off.")
            continue
        if side not in ("FAVORITE", "UNDERDOG"):
            errors.append("Invalid pick side.")
            continue
        if amount < 500:
            errors.append(f"Minimum bet is 500 points (you entered {amount:,}).")
            continue
        if amount % 500 != 0:
            errors.append(f"Bets must be in increments of 500 (you entered {amount:,}).")
            continue
        total += amount

    if total > available:
        errors.append(f"Total bets ({total:,}) exceed your available {available:,} points.")
    if not used_games:
        errors.append("You must select at least one game.")
    return errors


@router.get("/p/{token}", response_class=HTMLResponse)
async def picks_form(request: Request, token: str):
    player = validate_magic_token(token)
    week = _current_week()
    games = db.get_games(SEASON, week)
    existing_picks = {p["game_id"]: p for p in db.get_player_picks(player["id"], SEASON, week)}
    available = _available_points(player["id"], week)
    already_used = sum(p["pick_amount"] for p in existing_picks.values())
    banner = db.get_active_banner()

    return templates.TemplateResponse("picks_form.html", {
        "request": request,
        "player": player,
        "week": week,
        "season": SEASON,
        "games": games,
        "existing_picks": existing_picks,
        "available_points": available,
        "committed_points": already_used,
        "remaining_points": available - already_used,
        "banner": banner,
        "errors": [],
        "success": False,
    })


@router.post("/p/{token}", response_class=HTMLResponse)
async def submit_picks(
    request: Request,
    token: str,
):
    player = validate_magic_token(token)
    week = _current_week()
    games = db.get_games(SEASON, week)
    games_by_id = {g["id"]: g for g in games}
    available = _available_points(player["id"], week)
    banner = db.get_active_banner()

    form = await request.form()

    # Parse up to 3 pick slots from form data
    game_ids = [form.get(f"game_id_{i}", "") for i in range(1, 4)]
    sides    = [form.get(f"side_{i}", "") for i in range(1, 4)]
    raw_amts = [form.get(f"amount_{i}", "0") for i in range(1, 4)]
    amounts  = []
    for raw in raw_amts:
        try:
            amounts.append(int(str(raw).replace(",", "").strip()))
        except ValueError:
            amounts.append(0)

    errors = _validate_picks(game_ids, sides, amounts, games_by_id, available)

    existing_picks = {p["game_id"]: p for p in db.get_player_picks(player["id"], SEASON, week)}

    if errors:
        already_used = sum(p["pick_amount"] for p in existing_picks.values())
        return templates.TemplateResponse("picks_form.html", {
            "request": request,
            "player": player,
            "week": week,
            "season": SEASON,
            "games": games,
            "existing_picks": existing_picks,
            "available_points": available,
            "committed_points": already_used,
            "remaining_points": available - already_used,
            "banner": banner,
            "errors": errors,
            "success": False,
        })

    # Write picks (upsert — replaces prior submission for that game)
    for gid, side, amount in zip(game_ids, sides, amounts):
        if not gid:
            continue
        db.upsert_pick(player["id"], gid, side, amount)
        db.log_action("submit_pick", {
            "player_id": player["id"],
            "player_name": player["name"],
            "game_id": gid,
            "side": side,
            "amount": amount,
            "week": week,
        })

    # Reload picks after save
    existing_picks = {p["game_id"]: p for p in db.get_player_picks(player["id"], SEASON, week)}
    already_used = sum(p["pick_amount"] for p in existing_picks.values())

    return templates.TemplateResponse("picks_form.html", {
        "request": request,
        "player": player,
        "week": week,
        "season": SEASON,
        "games": games,
        "existing_picks": existing_picks,
        "available_points": available,
        "committed_points": already_used,
        "remaining_points": available - already_used,
        "banner": banner,
        "errors": [],
        "success": True,
    })
