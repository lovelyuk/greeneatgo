begin;

-- 0073: critical data exposure and the transaction generator.
--
-- 1) merchants / company_merchants were readable by every authenticated user
--    (0002 policies + default Supabase grants). Anyone who signed up through the
--    public anon key could list all bank accounts, business numbers, owner
--    phones, qr_token and view_token. No client reads these tables directly; the
--    API uses service_role, so the policies are dropped and client grants revoked.
-- 2) meal_balances (0001) is a definer view over meal_transactions readable by
--    anon. 3) The 8-argument process_meal_pay stub (0003) was still executable by
--    anon/authenticated without validation.
-- 4) The development transaction generator stays available, but it can no longer
--    touch a month with real transactions: generation, the on-behalf company
--    confirmation and reset all require a purely generated month. Real-provider
--    tax invoice issuance of generated settlements was already blocked in the API.

drop policy if exists merchants_authenticated_read on public.merchants;
drop policy if exists company_merchants_authenticated_read on public.company_merchants;
revoke all on table public.merchants, public.company_merchants from anon, authenticated;

alter view public.meal_balances set (security_invoker = true);
revoke all on table public.meal_balances from anon, authenticated;

revoke all on function public.process_meal_pay(uuid,uuid,uuid,integer,text,text,jsonb,text)
  from public, anon, authenticated, service_role;

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
 -- 0073: never mix generated rows into a month that has real transactions.
 if exists(select 1 from public.meal_transactions t where t.merchant_id=p_merchant_id and t.company_id=p_company_id and not t.is_demo
   and t.created_at>=(start_date::timestamp at time zone 'Asia/Seoul') and t.created_at<((end_date+1)::timestamp at time zone 'Asia/Seoul'))
 then raise exception 'GENERATED_PERIOD_HAS_REAL_TRANSACTIONS' using errcode='P0001'; end if;
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

create or replace function public.generated_transactions_confirm(p_actor_id uuid,p_merchant_id uuid,p_company_id uuid,p_period_ym text)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare r public.generated_transaction_runs%rowtype;
begin
 perform public.generated_transactions_assert_actor(p_actor_id,p_merchant_id);
 perform pg_advisory_xact_lock(pg_catalog.hashtext(p_merchant_id::text),pg_catalog.hashtext(p_company_id::text||':'||p_period_ym));
 select * into r from public.generated_transaction_runs where merchant_id=p_merchant_id and company_id=p_company_id and period_ym=p_period_ym for update;
 if not found or r.settlement_id is null then raise exception 'SETTLEMENT_GENERATION_NOT_CREATED' using errcode='P0001'; end if;
 -- 0073: the on-behalf company confirmation is only for purely generated months.
 if exists(select 1 from public.meal_transactions t where t.merchant_id=p_merchant_id and t.company_id=p_company_id and not t.is_demo
   and t.created_at>=(r.period_from::timestamp at time zone 'Asia/Seoul') and t.created_at<((r.period_to+1)::timestamp at time zone 'Asia/Seoul')
   and not exists(select 1 from public.generated_transaction_members gm join public.generated_transaction_runs gr on gr.id=gm.run_id where gm.transaction_id=t.id and gr.id=r.id))
 then raise exception 'GENERATED_PERIOD_HAS_REAL_TRANSACTIONS' using errcode='P0001'; end if;
 perform public.merchant_send_settlement(p_actor_id,p_merchant_id,r.settlement_id);
 perform public.company_confirm_and_request_tax_invoice(r.company_actor_id,r.company_id,r.settlement_id);
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
 -- 0073: reset only removes a purely generated month (no real transactions, no real settlement).
 if exists(select 1 from public.meal_transactions t where t.merchant_id=p_merchant_id and t.company_id=p_company_id and not t.is_demo
   and t.created_at>=(r.period_from::timestamp at time zone 'Asia/Seoul') and t.created_at<((r.period_to+1)::timestamp at time zone 'Asia/Seoul')
   and not exists(select 1 from public.generated_transaction_members gm join public.generated_transaction_runs gr on gr.id=gm.run_id where gm.transaction_id=t.id and gr.id=r.id))
 then raise exception 'GENERATED_PERIOD_HAS_REAL_TRANSACTIONS' using errcode='P0001'; end if;
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
  if exists(select 1 from public.tax_invoices i
    join public.settlements s on s.id=i.settlement_id
    where i.settlement_id=any(sids) and (
      i.issue_attempt_token is not null
      or (i.issue_lease_expires_at is not null and i.issue_lease_expires_at>clock_timestamp())
      or i.reconciliation_required_at is not null
      or (i.issue_attempt_started_at is not null and i.issued_at is null and not (
        (i.popbill_status='issued' and s.tax_invoice_status in ('issued','nts_sending','nts_accepted'))
        or (i.popbill_status='failed' and s.tax_invoice_status='failed')))))
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

notify pgrst, 'reload schema';
commit;
