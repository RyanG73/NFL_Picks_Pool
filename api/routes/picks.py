import os
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from api.lib import db
from api.lib.auth import validate_magic_token
from api.lib.timewall import saturday_noon_et, is_locked as game_is_locked, kickoff_time_et, kickoff_day_et

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))
templates.env.filters["kickoff_et"] = kickoff_time_et
templates.env.filters["kickoff_day"] = kickoff_day_et

SEASON = int(os.environ.get("CURRENT_SEASON", 2026))


def _current_week() -> int:
    return db.detect_current_week(SEASON)


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
        .limit(1)
        .execute()
    )
    return res.data[0]["start_points"] if res.data else 25_000


def _validate_picks(
    game_ids: list[str],
    sides: list[str],
    amounts: list[int],
    games_by_id: dict,
    available: int,
    sat_noon: datetime,
) -> list[str]:
    """Return a list of validation error messages (empty = valid)."""
    errors = []
    total = 0
    used_games = set()
    now = datetime.now(timezone.utc)
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
        if game["status"] != "scheduled" or game_is_locked(game, now, sat_noon):
            # Game is locked, voided, or postponed — the existing DB pick is preserved
            # as-is; skip this slot silently so the player can still update other
            # unlocked slots without hitting a spurious validation error.
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
    now = datetime.now(timezone.utc)
    sat_noon = saturday_noon_et(games)
    # Annotate each game with its effective lock status for the template
    for g in games:
        g["is_locked"] = game_is_locked(g, now, sat_noon)
    existing_picks = {p["game_id"]: p for p in db.get_player_picks(player["id"], SEASON, week)}
    available = _available_points(player["id"], week)
    already_used = sum(p["pick_amount"] for p in existing_picks.values())
    banner = db.get_active_banner()
    picks_list = sorted(existing_picks.values(), key=lambda p: p["game_id"])
    slot_picks = (picks_list + [None, None, None])[:3]

    return templates.TemplateResponse("picks_form.html", {
        "request": request,
        "player": player,
        "week": week,
        "season": SEASON,
        "games": games,
        "existing_picks": existing_picks,
        "slot_picks": slot_picks,
        "available_points": available,
        "committed_points": already_used,
        "remaining_points": available - already_used,
        "banner": banner,
        "sat_noon_passed": now >= sat_noon,
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
    now = datetime.now(timezone.utc)
    sat_noon = saturday_noon_et(games)
    for g in games:
        g["is_locked"] = game_is_locked(g, now, sat_noon)
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

    # Deduct locked picks before validating, so a player who already locked a
    # Thursday pick can't over-commit on Sunday games.
    existing_picks = {p["game_id"]: p for p in db.get_player_picks(player["id"], SEASON, week)}
    locked_amount = sum(p["pick_amount"] for p in existing_picks.values() if p.get("locked_at"))
    effective_available = available - locked_amount

    errors = _validate_picks(game_ids, sides, amounts, games_by_id, effective_available, sat_noon)

    if errors:
        already_used = sum(p["pick_amount"] for p in existing_picks.values())
        picks_list = sorted(existing_picks.values(), key=lambda p: p["game_id"])
        slot_picks = (picks_list + [None, None, None])[:3]
        return templates.TemplateResponse("picks_form.html", {
            "request": request,
            "player": player,
            "week": week,
            "season": SEASON,
            "games": games,
            "existing_picks": existing_picks,
            "slot_picks": slot_picks,
            "available_points": available,
            "committed_points": already_used,
            "remaining_points": available - already_used,
            "banner": banner,
            "sat_noon_passed": now >= sat_noon,
            "errors": errors,
            "success": False,
        })

    # Remove any previously submitted picks that are no longer in this submission.
    # This handles the case where a player changes which games they picked.
    # Locked picks (games already kicked off) are preserved automatically.
    submitted_game_ids = [gid for gid in game_ids if gid]
    db.delete_unlocked_picks_not_in(player["id"], submitted_game_ids)

    # Write picks (upsert — replaces prior submission for that game).
    # Skip locked games: their DB picks are already correct and must not be overwritten.
    for gid, side, amount in zip(game_ids, sides, amounts):
        if not gid:
            continue
        game = games_by_id.get(gid)
        if game and (game["status"] == "voided" or game["status"] != "scheduled" or game_is_locked(game, now, sat_noon)):
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
    picks_list = sorted(existing_picks.values(), key=lambda p: p["game_id"])
    slot_picks = (picks_list + [None, None, None])[:3]

    return templates.TemplateResponse("picks_form.html", {
        "request": request,
        "player": player,
        "week": week,
        "season": SEASON,
        "games": games,
        "existing_picks": existing_picks,
        "slot_picks": slot_picks,
        "available_points": available,
        "committed_points": already_used,
        "remaining_points": available - already_used,
        "banner": banner,
        "sat_noon_passed": now >= sat_noon,
        "errors": [],
        "success": True,
    })
