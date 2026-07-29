-- Complete the explicit settlement review, revision, issuance and payment workflow.
-- Browser roles never execute these functions directly; the API supplies an actor and
-- tenant which every SECURITY DEFINER entry point validates against app_users.

create or replace function public.merchant_begin_settlement_revision(
  p_actor_id uuid, p_merchant_id uuid, p_settlement_id uuid
) returns jsonb
language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare
  s public.settlements%rowtype;
  e public.settlement_events%rowtype;
  v_now timestamptz := pg_catalog.clock_timestamp();
begin
  if not exists (
    select 1 from public.app_users u
    where u.id=p_actor_id and u.merchant_id=p_merchant_id
      and u.role='merchant_admin' and u.status='active'
  ) then
    raise exception 'SETTLEMENT_FORBIDDEN' using errcode='P0001';
  end if;

  select * into s from public.settlements
   where id=p_settlement_id and merchant_id=p_merchant_id for update;
  if not found then
    raise exception 'SETTLEMENT_NOT_FOUND' using errcode='P0001';
  end if;
  if s.settlement_status='revising' then
    select * into e from public.settlement_events
     where settlement_id=s.id and event_type='merchant_revision_started'
     order by id desc limit 1;
    return jsonb_build_object('settlement',to_jsonb(s),'event',to_jsonb(e),'idempotent',true);
  end if;
  if s.settlement_status<>'disputed' or s.tax_invoice_status<>'not_requested' then
    raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001';
  end if;

  update public.settlements
     set settlement_status='revising', updated_at=v_now
   where id=s.id returning * into s;
  insert into public.settlement_events(
    settlement_id,company_id,merchant_id,event_type,payload,idempotency_key,actor_id
  ) values (
    s.id,s.company_id,s.merchant_id,'merchant_revision_started',
    jsonb_build_object('preserved_total_amount',s.total_amount),
    'revision-after-dispute-' || (select count(*)::text from public.settlement_events
      where settlement_id=s.id and event_type='company_disputed'),p_actor_id
  ) returning * into e;
  return jsonb_build_object('settlement',to_jsonb(s),'event',to_jsonb(e),'idempotent',false);
end $$;

revoke all on function public.merchant_begin_settlement_revision(uuid,uuid,uuid)
  from public, anon, authenticated, service_role;
grant execute on function public.merchant_begin_settlement_revision(uuid,uuid,uuid) to service_role;

-- Keep the browser and database gates identical. A draft/revision carrying any
-- invoice lifecycle state must not be exposed, and an already-issued/in-flight
-- document must never be pushed back into a dispute cycle.
create or replace function public.merchant_send_settlement(
  p_actor_id uuid,p_merchant_id uuid,p_settlement_id uuid
) returns jsonb
language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare
  s public.settlements%rowtype;
  e public.settlement_events%rowtype;
  v_cycle int;
  v_now timestamptz := pg_catalog.clock_timestamp();
begin
  if not exists (
    select 1 from public.app_users u
    where u.id=p_actor_id and u.merchant_id=p_merchant_id
      and u.role='merchant_admin' and u.status='active'
  ) then
    raise exception 'SETTLEMENT_FORBIDDEN' using errcode='P0001';
  end if;
  select * into s from public.settlements
   where id=p_settlement_id and merchant_id=p_merchant_id for update;
  if not found then
    raise exception 'SETTLEMENT_NOT_FOUND' using errcode='P0001';
  end if;
  if s.settlement_status='sent' and s.tax_invoice_status='not_requested' then
    return jsonb_build_object('settlement',to_jsonb(s),'idempotent',true);
  end if;
  if s.settlement_status not in ('draft','revising')
     or s.tax_invoice_status<>'not_requested' then
    raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001';
  end if;
  if s.due_date is null or s.supply_amount is null or s.vat_amount is null
     or s.total_amount is null or s.supply_amount<0 or s.vat_amount<0
     or s.supply_amount+s.vat_amount<>s.total_amount then
    raise exception 'SETTLEMENT_AMOUNTS_INVALID' using errcode='P0001';
  end if;
  select count(*)+1 into v_cycle from public.settlement_events
   where settlement_id=s.id and event_type='merchant_sent';
  update public.settlements
     set settlement_status='sent',sent_at=v_now,updated_at=v_now
   where id=s.id returning * into s;
  insert into public.settlement_events(
    settlement_id,company_id,merchant_id,event_type,payload,idempotency_key,actor_id
  ) values (
    s.id,s.company_id,s.merchant_id,'merchant_sent',
    jsonb_build_object('due_date',s.due_date,'total_amount',s.total_amount,'send_cycle',v_cycle),
    'send-cycle-'||v_cycle::text,p_actor_id
  ) returning * into e;
  return jsonb_build_object('settlement',to_jsonb(s),'event',to_jsonb(e),'idempotent',false);
