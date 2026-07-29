begin;

-- A backend/xact capability that browser and service roles cannot mint. It exists
-- only while this migration or the reset SECURITY DEFINER RPC removes append-only
-- dependent rows.
create table if not exists public.generated_reset_delete_guards (
  backend_pid int not null,
  transaction_xid bigint not null,
  settlement_id uuid not null,
  primary key(backend_pid,transaction_xid,settlement_id)
);

create or replace function public.prevent_settlement_event_mutation() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin
 if tg_op='DELETE' and exists(select 1 from public.generated_reset_delete_guards g
   where g.backend_pid=pg_catalog.pg_backend_pid() and g.transaction_xid=pg_catalog.txid_current()
     and g.settlement_id=old.settlement_id) then return old; end if;
 raise exception 'SETTLEMENT_EVENTS_ARE_IMMUTABLE' using errcode='55000';
end $$;
create or replace function public.prevent_tax_invoice_event_mutation() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin
 if tg_op='DELETE' and exists(select 1 from public.generated_reset_delete_guards g
   join public.tax_invoices i on i.id=old.tax_invoice_id
   where g.backend_pid=pg_catalog.pg_backend_pid() and g.transaction_xid=pg_catalog.txid_current()
     and g.settlement_id=i.settlement_id) then return old; end if;
 raise exception 'TAX_INVOICE_EVENTS_ARE_IMMUTABLE' using errcode='55000';
end $$;

-- Replay-safe retirement of the legacy settlement-demo provenance. The mapping is
-- authoritative: names and flags alone never select rows. Exact ordinary
-- settlements for a mapped run also aggregated those rows under 0048, so their
-- workflow snapshots are stale and are removed while real source rows remain.
create temporary table _legacy_generated_transactions on commit drop as
 select distinct dt.transaction_id
 from public.settlement_demo_transactions dt
 join public.settlement_demo_runs r on r.id=dt.run_id;
do $$
begin
 if exists(select 1 from public.meal_transactions child
   where child.original_transaction_id in (select transaction_id from _legacy_generated_transactions)
     and child.id not in (select transaction_id from _legacy_generated_transactions)) then
  raise exception 'LEGACY_GENERATED_TRANSACTION_EXTERNAL_REFERENCE: an unmapped transaction references mapped legacy evidence'
    using errcode='P0001';
 end if;
end $$;
create temporary table _legacy_derived_settlements on commit drop as
 select distinct s.id
 from public.settlement_demo_runs r
 -- 0042 seed rejected every pre-existing exact-period settlement, and 0048's
 -- ordinary creator necessarily aggregated the mapped rows. Therefore this exact
 -- merchant/company/month/date-range selection is derived evidence, not a broad
 -- company-month deletion rule.
 join public.settlements s on s.merchant_id=r.merchant_id and s.company_id=r.company_id
   and s.period_ym=r.period_ym and s.period_from=r.period_from and s.period_to=r.period_to
   and (s.id=r.settlement_id or not s.is_demo);
-- Lock the exact mapped derived graph before deciding whether local evidence is
-- safe to retire. Issued/completed history is intentionally deletable here; only
-- a transient or ambiguous provider operation aborts the migration.
do $$
begin
 perform 1 from public.settlements s join _legacy_derived_settlements d on d.id=s.id
   order by s.id for update of s;
 perform 1 from public.tax_invoices i join _legacy_derived_settlements d on d.id=i.settlement_id
   order by i.id for update of i;
 perform 1 from public.settlement_payments p join _legacy_derived_settlements d on d.id=p.settlement_id
   order by p.id for update of p;
 if exists(select 1 from public.tax_invoices i join _legacy_derived_settlements d on d.id=i.settlement_id
   where i.issue_attempt_token is not null or i.issue_attempt_started_at is not null
     or (i.issue_lease_expires_at is not null and i.issue_lease_expires_at>clock_timestamp())
     or i.reconciliation_required_at is not null) then
  raise exception 'LEGACY_GENERATED_STATE_PROVIDER_OPERATION_IN_FLIGHT' using errcode='P0001';
 end if;
end $$;
insert into public.generated_reset_delete_guards(backend_pid,transaction_xid,settlement_id)
 select pg_catalog.pg_backend_pid(),pg_catalog.txid_current(),id from _legacy_derived_settlements
 on conflict do nothing;
