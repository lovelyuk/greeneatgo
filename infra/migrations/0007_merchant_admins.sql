-- 식당관리자 권한 추가: 식당 사장님/운영자는 자기 식당 상품과 오늘 메뉴만 관리한다.
alter table app_users drop constraint if exists app_users_role_check;
alter table app_users
  add constraint app_users_role_check
  check (role in ('employee','company_admin','platform_admin','merchant_admin'));

create table if not exists merchant_admins (
  user_id uuid primary key references app_users(id) on delete cascade,
  merchant_id uuid not null references merchants(id) on delete cascade,
  created_at timestamptz default now()
);

create index if not exists idx_merchant_admins_merchant on merchant_admins(merchant_id);
