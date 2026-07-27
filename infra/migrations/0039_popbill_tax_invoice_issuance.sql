-- Atomic, fail-closed Popbill tax-invoice issuance and reconciliation.
-- Provider URLs and raw provider responses are intentionally not persisted.

create or replace function public.popbill_management_key(p_id uuid) returns text
language sql immutable strict parallel safe
set search_path = pg_catalog
as $$
  select 'GE' || rtrim(translate(encode(uuid_send(p_id), 'base64'), '+/', '-_'), '=')
$$;
revoke all on function public.popbill_management_key(uuid) from public, anon, authenticated;
grant execute on function public.popbill_management_key(uuid) to service_role;

-- Active original provider identities are reviewed after the legal-source review below.

-- Provider identity repair and format validation occur after legal-source review.

alter table public.settlements
  add column if not exists settlement_tax_type text;
alter table public.settlements drop constraint if exists settlements_settlement_tax_type_check;
alter table public.settlements add constraint settlements_settlement_tax_type_check
  check (settlement_tax_type is null or settlement_tax_type in ('taxable','tax_free'));

-- Historical classification is conservative: every eligible transaction in the frozen
-- period must be classified and all classifications must agree.
with classified as (
  select s.id, min(t.settlement_tax_type) as tax_type
  from public.settlements s
  join public.meal_transactions t
    on t.merchant_id=s.merchant_id and t.company_id=s.company_id
   and t.pay_type in ('ledger','subsidized') and t.kind in ('spend','refund','cancel')
   and s.period_from is not null and s.period_to is not null
   and t.created_at >= (s.period_from::timestamp at time zone 'Asia/Seoul')
   and t.created_at < ((s.period_to+1)::timestamp at time zone 'Asia/Seoul')
  group by s.id
  having count(*) = count(*) filter (where t.settlement_tax_type in ('taxable','tax_free'))
     and count(distinct t.settlement_tax_type) = 1
)
update public.settlements s set settlement_tax_type=c.tax_type
from classified c where c.id=s.id and s.settlement_tax_type is null;

-- Every existing original needs a complete and internally coherent source
-- settlement before either active validation or inactive repair.
do $$
begin
  if exists (
    select 1 from public.tax_invoices i
    join public.settlements s on s.id=i.settlement_id
    where i.document_type='original' and (
      s.settlement_tax_type is null or s.settlement_tax_type not in ('taxable','tax_free')
      or s.period_to is null or s.supply_amount is null or s.vat_amount is null or s.total_amount is null
      or s.supply_amount<0 or s.vat_amount<0 or s.total_amount<0
      or s.supply_amount+s.vat_amount<>s.total_amount
      or (s.settlement_tax_type='tax_free' and (s.vat_amount<>0 or s.supply_amount<>s.total_amount))
    )
  ) then
    raise exception 'LEGACY_TAX_INVOICE_SNAPSHOT_REVIEW_REQUIRED' using errcode='P0001';
  end if;
end $$;

-- A provider-active original identity must be reviewed by a human. Never rewrite it.
do $$
begin
  if exists (
    select 1 from public.tax_invoices
    where document_type='original'
      and invoicer_mgt_key is distinct from public.popbill_management_key(settlement_id)
      and (issued_at is not null or nts_sent_at is not null or nts_accepted_at is not null
        or cancelled_at is not null
        or coalesce(popbill_status, '') in ('issued','nts_sending','nts_accepted','cancelled'))
  ) then
    raise exception 'LEGACY_POPBILL_KEY_REVIEW_REQUIRED' using errcode='P0001';
  end if;
end $$;

-- Originals always derive identity from settlement_id. Inactive adjustment rows
-- retain their id-based fallback.
update public.tax_invoices
set invoicer_mgt_key = public.popbill_management_key(
      case when document_type='original' then settlement_id else id end),
    updated_at = clock_timestamp()
where (document_type='original'
       and invoicer_mgt_key is distinct from public.popbill_management_key(settlement_id))
   or (document_type<>'original' and invoicer_mgt_key !~ '^[A-Za-z0-9_-]{1,24}$');

alter table public.tax_invoices drop constraint if exists tax_invoices_invoicer_mgt_key_format_check;
alter table public.tax_invoices add constraint tax_invoices_invoicer_mgt_key_format_check
  check (invoicer_mgt_key ~ '^[A-Za-z0-9_-]{1,24}$') not valid;
alter table public.tax_invoices validate constraint tax_invoices_invoicer_mgt_key_format_check;

