-- Migration 002: DB helper functions
-- Run after 001_init.sql

-- ── lock_kicked_off_picks ──────────────────────────────────────────────────
-- Called by the Vercel /api/cron/lock-and-reveal endpoint.
-- Locks any pick whose game kickoff has passed and whose locked_at is still NULL.
-- Idempotent: safe to call repeatedly.

-- sat_noon: if provided and as_of >= sat_noon, ALL remaining unlocked picks lock
-- at min(game.kickoff_at, sat_noon) — the "Saturday noon hard lock" rule.
create or replace function lock_kicked_off_picks(
  as_of    timestamptz default now(),
  sat_noon timestamptz default null
)
returns integer
language plpgsql
as $$
declare
  updated_count integer;
begin
  update picks
  set locked_at = case
    when sat_noon is not null and as_of >= sat_noon
      then least(games.kickoff_at, sat_noon)
    else games.kickoff_at
  end
  from games
  where picks.game_id = games.id
    and picks.locked_at is null
    and games.status != 'voided'
    and (
      games.kickoff_at <= as_of
      or (sat_noon is not null and as_of >= sat_noon)
    );

  get diagnostics updated_count = row_count;
  return updated_count;
end;
$$;


-- ── player_current_points ──────────────────────────────────────────────────
-- Returns a player's current point balance for a given season.
-- Used by the picks form to validate bet amounts.

create or replace function player_current_points(p_player_id uuid, p_season integer)
returns integer
language sql
stable
as $$
  select coalesce(
    (
      select start_points
      from week_log
      where player_id = p_player_id
        and season = p_season
      order by week desc
      limit 1
    ),
    25000
  );
$$;


-- ── week_committed_points ─────────────────────────────────────────────────
-- Returns how many points a player has committed in unlocked picks this week.
-- Used server-side to enforce the "max bet = current balance" rule.

create or replace function week_committed_points(
  p_player_id uuid,
  p_season    integer,
  p_week      integer
)
returns integer
language sql
stable
as $$
  select coalesce(sum(pk.pick_amount), 0)::integer
  from picks pk
  join games g on g.id = pk.game_id
  where pk.player_id = p_player_id
    and g.season     = p_season
    and g.week       = p_week
    and pk.locked_at is null;   -- only count unlocked picks
$$;


-- ── settle_game_picks ──────────────────────────────────────────────────────
-- Batch-settle all picks for a game after final scores are confirmed.
-- Called from settle_week.py but available as RPC for one-off corrections.

create or replace function settle_game_picks(
  p_game_id     uuid,
  p_home_score  integer,
  p_away_score  integer
)
returns integer    -- number of picks settled
language plpgsql
as $$
declare
  game_rec    games%rowtype;
  fav_score   integer;
  dog_score   integer;
  diff        numeric;
  ats_winner  text;
  pick_rec    picks%rowtype;
  result_lbl  text;
  net         integer;
  count       integer := 0;
begin
  -- Fetch game
  select * into game_rec from games where id = p_game_id;
  if not found then
    raise exception 'Game % not found', p_game_id;
  end if;
  if game_rec.status = 'voided' then
    -- Void all picks for this game
    insert into settlements (pick_id, result, net_profit)
    select pk.id, 'voided', 0
    from picks pk
    where pk.game_id = p_game_id
    on conflict (pick_id) do update set result = 'voided', net_profit = 0;
    return (select count(*) from picks where game_id = p_game_id);
  end if;

  -- Determine which team is home vs which is favorite
  if game_rec.home_team = game_rec.favorite_team then
    fav_score := p_home_score;
    dog_score := p_away_score;
  else
    fav_score := p_away_score;
    dog_score := p_home_score;
  end if;

  diff := fav_score - dog_score;

  -- ATS result
  if diff > game_rec.spread then
    ats_winner := 'FAVORITE';
  elsif diff < game_rec.spread then
    ats_winner := 'UNDERDOG';
  else
    ats_winner := 'push';
  end if;

  -- Update game scores + status
  update games set
    home_score = p_home_score,
    away_score = p_away_score,
    status = 'final'
  where id = p_game_id;

  -- Settle each pick
  for pick_rec in select * from picks where game_id = p_game_id loop
    if ats_winner = 'push' then
      result_lbl := 'push';
      net        := 0;
    elsif pick_rec.pick_side = ats_winner then
      result_lbl := 'win';
      net        := pick_rec.pick_amount;
    else
      result_lbl := 'loss';
      net        := -pick_rec.pick_amount;
    end if;

    insert into settlements (pick_id, result, net_profit)
    values (pick_rec.id, result_lbl, net)
    on conflict (pick_id) do update
      set result = excluded.result, net_profit = excluded.net_profit;

    count := count + 1;
  end loop;

  return count;
end;
$$;


-- ── active_banner ─────────────────────────────────────────────────────────
-- Quick helper for reading the most-recent active broadcast banner.

create or replace function active_banner()
returns text
language sql
stable
as $$
  select banner_text
  from broadcasts
  where banner_text is not null
    and sent_at is not null
  order by sent_at desc
  limit 1;
$$;
