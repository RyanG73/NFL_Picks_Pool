"""
Replay test harness — validates settlement logic against 2025 historical data.

Loads the 2025 CSVs (pick_log, line_log, week_log, no_bet_log) and runs
the same bet-settlement logic as settle_week.py week by week, then compares
final point totals against the ground-truth week_log.csv.

This is the primary correctness check before launching the 2026 season.
A perfect replay means our Python logic matches Ryan's R scripts exactly.

Usage:
    python jobs/replay_test.py --season 2025 --archive Historical_Results/Archive_2025
    python jobs/replay_test.py --season 2025 --week 1   # replay only week 1
    python jobs/replay_test.py --season 2025 --show-diffs  # print mismatches
"""
import argparse
import csv
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import nfl_data_py as nfl

from api.lib.settlement import GameResult, ats_winner, settle_pick, compute_penalty_amount


# ── Data loaders ───────────────────────────────────────────────────────────

def load_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def na(val) -> str | None:
    return None if val in ("NA", "", None) else val


def load_pick_log(archive_dir: str) -> dict[int, list[dict]]:
    """Returns {week: [pick_rows]} — only team1 slot with actual picks."""
    rows = load_csv(os.path.join(archive_dir, "pick_log.csv"))
    by_week: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        week = na(row.get("week"))
        if not week:
            continue
        by_week[int(week)].append(row)
    return dict(by_week)


def load_line_log(archive_dir: str) -> dict[int, list[dict]]:
    """Returns {week: [game_rows]}."""
    rows = load_csv(os.path.join(archive_dir, "line_log.csv"))
    by_week: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        if not na(row.get("FAVORITE")):
            continue
        by_week[int(row["week"])].append(row)
    return dict(by_week)


def load_week_log(archive_dir: str) -> dict[tuple[str, int], dict]:
    """Returns {(player_name, week): row}."""
    rows = load_csv(os.path.join(archive_dir, "week_log.csv"))
    return {(r["player_name"], int(r["week"])): r for r in rows if na(r.get("player_name"))}


def load_no_bet_log(archive_dir: str) -> dict[str, int]:
    """Returns {player_name: current_penalty_amount}."""
    rows = load_csv(os.path.join(archive_dir, "no_bet_log.csv"))
    out = {}
    for r in rows:
        name = na(r.get("player_name"))
        if name:
            out[name] = int(na(r.get("penalty")) or 0)
    return out


# ── Score fetching ─────────────────────────────────────────────────────────

def load_nfldata_scores(season: int) -> dict[tuple[str, str], dict]:
    """
    Returns {(home_team_full, away_team_full): {home_score, away_score, week}}.
    We match by team name since we don't have ESPN IDs in the historical data.
    """
    schedules = nfl.import_schedules([season])
    teams_df = nfl.import_team_desc()

    # Build abbr → full-name map
    abbr_to_name = dict(zip(teams_df["team_abbr"], teams_df["team_name"]))

    results = {}
    for _, row in schedules.iterrows():
        home_full = abbr_to_name.get(row["home_team"], row["home_team"])
        away_full = abbr_to_name.get(row["away_team"], row["away_team"])
        results[(home_full, away_full)] = {
            "home_score": int(row.get("home_score") or 0),
            "away_score": int(row.get("away_score") or 0),
            "week": int(row["week"]),
        }
    return results


# ── ATS result using historical line_log ──────────────────────────────────

def compute_ats_results(line_rows: list[dict], scores: dict) -> dict[str, str]:
    """
    Returns {team_name: 'FAVORITE'|'UNDERDOG'|'push'|'no_result'}.
    Covers both sides so we can look up pick_team directly.
    """
    team_to_winner: dict[str, str] = {}

    for game in line_rows:
        fav = game["FAVORITE"]
        dog = game["UNDERDOG"]
        spread = float(game["SPREAD"])

        # Match score — try both home/away orientations
        score = scores.get((fav, dog)) or scores.get((dog, fav))
        if not score:
            # Couldn't find score — mark both as no_result (voided in real life)
            team_to_winner[fav] = "no_result"
            team_to_winner[dog] = "no_result"
            continue

        # Determine which team is home
        if (fav, dog) in scores:
            fav_score = score["home_score"]
            dog_score = score["away_score"]
        else:
            fav_score = score["away_score"]
            dog_score = score["home_score"]

        gr = GameResult(
            game_id="",
            favorite_team=fav,
            underdog_team=dog,
            spread=spread,
            favorite_score=fav_score,
            underdog_score=dog_score,
            status="final",
        )
        winner = ats_winner(gr)
        team_to_winner[fav] = winner
        team_to_winner[dog] = winner

    return team_to_winner


