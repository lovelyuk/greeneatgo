-- Real prepaid merchant-company meal-ticket inventory.
-- Inventory mutations are available only through service-role RPCs.

grant usage on schema public to service_role;

alter table public.merchant_companies
  add column if not exists prepurchase_enabled boolean not null default false;

create table if not exists public.merchant_company_prepurchase_batches (
  id uuid primary key default gen_random_uuid(),
  merchant_id uuid not null references public.merchants(id),
  company_id uuid not null references public.companies(id),
  purchase_quantity integer not null check (purchase_quantity > 0),
  unit_price integer not null check (unit_price > 0),
  total_amount bigint not null,
  remaining_quantity integer not null,
  purchased_at timestamptz not null default now(),
  actor_id uuid not null references public.app_users(id),
  idempotency_key text not null check (length(btrim(idempotency_key)) between 1 and 200),
  check (remaining_quantity between 0 and purchase_quantity),
  check (total_amount = purchase_quantity::bigint * unit_price::bigint),
  unique (merchant_id, idempotency_key),
  foreign key (merchant_id, company_id)
    references public.merchant_companies(merchant_id, company_id)
);
comment on column public.merchant_company_prepurchase_batches.unit_price is
  'Immutable price snapshot for this purchased ticket entitlement. It is intentionally supplied per batch and may differ from the current merchant-company contract unit_price.';
create index if not exists merchant_company_prepurchase_fifo_idx
  on public.merchant_company_prepurchase_batches(merchant_id, company_id, purchased_at, id)
  where remaining_quantity > 0;
create index if not exists merchant_company_prepurchase_history_idx
  on public.merchant_company_prepurchase_batches(merchant_id, company_id, purchased_at desc, id desc);

create table if not exists public.merchant_company_prepurchase_consumptions (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid not null references public.merchant_company_prepurchase_batches(id),
  meal_transaction_id bigint not null unique references public.meal_transactions(id),
  consumed_at timestamptz not null default now()
);
create index if not exists merchant_company_prepurchase_consumptions_batch_idx
  on public.merchant_company_prepurchase_consumptions(batch_id, consumed_at, id);

alter table public.merchant_company_prepurchase_batches enable row level security;
alter table public.merchant_company_prepurchase_consumptions enable row level security;
revoke all on table public.merchant_company_prepurchase_batches from public, anon, authenticated, service_role;
revoke all on table public.merchant_company_prepurchase_consumptions from public, anon, authenticated, service_role;
grant select on table public.merchant_company_prepurchase_batches to service_role;
grant select on table public.merchant_company_prepurchase_consumptions to service_role;

create or replace function public.charge_merchant_company_prepurchase(
 p_merchant_id uuid, p_company_id uuid, p_actor_id uuid,
 p_quantity integer, p_unit_price integer, p_idempotency_key text
) returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare contract public.merchant_companies%rowtype;
 batch public.merchant_company_prepurchase_batches%rowtype;
 inserted boolean := false; total_remaining bigint;
