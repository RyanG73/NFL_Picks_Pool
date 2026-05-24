"""
Saturday ~1pm ET — apply no-bet penalties for players who haven't picked,
then send the 'picks are live' email to everyone.

Note: per-game kickoff locking happens continuously via the web app.
This job handles the "missed the whole week" penalty and the reveal email.

Usage: python jobs/lock_and_reveal.py --week 1 --season 2026 [--dry-run]
"""
import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from api.lib import db, email_send
from api.lib.settlement import compute_penalty_amount


def main(week: int, season: int, dry_run: bool = False):
    print(f"[lock_and_reveal] season={season} week={week} dry_run={dry_run}")

    players = db.get_all_players()

    from api.lib.db import get_client
    games_list = db.get_games(season, week)
    games_this_week = {g["id"] for g in games_list}
    if not games_this_week:
        print(f"  No games found for week {week} season {season} — nothing to do.")
        return
    # Skip if the week has already fully settled (offseason re-run guard)
    if all(g["status"] in ("final", "voided") for g in games_list):
        print(f"  Week {week} games are all final/voided — reveal already sent. Skipping.")
        return

    all_picks = (
        get_client()
        .table("picks")
        .select("player_id, game_id")
        .in_("game_id", list(games_this_week))
        .execute()
        .data
    )
    submitted_ids = {p["player_id"] for p in all_picks}

    # Load week_log to check starting balances (eliminated players skip penalty)
    week_log_rows = (
        get_client()
        .table("week_log")
        .select("player_id, start_points")
        .eq("season", season)
        .eq("week", week)
        .execute()
        .data
    )
    start_by_player = {r["player_id"]: r["start_points"] for r in week_log_rows}

    for player in players:
        if not player["is_active"]:
            continue
        if player["id"] in submitted_ids:
            continue
        # Skip eliminated players — can't go below 0
        if start_by_player.get(player["id"], 25_000) <= 0:
            print(f"  Skipping {player['name']} (eliminated — 0 points)")
            continue

        # This player missed the week. Get consecutive miss count.
        prior_penalties = db.get_penalties(player["id"], season)
        active_penalties = [p for p in prior_penalties if not p["waived"]]
        # Count consecutive: how many of the last N weeks before this one had penalties?
        weeks_with_penalties = {p["week"] for p in active_penalties}
        consecutive = 1
        for prior_week in range(week - 1, 0, -1):
            if prior_week in weeks_with_penalties:
                consecutive += 1
            else:
                break

        amount = compute_penalty_amount(consecutive)
        print(f"  Penalty: {player['name']} week={week} consecutive={consecutive} amount={amount:,}")

        if not dry_run:
            db.insert_penalty(player["id"], season, week, amount, consecutive)
            db.log_action("auto_penalty", {
                "player_id": player["id"],
                "week": week,
                "consecutive": consecutive,
                "amount": amount,
            })

    # Send picks reveal email
    if not dry_run:
        try:
            email_send.send_picks_reveal(players, week, season)
            print(f"  Picks reveal email sent to {len(players)} players")
        except Exception as exc:
            print(f"  ⚠  send_picks_reveal failed (penalties were written): {exc}")
    else:
        print("  (dry-run: no penalties written, no emails sent)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--season", type=int, default=int(os.environ.get("CURRENT_SEASON", 2026)))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(args.week, args.season, args.dry_run)
