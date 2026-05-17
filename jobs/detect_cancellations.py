"""
Hourly (Wed–Tue) — poll ESPN for postponed/cancelled games and notify Ryan.

Any game with status POST or CANC is flagged in the DB as 'postponed'.
Ryan confirms void via the admin dashboard. Designed to be safe:
  - Never auto-voids; always requires human confirmation.
  - Idempotent: re-running won't duplicate flags.

Usage: python jobs/detect_cancellations.py --week 1 --season 2026 [--dry-run]
"""
import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

import httpx
from api.lib import db, email_send

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", os.environ.get("FROM_EMAIL", ""))


def fetch_postponed_ids() -> set[str]:
    """Return ESPN event IDs that are postponed or cancelled."""
    resp = httpx.get(ESPN_SCOREBOARD, timeout=10)
    resp.raise_for_status()
    events = resp.json().get("events", [])
    flagged = set()
    for event in events:
        status_type = event.get("status", {}).get("type", {})
        if status_type.get("shortDetail", "").upper() in ("POST", "CANC", "POSTPONED"):
            flagged.add(event["id"])
    return flagged


def main(week: int, season: int, dry_run: bool = False):
    print(f"[detect_cancellations] season={season} week={week}")

    postponed_espn_ids = fetch_postponed_ids()
    if not postponed_espn_ids:
        print("  No postponed/cancelled games detected")
        return

    games = db.get_games(season, week)
    newly_flagged = []
    for game in games:
        eid = game.get("espn_event_id", "")
        if eid not in postponed_espn_ids:
            continue
        if game["status"] in ("voided", "postponed"):
            continue  # Already handled
        print(f"  ⚠ Flagging postponed: {game['favorite_team']} vs {game['underdog_team']}")
        if not dry_run:
            db.update_game(game["id"], status="postponed")
            db.log_action("flag_postponed", {"game_id": game["id"], "espn_id": eid})
        newly_flagged.append(game)

    if newly_flagged and not dry_run and ADMIN_EMAIL:
        game_list = "\n".join(
            f"  - {g['favorite_team']} vs {g['underdog_team']} ({g['kickoff_at'][:16]})"
            for g in newly_flagged
        )
        body = f"""
<p>The following game(s) have been flagged as POSTPONED by ESPN:</p>
<pre>{game_list}</pre>
<p>Please review in the <a href="{os.environ.get('APP_URL', '')}/admin/">Admin Dashboard</a>
and <strong>void</strong> or <strong>restore</strong> each game as appropriate.</p>
<p>No bets have been settled yet for these games.</p>
"""
        import resend
        resend.api_key = os.environ.get("RESEND_API_KEY", "")
        resend.Emails.send({
            "from": os.environ.get("FROM_EMAIL", "picks@example.com"),
            "to": ADMIN_EMAIL,
            "subject": f"⚠ {len(newly_flagged)} game(s) postponed — action needed",
            "html": body,
        })
        print(f"  Alert sent to {ADMIN_EMAIL}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--season", type=int, default=int(os.environ.get("CURRENT_SEASON", 2026)))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(args.week, args.season, args.dry_run)
