"""
Replay test harness — validates settlement logic against 2025 historical data.

Loads the 2025 CSVs (pick_log, line_log, week_log, no_bet_log) and runs
the same bet-settlement logic as settle_week.py week by week, then compares
final point totals against the ground-truth week_log.csv.

Uses ESPN's public scoreboard API for scores (no external package required).

Usage:
    python jobs/replay_test.py --season 2025 --archive Historical_Results/Archive_2025
    python jobs/replay_test.py --season 2025 --week 1
    python jobs/replay_test.py --season 2025 --show-diffs
"""
import argparse
import csv
import json
import os
import sys
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.lib.settlement import GameResult, ats_winner


# Pool week → (ESPN seasontype, ESPN week)
# Regular season weeks 1-18; playoffs map to ESPN postseason weeks
POOL_WEEK_MAP = {**{w: (2, w) for w in range(1, 19)},
                 19: (3, 1), 20: (3, 2), 21: (3, 3), 22: (3, 5)}


# ── CSV loaders ────────────────────────────────────────────────────────────

def _na(val) -> str | None:
    return None if val in ("NA", "", None) else val


def _load(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_pick_log(archive_dir: str) -> dict[int, list[dict]]:
    rows = _load(os.path.join(archive_dir, "pick_log.csv"))
    by_week: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        wk = _na(row.get("week"))
        if wk:
            by_week[int(wk)].append(row)
    return dict(by_week)


def load_line_log(archive_dir: str) -> dict[int, list[dict]]:
    rows = _load(os.path.join(archive_dir, "line_log.csv"))
    by_week: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        if _na(row.get("FAVORITE")):
            by_week[int(row["week"])].append(row)
    return dict(by_week)


def load_week_log(archive_dir: str) -> dict[tuple[str, int], dict]:
    rows = _load(os.path.join(archive_dir, "week_log.csv"))
    return {(r["player_name"], int(r["week"])): r for r in rows if _na(r.get("player_name"))}


def load_no_bet_log(archive_dir: str) -> dict[str, int]:
    rows = _load(os.path.join(archive_dir, "no_bet_log.csv"))
    return {r["player_name"]: int(_na(r.get("penalty")) or 0)
            for r in rows if _na(r.get("player_name"))}


# ── ESPN score fetching ────────────────────────────────────────────────────

def fetch_espn_scores(season: int, pool_week: int) -> dict[tuple[str, str], dict]:
    """Return {(home_display_name, away_display_name): {home_score, away_score}}."""
    if pool_week not in POOL_WEEK_MAP:
        return {}
    seasontype, espn_week = POOL_WEEK_MAP[pool_week]
    url = (f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
           f"?season={season}&seasontype={seasontype}&week={espn_week}")
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as exc:
        print(f"    ⚠ ESPN fetch failed for week {pool_week}: {exc}")
        return {}

    results = {}
    for event in data.get("events", []):
        comp = event["competitions"][0]
        # Only use final scores
        if comp.get("status", {}).get("type", {}).get("name") != "STATUS_FINAL":
            continue
        teams = {c["homeAway"]: c for c in comp["competitors"]}
        h = teams.get("home", {}); a = teams.get("away", {})
        home_name = h.get("team", {}).get("displayName", "")
        away_name = a.get("team", {}).get("displayName", "")
        results[(home_name, away_name)] = {
            "home_score": int(h.get("score") or 0),
            "away_score": int(a.get("score") or 0),
        }
    return results


# ── ATS outcome per team name ──────────────────────────────────────────────

def compute_team_outcomes(
    line_rows: list[dict],
    espn_scores: dict[tuple[str, str], dict],
) -> dict[str, str]:
    """
    Returns {team_display_name: 'win'|'loss'|'push'|'no_result'}
    from the PICKER's perspective (win = I picked this team and they covered).
    """
    outcomes: dict[str, str] = {}
    for game in line_rows:
        fav = game["FAVORITE"]
        dog = game["UNDERDOG"]
        spread = float(game["SPREAD"])

        score = espn_scores.get((fav, dog)) or espn_scores.get((dog, fav))
        if not score:
            outcomes[fav] = "no_result"
            outcomes[dog] = "no_result"
            continue

        fav_score = score["home_score"] if (fav, dog) in espn_scores else score["away_score"]
        dog_score = score["away_score"] if (fav, dog) in espn_scores else score["home_score"]

        gr = GameResult(
            game_id="", favorite_team=fav, underdog_team=dog,
            spread=spread, favorite_score=fav_score, underdog_score=dog_score,
            status="final",
        )
        winner = ats_winner(gr)  # 'FAVORITE' | 'UNDERDOG' | 'push'

        if winner == "push":
            outcomes[fav] = "push"
            outcomes[dog] = "push"
        elif winner == "FAVORITE":
            outcomes[fav] = "win"
            outcomes[dog] = "loss"
        else:
            outcomes[fav] = "loss"
            outcomes[dog] = "win"

    return outcomes


# ── Per-player week settlement ─────────────────────────────────────────────

@dataclass
class PlayerResult:
    name: str
    start_points: int
    pick_profit: int = 0
    penalty: int = 0

    @property
    def end_points(self) -> int:
        return max(0, self.start_points + self.pick_profit + self.penalty)


def settle_one_week(
    week: int,
    pick_rows: list[dict],
    team_outcomes: dict[str, str],
    no_bet_log: dict[str, int],
    week_log: dict[tuple[str, int], dict],
) -> dict[str, PlayerResult]:
    player_picks: dict[str, list[dict]] = defaultdict(list)
    for row in pick_rows:
        player_picks[row["player_name"]].append(row)

    results: dict[str, PlayerResult] = {}
    for player_name in sorted(player_picks):
        picks = player_picks[player_name]
        wl = week_log.get((player_name, week))
        start = int(wl["start_points"]) if wl and _na(wl.get("start_points")) else 25_000
        result = PlayerResult(name=player_name, start_points=start)

        team1 = next((p for p in picks if p["pick_slot"] == "team1"), None)
        has_pick = team1 and _na(team1.get("pick_team"))

        if not has_pick and start > 0:
            result.penalty = int(no_bet_log.get(player_name) or 0)
        else:
            profit = 0
            for row in picks:
                pick_team = _na(row.get("pick_team"))
                pick_amount = _na(row.get("pick_amount"))
                if not pick_team or not pick_amount:
                    continue
                amount = int(float(pick_amount))
                outcome = team_outcomes.get(pick_team, "no_result")
                if outcome == "win":
                    profit += amount
                elif outcome == "loss":
                    profit -= amount
            result.pick_profit = profit

        results[player_name] = result
    return results


# ── Main runner ────────────────────────────────────────────────────────────

def run_replay(season: int, archive_dir: str,
               weeks: list[int] | None = None, show_diffs: bool = False) -> bool:
    print(f"\n{'='*65}")
    print(f"  REPLAY TEST — {season} Season")
    print(f"  Archive: {archive_dir}")
    print(f"{'='*65}\n")

    pick_log   = load_pick_log(archive_dir)
    line_log   = load_line_log(archive_dir)
    week_log   = load_week_log(archive_dir)
    no_bet_log = load_no_bet_log(archive_dir)

    target_weeks = sorted(weeks or (set(pick_log) & set(line_log)))

    total_checks = 0
    total_mismatches = 0
    weeks_with_data = 0

    for pool_week in target_weeks:
        if pool_week not in line_log or pool_week not in pick_log:
            continue

        print(f"  Week {pool_week:>2}  ", end="", flush=True)
        espn_scores = fetch_espn_scores(season, pool_week)
        game_count = len(espn_scores)

        team_outcomes = compute_team_outcomes(line_log[pool_week], espn_scores)
        week_results = settle_one_week(
            pool_week, pick_log[pool_week], team_outcomes, no_bet_log, week_log
        )

        week_checks = week_mismatches = 0
        mismatch_lines = []

        for player_name, res in sorted(week_results.items()):
            actual = week_log.get((player_name, pool_week))
            if not actual or not _na(actual.get("end_points")):
                continue
            expected_end = int(actual["end_points"])
            computed_end = res.end_points
            week_checks += 1
            if expected_end != computed_end:
                week_mismatches += 1
                mismatch_lines.append(
                    f"          {player_name:<20} computed={computed_end:>9,}  "
                    f"expected={expected_end:>9,}  delta={computed_end - expected_end:+,}"
                )

        total_checks += week_checks
        total_mismatches += week_mismatches
        weeks_with_data += 1 if week_checks > 0 else 0

        if game_count == 0:
            print(f"⚠  no ESPN scores (skipped)")
        elif week_mismatches == 0:
            print(f"✅  {week_checks} players correct  ({game_count} games)")
        else:
            print(f"❌  {week_mismatches}/{week_checks} mismatches  ({game_count} games)")
            if show_diffs:
                for line in mismatch_lines:
                    print(line)

    acc = total_checks - total_mismatches
    pct = acc / total_checks * 100 if total_checks else 0

    print(f"\n{'='*65}")
    print(f"  RESULT: {acc}/{total_checks} player-weeks match ({pct:.1f}%)")
    if total_mismatches == 0 and total_checks > 0:
        print("  ✅  PASS — Python settlement logic matches historical R output exactly")
    elif total_checks == 0:
        print("  ⚠   No week_log ground-truth data found to compare against")
    else:
        print(f"  ❌  FAIL — {total_mismatches} mismatches remain")
        if not show_diffs:
            print("      Re-run with --show-diffs for per-player detail")
    print(f"{'='*65}\n")
    return total_mismatches == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--season",  type=int, default=2025)
    parser.add_argument("--archive", default="Historical_Results/Archive_2025")
    parser.add_argument("--week",    type=int, default=None)
    parser.add_argument("--show-diffs", action="store_true")
    args = parser.parse_args()

    archive = os.path.join(os.path.dirname(os.path.dirname(__file__)), args.archive)
    weeks = [args.week] if args.week else None
    passed = run_replay(args.season, archive, weeks, args.show_diffs)
    sys.exit(0 if passed else 1)
