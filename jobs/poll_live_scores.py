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
from datetime import datetime, timezone
from api.lib import db
from api.lib.timewall import saturday_noon_et

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"


def fetch_espn_scores() -> dict[tuple[str, str], dict]:
    """
    Return dict keyed by (home_team_display_name, away_team_display_name).

    Does NOT key by espn_event_id — games inserted before the 2026 season may
    carry Odds API IDs in that column. Team names are stable across all sources.
    The ESPN event ID is stored in the value dict so we can write it back to the
    DB on first match.
    """
    resp = httpx.get(ESPN_SCOREBOARD, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    results = {}
    for event in data.get("events", []):
        comp = event.get("competitions", [{}])[0]
        competitors = {c["homeAway"]: c for c in comp.get("competitors", [])}
        home = competitors.get("home", {})
        away = competitors.get("away", {})
        home_name = home.get("team", {}).get("displayName", "")
        away_name = away.get("team", {}).get("displayName", "")
        if not home_name or not away_name:
            continue
        status_type = event.get("status", {}).get("type", {})
        state = status_type.get("state", "pre")  # pre | in | post
        results[(home_name, away_name)] = {
            "home_score": int(home.get("score", 0) or 0),
            "away_score": int(away.get("score", 0) or 0),
            "status": {
                "pre": "scheduled",
                "in": "in_progress",
                "post": "final",
            }.get(state, "scheduled"),
        }
    return results


def update_games(season: int, week: int, games: list[dict], scores: dict[tuple[str, str], dict], dry_run: bool):
    for game in games:
        if game["status"] in ("voided", "final", "postponed"):
            continue
        key = (game["home_team"], game["away_team"])
        score = scores.get(key)
        if not score:
            continue
        if (
            game["home_score"] == score["home_score"]
            and game["away_score"] == score["away_score"]
            and game["status"] == score["status"]
        ):
            continue
        print(f"  Update {game['home_team']} {score['home_score']}–{score['away_score']} {game['away_team']} [{score['status']}]")
        if not dry_run:
            db.update_game(game["id"],
                           home_score=score["home_score"],
                           away_score=score["away_score"],
                           status=score["status"])


def main(season: int, week: int | None = None, dry_run: bool = False, once: bool = False):
    if week is None:
        week = db.detect_current_week(season)
        print(f"[poll_live_scores] auto-detected week={week} season={season}")
    else:
        print(f"[poll_live_scores] season={season} week={week}")
    while True:
        try:
            games = db.get_games(season, week)
            now = datetime.now(timezone.utc)
            sat_noon = saturday_noon_et(games)
            params: dict = {"as_of": now.isoformat()}
            if now >= sat_noon:
                params["sat_noon"] = sat_noon.isoformat()
            if not dry_run:
                locked = db.get_client().rpc("lock_kicked_off_picks", params).execute()
                if locked.data:
                    print(f"  Locked {locked.data} pick(s)")

            scores = fetch_espn_scores()
            update_games(season, week, games, scores, dry_run)
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
