-- Migration 004: Add unique(season, week, home_team, away_team) to games table
--
-- Background: espn_event_id stores The Odds API's own event ID (not ESPN's),
-- used only for deduplication on pull_spreads.py reruns. Live score matching
-- in poll_live_scores.py uses home_team + away_team names instead.
-- This migration adds a proper team-pair uniqueness constraint and documents
-- the espn_event_id purpose.
--
-- Run after 001_init.sql and 002_functions.sql (skip 003_seed_example.sql in prod)

-- Add unique constraint on team names per week (the natural game identity)
alter table games
  add constraint games_season_week_teams_unique
  unique (season, week, home_team, away_team);

-- Rename the column for clarity (espn_event_id actually stores Odds API IDs)
-- We keep it as-is for now to avoid breaking existing upsert logic, but add a comment.
comment on column games.espn_event_id is
  'Stores The Odds API event ID (not ESPN ID). Used for dedup on pull_spreads reruns. '
  'Live score matching uses home_team + away_team instead.';
