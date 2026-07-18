-- Purchase-order refunds and immutable refund audit.
-- vouchers.order_id is the authoritative purchase-order relation and
-- toss_payment_orders.payment_key is the authoritative PG transaction key.
-- Apply after 0027_allow_point_only_orders.sql.

alter table toss_payment_orders
  add column if not exists paid_voucher_count int,
  add column if not exists bonus_voucher_count int,
  add column if not exists refund_account jsonb;

-- Toss exposes virtual-account refund details only for a limited time. Capture
-- them whenever the authoritative payment response is persisted.
create or replace function capture_toss_refund_account() returns trigger language plpgsql as $$
begin
  if new.refund_account is null and new.toss_response is not null then
    new.refund_account := new.toss_response #> '{virtualAccount,refundReceiveAccount}';
  end if;
  return new;
end $$;
drop trigger if exists toss_payment_orders_capture_refund_account on toss_payment_orders;
create trigger toss_payment_orders_capture_refund_account
before insert or update of toss_response on toss_payment_orders
for each row execute function capture_toss_refund_account();
alter table toss_payment_orders drop constraint if exists toss_payment_orders_status_check;
alter table toss_payment_orders add constraint toss_payment_orders_status_check
  check (status in ('ready','done','failed','canceled','refunded'));

-- Best-effort snapshots for orders created before this migration. Product data is
-- used when available; otherwise treating all issued vouchers as paid is safer
-- than accidentally forfeiting historical vouchers as bonuses.
update toss_payment_orders o set
  paid_voucher_count = case
    when o.pay_type='subsidized' then 1
    else least(o.voucher_count, coalesce(p.voucher_count, o.voucher_count)) end,
  bonus_voucher_count = case
    when o.pay_type='subsidized' then 0
    else greatest(o.voucher_count-coalesce(p.voucher_count,o.voucher_count),0) end
from (select id,voucher_count from voucher_products) p
where o.pay_type='voucher' and o.voucher_product_id=p.id
  and (o.paid_voucher_count is null or o.bonus_voucher_count is null);
update toss_payment_orders set
  paid_voucher_count=case when pay_type='subsidized' then 1 else voucher_count end,
  bonus_voucher_count=0
where pay_type in ('voucher','subsidized')
  and (paid_voucher_count is null or bonus_voucher_count is null);

alter table toss_payment_orders drop constraint if exists toss_payment_orders_refund_snapshot_check;
alter table toss_payment_orders add constraint toss_payment_orders_refund_snapshot_check check (
  (pay_type='direct' and paid_voucher_count is null and bonus_voucher_count is null)
  or (pay_type in ('voucher','subsidized') and paid_voucher_count > 0
      and bonus_voucher_count >= 0
      and paid_voucher_count + bonus_voucher_count = voucher_count)
);

alter table vouchers drop constraint if exists vouchers_status_check;
alter table vouchers add constraint vouchers_status_check
  check (status in ('unused','used','refunded','forfeited'));

create table if not exists refund_requests (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references toss_payment_orders(id),
  merchant_id uuid not null references merchants(id),
  user_id uuid not null references app_users(id),
  requested_by uuid not null references app_users(id),
  status text not null default 'processing'
    check (status in ('processing','completed','failed')),
  refund_amount int not null check (refund_amount >= 0),
  point_amount bigint not null default 0 check (point_amount >= 0),
  refunded_voucher_count int not null default 0 check (refunded_voucher_count >= 0),
  forfeited_voucher_count int not null default 0 check (forfeited_voucher_count >= 0),
  refund_account jsonb,
  pg_response jsonb,
  failure_code text,
  failure_message text,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  updated_at timestamptz not null default now()
);
create unique index if not exists idx_refund_requests_one_active_order
  on refund_requests(order_id) where status in ('processing','completed');
create index if not exists idx_refund_requests_merchant_created
  on refund_requests(merchant_id,created_at desc);
alter table refund_requests enable row level security;

alter table point_transactions drop constraint if exists point_transactions_type_check;
alter table point_transactions add constraint point_transactions_type_check
  check (type in ('charge','use','adjust','refund'));

-- Claims the order and calculates from locked, current voucher state. Calling
-- Toss only after this RPC prevents two admins from issuing duplicate cancels.
create or replace function claim_purchase_order_refund(
  p_order_id uuid, p_merchant_id uuid, p_user_id uuid,
  p_requested_by uuid, p_refund_account jsonb default null
) returns jsonb language plpgsql security definer set search_path=public as $$
declare o toss_payment_orders%rowtype; r refund_requests%rowtype;
  used_count int; paid_remaining int; unused_bonus int; card_refund int; already_refunded int;
