"""Unit tests for api/lib/timewall.py pure-logic functions."""
import pytest
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from api.lib.timewall import (
    kickoff_time_et,
    kickoff_day_et,
    saturday_noon_et,
    effective_lock_at,
    is_locked,
    compute_prize_ladder,
    apply_prize_ladder,
)

_ET = ZoneInfo("America/New_York")


# ── kickoff_time_et ────────────────────────────────────────────────────────────

def test_kickoff_time_et_afternoon():
    assert kickoff_time_et("2026-09-10T17:00:00Z") == "1:00 PM ET"


def test_kickoff_time_et_morning():
    assert kickoff_time_et("2026-09-10T14:30:00Z") == "10:30 AM ET"


def test_kickoff_time_et_midnight_hour():
    assert kickoff_time_et("2026-09-10T00:00:00Z") == "8:00 PM ET"


def test_kickoff_time_et_noon():
    # 2026-09-10T16:00:00Z = 12:00 PM EDT (UTC-4 in September)
    assert kickoff_time_et("2026-09-10T16:00:00Z") == "12:00 PM ET"


def test_kickoff_time_et_midnight():
    # 2026-09-10T04:00:00Z = 12:00 AM EDT
    assert kickoff_time_et("2026-09-10T04:00:00Z") == "12:00 AM ET"


def test_kickoff_time_et_invalid_fallback():
    result = kickoff_time_et("not-a-date")
    assert isinstance(result, str)


# ── kickoff_day_et ─────────────────────────────────────────────────────────────

def test_kickoff_day_et_sunday():
    # 2026-09-13 is a Sunday
    result = kickoff_day_et("2026-09-13T17:00:00Z")
    assert "Sun" in result
    assert "Sep" in result


def test_kickoff_day_et_thursday():
    # 2026-09-10 is a Thursday
    result = kickoff_day_et("2026-09-10T17:00:00Z")
    assert "Thu" in result


def test_kickoff_day_et_invalid_fallback():
    result = kickoff_day_et("not-a-date")
    assert isinstance(result, str)


# ── saturday_noon_et ───────────────────────────────────────────────────────────

def _game(kickoff_utc: str) -> dict:
    return {"kickoff_at": kickoff_utc}


def test_saturday_noon_with_sunday_games():
    # Sunday 2026-09-13 at 1pm ET = 17:00 UTC
    sun_game = _game("2026-09-13T17:00:00Z")
    thu_game = _game("2026-09-10T00:30:00Z")
    sat_noon = saturday_noon_et([thu_game, sun_game])
    # Should be Saturday 2026-09-12 at noon ET
    assert sat_noon.year == 2026
    assert sat_noon.month == 9
    assert sat_noon.day == 12
    assert sat_noon.hour == 12
    assert sat_noon.minute == 0


def test_saturday_noon_no_sunday_games():
    # TNF-only week — no Sunday games → far future
    thu_game = _game("2026-09-10T00:30:00Z")
    sat_noon = saturday_noon_et([thu_game])
    assert sat_noon == datetime.max.replace(tzinfo=timezone.utc)


def test_saturday_noon_empty_games():
    sat_noon = saturday_noon_et([])
    assert sat_noon == datetime.max.replace(tzinfo=timezone.utc)


def test_saturday_noon_monday_only_no_lock():
    # MNF-only week with no Sunday games → no Saturday-noon lock.
    # Mon 2026-09-14 at 8:15pm EDT = 2026-09-15T00:15:00Z (UTC)
    mon_game = _game("2026-09-15T00:15:00Z")
    sat_noon = saturday_noon_et([mon_game])
    assert sat_noon == datetime.max.replace(tzinfo=timezone.utc)


# ── effective_lock_at / is_locked ──────────────────────────────────────────────

def test_thursday_game_locks_at_kickoff():
    # Thursday 2026-09-10 kickoff at 8:20pm ET = 00:20 UTC next day
    thu_kickoff = "2026-09-11T00:20:00Z"
    game = _game(thu_kickoff)
    # Saturday noon for a week with a Sunday game
    sat_noon = datetime(2026, 9, 12, 12, 0, 0, tzinfo=_ET)

    # Before kickoff: not locked
    before = datetime(2026, 9, 10, 23, 0, 0, tzinfo=timezone.utc)
    assert not is_locked(game, before, sat_noon)

    # After kickoff: locked
    after = datetime(2026, 9, 11, 1, 0, 0, tzinfo=timezone.utc)
    assert is_locked(game, after, sat_noon)


