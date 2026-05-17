"""
Spread / schedule fetching — ported from Historical_Code/wednesday.R.

Wraps The Odds API (https://the-odds-api.com/) to pull the current week's
NFL games with consensus spreads. Transforms to the shape expected by the
games table.
"""
import os
import httpx
from datetime import datetime, timezone


ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
SPORT = "americanfootball_nfl"
REGIONS = "us"
MARKETS = "spreads"
BOOKMAKERS = "draftkings"    # use a single book for consistency


def fetch_week_games(season: int, week: int) -> list[dict]:
    """
    Pull upcoming NFL games from The Odds API and return a list of dicts
    ready to upsert into the games table.

    Uses remaining quota carefully: one request per weekly cron run.
    """
    api_key = os.environ["ODDS_API_KEY"]
    url = f"{ODDS_API_BASE}/sports/{SPORT}/odds/"
    params = {
        "apiKey": api_key,
        "regions": REGIONS,
        "markets": MARKETS,
        "bookmakers": BOOKMAKERS,
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    resp = httpx.get(url, params=params, timeout=15)
    resp.raise_for_status()
    raw_games = resp.json()

    return [_transform(g, season, week) for g in raw_games if g.get("bookmakers")]


def _transform(raw: dict, season: int, week: int) -> dict:
    """Map Odds API game object → games table row."""
    home = raw["home_team"]
    away = raw["away_team"]

    # Pull spread from the first bookmaker / spreads market
    spread_line, favorite, underdog = _extract_spread(raw, home, away)

    return {
        "season": season,
        "week": week,
        "espn_event_id": raw.get("id"),
        "home_team": home,
        "away_team": away,
        "favorite_team": favorite,
        "underdog_team": underdog,
        "spread": abs(spread_line),
        "kickoff_at": raw["commence_time"],
        "status": "scheduled",
    }


def fetch_espn_spreads() -> dict[tuple[str, str], float]:
    """
    Return {(home_display_name, away_display_name): spread_magnitude} from ESPN.

    Uses the same public scoreboard endpoint as poll_live_scores.py so no API key
    is needed. Returns an empty dict (non-fatal) when ESPN has no odds available
    (common early in the week before lines are posted).
    """
    resp = httpx.get(ESPN_SCOREBOARD, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    results: dict[tuple[str, str], float] = {}
    for event in data.get("events", []):
        comp = event.get("competitions", [{}])[0]
        odds_list = comp.get("odds", [])
        if not odds_list:
            continue
        competitors = {c["homeAway"]: c for c in comp.get("competitors", [])}
        home_name = competitors.get("home", {}).get("team", {}).get("displayName", "")
        away_name = competitors.get("away", {}).get("team", {}).get("displayName", "")
        if not home_name or not away_name:
            continue
        spread = odds_list[0].get("spread")  # absolute magnitude
        if spread is not None:
            results[(home_name, away_name)] = float(spread)
    return results


def cross_check_spreads(
    games: list[dict],
    espn_spreads: dict[tuple[str, str], float],
    threshold: float = 1.5,
) -> list[str]:
    """
    Compare Odds API spreads against ESPN consensus spreads.
    Returns a list of human-readable warning strings for discrepancies >= threshold.
    """
    warnings = []
    for g in games:
        key = (g["home_team"], g["away_team"])
        espn = espn_spreads.get(key)
        if espn is None:
            continue
        delta = abs(float(g["spread"]) - espn)
        if delta >= threshold:
            warnings.append(
                f"{g['favorite_team']} vs {g['underdog_team']}: "
                f"Odds API={g['spread']}, ESPN={espn:.1f} (Δ={delta:.1f})"
            )
    return warnings


def _extract_spread(raw: dict, home: str, away: str) -> tuple[float, str, str]:
    """Return (spread_magnitude, favorite_team, underdog_team)."""
    for bm in raw.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market["key"] != "spreads":
                continue
            outcomes = {o["name"]: o["point"] for o in market["outcomes"]}
            home_line = outcomes.get(home, 0.0)
            # Negative line = favorite (e.g. -3.5 means home favored by 3.5)
            if home_line <= 0:
                return home_line, home, away
            else:
                return -outcomes.get(away, 0.0), away, home
    # Fallback: pick-em
    return 0.0, home, away
