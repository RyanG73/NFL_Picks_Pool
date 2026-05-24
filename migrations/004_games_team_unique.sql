-- Migration 004: Add unique(season, week, home_team, away_team) to games table
--
-- Background: the app keys operational matching by home_team + away_team.
-- espn_event_id is still kept for ESPN import deduplication, but team names
-- are the natural game identity for the pool.
--
-- Run after 001_init.sql and 002_functions.sql (skip 003_seed_example.sql in prod)

-- Add unique constraint on team names per week (the natural game identity)
alter table games
  add constraint games_season_week_teams_unique
  unique (season, week, home_team, away_team);

comment on column games.espn_event_id is
  'Stores ESPN scoreboard event ID when available. Used for import deduplication; '
  'operational matching uses home_team + away_team.';
