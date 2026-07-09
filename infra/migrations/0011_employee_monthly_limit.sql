-- Per-employee monthly meal limit for company-admin employee management.

alter table app_users
  add column if not exists monthly_limit int not null default 200000;

alter table app_users drop constraint if exists app_users_monthly_limit_check;
alter table app_users
  add constraint app_users_monthly_limit_check
  check (monthly_limit >= 0);
