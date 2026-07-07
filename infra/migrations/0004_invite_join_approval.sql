-- greeneatGo invite-code join approval flow.
-- Existing installs: extend app_users statuses, add invite code and audit log tables.

alter table app_users drop constraint if exists app_users_status_check;
alter table app_users add constraint app_users_status_check
  check (status in ('pending','active','paused','left','rejected'));

alter table app_users add column if not exists approved_at timestamptz;
alter table app_users add column if not exists rejected_at timestamptz;

create table if not exists company_invite_codes (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references companies(id),
  code text unique not null,
  default_group_id uuid references employee_groups(id),
  expires_at timestamptz,
  max_uses int,
  used_count int not null default 0,
  is_active boolean not null default true,
  created_at timestamptz default now(),
  check (max_uses is null or max_uses > 0),
  check (used_count >= 0)
);

create table if not exists employee_join_audit_logs (
  id bigint generated always as identity primary key,
  user_id uuid not null references app_users(id),
  company_id uuid not null references companies(id),
  action text not null check (action in ('requested','approved','rejected')),
  actor_user_id uuid references app_users(id),
  reason text,
  created_at timestamptz default now()
);

create index if not exists idx_app_users_company_status on app_users(company_id, status);
create index if not exists idx_company_invite_codes_company on company_invite_codes(company_id) where is_active;
create index if not exists idx_employee_join_audit_logs_user on employee_join_audit_logs(user_id, created_at desc);

alter table company_invite_codes enable row level security;
alter table employee_join_audit_logs enable row level security;
-- No client write policies: invite-code join/approval is FastAPI service_role only.