begin
  select * into o from toss_payment_orders where id=p_order_id for update;
  if not found or o.merchant_id<>p_merchant_id or o.user_id<>p_user_id then
    raise exception 'ORDER_NOT_FOUND' using errcode='P0001';
  end if;
  if o.status<>'done' or o.pay_type not in ('voucher','subsidized') then
    raise exception 'ORDER_NOT_REFUNDABLE' using errcode='P0001';
  end if;
  if exists(select 1 from refund_requests where order_id=o.id and status in ('processing','completed')) then
    raise exception 'REFUND_ALREADY_REQUESTED' using errcode='P0001';
  end if;
  select count(*) filter(where status='used'),
         count(*) filter(where status='unused' and issue_index>o.paid_voucher_count)
    into used_count,unused_bonus from vouchers where order_id=o.id;
  if o.pay_type='subsidized' then
    if used_count>0 then raise exception 'ORDER_ALREADY_USED' using errcode='P0001'; end if;
    paid_remaining:=1; card_refund:=o.amount;
  else
    paid_remaining:=greatest(o.paid_voucher_count-used_count,0);
    if paid_remaining=0 and unused_bonus=0 then
      raise exception 'PAID_VOUCHERS_EXHAUSTED' using errcode='P0001';
    end if;
    select coalesce(sum(refund_amount),0) into already_refunded from refund_requests
      where order_id=o.id and status='completed';
    card_refund:=least(round(o.amount::numeric/o.paid_voucher_count)::int*paid_remaining,
                       greatest(o.amount-already_refunded,0));
  end if;
  insert into refund_requests(order_id,merchant_id,user_id,requested_by,status,
    refund_amount,point_amount,refunded_voucher_count,forfeited_voucher_count,refund_account)
  values(o.id,p_merchant_id,p_user_id,p_requested_by,'processing',card_refund,
    case when o.pay_type='subsidized' then o.point_amount else 0 end,
    paid_remaining,unused_bonus,p_refund_account) returning * into r;
  update toss_payment_orders set refund_account=p_refund_account,updated_at=now() where id=o.id;
  return jsonb_build_object('refund_request_id',r.id,'order_id',o.order_id,
    'payment_key',o.payment_key,'pay_type',o.pay_type,'refund_amount',card_refund,
    'point_amount',r.point_amount,'refunded_voucher_count',paid_remaining,
    'forfeited_voucher_count',unused_bonus);
end $$;
revoke all on function claim_purchase_order_refund(uuid,uuid,uuid,uuid,jsonb) from public,anon,authenticated;
grant execute on function claim_purchase_order_refund(uuid,uuid,uuid,uuid,jsonb) to service_role;

-- Finalizes voucher state, point restoration, and audit in one transaction.
create or replace function finalize_purchase_order_refund(
  p_refund_request_id uuid, p_merchant_id uuid, p_pg_response jsonb default null
) returns jsonb language plpgsql security definer set search_path=public as $$
declare r refund_requests%rowtype; o toss_payment_orders%rowtype; u app_users%rowtype;
  refunded_count int; forfeited_count int;
begin
  select * into r from refund_requests where id=p_refund_request_id for update;
  if not found or r.merchant_id<>p_merchant_id then raise exception 'REFUND_NOT_FOUND' using errcode='P0001'; end if;
  if r.status='completed' then return to_jsonb(r); end if;
  if r.status<>'processing' then raise exception 'REFUND_NOT_PROCESSING' using errcode='P0001'; end if;
  select * into o from toss_payment_orders where id=r.order_id for update;
  if o.pay_type='subsidized' then
    update vouchers set status='refunded' where order_id=o.id and status='unused';
  else
    update vouchers set status='refunded'
      where id in (select id from vouchers where order_id=o.id and status='unused'
        and issue_index<=o.paid_voucher_count order by issue_index limit r.refunded_voucher_count);
    update vouchers set status='forfeited'
      where order_id=o.id and status='unused' and issue_index>o.paid_voucher_count;
  end if;
  get diagnostics forfeited_count = row_count;
  select count(*) into refunded_count from vouchers where order_id=o.id and status='refunded';
  if r.point_amount>0 then
    select * into u from app_users where id=o.user_id for update;
    update app_users set point_balance=point_balance+r.point_amount where id=u.id returning * into u;
    insert into point_transactions(user_id,company_id,type,amount,balance_after,reason,
      processed_by,related_order_id)
    values(o.user_id,o.company_id,'refund',r.point_amount,u.point_balance,'보조금 식권 환불',r.requested_by,o.id);
  end if;
  update refund_requests set status='completed',pg_response=p_pg_response,
    completed_at=now(),updated_at=now() where id=r.id returning * into r;
  update toss_payment_orders set status='refunded',updated_at=now() where id=o.id;
  return jsonb_build_object('refund_request_id',r.id,'status','completed',
    'refund_amount',r.refund_amount,'point_amount',r.point_amount,
    'refunded_voucher_count',r.refunded_voucher_count,
    'forfeited_voucher_count',r.forfeited_voucher_count);
end $$;
revoke all on function finalize_purchase_order_refund(uuid,uuid,jsonb) from public,anon,authenticated;
grant execute on function finalize_purchase_order_refund(uuid,uuid,jsonb) to service_role;
