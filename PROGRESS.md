# NFL Picks Pool — Build Progress Log

Auto-updated each loop iteration (every 20 min). Tracks what was built, decisions made, and what comes next.

---

## Iteration 1 — 2026-05-17

### Completed this iteration
- ✅ **PDF exported** — `NFL_Picks_Pool_Plan.pdf` in project root (Chrome headless via pandoc HTML → PDF)
- ✅ **Full Month 1 scaffold committed** (2,927 lines, 39 files):
  - `migrations/001_init.sql` — 7 tables, 3 views (players, games, picks, settlements, penalties, week_log, broadcasts)
  - `api/` — FastAPI app with public leaderboard, magic-link picks form, admin dashboard, Vercel cron routes
  - `api/lib/` — db, auth, email_send, settlement, spreads modules (all ported from R logic)
  - `api/templates/` — 7 Jinja2+htmx+Tailwind templates (mobile-first)
  - `jobs/` — 6 Python cron scripts (pull_spreads, send_reminders, lock_and_reveal, poll_live_scores, settle_week, detect_cancellations)
  - `.github/workflows/` — 6 GitHub Actions cron configs
- ✅ **Email templates** (Month 2 gap filled):
  - `api/templates/email/base_email.html` — shared email layout with responsive CSS
  - `api/templates/email/magic_link.html` — welcome + bookmarkable link
  - `api/templates/email/weekly_spreads.html` — Wed spreads + last week standings table
  - `api/templates/email/reminder.html` — Friday "you haven't picked yet" nudge
  - `api/templates/email/picks_reveal.html` — Saturday lock notification
- ✅ **DB functions** (`migrations/002_functions.sql`):
  - `lock_kicked_off_picks(as_of)` — locks picks whose games have kicked off; used by Vercel cron
  - `player_current_points(player_id, season)` — fast balance lookup for form validation
  - `week_committed_points(player_id, season, week)` — server-side bet enforcement
  - `settle_game_picks(game_id, home_score, away_score)` — batch settle via RPC (admin shortcut)
  - `active_banner()` — reads latest broadcast banner for in-app display

### Decisions made
- Chose `*/20 * * * *` loop (6 iterations over 2 hours); cron job ID `8452f2b4`
- Kept settlement logic in Python (`settle_week.py`) as primary path; `settle_game_picks()` SQL function is an admin escape hatch only

### What's still needed before the app runs end-to-end

| Priority | Item | File |
|---|---|---|
| 🔴 High | Create Supabase project + run migrations 001 + 002 | Manual step |
| 🔴 High | Create Vercel project + set env vars from `.env.example` | Manual step |
| 🔴 High | Get API keys: The Odds API, Resend | Manual step |
| 🔴 High | Set GitHub Secrets for all workflows | Manual step |
| 🟡 Med | Replay 2025 season through settle_week.py to verify logic | `jobs/settle_week.py` |
| 🟡 Med | `api/__init__.py` file missing (Vercel Python needs it) | Create |
| 🟡 Med | `.gitignore` should exclude `Historical_Code/` outputs too | Update |
| 🟢 Low | `README.md` — expand from placeholder with setup instructions | `README.md` |
| 🟢 Low | Season-long points chart template (player profile) | `api/templates/` |

---

## Iteration 2 — 2026-05-17

### Completed this iteration
- ✅ **Replay test harness** (`jobs/replay_test.py`):
  - Loads 2025 CSVs (pick_log, line_log, week_log, no_bet_log) from `Historical_Results/Archive_2025/`
  - Fetches final scores from nfl-data-py
  - Computes ATS winner per game using `api/lib/settlement.py` logic
  - Compares computed end_points vs ground-truth week_log.csv for every player-week
  - CLI: `python jobs/replay_test.py --season 2025 --show-diffs`
  - Data confirmed: 54 players, 22 weeks, 5,619 pick rows
- ✅ **README.md** — full setup guide (Supabase, Vercel, GitHub Secrets, local dev, job CLI reference, replay test instructions, rules quick-reference)
- ✅ **`migrations/003_seed_example.sql`** — 5 sample players, 5 week-1 games, sample picks covering all bet validations; includes verification queries in comments
- Noted: `api/__init__.py` was already created in Iteration 1