end $$;
revoke all on function public.merchant_send_settlement(uuid,uuid,uuid)
  from public, anon, authenticated, service_role;
grant execute on function public.merchant_send_settlement(uuid,uuid,uuid) to service_role;

create or replace function public.company_dispute_settlement(
  p_actor_id uuid,p_company_id uuid,p_settlement_id uuid,p_reason text,p_idempotency_key text
) returns jsonb
language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare
  s public.settlements%rowtype;
  e public.settlement_events%rowtype;
  v_payload jsonb;
begin
  if not exists (
    select 1 from public.app_users u
    where u.id=p_actor_id and u.company_id=p_company_id
      and u.role='company_admin' and u.status='active'
  ) then
    raise exception 'SETTLEMENT_FORBIDDEN' using errcode='P0001';
  end if;
  if nullif(pg_catalog.btrim(p_reason),'') is null or char_length(p_reason)>1000
     or nullif(pg_catalog.btrim(p_idempotency_key),'') is null
     or char_length(p_idempotency_key)>128 then
    raise exception 'SETTLEMENT_INPUT_INVALID' using errcode='P0001';
  end if;
  select * into s from public.settlements
   where id=p_settlement_id and company_id=p_company_id for update;
  if not found then
    raise exception 'SETTLEMENT_NOT_FOUND' using errcode='P0001';
  end if;
  v_payload:=jsonb_build_object('reason',pg_catalog.btrim(p_reason));
  select * into e from public.settlement_events
   where settlement_id=s.id and event_type='company_disputed'
     and idempotency_key=p_idempotency_key;
  if found then
    if e.payload<>v_payload then
      raise exception 'IDEMPOTENCY_CONFLICT' using errcode='P0001';
    end if;
    return jsonb_build_object('settlement',to_jsonb(s),'event',to_jsonb(e),'idempotent',true);
  end if;
  if s.settlement_status<>'sent' or s.tax_invoice_status<>'not_requested' then
    raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001';
  end if;
  update public.settlements set settlement_status='disputed',updated_at=pg_catalog.clock_timestamp()
   where id=s.id returning * into s;
  insert into public.settlement_events(
    settlement_id,company_id,merchant_id,event_type,payload,idempotency_key,actor_id
  ) values (
    s.id,s.company_id,s.merchant_id,'company_disputed',v_payload,p_idempotency_key,p_actor_id
  ) returning * into e;
  return jsonb_build_object('settlement',to_jsonb(s),'event',to_jsonb(e),'idempotent',false);
end $$;
revoke all on function public.company_dispute_settlement(uuid,uuid,uuid,text,text)
  from public, anon, authenticated, service_role;
grant execute on function public.company_dispute_settlement(uuid,uuid,uuid,text,text) to service_role;

-- Company month totals obey the same visibility boundary as company list/detail.
-- Retire service execution of the old tenant-only signature and expose an actor-checked one.
revoke all on function public.company_settlement_month_summary(uuid,text)
  from public, anon, authenticated, service_role;
create or replace function public.company_settlement_month_summary(
  p_actor_id uuid, p_company_id uuid, p_period_ym text
) returns jsonb
language plpgsql stable security definer
set search_path = pg_catalog, public
as $$
begin
  if not exists (
    select 1 from public.app_users u
    where u.id=p_actor_id and u.company_id=p_company_id
      and u.role='company_admin' and u.status='active'
  ) then
    raise exception 'SETTLEMENT_FORBIDDEN' using errcode='P0001';
  end if;
  return (
    select jsonb_build_object(
      'settlement_count',count(*),
      'paid_count',count(*) filter(where s.payment_status in ('paid','overpaid') or s.status='paid'),
      'tx_count',coalesce(sum(s.tx_count),0),
      'total_amount',coalesce(sum(s.total_amount),0)
    ) from public.normal_settlements s
    where s.company_id=p_company_id and s.period_ym=p_period_ym
      and s.settlement_status in ('sent','confirmed','disputed','finalized','completed','cancelled')
  );
