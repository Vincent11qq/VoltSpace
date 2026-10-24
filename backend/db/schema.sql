-- ===========================================================================
-- VoltSpace — database schema (Supabase / PostgreSQL)
--
-- Run this in the Supabase SQL editor. It is idempotent, so re-running it is safe.
--
-- WHY THIS REPLACES THE ORIGINAL FILES
-- ------------------------------------
-- The first version (appliances.sql / profiles.sql / security.sql / connect.sql) was
-- written before the calculation API existed, and the two did not agree:
--
--   1. Column names/types differed from the API contract:
--        old: Power integer, Minutes numeric, Appliance text
--        API: power_watts, hours_per_day, days_per_month, quantity, voltage
--      Member B's own validation also used minutes, while the calculators work in
--      hours, so every stored row would have needed conversion in the frontend.
--   2. There was no tariff table, even though the bill calculator needs one.
--   3. The row-level-security policies were `to authenticated` with
--      `auth.uid() = user_id`, but the frontend has no sign-in flow, so every request
--      was anonymous -> `auth.uid()` is NULL -> inserts and reads both failed.
--      A schema that only works for a signed-in user needs the app to have sign-in.
--
-- This file keeps the good ideas (user-owned rows, RLS on everything) and fixes the
-- three problems: the columns now match the API exactly, a tariffs table exists, and a
-- `households` table is added so an anonymous device can still save its own data safely.
-- See docs/supabase.md for how to switch the backend from local SQLite to Supabase.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 1. Profiles (one row per auth user)
-- ---------------------------------------------------------------------------
create table if not exists public.profiles (
    id         uuid primary key references auth.users (id) on delete cascade,
    name       text,
    created_at timestamptz not null default now()
);

comment on table public.profiles is 'Display name for each authenticated user.';

-- Create a profile automatically when a user signs up.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.profiles (id, name)
    values (new.id, coalesce(new.raw_user_meta_data ->> 'name', split_part(new.email, '@', 1)))
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------------
-- 2. Appliances
--
-- One row per appliance in a user's household. Column names and units mirror
-- `ApplianceIn` in app/schemas.py exactly so there is no translation layer:
-- power is watts, usage is HOURS per day, days is per month.
-- ---------------------------------------------------------------------------
create table if not exists public.appliances (
    id             bigint generated always as identity primary key,
    user_id        uuid not null default auth.uid() references auth.users (id) on delete cascade,
    name           text not null check (length(btrim(name)) between 1 and 80),
    category       text check (category is null or length(category) <= 40),
    power_watts    numeric(10, 2) not null check (power_watts > 0 and power_watts <= 100000),
    hours_per_day  numeric(5, 2)  not null check (hours_per_day >= 0 and hours_per_day <= 24),
    days_per_month integer        not null default 30 check (days_per_month between 0 and 31),
    quantity       integer        not null default 1  check (quantity between 1 and 999),
    voltage        numeric(6, 2)  default 110 check (voltage is null or voltage > 0),
    power_factor   numeric(3, 2)  check (power_factor is null or power_factor between 0.1 and 1.0),
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);

comment on table public.appliances is
    'A user''s saved appliances. Units match the calculation API (W, hours/day).';

create index if not exists appliances_user_id_idx on public.appliances (user_id);

-- Keep updated_at honest without relying on the client.
create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists appliances_touch_updated_at on public.appliances;
create trigger appliances_touch_updated_at
    before update on public.appliances
    for each row execute function public.touch_updated_at();

-- ---------------------------------------------------------------------------
-- 3. Tariffs
--
-- Mirrors app/data/tariffs.json so the tariff data lives in one shape. The backend
-- keeps reading the JSON file (it must work offline); this table exists so Member B can
-- manage plans in the database and so the mobile client can read the same numbers.
-- ---------------------------------------------------------------------------
create table if not exists public.tariff_plans (
    id           text primary key,
    name_zh      text not null,
    name_en      text,
    type         text not null check (type in ('tiered', 'time_of_use', 'flat')),
    currency     text not null default 'TWD',
    unit         text not null default 'kWh',
    effective_from date,
    is_estimate  boolean not null default false,
    data         jsonb   not null,
    created_at   timestamptz not null default now()
);

comment on table public.tariff_plans is
    'Electricity plans. `data` holds the season/tier structure copied from tariffs.json.';

-- Public read: tariff data is not user-specific and the UI needs it before sign-in.
alter table public.tariff_plans enable row level security;

drop policy if exists "Tariffs are readable by everyone" on public.tariff_plans;
create policy "Tariffs are readable by everyone"
    on public.tariff_plans for select
    to anon, authenticated
    using (true);

-- ---------------------------------------------------------------------------
-- 4. Households
--
-- Why: the app supports anonymous use (a student opens it and types their appliances).
-- `auth.uid()` is NULL for those users, so `appliances.user_id` cannot be the only key.
-- A household row carries a random access token; the device keeps the token and sends it
-- in a header. Signed-in users additionally get their household linked to their account.
-- ---------------------------------------------------------------------------
create table if not exists public.households (
    id           uuid primary key default gen_random_uuid(),
    owner_id     uuid references auth.users (id) on delete set null default auth.uid(),
    access_token uuid not null default gen_random_uuid(),
    label        text,
    created_at   timestamptz not null default now()
);