delete from public.tax_invoice_events e using public.tax_invoices i,_legacy_derived_settlements s
 where e.tax_invoice_id=i.id and i.settlement_id=s.id;
delete from public.settlement_events e using _legacy_derived_settlements s where e.settlement_id=s.id;
delete from public.settlement_payments p using _legacy_derived_settlements s where p.settlement_id=s.id;
delete from public.tax_invoices i using _legacy_derived_settlements s where i.settlement_id=s.id;
update public.settlement_demo_runs r set settlement_id=null
 from _legacy_derived_settlements s where r.settlement_id=s.id;
delete from public.settlements x using _legacy_derived_settlements s where x.id=s.id;
delete from public.reviews v using _legacy_generated_transactions t where v.transaction_id=t.transaction_id;
delete from public.settlement_demo_transactions dt using _legacy_generated_transactions t
 where dt.transaction_id=t.transaction_id;
delete from public.meal_transactions m using _legacy_generated_transactions t where m.id=t.transaction_id;
delete from public.settlement_demo_runs;
delete from public.settlement_demo_reset_requests;
revoke insert,update,delete on table public.settlement_demo_runs,
 public.settlement_demo_transactions,public.settlement_demo_reset_requests from service_role;
delete from public.generated_reset_delete_guards
 where backend_pid=pg_catalog.pg_backend_pid() and transaction_xid=pg_catalog.txid_current();

-- Neutral invoice-profile predicate used only through owner-executed generated RPCs.
create or replace function public.company_invoice_profile_complete(p_company_id uuid)
returns boolean language sql stable security definer set search_path=pg_catalog,public as $$
 select coalesce((select nullif(btrim(c.biz_reg_no),'') is not null
   and nullif(btrim(c.name),'') is not null and nullif(btrim(c.representative_name),'') is not null
   and nullif(btrim(c.address),'') is not null and nullif(btrim(c.business_type),'') is not null
   and nullif(btrim(c.business_item),'') is not null and nullif(btrim(c.tax_invoice_email),'') is not null
   and nullif(btrim(c.contact_name),'') is not null and nullif(btrim(c.contact_phone),'') is not null
   from public.companies c where c.id=p_company_id),false)
$$;

-- Temporary merchant-admin company/month transaction generator. Generated rows are
-- ordinary business rows; private membership tables are provenance, not a business flag.
create table if not exists public.generated_transaction_runs (
  id uuid primary key default gen_random_uuid(),
  merchant_id uuid not null references public.merchants(id) on delete restrict,
  company_id uuid not null references public.companies(id) on delete restrict,
  company_actor_id uuid not null references public.app_users(id) on delete restrict,
  period_from date not null,
  period_to date not null,
  period_ym text not null,
  settlement_id uuid references public.settlements(id) on delete restrict,
  created_by uuid not null references public.app_users(id) on delete restrict,
  created_at timestamptz not null default now(),
  check(period_from=date_trunc('month',period_from::timestamp)::date),
  check(period_to=(period_from+interval '1 month - 1 day')::date),
  check(period_ym=to_char(period_from,'YYYY-MM')),
  unique(merchant_id,company_id,period_ym),
  unique(settlement_id)
);
create table if not exists public.generated_transaction_members (
  run_id uuid not null references public.generated_transaction_runs(id) on delete cascade,
  transaction_id bigint not null references public.meal_transactions(id) on delete restrict,
  primary key(run_id,transaction_id), unique(transaction_id)
);
create table if not exists public.generated_transaction_reset_requests (
  merchant_id uuid not null references public.merchants(id) on delete restrict,
  company_id uuid not null references public.companies(id) on delete restrict,
  period_ym text not null,
  idempotency_key text not null check(length(idempotency_key) between 1 and 200),
  reset_run_id uuid,
  created_at timestamptz not null default now(),
  primary key(merchant_id,idempotency_key)
);

alter table public.generated_transaction_runs enable row level security;
alter table public.generated_transaction_members enable row level security;
alter table public.generated_transaction_reset_requests enable row level security;
alter table public.generated_reset_delete_guards enable row level security;
revoke all on table public.generated_transaction_runs,public.generated_transaction_members,
 public.generated_transaction_reset_requests,public.generated_reset_delete_guards
 from public,anon,authenticated,service_role;
