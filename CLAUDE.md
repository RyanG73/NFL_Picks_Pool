# Project: NFL_Picks_Pool

## Purpose
Fully automated NFL picks pool web app (40-50 players, $50 buy-in, 25k starting points, 3 ATS bets/week, 22-week season including playoffs). Target launch: 2026 NFL season kickoff (Sept 2026).

## Tech Stack
- FastAPI + Jinja2 + htmx + Tailwind (Python end-to-end, Vercel hosting)
- Supabase Postgres (free tier, 500MB)
- GitHub Actions (free tier, scheduled Python cron jobs)
- Resend (email, free tier 3k/mo)
- The Odds API (weekly spreads, free tier 500 req/mo)
- ESPN public scoreboard API (live scores, stdlib-only, no API key)
- Magic-link auth per player (no login required for viewers)

## Historical Data
- `Historical_Results/Archive_2025/` — 2025 season CSVs (pick_log, line_log, week_log, no_bet_log); not committed (contains player PII)
- `Historical_Code/` — original R scripts (saturday.R, tuesday.R, wednesday.R); not committed
- `Rules/` — 2025 rules PDF; not committed
- The CSV data is used by `jobs/replay_test.py` to validate settlement logic; CI skips gracefully if not present

## Key Design Decisions
- Per-game kickoff locks (not Saturday lock-all) — rule change from the 2025 R-based system
- Picks form: 3 slots max, must submit all at once; stale picks (changed games) are deleted on resubmit
- settlement.py is pure logic; settle_week.py does all DB writes; idempotent re-runs are safe
- No-bet penalty: -5000 × consecutive misses, skips eliminated players (0 pts)
- ESPN week mapping: pool weeks 1-18 = seasontype 2, week 19→wk1, 20→wk2, 21→wk3, 22→wk5 (Super Bowl)

## Running Locally
```bash
make install   # pip install -r requirements.txt
make dev       # uvicorn api.main:app --reload
make replay    # validate 2025 settlement (needs Historical_Results/ data)
```