-- Legal/accounting facts on active provider documents are evidence, not repairable data.
do $$
begin
  if exists (
    select 1 from public.tax_invoices i
    join public.settlements s on s.id=i.settlement_id
    where i.document_type='original'
      and (i.issued_at is not null or i.nts_sent_at is not null or i.nts_accepted_at is not null
        or i.cancelled_at is not null
        or coalesce(i.popbill_status,'') in ('issued','nts_sending','nts_accepted','cancelled'))
      and row(i.tax_type,i.write_date,i.supply_amount,i.vat_amount,i.total_amount)
          is distinct from row(s.settlement_tax_type,s.period_to,s.supply_amount,s.vat_amount,s.total_amount)
  ) then
    raise exception 'LEGACY_TAX_INVOICE_SNAPSHOT_REVIEW_REQUIRED' using errcode='P0001';
  end if;
end $$;

-- Inactive originals have never become provider facts. Repair only their legal values;
-- party snapshots remain the original frozen evidence.
update public.tax_invoices i
set tax_type=s.settlement_tax_type, write_date=s.period_to,
    supply_amount=s.supply_amount, vat_amount=s.vat_amount, total_amount=s.total_amount,
    updated_at=clock_timestamp()
from public.settlements s
where i.settlement_id=s.id and i.document_type='original'
  and not (i.issued_at is not null or i.nts_sent_at is not null or i.nts_accepted_at is not null
    or i.cancelled_at is not null
    or coalesce(i.popbill_status,'') in ('issued','nts_sending','nts_accepted','cancelled'))
  and s.settlement_tax_type in ('taxable','tax_free') and s.period_to is not null
  and s.supply_amount is not null and s.vat_amount is not null and s.total_amount is not null
  and row(i.tax_type,i.write_date,i.supply_amount,i.vat_amount,i.total_amount)
      is distinct from row(s.settlement_tax_type,s.period_to,s.supply_amount,s.vat_amount,s.total_amount);

-- Destroy historical raw provider material before any RPC can expose it.
update public.tax_invoices
set provider_response=null, popbill_status_message=null
where provider_response is not null or popbill_status_message is not null;

alter table public.tax_invoices
  add column if not exists issue_attempt_token uuid,
  add column if not exists issue_attempt_started_at timestamptz,
  add column if not exists issue_lease_expires_at timestamptz,
  add column if not exists reconciliation_required_at timestamptz,
  add column if not exists status_refreshed_at timestamptz;

create or replace function public.safe_tax_invoice_json(p_invoice public.tax_invoices)
returns jsonb language sql immutable strict parallel safe set search_path=pg_catalog
as $$ select to_jsonb(p_invoice) - array['provider_response','popbill_status_message']::text[] $$;
revoke all on function public.safe_tax_invoice_json(public.tax_invoices) from public,anon,authenticated;

-- Frozen legal/accounting identity cannot be edited by the API after insert. A migration
-- bypass is intentionally available only to the table-owning login, never service_role.
create or replace function public.prevent_tax_invoice_frozen_update() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
declare v_owner name;
begin
  select tableowner into v_owner from pg_catalog.pg_tables
    where schemaname='public' and tablename='tax_invoices';
  if session_user=v_owner and current_setting('greeneatgo.tax_invoice_migration_bypass',true)='on' then
    return new;
  end if;
  if row(new.settlement_id,new.company_id,new.merchant_id,new.document_type,new.invoicer_mgt_key,
         new.tax_type,new.write_date,new.supply_amount,new.vat_amount,new.total_amount,
         new.supplier_snapshot,new.recipient_snapshot)
     is distinct from
     row(old.settlement_id,old.company_id,old.merchant_id,old.document_type,old.invoicer_mgt_key,
         old.tax_type,old.write_date,old.supply_amount,old.vat_amount,old.total_amount,
         old.supplier_snapshot,old.recipient_snapshot) then
    raise exception 'TAX_INVOICE_FROZEN_FIELDS_IMMUTABLE' using errcode='55000';
  end if;
  return new;
end $$;
revoke all on function public.prevent_tax_invoice_frozen_update() from public,anon,authenticated;
drop trigger if exists trg_tax_invoice_frozen_update on public.tax_invoices;
create trigger trg_tax_invoice_frozen_update before update on public.tax_invoices
for each row execute function public.prevent_tax_invoice_frozen_update();

create or replace function public.create_merchant_settlement(
  p_merchant_id uuid, p_company_id uuid, p_period_from date, p_period_to date
) returns jsonb
language plpgsql security definer set search_path=pg_catalog,public as $$
declare
  v_row public.settlements%rowtype; v_period_ym text; v_count int;
  v_classified_count int; v_tax_type_count int; v_tax_type text;
  v_supply bigint; v_vat bigint; v_total bigint;
