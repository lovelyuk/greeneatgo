-- Atomic, tenant-checked settlement workflows for company and merchant operators.
-- All mutations are service-owned RPCs. Actor and tenant are verified from rows;
-- no JWT GUC or other caller-settable session state is trusted.

create table if not exists public.settlement_events (
  id bigint generated always as identity primary key,
  settlement_id uuid not null references public.settlements(id),
  company_id uuid not null references public.companies(id),
  merchant_id uuid not null references public.merchants(id),
  event_type text not null check (char_length(btrim(event_type)) between 1 and 80),
  payload jsonb not null default '{}'::jsonb,
  idempotency_key text,
  actor_id uuid not null references public.app_users(id) on delete restrict,
  created_at timestamptz not null default now(),
  constraint settlement_events_idempotency_key_check check (
    idempotency_key is null or char_length(btrim(idempotency_key)) between 1 and 128
  ),
  constraint settlement_events_parties_fkey foreign key
    (settlement_id, company_id, merchant_id)
    references public.settlements(id, company_id, merchant_id)
);
create index if not exists idx_settlement_events_settlement_created
  on public.settlement_events(settlement_id, created_at, id);
create unique index if not exists idx_settlement_events_idempotency_unique
  on public.settlement_events(settlement_id, event_type, idempotency_key)
  where idempotency_key is not null;

create or replace function public.prevent_settlement_event_mutation() returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$ begin
  raise exception 'SETTLEMENT_EVENTS_ARE_IMMUTABLE' using errcode = '55000';
end $$;
revoke all on function public.prevent_settlement_event_mutation() from public, anon, authenticated, service_role;
drop trigger if exists trg_settlement_events_immutable on public.settlement_events;
create trigger trg_settlement_events_immutable before update or delete on public.settlement_events
for each row execute function public.prevent_settlement_event_mutation();

alter table public.settlement_events enable row level security;
revoke all on table public.settlement_events from anon, authenticated, service_role;
grant select, insert on table public.settlement_events to service_role;
revoke all on sequence public.settlement_events_id_seq from anon, authenticated, service_role;
grant usage, select on sequence public.settlement_events_id_seq to service_role;

-- Retire the pre-tax-snapshot implementation from 0016 while preserving its exact
-- PostgREST signature. This service-role-only compatibility wrapper receives the
-- authoritative merchant tenant from the API and verifies its active contract.
create or replace function public.create_merchant_settlement(
  p_merchant_id uuid, p_company_id uuid, p_period_from date, p_period_to date
) returns jsonb
language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare
  v_row public.settlements%rowtype;
  v_period_ym text;
  v_count int;
  v_classified_count int;
  v_supply bigint;
  v_vat bigint;
  v_total bigint;
