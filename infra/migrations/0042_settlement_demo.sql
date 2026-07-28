-- Merchant-admin settlement demo using an existing active contract, real company,
-- real company administrator, and real active employee/customer accounts.
-- This migration creates no companies, contracts, users, or business identities.

create table if not exists public.settlement_demo_runs (
  id uuid primary key default gen_random_uuid(),
  merchant_id uuid not null references public.merchants(id) on delete restrict,
  company_id uuid not null references public.companies(id) on delete restrict,
  company_actor_id uuid not null references public.app_users(id) on delete restrict,
  period_from date not null,
  period_to date not null,
  period_ym text not null,
  settlement_id uuid references public.settlements(id) on delete restrict,
  created_by uuid not null references public.app_users(id) on delete restrict,
  is_current boolean not null default true,
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  check (period_from=date_trunc('month',period_from::timestamp)::date),
  check (period_to=(period_from+interval '1 month - 1 day')::date),
  check (period_ym=to_char(period_from,'YYYY-MM')),
  check ((is_current and archived_at is null) or (not is_current and archived_at is not null)),
  unique(settlement_id)
);
-- 0042 was never deployed, but make local pre-release replays converge.
alter table public.settlement_demo_runs drop column if exists transaction_user_id;
create unique index if not exists settlement_demo_runs_one_current
  on public.settlement_demo_runs(merchant_id) where is_current;

create table if not exists public.settlement_demo_transactions (
  run_id uuid not null references public.settlement_demo_runs(id) on delete cascade,
  transaction_id bigint not null references public.meal_transactions(id) on delete cascade,
  primary key(run_id,transaction_id), unique(transaction_id)
);

create table if not exists public.settlement_demo_reset_requests (
  merchant_id uuid not null references public.merchants(id) on delete restrict,
  idempotency_key text not null,
  reset_run_id uuid,
  created_at timestamptz not null default now(),
  primary key(merchant_id,idempotency_key),
  check(length(idempotency_key) between 1 and 200)
);
alter table public.settlement_demo_reset_requests add column if not exists reset_run_id uuid;

alter table public.settlement_demo_runs enable row level security;
alter table public.settlement_demo_transactions enable row level security;
alter table public.settlement_demo_reset_requests enable row level security;
revoke all on table public.settlement_demo_runs,public.settlement_demo_transactions,
  public.settlement_demo_reset_requests from public,anon,authenticated,service_role;
grant select,insert,update,delete on table public.settlement_demo_runs,public.settlement_demo_transactions,
  public.settlement_demo_reset_requests to service_role;

create or replace function public.settlement_demo_assert_actor(p_actor_id uuid,p_merchant_id uuid)
returns void language plpgsql security definer set search_path=pg_catalog,public as $$
begin
 if not exists(select 1 from public.app_users where id=p_actor_id and merchant_id=p_merchant_id
               and role='merchant_admin' and status='active') then
   raise exception 'SETTLEMENT_DEMO_FORBIDDEN' using errcode='P0001';
 end if;
end $$;

create or replace function public.settlement_demo_company_profile_complete(p_company_id uuid)
returns boolean language sql stable security definer set search_path=pg_catalog,public as $$
 select coalesce((select nullif(btrim(c.biz_reg_no),'') is not null
   and nullif(btrim(c.name),'') is not null and nullif(btrim(c.representative_name),'') is not null
   and nullif(btrim(c.address),'') is not null and nullif(btrim(c.business_type),'') is not null
   and nullif(btrim(c.business_item),'') is not null and nullif(btrim(c.tax_invoice_email),'') is not null
   and nullif(btrim(c.contact_name),'') is not null and nullif(btrim(c.contact_phone),'') is not null
   from public.companies c where c.id=p_company_id),false)
$$;

-- Cross-table ownership is enforced at commit as well as inside every operation.
create or replace function public.settlement_demo_validate_run(p_run_id uuid)
returns void language plpgsql security definer set search_path=pg_catalog,public as $$
declare r public.settlement_demo_runs%rowtype; c_status text; mc_status text;
 qids bigint[]; dids bigint[]; qc bigint; dc bigint;
 qs bigint; qv bigint; qt bigint; ds bigint; dv bigint; dt bigint;
