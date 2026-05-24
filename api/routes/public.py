import os
import pathlib
from datetime import datetime, timezone
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from api.lib import db
from api.lib.timewall import saturday_noon_et, compute_prize_ladder, apply_prize_ladder, kickoff_time_et, kickoff_day_et, spread_fmt

_RULES_PATH = pathlib.Path(__file__).parent.parent.parent / "Rules" / "2026_NFL_PICKS_POOL_RULES.md"

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))
templates.env.filters["kickoff_et"] = kickoff_time_et
templates.env.filters["kickoff_day"] = kickoff_day_et
templates.env.filters["spread_fmt"] = spread_fmt

SEASON = int(os.environ.get("CURRENT_SEASON", 2026))


def _current_week() -> int:
    return db.detect_current_week(SEASON)


def _compute_live_standings(season: int, week: int) -> tuple[list[dict], bool]:
    """
    Compute standings with implied live scores for in-progress games.

    Returns (standings_list, is_live) where is_live=True means at least one
    game is currently in_progress and standings reflect real-time implied results.

    For settled picks (result != None): uses actual net_profit.
    For in_progress / final picks without settlement yet: computes ATS implied result.
    For scheduled picks: treated as 0 change (not started).
    """
    games = db.get_games(season, week)
    is_live = any(g["status"] == "in_progress" for g in games)
    has_active = any(g["status"] in ("in_progress", "final") for g in games)

    if not has_active:
        # No games started yet — use the static standings_v view
        return db.get_standings(season, week), False

    picks = (
        db.get_client()
        .table("picks_reveal_v")
        .select("*")
        .eq("season", season)
        .eq("week", week)
        .execute()
        .data
    )

    week_logs = (
        db.get_client()
        .table("week_log")
        .select("player_id, start_points")
        .eq("season", season)
        .eq("week", week)
        .execute()
        .data
    )
    start_by: dict[str, int] = {r["player_id"]: r["start_points"] for r in week_logs}

    profits: dict[str, int] = {}
    for pick in picks:
        pid = pick["player_id"]
        if pick.get("result") is not None:
            # Already settled — use actual net_profit
            profits[pid] = profits.get(pid, 0) + (pick["net_profit"] or 0)
        elif pick["game_status"] in ("in_progress", "final"):
            # Compute implied ATS result from current scores
            home_score = pick["home_score"] or 0
            away_score = pick["away_score"] or 0
            if pick["home_team"] == pick["favorite_team"]:
                fav_score, dog_score = home_score, away_score
            else:
                fav_score, dog_score = away_score, home_score
            diff = fav_score - dog_score
            spread = float(pick["spread"])
            if diff > spread:
                winner = "FAVORITE"
            elif diff < spread:
                winner = "UNDERDOG"
            else:
                winner = "push"
            if winner == "push":
                profit = 0
            elif pick["pick_side"] == winner:
                profit = pick["pick_amount"]
            else:
                profit = -pick["pick_amount"]
            profits[pid] = profits.get(pid, 0) + profit

    players = db.get_all_players(active_only=False)
    standings = []
    for player in players:
        if not player["is_active"]:
            continue
        pid = player["id"]
        start = start_by.get(pid, player.get("starting_points", 25_000))
        profit = profits.get(pid, 0)
        current = max(0, start + profit)
        standings.append({
            "player_id": pid,
            "name": player["name"],
            "paid_buyin": player["paid_buyin"],
            "is_active": True,
            "season": season,
            "week": week,
            "start_points": start,
            "current_points": current,
            "week_profit": profit,
            "is_eliminated": current <= 0,
        })

    standings.sort(key=lambda s: -s["current_points"])
    return standings, is_live


def _compute_prizes(standings: list[dict]) -> list[str]:
    """Compute dynamic prize ladder based on paid player count."""
    paid_count = sum(1 for s in standings if s.get("paid_buyin"))
    return compute_prize_ladder(max(paid_count, 1))


def _apply_prizes(standings: list[dict], prizes: list[str]) -> list[dict]:
    return apply_prize_ladder(standings, prizes)