begin
  if p_period_from is null or p_period_to is null or p_period_from > p_period_to
     or date_trunc('month',p_period_from::timestamp) <> date_trunc('month',p_period_to::timestamp) then
    raise exception 'INVALID_DATE_RANGE' using errcode='P0001';
  end if;
  if not exists(select 1 from public.merchants where id=p_merchant_id and status='active')
     or not exists(select 1 from public.companies where id=p_company_id and status='active')
     or not exists(select 1 from public.merchant_companies
                   where merchant_id=p_merchant_id and company_id=p_company_id and status='active') then
    raise exception 'SETTLEMENT_FORBIDDEN' using errcode='P0001';
  end if;

  v_period_ym:=to_char(p_period_from,'YYYY-MM');
  perform pg_advisory_xact_lock(pg_catalog.hashtext(p_merchant_id::text),
                                pg_catalog.hashtext(p_company_id::text||':'||v_period_ym));

  select count(*),
         count(*) filter(where t.settlement_tax_type in ('taxable','tax_free')
                           and t.settlement_supply_amount is not null
                           and t.settlement_vat_amount is not null
                           and t.settlement_total_amount is not null
                           and t.settlement_supply_amount+t.settlement_vat_amount=t.settlement_total_amount
                           and ((t.settlement_tax_type='tax_free' and t.settlement_vat_amount=0
                                 and t.settlement_supply_amount=t.settlement_total_amount)
                             or (t.settlement_tax_type='taxable'
                                 and t.settlement_supply_amount=round(t.settlement_total_amount::numeric/1.1)::int
                                 and t.settlement_vat_amount=t.settlement_total_amount-t.settlement_supply_amount))),
         coalesce(sum(case when t.kind='spend' then t.settlement_supply_amount else -t.settlement_supply_amount end),0),
         coalesce(sum(case when t.kind='spend' then t.settlement_vat_amount else -t.settlement_vat_amount end),0),
         coalesce(sum(case when t.kind='spend' then t.settlement_total_amount else -t.settlement_total_amount end),0)
    into v_count,v_classified_count,v_supply,v_vat,v_total
  from public.meal_transactions t
  where t.merchant_id=p_merchant_id and t.company_id=p_company_id
    and t.pay_type in ('ledger','subsidized') and t.kind in ('spend','refund','cancel')
    and t.created_at >= (p_period_from::timestamp at time zone 'Asia/Seoul')
    and t.created_at < ((p_period_to+1)::timestamp at time zone 'Asia/Seoul');

  if v_count<>v_classified_count then
    raise exception 'TAX_TYPE_UNCLASSIFIED' using errcode='P0001';
  end if;
  if v_supply<0 or v_vat<0 or v_total<0 or v_supply+v_vat<>v_total
     or v_supply>2147483647 or v_vat>2147483647 or v_total>2147483647 then
    raise exception 'SETTLEMENT_AMOUNTS_INVALID' using errcode='P0001';
  end if;

  select * into v_row from public.settlements
   where merchant_id=p_merchant_id and company_id=p_company_id and period_ym=v_period_ym
   for update;
  if found then
    if v_row.settlement_status not in ('draft','calculating','revising') then
      raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001';
    end if;
    update public.settlements set period_from=p_period_from,period_to=p_period_to,
      tx_count=v_count,total_amount=v_total::int,supply_amount=v_supply::int,vat_amount=v_vat::int,
      settlement_status='draft',tax_invoice_status='not_requested',payment_status='unpaid',
      due_date=p_period_to+30,status='draft',updated_at=pg_catalog.clock_timestamp()
     where id=v_row.id returning * into v_row;
  else
    insert into public.settlements(company_id,merchant_id,period_ym,period_from,period_to,
      tx_count,total_amount,supply_amount,vat_amount,status,settlement_status,tax_invoice_status,
      payment_status,due_date)
    values(p_company_id,p_merchant_id,v_period_ym,p_period_from,p_period_to,v_count,v_total::int,
      v_supply::int,v_vat::int,'draft','draft','not_requested','unpaid',p_period_to+30)
    returning * into v_row;
  end if;
  return to_jsonb(v_row);
end $$;
revoke all on function public.create_merchant_settlement(uuid,uuid,date,date) from public,anon,authenticated;
grant execute on function public.create_merchant_settlement(uuid,uuid,date,date) to service_role;

-- Company confirms the exact locked server-side amount and business profile, and
-- creates the sole original invoice and audit evidence in the same transaction.
create or replace function public.company_confirm_and_request_tax_invoice(
  p_actor_id uuid, p_company_id uuid, p_settlement_id uuid
) returns jsonb
language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare
  s public.settlements%rowtype;
  c public.companies%rowtype;
  m public.merchants%rowtype;
  inv public.tax_invoices%rowtype;
  v_now timestamptz := pg_catalog.clock_timestamp();
  v_key text;
