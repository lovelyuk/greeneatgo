-- Voucher products, Toss fulfillment, and unified ledger/voucher transactions.
-- Apply after 0014_toss_consumer_payments.sql.

create table if not exists voucher_products (
  id uuid primary key default gen_random_uuid(),
  merchant_id uuid not null references merchants(id),
  name text not null check (char_length(btrim(name)) > 0),
  voucher_count int not null check (voucher_count > 0),
  bonus_count int not null default 0 check (bonus_count >= 0),
  unit_price numeric(14,2) not null check (unit_price > 0),
  discount_rate numeric(5,2) not null default 0 check (discount_rate >= 0 and discount_rate < 100),
  sale_price numeric(14,2) generated always as
    (round(unit_price * voucher_count * (100 - discount_rate) / 100, 2)) stored,
  status text not null default 'active' check (status in ('active','inactive')),
  display_order int not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_voucher_products_merchant_status_order
  on voucher_products(merchant_id, status, display_order, created_at);
alter table voucher_products enable row level security;

alter table toss_payment_orders
  add column if not exists pay_type text not null default 'direct',
  add column if not exists voucher_product_id uuid references voucher_products(id),
  add column if not exists voucher_count int,
  add column if not exists voucher_purchase_price numeric(14,4),
  add column if not exists fulfilled_at timestamptz;

alter table toss_payment_orders drop constraint if exists toss_payment_orders_pay_type_check;
alter table toss_payment_orders add constraint toss_payment_orders_pay_type_check
  check (pay_type in ('direct','voucher'));
alter table toss_payment_orders drop constraint if exists toss_payment_orders_voucher_columns_check;
alter table toss_payment_orders add constraint toss_payment_orders_voucher_columns_check check (
  (pay_type = 'direct' and voucher_product_id is null and voucher_count is null
    and voucher_purchase_price is null and fulfilled_at is null)
  or
  (pay_type = 'voucher' and product_id is null and voucher_product_id is not null
    and voucher_count > 0 and voucher_purchase_price > 0 and amount > 0
    and voucher_purchase_price = round(amount::numeric / voucher_count, 4))
);
create index if not exists idx_toss_payment_orders_voucher_product
  on toss_payment_orders(voucher_product_id) where voucher_product_id is not null;

create table if not exists vouchers (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references app_users(id),
  merchant_id uuid not null references merchants(id),
  product_id uuid not null references voucher_products(id),
  order_id uuid not null references toss_payment_orders(id),
  issue_index int not null check (issue_index > 0),
  purchase_price numeric(14,4) not null check (purchase_price >= 0),
  status text not null default 'unused' check (status in ('unused','used','refunded')),
  pg_transaction_id text,
  purchased_at timestamptz not null default now(),
  used_at timestamptz,
  created_at timestamptz not null default now(),
  unique (order_id, issue_index)
);
create index if not exists idx_vouchers_user_fifo
  on vouchers(user_id, merchant_id, purchased_at, id) where status = 'unused';
alter table vouchers enable row level security;

-- Exact balance without relying on PostgREST's default row cap.
create or replace function voucher_balance(p_user_id uuid) returns bigint
language sql stable security definer set search_path = public
as $$ select count(*) from vouchers where user_id = p_user_id and status = 'unused' $$;
revoke all on function voucher_balance(uuid) from public, anon, authenticated;
grant execute on function voucher_balance(uuid) to service_role;

alter table meal_transactions
  alter column company_id drop not null,
  add column if not exists pay_type text not null default 'ledger',
  add column if not exists voucher_id uuid references vouchers(id);
alter table meal_transactions drop constraint if exists meal_transactions_pay_type_check;
alter table meal_transactions add constraint meal_transactions_pay_type_check
  check (pay_type in ('ledger','voucher'));
alter table meal_transactions drop constraint if exists meal_transactions_payment_columns_check;
alter table meal_transactions add constraint meal_transactions_payment_columns_check check (
  (pay_type = 'ledger' and company_id is not null and voucher_id is null)
  or (pay_type = 'voucher' and company_id is null and voucher_id is not null)
);
create unique index if not exists idx_meal_transactions_voucher_unique
  on meal_transactions(voucher_id) where voucher_id is not null;

-- Atomically marks a verified Toss voucher order DONE and issues all vouchers once.
-- The API must call this only after Toss returned status=DONE.
create or replace function fulfill_voucher_order(
  p_order_id uuid,
  p_payment_key text,
  p_payment_method text,
  p_toss_response jsonb,
  p_approved_at timestamptz
) returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_order toss_payment_orders%rowtype;
  v_issued int;
  v_balance int;
begin
  select * into v_order from toss_payment_orders where id = p_order_id for update;
  if not found then raise exception 'ORDER_NOT_FOUND' using errcode = 'P0001'; end if;
  if v_order.pay_type <> 'voucher' or v_order.product_id is not null
     or v_order.voucher_product_id is null or v_order.voucher_count is null
     or v_order.voucher_count <= 0 or v_order.voucher_purchase_price is null
     or v_order.voucher_purchase_price <= 0 or v_order.amount <= 0
     or v_order.voucher_purchase_price <> round(v_order.amount::numeric / v_order.voucher_count, 4) then
    raise exception 'NOT_VOUCHER_ORDER' using errcode = 'P0001';
  end if;
  if p_payment_key is null or btrim(p_payment_key) = '' then
    raise exception 'PAYMENT_KEY_REQUIRED' using errcode = 'P0001';
  end if;
  if v_order.status not in ('ready','done') then
    raise exception 'ORDER_NOT_FULFILLABLE' using errcode = 'P0001';
  end if;
  if v_order.payment_key is not null and v_order.payment_key <> p_payment_key then
    raise exception 'PAYMENT_KEY_MISMATCH' using errcode = 'P0001';
  end if;

  update toss_payment_orders set
    status = 'done', payment_key = coalesce(payment_key, p_payment_key),
    payment_method = coalesce(p_payment_method, payment_method),
    toss_response = coalesce(p_toss_response, toss_response),
    approved_at = coalesce(approved_at, p_approved_at, now()), updated_at = now()
  where id = p_order_id returning * into v_order;

  insert into vouchers(user_id, merchant_id, product_id, order_id, issue_index,
                       purchase_price, pg_transaction_id, purchased_at)
  select v_order.user_id, v_order.merchant_id, v_order.voucher_product_id, v_order.id, n,
         v_order.voucher_purchase_price, v_order.payment_key, coalesce(v_order.approved_at, now())
  from generate_series(1, v_order.voucher_count) n
  on conflict (order_id, issue_index) do nothing;

  select count(*) into v_issued from vouchers where order_id = v_order.id;
  if v_issued <> v_order.voucher_count then
    raise exception 'VOUCHER_ISSUE_INCOMPLETE' using errcode = 'P0001';
  end if;
  update toss_payment_orders set fulfilled_at = coalesce(fulfilled_at, now()) where id = v_order.id;
  select count(*) into v_balance from vouchers
    where user_id = v_order.user_id and merchant_id = v_order.merchant_id and status = 'unused';
  return jsonb_build_object('order_id', v_order.order_id, 'status', 'done',
    'issued_count', v_issued, 'voucher_balance', v_balance, 'duplicate', v_order.fulfilled_at is not null);
end;
$$;
revoke all on function fulfill_voucher_order(uuid, text, text, jsonb, timestamptz) from public, anon, authenticated;
grant execute on function fulfill_voucher_order(uuid, text, text, jsonb, timestamptz) to service_role;

-- Atomically consumes the oldest voucher and records the unified transaction.
create or replace function consume_voucher(
  p_user_id uuid,
  p_merchant_id uuid,
  p_idempotency_key text,
  p_tx_code text default null
) returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_existing meal_transactions%rowtype;
  v_voucher vouchers%rowtype;
  v_tx meal_transactions%rowtype;
  v_remaining int;
begin
  if p_idempotency_key is null or btrim(p_idempotency_key) = '' then
    raise exception 'INVALID_IDEMPOTENCY_KEY' using errcode = 'P0001';
  end if;
  -- Serialize retries with the same key so a concurrent retry observes the committed row.
  perform pg_advisory_xact_lock(1, hashtext(p_idempotency_key));
  select * into v_existing from meal_transactions where idempotency_key = p_idempotency_key limit 1;
  if found then
    if v_existing.user_id <> p_user_id or v_existing.merchant_id <> p_merchant_id
       or v_existing.pay_type <> 'voucher' or v_existing.kind <> 'spend'
       or v_existing.voucher_id is null
       or (p_tx_code is not null and v_existing.tx_code is distinct from p_tx_code) then
      raise exception 'IDEMPOTENCY_CONFLICT' using errcode = 'P0001';
    end if;
    select count(*) into v_remaining from vouchers
      where user_id = p_user_id and merchant_id = p_merchant_id and status = 'unused';
    return jsonb_build_object('id', v_existing.id, 'amount', abs(v_existing.amount),
      'voucher_id', v_existing.voucher_id, 'remaining', v_remaining, 'duplicate', true,
      'created_at', v_existing.created_at);
  end if;

  select * into v_voucher from vouchers
  where user_id = p_user_id and merchant_id = p_merchant_id and status = 'unused'
  order by purchased_at asc, id asc for update skip locked limit 1;
  if not found then raise exception 'NO_VOUCHER' using errcode = 'P0001'; end if;

  update vouchers set status = 'used', used_at = now() where id = v_voucher.id;
  insert into meal_transactions(user_id, company_id, merchant_id, amount, kind, tx_code,
    meal_window, flags, idempotency_key, product_name, product_price, pay_type, voucher_id)
  values (p_user_id, null, p_merchant_id, -round(v_voucher.purchase_price)::int, 'spend',
    coalesce(p_tx_code, upper(substr(replace(gen_random_uuid()::text, '-', ''), 1, 10))),
    '식권', jsonb_build_object('voucher_product_id', v_voucher.product_id), p_idempotency_key,
    '식권 사용', round(v_voucher.purchase_price)::int, 'voucher', v_voucher.id)
  returning * into v_tx;
  select count(*) into v_remaining from vouchers
    where user_id = p_user_id and merchant_id = p_merchant_id and status = 'unused';
  return jsonb_build_object('id', v_tx.id, 'amount', abs(v_tx.amount), 'voucher_id', v_voucher.id,
    'remaining', v_remaining, 'duplicate', false, 'created_at', v_tx.created_at);
end;
$$;
revoke all on function consume_voucher(uuid, uuid, text, text) from public, anon, authenticated;
grant execute on function consume_voucher(uuid, uuid, text, text) to service_role;

-- Keep legacy employee inserts explicitly classified as ledger transactions.
create or replace function process_meal_pay(
  p_user_id uuid, p_company_id uuid, p_merchant_id uuid, p_amount int, p_tx_code text,
  p_meal_window text, p_flags jsonb, p_idempotency_key text, p_product_id uuid default null,
  p_product_name text default null, p_product_price int default null
) returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_existing meal_transactions%rowtype;
  v_company_status text;
  v_contract_price int;
  v_tx meal_transactions%rowtype;
begin
  if p_idempotency_key is null or btrim(p_idempotency_key) = '' then
    raise exception 'INVALID_IDEMPOTENCY_KEY' using errcode = 'P0001';
  end if;
  if p_amount is null or p_amount <= 0 then raise exception 'INVALID_AMOUNT' using errcode = 'P0001'; end if;
  -- All retries serialize before any user/company row lock.
  perform pg_advisory_xact_lock(1, hashtext(p_idempotency_key));
  select * into v_existing from meal_transactions where idempotency_key = p_idempotency_key limit 1;
  if found then
    if v_existing.user_id <> p_user_id or v_existing.company_id is distinct from p_company_id
       or v_existing.merchant_id <> p_merchant_id or v_existing.pay_type <> 'ledger'
       or v_existing.kind <> 'spend' or abs(v_existing.amount) <> p_amount
       or v_existing.product_id is distinct from p_product_id
       or v_existing.product_name is distinct from p_product_name
       or v_existing.product_price is distinct from p_product_price then
      raise exception 'IDEMPOTENCY_CONFLICT' using errcode = 'P0001';
    end if;
    return jsonb_build_object('id',v_existing.id,'tx_code',v_existing.tx_code,
      'amount',abs(v_existing.amount),'duplicate',true,'created_at',v_existing.created_at,
      'product_id',v_existing.product_id,'product_name',v_existing.product_name,
      'product_price',v_existing.product_price,'pay_type','ledger');
  end if;

  perform pg_advisory_xact_lock(2, hashtext(p_user_id::text));
  select status into v_company_status from companies where id = p_company_id for share;
  if v_company_status is distinct from 'active' then raise exception 'COMPANY_NOT_ACTIVE' using errcode = 'P0001'; end if;
  select unit_price into v_contract_price from merchant_companies
    where merchant_id=p_merchant_id and company_id=p_company_id and status='active' for share;
  if not found then raise exception 'NOT_AFFILIATED' using errcode = 'P0001'; end if;
  if v_contract_price is null or v_contract_price <= 0 then raise exception 'PRICE_NOT_CONFIGURED' using errcode = 'P0001'; end if;
  if p_amount <> v_contract_price then raise exception 'CONTRACT_PRICE_MISMATCH' using errcode = 'P0001'; end if;

  insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,tx_code,meal_window,flags,idempotency_key,product_id,product_name,product_price,pay_type)
  values(p_user_id,p_company_id,p_merchant_id,-p_amount,'spend',p_tx_code,p_meal_window,coalesce(p_flags,'{}'::jsonb),p_idempotency_key,p_product_id,p_product_name,p_product_price,'ledger') returning * into v_tx;
  return jsonb_build_object('id',v_tx.id,'tx_code',v_tx.tx_code,'amount',abs(v_tx.amount),'duplicate',false,'created_at',v_tx.created_at,'product_id',v_tx.product_id,'product_name',v_tx.product_name,'product_price',v_tx.product_price,'pay_type','ledger');
end; $$;
revoke all on function process_meal_pay(uuid, uuid, uuid, int, text, text, jsonb, text, uuid, text, int) from public, anon, authenticated;
grant execute on function process_meal_pay(uuid, uuid, uuid, int, text, text, jsonb, text, uuid, text, int) to service_role;