# ── Week settlement ────────────────────────────────────────────────────────

@dataclass
class PlayerResult:
    name: str
    start_points: int
    pick_profit: int = 0
    penalty: int = 0

    @property
    def end_points(self) -> int:
        return max(0, self.start_points + self.pick_profit + self.penalty)


def settle_week(
    week: int,
    pick_rows: list[dict],
    ats_results: dict[str, str],
    no_bet_log: dict[str, int],
    week_log: dict[tuple[str, int], dict],
) -> dict[str, PlayerResult]:
    """
    Reproduce the R tuesday.R logic for one week.
    Returns {player_name: PlayerResult}.
    """
    # Group picks by player
    player_picks: dict[str, list[dict]] = defaultdict(list)
    for row in pick_rows:
        player_picks[row["player_name"]].append(row)

    results: dict[str, PlayerResult] = {}

    all_players = set(player_picks.keys()) | set(no_bet_log.keys())

    for player_name in all_players:
        picks = player_picks.get(player_name, [])

        # Get start_points from week_log (ground truth)
        wl = week_log.get((player_name, week))
        start = int(wl["start_points"]) if wl and na(wl.get("start_points")) else 25_000

        result = PlayerResult(name=player_name, start_points=start)

        # team1 slot with no pick = missed week (use no_bet_log penalty)
        team1_rows = [p for p in picks if p["pick_slot"] == "team1"]
        has_pick = team1_rows and na(team1_rows[0].get("pick_team"))

        if not has_pick and start > 0:
            # Missed week: apply penalty from no_bet_log
            penalty_amt = int(no_bet_log.get(player_name) or 0)
            result.penalty = penalty_amt
        else:
            # Settle each pick slot
            profit = 0
            for row in picks:
                pick_team = na(row.get("pick_team"))
                pick_amount = na(row.get("pick_amount"))
                if not pick_team or not pick_amount:
                    continue
                amount = int(float(pick_amount))
                winner = ats_results.get(pick_team, "no_result")
                if winner == "no_result":
                    continue  # voided game — no profit/loss
                # Determine if this pick is fav or dog
                game_line = next(
                    (g for g in [] if g.get("FAVORITE") == pick_team or g.get("UNDERDOG") == pick_team),
                    None
                )
                pick_side = "FAVORITE" if ats_results.get(pick_team) == "FAVORITE" and winner == "FAVORITE" else "UNDERDOG"
                # Simplify: winner dict maps team_name → which side won overall
                # pick wins if: ats_results[pick_team] == the side that WON (FAVORITE or UNDERDOG),
                # and pick_team is on that side
                # We stored {team: 'FAVORITE'|'UNDERDOG'|'push'} = which side WON ATS
                # pick_team wins if ats_results[pick_team] is the same string as the team's side
                # Rebuild: fav wins → ats_results[fav]='FAVORITE', ats_results[dog]='FAVORITE'
                # pick wins if pick_team IS the FAVORITE and winner='FAVORITE', or IS the UNDERDOG and winner='UNDERDOG'
                # We can't easily tell from just winner alone — need the game row.
                # Use a simpler approach: store {team: 'win'|'loss'|'push'} directly.
                # (See compute_ats_results_v2 below — this function uses that.)
                pass

        results[player_name] = result

    return results


def compute_ats_results_v2(line_rows: list[dict], scores: dict) -> dict[str, str]:
    """
    Returns {team_name: 'win'|'loss'|'push'|'no_result'} from the PICKER's perspective.
    A win means: you picked this team and covered.
    """
    team_outcome: dict[str, str] = {}

    for game in line_rows:
        fav = game["FAVORITE"]
        dog = game["UNDERDOG"]
        spread = float(game["SPREAD"])

        score = scores.get((fav, dog)) or scores.get((dog, fav))
        if not score:
            team_outcome[fav] = "no_result"
            team_outcome[dog] = "no_result"
            continue

        if (fav, dog) in scores:
            fav_score = score["home_score"]
            dog_score = score["away_score"]
        else:
            fav_score = score["away_score"]
            dog_score = score["home_score"]

        diff = fav_score - dog_score
        if diff > spread:
            team_outcome[fav] = "win"
            team_outcome[dog] = "loss"
        elif diff < spread:
            team_outcome[fav] = "loss"
            team_outcome[dog] = "win"
        else:
            team_outcome[fav] = "push"
            team_outcome[dog] = "push"

    return team_outcome


