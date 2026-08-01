begin;

-- Voucher products: one discount mode, explicit sold-out state, and history-safe deletion.
alter table public.voucher_products
  add column if not exists discount_amount_per_voucher numeric(14,2) not null default 0,
  add column if not exists deleted_at timestamptz;

alter table public.voucher_products
  drop constraint if exists voucher_products_status_check,
  drop constraint if exists voucher_products_discount_amount_per_voucher_check,
  drop constraint if exists voucher_products_single_discount_mode_check,
  drop constraint if exists voucher_products_discounted_unit_price_check;

update public.voucher_products
set status = 'sold_out'
where status = 'inactive';

alter table public.voucher_products
  add constraint voucher_products_status_check
    check (status in ('active', 'sold_out')),
  add constraint voucher_products_discount_amount_per_voucher_check
    check (discount_amount_per_voucher >= 0),
  add constraint voucher_products_single_discount_mode_check
    check (discount_rate = 0 or discount_amount_per_voucher = 0),
  add constraint voucher_products_discounted_unit_price_check
    check ((unit_price * (100 - discount_rate) / 100) - discount_amount_per_voucher > 0);

alter table public.voucher_products drop column sale_price;
alter table public.voucher_products
  add column sale_price numeric(14,2) generated always as (
    round(
      ((unit_price * (100 - discount_rate) / 100) - discount_amount_per_voucher)
      * voucher_count,
      2
    )
  ) stored;

alter table public.voucher_products
  add constraint voucher_products_sale_price_positive_check check (sale_price > 0);

create index if not exists idx_voucher_products_merchant_live_order
  on public.voucher_products(merchant_id, status, display_order, created_at)
  where deleted_at is null;

-- Merchant-managed coupon policies. Checkout redemption is a separate payment concern;
-- this table is the authoritative management catalog for percent/fixed coupons.
create table if not exists public.merchant_coupons (
  id uuid primary key default gen_random_uuid(),
  merchant_id uuid not null references public.merchants(id) on delete cascade,
  name text not null check (char_length(btrim(name)) between 1 and 120),
  discount_type text not null check (discount_type in ('percent', 'fixed')),
  discount_value numeric(14,2) not null,
  valid_from date,
  valid_until date,
  is_active boolean not null default true,
  created_by uuid not null references public.app_users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (
    (discount_type = 'percent' and discount_value > 0 and discount_value < 100)
    or (discount_type = 'fixed' and discount_value > 0)
  ),
  check (valid_until is null or valid_from is null or valid_until >= valid_from)
);

create index if not exists idx_merchant_coupons_merchant_active_created
  on public.merchant_coupons(merchant_id, is_active, created_at desc);

alter table public.merchant_coupons enable row level security;
revoke all on table public.merchant_coupons from anon, authenticated, service_role;
grant select, insert, update, delete on table public.merchant_coupons to service_role;

commit;