def test_sunday_game_locks_at_saturday_noon():
    # Sunday 2026-09-13 kickoff at 1pm ET
    sun_kickoff = "2026-09-13T17:00:00Z"
    game = _game(sun_kickoff)
    sat_noon = datetime(2026, 9, 12, 12, 0, 0, tzinfo=_ET)

    # Friday: not locked
    friday = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)
    assert not is_locked(game, friday, sat_noon)

    # Saturday at noon exactly: locked
    sat_noon_utc = sat_noon.astimezone(timezone.utc)
    assert is_locked(game, sat_noon_utc, sat_noon)

    # Saturday before noon: not locked
    sat_before = sat_noon_utc - timedelta(minutes=1)
    assert not is_locked(game, sat_before, sat_noon)


# ── compute_prize_ladder ───────────────────────────────────────────────────────

def test_prize_ladder_pot_sums_correctly():
    for count in [10, 20, 30, 40, 50]:
        prizes = compute_prize_ladder(count)
        total = sum(int(p.replace("$", "").replace(",", "")) for p in prizes)
        assert total == count * 50, f"count={count}: prizes sum {total} != pot {count * 50}"


def test_prize_ladder_descending():
    prizes = compute_prize_ladder(40)
    amounts = [int(p.replace("$", "").replace(",", "")) for p in prizes]
    assert amounts == sorted(amounts, reverse=True), "prizes should be descending"


def test_prize_ladder_15_percent():
    # 20 players → 15% = 3 winners
    prizes = compute_prize_ladder(20)
    assert len(prizes) == 3

    # 40 players → 15% = 6 winners
    prizes = compute_prize_ladder(40)
    assert len(prizes) == 6


def test_prize_ladder_single_player():
    prizes = compute_prize_ladder(1)
    assert len(prizes) == 1
    assert prizes[0] == "$50"


# ── apply_prize_ladder ─────────────────────────────────────────────────────────

def _standing(player_id: str, name: str, points: int, eliminated: bool = False) -> dict:
    return {
        "player_id": player_id,
        "name": name,
        "current_points": points,
        "is_eliminated": eliminated,
        "week_profit": 0,
    }


def test_apply_prize_ladder_no_ties():
    standings = [
        _standing("a", "Alice", 30000),
        _standing("b", "Bob",   25000),
        _standing("c", "Carol", 20000),
    ]
    prizes = ["$300", "$150", "$50"]
    result = apply_prize_ladder(standings, prizes)

    assert result[0]["prize"] == "$300"
    assert result[0]["rank_display"] == "1"
    assert result[1]["prize"] == "$150"
    assert result[1]["rank_display"] == "2"
    assert result[2]["prize"] == "$50"
    assert result[2]["rank_display"] == "3"


def test_apply_prize_ladder_tie_splits_prizes():
    # Two players tied for 1st — should split 1st+2nd prize
    standings = [
        _standing("a", "Alice", 30000),
        _standing("b", "Bob",   30000),
        _standing("c", "Carol", 20000),
    ]
    prizes = ["$300", "$200", "$100"]
    result = apply_prize_ladder(standings, prizes)

    # Alice and Bob each get ($300 + $200) / 2 = $250
    assert result[0]["prize"] == "$250"
    assert result[0]["rank_display"] == "T1"
    assert result[1]["prize"] == "$250"
    assert result[1]["rank_display"] == "T1"
    assert result[2]["prize"] == "$100"
    assert result[2]["rank_display"] == "3"


def test_apply_prize_ladder_eliminated_no_prize():
    standings = [
        _standing("a", "Alice", 5000),
        _standing("b", "Bob",   0, eliminated=True),
    ]
    prizes = ["$100"]
    result = apply_prize_ladder(standings, prizes)

    assert result[0]["prize"] == "$100"
    assert result[1]["prize"] is None


def test_apply_prize_ladder_more_players_than_prizes():
    # Only top N get prizes; the rest get None
    standings = [
        _standing("a", "Alice", 30000),
        _standing("b", "Bob",   25000),
        _standing("c", "Carol", 20000),
        _standing("d", "Dave",  15000),
    ]
    prizes = ["$300", "$150"]  # only 2 prizes for 4 players
    result = apply_prize_ladder(standings, prizes)
    assert result[0]["prize"] == "$300"
    assert result[1]["prize"] == "$150"
    assert result[2]["prize"] is None
    assert result[3]["prize"] is None


def test_apply_prize_ladder_empty():
    assert apply_prize_ladder([], []) == []
