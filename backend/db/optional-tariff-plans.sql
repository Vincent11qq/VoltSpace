-- ===========================================================================
-- VoltSpace — OPTIONAL: mirror the electricity prices into the database
--
-- You do NOT need this to run the app. The backend always calculates from
-- app/data/tariffs.json, because it must work offline and the prices are data the
-- calculation core owns (see app/calculators/electricity_bill.py).
--
-- Run this only if something else needs to read the prices from the database, for
-- example a mobile client that talks to Supabase directly, or Member B's tooling.
--
-- Keep it in sync with app/data/tariffs.json. The rates below are the MOEA adjustment
-- effective 2025-10-01 (summer 1.78/2.55/3.80/5.14/6.44/8.86,
-- non-summer 1.78/2.26/3.13/4.24/5.27/7.03).
-- ===========================================================================

create table if not exists public.tariff_plans (
    id             text primary key,
    name_zh        text not null,
    name_en        text,
    type           text not null check (type in ('tiered', 'time_of_use', 'flat')),
    currency       text not null default 'TWD',
    unit           text not null default 'kWh',
    effective_from date,
    is_estimate    boolean not null default false,
    data           jsonb not null,
    created_at     timestamptz not null default now()
);

comment on table public.tariff_plans is
    'Optional mirror of app/data/tariffs.json. The backend does not read this table.';

-- Prices are not user-specific and the UI may need them before sign-in.
alter table public.tariff_plans enable row level security;

drop policy if exists "tariff_plans_readable" on public.tariff_plans;
create policy "tariff_plans_readable"
    on public.tariff_plans for select
    to anon, authenticated
    using (true);

grant select on public.tariff_plans to anon, authenticated;

insert into public.tariff_plans (id, name_zh, name_en, type, effective_from, is_estimate, data)
values
    ('tw_residential_tiered',
     '台電住宅用電－累進（級距）電價',
     'Taipower residential - progressive (tiered) rate',
     'tiered', date '2025-10-01', false,
     '{"seasons": {"summer": {"tiers": [{"index":1,"up_to_kwh":120,"rate":1.78},{"index":2,"up_to_kwh":330,"rate":2.55},{"index":3,"up_to_kwh":500,"rate":3.80},{"index":4,"up_to_kwh":700,"rate":5.14},{"index":5,"up_to_kwh":1000,"rate":6.44},{"index":6,"up_to_kwh":null,"rate":8.86}]}, "non_summer": {"tiers": [{"index":1,"up_to_kwh":120,"rate":1.78},{"index":2,"up_to_kwh":330,"rate":2.26},{"index":3,"up_to_kwh":500,"rate":3.13},{"index":4,"up_to_kwh":700,"rate":4.24},{"index":5,"up_to_kwh":1000,"rate":5.27},{"index":6,"up_to_kwh":null,"rate":7.03}]}}}'::jsonb),
    ('tw_residential_tou',
     '台電住宅用電－時間電價（二段式，估算）',
     'Taipower residential - time-of-use (two-segment, estimated)',
     'time_of_use', date '2025-10-01', true,
     '{"seasons": {"summer": {"peak": 5.16, "off_peak": 2.13}, "non_summer": {"peak": 5.16, "off_peak": 1.90}}}'::jsonb),
    ('flat_rate_resell_reference',
     '單一費率參考（租屋常見房東轉售價）',
     'Flat-rate reference (typical rented-room resale price)',
     'flat', date '2025-01-01', true,
     '{"seasons": {"summer": {"rate": 5.5}, "non_summer": {"rate": 5.5}}}'::jsonb)
on conflict (id) do update
    set name_zh        = excluded.name_zh,
        name_en        = excluded.name_en,
        type           = excluded.type,
        effective_from = excluded.effective_from,
        is_estimate    = excluded.is_estimate,
        data           = excluded.data;

notify pgrst, 'reload schema';
