# Project: NFL_Picks_Pool

## Purpose
Fully automated NFL picks pool web app (40-50 players, $50 buy-in, 25k starting points, 3 ATS bets/week, 22-week season including playoffs). Target launch: 2026 NFL season kickoff (Sept 2026).

## Tech Stack
- FastAPI + Jinja2 + htmx + Tailwind (Python end-to-end, Vercel hosting)
- Supabase Postgres (free tier, 500MB)
- GitHub Actions (free tier, scheduled Python cron jobs)
- Resend (email, free tier 3k/mo)
- ESPN public scoreboard (weekly spreads, live scores, settlement scores; no API key required)
- nflverse games.csv (free spread cross-check, no API key required)
- Magic-link auth per player (no login required for viewers)

## Historical Data
- `Historical_Results/Archive_2025/` — 2025 season CSVs (pick_log, line_log, week_log, no_bet_log); not committed (contains player PII)
- `Historical_Code/` — original R scripts (saturday.R, tuesday.R, wednesday.R); not committed
- `Rules/` — 2025 rules PDF; not committed
- The CSV data is used by `jobs/replay_test.py` to validate settlement logic; CI skips gracefully if not present

## Key Design Decisions
- **Saturday-noon hard lock**: `effective_lock_at = min(game.kickoff_at, saturday_noon_ET)` — Thursday games lock at kickoff; all other games lock at Saturday noon ET. Enforced in `api/lib/timewall.py` (`is_locked()`, `saturday_noon_et()`), `api/routes/picks.py`, and `migrations/002_functions.sql`.
- Picks form: 3 slots max, must submit all at once; stale picks (changed games) are deleted on resubmit
- settlement.py is pure logic; settle_week.py does all DB writes; idempotent re-runs are safe
- No-bet penalty: -5000 × consecutive misses, skips eliminated players (0 pts)
- Dynamic prize ladder: top 15% of paid players, `compute_prize_ladder(paid_count)` and `apply_prize_ladder(standings, prizes)` in `timewall.py`
- Picks effective balance: `effective_available = available - locked_amount` where `locked_amount` = sum of already-locked Thursday picks; new unlocked picks are validated against this reduced budget, not the full weekly balance
- ESPN week mapping: pool weeks 1-18 = seasontype 2, week 19→wk1, 20→wk2, 21→wk3, 22→wk5 (Super Bowl)
- PostgREST embedded filters (`.eq("games.season", x)`) use LEFT JOIN — never filter parent rows. Always use game-ID prefetch + `.in_("game_id", ids)` pattern instead.
- ESPN scoreboard display names are the canonical team names in DB-facing code.
- `get_client()` in `db.py` uses `@lru_cache(maxsize=1)` — safe for Vercel serverless (one instance per cold start)

## Running Locally
```bash
make install   # pip install -r requirements.txt
make dev       # uvicorn api.main:app --reload
make replay    # validate 2025 settlement (needs Historical_Results/ data)
make smoke WEEK=1 SEASON=2026  # end-to-end pipeline test (needs live Supabase)
```