begin
 select * into r from public.settlement_demo_runs where id=p_run_id;
 if not found then return; end if;
 if r.is_current then
   select status into c_status from public.companies where id=r.company_id for key share;
   select status into mc_status from public.merchant_companies
     where merchant_id=r.merchant_id and company_id=r.company_id for key share;
 end if;
 if not exists(select 1 from public.app_users u where u.id=r.company_actor_id
      and u.company_id=r.company_id and u.role='company_admin' and u.status='active')
    or not exists(select 1 from public.app_users u where u.id=r.created_by
      and u.merchant_id=r.merchant_id and u.role='merchant_admin' and u.status='active')
    or (r.is_current and (c_status is distinct from 'active' or mc_status is distinct from 'active'))
    or (r.settlement_id is not null and not exists(select 1 from public.settlements s
      where s.id=r.settlement_id and s.merchant_id=r.merchant_id and s.company_id=r.company_id
        and s.period_ym=r.period_ym and s.period_from=r.period_from and s.period_to=r.period_to))
    or exists(select 1 from public.settlement_demo_transactions d
      left join public.meal_transactions t on t.id=d.transaction_id
      left join public.app_users u on u.id=t.user_id
      where d.run_id=r.id and (t.id is null or t.merchant_id<>r.merchant_id
        or t.company_id<>r.company_id or u.company_id<>r.company_id
        or u.role not in ('employee','customer')
        or t.flags->>'run_id' is distinct from r.id::text
        or t.flags->>'settlement_demo' is distinct from 'true')) then
   raise exception 'SETTLEMENT_DEMO_MEMBERSHIP_INVALID' using errcode='P0001';
 end if;
 if r.is_current then
   select count(*),array_agg(t.id order by t.id),
     coalesce(sum(case when t.kind='spend' then t.settlement_supply_amount else -t.settlement_supply_amount end),0),
     coalesce(sum(case when t.kind='spend' then t.settlement_vat_amount else -t.settlement_vat_amount end),0),
     coalesce(sum(case when t.kind='spend' then t.settlement_total_amount else -t.settlement_total_amount end),0)
   into qc,qids,qs,qv,qt from public.meal_transactions t
   where t.merchant_id=r.merchant_id and t.company_id=r.company_id
     and t.pay_type in ('ledger','subsidized') and t.kind in ('spend','refund','cancel')
     and t.created_at >= (r.period_from::timestamp at time zone 'Asia/Seoul')
     and t.created_at < ((r.period_to+1)::timestamp at time zone 'Asia/Seoul');
   select count(*),array_agg(t.id order by t.id),
     coalesce(sum(case when t.kind='spend' then t.settlement_supply_amount else -t.settlement_supply_amount end),0),
     coalesce(sum(case when t.kind='spend' then t.settlement_vat_amount else -t.settlement_vat_amount end),0),
     coalesce(sum(case when t.kind='spend' then t.settlement_total_amount else -t.settlement_total_amount end),0)
   into dc,dids,ds,dv,dt from public.settlement_demo_transactions d
     join public.meal_transactions t on t.id=d.transaction_id where d.run_id=r.id;
   if row(qc,qids,qs,qv,qt) is distinct from row(dc,dids,ds,dv,dt) then
     raise exception 'DEMO_PERIOD_TRANSACTION_CONFLICT' using errcode='P0001';
   end if;
   if r.settlement_id is not null and not exists(select 1 from public.settlements s
      where s.id=r.settlement_id and row(s.tx_count,s.supply_amount,s.vat_amount,s.total_amount)
        is not distinct from row(dc,ds,dv,dt)) then
     raise exception 'SETTLEMENT_DEMO_MEMBERSHIP_INVALID' using errcode='P0001';
   end if;
 end if;
end $$;