begin
  if p_period_from is null or p_period_to is null or p_period_from>p_period_to
     or date_trunc('month',p_period_from::timestamp)<>date_trunc('month',p_period_to::timestamp) then
    raise exception 'INVALID_DATE_RANGE' using errcode='P0001';
  end if;
  if not exists(select 1 from public.merchants where id=p_merchant_id and status='active')
     or not exists(select 1 from public.companies where id=p_company_id and status='active')
     or not exists(select 1 from public.merchant_companies where merchant_id=p_merchant_id and company_id=p_company_id and status='active') then
    raise exception 'SETTLEMENT_FORBIDDEN' using errcode='P0001';
  end if;
  v_period_ym:=to_char(p_period_from,'YYYY-MM');
  perform pg_advisory_xact_lock(pg_catalog.hashtext(p_merchant_id::text),pg_catalog.hashtext(p_company_id::text||':'||v_period_ym));
  select count(*),
    count(*) filter(where t.settlement_tax_type in ('taxable','tax_free')
      and t.settlement_supply_amount is not null and t.settlement_vat_amount is not null and t.settlement_total_amount is not null
      and t.settlement_supply_amount+t.settlement_vat_amount=t.settlement_total_amount
      and ((t.settlement_tax_type='tax_free' and t.settlement_vat_amount=0 and t.settlement_supply_amount=t.settlement_total_amount)
        or (t.settlement_tax_type='taxable' and t.settlement_supply_amount=round(t.settlement_total_amount::numeric/1.1)::int
          and t.settlement_vat_amount=t.settlement_total_amount-t.settlement_supply_amount))),
    count(distinct t.settlement_tax_type) filter(where t.settlement_tax_type in ('taxable','tax_free')),
    min(t.settlement_tax_type) filter(where t.settlement_tax_type in ('taxable','tax_free')),
    coalesce(sum(case when t.kind='spend' then t.settlement_supply_amount else -t.settlement_supply_amount end),0),
    coalesce(sum(case when t.kind='spend' then t.settlement_vat_amount else -t.settlement_vat_amount end),0),
    coalesce(sum(case when t.kind='spend' then t.settlement_total_amount else -t.settlement_total_amount end),0)
  into v_count,v_classified_count,v_tax_type_count,v_tax_type,v_supply,v_vat,v_total
  from public.meal_transactions t where t.merchant_id=p_merchant_id and t.company_id=p_company_id
    and t.pay_type in ('ledger','subsidized') and t.kind in ('spend','refund','cancel')
    and t.created_at >= (p_period_from::timestamp at time zone 'Asia/Seoul')
    and t.created_at < ((p_period_to+1)::timestamp at time zone 'Asia/Seoul');
  if v_count<>v_classified_count or v_count=0 then raise exception 'TAX_TYPE_UNCLASSIFIED' using errcode='P0001'; end if;
  if v_tax_type_count<>1 then raise exception 'MIXED_TAX_TYPES_NOT_SUPPORTED' using errcode='P0001'; end if;
  if v_supply<0 or v_vat<0 or v_total<0 or v_supply+v_vat<>v_total
     or v_supply>2147483647 or v_vat>2147483647 or v_total>2147483647 then
    raise exception 'SETTLEMENT_AMOUNTS_INVALID' using errcode='P0001';
  end if;
  select * into v_row from public.settlements where merchant_id=p_merchant_id and company_id=p_company_id and period_ym=v_period_ym for update;
  if found then
    if v_row.settlement_status not in ('draft','calculating','revising') then raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001'; end if;
    update public.settlements set period_from=p_period_from,period_to=p_period_to,tx_count=v_count,total_amount=v_total::int,
      supply_amount=v_supply::int,vat_amount=v_vat::int,settlement_tax_type=v_tax_type,settlement_status='draft',
      tax_invoice_status='not_requested',payment_status='unpaid',due_date=p_period_to+30,status='draft',updated_at=clock_timestamp()
      where id=v_row.id returning * into v_row;
  else
    insert into public.settlements(company_id,merchant_id,period_ym,period_from,period_to,tx_count,total_amount,supply_amount,vat_amount,
      settlement_tax_type,status,settlement_status,tax_invoice_status,payment_status,due_date)
    values(p_company_id,p_merchant_id,v_period_ym,p_period_from,p_period_to,v_count,v_total::int,v_supply::int,v_vat::int,
      v_tax_type,'draft','draft','not_requested','unpaid',p_period_to+30) returning * into v_row;
  end if;
  return to_jsonb(v_row);
end $$;
revoke all on function public.create_merchant_settlement(uuid,uuid,date,date) from public,anon,authenticated;
grant execute on function public.create_merchant_settlement(uuid,uuid,date,date) to service_role;