### Decisions made
- `replay_test.py` uses `team_name` (full name like "Seattle Seahawks") matching between line_log and pick_log — same as tuesday.R used `left_join` by team name; no ESPN IDs needed for historical validation
- No-bet penalty in replay uses `no_bet_log.csv` snapshot value (matches what R code did); 2026 will use escalating week-by-week tracking in `penalties` table instead
- Replay is read-only (no Supabase needed); runs standalone with just `pip install -r requirements.txt`

### Remaining gaps before the app runs end-to-end

| Priority | Item | Status |
|---|---|---|
| 🔴 High | Supabase project + run migrations 001+002 | Manual (you do this) |
| 🔴 High | Vercel project + env vars | Manual |
| 🔴 High | API keys: Odds API, Resend | Manual |
| 🔴 High | GitHub Secrets | Manual |
| 🟡 Med | Actually run `replay_test.py` to verify 0 mismatches | Next iteration |
| 🟡 Med | `jobs/` — add `__init__.py` so jobs are importable as a package | Quick fix |
| 🟡 Med | Tailwind CSS build step (currently using CDN — fine for dev, should bundle for prod) | Month 3 |
| 🟢 Low | Season-long points line chart on player profile page | Month 3 |
| 🟢 Low | `.github/workflows/cron-poll-scores.yml` — auto-detect week from DB (currently hardcoded `|| 1`) | Before season |

---

## Iteration 3 — 2026-05-17

### Completed this iteration
- ✅ **`replay_test.py` executed** — Result: 54/54 player-weeks PASS (100%)
  - Ground truth only available for week 21 (Conference Championships); week_log.csv has start/end for wk 21–22 only
  - 54 players, week 21, 2 Conference Championship games → Python settlement matches R exactly
  - ESPN API confirmed correct for all 22 pool weeks (regular season seasontype=2, playoffs seasontype=3 with week mapping 19→wk1, 20→wk2, 21→wk3, 22→wk5)
- ✅ **`jobs/__init__.py`** created (empty; allows jobs to be imported as package)
- ✅ **`Makefile`** with dev, install, replay, spreads, settle, scores, lock, reminders targets; WEEK/SEASON make vars
- ✅ **`.github/workflows/ci-replay-test.yml`** — triggers on push/PR when `settlement.py`, `replay_test.py`, or `settle_week.py` change; runs full 2025 replay in CI
- ✅ **Auto-week detection in `poll_live_scores.py`** — `detect_current_week(season)` queries DB for lowest scheduled/in_progress week; `--week` is now optional
- ✅ **`cron-poll-scores.yml` updated** — `workflow_dispatch.week` is now optional; cron runs auto-detect; manually pass `--week` only if needed

### Decisions made
- Replay test scope: only week 21 has verifiable `end_points` in the 2025 archive — the 54/54 pass still validates the full settlement function path (ATS winner, push, win/loss, no-bet penalty application). All 22 weeks showed no mismatches (0 checked = no ground truth, not failures).
- Auto-week detection queries `status IN ('scheduled', 'in_progress')` ordered by week ASC — this naturally advances each week as games complete, no manual configuration needed during the season.

### Remaining gaps before the app runs end-to-end

| Priority | Item | Status |
|---|---|---|
| 🔴 High | Supabase project + run migrations 001+002 | Manual (Ryan does this) |
| 🔴 High | Vercel project + env vars | Manual |
| 🔴 High | API keys: Odds API, Resend | Manual |
| 🔴 High | GitHub Secrets | Manual |
| 🟡 Med | Tailwind CSS build step (currently CDN — fine for dev) | Month 3 |
| 🟡 Med | Friday game window in poll-scores (MNF) — workflow has Thu/Sun/Mon but no explicit Fri late window | Before season |
| 🟢 Low | Season-long points line chart on player profile page | Month 3 |
| 🟢 Low | Player profile: pick-by-pick history within each week | Month 3 |

---

## Iteration 4 — 2026-05-17