create or replace function public.settlement_demo_integrity_trigger()
returns trigger language plpgsql security definer set search_path=pg_catalog,public as $$
declare x record;
begin
 if tg_table_name='settlement_demo_runs' then
   perform public.settlement_demo_validate_run(coalesce(new.id,old.id));
 elsif tg_table_name='settlement_demo_transactions' then
   if tg_op<>'DELETE' then perform public.settlement_demo_validate_run(new.run_id); end if;
   if tg_op<>'INSERT' then perform public.settlement_demo_validate_run(old.run_id); end if;
 elsif tg_table_name='app_users' then
   for x in select distinct r.id from public.settlement_demo_runs r
     left join public.settlement_demo_transactions dt on dt.run_id=r.id
     left join public.meal_transactions t on t.id=dt.transaction_id
     where r.company_actor_id in (old.id,new.id) or r.created_by in (old.id,new.id) or t.user_id in (old.id,new.id)
   loop perform public.settlement_demo_validate_run(x.id); end loop;
 elsif tg_table_name='settlements' then
   for x in select id from public.settlement_demo_runs where settlement_id in (old.id,new.id)
   loop perform public.settlement_demo_validate_run(x.id); end loop;
 elsif tg_table_name='meal_transactions' then
   for x in select distinct r.id from public.settlement_demo_runs r
     left join public.settlement_demo_transactions d on d.run_id=r.id
     where r.is_current and (
       (tg_op<>'INSERT' and d.transaction_id=old.id) or (tg_op<>'DELETE' and d.transaction_id=new.id)
       or (tg_op<>'INSERT' and r.merchant_id=old.merchant_id and r.company_id=old.company_id
         and old.created_at >= (r.period_from::timestamp at time zone 'Asia/Seoul')
         and old.created_at < ((r.period_to+1)::timestamp at time zone 'Asia/Seoul'))
       or (tg_op<>'DELETE' and r.merchant_id=new.merchant_id and r.company_id=new.company_id
         and new.created_at >= (r.period_from::timestamp at time zone 'Asia/Seoul')
         and new.created_at < ((r.period_to+1)::timestamp at time zone 'Asia/Seoul')))
   loop perform public.settlement_demo_validate_run(x.id); end loop;
 elsif tg_table_name='companies' then
   for x in select id from public.settlement_demo_runs where is_current
     and ((tg_op<>'INSERT' and company_id=old.id) or (tg_op<>'DELETE' and company_id=new.id))
   loop perform public.settlement_demo_validate_run(x.id); end loop;
 elsif tg_table_name='merchant_companies' then
   for x in select id from public.settlement_demo_runs where is_current and (
     (tg_op<>'INSERT' and merchant_id=old.merchant_id and company_id=old.company_id)
     or (tg_op<>'DELETE' and merchant_id=new.merchant_id and company_id=new.company_id))
   loop perform public.settlement_demo_validate_run(x.id); end loop;
 end if;
 return null;
end $$;

revoke all on function public.settlement_demo_assert_actor(uuid,uuid),
 public.settlement_demo_company_profile_complete(uuid),public.settlement_demo_validate_run(uuid),
 public.settlement_demo_integrity_trigger() from public,anon,authenticated,service_role;
drop trigger if exists settlement_demo_runs_integrity on public.settlement_demo_runs;
create constraint trigger settlement_demo_runs_integrity after insert or update on public.settlement_demo_runs
 deferrable initially deferred for each row execute function public.settlement_demo_integrity_trigger();
drop trigger if exists settlement_demo_transactions_integrity on public.settlement_demo_transactions;
create constraint trigger settlement_demo_transactions_integrity after insert or update or delete on public.settlement_demo_transactions
 deferrable initially deferred for each row execute function public.settlement_demo_integrity_trigger();
drop trigger if exists settlement_demo_users_integrity on public.app_users;
create constraint trigger settlement_demo_users_integrity after update of id,company_id,merchant_id,role,status on public.app_users
 deferrable initially deferred for each row execute function public.settlement_demo_integrity_trigger();
drop trigger if exists settlement_demo_settlements_integrity on public.settlements;
create constraint trigger settlement_demo_settlements_integrity after update of id,merchant_id,company_id,period_ym,period_from,period_to,tx_count,supply_amount,vat_amount,total_amount on public.settlements
 deferrable initially deferred for each row execute function public.settlement_demo_integrity_trigger();
drop trigger if exists settlement_demo_meal_transactions_integrity on public.meal_transactions;
create constraint trigger settlement_demo_meal_transactions_integrity
 after insert or delete or update of id,merchant_id,company_id,user_id,created_at,pay_type,kind,
   settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,flags on public.meal_transactions
 deferrable initially deferred for each row execute function public.settlement_demo_integrity_trigger();
drop trigger if exists settlement_demo_companies_integrity on public.companies;
create constraint trigger settlement_demo_companies_integrity after delete or update of id,status on public.companies
 deferrable initially deferred for each row execute function public.settlement_demo_integrity_trigger();
drop trigger if exists settlement_demo_contracts_integrity on public.merchant_companies;
create constraint trigger settlement_demo_contracts_integrity after delete or update of merchant_id,company_id,status on public.merchant_companies
 deferrable initially deferred for each row execute function public.settlement_demo_integrity_trigger();

create or replace function public.settlement_demo_state(p_actor_id uuid,p_merchant_id uuid)
returns jsonb language plpgsql stable security definer set search_path=pg_catalog,public as $$
declare r public.settlement_demo_runs%rowtype; s public.settlements%rowtype;
 inv public.tax_invoices%rowtype; n int; agg jsonb; options jsonb;
