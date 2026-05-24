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

    # Get picks for this week: query game IDs first, then filter picks by game_id.
    # (Filtering on embedded relationship columns in PostgREST only filters the
    # embedded resource, not the parent row — using .in_() on game_id is correct.)
    games_list = db.get_games(season, week)
    games_this_week = {g["id"] for g in games_list}
    if not games_this_week:
        print(f"  No games found for season={season} week={week} — skipping reminders")
        return
    # Skip if all games are final/voided (offseason guard: avoids re-reminding after season ends)
    if all(g["status"] in ("final", "voided") for g in games_list):
        print(f"  Week {week} games are all final/voided — skipping reminders")
        return

    from api.lib.db import get_client
    picks_this_week = (
        get_client()
        .table("picks")
        .select("player_id")
        .in_("game_id", list(games_this_week))
        .execute()
        .data
    )
    submitted_ids = {p["player_id"] for p in picks_this_week}

    # Load week balances so we can skip eliminated players (0 pts can't bet anyway)
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

    missing = [
        p for p in players
        if p["id"] not in submitted_ids
        and p["is_active"]
        and start_by_player.get(p["id"], 25_000) > 0
    ]
    print(f"  {len(missing)} players haven't picked yet (eliminated players skipped)")

    errors: list[tuple[str, str]] = []
    for player in missing:
        print(f"  → Reminding {player['name']} ({player['email']})")
        if not dry_run:
            try:
                email_send.send_reminder(player, week, season)
            except Exception as exc:
                errors.append((player["email"], str(exc)))

    if errors:
        print(f"  [send_reminders] {len(errors)} email error(s):")
        for addr, err in errors:
            print(f"    {addr}: {err}")
    if dry_run:
        print("  (dry-run: no emails sent)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--season", type=int, default=int(os.environ.get("CURRENT_SEASON", 2026)))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(args.week, args.season, args.dry_run)