begin
  if not exists (select 1 from public.app_users u where u.id=p_actor_id and u.company_id=p_company_id and u.role='company_admin' and u.status='active') then
    raise exception 'SETTLEMENT_FORBIDDEN' using errcode='P0001';
  end if;
  select * into s from public.settlements where id=p_settlement_id and company_id=p_company_id for update;
  if not found then raise exception 'SETTLEMENT_NOT_FOUND' using errcode='P0001'; end if;

  -- A completed first call returns its immutable invoice snapshot; a later profile
  -- edit must not turn the exact same operation into a failure.
  if s.settlement_status='confirmed' and s.tax_invoice_status='requested' then
    select * into inv from public.tax_invoices where settlement_id=s.id and document_type='original';
    if not found then raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001'; end if;
    return jsonb_build_object('settlement',to_jsonb(s),'tax_invoice',to_jsonb(inv),'idempotent',true);
  end if;

  select * into c from public.companies where id=s.company_id;
  select * into m from public.merchants where id=s.merchant_id;
  if nullif(btrim(c.biz_reg_no),'') is null or nullif(btrim(c.name),'') is null
     or nullif(btrim(c.representative_name),'') is null or nullif(btrim(c.address),'') is null
     or nullif(btrim(c.business_type),'') is null or nullif(btrim(c.business_item),'') is null
     or nullif(btrim(c.tax_invoice_email),'') is null or nullif(btrim(c.contact_name),'') is null
     or nullif(btrim(c.contact_phone),'') is null then
    raise exception 'BUSINESS_PROFILE_INCOMPLETE' using errcode='P0001';
  end if;
  if nullif(btrim(m.biz_reg_no),'') is null or nullif(btrim(m.name),'') is null
     or nullif(btrim(m.representative_name),'') is null or nullif(btrim(m.address),'') is null
     or nullif(btrim(m.business_type),'') is null or nullif(btrim(m.business_item),'') is null
     or nullif(btrim(m.tax_invoice_email),'') is null or nullif(btrim(m.owner_phone),'') is null then
    raise exception 'SUPPLIER_PROFILE_INCOMPLETE' using errcode='P0001';
  end if;
  if s.supply_amount is null or s.vat_amount is null or s.total_amount is null
     or s.supply_amount < 0 or s.vat_amount < 0
     or s.supply_amount + s.vat_amount <> s.total_amount then
    raise exception 'SETTLEMENT_AMOUNTS_INVALID' using errcode='P0001';
  end if;

  if s.settlement_status <> 'sent' or s.tax_invoice_status <> 'not_requested' then
    raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001';
  end if;

  update public.settlements set settlement_status='confirmed', tax_invoice_status='requested',
    confirmed_at=coalesce(confirmed_at,v_now), updated_at=v_now where id=s.id returning * into s;
  v_key := 'GE-' || replace(s.id::text,'-','');
  insert into public.tax_invoices(
    settlement_id,company_id,merchant_id,document_type,invoicer_mgt_key,tax_type,write_date,
    supply_amount,vat_amount,total_amount,supplier_snapshot,recipient_snapshot,
    requested_at,issue_requested_by,issue_requested_at,created_by,updated_by
  ) values (
    s.id,s.company_id,s.merchant_id,'original',v_key,
    case when s.vat_amount=0 then 'tax_free' else 'taxable' end,current_date,
    s.supply_amount,s.vat_amount,s.total_amount,
    jsonb_build_object('registration_number',m.biz_reg_no,'name',m.name,
      'representative',m.representative_name,'address',m.address,'business_type',m.business_type,
      'business_item',m.business_item,'tax_email',m.tax_invoice_email,'contact_phone',m.owner_phone),
    jsonb_build_object('registration_number',c.biz_reg_no,'name',c.name,
      'representative',c.representative_name,'address',c.address,'business_type',c.business_type,
      'business_item',c.business_item,'tax_email',c.tax_invoice_email,
      'contact_name',c.contact_name,'contact_phone',c.contact_phone),
    v_now,p_actor_id,v_now,p_actor_id,p_actor_id
  ) returning * into inv;
  insert into public.settlement_events(settlement_id,company_id,merchant_id,event_type,payload,idempotency_key,actor_id)
  values(s.id,s.company_id,s.merchant_id,'company_confirmed_and_tax_invoice_requested',
    jsonb_build_object('tax_invoice_id',inv.id,'supply_amount',s.supply_amount,'vat_amount',s.vat_amount,'total_amount',s.total_amount),
    'confirm-and-request-tax-invoice',p_actor_id);
  return jsonb_build_object('settlement',to_jsonb(s),'tax_invoice',to_jsonb(inv),'idempotent',false);
