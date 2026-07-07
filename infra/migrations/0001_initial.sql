-- greeneatGo initial schema (Supabase/Postgres)
create extension if not exists pgcrypto;

create table if not exists companies (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  biz_reg_no text,
  status text default 'active' check (status in ('active','suspended')),
  created_at timestamptz default now()
);

create table if not exists employee_groups (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references companies(id),
  name text not null,
  unique (company_id, name)
);

create table if not exists app_users (
  id uuid primary key references auth.users(id),
  company_id uuid references companies(id),
  group_id uuid references employee_groups(id),
  display_name text not null,
  role text not null default 'employee' check (role in ('employee','company_admin','platform_admin')),
  status text default 'active' check (status in ('active','paused','left')),
  fcm_token text,
  created_at timestamptz default now()
);

create table if not exists merchants (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  biz_reg_no text,
  owner_phone text,
  bank_account jsonb,
  address text,
  lat numeric,
  lng numeric,
  category text,
  avg_price int,
  qr_token text unique not null,
  view_token text unique not null,
  status text default 'active' check (status in ('active','paused','terminated')),
  created_at timestamptz default now()
);

create table if not exists company_merchants (
  company_id uuid references companies(id),
  merchant_id uuid references merchants(id),
  is_active boolean default true,
  primary key (company_id, merchant_id)
);

create table if not exists meal_policies (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references companies(id),
  group_id uuid references employee_groups(id),
  meal_windows jsonb not null default '[{"name":"중식","start":"11:00","end":"14:00","per_meal_limit":10000},{"name":"석식","start":"17:30","end":"20:30","per_meal_limit":12000}]',
  daily_limit int,
  monthly_grant int not null default 200000,
  weekend_allowed boolean default false,
  carry_over boolean default false
);

create table if not exists meal_transactions (
  id bigint generated always as identity primary key,
  user_id uuid not null references app_users(id),
  company_id uuid not null references companies(id),
  merchant_id uuid references merchants(id),
  amount int not null,
  kind text not null check (kind in ('grant','spend','expire','refund','adjust')),
  tx_code text unique,
  meal_window text,
  group_pay_id uuid,
  flags jsonb default '{}',
  idempotency_key text unique,
  created_at timestamptz default now()
);

create or replace view meal_balances as
select user_id, sum(amount) as balance
from meal_transactions group by user_id;

create table if not exists settlements (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references companies(id),
  merchant_id uuid not null references merchants(id),
  period_ym text not null,
  tx_count int not null,
  total_amount int not null,
  status text default 'draft' check (status in ('draft','confirmed','paid')),
  paid_at timestamptz,
  unique (company_id, merchant_id, period_ym)
);

create index if not exists idx_meal_transactions_user_created on meal_transactions(user_id, created_at desc);
create index if not exists idx_meal_transactions_company_created on meal_transactions(company_id, created_at desc);
create index if not exists idx_company_merchants_merchant on company_merchants(merchant_id);