begin
 perform public.settlement_demo_assert_actor(p_actor_id,p_merchant_id);
 select coalesce(jsonb_agg(jsonb_build_object(
   'company_id',q.company_id,'company_name',q.company_name,
   'active_employee_customer_count',q.employee_count,
   'active_company_admin_available',q.admin_available,
   'invoice_legal_profile_complete',q.profile_complete,
   'eligible',q.employee_count>0 and q.admin_available and q.profile_complete,
   'reason',case when q.employee_count=0 then 'NO_ACTIVE_EMPLOYEE_OR_CUSTOMER'
                 when not q.admin_available then 'NO_ACTIVE_COMPANY_ADMIN'
                 when not q.profile_complete then 'BUSINESS_PROFILE_INCOMPLETE' else null end)
   order by q.company_name,q.company_id),'[]'::jsonb) into options
 from (select c.id company_id,c.name company_name,
   (select count(*)::int from public.app_users u where u.company_id=c.id and u.status='active'
      and u.role in ('employee','customer')) employee_count,
   exists(select 1 from public.app_users u where u.company_id=c.id and u.status='active'
      and u.role='company_admin') admin_available,
   public.settlement_demo_company_profile_complete(c.id) profile_complete
   from public.merchant_companies mc join public.companies c on c.id=mc.company_id and c.status='active'
   where mc.merchant_id=p_merchant_id and mc.status='active') q;
 select * into r from public.settlement_demo_runs where merchant_id=p_merchant_id and is_current;
 if not found then return jsonb_build_object('seeded',false,'stage','empty','options',options); end if;
 perform public.settlement_demo_validate_run(r.id);
 select count(*)::int,jsonb_build_object('transaction_count',count(*)::int,
   'supply_amount',coalesce(sum(case when t.kind='spend' then t.settlement_supply_amount else -t.settlement_supply_amount end),0),
   'vat_amount',coalesce(sum(case when t.kind='spend' then t.settlement_vat_amount else -t.settlement_vat_amount end),0),
   'total_amount',coalesce(sum(case when t.kind='spend' then t.settlement_total_amount else -t.settlement_total_amount end),0))
 into n,agg from public.settlement_demo_transactions dt join public.meal_transactions t on t.id=dt.transaction_id
 where dt.run_id=r.id;
 if r.settlement_id is not null then
   select * into s from public.settlements where id=r.settlement_id and merchant_id=p_merchant_id;
   select * into inv from public.tax_invoices where settlement_id=s.id and document_type='original';
 end if;
 return jsonb_build_object('seeded',true,'stage',case when r.settlement_id is null then 'seeded'
   when s.payment_status in ('paid','overpaid') then 'paid'
   when s.tax_invoice_status in ('issued','nts_sending','nts_accepted') then 'issued'
   when s.settlement_status='confirmed' and s.tax_invoice_status='requested' then 'confirmed'
   else s.settlement_status end,
   'run_id',r.id,'company_id',r.company_id,
   'company_name',(select name from public.companies where id=r.company_id),
   'period_ym',r.period_ym,'period_from',r.period_from,'period_to',r.period_to,
   'transaction_count',n,'aggregate',agg,'settlement_id',r.settlement_id,'options',options,
   'settlement',case when r.settlement_id is null then null else jsonb_strip_nulls(jsonb_build_object(
    'id',s.id,'period_ym',s.period_ym,'tx_count',s.tx_count,'supply_amount',s.supply_amount,
    'vat_amount',s.vat_amount,'total_amount',s.total_amount,'status',s.status,
    'settlement_status',s.settlement_status,'tax_invoice_status',s.tax_invoice_status,
    'payment_status',s.payment_status,'due_date',s.due_date,'paid_at',s.paid_at,
    'issued_at',inv.issued_at,'nts_status',inv.nts_status,
    'nts_confirm_num',nullif(btrim(inv.nts_confirm_num),''),
    'can_view_tax_invoice',s.tax_invoice_status in ('issued','nts_sending','nts_accepted'),
    'can_download_tax_invoice_pdf',s.tax_invoice_status in ('issued','nts_sending','nts_accepted'))) end);
end $$;

create or replace function public.settlement_demo_seed(
 p_actor_id uuid,p_merchant_id uuid,p_company_id uuid,p_period_ym text)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare r public.settlement_demo_runs%rowtype; period_start date; period_end date;
 admin_id uuid; users uuid[]; tx_id bigint; total int; supply int; tx_count int;
 i int; d date; user_offset int; c_status text; mc_status text;
