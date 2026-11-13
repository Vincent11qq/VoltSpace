-- Enable Row Level Security
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.appliances ENABLE ROW LEVEL SECURITY;

-- Profiles policies
DROP POLICY IF EXISTS "Users can view their own profile"
ON public.profiles;

CREATE POLICY "Users can view their own profile"
ON public.profiles
FOR SELECT
TO authenticated
USING (auth.uid() = id);

DROP POLICY IF EXISTS "Users can update their own profile"
ON public.profiles;

CREATE POLICY "Users can update their own profile"
ON public.profiles
FOR UPDATE
TO authenticated
USING (auth.uid() = id)
WITH CHECK (auth.uid() = id);

-- Appliances policies
DROP POLICY IF EXISTS "Users can view their own appliances"
ON public.appliances;

CREATE POLICY "Users can view their own appliances"
ON public.appliances
FOR SELECT
TO authenticated
USING (household_id = auth.uid());

DROP POLICY IF EXISTS "Users can insert their own appliances"
ON public.appliances;

CREATE POLICY "Users can insert their own appliances"
ON public.appliances
FOR INSERT
TO authenticated
WITH CHECK (household_id = auth.uid());

DROP POLICY IF EXISTS "Users can update their own appliances"
ON public.appliances;

CREATE POLICY "Users can update their own appliances"
ON public.appliances
FOR UPDATE
TO authenticated
USING (household_id = auth.uid())
WITH CHECK (household_id = auth.uid());

DROP POLICY IF EXISTS "Users can delete their own appliances"
ON public.appliances;

CREATE POLICY "Users can delete their own appliances"
ON public.appliances
FOR DELETE
TO authenticated
USING (household_id = auth.uid());