end $$;
revoke all on function public.company_settlement_month_summary(uuid,uuid,text)
  from public, anon, authenticated, service_role;
grant execute on function public.company_settlement_month_summary(uuid,uuid,text) to service_role;

-- A merchant may issue only after the company has atomically confirmed/requested.
-- Existing issued and in-flight calls remain safely idempotent/reconcilable.
create or replace function public.merchant_claim_tax_invoice_issue(
  p_actor_id uuid,p_merchant_id uuid,p_settlement_id uuid
) returns jsonb
language plpgsql security definer
set search_path=pg_catalog,public
as $$
declare
  s public.settlements%rowtype;
  inv public.tax_invoices%rowtype;
  tok uuid;
  v_now timestamptz:=pg_catalog.clock_timestamp();
begin
  if not exists(select 1 from public.app_users where id=p_actor_id and merchant_id=p_merchant_id and role='merchant_admin' and status='active') then
    raise exception 'SETTLEMENT_FORBIDDEN' using errcode='P0001';
  end if;
  select * into s from public.settlements where id=p_settlement_id and merchant_id=p_merchant_id for update;
  if not found then raise exception 'SETTLEMENT_NOT_FOUND' using errcode='P0001'; end if;
  select * into inv from public.tax_invoices where settlement_id=s.id and document_type='original';
  if inv.id is not null and row(inv.tax_type,inv.write_date,inv.supply_amount,inv.vat_amount,inv.total_amount)
       is distinct from row(s.settlement_tax_type,s.period_to,s.supply_amount,s.vat_amount,s.total_amount) then
    raise exception 'TAX_INVOICE_LEGAL_FIELDS_MISMATCH' using errcode='P0001';
  end if;
  if s.tax_invoice_status in ('issued','nts_sending','nts_accepted') then
    return jsonb_build_object('action','already_issued','settlement',to_jsonb(s),'tax_invoice',public.safe_tax_invoice_json(inv),'attempt_token',null);
  end if;
  if s.tax_invoice_status='issuing' then
    return jsonb_build_object('action','reconcile','settlement',to_jsonb(s),'tax_invoice',public.safe_tax_invoice_json(inv),'attempt_token',inv.issue_attempt_token,'lease_expires_at',inv.issue_lease_expires_at);
  end if;
  if s.settlement_status<>'confirmed' or s.tax_invoice_status not in ('requested','failed')
     or inv.id is null or inv.requested_at is null then
    raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001';
  end if;
  tok:=gen_random_uuid();
  update public.tax_invoices set issue_attempt_token=tok,issue_attempt_started_at=v_now,
    issue_lease_expires_at=v_now+interval '5 minutes',reconciliation_required_at=null,
    failure_code=null,failure_message=null,failed_at=null,updated_by=p_actor_id,updated_at=v_now
    where id=inv.id returning * into inv;
  update public.settlements set tax_invoice_status='issuing',updated_at=v_now
    where id=s.id returning * into s;
  insert into public.tax_invoice_events(tax_invoice_id,event_type,payload,actor_id,occurred_at)
  values(inv.id,'tax_invoice_issue_claimed',
    jsonb_build_object('attempt_token',tok,'lease_expires_at',inv.issue_lease_expires_at),p_actor_id,v_now);
  return jsonb_build_object('action','issue','settlement',to_jsonb(s),
    'tax_invoice',public.safe_tax_invoice_json(inv),'attempt_token',tok,
    'lease_expires_at',inv.issue_lease_expires_at);
end $$;
revoke all on function public.merchant_claim_tax_invoice_issue(uuid,uuid,uuid)
  from public, anon, authenticated, service_role;
grant execute on function public.merchant_claim_tax_invoice_issue(uuid,uuid,uuid) to service_role;

