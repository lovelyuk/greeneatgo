-- 부페식 식당의 오늘 메뉴 공지. 직원 앱 상품 선택 화면에 표시한다.
create table if not exists merchant_daily_menus (
  id uuid primary key default gen_random_uuid(),
  merchant_id uuid not null references merchants(id) on delete cascade,
  service_date date not null,
  title text not null default '오늘의 부페 메뉴',
  menu_text text not null,
  is_active boolean not null default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (merchant_id, service_date)
);

create index if not exists idx_merchant_daily_menus_merchant_date
  on merchant_daily_menus(merchant_id, service_date desc);