-- The API only needs a tenant-filtered membership lookup for provider safety;
-- every mutation remains owner-only behind the generated RPCs.
grant select on table public.generated_transaction_runs to service_role;

create or replace function public.generated_transactions_assert_actor(p_actor_id uuid,p_merchant_id uuid)
returns void language plpgsql security definer set search_path=pg_catalog,public as $$
begin
 if not exists(select 1 from public.app_users where id=p_actor_id and merchant_id=p_merchant_id
   and role='merchant_admin' and status='active') then
  raise exception 'SETTLEMENT_GENERATION_FORBIDDEN' using errcode='P0001';
 end if;
end $$;

create or replace function public.generated_transactions_state(
 p_actor_id uuid,p_merchant_id uuid,p_company_id uuid default null,p_period_ym text default null)
returns jsonb language plpgsql volatile security definer set search_path=pg_catalog,public as $$
declare r public.generated_transaction_runs%rowtype; s public.settlements%rowtype;
 inv public.tax_invoices%rowtype; options jsonb; details jsonb:='[]'::jsonb; agg jsonb;
begin
 perform public.generated_transactions_assert_actor(p_actor_id,p_merchant_id);
 select coalesce(jsonb_agg(jsonb_build_object(
   'company_id',q.company_id,'company_name',q.company_name,
   'active_employee_customer_count',q.employee_count,
   'active_company_admin_available',q.admin_available,
   'invoice_legal_profile_complete',q.profile_complete,
   'eligible',q.employee_count>0 and q.admin_available and q.profile_complete and q.unit_price>0
      and q.tax_type in ('taxable','tax_free'),
   'reason',case when q.employee_count=0 then 'NO_ACTIVE_EMPLOYEE_OR_CUSTOMER'
     when not q.admin_available then 'NO_ACTIVE_COMPANY_ADMIN'
     when not q.profile_complete then 'BUSINESS_PROFILE_INCOMPLETE'
     when q.unit_price is null or q.unit_price<=0 then 'PRICE_NOT_CONFIGURED'
     when q.tax_type not in ('taxable','tax_free') then 'TAX_TYPE_UNCLASSIFIED' end)
   order by q.company_name,q.company_id),'[]'::jsonb) into options
 from (select c.id company_id,c.name company_name,mc.unit_price,mc.tax_type,
   (select count(*)::int from public.app_users u where u.company_id=c.id and u.status='active'
      and u.role in ('employee','customer')) employee_count,
   exists(select 1 from public.app_users u where u.company_id=c.id and u.status='active' and u.role='company_admin') admin_available,
   public.company_invoice_profile_complete(c.id) profile_complete
   from public.merchant_companies mc join public.companies c on c.id=mc.company_id and c.status='active'
   where mc.merchant_id=p_merchant_id and mc.status='active') q;
 if p_company_id is null or p_period_ym is null then
  return jsonb_build_object('generated',false,'stage','empty','options',options,'transactions','[]'::jsonb);
 end if;
 select * into r from public.generated_transaction_runs where merchant_id=p_merchant_id
   and company_id=p_company_id and period_ym=p_period_ym;
 if not found then return jsonb_build_object('generated',false,'stage','empty','options',options,'transactions','[]'::jsonb); end if;
 select coalesce(jsonb_agg(jsonb_build_object(
   'display_sequence',x.seq,'user_label',x.display_name,'used_at',x.created_at,
   'description',coalesce(x.product_name,'식대 사용'),'kind',x.kind,
   'supply_amount',case when x.kind='spend' then x.settlement_supply_amount else -x.settlement_supply_amount end,
   'vat_amount',case when x.kind='spend' then x.settlement_vat_amount else -x.settlement_vat_amount end,
   'total_amount',case when x.kind='spend' then x.settlement_total_amount else -x.settlement_total_amount end)
   order by x.seq),'[]'::jsonb),jsonb_build_object('transaction_count',count(*)::int,
   'supply_amount',coalesce(sum(case when x.kind='spend' then x.settlement_supply_amount else -x.settlement_supply_amount end),0),
   'vat_amount',coalesce(sum(case when x.kind='spend' then x.settlement_vat_amount else -x.settlement_vat_amount end),0),
   'total_amount',coalesce(sum(case when x.kind='spend' then x.settlement_total_amount else -x.settlement_total_amount end),0))
 into details,agg from (select row_number() over(order by t.created_at,t.id)::int seq,t.*,u.display_name
   from public.generated_transaction_members gm join public.meal_transactions t on t.id=gm.transaction_id
   join public.app_users u on u.id=t.user_id where gm.run_id=r.id) x;
 if r.settlement_id is not null then
  select * into s from public.settlements where id=r.settlement_id and not is_demo;
  select * into inv from public.tax_invoices where settlement_id=s.id and document_type='original';
 end if;
 return jsonb_build_object('generated',true,'stage',case when r.settlement_id is null then 'seeded'
   when s.payment_status in ('paid','overpaid') then 'paid'
   when s.tax_invoice_status in ('issued','nts_sending','nts_accepted') then 'issued'
   when s.settlement_status='confirmed' and s.tax_invoice_status='requested' then 'confirmed'
   else s.settlement_status end,'run_id',r.id,'company_id',r.company_id,
   'company_name',(select name from public.companies where id=r.company_id),'period_ym',r.period_ym,
   'transaction_count',jsonb_array_length(details),'aggregate',agg,'transactions',details,'options',options,
   'settlement',case when r.settlement_id is null then null else jsonb_strip_nulls(jsonb_build_object(
    'id',s.id,'period_ym',s.period_ym,'tx_count',s.tx_count,'supply_amount',s.supply_amount,
    'vat_amount',s.vat_amount,'total_amount',s.total_amount,'status',s.status,
    'settlement_status',s.settlement_status,'tax_invoice_status',s.tax_invoice_status,
    'payment_status',s.payment_status,'due_date',s.due_date,'paid_at',s.paid_at,
    'issued_at',inv.issued_at,'nts_confirm_num',nullif(btrim(inv.nts_confirm_num),''),
    'can_view_tax_invoice',s.tax_invoice_status in ('issued','nts_sending','nts_accepted'),
    'can_download_tax_invoice_pdf',s.tax_invoice_status in ('issued','nts_sending','nts_accepted'))) end);