def settle_week_v2(
    week: int,
    pick_rows: list[dict],
    team_outcomes: dict[str, str],
    no_bet_log: dict[str, int],
    week_log: dict[tuple[str, int], dict],
) -> dict[str, PlayerResult]:
    """Clean settlement using team_outcomes (win/loss/push per team name)."""
    player_picks: dict[str, list[dict]] = defaultdict(list)
    for row in pick_rows:
        player_picks[row["player_name"]].append(row)

    results: dict[str, PlayerResult] = {}
    all_players = set(player_picks.keys()) | {k for k, w in week_log.items() if w == week}

    for player_name in sorted(set(r["player_name"] for r in pick_rows)):
        picks = player_picks.get(player_name, [])
        wl = week_log.get((player_name, week))
        start = int(wl["start_points"]) if wl and na(wl.get("start_points")) else 25_000
        result = PlayerResult(name=player_name, start_points=start)

        team1 = next((p for p in picks if p["pick_slot"] == "team1"), None)
        has_pick = team1 and na(team1.get("pick_team"))

        if not has_pick and start > 0:
            result.penalty = int(no_bet_log.get(player_name) or 0)
        else:
            profit = 0
            for row in picks:
                pick_team = na(row.get("pick_team"))
                pick_amount = na(row.get("pick_amount"))
                if not pick_team or not pick_amount:
                    continue
                amount = int(float(pick_amount))
                outcome = team_outcomes.get(pick_team, "no_result")
                if outcome == "win":
                    profit += amount
                elif outcome == "loss":
                    profit -= amount
                # push / no_result = 0 net
            result.pick_profit = profit

        results[player_name] = result

    return results


# ── Main comparison ────────────────────────────────────────────────────────

def run_replay(
    season: int,
    archive_dir: str,
    weeks: list[int] | None = None,
    show_diffs: bool = False,
) -> bool:
    print(f"\n{'='*60}")
    print(f" REPLAY TEST — {season} Season")
    print(f" Archive: {archive_dir}")
    print(f"{'='*60}\n")

    pick_log = load_pick_log(archive_dir)
    line_log = load_line_log(archive_dir)
    week_log = load_week_log(archive_dir)
    no_bet_log_data = load_no_bet_log(archive_dir)

    print("Loading final scores from nfl-data-py…")
    scores = load_nfldata_scores(season)
    print(f"  Loaded {len(scores)} games\n")

    target_weeks = sorted(weeks or line_log.keys())
    total_checks = 0
    total_mismatches = 0

    for week in target_weeks:
        if week not in line_log or week not in pick_log:
            continue

        team_outcomes = compute_ats_results_v2(line_log[week], scores)
        week_results = settle_week_v2(
            week, pick_log[week], team_outcomes, no_bet_log_data, week_log
        )

        week_mismatches = 0
        for player_name, res in sorted(week_results.items()):
            actual = week_log.get((player_name, week))
            if not actual or not na(actual.get("end_points")):
                continue
            expected_end = int(actual["end_points"])
            computed_end = res.end_points
            total_checks += 1
            if expected_end != computed_end:
                total_mismatches += 1
                week_mismatches += 1
                if show_diffs:
                    print(f"  MISMATCH  Week {week:>2}  {player_name:<18}"
                          f"  computed={computed_end:>8,}  expected={expected_end:>8,}"
                          f"  delta={computed_end - expected_end:+,}")

        status = "✅" if week_mismatches == 0 else f"❌ {week_mismatches} mismatches"
        print(f"  Week {week:>2}: {status}")

    print(f"\n{'='*60}")
    print(f" RESULT: {total_checks - total_mismatches}/{total_checks} player-weeks match exactly")
    if total_mismatches == 0:
        print(" ✅ PASS — settlement logic is correct")
    else:
        pct = total_mismatches / total_checks * 100 if total_checks else 0
        print(f" ❌ FAIL — {total_mismatches} mismatches ({pct:.1f}%)")
        print("    Run with --show-diffs for details")
    print(f"{'='*60}\n")

    return total_mismatches == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay 2025 season to validate settlement logic")
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument("--archive", default="Historical_Results/Archive_2025")
    parser.add_argument("--week", type=int, default=None, help="Test only this week")
    parser.add_argument("--show-diffs", action="store_true")
    args = parser.parse_args()

    weeks = [args.week] if args.week else None
    archive = os.path.join(os.path.dirname(os.path.dirname(__file__)), args.archive)
    passed = run_replay(args.season, archive, weeks, args.show_diffs)
    sys.exit(0 if passed else 1)
