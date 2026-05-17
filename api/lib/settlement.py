"""
Bet settlement logic — ported from Historical_Code/tuesday.R.

Given a game's final scores and the agreed spread, determine:
  - Which side won ATS (FAVORITE / UNDERDOG / push)
  - Each player's net_profit for that pick

All heavy DB writes are done by jobs/settle_week.py; this module is pure logic.
"""
from dataclasses import dataclass


@dataclass
class GameResult:
    game_id: str
    favorite_team: str
    underdog_team: str
    spread: float          # positive; favorite is favored by this amount
    favorite_score: int
    underdog_score: int
    status: str            # 'final' | 'voided'


def ats_winner(result: GameResult) -> str:
    """
    Returns 'FAVORITE', 'UNDERDOG', or 'push'.

    The favorite wins ATS if:   favorite_score - underdog_score > spread
    The underdog wins ATS if:   favorite_score - underdog_score < spread
    Push if exactly equal.

    Mirrors tuesday.R lines 89-110.
    """
    if result.status == "voided":
        return "voided"
    diff = result.favorite_score - result.underdog_score
    if diff > result.spread:
        return "FAVORITE"
    elif diff < result.spread:
        return "UNDERDOG"
    else:
        return "push"


def settle_pick(pick_side: str, pick_amount: int, winner: str) -> tuple[str, int]:
    """
    Returns (result_label, net_profit).

    result_label: 'win' | 'loss' | 'push' | 'voided'
    net_profit:   +pick_amount on win, -pick_amount on loss, 0 on push/voided
    """
    if winner == "voided":
        return "voided", 0
    if winner == "push":
        return "push", 0
    if pick_side == winner:
        return "win", pick_amount
    return "loss", -pick_amount


def compute_penalty_amount(consecutive_misses: int) -> int:
    """
    Escalating no-bet penalty per rulebook section 5d.

    Week 1 miss: -5,000
    Week 2 miss: -10,000
    Week 3 miss: -15,000  … etc.
    """
    return -5_000 * consecutive_misses


def compute_player_week_end_points(
    start_points: int,
    settlements: list[dict],   # list of {result, net_profit}
    penalties: list[dict],     # list of {amount, waived}
) -> int:
    settled_profit = sum(s["net_profit"] for s in settlements)
    penalty_total = sum(
        p["amount"] for p in penalties if not p.get("waived")
    )
    return max(0, start_points + settled_profit + penalty_total)