end $$;

create or replace function public.generate_company_month_transactions(
 p_actor_id uuid,p_merchant_id uuid,p_company_id uuid,p_period_ym text)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare r public.generated_transaction_runs%rowtype; start_date date; end_date date;
 admin_id uuid; users uuid[]; contract public.merchant_companies%rowtype; split record;
 i int; d date; tx_id bigint; workdays date[];
begin
 perform public.generated_transactions_assert_actor(p_actor_id,p_merchant_id);
 if p_period_ym is null or p_period_ym !~ '^[0-9]{4}-(0[1-9]|1[0-2])$' then raise exception 'SETTLEMENT_INPUT_INVALID' using errcode='P0001'; end if;
 start_date:=to_date(p_period_ym||'-01','YYYY-MM-DD'); end_date:=(start_date+interval '1 month - 1 day')::date;
 if to_char(start_date,'YYYY-MM')<>p_period_ym or start_date>=date_trunc('month',current_date)::date
   or start_date<date_trunc('month',current_date)::date-interval '24 months' then raise exception 'SETTLEMENT_INPUT_INVALID' using errcode='P0001'; end if;
 perform pg_advisory_xact_lock(pg_catalog.hashtext(p_merchant_id::text),pg_catalog.hashtext(p_company_id::text||':'||p_period_ym));
 select * into r from public.generated_transaction_runs where merchant_id=p_merchant_id and company_id=p_company_id and period_ym=p_period_ym for update;
 if found then return public.generated_transactions_state(p_actor_id,p_merchant_id,p_company_id,p_period_ym); end if;
 select mc.* into contract from public.merchant_companies mc join public.companies c on c.id=mc.company_id and c.status='active'
  where mc.merchant_id=p_merchant_id and mc.company_id=p_company_id and mc.status='active' for key share of mc;
 if not found then raise exception 'SETTLEMENT_GENERATION_COMPANY_INELIGIBLE' using errcode='P0001'; end if;
 if contract.unit_price is null or contract.unit_price<=0 then raise exception 'PRICE_NOT_CONFIGURED' using errcode='P0001'; end if;
 if contract.tax_type not in ('taxable','tax_free') then raise exception 'TAX_TYPE_UNCLASSIFIED' using errcode='P0001'; end if;
 select id into admin_id from public.app_users where company_id=p_company_id and role='company_admin' and status='active' order by id limit 1;
 select array_agg(id order by id) into users from public.app_users where company_id=p_company_id and role in ('employee','customer') and status='active';
 if admin_id is null then raise exception 'SETTLEMENT_GENERATION_COMPANY_ADMIN_REQUIRED' using errcode='P0001'; end if;
 if coalesce(cardinality(users),0)=0 then raise exception 'SETTLEMENT_GENERATION_EMPLOYEE_REQUIRED' using errcode='P0001'; end if;
 if not public.company_invoice_profile_complete(p_company_id) then raise exception 'BUSINESS_PROFILE_INCOMPLETE' using errcode='P0001'; end if;
 -- Ordinary source rows may coexist and are included in the later settlement.
 -- An existing settlement is stale/derived state that only explicit reset removes.
 if exists(select 1 from public.settlements where merchant_id=p_merchant_id and company_id=p_company_id
   and period_ym=p_period_ym and period_from=start_date and period_to=end_date and not is_demo)
 then raise exception 'GENERATED_PERIOD_NOT_EMPTY' using errcode='P0001'; end if;
 insert into public.generated_transaction_runs(merchant_id,company_id,company_actor_id,period_from,period_to,period_ym,created_by)
 values(p_merchant_id,p_company_id,admin_id,start_date,end_date,p_period_ym,p_actor_id) returning * into r;
 select array_agg(gs::date order by gs) into workdays from generate_series(start_date,end_date,interval '1 day') gs where extract(isodow from gs)<6;
 select * into split from public.split_tax_inclusive(contract.unit_price,contract.tax_type);
 for i in 1..least(10,cardinality(workdays)) loop
  d:=workdays[1+((i*2-1)%cardinality(workdays))];
  insert into public.meal_transactions(user_id,company_id,merchant_id,amount,kind,tx_code,meal_window,flags,
   idempotency_key,product_name,product_price,pay_type,tax_type,supply_amount,vat_amount,total_amount,
   settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,is_demo,created_at)
  values(users[1+((i-1)%cardinality(users))],p_company_id,p_merchant_id,-contract.unit_price,'spend',
   upper(substr(replace(r.id::text,'-',''),1,8))||lpad(i::text,2,'0'),'중식','{}'::jsonb,
   gen_random_uuid()::text,'식대 사용',contract.unit_price,'ledger',contract.tax_type,
   split.supply_amount,split.vat_amount,split.total_amount,contract.tax_type,split.supply_amount,
   split.vat_amount,split.total_amount,false,(d+time '12:00') at time zone 'Asia/Seoul') returning id into tx_id;
  insert into public.generated_transaction_members(run_id,transaction_id) values(r.id,tx_id);
 end loop;
 return public.generated_transactions_state(p_actor_id,p_merchant_id,p_company_id,p_period_ym);