create or replace function public.create_original_tax_invoice_snapshot(
  p_settlement_id uuid,p_actor_id uuid,p_company_requested boolean
) returns public.tax_invoices
language plpgsql security definer set search_path=pg_catalog,public as $$
declare s public.settlements%rowtype; c public.companies%rowtype; m public.merchants%rowtype; inv public.tax_invoices%rowtype; v_now timestamptz:=clock_timestamp();
begin
  select * into s from public.settlements where id=p_settlement_id;
  if not found then raise exception 'SETTLEMENT_NOT_FOUND' using errcode='P0001'; end if;
  select * into inv from public.tax_invoices where settlement_id=s.id and document_type='original';
  if found then return inv; end if;
  if s.settlement_tax_type not in ('taxable','tax_free') then raise exception 'TAX_TYPE_UNCLASSIFIED' using errcode='P0001'; end if;
  select * into c from public.companies where id=s.company_id;
  select * into m from public.merchants where id=s.merchant_id;
  if nullif(btrim(c.biz_reg_no),'') is null or nullif(btrim(c.name),'') is null or nullif(btrim(c.representative_name),'') is null
    or nullif(btrim(c.address),'') is null or nullif(btrim(c.business_type),'') is null or nullif(btrim(c.business_item),'') is null
    or nullif(btrim(c.tax_invoice_email),'') is null or nullif(btrim(c.contact_name),'') is null or nullif(btrim(c.contact_phone),'') is null
    then raise exception 'BUSINESS_PROFILE_INCOMPLETE' using errcode='P0001'; end if;
  if nullif(btrim(m.biz_reg_no),'') is null or nullif(btrim(m.name),'') is null or nullif(btrim(m.representative_name),'') is null
    or nullif(btrim(m.address),'') is null or nullif(btrim(m.business_type),'') is null or nullif(btrim(m.business_item),'') is null
    or nullif(btrim(m.tax_invoice_email),'') is null or nullif(btrim(m.owner_phone),'') is null
    then raise exception 'SUPPLIER_PROFILE_INCOMPLETE' using errcode='P0001'; end if;
  if s.period_to is null or s.supply_amount is null or s.vat_amount is null or s.total_amount is null
    or s.supply_amount<0 or s.vat_amount<0 or s.supply_amount+s.vat_amount<>s.total_amount
    or (s.settlement_tax_type='tax_free' and s.vat_amount<>0) then
    raise exception 'SETTLEMENT_AMOUNTS_INVALID' using errcode='P0001'; end if;
  insert into public.tax_invoices(settlement_id,company_id,merchant_id,document_type,invoicer_mgt_key,tax_type,write_date,
    supply_amount,vat_amount,total_amount,supplier_snapshot,recipient_snapshot,requested_at,issue_requested_by,issue_requested_at,created_by,updated_by)
  values(s.id,s.company_id,s.merchant_id,'original',public.popbill_management_key(s.id),s.settlement_tax_type,s.period_to,
    s.supply_amount,s.vat_amount,s.total_amount,
    jsonb_build_object('registration_number',m.biz_reg_no,'name',m.name,'representative',m.representative_name,'address',m.address,
      'business_type',m.business_type,'business_item',m.business_item,'tax_email',m.tax_invoice_email,'contact_phone',m.owner_phone),
    jsonb_build_object('registration_number',c.biz_reg_no,'name',c.name,'representative',c.representative_name,'address',c.address,
      'business_type',c.business_type,'business_item',c.business_item,'tax_email',c.tax_invoice_email,'contact_name',c.contact_name,'contact_phone',c.contact_phone),
    case when p_company_requested then v_now end,case when p_company_requested then p_actor_id end,
    case when p_company_requested then v_now end,p_actor_id,p_actor_id) returning * into inv;
  return inv;
end $$;
revoke all on function public.create_original_tax_invoice_snapshot(uuid,uuid,boolean) from public,anon,authenticated;

