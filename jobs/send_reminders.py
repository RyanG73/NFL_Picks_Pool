"""
Friday 20:00 ET — email players who haven't submitted picks yet.

Usage: python jobs/send_reminders.py --week 1 --season 2026 [--dry-run]
"""
import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from api.lib import db, email_send


def main(week: int, season: int, dry_run: bool = False):
    print(f"[send_reminders] season={season} week={week} dry_run={dry_run}")

    players = db.get_all_players()

    # Get all players who have submitted at least one pick this week
    from api.lib.db import get_client
    picks_this_week = (
        get_client()
        .table("picks")
        .select("player_id, game_id, games(season, week)")
        .eq("games.season", season)
        .eq("games.week", week)
        .execute()
        .data
    )
    submitted_ids = {p["player_id"] for p in picks_this_week}

    missing = [p for p in players if p["id"] not in submitted_ids and p["is_active"]]
    print(f"  {len(missing)} players haven't picked yet")

    for player in missing:
        print(f"  → Reminding {player['name']} ({player['email']})")
        if not dry_run:
            email_send.send_reminder(player, week)

    if dry_run:
        print("  (dry-run: no emails sent)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--season", type=int, default=int(os.environ.get("CURRENT_SEASON", 2026)))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(args.week, args.season, args.dry_run)