begin
 if p_quantity is null or p_quantity <= 0 or p_quantity > 1000000
   or p_unit_price is null or p_unit_price <= 0 or p_unit_price > 10000000
 then raise exception 'INVALID_PREPURCHASE_CHARGE' using errcode='P0001'; end if;
 if p_idempotency_key is null or length(btrim(p_idempotency_key)) not between 1 and 200
 then raise exception 'INVALID_IDEMPOTENCY_KEY' using errcode='P0001'; end if;
 if not exists(
  select 1 from public.app_users u
  where u.id=p_actor_id and u.status='active' and u.role='merchant_admin'
    and (u.merchant_id=p_merchant_id or exists(
      select 1 from public.merchant_admins ma
      where ma.user_id=u.id and ma.merchant_id=p_merchant_id
    ))
 ) then raise exception 'PREPURCHASE_ACTOR_FORBIDDEN' using errcode='P0001'; end if;
 perform pg_advisory_xact_lock(hashtextextended('prepurchase-charge:'||p_merchant_id::text||':'||p_idempotency_key,0));
 -- A committed request is authoritative. Check it before mutable contract state
 -- so a safe retry still succeeds after a contract is paused or disabled.
 select * into batch from public.merchant_company_prepurchase_batches
  where merchant_id=p_merchant_id and idempotency_key=btrim(p_idempotency_key);
 if found then
  if batch.company_id<>p_company_id or batch.purchase_quantity<>p_quantity or batch.unit_price<>p_unit_price
  then raise exception 'IDEMPOTENCY_CONFLICT' using errcode='P0001'; end if;
  select coalesce(sum(remaining_quantity),0) into total_remaining
   from public.merchant_company_prepurchase_batches
   where merchant_id=p_merchant_id and company_id=p_company_id;
  return jsonb_build_object('id',batch.id,'company_id',batch.company_id,
   'purchase_quantity',batch.purchase_quantity,'unit_price',batch.unit_price,
   'amount',batch.total_amount,'remaining_quantity',batch.remaining_quantity,
   'total_remaining',total_remaining,'purchased_at',batch.purchased_at,'actor_id',batch.actor_id,
   'idempotency_key',batch.idempotency_key,'duplicate',true);
 end if;
 select * into contract from public.merchant_companies
  where merchant_id=p_merchant_id and company_id=p_company_id for update;
 if not found or contract.status<>'active' then raise exception 'PREPURCHASE_CONTRACT_NOT_FOUND' using errcode='P0001'; end if;
 if not contract.prepurchase_enabled then raise exception 'PREPURCHASE_NOT_ENABLED' using errcode='P0001'; end if;
 insert into public.merchant_company_prepurchase_batches(
  merchant_id,company_id,purchase_quantity,unit_price,total_amount,remaining_quantity,actor_id,idempotency_key)
 values(p_merchant_id,p_company_id,p_quantity,p_unit_price,p_quantity::bigint*p_unit_price::bigint,p_quantity,p_actor_id,btrim(p_idempotency_key))
 on conflict(merchant_id,idempotency_key) do nothing returning * into batch;
 inserted:=found;
 if not inserted then raise exception 'IDEMPOTENCY_CONFLICT' using errcode='P0001'; end if;
 select coalesce(sum(remaining_quantity),0) into total_remaining
  from public.merchant_company_prepurchase_batches
  where merchant_id=p_merchant_id and company_id=p_company_id;
 return jsonb_build_object('id',batch.id,'company_id',batch.company_id,
  'purchase_quantity',batch.purchase_quantity,'unit_price',batch.unit_price,
  'amount',batch.total_amount,'remaining_quantity',batch.remaining_quantity,
  'total_remaining',total_remaining,'purchased_at',batch.purchased_at,'actor_id',batch.actor_id,
  'idempotency_key',batch.idempotency_key,'duplicate',not inserted);
end $$;
revoke all on function public.charge_merchant_company_prepurchase(uuid,uuid,uuid,integer,integer,text) from public,anon,authenticated;
grant execute on function public.charge_merchant_company_prepurchase(uuid,uuid,uuid,integer,integer,text) to service_role;

create or replace function public.list_merchant_company_prepurchase_inventory(p_merchant_id uuid)
returns jsonb language sql stable security definer set search_path=pg_catalog,public as $$
 with eligible as (
  select mc.id as merchant_company_id,mc.company_id,c.name as company_name,mc.prepurchase_enabled,
   latest.purchased_at as latest_purchase_at,latest.purchased_at as latest_purchase_date,
   latest.purchase_quantity,latest.unit_price,
   coalesce(t.total_remaining,0) as remaining_quantity,
   coalesce(t.total_remaining,0) as total_remaining
  from public.merchant_companies mc
  join public.companies c on c.id=mc.company_id
  left join lateral (
   select b.purchased_at,b.purchase_quantity,b.unit_price
   from public.merchant_company_prepurchase_batches b
   where b.merchant_id=mc.merchant_id and b.company_id=mc.company_id
   order by b.purchased_at desc,b.id desc limit 1
  ) latest on true
  left join lateral (
   select sum(b.remaining_quantity)::bigint as total_remaining
   from public.merchant_company_prepurchase_batches b
   where b.merchant_id=mc.merchant_id and b.company_id=mc.company_id
  ) t on true
  where mc.merchant_id=p_merchant_id and mc.status='active' and mc.prepurchase_enabled
 )
 select jsonb_build_object('items',coalesce(jsonb_agg(to_jsonb(eligible)
  order by latest_purchase_at desc nulls last,company_name),'[]'::jsonb)) from eligible
