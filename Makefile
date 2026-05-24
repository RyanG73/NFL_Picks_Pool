.PHONY: dev install lint replay smoke test week season help

# ── Local dev ──────────────────────────────────────────────────────────────
dev:
	uvicorn api.main:app --reload

install:
	pip install -r requirements.txt

# ── Validation ─────────────────────────────────────────────────────────────
replay:
	python jobs/replay_test.py --season 2025 --show-diffs

smoke:
	python jobs/smoke_test.py --season $(SEASON) --week $(WEEK) --skip-email --verbose

test:
	python -m pytest tests/ -v

# ── Jobs (dry-run by default) ──────────────────────────────────────────────
spreads:
	python jobs/pull_spreads.py --week $(WEEK) --season $(SEASON) --dry-run

reminders:
	python jobs/send_reminders.py --week $(WEEK) --season $(SEASON) --dry-run

lock:
	python jobs/lock_and_reveal.py --week $(WEEK) --season $(SEASON) --dry-run

settle:
	python jobs/settle_week.py --week $(WEEK) --season $(SEASON) --dry-run

scores:
	python jobs/poll_live_scores.py --week $(WEEK) --season $(SEASON) --once

# ── Helpers ────────────────────────────────────────────────────────────────
help:
	@echo "Usage:"
	@echo "  make dev          Start FastAPI dev server"
	@echo "  make install      pip install -r requirements.txt"
	@echo "  make test         Run pytest unit tests (tests/)"
	@echo "  make replay       Run 2025 replay test (validates settlement logic)"
	@echo "  make spreads WEEK=1 SEASON=2026   Dry-run spread fetch"
	@echo "  make settle  WEEK=1 SEASON=2026   Dry-run settlement"
	@echo "  make scores  WEEK=1 SEASON=2026   Fetch live scores (once)"
	@echo "  make smoke   WEEK=1 SEASON=2026   End-to-end smoke test (needs live Supabase)"
