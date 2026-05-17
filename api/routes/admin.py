import os
import secrets
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from api.lib import db
from api.lib.auth import require_admin
from api.lib.email_send import send_magic_link, send_broadcast
from api.lib.timewall import compute_prize_ladder, apply_prize_ladder

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))
SEASON = int(os.environ.get("CURRENT_SEASON", 2026))


def _current_week() -> int:
    return db.detect_current_week(SEASON)


# ── Dashboard ──────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def admin_home(request: Request, _=Depends(require_admin)):
    week = _current_week()
    players = db.get_all_players(active_only=False)
    standings = db.get_standings(SEASON, week)
    games = db.get_games(SEASON, week)
    audit = db.get_client().table("admin_audit_log").select("*").order("performed_at", desc=True).limit(30).execute().data
    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "players": players,
        "standings": standings,
        "games": games,
        "audit": audit,
        "week": week,
        "season": SEASON,
    })


# ── Player management ──────────────────────────────────────────────────────

@router.post("/player/add", response_class=RedirectResponse)
async def add_player(
    name: str = Form(...),
    email: str = Form(...),
    _=Depends(require_admin),
):
    player = db.create_player(name, email)
    week = _current_week()
    # Seed week_log row so this player shows on the leaderboard
    db.upsert_week_log(player["id"], SEASON, week, 25_000)
    send_magic_link(player)
    db.log_action("add_player", {"name": name, "email": email, "player_id": player["id"]})
    return RedirectResponse("/admin/", status_code=303)


@router.post("/player/{player_id}/paid", response_class=RedirectResponse)
async def toggle_paid(player_id: str, _=Depends(require_admin)):
    players = db.get_all_players(active_only=False)
    player = next(p for p in players if p["id"] == player_id)
    new_val = not player["paid_buyin"]
    db.update_player(player_id, paid_buyin=new_val)
    db.log_action("toggle_paid", {"player_id": player_id, "paid_buyin": new_val})
    return RedirectResponse("/admin/", status_code=303)


@router.post("/player/{player_id}/resend-link", response_class=RedirectResponse)
async def resend_link(player_id: str, _=Depends(require_admin)):
    players = db.get_all_players(active_only=False)
    player = next(p for p in players if p["id"] == player_id)
    send_magic_link(player)
    db.log_action("resend_link", {"player_id": player_id})
    return RedirectResponse("/admin/", status_code=303)


