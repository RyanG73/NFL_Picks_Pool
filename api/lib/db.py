import os
from supabase import create_client, Client
from functools import lru_cache

@lru_cache(maxsize=1)
def get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


# ── Players ────────────────────────────────────────────────────────────────

def get_player_by_token(token: str) -> dict | None:
    res = get_client().table("players").select("*").eq("magic_token", token).single().execute()
    return res.data

def get_all_players(active_only: bool = True) -> list[dict]:
    q = get_client().table("players").select("*")
    if active_only:
        q = q.eq("is_active", True)
    return q.order("name").execute().data

def create_player(name: str, email: str) -> dict:
    res = get_client().table("players").insert({"name": name, "email": email}).execute()
    return res.data[0]

def update_player(player_id: str, **fields) -> dict:
    res = get_client().table("players").update(fields).eq("id", player_id).execute()
    return res.data[0]


# ── Games ──────────────────────────────────────────────────────────────────

def get_games(season: int, week: int) -> list[dict]:
    return (
        get_client()
        .table("games")
        .select("*")
        .eq("season", season)
        .eq("week", week)
        .order("kickoff_at")
        .execute()
        .data
    )

def get_game(game_id: str) -> dict | None:
    res = get_client().table("games").select("*").eq("id", game_id).single().execute()
    return res.data

def upsert_game(game: dict) -> dict:
    res = get_client().table("games").upsert(game, on_conflict="season,week,espn_event_id").execute()
    return res.data[0]

def update_game(game_id: str, **fields) -> dict:
    res = get_client().table("games").update(fields).eq("id", game_id).execute()
    return res.data[0]


# ── Picks ──────────────────────────────────────────────────────────────────

def get_player_picks(player_id: str, season: int, week: int) -> list[dict]:
    return (
        get_client()
        .table("picks")
        .select("*, games(*)")
        .eq("player_id", player_id)
        .eq("games.season", season)
        .eq("games.week", week)
        .execute()
        .data
    )

def upsert_pick(player_id: str, game_id: str, pick_side: str, pick_amount: int) -> dict:
    res = get_client().table("picks").upsert(
        {
            "player_id": player_id,
            "game_id": game_id,
            "pick_side": pick_side,
            "pick_amount": pick_amount,
        },
        on_conflict="player_id,game_id",
    ).execute()
    return res.data[0]

def delete_pick(player_id: str, game_id: str) -> None:
    get_client().table("picks").delete().eq("player_id", player_id).eq("game_id", game_id).execute()

def get_week_picks_reveal(season: int, week: int) -> list[dict]:
    return (
        get_client()
        .table("picks_reveal_v")
        .select("*")
        .eq("season", season)
        .eq("week", week)
        .order("player_name")
        .execute()
        .data
    )

def get_game_pick_totals(season: int, week: int) -> list[dict]:
    return (
        get_client()
        .table("game_pick_totals_v")
        .select("*")
        .eq("season", season)
        .eq("week", week)
        .order("kickoff_at")
        .execute()
        .data
    )


# ── Standings ──────────────────────────────────────────────────────────────

def get_standings(season: int, week: int) -> list[dict]:
    return (
        get_client()
        .table("standings_v")
        .select("*")
        .eq("season", season)
        .eq("week", week)
        .order("current_points", desc=True)
        .execute()
        .data
    )

def get_week_log(player_id: str, season: int) -> list[dict]:
    return (
        get_client()
        .table("week_log")
        .select("*")
        .eq("player_id", player_id)
        .eq("season", season)
        .order("week")
        .execute()
        .data
    )

def upsert_week_log(player_id: str, season: int, week: int, start_points: int, end_points: int | None = None):
    get_client().table("week_log").upsert(
        {"player_id": player_id, "season": season, "week": week,
         "start_points": start_points, "end_points": end_points},
        on_conflict="player_id,season,week",
    ).execute()


# ── Penalties ──────────────────────────────────────────────────────────────

def insert_penalty(player_id: str, season: int, week: int, amount: int, consecutive: int) -> dict:
    res = get_client().table("penalties").insert({
        "player_id": player_id, "season": season, "week": week,
        "amount": amount, "consecutive_misses": consecutive,
    }).execute()
    return res.data[0]

def waive_penalty(penalty_id: str, reason: str) -> dict:
    res = get_client().table("penalties").update(
        {"waived": True, "waived_reason": reason}
    ).eq("id", penalty_id).execute()
    return res.data[0]

def get_penalties(player_id: str, season: int) -> list[dict]:
    return (
        get_client()
        .table("penalties")
        .select("*")
        .eq("player_id", player_id)
        .eq("season", season)
        .order("week")
        .execute()
        .data
    )


# ── Settlements ────────────────────────────────────────────────────────────

def insert_settlement(pick_id: str, result: str, net_profit: int) -> dict:
    res = get_client().table("settlements").upsert(
        {"pick_id": pick_id, "result": result, "net_profit": net_profit},
        on_conflict="pick_id",
    ).execute()
    return res.data[0]


# ── Audit log ──────────────────────────────────────────────────────────────

def log_action(action: str, payload: dict) -> None:
    get_client().table("admin_audit_log").insert({"action": action, "payload": payload}).execute()


# ── Broadcasts ─────────────────────────────────────────────────────────────

def get_active_banner() -> dict | None:
    res = (
        get_client()
        .table("broadcasts")
        .select("*")
        .not_.is_("banner_text", "null")
        .not_.is_("sent_at", "null")
        .order("sent_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None
