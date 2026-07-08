-- 식당 등록 상품: 직원 앱은 금액 직접 입력 대신 이 상품 중 하나를 선택해 결제한다.
create table if not exists merchant_products (
  id uuid primary key default gen_random_uuid(),
  merchant_id uuid not null references merchants(id) on delete cascade,
  name text not null,
  price int not null check (price > 0),
  category text,
  image_url text,
  is_active boolean not null default true,
  sort_order int not null default 0,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_merchant_products_merchant_active
  on merchant_products(merchant_id, is_active, sort_order, created_at);

alter table meal_transactions
  add column if not exists product_id uuid references merchant_products(id),
  add column if not exists product_name text,
  add column if not exists product_price int;
