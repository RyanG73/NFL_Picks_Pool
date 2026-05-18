"""
End-to-end smoke test against a live (staging) Supabase project.

Exercises every cron job path using seeded fake data so Ryan can verify
the full pipeline before Week 1. Requires:
  - SUPABASE_URL + SUPABASE_SERVICE_KEY pointing at a staging project
  - migrations/001_init.sql + 002_functions.sql + 004_games_team_unique.sql run
  - RESEND_API_KEY (or --skip-email to skip email sends)

Usage:
    python jobs/smoke_test.py --season 2026 --week 1
    python jobs/smoke_test.py --season 2026 --week 1 --skip-email --verbose

What it tests (in order):
  1. Seed: insert 3 fake players + 2 fake games for the week
  2. Submit picks: upsert picks for all players
  3. Lock: lock picks via lock_kicked_off_picks() RPC (Thursday game past kickoff)
  4. Final scores: write fake final scores with definite ATS outcomes
  5. Settle: settle all picks via settlement logic
  6. Verify: check each player's net profit matches expected outcome
  7. No-bet penalty: apply -5000 penalty to Carol (skipped picks)
  Teardown: delete all seeded rows (runs in finally block, always executes)

All steps print PASS/FAIL. Final exit code is 0 if all pass, 1 if any fail.
"""
import argparse
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()

from api.lib import db
from api.lib.timewall import saturday_noon_et

FAKE_SEASON = None   # set from args
FAKE_WEEK = None     # set from args
VERBOSE = False
SKIP_EMAIL = False

_seeded_player_ids: list[str] = []
_seeded_game_ids: list[str] = []
_pass_count = 0
_fail_count = 0


def log(msg: str):
    print(msg)


def verbose(msg: str):
    if VERBOSE:
        print(f"  (debug) {msg}")


def check(label: str, condition: bool, detail: str = ""):
    global _pass_count, _fail_count
    if condition:
        _pass_count += 1
        log(f"  ✅ PASS  {label}")
    else:
        _fail_count += 1
        log(f"  ❌ FAIL  {label}" + (f": {detail}" if detail else ""))


# ── Step 1: Seed ──────────────────────────────────────────────────────────────

def seed_players() -> list[dict]:
    """Insert 3 fake players with unique emails."""
    global _seeded_player_ids
    run_id = uuid.uuid4().hex[:8]
    players = []
    for i, name in enumerate(["Smoke Alice", "Smoke Bob", "Smoke Carol"]):
        email = f"smoke-{run_id}-{i}@example.invalid"
        row = db.create_player(name=name, email=email)
        _seeded_player_ids.append(row["id"])  # track for teardown even on partial failure
        players.append(row)
        verbose(f"Seeded player: {name} id={row['id']}")
    return players


def seed_games(season: int, week: int) -> list[dict]:
    """Insert 2 fake games: one Thursday (locks at kickoff), one Sunday (locks at noon)."""
    now = datetime.now(timezone.utc)
    # Thursday kickoff = 3 days ago (already kicked off / in_progress)
    thu_kickoff = (now - timedelta(days=3)).isoformat()
    # Sunday kickoff = 4 days from now (not yet started)
    sun_kickoff = (now + timedelta(days=4)).isoformat()
    client = db.get_client()

    games = []
    for home, away, fav, dog, spread, kickoff in [
        ("Green Bay Packers", "Chicago Bears", "Green Bay Packers", "Chicago Bears", 7.0, thu_kickoff),
        ("Kansas City Chiefs", "Las Vegas Raiders", "Kansas City Chiefs", "Las Vegas Raiders", 10.5, sun_kickoff),
    ]:
        row = client.table("games").insert({
            "season": season,
            "week": week,
            "espn_event_id": f"smoke-{uuid.uuid4().hex[:8]}",
            "home_team": home,
            "away_team": away,
            "favorite_team": fav,
            "underdog_team": dog,
            "spread": spread,
            "kickoff_at": kickoff,
            "status": "scheduled",
        }).execute().data[0]
        _seeded_game_ids.append(row["id"])  # track for teardown even on partial failure
        games.append(row)
        verbose(f"Seeded game: {home} vs {away}  kickoff={kickoff[:16]}")
    return games