$$;
revoke all on function public.list_merchant_company_prepurchase_inventory(uuid) from public,anon,authenticated;
grant execute on function public.list_merchant_company_prepurchase_inventory(uuid) to service_role;

create or replace function public.list_merchant_company_prepurchase_charges(
 p_merchant_id uuid,p_company_id uuid,p_limit integer default 50,p_offset integer default 0
) returns jsonb language sql stable security definer set search_path=pg_catalog,public as $$
 with allowed as (
  select 1 from public.merchant_companies
  where merchant_id=p_merchant_id and company_id=p_company_id and status='active'
 ), bounds as (
  select greatest(1,least(coalesce(p_limit,50),100)) lim,greatest(coalesce(p_offset,0),0) off
 ), eligible as (
  select b.id,b.company_id,b.purchase_quantity,b.unit_price,b.total_amount as amount,
   b.remaining_quantity,b.purchased_at,b.actor_id,b.idempotency_key
  from public.merchant_company_prepurchase_batches b,allowed
  where b.merchant_id=p_merchant_id and b.company_id=p_company_id
 ), page as (
  select e.* from eligible e,bounds order by e.purchased_at desc,e.id desc
  limit (select lim from bounds) offset (select off from bounds)
 )
 select jsonb_build_object('items',coalesce((select jsonb_agg(to_jsonb(page) order by purchased_at desc,id desc) from page),'[]'::jsonb),
  'total',(select count(*) from eligible),'total_remaining',(select coalesce(sum(remaining_quantity),0) from eligible),
  'limit',(select lim from bounds),'offset',(select off from bounds))
$$;
revoke all on function public.list_merchant_company_prepurchase_charges(uuid,uuid,integer,integer) from public,anon,authenticated;
grant execute on function public.list_merchant_company_prepurchase_charges(uuid,uuid,integer,integer) to service_role;

-- Signature-compatible evolution of the complete 0036 ledger RPC. Prepaid
-- contracts consume one FIFO ticket in the same transaction as the ledger row.
create or replace function public.process_meal_pay(p_user_id uuid,p_company_id uuid,p_merchant_id uuid,p_amount int,p_tx_code text,
 p_meal_window text,p_flags jsonb,p_idempotency_key text,p_product_id uuid default null,p_product_name text default null,p_product_price int default null)
returns jsonb language plpgsql security definer set search_path=public as $$
declare existing meal_transactions%rowtype; company_status text; contract merchant_companies%rowtype; tx meal_transactions%rowtype; s record;
 batch merchant_company_prepurchase_batches%rowtype; remaining_total bigint; consumed_batch_id uuid;
 tx_flags jsonb; settlement_supply int; settlement_vat int; settlement_total int;