end $$;

create or replace function public.generated_transactions_create_settlement(
 p_actor_id uuid,p_merchant_id uuid,p_company_id uuid,p_period_ym text)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare r public.generated_transaction_runs%rowtype; result jsonb; sid uuid;
begin
 perform public.generated_transactions_assert_actor(p_actor_id,p_merchant_id);
 perform pg_advisory_xact_lock(pg_catalog.hashtext(p_merchant_id::text),pg_catalog.hashtext(p_company_id::text||':'||p_period_ym));
 select * into r from public.generated_transaction_runs where merchant_id=p_merchant_id and company_id=p_company_id and period_ym=p_period_ym for update;
 if not found then raise exception 'SETTLEMENT_GENERATION_NOT_CREATED' using errcode='P0001'; end if;
 if r.settlement_id is not null then return public.generated_transactions_state(p_actor_id,p_merchant_id,p_company_id,p_period_ym); end if;
 if exists(select 1 from public.settlements where merchant_id=p_merchant_id and company_id=p_company_id
   and period_ym=p_period_ym and period_from=r.period_from and period_to=r.period_to and not is_demo)
 then raise exception 'GENERATED_SETTLEMENT_SET_CONFLICT' using errcode='P0001'; end if;
 result:=public.create_merchant_settlement(p_merchant_id,p_company_id,r.period_from,r.period_to); sid:=(result->>'id')::uuid;
 if not exists(select 1 from public.settlements where id=sid and merchant_id=p_merchant_id and company_id=p_company_id and period_ym=p_period_ym and not is_demo)
 then raise exception 'GENERATED_SETTLEMENT_RESULT_MISMATCH' using errcode='P0001'; end if;
 update public.generated_transaction_runs set settlement_id=sid where id=r.id;
 return public.generated_transactions_state(p_actor_id,p_merchant_id,p_company_id,p_period_ym);
