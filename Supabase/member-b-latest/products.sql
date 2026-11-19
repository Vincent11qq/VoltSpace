create table if not exists public.products (
    id bigint generated always as identity primary key,

    name text not null,
    brand text,
    category text not null,
    model text,

    power_watts numeric(10,2)
        check (power_watts is null or power_watts > 0),

    voltage numeric(6,2),
    energy_rating text,

    price numeric(12,2)
        check (price is null or price >= 0),

    currency text not null default 'TWD',

    estimated_monthly_kwh numeric(10,2),

    product_url text,
    image_url text,
    description text,

    is_active boolean not null default true,

    created_at timestamptz not null default now()
);

-- Index for faster product category searches
create index if not exists products_category_idx
on public.products(category);

-- Enable Row Level Security
alter table public.products enable row level security;

-- Products can be viewed by everyone
drop policy if exists "Products are publicly readable"
on public.products;

create policy "Products are publicly readable"
on public.products
for select
to anon, authenticated
using (is_active = true);
