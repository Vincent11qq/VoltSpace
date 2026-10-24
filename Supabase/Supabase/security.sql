alter table public.appliances enable row level security;

create policy "All users are allowed to view information"
on public.appliances for select
to authenticated
using ( (select auth.uid())=user_id );

create policy "All users are allowed to insert information"
on public.appliances for insert
to authenticated
with check ( (select auth.uid())=user_id );

create policy "All users are allowed to update information"
on public.appliances for update 
to authenticated
using ( (select auth.uid())=user_id );

create policy "All users are allowed to delete information"
on public.appliances for delete
to authenticated
using ( (select auth.uid())=user_id );