end $$;

create or replace function public.generated_transactions_confirm(p_actor_id uuid,p_merchant_id uuid,p_company_id uuid,p_period_ym text)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare r public.generated_transaction_runs%rowtype;
begin
 perform public.generated_transactions_assert_actor(p_actor_id,p_merchant_id);
 perform pg_advisory_xact_lock(pg_catalog.hashtext(p_merchant_id::text),pg_catalog.hashtext(p_company_id::text||':'||p_period_ym));
 select * into r from public.generated_transaction_runs where merchant_id=p_merchant_id and company_id=p_company_id and period_ym=p_period_ym for update;
 if not found or r.settlement_id is null then raise exception 'SETTLEMENT_GENERATION_NOT_CREATED' using errcode='P0001'; end if;
 perform public.merchant_send_settlement(p_actor_id,p_merchant_id,r.settlement_id);
 perform public.company_confirm_and_request_tax_invoice(r.company_actor_id,r.company_id,r.settlement_id);
 return public.generated_transactions_state(p_actor_id,p_merchant_id,p_company_id,p_period_ym);
end $$;

create or replace function public.generated_transactions_assert_issue(p_actor_id uuid,p_merchant_id uuid,p_company_id uuid,p_period_ym text)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare r public.generated_transaction_runs%rowtype; s public.settlements%rowtype;
begin
 perform public.generated_transactions_assert_actor(p_actor_id,p_merchant_id);
 perform pg_advisory_xact_lock(pg_catalog.hashtext(p_merchant_id::text),pg_catalog.hashtext(p_company_id::text||':'||p_period_ym));
 select * into r from public.generated_transaction_runs where merchant_id=p_merchant_id and company_id=p_company_id and period_ym=p_period_ym for update;
 if not found or r.settlement_id is null then raise exception 'SETTLEMENT_GENERATION_NOT_CREATED' using errcode='P0001'; end if;
 select * into s from public.settlements where id=r.settlement_id and not is_demo;
 if not found or s.settlement_status<>'confirmed' or s.tax_invoice_status not in ('requested','failed') then raise exception 'SETTLEMENT_GENERATION_STATE_CONFLICT' using errcode='P0001'; end if;
 return jsonb_build_object('settlement_id',s.id,'company_id',s.company_id);
end $$;

create or replace function public.generated_transactions_mark_paid(p_actor_id uuid,p_merchant_id uuid,p_company_id uuid,p_period_ym text)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare r public.generated_transaction_runs%rowtype; s public.settlements%rowtype; paid bigint;
begin
 perform public.generated_transactions_assert_actor(p_actor_id,p_merchant_id);
 perform pg_advisory_xact_lock(pg_catalog.hashtext(p_merchant_id::text),pg_catalog.hashtext(p_company_id::text||':'||p_period_ym));
 select * into r from public.generated_transaction_runs where merchant_id=p_merchant_id and company_id=p_company_id and period_ym=p_period_ym for update;
 if not found or r.settlement_id is null then raise exception 'SETTLEMENT_GENERATION_NOT_CREATED' using errcode='P0001'; end if;
 select * into s from public.settlements where id=r.settlement_id for update;
 select coalesce(sum(amount),0) into paid from public.settlement_payments where settlement_id=s.id and confirmed_at is not null;
 if s.settlement_status not in ('confirmed','completed') or s.tax_invoice_status not in ('issued','nts_sending','nts_accepted') or paid<>0
 then raise exception 'SETTLEMENT_GENERATION_STATE_CONFLICT' using errcode='P0001'; end if;
 perform public.merchant_mark_settlement_paid(p_actor_id,p_merchant_id,s.id,s.total_amount,'정산 입금',clock_timestamp(),
   '정산 입금 처리',gen_random_uuid()::text);
 return public.generated_transactions_state(p_actor_id,p_merchant_id,p_company_id,p_period_ym);