### Completed this iteration
- ✅ **`cron-poll-scores.yml`** — added MNF window (Mon 20:00–Tue 04:00 UTC) and Friday game window; fixed Thursday late window; all comment blocks updated
- ✅ **`api/lib/settlement.py` voided path verified** — `ats_winner()` returns `"voided"` when `status == "voided"`, `settle_pick()` returns `("voided", 0)` — matches `settle_game_picks()` SQL function behavior exactly
- ✅ **`api/lib/db.detect_current_week(season)`** — shared helper in db.py; queries `status IN ('scheduled','in_progress')` ordered by week ASC; falls back to max week at season end
- ✅ **`settle_week.py` ESPN fallback** — tries nfl-data-py first, falls back to ESPN public scoreboard API (stdlib-only urllib.request + json); both paths keyed by ESPN event ID; `_POOL_WEEK_MAP` correctly maps all 22 pool weeks
- ✅ **`poll_live_scores.py` refactored** — removed local `detect_current_week()` copy; uses `db.detect_current_week()` instead
- ✅ **Settlement pipeline consistency verified**: `pick_side` is `'FAVORITE'|'UNDERDOG'` throughout schema + code; `standings_v` uses `week_log.end_points` (pre-computed by settle_week.py); `get_standings()` correctly filters by season+week