begin
 if p_idempotency_key is null or btrim(p_idempotency_key)='' then raise exception 'INVALID_IDEMPOTENCY_KEY' using errcode='P0001'; end if;
 if p_amount is null or p_amount<=0 then raise exception 'INVALID_AMOUNT' using errcode='P0001'; end if;
 perform pg_advisory_xact_lock(1,hashtext(p_idempotency_key));
 select * into existing from meal_transactions where idempotency_key=p_idempotency_key limit 1;
 if found then
  if existing.user_id<>p_user_id or existing.company_id is distinct from p_company_id or existing.merchant_id<>p_merchant_id or existing.pay_type<>'ledger'
   or existing.kind<>'spend' or abs(existing.amount)<>p_amount or existing.product_id is distinct from p_product_id
   or existing.product_name is distinct from p_product_name or existing.product_price is distinct from p_product_price
   or existing.tax_type='unclassified' or existing.total_amount is null or existing.settlement_total_amount is null
  then raise exception 'IDEMPOTENCY_CONFLICT' using errcode='P0001'; end if;
  select c.batch_id into consumed_batch_id from merchant_company_prepurchase_consumptions c where c.meal_transaction_id=existing.id;
  if consumed_batch_id is not null then
   select coalesce(sum(remaining_quantity),0) into remaining_total from merchant_company_prepurchase_batches
    where merchant_id=p_merchant_id and company_id=p_company_id;
  end if;
  return jsonb_build_object('id',existing.id,'tx_code',existing.tx_code,'amount',existing.total_amount,'duplicate',true,'created_at',existing.created_at,
   'product_id',existing.product_id,'product_name',existing.product_name,'product_price',existing.product_price,'pay_type','ledger','tax_type',existing.tax_type,
   'supply_amount',existing.supply_amount,'vat_amount',existing.vat_amount,'total_amount',existing.total_amount,
   'settlement_tax_type',existing.settlement_tax_type,'settlement_supply_amount',existing.settlement_supply_amount,
   'settlement_vat_amount',existing.settlement_vat_amount,'settlement_total_amount',existing.settlement_total_amount,
   'prepurchase_batch_id',consumed_batch_id,'prepurchase_remaining',remaining_total);
 end if;
 perform pg_advisory_xact_lock(2,hashtext(p_user_id::text));
 select status into company_status from companies where id=p_company_id for share;
 if company_status is distinct from 'active' then raise exception 'COMPANY_NOT_ACTIVE' using errcode='P0001'; end if;
 select * into contract from merchant_companies where merchant_id=p_merchant_id and company_id=p_company_id and status='active' for update;
 if not found then raise exception 'NOT_AFFILIATED' using errcode='P0001'; end if;
 if contract.unit_price is null or contract.unit_price<=0 then raise exception 'PRICE_NOT_CONFIGURED' using errcode='P0001'; end if;
 if p_amount<>contract.unit_price then raise exception 'CONTRACT_PRICE_MISMATCH' using errcode='P0001'; end if;
 if contract.tax_type='unclassified' then raise exception 'TAX_TYPE_UNCLASSIFIED' using errcode='P0001'; end if;
 if contract.prepurchase_enabled then
  select * into batch from merchant_company_prepurchase_batches
   where merchant_id=p_merchant_id and company_id=p_company_id and remaining_quantity>0
   order by purchased_at,id limit 1 for update;
  if not found then raise exception 'PREPURCHASE_INVENTORY_EMPTY' using errcode='P0001'; end if;
  update merchant_company_prepurchase_batches set remaining_quantity=remaining_quantity-1
   where id=batch.id and remaining_quantity>0 returning * into batch;
  if not found then raise exception 'PREPURCHASE_INVENTORY_EMPTY' using errcode='P0001'; end if;
  consumed_batch_id:=batch.id;
 end if;
 select * into s from split_tax_inclusive(p_amount,contract.tax_type);
 tx_flags:=coalesce(p_flags,'{}'::jsonb);
 settlement_supply:=s.supply_amount; settlement_vat:=s.vat_amount; settlement_total:=s.total_amount;
 if consumed_batch_id is not null then
  tx_flags:=tx_flags||jsonb_build_object('prepurchase',true,'prepurchase_batch_id',consumed_batch_id);
  settlement_supply:=0; settlement_vat:=0; settlement_total:=0;
 end if;
 insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,tx_code,meal_window,flags,idempotency_key,product_id,product_name,product_price,pay_type,
  tax_type,supply_amount,vat_amount,total_amount,settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount)
 values(p_user_id,p_company_id,p_merchant_id,-p_amount,'spend',p_tx_code,p_meal_window,tx_flags,p_idempotency_key,p_product_id,p_product_name,
  p_product_price,'ledger',contract.tax_type,s.supply_amount,s.vat_amount,s.total_amount,contract.tax_type,settlement_supply,settlement_vat,settlement_total) returning * into tx;
 if consumed_batch_id is not null then
  insert into merchant_company_prepurchase_consumptions(batch_id,meal_transaction_id) values(consumed_batch_id,tx.id);
  select coalesce(sum(remaining_quantity),0) into remaining_total from merchant_company_prepurchase_batches
   where merchant_id=p_merchant_id and company_id=p_company_id;
 end if;
 return jsonb_build_object('id',tx.id,'tx_code',tx.tx_code,'amount',tx.total_amount,'duplicate',false,'created_at',tx.created_at,'product_id',tx.product_id,
  'product_name',tx.product_name,'product_price',tx.product_price,'pay_type','ledger','tax_type',tx.tax_type,'supply_amount',tx.supply_amount,'vat_amount',tx.vat_amount,
  'total_amount',tx.total_amount,'settlement_tax_type',tx.settlement_tax_type,'settlement_supply_amount',tx.settlement_supply_amount,
  'settlement_vat_amount',tx.settlement_vat_amount,'settlement_total_amount',tx.settlement_total_amount,
  'prepurchase_batch_id',consumed_batch_id,'prepurchase_remaining',remaining_total);
