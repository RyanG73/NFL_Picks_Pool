"""
Every 60 seconds during game windows (Thu/Sat/Sun/Mon) — poll ESPN's
public scoreboard API and update games.home_score / away_score / status.

Game windows:
  Thursday:  18:00–23:59 ET
  Saturday:  12:00–23:59 ET  (playoff weeks only)
  Sunday:    13:00–23:59 ET
  Monday:    20:00–23:59 ET

Designed to run as a short-lived process from GitHub Actions on a
1-minute schedule, or as an infinite loop from a local machine.

Usage: python jobs/poll_live_scores.py --season 2026 [--week 1] [--dry-run] [--once]
       Omit --week to auto-detect the current active week from the DB.
"""
import argparse
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

import httpx
from api.lib import db

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"


def detect_current_week(season: int) -> int:
    """Return the lowest week with scheduled or in-progress games, else the latest week."""
    client = db.get_client()
    res = (
        client.table("games")
        .select("week")
        .eq("season", season)
        .in_("status", ["scheduled", "in_progress"])
        .order("week")
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]["week"]
    # Fall back to the max week with any games (season over edge case)
    res2 = client.table("games").select("week").eq("season", season).order("week", desc=True).limit(1).execute()
    return res2.data[0]["week"] if res2.data else 1


def fetch_espn_scores() -> dict[str, dict]:
    """Return dict of {espn_event_id: {home_score, away_score, status}}."""
    resp = httpx.get(ESPN_SCOREBOARD, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    results = {}
    for event in data.get("events", []):
        eid = event["id"]
        comp = event.get("competitions", [{}])[0]
        competitors = {c["homeAway"]: c for c in comp.get("competitors", [])}
        home = competitors.get("home", {})
        away = competitors.get("away", {})
        status_type = event.get("status", {}).get("type", {})
        state = status_type.get("state", "pre")  # pre | in | post
        results[eid] = {
            "home_score": int(home.get("score", 0) or 0),
            "away_score": int(away.get("score", 0) or 0),
            "status": {
                "pre": "scheduled",
                "in": "in_progress",
                "post": "final",
            }.get(state, "scheduled"),
        }
    return results


def update_games(season: int, week: int, scores: dict, dry_run: bool):
    games = db.get_games(season, week)
    for game in games:
        if game["status"] in ("voided", "final"):
            continue
        eid = game.get("espn_event_id")
        if not eid or eid not in scores:
            continue
        score = scores[eid]
        if (
            game["home_score"] == score["home_score"]
            and game["away_score"] == score["away_score"]
            and game["status"] == score["status"]
        ):
            continue  # No change
        print(f"  Update {game['home_team']} {score['home_score']}–{score['away_score']} {game['away_team']} [{score['status']}]")
        if not dry_run:
            db.update_game(game["id"], **score)


def main(season: int, week: int | None = None, dry_run: bool = False, once: bool = False):
    if week is None:
        week = detect_current_week(season)
        print(f"[poll_live_scores] auto-detected week={week} season={season}")
    else:
        print(f"[poll_live_scores] season={season} week={week}")
    while True:
        try:
            scores = fetch_espn_scores()
            update_games(season, week, scores, dry_run)
        except Exception as exc:
            print(f"  Error: {exc}")
        if once:
            break
        time.sleep(60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", type=int, default=None, help="Week number (auto-detects from DB if omitted)")
    parser.add_argument("--season", type=int, default=int(os.environ.get("CURRENT_SEASON", 2026)))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true", help="Run once then exit (for cron)")
    args = parser.parse_args()
    main(args.season, args.week, args.dry_run, args.once)
