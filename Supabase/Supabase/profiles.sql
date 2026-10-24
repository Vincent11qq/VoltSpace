create table profiles (
  Id uuid primary key references auth.users(Id),
  name text 
)