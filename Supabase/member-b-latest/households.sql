create table if not exists
public.households(
  id uuid primary key default
  gen_random_uuid(),
  owner_id uuid references
  auth.users(id) on delete set null
  default auth.uid(),
  access_token uuid not null default
  gen_random_uuid(),
  label text,
  created_at timestamptz not null default now()
);
