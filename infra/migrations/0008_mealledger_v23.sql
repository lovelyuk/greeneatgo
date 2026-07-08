-- MEALLEDGER Addendum v2.3: merchant self-management of ledger companies.

alter table companies drop constraint if exists companies_status_check;
update companies set status = 'active' where status is null;
alter table companies
  alter column status set default 'active',
  alter column status set not null;
alter table companies
  add constraint companies_status_check
  check (status in ('invited','active','suspended'));

alter table app_users
  add column if not exists merchant_id uuid references merchants(id);

-- Backfill from the temporary merchant_admins table used by the first merchant-admin slice.
update app_users u
set merchant_id = ma.merchant_id
from merchant_admins ma
where u.id = ma.user_id
  and u.merchant_id is null;

create table if not exists merchant_companies (
  id uuid primary key default gen_random_uuid(),
  merchant_id uuid not null references merchants(id),
  company_id uuid not null references companies(id),
  status text not null default 'active' check (status in ('active','paused')),
  created_by uuid references app_users(id),
  created_at timestamptz default now(),
  unique (merchant_id, company_id)
);

create index if not exists idx_merchant_companies_merchant on merchant_companies(merchant_id, status);
create index if not exists idx_merchant_companies_company on merchant_companies(company_id);

-- Keep legacy company_merchants populated for existing payment/settlement code while v2.3 APIs use merchant_companies.
insert into merchant_companies (merchant_id, company_id, status)
select merchant_id, company_id, case when is_active then 'active' else 'paused' end
from company_merchants
on conflict (merchant_id, company_id) do nothing;

create table if not exists invites (
  id uuid primary key default gen_random_uuid(),
  token text unique not null,
  role text not null check (role in ('merchant_admin','company_admin')),
  merchant_id uuid references merchants(id),
  company_id uuid references companies(id),
  phone text not null,
  status text not null default 'pending' check (status in ('pending','claimed','expired')),
  invited_by uuid references app_users(id),
  expires_at timestamptz not null,
  created_at timestamptz default now()
);

create index if not exists idx_invites_token_status on invites(token, status);
create index if not exists idx_invites_company on invites(company_id);
create index if not exists idx_invites_merchant on invites(merchant_id);