end $$;

create or replace function public.company_dispute_settlement(
 p_actor_id uuid,p_company_id uuid,p_settlement_id uuid,p_reason text,p_idempotency_key text
) returns jsonb language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare s public.settlements%rowtype; e public.settlement_events%rowtype; v_payload jsonb;
begin
  if not exists(select 1 from public.app_users u where u.id=p_actor_id and u.company_id=p_company_id and u.role='company_admin' and u.status='active') then raise exception 'SETTLEMENT_FORBIDDEN' using errcode='P0001'; end if;
  if nullif(btrim(p_reason),'') is null or char_length(p_reason)>1000 or nullif(btrim(p_idempotency_key),'') is null or char_length(p_idempotency_key)>128 then raise exception 'SETTLEMENT_INPUT_INVALID' using errcode='P0001'; end if;
  select * into s from public.settlements where id=p_settlement_id and company_id=p_company_id for update;
  if not found then raise exception 'SETTLEMENT_NOT_FOUND' using errcode='P0001'; end if;
  v_payload:=jsonb_build_object('reason',btrim(p_reason));
  select * into e from public.settlement_events where settlement_id=s.id and event_type='company_disputed' and idempotency_key=p_idempotency_key;
  if found then
    if e.payload<>v_payload then raise exception 'IDEMPOTENCY_CONFLICT' using errcode='P0001'; end if;
    return jsonb_build_object('settlement',to_jsonb(s),'event',to_jsonb(e),'idempotent',true);
  end if;
  if s.settlement_status<>'sent' then raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001'; end if;
  update public.settlements set settlement_status='disputed',updated_at=now() where id=s.id returning * into s;
  insert into public.settlement_events(settlement_id,company_id,merchant_id,event_type,payload,idempotency_key,actor_id)
    values(s.id,s.company_id,s.merchant_id,'company_disputed',v_payload,p_idempotency_key,p_actor_id) returning * into e;
  return jsonb_build_object('settlement',to_jsonb(s),'event',to_jsonb(e),'idempotent',false);
end $$;

create or replace function public.merchant_send_settlement(
 p_actor_id uuid,p_merchant_id uuid,p_settlement_id uuid
) returns jsonb language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare
  s public.settlements%rowtype;
  e public.settlement_events%rowtype;
  v_cycle int;
  v_now timestamptz := pg_catalog.clock_timestamp();
begin
  if not exists(select 1 from public.app_users u where u.id=p_actor_id and u.merchant_id=p_merchant_id and u.role='merchant_admin' and u.status='active') then raise exception 'SETTLEMENT_FORBIDDEN' using errcode='P0001'; end if;
  select * into s from public.settlements where id=p_settlement_id and merchant_id=p_merchant_id for update;
  if not found then raise exception 'SETTLEMENT_NOT_FOUND' using errcode='P0001'; end if;
  if s.settlement_status='sent' then return jsonb_build_object('settlement',to_jsonb(s),'idempotent',true); end if;
  if s.settlement_status not in ('draft','revising') then raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001'; end if;
  if s.due_date is null or s.supply_amount is null or s.vat_amount is null or s.total_amount is null
     or s.supply_amount<0 or s.vat_amount<0 or s.supply_amount+s.vat_amount<>s.total_amount then raise exception 'SETTLEMENT_AMOUNTS_INVALID' using errcode='P0001'; end if;
  select count(*)+1 into v_cycle from public.settlement_events
    where settlement_id=s.id and event_type='merchant_sent';
  update public.settlements set settlement_status='sent',sent_at=v_now,updated_at=v_now where id=s.id returning * into s;
  insert into public.settlement_events(settlement_id,company_id,merchant_id,event_type,payload,idempotency_key,actor_id)
   values(s.id,s.company_id,s.merchant_id,'merchant_sent',
     jsonb_build_object('due_date',s.due_date,'total_amount',s.total_amount,'send_cycle',v_cycle),
     'send-cycle-'||v_cycle::text,p_actor_id) returning * into e;
  return jsonb_build_object('settlement',to_jsonb(s),'event',to_jsonb(e),'idempotent',false);
