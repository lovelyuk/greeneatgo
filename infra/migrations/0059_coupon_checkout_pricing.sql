begin;

-- Immutable checkout pricing snapshots. Historical orders are backfilled from
-- the economic values that were authoritative before coupons were introduced.
alter table public.payment_orders
  add column if not exists gross_amount integer,
  add column if not exists coupon_id uuid,
  add column if not exists coupon_discount_amount integer not null default 0,
  add column if not exists coupon_snapshot jsonb,
  add column if not exists requested_point_amount integer;

update public.payment_orders
set gross_amount = case
  when pay_type='subsidized' then coalesce(total_employee_burden,amount+coalesce(point_amount,0))
  else amount
end
where gross_amount is null;

update public.payment_orders
set requested_point_amount=0
where pay_type='voucher' and requested_point_amount is null;

alter table public.payment_orders
  drop constraint if exists payment_orders_coupon_pricing_snapshot_check;
alter table public.payment_orders add constraint payment_orders_coupon_pricing_snapshot_check check (
  (
    pay_type not in ('voucher','subsidized')
    and (gross_amount is null or gross_amount=amount)
    and coupon_id is null and coupon_discount_amount=0 and coupon_snapshot is null
    and requested_point_amount is null
  )
  or (
    pay_type in ('voucher','subsidized')
    and gross_amount is not null and gross_amount>0
    and coupon_discount_amount>=0 and coupon_discount_amount<gross_amount
    and (requested_point_amount is null or requested_point_amount>=0)
    and (
      (coupon_id is null and coupon_discount_amount=0 and coupon_snapshot is null)
      or (coupon_id is not null and coupon_snapshot is not null
          and jsonb_typeof(coupon_snapshot)='object'
          and coupon_snapshot->>'id'=coupon_id::text
          and coupon_snapshot->>'merchant_id'=merchant_id::text)
    )
    and (
      (pay_type='voucher' and gross_amount=amount+coupon_discount_amount
       and requested_point_amount=0)
      or (pay_type='subsidized' and gross_amount=total_employee_burden+coupon_discount_amount)
    )
  )
);

comment on column public.payment_orders.gross_amount is
  'Server-recalculated order amount before coupon and points.';
comment on column public.payment_orders.requested_point_amount is
  'Client-selected point cap; NULL preserves the legacy use-maximum policy.';

create or replace function public.prevent_payment_pricing_snapshot_change() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin
 if (new.gross_amount,new.coupon_id,new.coupon_discount_amount,new.coupon_snapshot,new.requested_point_amount)
    is distinct from
    (old.gross_amount,old.coupon_id,old.coupon_discount_amount,old.coupon_snapshot,old.requested_point_amount)
 then raise exception 'PAYMENT_PRICING_SNAPSHOT_IMMUTABLE' using errcode='P0001'; end if;
 return new;
end $$;
revoke all on function public.prevent_payment_pricing_snapshot_change() from public,anon,authenticated,service_role;
drop trigger if exists trg_payment_order_pricing_immutable on public.payment_orders;
create trigger trg_payment_order_pricing_immutable
 before update of gross_amount,coupon_id,coupon_discount_amount,coupon_snapshot,requested_point_amount
 on public.payment_orders for each row execute function public.prevent_payment_pricing_snapshot_change();

-- Promotion coupons are a reusable catalog. This table records successful uses
-- for audit/analytics, not a per-user eligibility limit.
create table if not exists public.coupon_redemptions (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references public.payment_orders(id) on delete restrict,
  coupon_id uuid not null,
  user_id uuid not null references public.app_users(id) on delete restrict,
  merchant_id uuid not null references public.merchants(id) on delete restrict,
  discount_amount integer not null check(discount_amount>=0),
  coupon_snapshot jsonb not null check(jsonb_typeof(coupon_snapshot)='object'),
  redeemed_at timestamptz not null default now(),
  unique(order_id)
);
create index if not exists idx_coupon_redemptions_coupon_redeemed
 on public.coupon_redemptions(coupon_id,redeemed_at desc);
alter table public.coupon_redemptions enable row level security;
revoke all on table public.coupon_redemptions from public,anon,authenticated,service_role;
grant select on table public.coupon_redemptions to service_role;

create or replace function public.record_fulfilled_coupon_redemption() returns trigger
language plpgsql security definer set search_path=pg_catalog,public as $$
begin
 if old.fulfilled_at is null and new.fulfilled_at is not null and new.coupon_id is not null then
  insert into public.coupon_redemptions(
    order_id,coupon_id,user_id,merchant_id,discount_amount,coupon_snapshot,redeemed_at)
  values(new.id,new.coupon_id,new.user_id,new.merchant_id,new.coupon_discount_amount,
         new.coupon_snapshot,coalesce(new.fulfilled_at,pg_catalog.clock_timestamp()))
  on conflict(order_id) do nothing;
 end if;
 return new;
end $$;
revoke all on function public.record_fulfilled_coupon_redemption() from public,anon,authenticated,service_role;
drop trigger if exists trg_fulfilled_coupon_redemption on public.payment_orders;
create trigger trg_fulfilled_coupon_redemption
 after update of fulfilled_at on public.payment_orders
 for each row execute function public.record_fulfilled_coupon_redemption();

-- NULL requested_point_amount keeps old clients' maximum-point behavior. An
-- explicit value (including zero) is an upper bound; wallet availability and the
-- coupon-adjusted burden are still enforced under the existing row locks.
create or replace function public.reserve_subsidized_order_points(p_order_id uuid) returns jsonb
language plpgsql security definer set search_path=pg_catalog,public as $$
declare o public.payment_orders%rowtype; u public.app_users%rowtype; employee_due bigint; points bigint;
begin
 select * into o from public.payment_orders where id=p_order_id for update;
 if not found or o.pay_type<>'subsidized' or o.status<>'ready' then raise exception 'ORDER_NOT_RESERVABLE' using errcode='P0001'; end if;
 if o.point_reserved then return jsonb_build_object('point_amount',o.point_amount,'card_amount',o.amount,'duplicate',true); end if;
 select * into u from public.app_users where id=o.user_id and role='employee' and company_id=o.company_id for update;
 if not found then raise exception 'EMPLOYEE_NOT_FOUND' using errcode='P0001'; end if;
 employee_due:=o.total_employee_burden;
 if employee_due is null or employee_due<=0 then raise exception 'INVALID_EMPLOYEE_BURDEN' using errcode='P0001'; end if;
 points:=greatest(least(employee_due,u.point_balance-u.point_reserved,
   coalesce(o.requested_point_amount,employee_due)),0);
 update public.app_users set point_reserved=point_reserved+points where id=u.id;
 update public.payment_orders set point_amount=points,point_reserved=(points>0),
   amount=employee_due-points,updated_at=now() where id=o.id returning * into o;
 return jsonb_build_object('point_amount',points,'card_amount',o.amount,'duplicate',false);
end $$;
revoke all on function public.reserve_subsidized_order_points(uuid) from public,anon,authenticated;
grant execute on function public.reserve_subsidized_order_points(uuid) to service_role;

notify pgrst,'reload schema';
commit;
