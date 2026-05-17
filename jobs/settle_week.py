"""
Tuesday 09:00 ET — pull authoritative final scores, settle all picks,
apply escalating no-bet penalties, advance week_log.

Score source priority:
  1. nfl-data-py (authoritative; requires pip install nfl-data-py)
  2. ESPN public scoreboard API (stdlib-only fallback; used when nfl-data-py unavailable)

Ported from Historical_Code/tuesday.R (lines 35–184).
Idempotent: safe to re-run; will skip already-settled picks.

Usage: python jobs/settle_week.py --week 1 --season 2026 [--dry-run]
"""
import argparse
import json
import os
import sys
import urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from api.lib import db
from api.lib.settlement import GameResult, ats_winner, settle_pick, compute_player_week_end_points


# Pool week → (ESPN seasontype, ESPN week) — mirrors replay_test.py
_POOL_WEEK_MAP = {**{w: (2, w) for w in range(1, 19)},
                  19: (3, 1), 20: (3, 2), 21: (3, 3), 22: (3, 5)}


def _load_via_nfl_data_py(season: int, week: int) -> dict[str, dict]:
    import nfl_data_py as nfl
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


def _load_via_espn(season: int, week: int) -> dict[str, dict]:
    """ESPN public scoreboard fallback — no external packages required."""
    if week not in _POOL_WEEK_MAP:
        return {}
    seasontype, espn_week = _POOL_WEEK_MAP[week]
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
        f"?season={season}&seasontype={seasontype}&week={espn_week}"
    )
    with urllib.request.urlopen(url, timeout=20) as r:
        data = json.loads(r.read())

    results = {}
    for event in data.get("events", []):
        comp = event["competitions"][0]
        if comp.get("status", {}).get("type", {}).get("name") != "STATUS_FINAL":
            continue
        eid = event["id"]
        teams = {c["homeAway"]: c for c in comp["competitors"]}
        h = teams.get("home", {})
        a = teams.get("away", {})
        results[eid] = {
            "home_team": h.get("team", {}).get("displayName", ""),
            "away_team": a.get("team", {}).get("displayName", ""),
            "home_score": int(h.get("score") or 0),
            "away_score": int(a.get("score") or 0),
        }
    return results


def load_final_scores(season: int, week: int) -> dict[str, dict]:
    """Load final scores keyed by ESPN event ID. Tries nfl-data-py, falls back to ESPN."""
    try:
        scores = _load_via_nfl_data_py(season, week)
        print(f"  Loaded {len(scores)} final scores from nfl-data-py")
        return scores
    except Exception as exc:
        print(f"  nfl-data-py unavailable ({exc}); falling back to ESPN API")

    scores = _load_via_espn(season, week)
    print(f"  Loaded {len(scores)} final scores from ESPN API")
    return scores


def main(week: int, season: int, dry_run: bool = False):
    print(f"[settle_week] season={season} week={week} dry_run={dry_run}")

    final_scores = load_final_scores(season, week)

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

        # Gather settled picks for this week via picks_reveal_v (direct columns,
        # no nested-resource filters which don't reliably filter parent rows).
        from api.lib.db import get_client
        settlements_raw = (
            get_client()
            .table("picks_reveal_v")
            .select("result, net_profit")
            .eq("player_id", player["id"])
            .eq("season", season)
            .eq("week", week)
            .not_.is_("result", "null")
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