end $$;

create or replace function public.merchant_mark_settlement_paid(
 p_actor_id uuid,p_merchant_id uuid,p_settlement_id uuid,p_amount int,p_depositor_name text,
 p_deposited_at timestamptz,p_memo text,p_idempotency_key text
) returns jsonb language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare s public.settlements%rowtype; pay public.settlement_payments%rowtype; e public.settlement_events%rowtype; v_payload jsonb;
begin
  if not exists(select 1 from public.app_users u where u.id=p_actor_id and u.merchant_id=p_merchant_id and u.role='merchant_admin' and u.status='active') then raise exception 'SETTLEMENT_FORBIDDEN' using errcode='P0001'; end if;
  if p_amount<=0 or p_deposited_at is null or nullif(btrim(p_depositor_name),'') is null or char_length(p_depositor_name)>100
     or nullif(btrim(p_idempotency_key),'') is null or char_length(p_idempotency_key)>128 or char_length(coalesce(p_memo,''))>500 then raise exception 'SETTLEMENT_INPUT_INVALID' using errcode='P0001'; end if;
  select * into s from public.settlements where id=p_settlement_id and merchant_id=p_merchant_id for update;
  if not found then raise exception 'SETTLEMENT_NOT_FOUND' using errcode='P0001'; end if;
  select * into pay from public.settlement_payments where idempotency_key=p_idempotency_key;
  if found then
    if pay.settlement_id<>s.id or pay.amount<>p_amount or pay.depositor_name is distinct from btrim(p_depositor_name)
       or pay.deposited_at<>p_deposited_at or pay.memo is distinct from nullif(btrim(coalesce(p_memo,'')),'') then raise exception 'IDEMPOTENCY_CONFLICT' using errcode='P0001'; end if;
    select * into s from public.settlements where id=s.id;
    return jsonb_build_object('settlement',to_jsonb(s),'payment',to_jsonb(pay),'idempotent',true);
  end if;
  if s.tax_invoice_status not in ('issued','nts_sending','nts_accepted') or s.settlement_status in ('cancelled','disputed') then raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001'; end if;
  insert into public.settlement_payments(settlement_id,amount,depositor_name,deposited_at,match_method,confirmed_by,confirmed_at,idempotency_key,memo,audit_metadata,created_by,updated_by)
   values(s.id,p_amount,btrim(p_depositor_name),p_deposited_at,'manual',p_actor_id,now(),p_idempotency_key,nullif(btrim(coalesce(p_memo,'')),''),jsonb_build_object('source','merchant_operator'),p_actor_id,p_actor_id) returning * into pay;
  v_payload:=jsonb_build_object('payment_id',pay.id,'amount',pay.amount,'deposited_at',pay.deposited_at);
  insert into public.settlement_events(settlement_id,company_id,merchant_id,event_type,payload,idempotency_key,actor_id)
   values(s.id,s.company_id,s.merchant_id,'merchant_payment_recorded',v_payload,p_idempotency_key,p_actor_id) returning * into e;
  select * into s from public.settlements where id=s.id;
  return jsonb_build_object('settlement',to_jsonb(s),'payment',to_jsonb(pay),'event',to_jsonb(e),'idempotent',false);
end $$;