-- Confirmed deposits complete an issued, company-confirmed settlement. Removing or
-- unconfirming deposits rolls completed back to confirmed, except cancelled rows.
create or replace function public.recompute_settlement_payment_status(p_settlement_id uuid)
returns void
language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare
  s public.settlements%rowtype;
  v_confirmed_total bigint;
  v_has_unconfirmed boolean;
  v_latest_confirmed_at timestamptz;
  v_status text;
  v_now timestamptz := pg_catalog.clock_timestamp();
begin
  select * into s from public.settlements where id=p_settlement_id for no key update;
  if not found then return; end if;
  select coalesce(sum(amount),0),max(confirmed_at)
    into v_confirmed_total,v_latest_confirmed_at
    from public.settlement_payments
   where settlement_id=p_settlement_id and confirmed_at is not null;
  select exists(select 1 from public.settlement_payments
    where settlement_id=p_settlement_id and confirmed_at is null) into v_has_unconfirmed;
  v_status:=case
    when v_confirmed_total=0 and v_has_unconfirmed then 'matching'
    when v_confirmed_total=0 then 'unpaid'
    when v_confirmed_total<s.total_amount then 'partially_paid'
    when v_confirmed_total=s.total_amount then 'paid'
    else 'overpaid' end;

  update public.settlements set
    payment_status=v_status,
    settlement_status=case
      when s.settlement_status='cancelled' then 'cancelled'
      when v_status in ('paid','overpaid')
       and s.settlement_status in ('confirmed','completed')
       and s.tax_invoice_status in ('issued','nts_sending','nts_accepted') then 'completed'
      when v_status not in ('paid','overpaid') and s.settlement_status='completed' then 'confirmed'
      else s.settlement_status end,
    finalized_at=case
      when s.settlement_status='cancelled' then s.finalized_at
      when v_status in ('paid','overpaid')
       and s.settlement_status in ('confirmed','completed')
       and s.tax_invoice_status in ('issued','nts_sending','nts_accepted')
        then coalesce(s.finalized_at,v_latest_confirmed_at,v_now)
      when v_status not in ('paid','overpaid') and s.settlement_status='completed' then null
      else s.finalized_at end,
    status=case
      when v_status in ('paid','overpaid') then 'paid'
      when s.settlement_status in ('confirmed','finalized','completed') then 'confirmed'
      else 'draft' end,
    paid_at=case when v_status in ('paid','overpaid') then v_latest_confirmed_at else null end,
    updated_at=v_now
  where id=p_settlement_id;
end $$;
revoke all on function public.recompute_settlement_payment_status(uuid)
  from public, anon, authenticated, service_role;
grant execute on function public.recompute_settlement_payment_status(uuid) to service_role;

-- The write RPC also rejects payment registration before both required milestones.
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
  if s.tax_invoice_status not in ('issued','nts_sending','nts_accepted')
     or s.settlement_status not in ('confirmed','completed') then
    raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001';
  end if;
  insert into public.settlement_payments(settlement_id,amount,depositor_name,deposited_at,match_method,confirmed_by,confirmed_at,idempotency_key,memo,audit_metadata,created_by,updated_by)
   values(s.id,p_amount,btrim(p_depositor_name),p_deposited_at,'manual',p_actor_id,now(),p_idempotency_key,nullif(btrim(coalesce(p_memo,'')),''),jsonb_build_object('source','merchant_operator'),p_actor_id,p_actor_id) returning * into pay;
  v_payload:=jsonb_build_object('payment_id',pay.id,'amount',pay.amount,'deposited_at',pay.deposited_at);
  insert into public.settlement_events(settlement_id,company_id,merchant_id,event_type,payload,idempotency_key,actor_id)
   values(s.id,s.company_id,s.merchant_id,'merchant_payment_recorded',v_payload,p_idempotency_key,p_actor_id) returning * into e;
  select * into s from public.settlements where id=s.id;
  return jsonb_build_object('settlement',to_jsonb(s),'payment',to_jsonb(pay),'event',to_jsonb(e),'idempotent',false);
end $$;
revoke all on function public.merchant_mark_settlement_paid(uuid,uuid,uuid,int,text,timestamptz,text,text)
  from public, anon, authenticated, service_role;
grant execute on function public.merchant_mark_settlement_paid(uuid,uuid,uuid,int,text,timestamptz,text,text) to service_role;
