begin;

-- Keep the merchant's internal monthly draft in sync with every eligible company
-- transaction. Publication remains explicit: company reads still exclude draft,
-- calculating, and revising settlements until merchant_send_settlement is called.
create or replace function public.refresh_monthly_draft_after_meal_transaction()
returns trigger
language plpgsql security definer set search_path=pg_catalog,public as $$
declare
  v_period_from date;
  v_period_to date;
  current_status text;
  current_invoice_status text;
  v_count int;
  v_classified_count int;
  v_tax_type_count int;
begin
  if new.company_id is null
     or new.merchant_id is null
     or new.pay_type not in ('ledger','subsidized')
     or new.kind not in ('spend','refund','cancel')
     or new.is_demo
     or coalesce(new.flags,'{}'::jsonb) ? 'settlement_demo' then
    return new;
  end if;

  v_period_from := date_trunc('month', new.created_at at time zone 'Asia/Seoul')::date;
  v_period_to := (v_period_from + interval '1 month - 1 day')::date;

  -- Legacy demo runs own their month lock and deferred pollution checks. Let
  -- those checks reject a concurrent non-demo insert at COMMIT without making
  -- this immediate trigger wait behind the demo creator.
  if exists(select 1 from public.settlement_demo_runs r
    where r.merchant_id=new.merchant_id and r.company_id=new.company_id
      and r.period_ym=to_char(v_period_from,'YYYY-MM') and r.is_current) then
    return new;
  end if;

  if not exists(select 1 from public.merchants m where m.id=new.merchant_id and m.status='active')
     or not exists(select 1 from public.companies c where c.id=new.company_id and c.status='active')
     or not exists(select 1 from public.merchant_companies mc
       where mc.merchant_id=new.merchant_id and mc.company_id=new.company_id and mc.status='active') then
    return new;
  end if;

  select count(*),
    count(*) filter(where t.settlement_tax_type in ('taxable','tax_free')
      and t.settlement_supply_amount is not null
      and t.settlement_vat_amount is not null
      and t.settlement_total_amount is not null
      and t.settlement_supply_amount+t.settlement_vat_amount=t.settlement_total_amount),
    count(distinct t.settlement_tax_type) filter(where t.settlement_tax_type in ('taxable','tax_free'))
    into v_count,v_classified_count,v_tax_type_count
    from public.meal_transactions t
   where t.merchant_id=new.merchant_id and t.company_id=new.company_id
     and t.pay_type in ('ledger','subsidized') and t.kind in ('spend','refund','cancel')
     and t.created_at >= (v_period_from::timestamp at time zone 'Asia/Seoul')
     and t.created_at < ((v_period_to+1)::timestamp at time zone 'Asia/Seoul');

  if v_count<>v_classified_count or v_count=0 or v_tax_type_count<>1 then
    delete from public.settlements s
     where s.merchant_id=new.merchant_id and s.company_id=new.company_id
       and s.period_ym=to_char(v_period_from,'YYYY-MM') and not s.is_demo
       and s.settlement_status='draft' and s.tax_invoice_status='not_requested'
       and not exists(select 1 from public.settlement_events e where e.settlement_id=s.id)
       and not exists(select 1 from public.tax_invoices i where i.settlement_id=s.id)
       and not exists(select 1 from public.settlement_payments p where p.settlement_id=s.id);
    return new;
  end if;

  select s.settlement_status, s.tax_invoice_status
    into current_status, current_invoice_status
    from public.settlements s
   where s.merchant_id = new.merchant_id
     and s.company_id = new.company_id
     and s.period_ym = to_char(v_period_from, 'YYYY-MM')
     and not s.is_demo;

  -- Once sent, legal amounts are frozen. A later transaction must still succeed,
  -- but it cannot silently rewrite a settlement already visible to the company.
  if found and (current_status not in ('draft','calculating','revising')
                or current_invoice_status <> 'not_requested') then
    return new;
  end if;

  perform public.create_merchant_settlement(
    new.merchant_id, new.company_id, v_period_from, v_period_to
  );
  return new;
end $$;

