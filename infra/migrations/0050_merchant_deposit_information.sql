-- Persist optional merchant deposit information shown in settlement details.
alter table public.merchants add column if not exists bank_name varchar(80);
alter table public.merchants add column if not exists account_number varchar(80);
alter table public.merchants add column if not exists account_holder varchar(80);