create or replace function public.company_confirm_and_request_tax_invoice(p_actor_id uuid,p_company_id uuid,p_settlement_id uuid)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare s public.settlements%rowtype; inv public.tax_invoices%rowtype; v_now timestamptz:=clock_timestamp();
begin
 if not exists(select 1 from public.app_users where id=p_actor_id and company_id=p_company_id and role='company_admin' and status='active') then raise exception 'SETTLEMENT_FORBIDDEN' using errcode='P0001'; end if;
 select * into s from public.settlements where id=p_settlement_id and company_id=p_company_id for update;
 if not found then raise exception 'SETTLEMENT_NOT_FOUND' using errcode='P0001'; end if;
 select * into inv from public.tax_invoices where settlement_id=s.id and document_type='original';
 if s.settlement_status='confirmed' and s.tax_invoice_status in ('requested','issuing','issued','nts_sending','nts_accepted') and found then
   return jsonb_build_object('settlement',to_jsonb(s),'tax_invoice',public.safe_tax_invoice_json(inv),'idempotent',true); end if;
 if s.settlement_status<>'sent' or s.tax_invoice_status<>'not_requested' then raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001'; end if;
 if found then
   update public.tax_invoices set requested_at=v_now,issue_requested_by=p_actor_id,issue_requested_at=v_now,updated_by=p_actor_id,updated_at=v_now where id=inv.id returning * into inv;
 else inv:=public.create_original_tax_invoice_snapshot(s.id,p_actor_id,true); end if;
 update public.settlements set settlement_status='confirmed',tax_invoice_status='requested',confirmed_at=coalesce(confirmed_at,v_now),updated_at=v_now where id=s.id returning * into s;
 insert into public.settlement_events(settlement_id,company_id,merchant_id,event_type,payload,idempotency_key,actor_id)
 values(s.id,s.company_id,s.merchant_id,'company_confirmed_and_tax_invoice_requested',jsonb_build_object('tax_invoice_id',inv.id,'supply_amount',s.supply_amount,'vat_amount',s.vat_amount,'total_amount',s.total_amount),'confirm-and-request-tax-invoice',p_actor_id);
 insert into public.tax_invoice_events(tax_invoice_id,event_type,payload,actor_id,occurred_at)
 values(inv.id,'tax_invoice_issue_requested',jsonb_build_object('source','company_confirmation'),p_actor_id,v_now);
 return jsonb_build_object('settlement',to_jsonb(s),'tax_invoice',public.safe_tax_invoice_json(inv),'idempotent',false);
end $$;

create or replace function public.merchant_claim_tax_invoice_issue(p_actor_id uuid,p_merchant_id uuid,p_settlement_id uuid)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare s public.settlements%rowtype; inv public.tax_invoices%rowtype; tok uuid; v_now timestamptz:=clock_timestamp(); v_direct boolean;
begin
 if not exists(select 1 from public.app_users where id=p_actor_id and merchant_id=p_merchant_id and role='merchant_admin' and status='active') then raise exception 'SETTLEMENT_FORBIDDEN' using errcode='P0001'; end if;
 select * into s from public.settlements where id=p_settlement_id and merchant_id=p_merchant_id for update;
 if not found then raise exception 'SETTLEMENT_NOT_FOUND' using errcode='P0001'; end if;
 select * into inv from public.tax_invoices where settlement_id=s.id and document_type='original';
 if inv.id is not null and row(inv.tax_type,inv.write_date,inv.supply_amount,inv.vat_amount,inv.total_amount)
      is distinct from row(s.settlement_tax_type,s.period_to,s.supply_amount,s.vat_amount,s.total_amount) then
   raise exception 'TAX_INVOICE_LEGAL_FIELDS_MISMATCH' using errcode='P0001';
 end if;
 if s.tax_invoice_status in ('issued','nts_sending','nts_accepted') then
   return jsonb_build_object('action','already_issued','settlement',to_jsonb(s),'tax_invoice',public.safe_tax_invoice_json(inv),'attempt_token',null); end if;
 if s.tax_invoice_status='issuing' then
   return jsonb_build_object('action','reconcile','settlement',to_jsonb(s),'tax_invoice',public.safe_tax_invoice_json(inv),'attempt_token',inv.issue_attempt_token,'lease_expires_at',inv.issue_lease_expires_at); end if;
 if not ((s.settlement_status='sent' and s.tax_invoice_status='not_requested')
      or (s.settlement_status='confirmed' and s.tax_invoice_status='requested')
      or (s.settlement_status='sent' and s.tax_invoice_status='failed' and inv.requested_at is null)
      or (s.settlement_status='confirmed' and s.tax_invoice_status='failed' and inv.requested_at is not null)) then
   raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001';
 end if;
 v_direct:=s.settlement_status='sent';
 if inv.id is null then inv:=public.create_original_tax_invoice_snapshot(s.id,p_actor_id,false); end if;
 tok:=gen_random_uuid();
 update public.tax_invoices set issue_attempt_token=tok,issue_attempt_started_at=v_now,issue_lease_expires_at=v_now+interval '5 minutes',reconciliation_required_at=null,
   failure_code=null,failure_message=null,failed_at=null,updated_by=p_actor_id,updated_at=v_now where id=inv.id returning * into inv;
 update public.settlements set tax_invoice_status='issuing',updated_at=v_now where id=s.id returning * into s;
 insert into public.tax_invoice_events(tax_invoice_id,event_type,payload,actor_id,occurred_at)
 values(inv.id,case when v_direct then 'merchant_direct_issue_prepared' else 'tax_invoice_issue_claimed' end,
   jsonb_build_object('attempt_token',tok,'lease_expires_at',inv.issue_lease_expires_at),p_actor_id,v_now);
 return jsonb_build_object('action','issue','settlement',to_jsonb(s),'tax_invoice',public.safe_tax_invoice_json(inv),'attempt_token',tok,'lease_expires_at',inv.issue_lease_expires_at);
