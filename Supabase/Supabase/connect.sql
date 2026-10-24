alter table public.appliances
alter column user_id set default auth.uid();