end $$;
revoke all on function public.process_meal_pay(uuid,uuid,uuid,int,text,text,jsonb,text,uuid,text,int) from public,anon,authenticated;
grant execute on function public.process_meal_pay(uuid,uuid,uuid,int,text,text,jsonb,text,uuid,text,int) to service_role;

-- Every refund/cancel that points at a consumed prepaid spend is audited. The
-- unique consumption key makes restoration automatic and exactly-once even if
-- multiple reversal rows are later written for the same spend.
create table if not exists public.merchant_company_prepurchase_reversals (
 id uuid primary key default gen_random_uuid(),
 consumption_id uuid not null unique references public.merchant_company_prepurchase_consumptions(id),
 batch_id uuid not null references public.merchant_company_prepurchase_batches(id),
 original_meal_transaction_id bigint not null references public.meal_transactions(id),
 reversal_meal_transaction_id bigint not null unique references public.meal_transactions(id),
 restored_quantity integer not null default 1 check (restored_quantity=1),
 restored_at timestamptz not null default now()
);
create index if not exists merchant_company_prepurchase_reversals_batch_idx
 on public.merchant_company_prepurchase_reversals(batch_id,restored_at,id);
alter table public.merchant_company_prepurchase_reversals enable row level security;
revoke all on table public.merchant_company_prepurchase_reversals from public,anon,authenticated,service_role;
grant select on table public.merchant_company_prepurchase_reversals to service_role;

-- Normalize a prepaid reversal before any AFTER INSERT settlement trigger can
-- observe it. PostgreSQL orders triggers with the same timing alphabetically, so
-- this must be a BEFORE trigger rather than relying on an AFTER-trigger name.
create or replace function public.mark_merchant_company_prepurchase_reversal()
returns trigger language plpgsql security definer set search_path=pg_catalog,public as $$
declare consumption public.merchant_company_prepurchase_consumptions%rowtype;
begin
 if new.kind not in ('refund','cancel') or new.original_transaction_id is null then return new; end if;
 select * into consumption from public.merchant_company_prepurchase_consumptions
  where meal_transaction_id=new.original_transaction_id;
 if not found then return new; end if;
 new.flags:=coalesce(new.flags,'{}'::jsonb)||jsonb_build_object(
  'prepurchase',true,'prepurchase_batch_id',consumption.batch_id,'prepurchase_restoration',true);
 new.settlement_supply_amount:=0;
 new.settlement_vat_amount:=0;
 new.settlement_total_amount:=0;
 return new;
end $$;
revoke all on function public.mark_merchant_company_prepurchase_reversal() from public,anon,authenticated,service_role;
drop trigger if exists trg_mark_merchant_company_prepurchase_reversal on public.meal_transactions;
create trigger trg_mark_merchant_company_prepurchase_reversal before insert on public.meal_transactions
 for each row execute function public.mark_merchant_company_prepurchase_reversal();

