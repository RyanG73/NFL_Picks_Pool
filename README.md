# NFL Picks Pool

Fully automated NFL picks pool web app. 40–50 players, $50 buy-in, 25,000 starting points, up to 3 ATS bets/week. Public leaderboard, magic-link picks form, live score updates, automated emails.

**Tech:** FastAPI + Jinja2 + htmx + Tailwind · Supabase Postgres · Vercel · GitHub Actions · The Odds API · Resend

---

## First-time setup checklist

### 1. Create accounts (all free)

| Service | URL | What for |
|---|---|---|
| Supabase | https://supabase.com | Database + RPC functions |
| Vercel | https://vercel.com | Hosting + short cron jobs |
| The Odds API | https://the-odds-api.com | Weekly spread data |
| Resend | https://resend.com | Automated emails |

### 2. Set up Supabase

1. Create a new project at supabase.com
2. Go to **SQL Editor** and run migrations in order:
   ```
   migrations/001_init.sql              ← tables + views
   migrations/002_functions.sql         ← stored procedures
   migrations/004_games_team_unique.sql ← unique constraint (required)
   # skip 003_seed_example.sql in prod — dev seed only
   ```
3. Copy your project URL and **service role key** (Settings → API)

### 3. Configure environment variables

```bash
cp .env.example .env
# edit .env with your values
```

| Variable | Where to get it |
|---|---|
| `SUPABASE_URL` | Supabase → Settings → API → Project URL |
| `SUPABASE_SERVICE_KEY` | Supabase → Settings → API → service_role key |
| `RESEND_API_KEY` | Resend dashboard → API Keys |
| `FROM_EMAIL` | A verified domain/email in Resend |
| `ODDS_API_KEY` | The Odds API dashboard |
| `APP_URL` | Your Vercel deployment URL |
| `ADMIN_USERNAME` | Choose anything (HTTP Basic auth for `/admin/`) |
| `ADMIN_PASSWORD` | Choose something strong |
| `CURRENT_SEASON` | `2026` |

### 4. Deploy to Vercel

```bash
npm i -g vercel
vercel login
vercel
```

Add every `.env` variable in Vercel dashboard → Settings → Environment Variables.

> **Vercel plan note**: The `vercel.json` cron for pick-locking runs every 5 minutes (`*/5 * * * *`). This requires the **Vercel Pro** plan ($20/mo). On Hobby (free), cron jobs fire at most daily — pick locking will still work correctly via server-side validation in the picks form; only the DB `locked_at` field will lag until Tuesday settlement. If staying on Hobby, remove the `lock-and-reveal` cron from `vercel.json` and rely on the GitHub Actions `cron-lock-and-reveal.yml` (fires Saturday afternoon).

### 5. Set GitHub Secrets

Repo → Settings → Secrets and Variables → Actions:

```
SUPABASE_URL  SUPABASE_SERVICE_KEY  RESEND_API_KEY  ODDS_API_KEY
FROM_EMAIL  FROM_NAME  APP_URL  ADMIN_EMAIL
```

Variables (not secrets): `CURRENT_SEASON = 2026`

> **`CRON_SECRET`** is used only by the Vercel cron endpoints (not GitHub Actions) — add it
> to Vercel dashboard → Settings → Environment Variables, not GitHub Secrets.
> Generate with: `python -c "import secrets; print(secrets.token_hex(32))"`

### 6. First season kickoff (~2 weeks before Week 1)

```bash
# Add players via admin dashboard
open https://your-app.vercel.app/admin/

# Dry-run spread fetcher to verify API wiring
python jobs/pull_spreads.py --week 1 --season 2026 --dry-run
```

---

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn api.main:app --reload
# → http://localhost:8000
```

Local Supabase (optional):
```bash
supabase start   # starts local Postgres
supabase db reset  # applies all migrations
```

---

## Running jobs manually (all support `--dry-run`)

```bash
python jobs/pull_spreads.py       --week 1 --season 2026 --dry-run
python jobs/send_reminders.py     --week 1 --season 2026 --dry-run
python jobs/lock_and_reveal.py    --week 1 --season 2026 --dry-run
python jobs/poll_live_scores.py   --week 1 --season 2026 --once
python jobs/settle_week.py        --week 1 --season 2026 --dry-run
python jobs/detect_cancellations.py --week 1 --season 2026 --dry-run
```

## Validating settlement logic

```bash
# Replay 2025 season (needs Historical_Results/ CSVs)
python jobs/replay_test.py --season 2025 --show-diffs

# End-to-end smoke test (needs live Supabase connection)
make smoke WEEK=1 SEASON=2026
```

Replay: validates settlement logic against 2025 historical data. 0 mismatches = correct.

Smoke test: seeds 3 fake players + 2 games, submits picks, locks, simulates scores, settles, verifies outcomes, then tears down all seeded data. Run this against staging before going live.

---

## Weekly automated timeline

| Day | Time ET | Action |
|---|---|---|
| Wednesday | 8:00am | Fetch spreads → update DB → send Wed email |
| Friday | 8:00pm | Reminder to players who haven't picked |
| Saturday | ~1pm ET | Apply no-bet penalties → send picks reveal email (fires after noon lock) |
| Thu/Sat/Sun/Mon | Game windows | Poll ESPN every 5 min for live scores (Sat = playoff weeks) |
| Tuesday | 9:00am | Settle picks with final scores → advance week_log |

---

## Rules quick-reference

- 25,000 starting pts · $50 buy-in (Venmo @Ryan-Gerda)
- 1–3 picks/week ATS · min 500 pts · increments of 500 · max = current balance
- Thursday games lock at kickoff · Sunday/Monday games lock **Saturday noon ET**
- Miss a week: −5,000 pts (escalates +5,000 per consecutive miss)
- Tie against spread → push (refund) · Cancelled game → voided (refund)
- 0 points → eliminated · Top 15% of paid players win prizes at Super Bowl · ties split evenly