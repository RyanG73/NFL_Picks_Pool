# NFL Picks Pool — Operations Runbook

Quick reference for common operational situations. All admin actions require
the admin username/password (HTTP Basic auth at `/admin/`).

---

## Pre-season setup (one-time, ~2 weeks before Week 1)

1. **Run migrations in Supabase SQL Editor** (in order):
   ```
   001_init.sql → 002_functions.sql → 004_games_team_unique.sql
   ```
   Skip 003_seed_example.sql in production.

2. **Add players** via `/admin/` → "Add Player" form.
   Each player gets a magic link emailed automatically.

3. **Confirm Venmo payments** — toggle "Paid" in admin when money arrives.

4. **Dry-run week 1 spreads** (after Odds API key is set):
   ```bash
   python jobs/pull_spreads.py --week 1 --season 2026 --dry-run
   ```

5. **Send onboarding email** — use admin broadcast to all players with
   pool rules link and reminder to bookmark their picks URL.

---

## Weekly operations (automated — verify each week)

| Day | Time ET | What runs | How to verify |
|---|---|---|---|
| Wednesday | 8am | Pull spreads + send Wed email | Check `/` shows new games |
| Friday | 8pm | Send pick reminders | Check GitHub Actions log |
| Saturday | 11:59am | Lock kicks + apply no-bet penalties | Check `/admin/` penalties section |
| Thu/Sun/Mon | Game windows | Poll ESPN live scores | Check game scores update on `/` |
| Tuesday | 9am | Settle week + advance balances | Check leaderboard + week_log |

---

## "Spread didn't import" (Wednesday job failed)

1. Check GitHub Actions → `cron-pull-spreads.yml` log for the error.
2. Common causes:
   - Odds API quota exceeded (500 req/mo free tier — one per week is fine)
   - NFL schedule not yet posted (early in offseason)
   - API key wrong/expired
3. **Manual fix**: run locally with the correct week number:
   ```bash
   python jobs/pull_spreads.py --week N --season 2026
   ```
4. If games were partially inserted, the job is idempotent — safe to rerun.

---

## "ESPN returned a bad score" (wrong score in DB)

1. Go to `/admin/` → Games section → find the game.
2. Click "Correct Score" and enter the right home/away scores.
3. Re-run settlement for that week to recompute picks using the corrected score:
   ```bash
   python jobs/settle_week.py --week N --season 2026
   ```
   (Idempotent — will skip already-settled picks and re-settle corrected ones.)

---

## "Magic link broken for player X"

1. Go to `/admin/` → Players → find the player → "Resend Link".
2. The same permanent token is used (it never changes).
3. If the player's email bounced, update their email manually in Supabase
   table editor, then resend.

---

## "Game was postponed / cancelled"

1. The hourly `detect_cancellations` job flags postponed games automatically.
2. Check your email (ADMIN_EMAIL) for an alert with the game name.
3. Go to `/admin/` → Games → "Void Game" with a reason.
4. All picks for that game are automatically refunded (settlement writes
   `result='voided', net_profit=0` for each pick).

---

## "Player wants to waive their no-bet penalty"

1. Go to `/admin/` → find the penalty in the Penalties section.
2. Click "Waive" and enter a reason (this is logged in the audit trail).
3. The next settlement run will skip the waived penalty in the balance calc.

---

## "Need to manually override a player's picks"

1. Go to `/admin/picks/<player_id>/<week>` (linked from admin dashboard).
2. Edit pick sides and amounts directly.
3. All changes are logged in the audit trail.

---

## "Player is eliminated (0 points) — what happens?"

- They stay on the leaderboard, sorted last, marked ELIMINATED.
- They receive no further no-bet penalties (skipped automatically).
- Their picks form still works but they can't bet (no points available).
- They can still pick 0-amount games... actually, min bet is 500 points so
  an eliminated player with 0 points cannot place any picks. The form will
  show "0 available" and reject any pick attempt. This is correct behavior.

---

## Season end (after Super Bowl, Week 22)

1. Let the Tuesday settlement job run for Week 22.
2. Check final standings at `/week/22`.
3. Export final balances from Supabase for prize payout tracking.
4. Announce winners via admin broadcast.
5. No cleanup needed — the DB retains all season data.

---

## Common Supabase queries for debugging

```sql
-- Who has picks for current week?
select p.name, count(pk.id) as picks, sum(pk.pick_amount) as total
from players p
left join picks pk on pk.player_id = p.id
join games g on g.id = pk.game_id
where g.season = 2026 and g.week = 1
group by p.name order by p.name;

-- Current standings
select name, current_points, is_eliminated
from standings_v
where season = 2026 and week = 1
order by current_points desc;

-- This week's settlements
select p.name, g.home_team, g.away_team, pk.pick_side, pk.pick_amount,
       s.result, s.net_profit
from settlements s
join picks pk on pk.id = s.pick_id
join players p on p.id = pk.player_id
join games g on g.id = pk.game_id
where g.season = 2026 and g.week = 1
order by p.name;

-- Audit log (last 20 actions)
select action, payload, performed_at
from admin_audit_log
order by performed_at desc
limit 20;
```
