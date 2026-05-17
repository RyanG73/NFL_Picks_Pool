"""
Lock timing helpers for the Saturday-noon hard lock rule.

Rule: picks for any game kicking off on/after Saturday noon ET must be
submitted by Saturday noon ET. Thursday games still lock at kickoff.

Effective lock for any game = min(game.kickoff_at, saturday_noon_et(week_games))
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")


def saturday_noon_et(games: list[dict]) -> datetime:
    """
    Return the Saturday 12:00 ET hard-lock time for a given week's game list.

    Finds the first Sunday game in the slate and returns the preceding Saturday
    at noon ET. If there are no Sunday games (TNF-only week), returns a far-future
    datetime so no Saturday-noon lock applies.
    """
    sunday_kickoffs = []
    for g in games:
        if not g.get("kickoff_at"):
            continue
        ko = _parse_utc(g["kickoff_at"])
        if ko.astimezone(_ET).weekday() == 6:  # Sunday
            sunday_kickoffs.append(ko)

    if not sunday_kickoffs:
        # No Sunday games — Saturday-noon lock doesn't apply this week
        return datetime.max.replace(tzinfo=timezone.utc)

    first_sunday = min(sunday_kickoffs).astimezone(_ET).date()
    saturday = first_sunday - timedelta(days=1)
    return datetime(saturday.year, saturday.month, saturday.day, 12, 0, 0, tzinfo=_ET)


def effective_lock_at(game: dict, sat_noon: datetime) -> datetime:
    """Return the effective lock datetime for a single game."""
    return min(_parse_utc(game["kickoff_at"]), sat_noon)


def is_locked(game: dict, now: datetime, sat_noon: datetime) -> bool:
    """True if this game's effective lock time has passed."""
    return now >= effective_lock_at(game, sat_noon)


def compute_prize_ladder(paid_count: int) -> list[str]:
    """
    Build a descending prize ladder for the top 15% of paid players.

    Uses a linearly-weighted arithmetic scheme: position k from the bottom
    gets weight k (so 1st place is most valuable). Prizes are rounded to the
    nearest $25; the bottom position absorbs any rounding remainder so the
    total always equals the exact pot.
    """
    pot = paid_count * 50
    n = max(1, round(paid_count * 0.15))
    total_weight = n * (n + 1) // 2  # sum 1..n

    prizes: list[int] = []
    running = 0
    for i, weight in enumerate(range(n, 0, -1)):  # n, n-1, ..., 1
        if i < n - 1:
            raw = pot * weight / total_weight
            p = round(raw / 25) * 25  # snap to nearest $25
            prizes.append(p)
            running += p
        else:
            prizes.append(pot - running)  # last place absorbs remainder

    return [f"${p:,}" for p in prizes]


def _parse_utc(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