begin
 perform public.settlement_demo_assert_actor(p_actor_id,p_merchant_id);
 if p_period_ym is null or p_period_ym !~ '^[0-9]{4}-(0[1-9]|1[0-2])$' then
   raise exception 'SETTLEMENT_INPUT_INVALID' using errcode='P0001'; end if;
 period_start:=to_date(p_period_ym||'-01','YYYY-MM-DD'); period_end:=(period_start+interval '1 month - 1 day')::date;
 if to_char(period_start,'YYYY-MM')<>p_period_ym or period_start>=date_trunc('month',current_date)::date
    or period_start<date_trunc('month',current_date)::date-interval '24 months' then
   raise exception 'SETTLEMENT_INPUT_INVALID' using errcode='P0001'; end if;
 perform pg_advisory_xact_lock(hashtextextended('settlement-demo:'||p_merchant_id::text,0));
 select * into r from public.settlement_demo_runs where merchant_id=p_merchant_id and is_current for update;
 if found then
   if r.company_id=p_company_id and r.period_ym=p_period_ym then return public.settlement_demo_state(p_actor_id,p_merchant_id); end if;
   raise exception 'SETTLEMENT_DEMO_STATE_CONFLICT' using errcode='P0001';
 end if;
 perform pg_advisory_xact_lock(pg_catalog.hashtext(p_merchant_id::text),pg_catalog.hashtext(p_company_id::text||':'||p_period_ym));
 select status into c_status from public.companies where id=p_company_id for key share;
 select status into mc_status from public.merchant_companies
   where merchant_id=p_merchant_id and company_id=p_company_id for key share;
 if c_status is distinct from 'active' or mc_status is distinct from 'active' then
   raise exception 'SETTLEMENT_DEMO_COMPANY_INELIGIBLE' using errcode='P0001'; end if;
 if not public.settlement_demo_company_profile_complete(p_company_id) then
   raise exception 'BUSINESS_PROFILE_INCOMPLETE' using errcode='P0001'; end if;
 select id into admin_id from public.app_users where company_id=p_company_id and role='company_admin' and status='active'
   order by pg_catalog.random() limit 1;
 if admin_id is null then raise exception 'SETTLEMENT_DEMO_COMPANY_ADMIN_REQUIRED' using errcode='P0001'; end if;
 select array_agg(id order by id) into users from public.app_users
   where company_id=p_company_id and role in ('employee','customer') and status='active';
 if coalesce(cardinality(users),0)=0 then raise exception 'SETTLEMENT_DEMO_EMPLOYEE_REQUIRED' using errcode='P0001'; end if;
 if exists(select 1 from public.settlements where merchant_id=p_merchant_id and company_id=p_company_id and period_ym=p_period_ym)
    or exists(select 1 from public.meal_transactions t where t.merchant_id=p_merchant_id and t.company_id=p_company_id
      and t.pay_type in ('ledger','subsidized') and t.kind in ('spend','refund','cancel')
      and t.created_at >= (period_start::timestamp at time zone 'Asia/Seoul')
      and t.created_at < ((period_end+1)::timestamp at time zone 'Asia/Seoul')) then
   raise exception 'DEMO_PERIOD_TRANSACTION_CONFLICT' using errcode='P0001'; end if;
 insert into public.settlement_demo_runs(merchant_id,company_id,company_actor_id,period_from,period_to,period_ym,created_by)
 values(p_merchant_id,p_company_id,admin_id,period_start,period_end,p_period_ym,p_actor_id) returning * into r;
 tx_count:=6+floor(pg_catalog.random()*7)::int;
 user_offset:=floor(pg_catalog.random()*cardinality(users))::int;
 for i in 1..tx_count loop
   select candidate_day into d from (select gs::date as candidate_day from generate_series(period_start,period_end,interval '1 day') gs
     where extract(isodow from gs)<6 order by pg_catalog.random() offset (i-1) %
       (select count(*) from generate_series(period_start,period_end,interval '1 day') x where extract(isodow from x)<6) limit 1) picked;
   total:=(array[8000,9000,10000,11000,12000,13000,14000,15000])[1+floor(pg_catalog.random()*8)::int];
   supply:=round(total::numeric/1.1)::int;
   insert into public.meal_transactions(user_id,company_id,merchant_id,amount,kind,tx_code,meal_window,
     flags,idempotency_key,product_name,product_price,pay_type,tax_type,supply_amount,vat_amount,total_amount,
     settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,created_at)
   values(users[1+((user_offset+i-1)%cardinality(users))],p_company_id,p_merchant_id,0,'spend',
     upper(substr(replace(r.id::text,'-',''),1,8))||lpad(i::text,2,'0'),'중식',jsonb_build_object('settlement_demo',true,'run_id',r.id),
     'settlement-demo:'||r.id||':'||i,'정산 데모 식사',total,'ledger','taxable',supply,total-supply,total,
     'taxable',supply,total-supply,total,(d+time '12:00') at time zone 'Asia/Seoul') returning id into tx_id;
   insert into public.settlement_demo_transactions(run_id,transaction_id) values(r.id,tx_id);
 end loop;
 return public.settlement_demo_state(p_actor_id,p_merchant_id);