revoke all on function public.refresh_monthly_draft_after_meal_transaction()
  from public, anon, authenticated, service_role;

drop trigger if exists trg_meal_transaction_refresh_monthly_draft
  on public.meal_transactions;
create trigger trg_meal_transaction_refresh_monthly_draft
after insert on public.meal_transactions
for each row execute function public.refresh_monthly_draft_after_meal_transaction();

create or replace function public.remove_empty_monthly_draft_after_meal_transaction_delete()
returns trigger
language plpgsql security definer set search_path=pg_catalog,public as $$
declare
  v_period_from date;
begin
  if old.company_id is null or old.merchant_id is null
     or old.pay_type not in ('ledger','subsidized')
     or old.kind not in ('spend','refund','cancel')
     or old.is_demo
     or coalesce(old.flags,'{}'::jsonb) ? 'settlement_demo' then
    return old;
  end if;
  v_period_from:=date_trunc('month',old.created_at at time zone 'Asia/Seoul')::date;
  if not exists(select 1 from public.meal_transactions t
    where t.merchant_id=old.merchant_id and t.company_id=old.company_id
      and t.pay_type in ('ledger','subsidized') and t.kind in ('spend','refund','cancel')
      and not t.is_demo and not (coalesce(t.flags,'{}'::jsonb) ? 'settlement_demo')
      and t.created_at >= (v_period_from::timestamp at time zone 'Asia/Seoul')
      and t.created_at < (((v_period_from+interval '1 month')::date)::timestamp at time zone 'Asia/Seoul')) then
    delete from public.settlements s
     where s.merchant_id=old.merchant_id and s.company_id=old.company_id
       and s.period_ym=to_char(v_period_from,'YYYY-MM') and not s.is_demo
       and s.settlement_status='draft' and s.tax_invoice_status='not_requested'
       and not exists(select 1 from public.settlement_events e where e.settlement_id=s.id)
       and not exists(select 1 from public.tax_invoices i where i.settlement_id=s.id)
       and not exists(select 1 from public.settlement_payments p where p.settlement_id=s.id);
  end if;
  return old;
end $$;

revoke all on function public.remove_empty_monthly_draft_after_meal_transaction_delete()
  from public,anon,authenticated,service_role;
drop trigger if exists trg_meal_transaction_remove_empty_monthly_draft
  on public.meal_transactions;
create trigger trg_meal_transaction_remove_empty_monthly_draft
after delete on public.meal_transactions
for each row execute function public.remove_empty_monthly_draft_after_meal_transaction_delete();

-- Backward-compatible generated-run attachment. Existing clients may still call
-- the old create endpoint, but new generation links the automatically-created
-- draft in the same transaction and returns stage=draft immediately.
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
 result:=public.create_merchant_settlement(p_merchant_id,p_company_id,r.period_from,r.period_to); sid:=(result->>'id')::uuid;
 if not exists(select 1 from public.settlements where id=sid and merchant_id=p_merchant_id and company_id=p_company_id
   and period_ym=p_period_ym and period_from=r.period_from and period_to=r.period_to and not is_demo
   and settlement_status in ('draft','calculating','revising') and tax_invoice_status='not_requested')
 then raise exception 'GENERATED_SETTLEMENT_RESULT_MISMATCH' using errcode='P0001'; end if;
 update public.generated_transaction_runs set settlement_id=sid where id=r.id;
 return public.generated_transactions_state(p_actor_id,p_merchant_id,p_company_id,p_period_ym);
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
 if found then return public.generated_transactions_create_settlement(p_actor_id,p_merchant_id,p_company_id,p_period_ym); end if;
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
 return public.generated_transactions_create_settlement(p_actor_id,p_merchant_id,p_company_id,p_period_ym);
end $$;

revoke all on function public.generated_transactions_create_settlement(uuid,uuid,uuid,text),
 public.generate_company_month_transactions(uuid,uuid,uuid,text)
 from public,anon,authenticated,service_role;
grant execute on function public.generated_transactions_create_settlement(uuid,uuid,uuid,text),
 public.generate_company_month_transactions(uuid,uuid,uuid,text)
 to service_role;

commit;