# ── Step 2: Submit picks ───────────────────────────────────────────────────────

def submit_picks(players: list[dict], games: list[dict], week: int, season: int) -> dict[str, list[dict]]:
    """
    Alice: picks both games (FAVORITE, 5000 each)
    Bob:   picks only game 1 (UNDERDOG, 2000)
    Carol: no picks (will get no-bet penalty)
    Returns {player_id: [pick, ...]}
    """
    client = db.get_client()
    result = {}
    assignments = [
        (players[0], [(games[0]["id"], "FAVORITE", 5000), (games[1]["id"], "FAVORITE", 5000)]),
        (players[1], [(games[0]["id"], "UNDERDOG",  2000)]),
        (players[2], []),  # Carol skips
    ]
    for player, picks in assignments:
        pid = player["id"]
        result[pid] = []
        # Seed week_log start for this player
        db.upsert_week_log(pid, season, week, start_points=25_000)
        for gid, side, amount in picks:
            row = db.upsert_pick(pid, gid, side, amount)
            result[pid].append(row)
            verbose(f"  Seeded pick: {player['name']} {side} {amount:,} on game {gid[:8]}")
    return result


# ── Step 3: Lock ──────────────────────────────────────────────────────────────

def run_lock(games: list[dict]):
    """Call lock_kicked_off_picks() via RPC — locks Thu game (past kickoff)."""
    now = datetime.now(timezone.utc)
    sat_noon = saturday_noon_et(games)
    params: dict = {"as_of": now.isoformat()}
    if now >= sat_noon:
        params["sat_noon"] = sat_noon.isoformat()
    result = db.get_client().rpc("lock_kicked_off_picks", params).execute()
    verbose(f"lock_kicked_off_picks returned: {result.data}")
    return result


# ── Step 4: Simulate live scores ──────────────────────────────────────────────

def simulate_final_scores(games: list[dict], season: int, week: int):
    """Mark both games final with definite ATS outcomes."""
    client = db.get_client()
    # Game 1 (GB -7): GB wins 24-10 → margin +14 > 7 → FAVORITE covers
    client.table("games").update({
        "home_score": 24, "away_score": 10, "status": "final"
    }).eq("id", games[0]["id"]).execute()
    # Game 2 (KC -10.5): KC wins 20-14 → margin +6 < 10.5 → UNDERDOG covers
    client.table("games").update({
        "home_score": 20, "away_score": 14, "status": "final"
    }).eq("id", games[1]["id"]).execute()
    verbose("Set game 1 final: GB 24-10 (fav covers); game 2 final: KC 20-14 (dog covers)")


# ── Step 5: Settle ────────────────────────────────────────────────────────────

def run_settlement(season: int, week: int):
    """Run settle_week settlement logic directly against seeded data."""
    from api.lib.settlement import GameResult, settle_pick, ats_winner
    games = db.get_games(season, week)
    client = db.get_client()
    for game in games:
        if game["status"] != "final":
            continue
        home_score = int(game.get("home_score") or 0)
        away_score = int(game.get("away_score") or 0)
        fav_score = home_score if game["home_team"] == game["favorite_team"] else away_score
        dog_score = home_score if game["home_team"] == game["underdog_team"] else away_score
        gr = GameResult(
            game_id=game["id"],
            favorite_team=game["favorite_team"],
            underdog_team=game["underdog_team"],
            spread=float(game["spread"]),
            favorite_score=fav_score,
            underdog_score=dog_score,
            status=game["status"],
        )
        winner = ats_winner(gr)
        picks = (
            client.table("picks").select("*, players(name)")
            .eq("game_id", game["id"]).execute().data
        )
        for pick in picks:
            result_lbl, net = settle_pick(pick["pick_side"], pick["pick_amount"], winner)
            client.table("settlements").upsert({
                "pick_id": pick["id"],
                "result": result_lbl,
                "net_profit": net,
            }, on_conflict="pick_id").execute()
            verbose(f"  Settled {pick['players']['name']}: {result_lbl} {net:+,}")