@router.post("/player/{player_id}/adjust-points", response_class=RedirectResponse)
async def adjust_points(
    player_id: str,
    week: int = Form(...),
    adjustment: int = Form(...),
    reason: str = Form(...),
    _=Depends(require_admin),
):
    """Manually adjust a player's end-of-week points (for corrections or waived penalties)."""
    from api.lib.db import get_client
    rows = (
        get_client()
        .table("week_log")
        .select("*")
        .eq("player_id", player_id)
        .eq("season", SEASON)
        .eq("week", week)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        return RedirectResponse("/admin/?error=week_log_not_found", status_code=303)
    row = rows[0]
    new_end = (row["end_points"] or row["start_points"]) + adjustment
    get_client().table("week_log").update({"end_points": new_end}).eq("id", row["id"]).execute()
    db.log_action("adjust_points", {
        "player_id": player_id, "week": week,
        "adjustment": adjustment, "reason": reason,
        "new_end_points": new_end,
    })
    return RedirectResponse("/admin/", status_code=303)


# ── Pick overrides ─────────────────────────────────────────────────────────

@router.get("/picks/{player_id}/{week}", response_class=HTMLResponse)
async def edit_picks_form(request: Request, player_id: str, week: int, _=Depends(require_admin)):
    players = db.get_all_players(active_only=False)
    player = next((p for p in players if p["id"] == player_id), None)
    picks = db.get_player_picks(player_id, SEASON, week)
    games = db.get_games(SEASON, week)
    return templates.TemplateResponse("admin/edit_picks.html", {
        "request": request,
        "player": player,
        "picks": picks,
        "games": games,
        "week": week,
        "season": SEASON,
    })


@router.post("/picks/{player_id}/{week}", response_class=RedirectResponse)
async def save_pick_override(
    player_id: str,
    week: int,
    game_id: str = Form(...),
    pick_side: str = Form(...),
    pick_amount: int = Form(...),
    _=Depends(require_admin),
):
    db.upsert_pick(player_id, game_id, pick_side, pick_amount)
    db.log_action("override_pick", {
        "player_id": player_id, "game_id": game_id,
        "pick_side": pick_side, "pick_amount": pick_amount, "week": week,
    })
    return RedirectResponse(f"/admin/picks/{player_id}/{week}", status_code=303)


# ── Game management ────────────────────────────────────────────────────────

@router.post("/game/{game_id}/void", response_class=RedirectResponse)
async def void_game(
    game_id: str,
    reason: str = Form(...),
    _=Depends(require_admin),
):
    db.update_game(game_id, status="voided", voided_reason=reason)
    db.log_action("void_game", {"game_id": game_id, "reason": reason})
    return RedirectResponse("/admin/", status_code=303)


@router.post("/game/{game_id}/correct-score", response_class=RedirectResponse)
async def correct_score(
    game_id: str,
    home_score: int = Form(...),
    away_score: int = Form(...),
    _=Depends(require_admin),
):
    db.update_game(game_id, home_score=home_score, away_score=away_score)
    db.log_action("correct_score", {"game_id": game_id, "home_score": home_score, "away_score": away_score})
    return RedirectResponse("/admin/", status_code=303)


# ── Penalty waive ──────────────────────────────────────────────────────────

@router.post("/penalty/{penalty_id}/waive", response_class=RedirectResponse)
async def waive_penalty(
    penalty_id: str,
    reason: str = Form(...),
    _=Depends(require_admin),
):
    db.waive_penalty(penalty_id, reason)
    db.log_action("waive_penalty", {"penalty_id": penalty_id, "reason": reason})
    return RedirectResponse("/admin/", status_code=303)


# ── Season payout ──────────────────────────────────────────────────────────

@router.get("/payout", response_class=HTMLResponse)
async def payout_page(request: Request, _=Depends(require_admin)):
    """End-of-season prize payout summary for Ryan to reference when sending Venmo payments."""
    players_all = db.get_all_players(active_only=False)
    paid_count = sum(1 for p in players_all if p.get("paid_buyin"))
    pot = paid_count * 50

    # Use final standings from the last settled week
    final_week = db.detect_current_week(SEASON)
    standings = db.get_standings(SEASON, final_week)

    # Merge paid_buyin flag into standings for prize computation
    paid_by_id = {p["id"]: p.get("paid_buyin", False) for p in players_all}
    for s in standings:
        s["paid_buyin"] = paid_by_id.get(s["player_id"], False)

    prizes = compute_prize_ladder(max(paid_count, 1))
    standings = apply_prize_ladder(standings, prizes)

    return templates.TemplateResponse("admin/payout.html", {
        "request": request,
        "standings": standings,
        "prizes": prizes,
        "pot": pot,
        "paid_count": paid_count,
        "final_week": final_week,
        "season": SEASON,
        "week": final_week,
    })


# ── Broadcast ──────────────────────────────────────────────────────────────

@router.post("/broadcast", response_class=RedirectResponse)
async def send_broadcast_msg(
    subject: str = Form(...),
    body_html: str = Form(...),
    banner_text: str = Form(default=""),
    _=Depends(require_admin),
):
    players = db.get_all_players()
    send_broadcast(players, subject, body_html)
    from api.lib.db import get_client
    get_client().table("broadcasts").insert({
        "subject": subject,
        "body_html": body_html,
        "banner_text": banner_text or None,
        "sent_at": "now()",
    }).execute()
    db.log_action("broadcast", {"subject": subject})
    return RedirectResponse("/admin/", status_code=303)