end $$;

create or replace function public.merchant_finalize_tax_invoice_issue(
 p_actor_id uuid,p_merchant_id uuid,p_settlement_id uuid,p_attempt_token uuid,p_outcome text,p_failure_code text default null,p_failure_message text default null)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare s public.settlements%rowtype; inv public.tax_invoices%rowtype; v_now timestamptz:=clock_timestamp();
begin
 if not exists(select 1 from public.app_users where id=p_actor_id and merchant_id=p_merchant_id and role='merchant_admin' and status='active') then raise exception 'SETTLEMENT_FORBIDDEN' using errcode='P0001'; end if;
 select * into s from public.settlements where id=p_settlement_id and merchant_id=p_merchant_id for update;
 if not found then raise exception 'SETTLEMENT_NOT_FOUND' using errcode='P0001'; end if;
 select * into inv from public.tax_invoices where settlement_id=s.id and document_type='original' for update;
 if not found then raise exception 'POPBILL_DOCUMENT_NOT_FOUND' using errcode='P0001'; end if;
 -- A provider refresh may win the race. Only success may then complete idempotently,
 -- and only while the persisted provider fact proves issuance.
 if s.tax_invoice_status in ('issued','nts_sending','nts_accepted') and inv.popbill_status='issued' then
   if p_outcome='success' then return jsonb_build_object('settlement',to_jsonb(s),'tax_invoice',public.safe_tax_invoice_json(inv),'idempotent',true); end if;
   raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001';
 end if;
 if s.tax_invoice_status<>'issuing' then raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001'; end if;
 if inv.issue_attempt_token is null or inv.issue_attempt_token is distinct from p_attempt_token then raise exception 'ISSUE_ATTEMPT_TOKEN_MISMATCH' using errcode='P0001'; end if;
 if p_outcome='success' then
   update public.tax_invoices set popbill_status='issued',issued_by=p_actor_id,
     failure_code=null,failure_message=null,failed_at=null,reconciliation_required_at=null,issue_attempt_token=null,issue_lease_expires_at=null,updated_by=p_actor_id,updated_at=v_now where id=inv.id returning * into inv;
   update public.settlements set tax_invoice_status='issued',updated_at=v_now where id=s.id returning * into s;
   insert into public.tax_invoice_events(tax_invoice_id,event_type,payload,actor_id,occurred_at) values(inv.id,'tax_invoice_issue_succeeded',jsonb_build_object('attempt_token',p_attempt_token),p_actor_id,v_now);
 elsif p_outcome='reconciliation_required' then
   update public.tax_invoices set reconciliation_required_at=coalesce(reconciliation_required_at,v_now),updated_by=p_actor_id,updated_at=v_now where id=inv.id returning * into inv;
   insert into public.tax_invoice_events(tax_invoice_id,event_type,payload,actor_id,occurred_at) values(inv.id,'tax_invoice_reconciliation_required',jsonb_build_object('attempt_token',p_attempt_token),p_actor_id,v_now);
 elsif p_outcome='rejected' then
   update public.tax_invoices set popbill_status='failed',failure_code=left(coalesce(p_failure_code,'POPBILL_ISSUE_REJECTED'),80),
     failure_message=left(coalesce(p_failure_message,'Popbill rejected the request'),300),failed_at=v_now,reconciliation_required_at=null,
     issue_attempt_token=null,issue_lease_expires_at=null,updated_by=p_actor_id,updated_at=v_now where id=inv.id returning * into inv;
   update public.settlements set tax_invoice_status='failed',updated_at=v_now where id=s.id returning * into s;
   insert into public.tax_invoice_events(tax_invoice_id,event_type,payload,actor_id,occurred_at) values(inv.id,'tax_invoice_issue_rejected',jsonb_build_object('attempt_token',p_attempt_token,'failure_code',inv.failure_code),p_actor_id,v_now);
 else raise exception 'SETTLEMENT_INPUT_INVALID' using errcode='P0001'; end if;
 return jsonb_build_object('settlement',to_jsonb(s),'tax_invoice',public.safe_tax_invoice_json(inv),'idempotent',false);
end $$;

