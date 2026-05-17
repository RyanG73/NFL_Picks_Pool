-- NFL Picks Pool — Initial Schema
-- Run once in Supabase SQL editor (or via supabase db push)

-- ── Players ────────────────────────────────────────────────────────────────
create table if not exists players (
  id              uuid primary key default gen_random_uuid(),
  name            text not null,
  email           text not null unique,
  magic_token     text not null unique default encode(gen_random_bytes(24), 'hex'),
  paid_buyin      boolean not null default false,
  starting_points integer not null default 25000,
  is_active       boolean not null default true,
  created_at      timestamptz not null default now()
);

-- ── Games ──────────────────────────────────────────────────────────────────
create table if not exists games (
  id              uuid primary key default gen_random_uuid(),
  season          integer not null,
  week            integer not null,          -- 1‥22 incl. playoffs
  espn_event_id   text,
  home_team       text not null,
  away_team       text not null,
  favorite_team   text not null,             -- home_team or away_team
  underdog_team   text not null,
  spread          numeric(4,1) not null,     -- positive; favorite is favored by this
  kickoff_at      timestamptz not null,
  home_score      integer,
  away_score      integer,
  status          text not null default 'scheduled'
                    check (status in ('scheduled','in_progress','final','voided','postponed')),
  voided_reason   text,
  created_at      timestamptz not null default now(),
  unique (season, week, espn_event_id)
);

-- ── Picks ──────────────────────────────────────────────────────────────────
-- One row per player per game. Upsert on resubmit before lock.
create table if not exists picks (
  id              uuid primary key default gen_random_uuid(),
  player_id       uuid not null references players(id) on delete cascade,
  game_id         uuid not null references games(id) on delete cascade,
  pick_side       text not null check (pick_side in ('FAVORITE','UNDERDOG')),
  pick_amount     integer not null check (pick_amount >= 500 and pick_amount % 500 = 0),
  submitted_at    timestamptz not null default now(),
  locked_at       timestamptz,               -- set when game kicks off
  unique (player_id, game_id)
);

-- ── Settlements ────────────────────────────────────────────────────────────
-- Written by settle_week.py after final scores are available (Tuesday).
create table if not exists settlements (
  id              uuid primary key default gen_random_uuid(),
  pick_id         uuid not null references picks(id) on delete cascade unique,
  result          text not null check (result in ('win','loss','push','voided')),
  net_profit      integer not null,          -- +pick_amount win, -pick_amount loss, 0 push/voided
  settled_at      timestamptz not null default now()
);

-- ── Penalties (missed weeks) ───────────────────────────────────────────────
create table if not exists penalties (
  id              uuid primary key default gen_random_uuid(),
  player_id       uuid not null references players(id) on delete cascade,
  season          integer not null,
  week            integer not null,
  amount          integer not null,          -- always negative e.g. -5000
  consecutive_misses integer not null default 1,
  waived          boolean not null default false,
  waived_reason   text,
  applied_at      timestamptz not null default now(),
  unique (player_id, season, week)
);

-- ── Admin audit log ────────────────────────────────────────────────────────
create table if not exists admin_audit_log (
  id              uuid primary key default gen_random_uuid(),
  action          text not null,
  payload         jsonb,
  performed_at    timestamptz not null default now()
);

-- ── Week log ───────────────────────────────────────────────────────────────
-- Snapshot of each player's points at end of each week (derived + cached).
-- Written by settle_week.py; used for leaderboard history & season-long charts.
create table if not exists week_log (
  id              uuid primary key default gen_random_uuid(),
  player_id       uuid not null references players(id) on delete cascade,
  season          integer not null,
  week            integer not null,
  start_points    integer not null,
  end_points      integer,                   -- null until week settled
  unique (player_id, season, week)
);

-- ── Broadcast messages ─────────────────────────────────────────────────────
create table if not exists broadcasts (
  id              uuid primary key default gen_random_uuid(),
  subject         text not null,
  body_html       text not null,
  banner_text     text,                      -- shown in-app if set
  sent_at         timestamptz,
  created_at      timestamptz not null default now()
);

-- ── Views ──────────────────────────────────────────────────────────────────

-- Live standings for a given season+week, accounting for:
--   starting_points + sum(settled net_profit) + sum(active penalties)
create or replace view standings_v as
select
  p.id                                          as player_id,
  p.name,
  p.paid_buyin,
  p.is_active,
  wl.season,
  wl.week,
  wl.start_points,
  wl.end_points,
  coalesce(wl.end_points, wl.start_points)      as current_points,
  coalesce(wl.end_points, wl.start_points)
    - wl.start_points                           as week_profit,
  case
    when coalesce(wl.end_points, wl.start_points) <= 0 then true
    else false
  end                                           as is_eliminated
from players p
join week_log wl on wl.player_id = p.id
order by wl.season, wl.week, coalesce(wl.end_points, wl.start_points) desc;

-- Quick view: current week picks with game info (used on the picks-reveal page)
create or replace view picks_reveal_v as
select
  pk.id                   as pick_id,
  pl.name                 as player_name,
  pl.id                   as player_id,
  g.season,
  g.week,
  g.home_team,
  g.away_team,
  g.favorite_team,
  g.underdog_team,
  g.spread,
  g.kickoff_at,
  g.status                as game_status,
  g.home_score,
  g.away_score,
  pk.pick_side,
  case pk.pick_side
    when 'FAVORITE' then g.favorite_team
    else g.underdog_team
  end                     as pick_team_name,
  pk.pick_amount,
  pk.locked_at,
  s.result,
  s.net_profit
from picks pk
join players pl on pl.id = pk.player_id
join games   g  on g.id  = pk.game_id
left join settlements s on s.pick_id = pk.id;

-- Per-game pool totals (shown on picks-by-team heatmap)
create or replace view game_pick_totals_v as
select
  g.id            as game_id,
  g.season,
  g.week,
  g.favorite_team,
  g.underdog_team,
  g.spread,
  g.kickoff_at,
  g.status,
  coalesce(sum(case when pk.pick_side = 'FAVORITE' then pk.pick_amount end), 0) as favorite_points,
  coalesce(sum(case when pk.pick_side = 'UNDERDOG' then pk.pick_amount end), 0) as underdog_points,
  count(case when pk.pick_side = 'FAVORITE' then 1 end)                          as favorite_count,
  count(case when pk.pick_side = 'UNDERDOG' then 1 end)                          as underdog_count
from games g
left join picks pk on pk.game_id = g.id
group by g.id, g.season, g.week, g.favorite_team, g.underdog_team,
         g.spread, g.kickoff_at, g.status;