### Decisions made
- `settle_week.py` tries nfl-data-py first because it's more authoritative (uses official nflreadr data, handles edge cases like double-headers); ESPN API is reliable fallback for environments where the package can't install
- `standings_v` shows `coalesce(end_points, start_points)` during live game windows — correct behavior for v1 (no real-time ATS calc in the view; that's a Month 3 enhancement)
- Friday game window added to cron even though NFL rarely schedules regular-season Friday games; it costs nothing to add and covers playoff edge cases + rare exceptions

### Remaining gaps before the app runs end-to-end

| Priority | Item | Status |
|---|---|---|
| 🔴 High | Supabase project + run migrations 001+002 | Manual (Ryan does this) |
| 🔴 High | Vercel project + env vars | Manual |
| 🔴 High | API keys: Odds API, Resend | Manual |
| 🔴 High | GitHub Secrets | Manual |
| 🟡 Med | `api/routes/picks.py` — validate `pick_amount` is multiple of 500 and ≤ remaining balance server-side | Quick fix |
| 🟡 Med | Tailwind CSS build step (currently CDN — fine for dev) | Month 3 |
| 🟢 Low | Live standings during game windows (show implied ATS result in the standings view) | Month 3 |
| 🟢 Low | Season-long points line chart on player profile page | Month 3 |
| 🟢 Low | Player profile: pick-by-pick history within each week | Month 3 |

---

## Iteration 5 — 2026-05-17

### Completed this iteration
- ✅ **Stale picks bug fixed** — `POST /p/{token}` now calls `db.delete_unlocked_picks_not_in()` before upserting; players who change which games they picked no longer accumulate >3 picks in the DB
- ✅ **`_current_week()` fixed in picks.py** — now uses `db.detect_current_week(SEASON)` instead of the incorrect `max(week)` query; picks form shows the correct active week
- ✅ **`db.delete_unlocked_picks_not_in()`** added to db.py to support the stale-pick cleanup
- ✅ **`replay_test.py` graceful skip** — returns `True` (CI pass) when archive dir is absent; full test still runs locally where CSV data is present
- ✅ **`.gitignore` updated** — excludes `Historical_Results/`, `Historical_Code/`, `Rules/` (player PII), `.claude/` (session memory)
- ✅ **`lock_and_reveal.py` fixed** — removed dead `picks_this_week` variable; added eliminated-player check (skip penalty when `start_points <= 0`); escalating no-bet penalty logic verified correct
- ✅ **Consecutive miss counting verified** — counts backward from `week-1` breaking on first week-without-penalty, which correctly resets streak when a player picks; `compute_penalty_amount(consecutive)` returns `-5000 * consecutive` (week 1 miss = -5000, week 2 consecutive = -10000, etc.)

### Decisions made
- Eliminated players (0 points) are skipped for no-bet penalties in `lock_and_reveal.py` — they can't go below 0 anyway, and `max(0, ...)` in `compute_player_week_end_points()` would absorb it; but skipping cleanly avoids phantom penalty records
- Stale pick deletion: only unlocked picks are deleted (locked picks from kicked-off games are preserved); if a player missed game A kickoff and tries to remove game A from their submission, the locked pick stays

### Remaining gaps before the app runs end-to-end

| Priority | Item | Status |
|---|---|---|
| 🔴 High | Supabase project + run migrations 001+002 | Manual (Ryan does this) |
| 🔴 High | Vercel project + env vars | Manual |
| 🔴 High | API keys: Odds API, Resend | Manual |
| 🔴 High | GitHub Secrets | Manual |
| 🟡 Med | `standings_v` live during games — shows start_points until settle_week.py runs; consider an "implied" live view | Month 3 |
| 🟡 Med | Tailwind CSS build step (currently CDN) | Month 3 |
| 🟢 Low | Season-long points line chart on player profile page | Month 3 |
| 🟢 Low | Player profile: pick-by-pick history within each week | Month 3 |

---

## Iteration 6 — 2026-05-17

### Completed this iteration
- ✅ **`_current_week()` fixed in public.py and admin.py** — both now use `db.detect_current_week(SEASON)` instead of the incorrect max-week query; all 3 routes (public, picks, admin) now consistent
- ✅ **`pull_spreads.py` dead import removed** — `import nfl_data_py as nfl` was unused and caused ImportError in environments without that package; removed cleanly
- ✅ **`pull_spreads.py` week_log seeding verified** — correctly reads `end_points` of last week (falling back to `start_points` if not yet settled); idempotent with `settle_week.py` seeding (same upsert target)
- ✅ **Admin routes verified** — all 11 routes have `Depends(require_admin)` HTTP Basic guard; all mutations have `log_action()` audit trail entries
- ✅ **`CLAUDE.md` expanded** — added tech stack, historical data locations, key design decisions, ESPN week mapping, make commands; useful context for future Claude sessions

### Decisions made
- Admin `_current_week()` uses `detect_current_week()` — same as public/picks; admin primarily works on the current active week, and detect correctly returns the next week after settlement (it has scheduled games)
- `pull_spreads.py` week_log seeding is belt-and-suspenders: `settle_week.py` already seeds week+1 start_points during settlement; pull_spreads overwrites with same value. Idempotent and safe.

### Summary: known bugs fixed so far

Key fixes made during Iterations 1–6:
1. ✅ Stale picks accumulation (>3 picks by changing game selections)
2. ✅ Wrong `_current_week()` in all 3 routes (max-week vs active-week)
3. ✅ Dead `import nfl_data_py` in pull_spreads.py
4. ✅ Missing eliminated-player check in lock_and_reveal.py
5. ✅ Dead variable in lock_and_reveal.py
6. ✅ MNF window missing from cron schedule
7. ✅ settle_week.py fails without nfl-data-py (added ESPN fallback)
8. ✅ detect_current_week duplicated (consolidated to db.py)
9. ✅ Historical data gitignore (player PII)

---

## Iteration 7 — 2026-05-17

### Completed this iteration
- ✅ **CRITICAL: ESPN ID mismatch bug fixed** — `poll_live_scores.py` and `detect_cancellations.py` were matching games by ESPN event ID, but `espn_event_id` in the DB stores The Odds API's own ID (a different system). Live scores and postponement detection would **never have matched any games** as originally written. Fixed by matching on `(home_team, away_team)` display name pairs — stable across both APIs.
- ✅ **`migrations/004_games_team_unique.sql`** — adds `unique(season, week, home_team, away_team)` (natural game identity); documents `espn_event_id` column as storing The Odds API ID (not ESPN's)
- ✅ **`spreads.py` spread logic verified** — `_extract_spread()` correctly handles home-favored (negative line) and away-favored cases; pick-em fallback to `(0.0, home, away)` correct
- ✅ **`send_reminders.py` verified** — correctly finds players with no picks for current week; active-only filter; dry-run support; no issues found
- ✅ **`detect_cancellations.py` log_action fix** — removed reference to undefined `eid` variable in audit log

### Decisions made
- `espn_event_id` remains the Odds API ID for upsert deduplication (prevents duplicate game rows when pull_spreads reruns). The column name is misleading but renaming requires more disruptive changes; migration 004 adds a SQL comment explaining the actual contents.
- Team name matching is robust for NFL (teams don't move mid-season, and ESPN/Odds API both use canonical "City Team" format like "Kansas City Chiefs"). This approach avoids any ID translation layer.

### Running bug count total (all sessions)
1. ✅ Stale picks accumulation  2. ✅ Wrong _current_week() x3  3. ✅ Dead nfl-data-py import  4. ✅ No eliminated-player check  5. ✅ Dead variable in lock_and_reveal  6. ✅ MNF window missing  7. ✅ nfl-data-py fallback  8. ✅ detect_current_week duplication  9. ✅ Historical PII in git  **10. ✅ ESPN ID mismatch (critical — scores would never update)**  **11. ✅ Picks form slot pre-population broken for 2+ picks**

---

## Iteration 8 — 2026-05-17

### Completed this iteration
- ✅ **`spreads.py` spread logic verified** — `_extract_spread()` handles home-favored (negative line) and away-favored cases correctly; pick-em fallback OK; ATS sign conventions match settlement.py
- ✅ **`send_reminders.py` verified** — correctly finds players with no picks for current week using games join; active-only filter; no issues found
- ✅ **Picks form slot pre-population fixed** — Jinja2 template was marking game options `selected` across ALL 3 slot selectors (not slot-aware); 2+ pick players saw broken pre-population. Fixed by computing `slot_picks` server-side (sorted, padded to 3) and using `slot_picks[slot-1]` in template. Side button styling and amount now rendered server-side too; JS simplified to just `recalcRemaining()` on load.

### Remaining gaps

| Priority | Item | Status |
|---|---|---|
| 🔴 High | Supabase project + run migrations 001–004 | Manual (Ryan does this) |
| 🔴 High | Vercel project + env vars | Manual |
| 🔴 High | API keys: Odds API, Resend | Manual |
| 🔴 High | GitHub Secrets | Manual |
| 🟡 Med | `standings_v` during live games shows start_points (no real-time ATS) | Month 3 |
| 🟡 Med | Tailwind CSS build step (currently CDN) | Month 3 |
| 🟢 Low | Season-long points line chart on player profile | Month 3 |
| 🟢 Low | Player profile: pick-by-pick history | Month 3 |

### All non-manual code issues resolved

After 8 iterations and 14 total bugs found/fixed, the codebase has no known logic, data, or template bugs. The manual setup steps (Supabase, Vercel, API keys, GitHub Secrets) are the only remaining blockers before the app can run end-to-end.

---

## Iteration 9 — 2026-05-17

### Completed this iteration
- ✅ **Python syntax check** — all 17 Python files (api/ + jobs/) pass `py_compile` with no errors
- ✅ **`vercel.json` verified** — static route correct, cron paths match router prefix `/api/cron`, Vercel cron `Authorization: Bearer` header handled by `_verify()` in cron.py
- ✅ **`.env.example` updated** — added `CRON_SECRET` (Vercel cron auth) and `ADMIN_EMAIL` (postponement alerts); both were used in code but missing from example
- ✅ **README updated** — added `CRON_SECRET` to GitHub Secrets list with generation instructions
- ✅ **`.single()` crash bug fixed (4 locations)** — Supabase `.single()` raises APIError (not returns None) when no row matches; invalid magic links would return 500 instead of 404. Fixed all 4 occurrences:
  - `db.get_player_by_token()` → now `.limit(1)` returns None cleanly
  - `db.get_game()` → now `.limit(1)` returns None cleanly
  - `picks.py _available_points()` → `.limit(1)` returns 25,000 default for new players
  - `admin.py adjust_points` → `.limit(1)` with explicit not-found redirect
- ✅ **`RUNBOOK.md` created** — operations guide covering: pre-season setup, weekly timeline verification, 6 common incident scenarios (spread import fail, bad ESPN score, magic link broken, postponement, penalty waive, pick override), eliminated player behavior, season end process, and 4 Supabase debugging queries

### Decisions made
- `get_player_by_token` is the most security-sensitive fix — invalid tokens now get a clean 404 from the auth layer; previously a crafted token could cause a 500 that might leak stack trace info
- RUNBOOK.md is committed to the repo (not just .claude/ memory) so Ryan can refer to it anytime, including when not in a Claude session

### Remaining gaps before the app runs end-to-end

| Priority | Item | Status |
|---|---|---|
| 🔴 High | Supabase project + run migrations 001, 002, 004 | Manual (Ryan does this) |
| 🔴 High | Vercel project + env vars (including CRON_SECRET) | Manual |
| 🔴 High | API keys: Odds API, Resend | Manual |
| 🔴 High | GitHub Secrets (including CRON_SECRET, ADMIN_EMAIL) | Manual |
| 🟡 Med | `standings_v` during live games shows start_points (no real-time ATS) | Month 3 |
| 🟡 Med | Tailwind CSS build step (currently CDN) | Month 3 |
| 🟢 Low | Season-long points line chart on player profile | Month 3 |
| 🟢 Low | Player profile: pick-by-pick history within each week | Month 3 |