end $$;

create or replace function public.settlement_demo_create(p_actor_id uuid,p_merchant_id uuid)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare r public.settlement_demo_runs%rowtype; s public.settlements%rowtype; result jsonb;
 qids bigint[]; dids bigint[]; qc int; dc int; qs bigint; qv bigint; qt bigint; ds bigint; dv bigint; dt bigint;
begin
 perform public.settlement_demo_assert_actor(p_actor_id,p_merchant_id);
 select * into r from public.settlement_demo_runs where merchant_id=p_merchant_id and is_current for update;
 if not found then raise exception 'SETTLEMENT_DEMO_NOT_SEEDED' using errcode='P0001'; end if;
 if r.settlement_id is not null then raise exception 'SETTLEMENT_DEMO_STATE_CONFLICT' using errcode='P0001'; end if;
 perform public.settlement_demo_validate_run(r.id);
 perform pg_advisory_xact_lock(pg_catalog.hashtext(p_merchant_id::text),pg_catalog.hashtext(r.company_id::text||':'||r.period_ym));
 select count(*),array_agg(t.id order by t.id),coalesce(sum(case when t.kind='spend' then t.settlement_supply_amount else -t.settlement_supply_amount end),0),
   coalesce(sum(case when t.kind='spend' then t.settlement_vat_amount else -t.settlement_vat_amount end),0),coalesce(sum(case when t.kind='spend' then t.settlement_total_amount else -t.settlement_total_amount end),0)
 into qc,qids,qs,qv,qt from public.meal_transactions t where t.merchant_id=p_merchant_id and t.company_id=r.company_id
   and t.pay_type in ('ledger','subsidized') and t.kind in ('spend','refund','cancel')
   and t.created_at >= (r.period_from::timestamp at time zone 'Asia/Seoul')
   and t.created_at < ((r.period_to+1)::timestamp at time zone 'Asia/Seoul');
 select count(*),array_agg(t.id order by t.id),coalesce(sum(case when t.kind='spend' then t.settlement_supply_amount else -t.settlement_supply_amount end),0),
   coalesce(sum(case when t.kind='spend' then t.settlement_vat_amount else -t.settlement_vat_amount end),0),coalesce(sum(case when t.kind='spend' then t.settlement_total_amount else -t.settlement_total_amount end),0)
 into dc,dids,ds,dv,dt from public.settlement_demo_transactions x join public.meal_transactions t on t.id=x.transaction_id where x.run_id=r.id;
 if row(qc,qids,qs,qv,qt) is distinct from row(dc,dids,ds,dv,dt) then
   raise exception 'DEMO_PERIOD_TRANSACTION_CONFLICT' using errcode='P0001'; end if;
 result:=public.create_merchant_settlement(p_merchant_id,r.company_id,r.period_from,r.period_to);
 -- Exact post-call membership/result verification makes any pollution or creator regression roll back.
 select count(*),array_agg(t.id order by t.id),coalesce(sum(case when t.kind='spend' then t.settlement_supply_amount else -t.settlement_supply_amount end),0),
   coalesce(sum(case when t.kind='spend' then t.settlement_vat_amount else -t.settlement_vat_amount end),0),coalesce(sum(case when t.kind='spend' then t.settlement_total_amount else -t.settlement_total_amount end),0)
 into qc,qids,qs,qv,qt from public.meal_transactions t where t.merchant_id=p_merchant_id and t.company_id=r.company_id
   and t.pay_type in ('ledger','subsidized') and t.kind in ('spend','refund','cancel')
   and t.created_at >= (r.period_from::timestamp at time zone 'Asia/Seoul') and t.created_at < ((r.period_to+1)::timestamp at time zone 'Asia/Seoul');
 if row(qc,qids,qs,qv,qt) is distinct from row(dc,dids,ds,dv,dt) then raise exception 'DEMO_PERIOD_TRANSACTION_CONFLICT' using errcode='P0001'; end if;
 select * into s from public.settlements where id=(result->>'id')::uuid;
 if not found or row(s.merchant_id,s.company_id,s.period_from,s.period_to,s.period_ym,s.tx_count,s.supply_amount,s.vat_amount,s.total_amount)
   is distinct from row(p_merchant_id,r.company_id,r.period_from,r.period_to,r.period_ym,dc,ds,dv,dt)
   or (result->>'merchant_id')::uuid is distinct from p_merchant_id or (result->>'company_id')::uuid is distinct from r.company_id
   or (result->>'tx_count')::int is distinct from dc or (result->>'total_amount')::bigint is distinct from dt then
   raise exception 'SETTLEMENT_DEMO_CREATE_RESULT_MISMATCH' using errcode='P0001'; end if;
 update public.settlement_demo_runs set settlement_id=s.id where id=r.id;
 return public.settlement_demo_state(p_actor_id,p_merchant_id);
