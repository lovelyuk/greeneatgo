-- 일반 사용자의 키움페이 상품 결제 주문.
-- 장부(employee) 결제 원장과 실제 PG 결제를 분리한다.

alter table app_users drop constraint if exists app_users_role_check;
alter table app_users
  add constraint app_users_role_check
  check (role in ('employee','customer','company_admin','platform_admin','merchant_admin'));

create table if not exists payment_orders (
  id uuid primary key default gen_random_uuid(),
  order_id text unique not null,
  checkout_token text unique not null,
  user_id uuid not null references app_users(id),
  merchant_id uuid not null references merchants(id),
  product_id uuid references merchant_products(id),
  merchant_name text not null,
  product_name text not null,
  amount int not null check (amount > 0),
  status text not null default 'ready'
    check (status in ('ready','done','failed','canceled')),
  provider_payment_key text unique,
  payment_method text,
  provider_response jsonb,
  failure_code text,
  failure_message text,
  approved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_payment_orders_user_created
  on payment_orders(user_id, created_at desc);
create index if not exists idx_payment_orders_merchant_created
  on payment_orders(merchant_id, created_at desc);

alter table payment_orders enable row level security;
-- 앱에서 직접 읽거나 쓰지 않는다. FastAPI service_role만 접근한다.
