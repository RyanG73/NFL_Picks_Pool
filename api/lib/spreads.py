"""
Spread / schedule fetching — ESPN scoreboard (primary) + nflverse CSV (cross-check).

ESPN public scoreboard is called once per week Wednesday morning; no API key required.
nflverse games.csv is fetched as a free no-key cross-check source.
"""
import csv
import io
import httpx


ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
NFLVERSE_GAMES_CSV = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"

# Pool week → (ESPN seasontype, ESPN week).
# Regular season weeks 1-18 map directly; playoff weeks map to ESPN postseason weeks.
# Shared with settle_week.py and replay_test.py — keep all three in sync.
POOL_WEEK_MAP = {**{w: (2, w) for w in range(1, 19)},
                 19: (3, 1), 20: (3, 2), 21: (3, 3), 22: (3, 5)}

# nflverse uses PFR-style abbreviations; ESPN and the DB use full display names.
TEAM_ABBR_TO_DISPLAY = {
    "ARI": "Arizona Cardinals",
    "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",
    "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",
    "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos",
    "DET": "Detroit Lions",
    "GB":  "Green Bay Packers",
    "HOU": "Houston Texans",
    "IND": "Indianapolis Colts",
    "JAX": "Jacksonville Jaguars",
    "KC":  "Kansas City Chiefs",
    "LA":  "Los Angeles Rams",
    "LAC": "Los Angeles Chargers",
    "LV":  "Las Vegas Raiders",
    "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings",
    "NE":  "New England Patriots",
    "NO":  "New Orleans Saints",
    "NYG": "New York Giants",
    "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks",
    "SF":  "San Francisco 49ers",
    "TB":  "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
}


def fetch_week_games(season: int, week: int) -> list[dict]:
    """
    Pull the week's NFL games + spreads from ESPN scoreboard.

    Returns a list of dicts ready to upsert into the games table.
    Games with no odds posted yet are skipped with a warning — re-run later in the week.
    """
    if week not in POOL_WEEK_MAP:
        raise ValueError(f"Week {week} not in POOL_WEEK_MAP (valid: 1-22)")
    seasontype, espn_week = POOL_WEEK_MAP[week]
    url = f"{ESPN_SCOREBOARD}?season={season}&seasontype={seasontype}&week={espn_week}"
    resp = httpx.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    games = []
    for event in data.get("events", []):
        result = _extract_game(event, season, week)
        if result is not None:
            games.append(result)
    return games


def _extract_game(event: dict, season: int, week: int) -> dict | None:
    """Map an ESPN scoreboard event → games table row.  Returns None if odds not yet posted."""
    comp = event.get("competitions", [{}])[0]
    competitors = {c["homeAway"]: c for c in comp.get("competitors", [])}
    home = competitors.get("home", {}).get("team", {}).get("displayName", "")
    away = competitors.get("away", {}).get("team", {}).get("displayName", "")
    if not home or not away:
        return None

    odds_list = comp.get("odds", [])
    if not odds_list:
        print(f"  no odds yet for {home} vs {away} — skipping (re-run Wednesday morning)")
        return None

    odds = odds_list[0]
    # ESPN's spread field is signed (negative = home favored, e.g. -3.5 means home -3.5)
    spread_signed = float(odds.get("spread") or 0)
    spread_magnitude = abs(spread_signed)
    home_is_favorite = odds.get("homeTeamOdds", {}).get("favorite", False)

    if spread_magnitude == 0:
        favorite, underdog = home, away
    elif home_is_favorite:
        favorite, underdog = home, away
    else:
        favorite, underdog = away, home

    return {
        "season": season,
        "week": week,
        "espn_event_id": event.get("id"),
        "home_team": home,
        "away_team": away,
        "favorite_team": favorite,
        "underdog_team": underdog,
        "spread": spread_magnitude,
        "kickoff_at": event.get("date"),
        # Intentionally omit "status" — DB default "scheduled" applies for new rows;
        # existing rows keep their current status if pull_spreads is re-run mid-week.
    }


def fetch_nflverse_spreads(season: int, week: int) -> dict[tuple[str, str], float]:
    """
    Return {(home_display_name, away_display_name): spread_magnitude} from nflverse games.csv.

    nflverse updates games.csv throughout the week; spread_line populates once lines open.
    Returns an empty dict (non-fatal) when spreads aren't yet posted or the request fails.
    nflverse abbreviations are translated to ESPN display names via TEAM_ABBR_TO_DISPLAY.
    """
    resp = httpx.get(NFLVERSE_GAMES_CSV, timeout=20)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    results: dict[tuple[str, str], float] = {}
    for row in reader:
        if row.get("season") != str(season) or row.get("week") != str(week):
            continue
        spread_raw = (row.get("spread_line") or "").strip()
        if not spread_raw:
            continue
        try:
            spread = float(spread_raw)
        except ValueError:
            continue
        home = TEAM_ABBR_TO_DISPLAY.get(row.get("home_team", ""), row.get("home_team", ""))
        away = TEAM_ABBR_TO_DISPLAY.get(row.get("away_team", ""), row.get("away_team", ""))
        results[(home, away)] = abs(spread)
    return results


def cross_check_spreads(
    games: list[dict],
    nflverse_spreads: dict[tuple[str, str], float],
    threshold: float = 1.5,
) -> list[str]:
    """
    Compare ESPN spreads against nflverse spreads.
    Returns a list of human-readable warning strings for discrepancies >= threshold.
    """
    warnings = []
    for g in games:
        key = (g["home_team"], g["away_team"])
        nfl = nflverse_spreads.get(key)
        if nfl is None:
            continue
        delta = abs(float(g["spread"]) - nfl)
        if delta >= threshold:
            warnings.append(
                f"{g['favorite_team']} vs {g['underdog_team']}: "
                f"ESPN={g['spread']}, nflverse={nfl:.1f} (Δ={delta:.1f})"
            )
    return warnings
