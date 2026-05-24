"""
Tuesday ~18:00 ET — send personalized Week N results emails after settlement runs.

Each player gets their own email showing:
  - Each pick they made: team, result (WIN/LOSS/PUSH/VOID), net P&L
  - Weekly P&L total
  - Current points balance
  - Current standings rank (and prize position if applicable)

Run AFTER settle_week.py — standings_v must reflect settled results.

Usage: python jobs/send_settlement_email.py --week 1 --season 2026 [--dry-run]
"""
import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from api.lib import db, email_send
from api.lib.timewall import compute_prize_ladder, apply_prize_ladder


def main(week: int, season: int, dry_run: bool = False):
    print(f"[send_settlement_email] season={season} week={week} dry_run={dry_run}")

    players = db.get_all_players()
    if not players:
        print("  No active players found — aborting")
        return

    # Picks with results (picks_reveal_v includes result + net_profit post-settlement)
    picks_raw = db.get_week_picks_reveal(season, week)
    picks_by_player: dict[str, list[dict]] = {}
    for pick in picks_raw:
        picks_by_player.setdefault(pick["player_id"], []).append(pick)
    print(f"  {len(picks_raw)} settled picks for {len(picks_by_player)} players")

    # Standings with prize positions
    standings = db.get_standings(season, week)
    if not standings:
        print(f"  No standings for season={season} week={week} — has settlement run yet?")
        return
    paid_count = sum(1 for p in players if p.get("paid_buyin"))
    prizes = compute_prize_ladder(max(paid_count, 1))
    standings = apply_prize_ladder(standings, prizes)

    # Penalties applied this week (for no-pick notice)
    from api.lib.db import get_client
    penalty_rows = (
        get_client()
        .table("penalties")
        .select("player_id, amount, consecutive_misses, waived")
        .eq("season", season)
        .eq("week", week)
        .eq("waived", False)
        .execute()
        .data
    )
    penalties_by_player = {r["player_id"]: r for r in penalty_rows}

    if dry_run:
        for player in players:
            pid = player["id"]
            my_picks = picks_by_player.get(pid, [])
            pnl = sum(p.get("net_profit") or 0 for p in my_picks)
            penalty = penalties_by_player.get(pid)
            pick_summary = ", ".join(
                f"{p.get('pick_team_name','?')} {p.get('result','?').upper() if p.get('result') else 'PENDING'}"
                for p in my_picks
            )
            print(f"  {player['name']}: P&L={pnl:+,} [{pick_summary or 'no picks'}]"
                  f"{' | PENALTY' if penalty else ''}")
        print("  (dry-run: no emails sent)")
        return

    email_send.send_settlement_results(
        players=players,
        week=week,
        season=season,
        picks_by_player=picks_by_player,
        standings=standings,
        penalties_by_player=penalties_by_player,
    )
    print(f"  Results emails sent to {len(players)} players")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--season", type=int, default=int(os.environ.get("CURRENT_SEASON", 2026)))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(args.week, args.season, args.dry_run)
