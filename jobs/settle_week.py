"""
Tuesday 09:00 ET — pull authoritative final scores from nfl-data-py,
settle all picks, apply escalating no-bet penalties, advance week_log.

Ported from Historical_Code/tuesday.R (lines 35–184).
Idempotent: safe to re-run; will skip already-settled picks.

Usage: python jobs/settle_week.py --week 1 --season 2026 [--dry-run]
"""
import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

import nfl_data_py as nfl
from api.lib import db
from api.lib.settlement import GameResult, ats_winner, settle_pick, compute_player_week_end_points


def load_final_scores(season: int, week: int) -> dict[str, dict]:
    """Pull authoritative scores from nfl-data-py keyed by ESPN game ID."""
    schedules = nfl.import_schedules([season])
    week_games = schedules[schedules["week"] == week]
    results = {}
    for _, row in week_games.iterrows():
        results[str(row.get("espn_id", ""))] = {
            "home_team": row["home_team"],
            "away_team": row["away_team"],
            "home_score": int(row.get("home_score", 0) or 0),
            "away_score": int(row.get("away_score", 0) or 0),
        }
    return results


def main(week: int, season: int, dry_run: bool = False):
    print(f"[settle_week] season={season} week={week} dry_run={dry_run}")

    final_scores = load_final_scores(season, week)
    print(f"  Loaded {len(final_scores)} final scores from nfl-data-py")

    games = db.get_games(season, week)
    players = db.get_all_players()

    # ── Settle each game ────────────────────────────────────────────────────
    for game in games:
        eid = game.get("espn_event_id", "")
        score = final_scores.get(eid)
        if not score:
            print(f"  ⚠ No final score found for {game['favorite_team']} vs {game['underdog_team']} (ESPN ID: {eid})")
            continue

        gr = GameResult(
            game_id=game["id"],
            favorite_team=game["favorite_team"],
            underdog_team=game["underdog_team"],
            spread=float(game["spread"]),
            favorite_score=score["home_score"] if game["home_team"] == game["favorite_team"] else score["away_score"],
            underdog_score=score["home_score"] if game["home_team"] == game["underdog_team"] else score["away_score"],
            status=game["status"],
        )
        winner = ats_winner(gr)
        print(f"  {gr.favorite_team} -{gr.spread} vs {gr.underdog_team} → ATS winner: {winner}")

        if not dry_run:
            db.update_game(game["id"],
                           home_score=score["home_score"],
                           away_score=score["away_score"],
                           status="final")

        # Settle each pick for this game
        from api.lib.db import get_client
        picks = (
            get_client()
            .table("picks")
            .select("*")
            .eq("game_id", game["id"])
            .execute()
            .data
        )
        for pick in picks:
            # Skip if already settled
            existing = (
                get_client()
                .table("settlements")
                .select("id")
                .eq("pick_id", pick["id"])
                .execute()
                .data
            )
            if existing:
                continue
            result_label, net_profit = settle_pick(pick["pick_side"], pick["pick_amount"], winner)
            print(f"    {pick['player_id'][:8]}… {pick['pick_side']} {pick['pick_amount']:,} → {result_label} {net_profit:+,}")
            if not dry_run:
                db.insert_settlement(pick["id"], result_label, net_profit)

    # ── Advance week_log ────────────────────────────────────────────────────
    print("  Computing end-of-week balances…")
    for player in players:
        week_log = db.get_week_log(player["id"], season)
        current = next((r for r in week_log if r["week"] == week), None)
        if not current:
            print(f"  ⚠ No week_log row for {player['name']} week {week}")
            continue

        # Gather all settlements and penalties for this week
        from api.lib.db import get_client
        settlements_raw = (
            get_client()
            .table("settlements")
            .select("result, net_profit, picks(player_id, game_id, games(week, season))")
            .eq("picks.player_id", player["id"])
            .eq("picks.games.week", week)
            .eq("picks.games.season", season)
            .execute()
            .data
        )
        penalties_raw = db.get_penalties(player["id"], season)
        week_penalties = [p for p in penalties_raw if p["week"] == week]

        end_points = compute_player_week_end_points(
            current["start_points"],
            settlements_raw,
            week_penalties,
        )
        print(f"  {player['name']}: {current['start_points']:,} → {end_points:,}")
        if not dry_run:
            db.upsert_week_log(player["id"], season, week, current["start_points"], end_points)
            # Seed next week's start_points
            db.upsert_week_log(player["id"], season, week + 1, end_points)

    print("  Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--season", type=int, default=int(os.environ.get("CURRENT_SEASON", 2026)))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(args.week, args.season, args.dry_run)