end $$;

create or replace function public.reset_generated_company_month_state(
 p_actor_id uuid,p_merchant_id uuid,p_company_id uuid,p_period_ym text,p_idempotency_key text)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare r public.generated_transaction_runs%rowtype; mids bigint[]; sids uuid[]; inv_ids uuid[];
begin
 perform public.generated_transactions_assert_actor(p_actor_id,p_merchant_id);
 if p_period_ym is null or p_period_ym !~ '^[0-9]{4}-(0[1-9]|1[0-2])$'
   or nullif(btrim(p_idempotency_key),'') is null or length(p_idempotency_key)>200
 then raise exception 'SETTLEMENT_INPUT_INVALID' using errcode='P0001'; end if;
 perform pg_advisory_xact_lock(pg_catalog.hashtext(p_merchant_id::text),pg_catalog.hashtext(p_company_id::text||':'||p_period_ym));
 if exists(select 1 from public.generated_transaction_reset_requests where merchant_id=p_merchant_id and idempotency_key=p_idempotency_key
    and company_id=p_company_id and period_ym=p_period_ym) then
  return public.generated_transactions_state(p_actor_id,p_merchant_id,p_company_id,p_period_ym)||jsonb_build_object('reset',true,'idempotent',true);
 end if;
 if exists(select 1 from public.generated_transaction_reset_requests where merchant_id=p_merchant_id and idempotency_key=p_idempotency_key)
 then raise exception 'IDEMPOTENCY_CONFLICT' using errcode='P0001'; end if;
 select * into r from public.generated_transaction_runs where merchant_id=p_merchant_id and company_id=p_company_id and period_ym=p_period_ym for update;
 if not found then
  insert into public.generated_transaction_reset_requests(merchant_id,company_id,period_ym,idempotency_key)
   values(p_merchant_id,p_company_id,p_period_ym,p_idempotency_key);
  return public.generated_transactions_state(p_actor_id,p_merchant_id,p_company_id,p_period_ym)||jsonb_build_object('reset',true,'idempotent',true);
 end if;
 select array_agg(transaction_id order by transaction_id) into mids from public.generated_transaction_members where run_id=r.id;
 if exists(select 1 from public.reviews where transaction_id=any(mids))
   or exists(select 1 from public.meal_transactions where original_transaction_id=any(mids)
     and not (id=any(mids)))
 then raise exception 'GENERATED_STATE_EXTERNAL_REFERENCE' using errcode='P0001'; end if;
 select array_agg(id) into sids from public.settlements where merchant_id=p_merchant_id and company_id=p_company_id
   and period_ym=p_period_ym and period_from=r.period_from and period_to=r.period_to and not is_demo;
 if r.settlement_id is not null and (sids is null or not (r.settlement_id=any(sids)))
 then raise exception 'GENERATED_SETTLEMENT_SET_CONFLICT' using errcode='P0001'; end if;
 if sids is not null then
  -- Parent-first deterministic locks serialize reset against claim/finalize,
  -- provider reconciliation, and payment matching before any safety decision.
  perform 1 from public.settlements where id=any(sids) order by id for update;
  perform 1 from public.tax_invoices where settlement_id=any(sids) order by id for update;
  perform 1 from public.settlement_payments where settlement_id=any(sids) order by id for update;
  if exists(select 1 from public.settlements where id=any(sids)
      and tax_invoice_status in ('issuing','nts_sending','nts_accepted'))
    or exists(select 1 from public.settlement_payments where settlement_id=any(sids)
      and external_reference is not null)
    or exists(select 1 from public.tax_invoices where settlement_id=any(sids) and (
      issue_attempt_token is not null or issue_attempt_started_at is not null
      or (issue_lease_expires_at is not null and issue_lease_expires_at>clock_timestamp())
      or reconciliation_required_at is not null or nts_sent_at is not null or nts_accepted_at is not null
      or issued_at is not null or popbill_status_code is not null or provider_response is not null
      or nullif(btrim(coalesce(popbill_status,'')),'') is not null
      or nullif(btrim(coalesce(nts_confirm_num,'')),'') is not null))
    or exists(select 1 from public.tax_invoice_events e join public.tax_invoices i on i.id=e.tax_invoice_id
      where i.settlement_id=any(sids) and e.provider_event_id is not null)
  then raise exception 'GENERATED_STATE_EXTERNAL_REFERENCE' using errcode='P0001'; end if;
  insert into public.generated_reset_delete_guards
    select pg_catalog.pg_backend_pid(),pg_catalog.txid_current(),unnest(sids);
  select array_agg(id) into inv_ids from public.tax_invoices where settlement_id=any(sids);
  if inv_ids is not null then delete from public.tax_invoice_events where tax_invoice_id=any(inv_ids); end if;
  delete from public.settlement_events where settlement_id=any(sids);
  delete from public.settlement_payments where settlement_id=any(sids);
  delete from public.tax_invoices where settlement_id=any(sids);
  update public.generated_transaction_runs set settlement_id=null where id=r.id;
  delete from public.settlements where id=any(sids);
 end if;
 delete from public.generated_transaction_members where run_id=r.id;
 delete from public.meal_transactions where id=any(mids);
 delete from public.generated_transaction_runs where id=r.id;
 delete from public.generated_reset_delete_guards where backend_pid=pg_catalog.pg_backend_pid() and transaction_xid=pg_catalog.txid_current();
 insert into public.generated_transaction_reset_requests(merchant_id,company_id,period_ym,idempotency_key,reset_run_id)
 values(p_merchant_id,p_company_id,p_period_ym,p_idempotency_key,r.id);
 return public.generated_transactions_state(p_actor_id,p_merchant_id,p_company_id,p_period_ym)||jsonb_build_object('reset',true,'idempotent',false);