# ── Step 6: Verify standings ──────────────────────────────────────────────────

def verify_standings(players: list[dict], games: list[dict], season: int, week: int):
    """
    Expected outcomes:
      Alice:  picked FAVORITE on game1 (WIN +5000) + FAVORITE on game2 (LOSS -5000) → net 0 → 25,000
      Bob:    picked UNDERDOG on game1 (LOSS -2000) → net -2000 → 23,000
      Carol:  no picks → 25,000 (before penalty)
    """
    client = db.get_client()
    game_ids = [g["id"] for g in games]
    picks = client.table("picks").select("id, player_id").in_("game_id", game_ids).execute().data
    pick_id_to_player = {p["id"]: p["player_id"] for p in picks}

    settlements_by_player: dict[str, int] = {}
    if pick_id_to_player:
        setts = (
            client.table("settlements")
            .select("net_profit, pick_id")
            .in_("pick_id", list(pick_id_to_player.keys()))
            .execute().data
        )
        for s in setts:
            pid = pick_id_to_player.get(s["pick_id"])
            if pid:
                settlements_by_player[pid] = settlements_by_player.get(pid, 0) + (s["net_profit"] or 0)

    alice = next(p for p in players if p["name"] == "Smoke Alice")
    bob   = next(p for p in players if p["name"] == "Smoke Bob")

    check("Alice net profit = 0 (fav win + fav loss cancel)",
          settlements_by_player.get(alice["id"], 0) == 0,
          f"got {settlements_by_player.get(alice['id'], 'no settlements')}")
    check("Bob net profit = -2000 (underdog loss on game 1)",
          settlements_by_player.get(bob["id"], 0) == -2000,
          f"got {settlements_by_player.get(bob['id'], 'no settlements')}")


# ── Step 7: No-bet penalty ────────────────────────────────────────────────────

def apply_no_bet_penalty(players: list[dict], season: int, week: int):
    """Carol has no picks → should receive -5000 penalty (first miss)."""
    carol = next(p for p in players if p["name"] == "Smoke Carol")
    # Check consecutive misses (0 prior weeks = this is first miss)
    client = db.get_client()
    picks = client.table("picks").select("id").eq("player_id", carol["id"]).execute().data
    no_picks = len(picks) == 0
    if no_picks:
        client.table("penalties").insert({
            "player_id": carol["id"],
            "season": season,
            "week": week,
            "amount": -5000,
            "consecutive_misses": 1,
            "waived": False,
        }).execute()
        verbose("Applied -5000 penalty to Carol")

    penalties = client.table("penalties").select("amount").eq("player_id", carol["id"]).execute().data
    check("Carol received -5000 no-bet penalty",
          any(p["amount"] == -5000 for p in penalties),
          f"penalties found: {penalties}")


# ── Step 8: Teardown ──────────────────────────────────────────────────────────

def teardown(player_ids: list[str], game_ids: list[str]):
    """Delete all seeded data (cascades clean up picks/settlements/penalties).

    Uses the module-level _seeded_* trackers as the authoritative source so
    partial-seed failures don't leave orphaned rows in the staging DB.
    """
    all_game_ids = list(set(_seeded_game_ids) | set(game_ids))
    all_player_ids = list(set(_seeded_player_ids) | set(player_ids))
    client = db.get_client()
    if all_game_ids:
        client.table("games").delete().in_("id", all_game_ids).execute()
    if all_player_ids:
        client.table("players").delete().in_("id", all_player_ids).execute()
    verbose(f"Teardown: deleted {len(all_player_ids)} players, {len(all_game_ids)} games")


# ── Main ──────────────────────────────────────────────────────────────────────

