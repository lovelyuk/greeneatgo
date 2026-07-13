-- Merchant-scoped announcement board and purchase-verified review board.
create table if not exists announcements (
  id uuid primary key default gen_random_uuid(),
  merchant_id uuid not null references merchants(id),
  title text not null check (char_length(trim(title)) between 1 and 120),
  content text not null check (char_length(trim(content)) between 1 and 5000),
  status text not null default 'published' check (status in ('published','hidden')),
  pinned boolean not null default false,
  send_push boolean not null default false,
  created_by uuid not null references app_users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_announcements_merchant_list on announcements(merchant_id, pinned desc, created_at desc);

create table if not exists reviews (
  id uuid primary key default gen_random_uuid(),
  merchant_id uuid not null references merchants(id),
  account_id uuid not null references app_users(id),
  transaction_id bigint not null unique references meal_transactions(id),
  rating smallint not null check (rating between 1 and 5),
  content text check (content is null or char_length(content) <= 2000),
  image_urls text[] not null default '{}',
  status text not null default 'visible' check (status in ('visible','hidden')),
  owner_reply text check (owner_reply is null or char_length(owner_reply) <= 2000),
  owner_reply_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (cardinality(image_urls) <= 3)
);
create index if not exists idx_reviews_merchant_list on reviews(merchant_id, created_at desc);

alter table announcements enable row level security;
alter table reviews enable row level security;
-- API uses the service role and performs tenant/role authorization. Keep direct client access closed.
revoke all on announcements, reviews from anon, authenticated;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('review-images', 'review-images', true, 524288, array['image/jpeg','image/png','image/webp'])
on conflict (id) do update set public=true, file_size_limit=524288,
  allowed_mime_types=array['image/jpeg','image/png','image/webp'];
