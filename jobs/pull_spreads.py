"""
Wednesday 08:00 ET — fetch week's games + spreads from The Odds API,
write to Supabase games table, and send the Wed email to all players.

Usage: python jobs/pull_spreads.py --week 1 --season 2026 [--dry-run]
       (GitHub Actions sets --week and --season via env vars)
"""
import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from api.lib import db, email_send
from api.lib.spreads import fetch_week_games, fetch_espn_spreads, cross_check_spreads
from api.lib.timewall import compute_prize_ladder


def main(week: int, season: int, dry_run: bool = False):
    print(f"[pull_spreads] season={season} week={week} dry_run={dry_run}")

    # Fetch from Odds API
    games = fetch_week_games(season, week)
    print(f"  Fetched {len(games)} games from Odds API")

    if not games:
        print("  No games returned — check API key and season schedule")
        return

    # ESPN cross-check (non-fatal; warn if delta ≥ 1.5 points)
    try:
        espn_spreads = fetch_espn_spreads()
        warnings = cross_check_spreads(games, espn_spreads)
        if warnings:
            print(f"\n  ⚠️  SPREAD DISCREPANCIES (Odds API vs ESPN ≥ 1.5 pts):")
            for w in warnings:
                print(f"    {w}")
            admin_email = os.environ.get("ADMIN_EMAIL")
            if admin_email and not dry_run:
                body = "\n".join([
                    f"Week {week} spread discrepancies (Odds API vs ESPN consensus ≥ 1.5 pts):",
                    "",
                    *[f"  • {w}" for w in warnings],
                    "",
                    "Review and edit via /admin/games before Wednesday email goes out.",
                ])
                email_send.send_admin_alert(
                    to=admin_email,
                    subject=f"⚠️ Week {week} Spread Discrepancies — Action May Be Needed",
                    body=body,
                )
                print(f"  Alert emailed to {admin_email}")
        else:
            print(f"  ESPN cross-check OK ({len(espn_spreads)} games checked)")
    except Exception as exc:
        print(f"  ESPN cross-check failed (non-fatal): {exc}")

    if dry_run:
        for g in games:
            print(f"    {g['favorite_team']} -{g['spread']} vs {g['underdog_team']}  {g['kickoff_at'][:16]}")
        return

    # Upsert into games table
    for g in games:
        db.upsert_game(g)
        print(f"  Upserted: {g['favorite_team']} vs {g['underdog_team']}")

    # Seed week_log for all active players (start_points = last week's end_points)
    players = db.get_all_players()
    for player in players:
        # Find last week's end_points to use as this week's start
        prior = db.get_week_log(player["id"], season)
        if prior:
            last = max(prior, key=lambda r: r["week"])
            start = last["end_points"] if last["end_points"] is not None else last["start_points"]
        else:
            start = 25_000
        db.upsert_week_log(player["id"], season, week, start_points=start)

    # Last week's standings for the email
    standings = db.get_standings(season, week - 1) if week > 1 else []
    paid_count = sum(1 for p in players if p.get("paid_buyin"))
    prizes = compute_prize_ladder(max(paid_count, 1))

    # Send Wednesday email
    email_send.send_weekly_spreads(players, week, season, games, standings, prizes=prizes)
    print(f"  Emailed {len(players)} players")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--season", type=int, default=int(os.environ.get("CURRENT_SEASON", 2026)))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(args.week, args.season, args.dry_run)