end $$;

revoke all on function public.generated_transactions_assert_actor(uuid,uuid),
 public.company_invoice_profile_complete(uuid),
 public.generated_transactions_state(uuid,uuid,uuid,text),
 public.generate_company_month_transactions(uuid,uuid,uuid,text),
 public.generated_transactions_create_settlement(uuid,uuid,uuid,text),
 public.generated_transactions_confirm(uuid,uuid,uuid,text),
 public.generated_transactions_assert_issue(uuid,uuid,uuid,text),
 public.generated_transactions_mark_paid(uuid,uuid,uuid,text),
 public.reset_generated_company_month_state(uuid,uuid,uuid,text,text)
 from public,anon,authenticated,service_role;

-- Retire every legacy mutating/demo surface after its mapped evidence is removed.
-- The owner may still call old helpers internally, but no API role can execute them.
revoke all on function public.settlement_demo_state(uuid,uuid),
 public.settlement_demo_assert_actor(uuid,uuid),
 public.settlement_demo_company_profile_complete(uuid),
 public.settlement_demo_validate_run(uuid),
 public.settlement_demo_seed(uuid,uuid,uuid,text),
 public.settlement_demo_create(uuid,uuid),
 public.settlement_demo_confirm(uuid,uuid),
 public.settlement_demo_assert_issue(uuid,uuid),
 public.settlement_demo_mark_paid(uuid,uuid),
 public.settlement_demo_reset(uuid,uuid),
 public.settlement_demo_reset(uuid,uuid,text)
 from public,anon,authenticated,service_role;

grant execute on function public.generated_transactions_state(uuid,uuid,uuid,text),
 public.generate_company_month_transactions(uuid,uuid,uuid,text),
 public.generated_transactions_create_settlement(uuid,uuid,uuid,text),
 public.generated_transactions_confirm(uuid,uuid,uuid,text),
 public.generated_transactions_assert_issue(uuid,uuid,uuid,text),
 public.generated_transactions_mark_paid(uuid,uuid,uuid,text),
 public.reset_generated_company_month_state(uuid,uuid,uuid,text,text) to service_role;

notify pgrst,'reload schema';
commit;