end $$;

create or replace function public.settlement_demo_confirm(p_actor_id uuid,p_merchant_id uuid)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare r public.settlement_demo_runs%rowtype; s public.settlements%rowtype;
begin
 perform public.settlement_demo_assert_actor(p_actor_id,p_merchant_id);
 select * into r from public.settlement_demo_runs where merchant_id=p_merchant_id and is_current for update;
 if not found or r.settlement_id is null then raise exception 'SETTLEMENT_DEMO_NOT_CREATED' using errcode='P0001'; end if;
 perform public.settlement_demo_validate_run(r.id);
 if not public.settlement_demo_company_profile_complete(r.company_id) then raise exception 'BUSINESS_PROFILE_INCOMPLETE' using errcode='P0001'; end if;
 if not exists(select 1 from public.app_users where id=r.company_actor_id and company_id=r.company_id and role='company_admin' and status='active') then
   raise exception 'SETTLEMENT_DEMO_COMPANY_ADMIN_REQUIRED' using errcode='P0001'; end if;
 select * into s from public.settlements where id=r.settlement_id and merchant_id=p_merchant_id for update;
 if s.settlement_status<>'draft' or s.tax_invoice_status<>'not_requested' then raise exception 'SETTLEMENT_DEMO_STATE_CONFLICT' using errcode='P0001'; end if;
 perform public.merchant_send_settlement(p_actor_id,p_merchant_id,s.id);
 perform public.company_confirm_and_request_tax_invoice(r.company_actor_id,r.company_id,s.id);
 return public.settlement_demo_state(p_actor_id,p_merchant_id);
end $$;

create or replace function public.settlement_demo_assert_issue(p_actor_id uuid,p_merchant_id uuid)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare r public.settlement_demo_runs%rowtype; s public.settlements%rowtype;
begin
 perform public.settlement_demo_assert_actor(p_actor_id,p_merchant_id);
 select * into r from public.settlement_demo_runs where merchant_id=p_merchant_id and is_current;
 if not found or r.settlement_id is null then raise exception 'SETTLEMENT_DEMO_NOT_CREATED' using errcode='P0001'; end if;
 select * into s from public.settlements where id=r.settlement_id and merchant_id=p_merchant_id and company_id=r.company_id;
 if not found then raise exception 'SETTLEMENT_DEMO_MEMBERSHIP_INVALID' using errcode='P0001'; end if;
 if s.settlement_status<>'confirmed' or s.tax_invoice_status<>'requested' then raise exception 'SETTLEMENT_DEMO_STATE_CONFLICT' using errcode='P0001'; end if;
 return jsonb_build_object('settlement_id',s.id,'company_id',s.company_id,'total_amount',s.total_amount);
end $$;

create or replace function public.settlement_demo_mark_paid(p_actor_id uuid,p_merchant_id uuid)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare r public.settlement_demo_runs%rowtype; s public.settlements%rowtype; paid bigint;
begin
 perform public.settlement_demo_assert_actor(p_actor_id,p_merchant_id);
 select * into r from public.settlement_demo_runs where merchant_id=p_merchant_id and is_current for update;
 if not found or r.settlement_id is null then raise exception 'SETTLEMENT_DEMO_NOT_CREATED' using errcode='P0001'; end if;
 select * into s from public.settlements where id=r.settlement_id and merchant_id=p_merchant_id for update;
 if s.settlement_status<>'confirmed' or s.tax_invoice_status not in ('issued','nts_sending','nts_accepted') or s.payment_status<>'unpaid' then
   raise exception 'SETTLEMENT_DEMO_STATE_CONFLICT' using errcode='P0001'; end if;
 select coalesce(sum(amount),0) into paid from public.settlement_payments where settlement_id=s.id and confirmed_at is not null;
 if paid<>0 then raise exception 'SETTLEMENT_DEMO_STATE_CONFLICT' using errcode='P0001'; end if;
 perform public.merchant_mark_settlement_paid(p_actor_id,p_merchant_id,s.id,s.total_amount,'그린잇 정산 데모',
   clock_timestamp(),'test-only settlement demo','settlement-demo-paid:'||r.id);
 return public.settlement_demo_state(p_actor_id,p_merchant_id);