drop function if exists public.merchant_apply_tax_invoice_status(uuid,uuid,uuid,int,text,timestamptz,timestamptz,timestamptz);
create or replace function public.merchant_apply_tax_invoice_status(
 p_actor_id uuid,p_merchant_id uuid,p_settlement_id uuid,p_state_code int,p_nts_result text,p_nts_confirm_num text default null,
 p_issued_at timestamptz default null,p_nts_sent_at timestamptz default null,p_nts_result_at timestamptz default null)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare s public.settlements%rowtype; inv public.tax_invoices%rowtype; v_set text; v_nts text; v_now timestamptz:=clock_timestamp(); v_attempt uuid; v_old_set text; v_old_nts text;
  v_effective_issued timestamptz; v_effective_sent timestamptz; v_effective_result timestamptz;
begin
 if not exists(select 1 from public.app_users where id=p_actor_id and merchant_id=p_merchant_id and role='merchant_admin' and status='active') then raise exception 'SETTLEMENT_FORBIDDEN' using errcode='P0001'; end if;
 select * into s from public.settlements where id=p_settlement_id and merchant_id=p_merchant_id for update;
 if not found then raise exception 'SETTLEMENT_NOT_FOUND' using errcode='P0001'; end if;
 if s.tax_invoice_status not in ('issuing','issued','nts_sending','nts_accepted') then raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001'; end if;
 select * into inv from public.tax_invoices where settlement_id=s.id and document_type='original' for update;
 if not found then raise exception 'POPBILL_DOCUMENT_NOT_FOUND' using errcode='P0001'; end if;
 if p_state_code is null or p_state_code not between 300 and 305 then raise exception 'POPBILL_INVALID_PROVIDER_STATE' using errcode='P0001'; end if;
 v_effective_issued:=coalesce(inv.issued_at,p_issued_at);
 v_effective_sent:=coalesce(inv.nts_sent_at,p_nts_sent_at);
 v_effective_result:=coalesce(inv.nts_accepted_at,p_nts_result_at);
 if v_effective_issued is null then raise exception 'POPBILL_INVALID_PROVIDER_TIMESTAMP' using errcode='P0001'; end if;
 if (v_effective_sent is not null and v_effective_issued>v_effective_sent)
    or (v_effective_result is not null and v_effective_issued>v_effective_result)
    or (v_effective_result is not null and v_effective_sent is not null and v_effective_sent>v_effective_result)
    or (p_state_code=303 and inv.nts_status is distinct from 'accepted' and v_effective_sent is null)
    or (p_state_code=304 and p_nts_result='SUC001' and inv.nts_status is distinct from 'accepted'
        and (v_effective_sent is null or v_effective_result is null)) then
   raise exception 'POPBILL_INVALID_PROVIDER_TIMESTAMP' using errcode='P0001';
 end if;
 v_old_set:=s.tax_invoice_status; v_old_nts:=inv.nts_status; v_attempt:=inv.issue_attempt_token;
 if p_state_code=303 then v_set:='nts_sending';v_nts:='sending';
 elsif p_state_code=304 and p_nts_result='SUC001' then v_set:='nts_accepted';v_nts:='accepted';
 elsif p_state_code=305 then v_set:='issued';v_nts:='failed';
 else v_set:='issued';v_nts:=inv.nts_status; end if;
 if s.tax_invoice_status='nts_accepted' then v_set:='nts_accepted';v_nts:='accepted';
 elsif s.tax_invoice_status='nts_sending' and v_set='issued' and p_state_code<>305 then v_set:='nts_sending';v_nts:='sending';
 elsif inv.nts_status='failed' and not (p_state_code=304 and p_nts_result='SUC001') then v_set:='issued';v_nts:='failed'; end if;
 update public.tax_invoices set popbill_status='issued',popbill_status_code=p_state_code,nts_status=v_nts,
   nts_status_code=case when inv.nts_status='accepted' then inv.nts_status_code else coalesce(left(p_nts_result,80),inv.nts_status_code) end,
   nts_confirm_num=case when inv.nts_status='accepted' then inv.nts_confirm_num else coalesce(left(p_nts_confirm_num,100),inv.nts_confirm_num) end,
   issued_at=coalesce(issued_at,p_issued_at),
   nts_sent_at=case when v_set in ('nts_sending','nts_accepted') then coalesce(nts_sent_at,p_nts_sent_at) else nts_sent_at end,
   nts_accepted_at=case when v_set='nts_accepted' then coalesce(nts_accepted_at,p_nts_result_at) else nts_accepted_at end,
   reconciliation_required_at=null,status_refreshed_at=v_now,issue_attempt_token=null,issue_lease_expires_at=null,updated_by=p_actor_id,updated_at=v_now
   where id=inv.id returning * into inv;
 update public.settlements set tax_invoice_status=v_set,updated_at=v_now where id=s.id returning * into s;
 insert into public.tax_invoice_events(tax_invoice_id,event_type,payload,actor_id,occurred_at)
 values(inv.id,'tax_invoice_status_refreshed',jsonb_strip_nulls(jsonb_build_object('attempt_token',v_attempt,'provider_state_code',p_state_code,
   'from_status',v_old_set,'to_status',v_set,'from_nts_status',v_old_nts,'to_nts_status',v_nts,'nts_result_code',left(p_nts_result,80))),p_actor_id,v_now);
 return jsonb_build_object('settlement',to_jsonb(s),'tax_invoice',public.safe_tax_invoice_json(inv));