# ── Leaderboard (home) ─────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    week = _current_week()
    standings, is_live = _compute_live_standings(SEASON, week)
    games = db.get_games(SEASON, week)
    banner = db.get_active_banner()
    prizes = _compute_prizes(standings)
    standings = _apply_prizes(standings, prizes)
    return templates.TemplateResponse("leaderboard.html", {
        "request": request,
        "standings": standings,
        "week": week,
        "season": SEASON,
        "games": games,
        "banner": banner,
        "is_live": is_live,
        "is_fragment": False,
    })


@router.get("/leaderboard-fragment", response_class=HTMLResponse)
async def leaderboard_fragment(request: Request):
    """htmx polling target — returns only the table rows (with live standings during games)."""
    week = _current_week()
    standings, is_live = _compute_live_standings(SEASON, week)
    prizes = _compute_prizes(standings)
    standings = _apply_prizes(standings, prizes)
    return templates.TemplateResponse("fragments/standings_rows.html", {
        "request": request,
        "standings": standings,
        "week": week,
        "is_live": is_live,
    })


# ── Week view (picks reveal + heatmap) ────────────────────────────────────

@router.get("/week/{week}", response_class=HTMLResponse)
async def week_view(request: Request, week: int):
    games = db.get_games(SEASON, week)
    game_totals = db.get_game_pick_totals(SEASON, week)
    banner = db.get_active_banner()
    now = datetime.now(timezone.utc)
    sat_noon = saturday_noon_et(games)
    picks_revealed = now >= sat_noon  # picks are public only after Saturday noon

    # game_pick_totals_v doesn't include home_score/away_score; merge from games.
    scores_by_id = {g["id"]: g for g in games}
    for gt in game_totals:
        game = scores_by_id.get(gt.get("game_id"))
        if game:
            gt["home_score"] = game.get("home_score", 0)
            gt["away_score"] = game.get("away_score", 0)

    players_picks: list[dict] = []
    if picks_revealed:
        picks = db.get_week_picks_reveal(SEASON, week)
        players_picks_map: dict[str, dict] = {}
        for pick in picks:
            pid = pick["player_id"]
            if pid not in players_picks_map:
                players_picks_map[pid] = {
                    "player_name": pick["player_name"],
                    "picks": [],
                }
            players_picks_map[pid]["picks"].append(pick)
        for pp in players_picks_map.values():
            pp["total_net_profit"] = sum(p["net_profit"] or 0 for p in pp["picks"])
        players_picks = sorted(players_picks_map.values(), key=lambda x: -x["total_net_profit"])

    return templates.TemplateResponse("week_view.html", {
        "request": request,
        "week": week,
        "current_week": _current_week(),
        "season": SEASON,
        "players_picks": players_picks,
        "game_totals": game_totals,
        "games": games,
        "banner": banner,
        "picks_revealed": picks_revealed,
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
    all_picks = db.get_player_picks_history(player_id, SEASON)

    # Determine which weeks have been publicly revealed (sat_noon has passed).
    # Current week's picks are hidden until Saturday noon ET.
    current_week = _current_week()
    now = datetime.now(timezone.utc)
    current_games = db.get_games(SEASON, current_week)
    sat_noon = saturday_noon_et(current_games)
    picks_revealed = now >= sat_noon

    # Group picks by week — exclude current week if not yet revealed
    picks_by_week: dict[int, list[dict]] = {}
    for pick in all_picks:
        if pick["week"] == current_week and not picks_revealed:
            continue
        picks_by_week.setdefault(pick["week"], []).append(pick)

    return templates.TemplateResponse("player_profile.html", {
        "request": request,
        "player": player,
        "week_log": week_log,
        "penalties": penalties,
        "picks_by_week": picks_by_week,
        "season": SEASON,
        "week": current_week,
        "banner": db.get_active_banner(),
    })


# ── Rules ──────────────────────────────────────────────────────────────────

@router.get("/rules", response_class=HTMLResponse)
async def rules_page(request: Request):
    try:
        raw_md = _RULES_PATH.read_text()
    except FileNotFoundError:
        raw_md = "Rules not found."
    return templates.TemplateResponse("rules.html", {
        "request": request,
        "raw_md": raw_md,
        "season": SEASON,
        "week": _current_week(),
        "banner": db.get_active_banner(),
    })
