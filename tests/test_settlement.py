"""Unit tests for api/lib/settlement.py pure-logic functions."""
from api.lib.settlement import ats_winner, settle_pick, compute_penalty_amount, compute_player_week_end_points, GameResult



def _result(fav_score: int, dog_score: int, spread: float, status: str = "final") -> GameResult:
    return GameResult(
        game_id="test",
        favorite_team="Chiefs",
        underdog_team="Raiders",
        spread=spread,
        favorite_score=fav_score,
        underdog_score=dog_score,
        status=status,
    )


# ── ats_winner ─────────────────────────────────────────────────────────────────

def test_favorite_covers():
    gr = _result(fav_score=27, dog_score=10, spread=10.5)
    # Chiefs win by 17 > 10.5 → favorite covers
    assert ats_winner(gr) == "FAVORITE"


def test_underdog_covers():
    gr = _result(fav_score=20, dog_score=17, spread=10.5)
    # Chiefs win by 3 < 10.5 → underdog covers
    assert ats_winner(gr) == "UNDERDOG"


def test_push():
    gr = _result(fav_score=17, dog_score=10, spread=7.0)
    # Chiefs win by exactly 7 → push
    assert ats_winner(gr) == "push"


def test_in_progress_game_computes_ats_anyway():
    # ats_winner doesn't short-circuit on status; in_progress games are computed live.
    # margin 7 < spread 10.5 → underdog covers
    gr = _result(fav_score=14, dog_score=7, spread=10.5, status="in_progress")
    assert ats_winner(gr) == "UNDERDOG"


def test_zero_spread_favorite_wins():
    gr = _result(fav_score=21, dog_score=14, spread=0.0)
    # Favorite wins straight up
    assert ats_winner(gr) == "FAVORITE"


def test_zero_spread_tie():
    gr = _result(fav_score=14, dog_score=14, spread=0.0)
    assert ats_winner(gr) == "push"


def test_voided_game_returns_voided():
    gr = _result(fav_score=14, dog_score=7, spread=3.0, status="voided")
    assert ats_winner(gr) == "voided"


def test_underdog_wins_outright():
    gr = _result(fav_score=10, dog_score=21, spread=3.5)
    # diff = 10 - 21 = -11, which is < 3.5 → underdog covers
    assert ats_winner(gr) == "UNDERDOG"


# ── settle_pick ────────────────────────────────────────────────────────────────

def test_settle_pick_win():
    result, net = settle_pick("FAVORITE", 5000, "FAVORITE")
    assert result == "win"
    assert net == 5000


def test_settle_pick_loss():
    result, net = settle_pick("FAVORITE", 5000, "UNDERDOG")
    assert result == "loss"
    assert net == -5000


def test_settle_pick_push():
    result, net = settle_pick("FAVORITE", 5000, "push")
    assert result == "push"
    assert net == 0


def test_settle_pick_voided():
    result, net = settle_pick("FAVORITE", 5000, "voided")
    assert result == "voided"
    assert net == 0


def test_settle_pick_winner_none():
    # None winner (game not yet settled) doesn't match any side → treated as loss
    result, net = settle_pick("FAVORITE", 5000, None)
    assert result == "loss"
    assert net == -5000


# ── compute_penalty_amount ─────────────────────────────────────────────────────

def test_first_miss():
    assert compute_penalty_amount(1) == -5_000


def test_second_consecutive_miss():
    assert compute_penalty_amount(2) == -10_000


def test_third_consecutive_miss():
    assert compute_penalty_amount(3) == -15_000


def test_penalty_escalates_linearly():
    for n in range(1, 6):
        assert compute_penalty_amount(n) == -5_000 * n


# ── compute_player_week_end_points ────────────────────────────────────────────

def test_week_end_points_win():
    # Win 5000: 25000 + 5000 = 30000
    result = compute_player_week_end_points(
        25_000,
        settlements=[{"net_profit": 5000}],
        penalties=[],
    )
    assert result == 30_000


def test_week_end_points_loss():
    result = compute_player_week_end_points(
        25_000,
        settlements=[{"net_profit": -5000}],
        penalties=[],
    )
    assert result == 20_000


def test_week_end_points_with_penalty():
    # 25000 + 0 (no picks settled) - 5000 (penalty) = 20000
    result = compute_player_week_end_points(
        25_000,
        settlements=[],
        penalties=[{"amount": -5000, "waived": False}],
    )
    assert result == 20_000


def test_week_end_points_waived_penalty_excluded():
    # Waived penalty should NOT be applied
    result = compute_player_week_end_points(
        25_000,
        settlements=[],
        penalties=[{"amount": -5000, "waived": True}],
    )
    assert result == 25_000


def test_week_end_points_clamps_to_zero():
    # Points can't go below 0
    result = compute_player_week_end_points(
        1_000,
        settlements=[{"net_profit": -5000}],
        penalties=[],
    )
    assert result == 0


def test_week_end_points_multiple_settlements_and_penalty():
    # 25000 + 5000 (win) - 3000 (loss) - 5000 (penalty) = 22000
    result = compute_player_week_end_points(
        25_000,
        settlements=[{"net_profit": 5000}, {"net_profit": -3000}],
        penalties=[{"amount": -5000, "waived": False}],
    )
    assert result == 22_000


def test_week_end_points_already_eliminated():
    # Eliminated player (0 points) — penalty can't push below zero; clamp holds
    result = compute_player_week_end_points(
        0,
        settlements=[],
        penalties=[{"amount": -5000, "waived": False}],
    )
    assert result == 0
