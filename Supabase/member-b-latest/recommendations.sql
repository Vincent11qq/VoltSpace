create table if not exists
public.recommendations(id bigint generated always as identity primary key,
household_id uuid
references public.households(id) on delete cascade,
appliance_id bigint
references public.appliances(id) on delete cascade,
product_id bigint
references public.products(id) on delete cascade,

estimated_savings_kwh numeric(10,2),
estimated_savings_cost numeric(12,2),
reason text,

created_at timestamptz not null default now());

create index if not exists
recommendations_household_idx
on public.recommendations(household_id);

create index if not exists
recommendations_appliance_idx
on public.recommendations(appliance_id);

create index if not exists
recommendations_product_idx
on public.recommendations(product_id);

alter table public.recommendations
enable row level security;
