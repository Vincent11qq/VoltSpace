-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Allow authenticated users to access their own profiles
GRANT USAGE ON SCHEMA public TO authenticated;

GRANT SELECT, UPDATE
ON public.profiles
TO authenticated;

-- Allow authenticated users to manage appliances
GRANT SELECT, INSERT, UPDATE, DELETE
ON public.appliances
TO authenticated;

-- Allow Supabase API roles to access public tables
GRANT USAGE ON SCHEMA public TO anon, authenticated;

-- Reload PostgREST schema cache
NOTIFY pgrst, 'reload schema';