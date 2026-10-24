create table appliances (
  Id serial primary key,
  User_id uuid default auth.uid(),
  Appliance text not null,
  Power integer default 1 not null,
  Quantity integer default 1 not null,
  Minutes numeric
);
