"""Unit tests for api/lib/spreads.py pure-logic functions."""
from api.lib.spreads import cross_check_spreads


def _game(home: str, away: str, fav: str, dog: str, spread: float) -> dict:
    return {"home_team": home, "away_team": away, "favorite_team": fav, "underdog_team": dog, "spread": spread}


# ── cross_check_spreads ────────────────────────────────────────────────────────

def test_no_discrepancy():
    games = [_game("Eagles", "Cowboys", "Eagles", "Cowboys", 3.0)]
    nfl = {("Eagles", "Cowboys"): 3.0}
    assert cross_check_spreads(games, nfl) == []


def test_delta_below_threshold():
    games = [_game("A", "B", "A", "B", 3.0)]
    nfl = {("A", "B"): 4.0}  # delta = 1.0, below default threshold 1.5
    assert cross_check_spreads(games, nfl) == []


def test_delta_at_threshold_triggers_warning():
    games = [_game("A", "B", "A", "B", 3.0)]
    nfl = {("A", "B"): 4.5}  # delta = 1.5, exactly at threshold
    warnings = cross_check_spreads(games, nfl)
    assert len(warnings) == 1
    assert "A" in warnings[0]
    assert "3.0" in warnings[0]
    assert "4.5" in warnings[0]


def test_delta_above_threshold_triggers_warning():
    games = [_game("Chiefs", "Raiders", "Chiefs", "Raiders", 7.0)]
    nfl = {("Chiefs", "Raiders"): 10.0}  # delta = 3.0
    warnings = cross_check_spreads(games, nfl)
    assert len(warnings) == 1
    assert "Chiefs" in warnings[0]


def test_no_nflverse_match_no_warning():
    games = [_game("X", "Y", "X", "Y", 3.0)]
    nfl = {}
    assert cross_check_spreads(games, nfl) == []


def test_only_matching_games_trigger():
    games = [
        _game("A", "B", "A", "B", 3.0),
        _game("C", "D", "C", "D", 7.0),
    ]
    # A vs B is fine, C vs D has delta 3.0
    nfl = {("A", "B"): 3.0, ("C", "D"): 10.0}
    warnings = cross_check_spreads(games, nfl)
    assert len(warnings) == 1
    assert "C" in warnings[0]


def test_custom_threshold():
    games = [_game("A", "B", "A", "B", 3.0)]
    nfl = {("A", "B"): 4.0}  # delta = 1.0
    # With threshold=1.0, delta exactly at threshold → warning
    warnings = cross_check_spreads(games, nfl, threshold=1.0)
    assert len(warnings) == 1
    # With threshold=1.5 (default), no warning
    assert cross_check_spreads(games, nfl, threshold=1.5) == []


def test_empty_inputs():
    assert cross_check_spreads([], {}) == []
    assert cross_check_spreads([], {("A", "B"): 3.0}) == []