create or replace function public.restore_merchant_company_prepurchase_on_reversal()
returns trigger language plpgsql security definer set search_path=pg_catalog,public as $$
declare consumption public.merchant_company_prepurchase_consumptions%rowtype;
 batch public.merchant_company_prepurchase_batches%rowtype;
 reversal_id uuid;
begin
 if new.kind not in ('refund','cancel') or new.original_transaction_id is null
    or new.flags->>'prepurchase_restoration' is distinct from 'true' then return new; end if;
 select * into consumption from public.merchant_company_prepurchase_consumptions
  where meal_transaction_id=new.original_transaction_id;
 if not found then return new; end if;
 select * into batch from public.merchant_company_prepurchase_batches
  where id=consumption.batch_id for update;
 if not found then raise exception 'PREPURCHASE_BATCH_NOT_FOUND' using errcode='P0001'; end if;
 insert into public.merchant_company_prepurchase_reversals(
  consumption_id,batch_id,original_meal_transaction_id,reversal_meal_transaction_id)
 values(consumption.id,batch.id,new.original_transaction_id,new.id)
 on conflict(consumption_id) do nothing returning id into reversal_id;
 if reversal_id is null then return new; end if;
 update public.merchant_company_prepurchase_batches
  set remaining_quantity=remaining_quantity+1
  where id=batch.id and remaining_quantity<purchase_quantity;
 if not found then raise exception 'PREPURCHASE_RESTORE_OVERFLOW' using errcode='P0001'; end if;
 return new;
end $$;
revoke all on function public.restore_merchant_company_prepurchase_on_reversal() from public,anon,authenticated,service_role;
drop trigger if exists trg_restore_merchant_company_prepurchase on public.meal_transactions;
create trigger trg_restore_merchant_company_prepurchase after insert on public.meal_transactions
 for each row execute function public.restore_merchant_company_prepurchase_on_reversal();

-- Usage remains visible in counts, while the immutable settlement snapshot is
-- authoritative for the company's outstanding postpaid amount. This makes a
-- prepaid spend (zero settlement snapshot) visible without billing it again.
create or replace function public.merchant_ledger_summary(
 p_merchant_id uuid,p_company_id uuid,p_period_from date,p_period_to date
) returns jsonb language plpgsql stable security definer set search_path=pg_catalog,public as $$
declare v_result jsonb;
begin
 if p_period_from is null or p_period_to is null or p_period_from>p_period_to then
  raise exception 'INVALID_DATE_RANGE' using errcode='P0001';
 end if;
 select jsonb_build_object(
  'total_amount',coalesce(sum(case
   when kind='spend' then case when pay_type='subsidized' then company_subsidy_amount
    else coalesce(settlement_total_amount,abs(amount)) end
   when kind in ('refund','cancel') then -(case when pay_type='subsidized' then company_subsidy_amount
    else coalesce(settlement_total_amount,abs(amount)) end)
   else 0 end),0),
  'total_count',count(*),
  'cancel_count',count(*) filter(where kind in ('refund','cancel')),
  'restaurant_subsidy_amount',coalesce(sum(case
   when kind='spend' and pay_type='subsidized' then restaurant_subsidy_amount
   when kind in ('refund','cancel') and pay_type='subsidized' then -restaurant_subsidy_amount
   else 0 end),0)
 ) into v_result from public.meal_transactions
 where merchant_id=p_merchant_id and company_id=p_company_id
  and pay_type in ('ledger','subsidized')
  and created_at >= (p_period_from::timestamp at time zone 'Asia/Seoul')
  and created_at < ((p_period_to+1)::timestamp at time zone 'Asia/Seoul');
 return v_result;
end $$;
revoke all on function public.merchant_ledger_summary(uuid,uuid,date,date) from public,anon,authenticated;
grant execute on function public.merchant_ledger_summary(uuid,uuid,date,date) to service_role;

notify pgrst, 'reload schema';