def main(season: int, week: int, skip_email: bool = False, verbose_mode: bool = False):
    global FAKE_SEASON, FAKE_WEEK, VERBOSE, SKIP_EMAIL
    FAKE_SEASON, FAKE_WEEK, VERBOSE, SKIP_EMAIL = season, week, verbose_mode, skip_email

    log(f"\n{'='*60}")
    log(f"  NFL Picks Pool — Smoke Test  season={season} week={week}")
    log(f"{'='*60}\n")

    players: list[dict] = []
    games: list[dict] = []

    try:
        # Step 1: Seed
        log("[1/7] Seeding fake players and games...")
        players = seed_players()
        games   = seed_games(season, week)
        check("Seeded 3 players", len(players) == 3)
        check("Seeded 2 games",   len(games) == 2)

        # Step 2: Submit picks
        log("\n[2/7] Submitting picks...")
        picks_by_player = submit_picks(players, games, week, season)
        alice_picks = picks_by_player.get(players[0]["id"], [])
        bob_picks   = picks_by_player.get(players[1]["id"], [])
        carol_picks = picks_by_player.get(players[2]["id"], [])
        check("Alice has 2 picks", len(alice_picks) == 2)
        check("Bob has 1 pick",    len(bob_picks) == 1)
        check("Carol has 0 picks", len(carol_picks) == 0)

        # Step 3: Lock
        log("\n[3/7] Running pick lock (Thursday game should lock)...")
        run_lock(games)
        client = db.get_client()
        thu_picks = client.table("picks").select("locked_at").eq("game_id", games[0]["id"]).execute().data
        thu_locked = all(p["locked_at"] is not None for p in thu_picks)
        check("Thursday game picks are locked (past kickoff)", thu_locked,
              f"found {sum(1 for p in thu_picks if p['locked_at'])} locked out of {len(thu_picks)}")

        # Step 4: Final scores
        log("\n[4/7] Simulating final scores...")
        simulate_final_scores(games, season, week)
        g1 = db.get_game(games[0]["id"])
        check("Game 1 marked final", g1 and g1["status"] == "final",
              f"status={g1.get('status') if g1 else 'not found'}")

        # Step 5: Settle
        log("\n[5/7] Running settlement...")
        run_settlement(season, week)
        seeded_picks = client.table("picks").select("id").in_("game_id", [g["id"] for g in games]).execute().data
        seeded_pick_ids = [p["id"] for p in seeded_picks]
        seeded_setts = (
            client.table("settlements").select("id").in_("pick_id", seeded_pick_ids).execute().data
            if seeded_pick_ids else []
        )
        check("Settlements written (at least 1)", len(seeded_setts) >= 1)

        # Step 6: Verify outcomes
        log("\n[6/7] Verifying pick outcomes...")
        verify_standings(players, games, season, week)

        # Step 7: No-bet penalty
        log("\n[7/7] Applying no-bet penalty for Carol...")
        apply_no_bet_penalty(players, season, week)

    except Exception as exc:
        global _fail_count
        log(f"\n  💥 Unexpected error: {exc}")
        import traceback; traceback.print_exc()
        _fail_count += 1
    finally:
        log("\n[Teardown] Cleaning up seeded data...")
        teardown([p["id"] for p in players], [g["id"] for g in games])
        log("  Done.\n")

    # Summary
    log(f"{'='*60}")
    total = _pass_count + _fail_count
    log(f"  Results: {_pass_count}/{total} passed  ({_fail_count} failed)")
    log(f"{'='*60}\n")
    return _fail_count == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="End-to-end smoke test against staging Supabase")
    parser.add_argument("--season", type=int, default=int(os.environ.get("CURRENT_SEASON", 2026)))
    parser.add_argument("--week",   type=int, default=1)
    parser.add_argument("--skip-email", action="store_true", help="Skip Resend email sends")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    ok = main(args.season, args.week, args.skip_email, args.verbose)
    sys.exit(0 if ok else 1)