end $$;

create or replace function public.settlement_demo_reset(p_actor_id uuid,p_merchant_id uuid,p_idempotency_key text)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare r public.settlement_demo_runs%rowtype; s public.settlements%rowtype; old_id uuid; removable boolean:=false;
begin
 perform public.settlement_demo_assert_actor(p_actor_id,p_merchant_id);
 if p_idempotency_key is not null and length(p_idempotency_key) not between 1 and 200 then raise exception 'SETTLEMENT_INPUT_INVALID' using errcode='P0001'; end if;
 perform pg_advisory_xact_lock(hashtextextended('settlement-demo:'||p_merchant_id::text,0));
 if p_idempotency_key is not null and exists(select 1 from public.settlement_demo_reset_requests
      where merchant_id=p_merchant_id and idempotency_key=p_idempotency_key) then
   return jsonb_build_object('seeded',false,'stage','empty','options',
     public.settlement_demo_state(p_actor_id,p_merchant_id)->'options'); end if;
 select * into r from public.settlement_demo_runs where merchant_id=p_merchant_id and is_current for update;
 if found then
   old_id:=r.id; perform public.settlement_demo_validate_run(r.id);
   if r.settlement_id is null then removable:=true;
   else
     select * into s from public.settlements where id=r.settlement_id
       and merchant_id=r.merchant_id and company_id=r.company_id for update;
     removable:=found and s.settlement_status='draft' and s.tax_invoice_status='not_requested'
       and not exists(select 1 from public.tax_invoices where settlement_id=s.id)
       and not exists(select 1 from public.settlement_events where settlement_id=s.id)
       and not exists(select 1 from public.settlement_payments where settlement_id=s.id);
   end if;
   if removable then
     if r.settlement_id is not null then
       update public.settlement_demo_runs set settlement_id=null where id=r.id;
       delete from public.settlements where id=r.settlement_id and merchant_id=r.merchant_id and company_id=r.company_id;
     end if;
     delete from public.meal_transactions t using public.settlement_demo_transactions dt
       where dt.run_id=r.id and dt.transaction_id=t.id and t.merchant_id=r.merchant_id and t.company_id=r.company_id
         and t.flags->>'run_id'=r.id::text and t.flags->>'settlement_demo'='true';
     delete from public.settlement_demo_runs where id=r.id;
   else
     update public.settlement_demo_runs set is_current=false,archived_at=clock_timestamp() where id=r.id;
   end if;
 end if;
 if p_idempotency_key is not null then
   insert into public.settlement_demo_reset_requests(merchant_id,idempotency_key,reset_run_id)
   values(p_merchant_id,p_idempotency_key,old_id);
 end if;
 return public.settlement_demo_state(p_actor_id,p_merchant_id);
end $$;

create or replace function public.settlement_demo_reset(p_actor_id uuid,p_merchant_id uuid)
returns jsonb language sql security definer set search_path=pg_catalog,public as $$
 select public.settlement_demo_reset(p_actor_id,p_merchant_id,null)
$$;

revoke all on function public.settlement_demo_state(uuid,uuid) from public,anon,authenticated;
revoke all on function public.settlement_demo_seed(uuid,uuid,uuid,text) from public,anon,authenticated;
revoke all on function public.settlement_demo_create(uuid,uuid) from public,anon,authenticated;
revoke all on function public.settlement_demo_confirm(uuid,uuid) from public,anon,authenticated;
revoke all on function public.settlement_demo_assert_issue(uuid,uuid) from public,anon,authenticated;
revoke all on function public.settlement_demo_mark_paid(uuid,uuid) from public,anon,authenticated;
revoke all on function public.settlement_demo_reset(uuid,uuid) from public,anon,authenticated;
revoke all on function public.settlement_demo_reset(uuid,uuid,text) from public,anon,authenticated;
grant execute on function public.settlement_demo_state(uuid,uuid) to service_role;
grant execute on function public.settlement_demo_seed(uuid,uuid,uuid,text) to service_role;
grant execute on function public.settlement_demo_create(uuid,uuid) to service_role;
grant execute on function public.settlement_demo_confirm(uuid,uuid) to service_role;
grant execute on function public.settlement_demo_assert_issue(uuid,uuid) to service_role;
grant execute on function public.settlement_demo_mark_paid(uuid,uuid) to service_role;
grant execute on function public.settlement_demo_reset(uuid,uuid) to service_role;
grant execute on function public.settlement_demo_reset(uuid,uuid,text) to service_role;
notify pgrst,'reload schema';