-- Safe implementation behind the legacy admin confirm-payment route. The parent
-- lock serializes retries and the amount is always the server-computed remainder.
create or replace function public.merchant_confirm_settlement_payment_legacy(
 p_actor_id uuid,p_merchant_id uuid,p_company_id uuid,p_settlement_id uuid
) returns jsonb language plpgsql security definer
set search_path=pg_catalog,public as $$
declare
 s public.settlements%rowtype;
 pay public.settlement_payments%rowtype;
 e public.settlement_events%rowtype;
 v_paid bigint;
 v_remaining bigint;
 v_key text:='legacy-confirm-payment:'||p_settlement_id::text;
 v_now timestamptz:=pg_catalog.clock_timestamp();
begin
 if not exists(select 1 from public.app_users u where u.id=p_actor_id
   and u.merchant_id=p_merchant_id and u.role='merchant_admin' and u.status='active')
 then raise exception 'SETTLEMENT_FORBIDDEN' using errcode='P0001'; end if;
 select * into s from public.settlements where id=p_settlement_id
   and merchant_id=p_merchant_id and company_id=p_company_id for update;
 if not found then raise exception 'SETTLEMENT_NOT_FOUND' using errcode='P0001'; end if;
 select * into pay from public.settlement_payments where idempotency_key=v_key;
 if found then
   return jsonb_build_object('settlement',to_jsonb(s),'payment',to_jsonb(pay),'idempotent',true);
 end if;
 if s.tax_invoice_status not in ('issued','nts_sending','nts_accepted')
    or s.settlement_status in ('cancelled','disputed')
 then raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001'; end if;
 select coalesce(sum(amount),0) into v_paid from public.settlement_payments
  where settlement_id=s.id and confirmed_at is not null;
 v_remaining:=s.total_amount-v_paid;
 if v_remaining<=0 then
   return jsonb_build_object('settlement',to_jsonb(s),'payment',null,'idempotent',true);
 end if;
 insert into public.settlement_payments(settlement_id,amount,depositor_name,deposited_at,
   match_method,confirmed_by,confirmed_at,idempotency_key,memo,audit_metadata,created_by,updated_by)
 values(s.id,v_remaining::int,'관리자 수동 확인',v_now,'manual',p_actor_id,v_now,v_key,
   'legacy confirm-payment compatibility wrapper',jsonb_build_object('source','legacy_confirm_payment'),
   p_actor_id,p_actor_id) returning * into pay;
 insert into public.settlement_events(settlement_id,company_id,merchant_id,event_type,payload,
   idempotency_key,actor_id)
 values(s.id,s.company_id,s.merchant_id,'merchant_payment_recorded',
   jsonb_build_object('payment_id',pay.id,'amount',pay.amount,'source','legacy_confirm_payment'),
   v_key,p_actor_id) returning * into e;
 select * into s from public.settlements where id=s.id;
 return jsonb_build_object('settlement',to_jsonb(s),'payment',to_jsonb(pay),
   'event',to_jsonb(e),'idempotent',false);
end $$;

revoke all on function public.company_confirm_and_request_tax_invoice(uuid,uuid,uuid) from public,anon,authenticated;
revoke all on function public.company_dispute_settlement(uuid,uuid,uuid,text,text) from public,anon,authenticated;
revoke all on function public.merchant_send_settlement(uuid,uuid,uuid) from public,anon,authenticated;
revoke all on function public.merchant_mark_settlement_paid(uuid,uuid,uuid,int,text,timestamptz,text,text) from public,anon,authenticated;
revoke all on function public.merchant_confirm_settlement_payment_legacy(uuid,uuid,uuid,uuid) from public,anon,authenticated;
grant execute on function public.company_confirm_and_request_tax_invoice(uuid,uuid,uuid) to service_role;
grant execute on function public.company_dispute_settlement(uuid,uuid,uuid,text,text) to service_role;
grant execute on function public.merchant_send_settlement(uuid,uuid,uuid) to service_role;
grant execute on function public.merchant_mark_settlement_paid(uuid,uuid,uuid,int,text,timestamptz,text,text) to service_role;
grant execute on function public.merchant_confirm_settlement_payment_legacy(uuid,uuid,uuid,uuid) to service_role;