comment on table public.households is
    'A saved appliance collection. access_token lets an anonymous device own its data.';

create index if not exists households_owner_idx on public.households (owner_id);
create unique index if not exists households_token_idx on public.households (access_token);

alter table public.appliances
    add column if not exists household_id uuid references public.households (id) on delete cascade;

create index if not exists appliances_household_idx on public.appliances (household_id);

-- ---------------------------------------------------------------------------
-- 5. Row level security
--
-- Two ways to own a row:
--   * signed in  -> owner_id / user_id equals auth.uid()
--   * anonymous  -> the request carries a household access token (checked by the
--                   backend with the service key; anon clients never get service rights)
-- ---------------------------------------------------------------------------
alter table public.profiles enable row level security;
alter table public.households enable row level security;
alter table public.appliances enable row level security;

-- profiles: a user sees and edits only their own row.
drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own"
    on public.profiles for select to authenticated
    using ((select auth.uid()) = id);

drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own"
    on public.profiles for update to authenticated
    using ((select auth.uid()) = id)
    with check ((select auth.uid()) = id);

drop policy if exists "profiles_insert_own" on public.profiles;
create policy "profiles_insert_own"
    on public.profiles for insert to authenticated
    with check ((select auth.uid()) = id);

-- households: the owner can read/update; creation is allowed while signed in.
drop policy if exists "households_select_own" on public.households;
create policy "households_select_own"
    on public.households for select to authenticated
    using ((select auth.uid()) = owner_id);

drop policy if exists "households_insert_own" on public.households;
create policy "households_insert_own"
    on public.households for insert to authenticated
    with check (owner_id is null or (select auth.uid()) = owner_id);

drop policy if exists "households_update_own" on public.households;
create policy "households_update_own"
    on public.households for update to authenticated
    using ((select auth.uid()) = owner_id)
    with check ((select auth.uid()) = owner_id);

drop policy if exists "households_delete_own" on public.households;
create policy "households_delete_own"
    on public.households for delete to authenticated
    using ((select auth.uid()) = owner_id);

-- appliances: signed-in users own their rows. Anonymous households are served by the
-- backend using the service key (which bypasses RLS by design, and is never shipped to
-- a client), so no anon policy is granted here.
drop policy if exists "All users are allowed to view information" on public.appliances;
drop policy if exists "All users are allowed to insert information" on public.appliances;
drop policy if exists "All users are allowed to update information" on public.appliances;
drop policy if exists "All users are allowed to delete information" on public.appliances;

drop policy if exists "appliances_select_own" on public.appliances;
create policy "appliances_select_own"
    on public.appliances for select to authenticated
    using ((select auth.uid()) = user_id);

drop policy if exists "appliances_insert_own" on public.appliances;
create policy "appliances_insert_own"
    on public.appliances for insert to authenticated
    with check ((select auth.uid()) = user_id);

drop policy if exists "appliances_update_own" on public.appliances;
create policy "appliances_update_own"
    on public.appliances for update to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

drop policy if exists "appliances_delete_own" on public.appliances;
create policy "appliances_delete_own"
    on public.appliances for delete to authenticated
    using ((select auth.uid()) = user_id);

-- ---------------------------------------------------------------------------
-- 6. Seed the tariff plans (matches app/data/tariffs.json)
-- ---------------------------------------------------------------------------
insert into public.tariff_plans (id, name_zh, name_en, type, effective_from, data)
values
    ('tw_residential_tiered',
     '台電住宅用電－累進（級距）電價',
     'Taipower residential - progressive (tiered) rate',
     'tiered', date '2024-04-01',
     '{"seasons": {"summer": {"tiers": [{"index":1,"up_to_kwh":120,"rate":1.68},{"index":2,"up_to_kwh":330,"rate":2.45},{"index":3,"up_to_kwh":500,"rate":3.70},{"index":4,"up_to_kwh":700,"rate":5.04},{"index":5,"up_to_kwh":1000,"rate":6.24},{"index":6,"up_to_kwh":null,"rate":8.46}]}, "non_summer": {"tiers": [{"index":1,"up_to_kwh":120,"rate":1.68},{"index":2,"up_to_kwh":330,"rate":2.16},{"index":3,"up_to_kwh":500,"rate":3.03},{"index":4,"up_to_kwh":700,"rate":4.14},{"index":5,"up_to_kwh":1000,"rate":5.07},{"index":6,"up_to_kwh":null,"rate":6.63}]}}}'::jsonb),
    ('tw_residential_tou',
     '台電住宅用電－時間電價（二段式，估算）',
     'Taipower residential - time-of-use (two-segment, estimated)',
     'time_of_use', date '2024-04-01',
     '{"seasons": {"summer": {"peak": 5.16, "off_peak": 2.13}, "non_summer": {"peak": 5.16, "off_peak": 1.90}}}'::jsonb),
    ('flat_rate_resell_reference',
     '單一費率參考（租屋常見房東轉售價）',
     'Flat-rate reference (typical rented-room resale price)',
     'flat', date '2025-01-01',
     '{"seasons": {"summer": {"rate": 5.5}, "non_summer": {"rate": 5.5}}}'::jsonb)
on conflict (id) do update
    set name_zh = excluded.name_zh,
        name_en = excluded.name_en,
        type = excluded.type,
        effective_from = excluded.effective_from,
        data = excluded.data;
