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

## Iteration 3 — (next ~20 min)

### Planned
- Run replay_test.py against the actual 2025 data and report results
- Add `jobs/__init__.py`
- Add GitHub Actions workflow for running replay_test as a CI check
- Wire up auto-week detection in poll_live_scores workflow
- Create a `Makefile` with common dev commands