end $$;

-- Reset is allowed only after an exact provider check returned false and the lease expired.
-- It never issues; a later explicit user action may claim a fresh attempt.
create or replace function public.merchant_reset_stale_tax_invoice_issue(
 p_actor_id uuid,p_merchant_id uuid,p_settlement_id uuid,p_attempt_token uuid,p_management_key_in_use boolean)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare s public.settlements%rowtype; inv public.tax_invoices%rowtype; v_now timestamptz:=clock_timestamp();
begin
 if not exists(select 1 from public.app_users where id=p_actor_id and merchant_id=p_merchant_id and role='merchant_admin' and status='active') then raise exception 'SETTLEMENT_FORBIDDEN' using errcode='P0001'; end if;
 select * into s from public.settlements where id=p_settlement_id and merchant_id=p_merchant_id for update;
 if not found then raise exception 'SETTLEMENT_NOT_FOUND' using errcode='P0001'; end if;
 select * into inv from public.tax_invoices where settlement_id=s.id and document_type='original' for update;
 if not found then raise exception 'POPBILL_DOCUMENT_NOT_FOUND' using errcode='P0001'; end if;
 if s.tax_invoice_status<>'issuing' or inv.issue_attempt_token is distinct from p_attempt_token then raise exception 'ISSUE_ATTEMPT_TOKEN_MISMATCH' using errcode='P0001'; end if;
 if p_management_key_in_use is distinct from false then raise exception 'POPBILL_RECONCILIATION_REQUIRED' using errcode='P0001'; end if;
 if inv.issue_lease_expires_at is null or inv.issue_lease_expires_at>v_now then raise exception 'POPBILL_ISSUE_LEASE_ACTIVE' using errcode='P0001'; end if;
 update public.tax_invoices set popbill_status='failed',failure_code='POPBILL_MANAGEMENT_KEY_UNUSED',failure_message='Provider management key is unused',failed_at=v_now,
   issue_attempt_token=null,issue_lease_expires_at=null,reconciliation_required_at=null,updated_by=p_actor_id,updated_at=v_now where id=inv.id returning * into inv;
 update public.settlements set tax_invoice_status='failed',updated_at=v_now where id=s.id returning * into s;
 insert into public.tax_invoice_events(tax_invoice_id,event_type,payload,actor_id,occurred_at)
 values(inv.id,'tax_invoice_stale_issue_reset',jsonb_build_object('attempt_token',p_attempt_token,'reason','management_key_unused'),p_actor_id,v_now);
 return jsonb_build_object('settlement',to_jsonb(s),'tax_invoice',public.safe_tax_invoice_json(inv),'retryable',true);
end $$;

revoke all on function public.company_confirm_and_request_tax_invoice(uuid,uuid,uuid) from public,anon,authenticated;
revoke all on function public.merchant_claim_tax_invoice_issue(uuid,uuid,uuid) from public,anon,authenticated;
revoke all on function public.merchant_finalize_tax_invoice_issue(uuid,uuid,uuid,uuid,text,text,text) from public,anon,authenticated;
revoke all on function public.merchant_apply_tax_invoice_status(uuid,uuid,uuid,int,text,text,timestamptz,timestamptz,timestamptz) from public,anon,authenticated;
revoke all on function public.merchant_reset_stale_tax_invoice_issue(uuid,uuid,uuid,uuid,boolean) from public,anon,authenticated;
grant execute on function public.company_confirm_and_request_tax_invoice(uuid,uuid,uuid) to service_role;
grant execute on function public.merchant_claim_tax_invoice_issue(uuid,uuid,uuid) to service_role;
grant execute on function public.merchant_finalize_tax_invoice_issue(uuid,uuid,uuid,uuid,text,text,text) to service_role;
grant execute on function public.merchant_apply_tax_invoice_status(uuid,uuid,uuid,int,text,text,timestamptz,timestamptz,timestamptz) to service_role;
grant execute on function public.merchant_reset_stale_tax_invoice_issue(uuid,uuid,uuid,uuid,boolean) to service_role;
